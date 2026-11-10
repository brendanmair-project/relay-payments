"""Idempotency key cleanup (REL-47, data-model.md "idempotency_keys", ADR-0008).

A row is deleted only when `expires_at < now`, so a key is never removed inside its 24 hours. As an extra guard, an
`in_progress` row whose lease is still valid is kept even when expired: its holder may still complete it, and
`create_once` would otherwise answer 409. Only key rows go; `payment_id` points at payments, which are never touched.

One call removes at most one batch, oldest `expires_at` first (the `(expires_at)` index). `FOR UPDATE SKIP LOCKED`
makes a second cleaner (or a request taking the key over) skip rows another transaction holds, so no row goes twice.
"""

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

_DELETE_BATCH = sa.text(
    """
    DELETE FROM idempotency_keys WHERE key IN (
        SELECT key FROM idempotency_keys
        WHERE expires_at < :now AND NOT (state = 'in_progress' AND lease_expires_at >= :now)
        ORDER BY expires_at
        LIMIT :batch_size
        FOR UPDATE SKIP LOCKED
    )
    """
)


def cleanup_expired_keys(factory: sessionmaker[Session], *, now: datetime, batch_size: int) -> int:
    """Delete one batch of expired keys and return how many rows were removed."""
    with factory.begin() as session:
        result = session.execute(_DELETE_BATCH, {"now": now, "batch_size": batch_size})
        return int(result.rowcount)  # type: ignore[attr-defined]
