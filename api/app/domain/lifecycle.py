"""Payment lifecycle state machine (docs/architecture/payment-lifecycle.md, ADR-0004, ADR-0008).

Pure and immutable: `transition` returns a new `PaymentStatus` or raises; it never changes its input and
writes nothing. Recording an `attempt.late_result` event for a `LateResultError` is the caller's job.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.reasons import LateResultReason

MAX_ATTEMPTS = 2  # attempt 1 plus the single retry


class PaymentState(StrEnum):
    RECEIVED = "received"
    ROUTED = "routed"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    DECLINED = "declined"
    FAILED = "failed"


class Event(StrEnum):
    """What happened to the payment; each names the state it leads to."""

    ROUTE = "routed"
    AUTHORIZE = "authorized"
    DECLINE = "declined"
    FAIL = "failed"
    CAPTURE = "captured"


@dataclass(frozen=True, slots=True)
class PaymentStatus:
    """The stored lifecycle columns. `is_final` is needed because a `failed` payment on attempt 1 is
    final when it failed from `authorized` and retrying otherwise."""

    state: PaymentState
    attempt_no: int
    is_final: bool


class InvalidTransitionError(Exception):
    """The (state, event) pair is not in the transition table."""


class LateResultError(InvalidTransitionError):
    """A processor result no longer matches the payment: record `reason` as attempt.late_result."""

    def __init__(self, message: str, reason: LateResultReason) -> None:
        super().__init__(message)
        self.reason = reason


class StaleAttemptError(LateResultError):
    """The result belongs to an attempt that is not the current one (ADR-0008)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, LateResultReason.STALE_ATTEMPT)


# (from state, event) -> to state
_ALLOWED: dict[tuple[PaymentState, Event], PaymentState] = {
    (PaymentState.RECEIVED, Event.ROUTE): PaymentState.ROUTED,
    (PaymentState.ROUTED, Event.AUTHORIZE): PaymentState.AUTHORIZED,
    (PaymentState.ROUTED, Event.DECLINE): PaymentState.DECLINED,
    (PaymentState.ROUTED, Event.FAIL): PaymentState.FAILED,
    (PaymentState.AUTHORIZED, Event.CAPTURE): PaymentState.CAPTURED,
    (PaymentState.AUTHORIZED, Event.FAIL): PaymentState.FAILED,
    (PaymentState.FAILED, Event.ROUTE): PaymentState.ROUTED,  # the single retry, guarded below
}

_RESULT_EVENTS = frozenset({Event.AUTHORIZE, Event.DECLINE, Event.FAIL, Event.CAPTURE})


def new_payment() -> PaymentStatus:
    """A created payment: received, attempt 0."""
    return PaymentStatus(PaymentState.RECEIVED, 0, False)


def transition(
    current: PaymentStatus,
    event: Event,
    *,
    retries_enabled: bool,
    event_attempt: int | None = None,
) -> PaymentStatus:
    """Apply `event` to `current`.

    `event_attempt` is the attempt a processor result belongs to; None means the current attempt.
    Raises StaleAttemptError when it is not the current attempt, LateResultError (after_timeout) when the
    sweeper already failed the current attempt, and InvalidTransitionError for any other pair.
    """
    if event in _RESULT_EVENTS and event_attempt is not None and event_attempt != current.attempt_no:
        raise StaleAttemptError(f"result for attempt {event_attempt}, current attempt is {current.attempt_no}")
    if current.state is PaymentState.FAILED and event in {Event.AUTHORIZE, Event.DECLINE, Event.CAPTURE}:
        raise LateResultError(
            f"{event.value} result arrived after attempt {current.attempt_no} failed", LateResultReason.AFTER_TIMEOUT
        )

    target = _ALLOWED.get((current.state, event))
    if target is None or current.is_final:
        raise InvalidTransitionError(f"{current.state.value} -> {event.value} is not allowed")

    attempt_no = current.attempt_no
    if event is Event.ROUTE:
        if current.state is PaymentState.FAILED and (not retries_enabled or current.attempt_no >= MAX_ATTEMPTS):
            raise InvalidTransitionError("retries are disabled or the single retry was used")
        attempt_no += 1

    if target is PaymentState.FAILED:
        # Final from authorized, on the last attempt, or with retries disabled.
        is_final = current.state is PaymentState.AUTHORIZED or attempt_no >= MAX_ATTEMPTS or not retries_enabled
    else:
        is_final = target in {PaymentState.CAPTURED, PaymentState.DECLINED}
    return PaymentStatus(target, attempt_no, is_final)
