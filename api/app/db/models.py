"""SQLAlchemy models for docs/architecture/data-model.md.

The Alembic migration hard-codes its DDL and never imports this module; the tests compare the two.
Updates to `PaymentEvent` rows go through `app.db.events` only (ADR-0003): there is no update or delete helper.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.lifecycle import PaymentState
from app.domain.money import CURRENCY_DIGITS
from app.domain.reasons import REASONS_BY_EVENT_TYPE, EventType
from app.webhooks.types import DELIVERY_STATUSES, MAX_ATTEMPTS, WEBHOOK_EVENT_TYPES


def _in_list(values: list[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


STATUSES = [s.value for s in PaymentState]
CURRENCIES = list(CURRENCY_DIGITS)
EVENT_TYPES = [t.value for t in EventType]
# Distinct reason values in first-seen order; the shared enum in code decides which fits which event type.
REASONS = list(dict.fromkeys(m.value for enum in REASONS_BY_EVENT_TYPE.values() if enum for m in enum))
# Event types that must name a processor: processor health counts by it.
PROCESSOR_EVENT_TYPES = [
    EventType.PAYMENT_ROUTED.value,
    EventType.PAYMENT_FAILED.value,
    EventType.ATTEMPT_AUTHORIZE_RESULT.value,
    EventType.ATTEMPT_CAPTURE_RESULT.value,
    EventType.ATTEMPT_LATE_RESULT.value,
]

TIMESTAMPTZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(CHAR(3))
    description: Mapped[str | None] = mapped_column(String(200))
    reference: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(Text)
    processor: Mapped[str | None] = mapped_column(CHAR(1))
    attempt_no: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    is_final: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    correlation_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    status_changed_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    last_driven_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    final_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)

    __table_args__ = (
        CheckConstraint("amount_minor BETWEEN 1 AND 1000000000000", name="ck_payments_amount_range"),
        CheckConstraint(f"currency IN ({_in_list(CURRENCIES)})", name="ck_payments_currency"),
        CheckConstraint("reference ~ '^[A-Za-z0-9._-]{1,64}$'", name="ck_payments_reference"),
        CheckConstraint(f"status IN ({_in_list(STATUSES)})", name="ck_payments_status"),
        CheckConstraint("processor IN ('A','B')", name="ck_payments_processor"),
        CheckConstraint("attempt_no BETWEEN 0 AND 2", name="ck_payments_attempt_no"),
        CheckConstraint("(attempt_no = 0) = (status = 'received')", name="ck_payments_received_attempt_zero"),
        CheckConstraint("NOT is_final OR status IN ('captured','declined','failed')", name="ck_payments_final_status"),
        CheckConstraint("(final_at IS NULL) = (NOT is_final)", name="ck_payments_final_at"),
        CheckConstraint("(processor IS NULL) = (attempt_no = 0)", name="ck_payments_processor_attempt"),
        Index("ix_payments_status_processor_created_at", "status", "processor", "created_at"),
        Index("ix_payments_status_status_changed_at", "status", "status_changed_at"),
        Index("ix_payments_created_at_id", created_at.desc(), id.desc()),
    )


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payments.id"))
    seq: Mapped[int] = mapped_column(Integer)
    attempt_no: Mapped[int] = mapped_column(SmallInteger)
    type: Mapped[str] = mapped_column(Text)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    processor: Mapped[str | None] = mapped_column(CHAR(1))
    reason: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    correlation_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)

    __table_args__ = (
        UniqueConstraint("payment_id", "seq", name="uq_payment_events_payment_id_seq"),
        CheckConstraint("attempt_no BETWEEN 0 AND 2", name="ck_payment_events_attempt_no"),
        CheckConstraint(f"type IN ({_in_list(EVENT_TYPES)})", name="ck_payment_events_type"),
        CheckConstraint("to_status IS NOT NULL OR from_status IS NULL", name="ck_payment_events_from_needs_to"),
        CheckConstraint("processor IN ('A','B')", name="ck_payment_events_processor"),
        CheckConstraint(
            f"type NOT IN ({_in_list(PROCESSOR_EVENT_TYPES)}) OR processor IS NOT NULL",
            name="ck_payment_events_processor_required",
        ),
        CheckConstraint(f"reason IS NULL OR reason IN ({_in_list(REASONS)})", name="ck_payment_events_reason"),
        Index("ix_payment_events_type_processor_occurred_at", "type", "processor", "occurred_at"),
        Index("ix_payment_events_unpublished", "id", postgresql_where=text("published_at IS NULL")),
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_hash: Mapped[str] = mapped_column(CHAR(64))
    state: Mapped[str] = mapped_column(Text)
    lease_token: Mapped[uuid.UUID] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("payments.id"))
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)

    __table_args__ = (
        CheckConstraint("state IN ('in_progress','completed')", name="ck_idempotency_keys_state"),
        CheckConstraint(
            "(state = 'completed') = (response_body IS NOT NULL)", name="ck_idempotency_keys_response_body"
        ),
        Index("ix_idempotency_keys_expires_at", "expires_at"),
    )


FINAL_FAILURE = text("trigger = 'final_failure'")  # the class has a column named text


class PaymentExplanation(Base):
    """An explanation of a final payment (data-model.md); written by app.explain.store only."""

    __tablename__ = "payment_explanations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payments.id"))
    source: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    cited_event_seqs: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    trigger: Mapped[str] = mapped_column(Text)
    fallback_reason: Mapped[str | None] = mapped_column(Text)
    final_event_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    generated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)

    __table_args__ = (
        CheckConstraint("source IN ('model','rules')", name="ck_payment_explanations_source"),
        CheckConstraint("(source = 'model') = (model IS NOT NULL)", name="ck_payment_explanations_model"),
        CheckConstraint(
            "trigger IN ('final_failure','on_request','regenerate')", name="ck_payment_explanations_trigger"
        ),
        Index("ix_payment_explanations_payment_id_generated_at", "payment_id", generated_at.desc()),
        Index(
            "uq_payment_explanations_final_failure",
            "payment_id",
            unique=True,
            postgresql_where=FINAL_FAILURE,
        ),
    )


OPEN_INCIDENT = text("status <> 'resolved' AND processor IS NOT NULL")


class Incident(Base):
    """An incident on a processor (data-model.md): opened by the detector (`rule`) or an analyst (`manual`)."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    processor: Mapped[str | None] = mapped_column(CHAR(1))
    source: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    opened_by_event_id: Mapped[int | None] = mapped_column(BigInteger)
    recovered_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    triaged_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    __table_args__ = (
        CheckConstraint("processor IN ('A','B')", name="ck_incidents_processor"),
        CheckConstraint("source IN ('rule','manual')", name="ck_incidents_source"),
        CheckConstraint("status IN ('detected','triaged','resolved')", name="ck_incidents_status"),
        Index("ix_incidents_opened_at", opened_at.desc()),
        Index("uq_incidents_open_per_processor", "processor", unique=True, postgresql_where=OPEN_INCIDENT),
    )


class IncidentDetectorState(Base):
    """The id of the last `payment.routed` event the detector applied, per processor (ADR-0014)."""

    __tablename__ = "incident_detector_state"

    processor: Mapped[str] = mapped_column(CHAR(1), primary_key=True)
    last_event_id: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (CheckConstraint("processor IN ('A','B')", name="ck_incident_detector_state_processor"),)


class IncidentPayment(Base):
    """A payment affected by an incident (data-model.md); written by the detector in its own transaction."""

    __tablename__ = "incident_payments"

    incident_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("incidents.id"), primary_key=True)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payments.id"), primary_key=True)
    linked_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    first_event_id: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (Index("ix_incident_payments_payment_id", "payment_id"),)


class IncidentSummary(Base):
    """A stored incident summary (data-model.md); written by app.incidents.summary_store only."""

    __tablename__ = "incident_summaries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("incidents.id"))
    source: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    cited_event_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    cause: Mapped[str] = mapped_column(Text)
    fallback_reason: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ)
    trigger: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("source IN ('model','rules')", name="ck_incident_summaries_source"),
        CheckConstraint("(source = 'model') = (model IS NOT NULL)", name="ck_incident_summaries_model"),
        CheckConstraint("cause IN ('outage','timeouts','mixed','none')", name="ck_incident_summaries_cause"),
        CheckConstraint("trigger IN ('on_request','regenerate')", name="ck_incident_summaries_trigger"),
        Index("ix_incident_summaries_incident_id_generated_at", "incident_id", generated_at.desc()),
    )


class WebhookSubscription(Base):
    """A webhook subscription (data-model.md); `secret` signs deliveries and is returned only when created."""

    __tablename__ = "webhook_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    event_types: Mapped[list[str]] = mapped_column(ARRAY(Text))
    secret: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            f"cardinality(event_types) >= 1 AND event_types <@ ARRAY[{_in_list(list(WEBHOOK_EVENT_TYPES))}]::text[]",
            name="ck_webhook_subscriptions_event_types",
        ),
        Index("ix_webhook_subscriptions_created_at", created_at.desc()),
    )


class WebhookDelivery(Base):
    """One delivery of one event to one subscription; the row is the log entry (attempt count, last response)."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("webhook_subscriptions.id"))
    event_id: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    next_attempt_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("subscription_id", "event_id", name="uq_webhook_deliveries_subscription_event"),
        CheckConstraint(
            f"event_type IN ({_in_list(list(WEBHOOK_EVENT_TYPES))})", name="ck_webhook_deliveries_event_type"
        ),
        CheckConstraint(f"status IN ({_in_list(list(DELIVERY_STATUSES))})", name="ck_webhook_deliveries_status"),
        CheckConstraint(f"attempt BETWEEN 0 AND {MAX_ATTEMPTS}", name="ck_webhook_deliveries_attempt"),
        Index("ix_webhook_deliveries_due", "next_attempt_at", postgresql_where=text("status = 'pending'")),
        Index("ix_webhook_deliveries_created_at_id", created_at.desc(), id.desc()),
        Index("ix_webhook_deliveries_status_updated_at", "status", "updated_at"),
    )


class WebhookConsumerState(Base):
    """The id of the last stream event the webhooks consumer applied (one row, ADR-0015)."""

    __tablename__ = "webhook_consumer_state"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    last_event_id: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (CheckConstraint("id = 1", name="ck_webhook_consumer_state_single_row"),)


class WebhookDeliveryAttempt(Base):
    """One attempt of a delivery (the per-attempt delivery log); deleted with its delivery."""

    __tablename__ = "webhook_delivery_attempts"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    delivery_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("webhook_deliveries.id", ondelete="CASCADE"))
    attempt: Mapped[int] = mapped_column(SmallInteger)
    status_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)
    attempted_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, server_default=func.now())

    __table_args__ = (
        CheckConstraint(f"attempt BETWEEN 1 AND {MAX_ATTEMPTS}", name="ck_webhook_delivery_attempts_attempt"),
        CheckConstraint("duration_ms >= 0", name="ck_webhook_delivery_attempts_duration"),
        Index("ix_webhook_delivery_attempts_delivery_id", "delivery_id"),
    )
