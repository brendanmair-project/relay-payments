"""The only write paths for `payment_events` (ADR-0003): insert, and mark an event published.

There is deliberately no update or delete function. The database trigger enforces the same rule
(only `published_at` may be set, once, from null). The caller owns the transaction: REL-16 calls
`insert_event` in the same transaction as the state change, after locking the payment row to assign `seq`.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import PaymentEvent


def insert_event(
    session: Session,
    *,
    payment_id: uuid.UUID | str,
    seq: int,
    attempt_no: int,
    type: str,  # noqa: A002 - the column is named `type`
    correlation_id: str,
    from_status: str | None = None,
    to_status: str | None = None,
    processor: str | None = None,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
) -> int:
    """Append one event and return its global id. Does not commit."""
    values: dict[str, Any] = {
        "payment_id": uuid.UUID(str(payment_id)),
        "seq": seq,
        "attempt_no": attempt_no,
        "type": type,
        "from_status": from_status,
        "to_status": to_status,
        "processor": processor,
        "reason": reason,
        "correlation_id": correlation_id,
    }
    if data is not None:
        values["data"] = data
    result = session.execute(sa.insert(PaymentEvent).values(**values).returning(PaymentEvent.id))
    return int(result.scalar_one())


def mark_published(session: Session, event_ids: Sequence[int]) -> int:
    """Set `published_at` on events that are still unpublished (REL-20); return how many changed."""
    if not event_ids:
        return 0
    result = session.execute(
        sa.update(PaymentEvent)
        .where(PaymentEvent.id.in_(list(event_ids)), PaymentEvent.published_at.is_(None))
        .values(published_at=sa.func.now())
    )
    return int(getattr(result, "rowcount", 0))
