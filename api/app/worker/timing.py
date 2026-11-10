"""Creation-to-final timing (REL-57): observed where a payment becomes final, in the worker and in the sweeper."""

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Payment
from app.metrics import PAYMENT_PROCESSING


def observe_processing(session: Session, payment_id: uuid.UUID, processor: str | None, outcome: str) -> None:
    """Record `final_at - created_at` of a payment that was just made final in this transaction.

    Both stamps come from the database clock, so the figure is the same on every host. A payment without a handling
    processor is skipped: the series is labelled by processor.
    """
    if processor is None:
        return
    seconds = session.scalar(
        sa.select(sa.func.extract("epoch", Payment.final_at - Payment.created_at)).where(Payment.id == payment_id)
    )
    if seconds is not None:
        PAYMENT_PROCESSING.labels(processor, outcome).observe(max(float(seconds), 0.0))
