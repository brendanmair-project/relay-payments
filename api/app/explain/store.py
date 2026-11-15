"""Generate and store explanations (REL-25.7, ADR-0009, ADR-0012).

The model call runs with no database transaction open: the snapshot is read and closed, the explanation is
generated, then one short transaction inserts the row and, only when a row was inserted, writes `payment.explained`
through the transition service. The partial unique index plus `ON CONFLICT DO NOTHING` keeps the automatic
(`final_failure`) explanation to one per payment, so a redelivered `payment.final` creates nothing.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import iso_utc
from app.core.correlation import get_correlation_id
from app.db.models import Payment, PaymentEvent, PaymentExplanation
from app.domain.reasons import EventType
from app.explain.generate import Generated, generate_explanation
from app.explain.model import ModelClient
from app.explain.rules import ExplainEvent
from app.services.transitions import PaymentNotFoundError, append_event

UNAVAILABLE_REASONS = ("model_timeout", "model_error", "citation_check_failed")
TRIGGERS = ("final_failure", "on_request", "regenerate")


class PaymentNotFinalError(Exception):
    """The payment has not reached a final state, so there is nothing to explain yet."""


@dataclass(frozen=True)
class Snapshot:
    events: list[ExplainEvent]
    amount_minor: int
    currency: str
    final_event_at: datetime


@dataclass(frozen=True)
class StoredExplanation:
    id: int
    payment_id: uuid.UUID
    source: str
    model: str | None
    text: str
    cited_event_seqs: tuple[int, ...]
    trigger: str
    fallback_reason: str | None
    final_event_at: datetime
    generated_at: datetime
    attempted_model: str | None = None
    model_cause: str | None = None
    rules_cause: str | None = None
    generation_ms: int | None = None
    inputs: dict[str, Any] | None = None

    @property
    def cross_check(self) -> str | None:
        """How the model's answer and the rules compared (REL-63); None when a pre-REL-63 row cannot tell."""
        if self.source == "model":
            return "agreed"
        if self.fallback_reason == "cause_mismatch":
            return "disagreed_rules_used"
        if self.attempted_model is not None or self.fallback_reason in UNAVAILABLE_REASONS:
            return "model_unavailable"
        if self.inputs is not None:
            return "rules_only"  # stored with details, but no model was asked
        return None  # an old model_unreachable row: no model configured, or one that did not answer

    @classmethod
    def of(cls, row: PaymentExplanation) -> "StoredExplanation":
        return cls(
            row.id,
            row.payment_id,
            row.source,
            row.model,
            row.text,
            tuple(row.cited_event_seqs),
            row.trigger,
            row.fallback_reason,
            row.final_event_at,
            row.generated_at,
            row.attempted_model,
            row.model_cause,
            row.rules_cause,
            row.generation_ms,
            row.inputs,
        )


def read_snapshot(factory: sessionmaker[Session], payment_id: uuid.UUID) -> Snapshot:
    """The payment's own timeline, read and released before any model call."""
    with factory() as session:
        payment = session.get(Payment, payment_id)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        if not payment.is_final:
            raise PaymentNotFinalError(str(payment_id))
        rows = session.scalars(
            sa.select(PaymentEvent).where(PaymentEvent.payment_id == payment_id).order_by(PaymentEvent.seq)
        ).all()
        events = [
            ExplainEvent(
                seq=e.seq,
                type=e.type,
                attempt_no=e.attempt_no,
                processor=e.processor,
                reason=e.reason,
                data=e.data,
                to_status=e.to_status,
                occurred_at=iso_utc(e.occurred_at),
            )
            for e in rows
        ]
        finals = [e.occurred_at for e in rows if e.type == EventType.PAYMENT_FINAL.value]
        return Snapshot(
            events,
            payment.amount_minor,
            payment.currency,
            finals[-1] if finals else payment.final_at or rows[-1].occurred_at,
        )


def latest_explanation(session: Session, payment_id: uuid.UUID) -> StoredExplanation | None:
    row = session.scalars(
        sa.select(PaymentExplanation)
        .where(PaymentExplanation.payment_id == payment_id)
        .order_by(PaymentExplanation.generated_at.desc(), PaymentExplanation.id.desc())
        .limit(1)
    ).first()
    return StoredExplanation.of(row) if row else None


def insert_explanation(
    factory: sessionmaker[Session],
    payment_id: uuid.UUID,
    trigger: str,
    generated: Generated,
    snapshot: Snapshot,
    correlation_id: str | None = None,
) -> StoredExplanation | None:
    """Insert the row and its `payment.explained` event in one transaction; None when the insert conflicted."""
    cid = correlation_id or get_correlation_id() or str(uuid.uuid4())
    statement = (
        pg_insert(PaymentExplanation)
        .values(
            payment_id=payment_id,
            source=generated.source,
            model=generated.model,
            text=generated.text,
            cited_event_seqs=list(generated.cited_event_seqs),
            trigger=trigger,
            fallback_reason=generated.fallback_reason,
            final_event_at=snapshot.final_event_at,
            generated_at=sa.func.clock_timestamp(),
            attempted_model=generated.attempted_model,
            model_cause=generated.model_cause,
            rules_cause=generated.rules_cause,
            generation_ms=generated.generation_ms,
            inputs=generated.inputs,
        )
        .on_conflict_do_nothing()
        .returning(PaymentExplanation)
    )
    with factory.begin() as session:
        row = session.scalars(statement).first()
        if row is None:
            return None
        append_event(
            session,
            payment_id,
            EventType.PAYMENT_EXPLAINED,
            data={"explanation_id": row.id, "source": row.source, "trigger": trigger},
            correlation_id=cid,
        )
        return StoredExplanation.of(row)


def explain_payment(
    factory: sessionmaker[Session],
    payment_id: uuid.UUID,
    trigger: str,
    model: ModelClient | None,
    correlation_id: str | None = None,
) -> StoredExplanation | None:
    """Explain a final payment and store the result.

    Raises PaymentNotFoundError or PaymentNotFinalError. Returns None when an automatic (`final_failure`)
    explanation already exists: nothing is generated or written then.
    """
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")
    snapshot = read_snapshot(factory, payment_id)
    if trigger == "final_failure":
        with factory() as session:
            exists = session.scalar(
                sa.select(PaymentExplanation.id).where(
                    PaymentExplanation.payment_id == payment_id, PaymentExplanation.trigger == "final_failure"
                )
            )
        if exists is not None:
            return None
    generated = generate_explanation(
        snapshot.events, amount_minor=snapshot.amount_minor, currency=snapshot.currency, model=model
    )
    return insert_explanation(factory, payment_id, trigger, generated, snapshot, correlation_id)
