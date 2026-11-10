from enum import Enum

from app.domain.reasons import (
    REASONS_BY_EVENT_TYPE,
    AuthorizeResultReason,
    CaptureResultReason,
    DeclinedReason,
    EventType,
    FailedReason,
    LateResultReason,
    RoutedReason,
)

# Copied from docs/architecture/data-model.md: the CHECK on payment_events.reason (ADR-0012).
DOCUMENTED_CHECK = {
    "initial",
    "failover",
    "retry",
    "static",
    "adaptive",
    "insufficient_funds",
    "do_not_honor",
    "card_expired",
    "timeout",
    "outage",
    "capture_failed",
    "stale_attempt",
    "after_timeout",
}

EVENT_TYPES_WITH_REASON = {
    EventType.PAYMENT_ROUTED,
    EventType.PAYMENT_DECLINED,
    EventType.PAYMENT_FAILED,
    EventType.ATTEMPT_AUTHORIZE_RESULT,
    EventType.ATTEMPT_CAPTURE_RESULT,
    EventType.ATTEMPT_LATE_RESULT,
}


def values(enum_type: type[Enum]) -> set[object]:
    return {m.value for m in enum_type}


def test_per_event_type_values_match_documented_table() -> None:
    assert values(RoutedReason) == {"initial", "failover", "retry", "static", "adaptive"}
    assert values(DeclinedReason) == {"insufficient_funds", "do_not_honor", "card_expired"}
    assert values(FailedReason) == {"timeout", "outage", "capture_failed"}
    assert values(AuthorizeResultReason) == {"insufficient_funds", "do_not_honor", "card_expired", "timeout", "outage"}
    assert values(CaptureResultReason) == {"capture_failed", "timeout", "outage"}
    assert values(LateResultReason) == {"stale_attempt", "after_timeout"}


def test_union_equals_database_check_list() -> None:
    union: set[object] = set()
    for enum_type in REASONS_BY_EVENT_TYPE.values():
        if enum_type is not None:
            union |= values(enum_type)
    assert union == DOCUMENTED_CHECK


def test_mapping_for_event_types_with_reasons() -> None:
    assert REASONS_BY_EVENT_TYPE[EventType.PAYMENT_ROUTED] is RoutedReason
    assert REASONS_BY_EVENT_TYPE[EventType.PAYMENT_DECLINED] is DeclinedReason
    assert REASONS_BY_EVENT_TYPE[EventType.PAYMENT_FAILED] is FailedReason
    assert REASONS_BY_EVENT_TYPE[EventType.ATTEMPT_AUTHORIZE_RESULT] is AuthorizeResultReason
    assert REASONS_BY_EVENT_TYPE[EventType.ATTEMPT_CAPTURE_RESULT] is CaptureResultReason
    assert REASONS_BY_EVENT_TYPE[EventType.ATTEMPT_LATE_RESULT] is LateResultReason


def test_every_other_event_type_has_no_reason() -> None:
    assert set(REASONS_BY_EVENT_TYPE) == set(EventType)
    for event_type in EventType:
        if event_type not in EVENT_TYPES_WITH_REASON:
            assert REASONS_BY_EVENT_TYPE[event_type] is None


def test_event_type_values_match_data_model() -> None:
    assert values(EventType) == {
        "payment.received",
        "payment.routed",
        "attempt.authorize_result",
        "payment.authorized",
        "attempt.capture_result",
        "payment.captured",
        "payment.declined",
        "payment.failed",
        "payment.retry_scheduled",
        "payment.final",
        "attempt.late_result",
        "payment.redriven",
        "payment.explained",
    }
