"""Link an incident to the payments that failed on its processor, and read the links back (REL-35).

A failure on a processor is a `payment.failed` event for it, or an `attempt.authorize_result` /
`attempt.capture_result` event for it with reason `timeout` or `outage`: the failures that made routing avoid it.
`link_failures` runs inside the detector's transaction; the primary key `(incident_id, payment_id)` makes it
idempotent. `load_facts` reads the linked payments and their failure events back for the detail and the summary.
"""

import uuid
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Incident, IncidentPayment, Payment, PaymentEvent
from app.domain.reasons import AuthorizeResultReason, EventType, RoutedReason
from app.incidents.summary import AffectedPayment, IncidentFacts, LinkedEvent
from app.routing.config import health_settings

_ATTEMPT_RESULTS = [EventType.ATTEMPT_AUTHORIZE_RESULT.value, EventType.ATTEMPT_CAPTURE_RESULT.value]
_CALL_FAILURES = [AuthorizeResultReason.TIMEOUT.value, AuthorizeResultReason.OUTAGE.value]
_RESCUE_REASONS = [RoutedReason.FAILOVER.value, RoutedReason.RETRY.value]


def lookback() -> timedelta:
    return timedelta(seconds=health_settings().window_seconds)


def failure_on(processor: str) -> sa.ColumnElement[bool]:
    return sa.and_(
        PaymentEvent.processor == processor,
        sa.or_(
            PaymentEvent.type == EventType.PAYMENT_FAILED.value,
            sa.and_(PaymentEvent.type.in_(_ATTEMPT_RESULTS), PaymentEvent.reason.in_(_CALL_FAILURES)),
        ),
    )


def link_failures(session: Session, incident_id: uuid.UUID, processor: str, since: datetime, until: datetime) -> None:
    """Link every payment with a failure on `processor` in `[since, until]`; already linked payments are skipped."""
    first_failure = (
        sa.select(sa.literal(incident_id, sa.Uuid), PaymentEvent.payment_id, sa.func.min(PaymentEvent.id))
        .where(failure_on(processor), PaymentEvent.occurred_at >= since, PaymentEvent.occurred_at <= until)
        .group_by(PaymentEvent.payment_id)
    )
    session.execute(
        insert(IncidentPayment)
        .from_select(["incident_id", "payment_id", "first_event_id"], first_failure)
        .on_conflict_do_nothing(index_elements=["incident_id", "payment_id"])
    )


def load_facts(session: Session, incident: Incident) -> IncidentFacts:
    """The incident's linked payments and failure events (empty for an incident without a processor)."""
    if incident.processor is None:
        return IncidentFacts(None, incident.opened_at, incident.recovered_at, incident.resolved_at, [], [])
    rescued = (
        sa.select(PaymentEvent.id)
        .where(
            PaymentEvent.payment_id == Payment.id,
            PaymentEvent.type == EventType.PAYMENT_ROUTED.value,
            PaymentEvent.reason.in_(_RESCUE_REASONS),
        )
        .exists()
    )
    payment_rows = session.execute(
        sa.select(Payment, sa.and_(Payment.status == "captured", rescued))
        .join(IncidentPayment, IncidentPayment.payment_id == Payment.id)
        .where(IncidentPayment.incident_id == incident.id)
        .order_by(IncidentPayment.linked_at, Payment.id)
    ).all()
    payments = [
        AffectedPayment(str(p.id), p.status, p.amount_minor, p.currency, bool(saved), p.processor)
        for p, saved in payment_rows
    ]
    end = incident.recovered_at or incident.resolved_at
    query = (
        sa.select(PaymentEvent)
        .join(IncidentPayment, IncidentPayment.payment_id == PaymentEvent.payment_id)
        .where(
            IncidentPayment.incident_id == incident.id,
            failure_on(incident.processor),
            PaymentEvent.occurred_at >= incident.opened_at - lookback(),
        )
        .order_by(PaymentEvent.occurred_at, PaymentEvent.id)
    )
    if end is not None:
        query = query.where(PaymentEvent.occurred_at <= end)
    events = [
        LinkedEvent(e.id, str(e.payment_id), e.type, e.reason, e.processor, e.occurred_at)
        for e in session.scalars(query).all()
    ]
    return IncidentFacts(
        incident.processor, incident.opened_at, incident.recovered_at, incident.resolved_at, payments, events
    )
