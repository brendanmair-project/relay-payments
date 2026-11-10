"""One trigger, start to finish (ADR-0008, ADR-0012): route, authorize, capture.

Every database step is its own short transaction and no transaction is open during a processor call. Each step locks
the payment row and compares status and attempt with what this worker expects; a result that no longer fits is written
as `attempt.late_result` (`stale_attempt` when the attempt is no longer current, `after_timeout` when the same attempt
was already failed) and changes nothing else. The router (REL-22) picks the processor: a `received` payment is routed
for attempt 1; a `failed`, non-final payment (a `payment.retry_scheduled` or `payment.redriven` trigger) is routed
once more to the other processor. Under `ROUTING_STRATEGY=static` every payment goes to A and every `failed` is final.
"""

import logging
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Payment
from app.domain.lifecycle import Event, PaymentState
from app.domain.reasons import EventType, LateResultReason
from app.metrics import PAYMENTS_FINAL, PROCESSOR_CALLS, PROCESSOR_DURATION
from app.routing.config import retries_enabled
from app.routing.registry import RouteDecision
from app.routing.router import decide_initial, decide_retry
from app.services.transitions import StateMismatchError, append_event, apply_transition
from app.worker.processor import (
    ProcessorClient,
    ProcessorError,
    ProcessorOutage,
    ProcessorResult,
    ProcessorTimeout,
)
from app.worker.timing import observe_processing

TRIGGER_TYPES = frozenset({"payment.received", "payment.retry_scheduled", "payment.redriven"})

logger = logging.getLogger("relay.worker")


@dataclass(frozen=True)
class _Snapshot:
    id: uuid.UUID  # REL-59: the adaptive sampler seeds from it when the payment has no reference
    status: str
    attempt_no: int
    amount_minor: int
    currency: str
    reference: str | None
    is_final: bool
    processor: str | None


def _read(factory: sessionmaker[Session], payment_id: uuid.UUID) -> _Snapshot | None:
    with factory() as session:
        row = session.execute(
            sa.select(
                Payment.id,
                Payment.status,
                Payment.attempt_no,
                Payment.amount_minor,
                Payment.currency,
                Payment.reference,
                Payment.is_final,
                Payment.processor,
            ).where(Payment.id == payment_id)
        ).one_or_none()
    return None if row is None else _Snapshot(*row)


def _lock_and_check(
    session: Session, payment_id: uuid.UUID, status: PaymentState, attempt_no: int
) -> LateResultReason | None:
    """Lock the row; return None while it is still in the expected status and attempt, else why a result is late."""
    row = session.execute(
        sa.select(Payment.status, Payment.attempt_no).where(Payment.id == payment_id).with_for_update()
    ).one()
    if row.status == status.value and row.attempt_no == attempt_no:
        return None
    return LateResultReason.STALE_ATTEMPT if row.attempt_no != attempt_no else LateResultReason.AFTER_TIMEOUT


def _call_data(outcome: ProcessorResult | ProcessorError) -> tuple[str, str | None, int]:
    """(data.result, reason, latency_ms) of a processor call for its result event."""
    if isinstance(outcome, ProcessorResult):
        return outcome.result, outcome.reason, outcome.latency_ms
    return "failed", ("timeout" if isinstance(outcome, ProcessorTimeout) else "outage"), outcome.elapsed_ms


def _record_step(
    factory: sessionmaker[Session],
    payment_id: uuid.UUID,
    *,
    processor: str,
    operation: str,
    expected: PaymentState,
    attempt_no: int,
    outcome: ProcessorResult | ProcessorError,
) -> PaymentState | None:
    """Commit the result of one processor call; return the new state, or None when the result was late."""
    result, reason, latency_ms = _call_data(outcome)
    call_outcome = result if isinstance(outcome, ProcessorResult) else reason  # timeout or outage for an error
    PROCESSOR_CALLS.labels(processor, operation, call_outcome or "unknown").inc()
    PROCESSOR_DURATION.labels(processor, operation).observe(latency_ms / 1000)
    data = {"result": result, "latency_ms": latency_ms}
    result_type = EventType.ATTEMPT_AUTHORIZE_RESULT if operation == "authorize" else EventType.ATTEMPT_CAPTURE_RESULT
    with factory.begin() as session:
        late = _lock_and_check(session, payment_id, expected, attempt_no)
        if late is not None:
            append_event(
                session,
                payment_id,
                EventType.ATTEMPT_LATE_RESULT,
                processor=processor,
                reason=late.value,
                data={**data, "operation": operation, "processor_reason": reason},
                attempt_no=attempt_no,
            )
            return None
        append_event(
            session, payment_id, result_type, processor=processor, reason=reason, data=data, attempt_no=attempt_no
        )
        if isinstance(outcome, ProcessorError):
            event, event_reason = Event.FAIL, reason
        elif operation == "authorize":
            if outcome.result == "approved":
                event, event_reason = Event.AUTHORIZE, None
            else:
                event, event_reason = Event.DECLINE, outcome.reason
        elif outcome.result == "captured":
            event, event_reason = Event.CAPTURE, None
        else:
            event, event_reason = Event.FAIL, outcome.reason
        new = apply_transition(
            session,
            payment_id,
            event,
            expected_status=expected,
            expected_attempt=attempt_no,
            retries_enabled=retries_enabled(),
            reason=event_reason,
            event_attempt=attempt_no,
        )
        if new.is_final:
            PAYMENTS_FINAL.labels(processor, new.state.value).inc()
            observe_processing(session, payment_id, processor, new.state.value)
        return new.state


def _call(
    processors: ProcessorClient,
    processor: str,
    operation: str,
    payment_id: uuid.UUID,
    attempt_no: int,
    snap: _Snapshot,
) -> ProcessorResult | ProcessorError:
    send = processors.authorize if operation == "authorize" else processors.capture
    try:
        return send(
            processor,
            payment_id=payment_id,
            attempt_no=attempt_no,
            amount_minor=snap.amount_minor,
            currency=snap.currency,
            reference=snap.reference,
        )
    except (ProcessorTimeout, ProcessorOutage) as error:
        return error  # a recorded failure; any other ProcessorError propagates and leaves the message pending


def handle_trigger(factory: sessionmaker[Session], processors: ProcessorClient, payment_id: uuid.UUID) -> None:
    """Process one trigger for `payment_id`.

    Returns normally when the message may be acknowledged: it was done, or it was a duplicate or late message with
    nothing left to do. Raises when a database step or the processor protocol failed, so the caller leaves the
    message pending for reclaim.
    """
    snap = _read(factory, payment_id)
    if snap is None:
        logger.info("trigger ignored: unknown payment", extra={"payment_id": str(payment_id)})
        return
    is_retry = (
        snap.status == PaymentState.FAILED.value
        and not snap.is_final
        and snap.processor is not None
        and retries_enabled()
    )
    if snap.status != PaymentState.RECEIVED.value and not is_retry:
        logger.info("trigger ignored: payment is not waiting for routing", extra={"payment_id": str(payment_id)})
        return

    try:
        with factory.begin() as session:
            decision: RouteDecision = decide_retry(snap.processor or "A") if is_retry else decide_initial(session, snap)
            routed = apply_transition(
                session,
                payment_id,
                Event.ROUTE,
                expected_status=PaymentState.FAILED if is_retry else PaymentState.RECEIVED,
                expected_attempt=snap.attempt_no,
                retries_enabled=retries_enabled(),
                processor=decision.processor,
                reason=decision.reason,
                data=decision.data,
            )
    except StateMismatchError:
        return  # another worker routed it first
    attempt_no = routed.attempt_no
    processor = decision.processor

    outcome = _call(processors, processor, "authorize", payment_id, attempt_no, snap)
    state = _record_step(
        factory,
        payment_id,
        processor=processor,
        operation="authorize",
        expected=PaymentState.ROUTED,
        attempt_no=attempt_no,
        outcome=outcome,
    )
    if state is not PaymentState.AUTHORIZED:
        return  # declined, failed, or a late result: nothing more to do

    outcome = _call(processors, processor, "capture", payment_id, attempt_no, snap)
    _record_step(
        factory,
        payment_id,
        processor=processor,
        operation="capture",
        expected=PaymentState.AUTHORIZED,
        attempt_no=attempt_no,
        outcome=outcome,
    )
