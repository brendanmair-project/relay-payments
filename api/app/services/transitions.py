"""Transactional outbox writes (REL-16, ADR-0003, ADR-0008).

Every function here takes a SQLAlchemy `Session` and never commits or rolls back: the caller owns the transaction,
so the payment row update and its events commit together or not at all. Each function first locks the payment row
(`SELECT ... FOR UPDATE`), which serializes every writer of that payment, and assigns the next per-payment `seq`
inside that lock, so `UNIQUE (payment_id, seq)` is never hit and events are strictly ordered without gaps.

Companion events written with a state change (docs/architecture/data-model.md):
- routed -> `payment.routed`; authorized -> `payment.authorized`; declined -> `payment.declined`;
  captured -> `payment.captured`; failed -> `payment.failed` (processor = the failed attempt's processor);
- a transition that makes the payment final also appends `payment.final` with `data.outcome`;
- a non-final failure (a retry is possible) also appends `payment.retry_scheduled`.
"""

import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.correlation import get_correlation_id
from app.db.events import insert_event
from app.db.models import Payment, PaymentEvent
from app.domain.lifecycle import Event, LateResultError, PaymentState, PaymentStatus, transition
from app.domain.reasons import REASONS_BY_EVENT_TYPE, EventType

_EVENT_TYPE_FOR: dict[Event, EventType] = {
    Event.ROUTE: EventType.PAYMENT_ROUTED,
    Event.AUTHORIZE: EventType.PAYMENT_AUTHORIZED,
    Event.DECLINE: EventType.PAYMENT_DECLINED,
    Event.FAIL: EventType.PAYMENT_FAILED,
    Event.CAPTURE: EventType.PAYMENT_CAPTURED,
}

# Event types that carry no state change and may be appended through `append_event`.
NON_STATE_CHANGE_TYPES = frozenset(
    {
        EventType.ATTEMPT_AUTHORIZE_RESULT,
        EventType.ATTEMPT_CAPTURE_RESULT,
        EventType.ATTEMPT_LATE_RESULT,
        EventType.PAYMENT_REDRIVEN,
        EventType.PAYMENT_EXPLAINED,
    }
)

# Types whose `reason` must be set (the others may leave it null, e.g. an approved authorize_result).
_REASON_REQUIRED = frozenset(
    {
        EventType.PAYMENT_ROUTED,
        EventType.PAYMENT_DECLINED,
        EventType.PAYMENT_FAILED,
        EventType.ATTEMPT_LATE_RESULT,
    }
)


class PaymentNotFoundError(Exception):
    """No payment row has this id."""


class StateMismatchError(Exception):
    """The locked payment is not in the status and attempt the caller expected; nothing was written."""


def _correlation(explicit: str | None) -> str:
    value = explicit if explicit is not None else get_correlation_id()
    if not value:
        raise ValueError("a correlation_id is required: pass one or bind it with bind_correlation_id")
    return value


def _check_reason(event_type: EventType, reason: str | None) -> None:
    allowed = REASONS_BY_EVENT_TYPE[event_type]
    if reason is None:
        if event_type in _REASON_REQUIRED:
            raise ValueError(f"{event_type.value} requires a reason")
        return
    if allowed is None or reason not in {m.value for m in allowed}:
        raise ValueError(f"reason {reason!r} is not allowed for {event_type.value}")


def _lock(session: Session, payment_id: uuid.UUID) -> sa.Row[str, int, str | None, bool]:
    row = session.execute(
        sa.select(Payment.status, Payment.attempt_no, Payment.processor, Payment.is_final)
        .where(Payment.id == payment_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise PaymentNotFoundError(str(payment_id))
    return row


def _next_seq(session: Session, payment_id: uuid.UUID) -> int:
    """Call only while holding the payment row lock."""
    current = session.execute(
        sa.select(sa.func.coalesce(sa.func.max(PaymentEvent.seq), 0)).where(PaymentEvent.payment_id == payment_id)
    ).scalar_one()
    return int(current) + 1


def create_payment(
    session: Session,
    *,
    amount_minor: int,
    currency: str,
    payment_id: uuid.UUID | None = None,
    reference: str | None = None,
    description: str | None = None,
    correlation_id: str | None = None,
) -> uuid.UUID:
    """Insert a `received` payment and its seq 1 `payment.received` event. Does not commit."""
    cid = _correlation(correlation_id)
    pid = payment_id or uuid.uuid4()
    session.execute(
        sa.insert(Payment).values(
            id=pid,
            amount_minor=amount_minor,
            currency=currency,
            reference=reference,
            description=description,
            status=PaymentState.RECEIVED.value,
            attempt_no=0,
            correlation_id=cid,
        )
    )
    insert_event(
        session,
        payment_id=pid,
        seq=1,
        attempt_no=0,
        type=EventType.PAYMENT_RECEIVED.value,
        to_status=PaymentState.RECEIVED.value,
        correlation_id=cid,
    )
    return pid


def apply_transition(
    session: Session,
    payment_id: uuid.UUID,
    event: Event,
    *,
    expected_status: PaymentState,
    expected_attempt: int,
    retries_enabled: bool,
    processor: str | None = None,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
    event_attempt: int | None = None,
    correlation_id: str | None = None,
) -> PaymentStatus:
    """Lock the payment, check `expected_status` and `expected_attempt`, apply one domain transition, update the
    row and append the state-change event plus its companions. Returns the new status. Does not commit.

    `processor` is required for `Event.ROUTE` (the processor of the new attempt) and not allowed otherwise.
    Raises StateMismatchError on a mismatch and the domain's errors (including LateResultError) for a transition
    that is not allowed; in every error case nothing has been written.
    """
    cid = _correlation(correlation_id)
    event_type = _EVENT_TYPE_FOR[event]
    _check_reason(event_type, reason)
    if (event is Event.ROUTE) != (processor is not None):
        raise ValueError("processor is required for a route event and not allowed for any other")

    locked = _lock(session, payment_id)
    if locked.status != expected_status.value or locked.attempt_no != expected_attempt:
        raise StateMismatchError(
            f"expected {expected_status.value} attempt {expected_attempt}, "
            f"found {locked.status} attempt {locked.attempt_no}"
        )
    current = PaymentStatus(PaymentState(locked.status), locked.attempt_no, locked.is_final)
    new = transition(current, event, retries_enabled=retries_enabled, event_attempt=event_attempt)

    new_processor = processor if event is Event.ROUTE else locked.processor
    values: dict[str, Any] = {
        "status": new.state.value,
        "attempt_no": new.attempt_no,
        "processor": new_processor,
        "is_final": new.is_final,
        "status_changed_at": sa.func.now(),
    }
    if new.is_final:
        values["final_at"] = sa.func.now()
    session.execute(sa.update(Payment).where(Payment.id == payment_id).values(**values))

    def write(type_: EventType, **kw: Any) -> None:
        insert_event(
            session,
            payment_id=payment_id,
            seq=_next_seq(session, payment_id),
            attempt_no=new.attempt_no,
            type=type_.value,
            correlation_id=cid,
            **kw,
        )

    write(
        event_type,
        from_status=current.state.value,
        to_status=new.state.value,
        processor=new_processor if event in (Event.ROUTE, Event.FAIL) else None,
        reason=reason,
        data=data,
    )
    if new.is_final:
        write(EventType.PAYMENT_FINAL, data={"outcome": new.state.value})
    elif event is Event.FAIL:
        write(EventType.PAYMENT_RETRY_SCHEDULED)
    return new


def append_event(
    session: Session,
    payment_id: uuid.UUID,
    event_type: EventType,
    *,
    processor: str | None = None,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
    attempt_no: int | None = None,
    correlation_id: str | None = None,
) -> int:
    """Append a non-state-change event through the same row lock and seq path; return its seq.

    `attempt_no` defaults to the payment's current attempt. Does not commit.
    """
    if event_type not in NON_STATE_CHANGE_TYPES:
        raise ValueError(f"{event_type.value} is not a non-state-change event; use apply_transition")
    cid = _correlation(correlation_id)
    _check_reason(event_type, reason)
    locked = _lock(session, payment_id)
    seq = _next_seq(session, payment_id)
    insert_event(
        session,
        payment_id=payment_id,
        seq=seq,
        attempt_no=locked.attempt_no if attempt_no is None else attempt_no,
        type=event_type.value,
        processor=processor,
        reason=reason,
        data=data,
        correlation_id=cid,
    )
    return seq


def record_late_result(
    session: Session,
    payment_id: uuid.UUID,
    error: LateResultError,
    *,
    processor: str,
    data: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> int:
    """Record a rejected processor result as `attempt.late_result` with the error's reason; no result is dropped."""
    return append_event(
        session,
        payment_id,
        EventType.ATTEMPT_LATE_RESULT,
        processor=processor,
        reason=error.reason.value,
        data=data,
        correlation_id=correlation_id,
    )
