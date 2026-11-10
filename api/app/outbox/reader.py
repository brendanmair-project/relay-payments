"""Outbox reader: unpublished events in `id` order, locked so two publishers never take the same row."""

import uuid
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import PaymentEvent


@dataclass(frozen=True)
class OutboxEvent:
    id: int
    payment_id: uuid.UUID
    seq: int
    attempt_no: int
    type: str
    correlation_id: str
    occurred_at: datetime


def fetch_unpublished(session: Session, limit: int) -> list[OutboxEvent]:
    """Lock and return up to `limit` unpublished events, lowest id first.

    `FOR UPDATE SKIP LOCKED` skips rows another publisher holds. The locks last until the caller's transaction ends,
    so the caller marks the events in the same transaction (the partial index on unpublished ids serves the scan).
    """
    rows = session.execute(
        sa.select(
            PaymentEvent.id,
            PaymentEvent.payment_id,
            PaymentEvent.seq,
            PaymentEvent.attempt_no,
            PaymentEvent.type,
            PaymentEvent.correlation_id,
            PaymentEvent.occurred_at,
        )
        .where(PaymentEvent.published_at.is_(None))
        .order_by(PaymentEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return [OutboxEvent(*row) for row in rows]
