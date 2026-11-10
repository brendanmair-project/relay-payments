"""Event types and the decided `reason` values per event type (data-model.md "Reason values", ADR-0012).

Processor health counts errors by these exact strings, so no other value is allowed.
"""

from enum import StrEnum


class EventType(StrEnum):
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_ROUTED = "payment.routed"
    ATTEMPT_AUTHORIZE_RESULT = "attempt.authorize_result"
    PAYMENT_AUTHORIZED = "payment.authorized"
    ATTEMPT_CAPTURE_RESULT = "attempt.capture_result"
    PAYMENT_CAPTURED = "payment.captured"
    PAYMENT_DECLINED = "payment.declined"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_RETRY_SCHEDULED = "payment.retry_scheduled"
    PAYMENT_FINAL = "payment.final"
    ATTEMPT_LATE_RESULT = "attempt.late_result"
    PAYMENT_REDRIVEN = "payment.redriven"
    PAYMENT_EXPLAINED = "payment.explained"


class RoutedReason(StrEnum):
    INITIAL = "initial"
    FAILOVER = "failover"
    RETRY = "retry"
    STATIC = "static"
    ADAPTIVE = "adaptive"


class DeclinedReason(StrEnum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    DO_NOT_HONOR = "do_not_honor"
    CARD_EXPIRED = "card_expired"


class FailedReason(StrEnum):
    TIMEOUT = "timeout"
    OUTAGE = "outage"
    CAPTURE_FAILED = "capture_failed"


class AuthorizeResultReason(StrEnum):
    """Null when approved; a decline reason when declined; timeout or outage when the call failed."""

    INSUFFICIENT_FUNDS = "insufficient_funds"
    DO_NOT_HONOR = "do_not_honor"
    CARD_EXPIRED = "card_expired"
    TIMEOUT = "timeout"
    OUTAGE = "outage"


class CaptureResultReason(StrEnum):
    """Null when captured; otherwise one of these."""

    CAPTURE_FAILED = "capture_failed"
    TIMEOUT = "timeout"
    OUTAGE = "outage"


class LateResultReason(StrEnum):
    STALE_ATTEMPT = "stale_attempt"
    AFTER_TIMEOUT = "after_timeout"


# None means the event type carries no reason (it must be null).
REASONS_BY_EVENT_TYPE: dict[EventType, type[StrEnum] | None] = {
    EventType.PAYMENT_RECEIVED: None,
    EventType.PAYMENT_ROUTED: RoutedReason,
    EventType.ATTEMPT_AUTHORIZE_RESULT: AuthorizeResultReason,
    EventType.PAYMENT_AUTHORIZED: None,
    EventType.ATTEMPT_CAPTURE_RESULT: CaptureResultReason,
    EventType.PAYMENT_CAPTURED: None,
    EventType.PAYMENT_DECLINED: DeclinedReason,
    EventType.PAYMENT_FAILED: FailedReason,
    EventType.PAYMENT_RETRY_SCHEDULED: None,
    EventType.PAYMENT_FINAL: None,
    EventType.ATTEMPT_LATE_RESULT: LateResultReason,
    EventType.PAYMENT_REDRIVEN: None,
    EventType.PAYMENT_EXPLAINED: None,
}
