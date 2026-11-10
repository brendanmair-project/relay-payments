"""Database operations of the webhooks feature: subscriptions, fan-out, claiming, results, retention (ADR-0015).

Every function opens its own short transaction. Nothing here is called with a transaction open around an HTTP call: the
send loop claims rows (a short transaction), posts with no transaction, then records the result (another).
"""

import json
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import iso_utc
from app.db.models import (
    Payment,
    PaymentEvent,
    WebhookConsumerState,
    WebhookDelivery,
    WebhookDeliveryAttempt,
    WebhookSubscription,
)
from app.metrics import WEBHOOK_DELIVERIES
from app.webhooks.config import WebhookSettings, backoff_seconds
from app.webhooks.types import MAX_ATTEMPTS, WEBHOOK_EVENT_TYPES

DELIVERED, RETRIED, FAILED = "delivered", "retried", "failed"
ONE_SECOND: sa.ColumnClause[Any] = sa.literal_column("interval '1 second'")
ONE_DAY: sa.ColumnClause[Any] = sa.literal_column("interval '1 day'")


@dataclass(frozen=True)
class Claimed:
    """A delivery taken by the send loop, with everything needed to post it (no session is kept)."""

    id: int
    attempt: int
    event_id: int
    event_type: str
    subscription_id: uuid.UUID
    url: str
    secret: str
    active: bool
    body: bytes | None  # None when the event row no longer exists


def new_secret() -> str:
    """A random signing secret chosen by Relay, never by the subscriber (ADR-0015, item 5)."""
    return secrets.token_urlsafe(32)


def create_subscription(session: Session, url: str, event_types: list[str]) -> WebhookSubscription:
    """Insert an active subscription with a new secret; the caller commits. Repeated types are stored once."""
    row = WebhookSubscription(
        id=uuid.uuid4(), url=url, event_types=list(dict.fromkeys(event_types)), secret=new_secret(), active=True
    )
    session.add(row)
    session.flush()
    session.refresh(row)
    return row


def fan_out(factory: sessionmaker[Session], event_id: int) -> int:
    """Store one pending delivery per active subscription of the event's type, with the bookkeeping, in one transaction.

    Returns how many deliveries were created. Anything but a lifecycle event creates none. The unique key on
    `(subscription_id, event_id)` makes a duplicate or redelivered stream entry a no-op; the bookkeeping keeps the
    highest event id seen (it is never used to skip an entry, because the stream is not strictly ordered).
    """
    with factory.begin() as session:
        event = session.get(PaymentEvent, event_id)
        if event is None or event.type not in WEBHOOK_EVENT_TYPES:
            return 0
        subscriptions = session.scalars(
            sa.select(WebhookSubscription.id).where(
                WebhookSubscription.active.is_(True), WebhookSubscription.event_types.contains([event.type])
            )
        ).all()
        created = 0
        if subscriptions:
            result = session.execute(
                insert(WebhookDelivery)
                .values(
                    [{"subscription_id": sid, "event_id": event_id, "event_type": event.type} for sid in subscriptions]
                )
                .on_conflict_do_nothing(index_elements=[WebhookDelivery.subscription_id, WebhookDelivery.event_id])
                .returning(WebhookDelivery.id)
            )
            created = len(result.all())
        state = insert(WebhookConsumerState).values(id=1, last_event_id=event_id)
        session.execute(
            state.on_conflict_do_update(
                index_elements=[WebhookConsumerState.id],
                set_={
                    "last_event_id": sa.func.greatest(WebhookConsumerState.last_event_id, state.excluded.last_event_id)
                },
            )
        )
    return created


def _body(event_id: int, type_: str, occurred_at: Any, payment: Payment, to_status: str | None) -> bytes:
    """The JSON message: never the payment description (ADR-0015, item 2)."""
    message = {
        "id": event_id,
        "type": type_,
        "created_at": iso_utc(occurred_at),
        "data": {
            "payment_id": str(payment.id),
            "status": to_status or payment.status,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
        },
    }
    return json.dumps(message, separators=(",", ":")).encode()


def claim_due(factory: sessionmaker[Session], limit: int, lease_seconds: float) -> list[Claimed]:
    """Take up to `limit` due pending deliveries, oldest first, and push their next attempt out by the lease.

    The rows are picked with `FOR UPDATE SKIP LOCKED`, so two senders never take the same one. The lease replaces a
    long lock: the transaction ends here, and a sender that dies before recording a result simply finds the delivery
    due again after the lease (at-least-once; subscribers drop repeats by `Relay-Event-Id`).
    """
    due = (
        sa.select(WebhookDelivery.id)
        .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= sa.func.now())
        .order_by(WebhookDelivery.next_attempt_at, WebhookDelivery.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    with factory.begin() as session:
        ids = session.scalars(
            sa.update(WebhookDelivery)
            .where(WebhookDelivery.id.in_(due))
            .values(next_attempt_at=sa.func.now() + ONE_SECOND * sa.cast(lease_seconds, sa.Float))
            .returning(WebhookDelivery.id)
        ).all()
        if not ids:
            return []
        rows = session.execute(
            sa.select(WebhookDelivery, WebhookSubscription, PaymentEvent, Payment)
            .join(WebhookSubscription, WebhookSubscription.id == WebhookDelivery.subscription_id)
            .outerjoin(PaymentEvent, PaymentEvent.id == WebhookDelivery.event_id)
            .outerjoin(Payment, Payment.id == PaymentEvent.payment_id)
            .where(WebhookDelivery.id.in_(ids))
            .order_by(WebhookDelivery.id)
        ).all()
        return [
            Claimed(
                id=delivery.id,
                attempt=delivery.attempt,
                event_id=delivery.event_id,
                event_type=delivery.event_type,
                subscription_id=subscription.id,
                url=subscription.url,
                secret=subscription.secret,
                active=subscription.active,
                body=None
                if event is None or payment is None
                else _body(event.id, delivery.event_type, event.occurred_at, payment, event.to_status),
            )
            for delivery, subscription, event, payment in rows
        ]


def record_attempt(
    factory: sessionmaker[Session],
    claimed: Claimed,
    status_code: int | None,
    error: str | None,
    settings: WebhookSettings,
    duration_ms: int = 0,
) -> str:
    """Record the answer of one attempt and return its outcome: `delivered`, `retried` or `failed`.

    2xx is delivered. Anything else (another status, a timeout, a connection error) counts the attempt, then either
    schedules the next one by exponential backoff or, at the 8th, gives up. The metric is counted after the commit.
    """
    attempt = claimed.attempt + 1
    values: dict[str, Any] = {
        "attempt": attempt,
        "last_status_code": status_code,
        "updated_at": sa.func.now(),
    }
    if status_code is not None and 200 <= status_code < 300:
        outcome = DELIVERED
        values |= {"status": "delivered", "last_error": None}
    else:
        values["last_error"] = error or f"HTTP {status_code}"
        if attempt >= MAX_ATTEMPTS:
            outcome = FAILED
            values["status"] = "failed"
        else:
            outcome = RETRIED
            delay = backoff_seconds(attempt, settings)
            values["next_attempt_at"] = sa.func.now() + ONE_SECOND * sa.cast(delay, sa.Float)
    with factory.begin() as session:
        result = session.execute(
            sa.update(WebhookDelivery)
            .where(WebhookDelivery.id == claimed.id, WebhookDelivery.status == "pending")
            .values(**values)
        )
        changed = int(getattr(result, "rowcount", 0))
        if changed:
            _log_attempt(session, claimed.id, attempt, status_code, values.get("last_error"), duration_ms)
    if changed:
        WEBHOOK_DELIVERIES.labels(outcome).inc()
    return outcome


def fail_without_request(factory: sessionmaker[Session], claimed: Claimed, reason: str) -> None:
    """Mark a delivery failed with a reason of ours (for example `target_not_allowed`) when no request was made.

    It still counts and records one attempt (no status code, duration 0), so the log shows why nothing was sent.
    """
    with factory.begin() as session:
        result = session.execute(
            sa.update(WebhookDelivery)
            .where(WebhookDelivery.id == claimed.id, WebhookDelivery.status == "pending")
            .values(
                status="failed",
                attempt=claimed.attempt + 1,
                last_error=reason,
                last_status_code=None,
                updated_at=sa.func.now(),
            )
        )
        changed = int(getattr(result, "rowcount", 0))
        if changed:
            _log_attempt(session, claimed.id, claimed.attempt + 1, None, reason, 0)
    if changed:
        WEBHOOK_DELIVERIES.labels(FAILED).inc()


def cleanup(factory: sessionmaker[Session], retention_days: int) -> int:
    """Delete delivered and failed rows last updated more than `retention_days` ago; pending rows are never deleted."""
    with factory.begin() as session:
        result = session.execute(
            sa.delete(WebhookDelivery).where(
                WebhookDelivery.status.in_(("delivered", "failed")),
                WebhookDelivery.updated_at < sa.func.now() - ONE_DAY * sa.cast(retention_days, sa.Float),
            )
        )
        return int(getattr(result, "rowcount", 0))


def count_pending(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return int(
            session.scalar(
                sa.select(sa.func.count()).select_from(WebhookDelivery).where(WebhookDelivery.status == "pending")
            )
            or 0
        )


def _log_attempt(
    session: Session, delivery_id: int, attempt: int, status_code: int | None, error: str | None, duration_ms: int
) -> None:
    """The per-attempt log row, written in the transaction that records the delivery's result."""
    session.add(
        WebhookDeliveryAttempt(
            delivery_id=delivery_id,
            attempt=attempt,
            status_code=status_code,
            error=error,
            duration_ms=max(duration_ms, 0),
        )
    )
