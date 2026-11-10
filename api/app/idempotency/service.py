"""Idempotency keys for POST /payments: claim, lease, takeover and completion (data-model.md "Create flow").

Claim is a short transaction of its own, so a concurrent request sees `in_progress` and gets 409 (ADR-0008 decision 6).
Creation then runs in one transaction that also completes the key, guarded by the lease token: a stalled first request
that wakes after a takeover updates zero rows, rolls back and creates no payment.
"""

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine, Row
from sqlalchemy.orm import Session

from app.db.models import IdempotencyKey, Payment
from app.errors import ApiError
from app.services.transitions import create_payment

IN_PROGRESS = "in_progress"
COMPLETED = "completed"
MAX_CLAIM_ROUNDS = 5  # re-reads after losing a race; each round needs another request to have just changed the row


@dataclass(frozen=True)
class Claimed:
    """This request owns the key; `token` must be presented to complete it."""

    token: uuid.UUID


@dataclass(frozen=True)
class Replay:
    """The key is completed with the same body: answer with the stored first response."""

    status: int
    body: dict[str, Any]


def request_hash(body: dict[str, Any]) -> str:
    """SHA-256 hex of the canonical JSON: keys sorted, no insignificant whitespace."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _in_progress() -> ApiError:
    return ApiError(
        409,
        "idempotency_request_in_progress",
        "a request with this Idempotency-Key is still being processed",
        headers={"Retry-After": "1"},
    )


def _reused() -> ApiError:
    return ApiError(409, "idempotency_key_reused", "this Idempotency-Key was used with a different request body")


def _read(conn: Connection, key: str) -> Row[Any] | None:
    return conn.execute(sa.select(IdempotencyKey).where(IdempotencyKey.key == key)).one_or_none()


def claim(
    engine: Engine,
    key: str,
    digest: str,
    *,
    ttl_hours: int,
    lease_seconds: int,
    now: datetime | None = None,
) -> Claimed | Replay:
    """Claim `key` for a request with body hash `digest`, or return the stored response, or raise the 409."""
    for _ in range(MAX_CLAIM_ROUNDS):
        moment = now or datetime.now(UTC)
        token = uuid.uuid4()
        fresh = {
            "request_hash": digest,
            "state": IN_PROGRESS,
            "lease_token": token,
            "lease_expires_at": moment + timedelta(seconds=lease_seconds),
            "created_at": moment,
            "expires_at": moment + timedelta(hours=ttl_hours),
        }
        with engine.begin() as conn:
            inserted = conn.execute(
                pg_insert(IdempotencyKey)
                .values(key=key, **fresh)
                .on_conflict_do_nothing(index_elements=[IdempotencyKey.key])
                .returning(IdempotencyKey.key)
            ).first()
            if inserted is not None:
                return Claimed(token)
            row = _read(conn, key)
            if row is None:  # deleted after the conflict (cleanup job): insert again
                continue
            if moment < row.expires_at:
                if row.request_hash != digest:
                    raise _reused()
                if row.state == COMPLETED:
                    return Replay(int(row.response_status), dict(row.response_body))
                if moment < row.lease_expires_at:
                    raise _in_progress()
            # Past the 24 hours, or an in-progress key with an expired lease: take it over. The token read above
            # must still be current; zero rows means another request won, so decide again from a fresh read.
            taken = conn.execute(
                sa.update(IdempotencyKey)
                .where(IdempotencyKey.key == key, IdempotencyKey.lease_token == row.lease_token)
                .values(**fresh, payment_id=None, response_status=None, response_body=sa.null())
            )
            if taken.rowcount == 1:
                return Claimed(token)
    raise _in_progress()


def create_once(
    engine: Engine,
    key: str,
    token: uuid.UUID,
    *,
    fields: dict[str, Any],
    correlation_id: str,
    render: Callable[[Payment], dict[str, Any]],
) -> dict[str, Any]:
    """Insert the payment and its `payment.received` event and complete the key, in one transaction."""
    with Session(engine) as session, session.begin():
        payment_id = create_payment(session, correlation_id=correlation_id, **fields)
        payment = session.get_one(Payment, payment_id)
        body = render(payment)
        completed = session.execute(
            sa.update(IdempotencyKey)
            .where(
                IdempotencyKey.key == key,
                IdempotencyKey.state == IN_PROGRESS,
                IdempotencyKey.lease_token == token,
            )
            .values(state=COMPLETED, payment_id=payment_id, response_status=201, response_body=body)
        )
        if completed.rowcount != 1:  # type: ignore[attr-defined]
            # The lease was taken over: raising rolls back the payment and the event.
            raise _in_progress()
    return body
