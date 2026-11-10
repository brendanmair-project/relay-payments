"""Helpers of the webhook tests: subscriptions and events written straight to the database."""

import secrets
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import bind_correlation_id
from app.db.models import PaymentEvent
from app.services.transitions import create_payment
from app.webhooks.store import create_subscription

Factory = sessionmaker[Session]
SENTINEL = "relay-test-sentinel-description"
HOOK_URL = "http://hooks.test/inbox"
# Event types the table requires a processor for (ck_payment_events_processor_required).
NEEDS_PROCESSOR = {
    "payment.routed",
    "payment.failed",
    "attempt.authorize_result",
    "attempt.capture_result",
    "attempt.late_result",
}


def subscribe(factory: Factory, types: list[str], url: str = HOOK_URL) -> tuple[uuid.UUID, str]:
    """A subscription made directly in the database; returns its id and secret."""
    with factory.begin() as session:
        row = create_subscription(session, url, types)
        return row.id, row.secret


def make_event(
    factory: Factory, type_: str, to_status: str | None = None, amount_minor: int = 1250
) -> tuple[uuid.UUID, int]:
    """A throwaway payment (with a sentinel description) and one event of `type_`: its payment id and event id."""
    with bind_correlation_id("corr-test"), factory.begin() as session:
        pid = create_payment(session, amount_minor=amount_minor, currency="EUR", description=SENTINEL)
        event_id = session.execute(
            sa.insert(PaymentEvent)
            .values(
                payment_id=pid,
                seq=2,
                attempt_no=0,
                type=type_,
                to_status=to_status,
                processor="A" if type_ in NEEDS_PROCESSOR else None,
                correlation_id="seed",
                data={},
            )
            .returning(PaymentEvent.id)
        ).scalar_one()
    return pid, int(event_id)


def random_secret() -> str:
    return secrets.token_urlsafe(24)


def deliveries(factory: Factory) -> list[dict[str, object]]:
    with factory() as session:
        rows = session.execute(sa.text("SELECT * FROM webhook_deliveries ORDER BY id")).mappings().all()
    return [dict(r) for r in rows]
