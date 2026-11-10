"""REL-24: the rule-based explainer maps each timeline to one fixed pattern, cause and next step."""

import dataclasses
from typing import Any

import pytest

from app.explain import PATTERNS, ExplainEvent, Explanation, explain

Spec = tuple[str, int | None, str | None, str | None, dict[str, Any]]


def ev(
    type_: str, attempt: int | None = None, processor: str | None = None, reason: str | None = None, **data: Any
) -> Spec:
    return (type_, attempt, processor, reason, data)


def timeline(*specs: Spec) -> list[ExplainEvent]:
    return [
        ExplainEvent(seq=i, type=t, attempt_no=a, processor=p, reason=r, data=d)
        for i, (t, a, p, r, d) in enumerate(specs, 1)
    ]


RECEIVED = ev("payment.received", 0)


def routed(attempt: int, proc: str, reason: str = "initial") -> Spec:
    return ev("payment.routed", attempt, proc, reason)


def auth(attempt: int, proc: str, result: str, reason: str | None = None) -> Spec:
    return ev("attempt.authorize_result", attempt, proc, reason, result=result, latency_ms=120)


def cap(attempt: int, proc: str, result: str, reason: str | None = None) -> Spec:
    return ev("attempt.capture_result", attempt, proc, reason, result=result, latency_ms=90)


def authorized(attempt: int, proc: str) -> Spec:
    return ev("payment.authorized", attempt, proc)


def captured(attempt: int, proc: str) -> Spec:
    return ev("payment.captured", attempt, proc)


def declined(attempt: int, proc: str, reason: str) -> Spec:
    return ev("payment.declined", attempt, proc, reason)


def failed(attempt: int, proc: str, reason: str) -> Spec:
    return ev("payment.failed", attempt, proc, reason)


def final(outcome: str) -> Spec:
    return ev("payment.final", None, None, None, outcome=outcome)


def retry(attempt: int) -> Spec:
    return ev("payment.retry_scheduled", attempt)


def late(attempt: int, proc: str, reason: str, operation: str, result: str) -> Spec:
    return ev("attempt.late_result", attempt, proc, reason, operation=operation, result=result, latency_ms=4000)


# name -> (events, expected pattern, expected cited seqs, phrase in cause, phrase in next step)
SCENARIOS: dict[str, tuple[list[ExplainEvent], str, tuple[int, ...], str, str]] = {
    "decline_insufficient_funds": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "declined", "insufficient_funds"),
            declined(1, "A", "insufficient_funds"),
            final("declined"),
        ),
        "decline_insufficient_funds",
        (3, 4),
        "not enough money",
        "another payment method",
    ),
    "decline_do_not_honor": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "declined", "do_not_honor"),
            declined(1, "A", "do_not_honor"),
            final("declined"),
        ),
        "decline_do_not_honor",
        (3, 4),
        "bank refused",
        "contact their bank",
    ),
    "decline_card_expired": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "declined", "card_expired"),
            declined(1, "A", "card_expired"),
            final("declined"),
        ),
        "decline_card_expired",
        (3, 4),
        "expired",
        "updated card",
    ),
    "authorize_timeout": (
        timeline(RECEIVED, routed(1, "A", "initial"), failed(1, "A", "timeout"), final("failed")),
        "authorize_timeout",
        (3,),
        "did not answer in time",
        "processor's status",
    ),
    "authorize_outage": (
        timeline(
            RECEIVED,
            routed(1, "A", "initial"),
            auth(1, "A", "failed", "outage"),
            failed(1, "A", "outage"),
            final("failed"),
        ),
        "authorize_outage",
        (3, 4),
        "was down",
        "processor's status",
    ),
    "capture_failed": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "approved"),
            authorized(1, "A"),
            cap(1, "A", "failed", "capture_failed"),
            failed(1, "A", "capture_failed"),
            final("failed"),
        ),
        "capture_failed",
        (4, 5, 6),
        "refused to collect",
        "release",
    ),
    "capture_timeout": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "approved"),
            authorized(1, "A"),
            failed(1, "A", "timeout"),
            final("failed"),
        ),
        "capture_timeout",
        (4, 5),
        "to collect the money",
        "release",
    ),
    "capture_outage": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "approved"),
            authorized(1, "A"),
            cap(1, "A", "failed", "outage"),
            failed(1, "A", "outage"),
            final("failed"),
        ),
        "capture_outage",
        (4, 5, 6),
        "went down while collecting",
        "release",
    ),
    "failed_after_retry": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "failed", "outage"),
            failed(1, "A", "outage"),
            retry(1),
            routed(2, "B", "failover"),
            auth(2, "B", "failed", "timeout"),
            failed(2, "B", "timeout"),
            final("failed"),
        ),
        "failed_after_retry",
        (4, 8),
        "both attempts failed",
        "try again later",
    ),
    "captured_after_retry": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "failed", "outage"),
            failed(1, "A", "outage"),
            retry(1),
            routed(2, "B", "failover"),
            auth(2, "B", "approved"),
            authorized(2, "B"),
            cap(2, "B", "captured"),
            captured(2, "B"),
            final("captured"),
        ),
        "captured_after_retry",
        (4, 6, 10),
        "first attempt failed",
        "No action",
    ),
    "captured_first_time": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "approved"),
            authorized(1, "A"),
            cap(1, "A", "captured"),
            captured(1, "A"),
            final("captured"),
        ),
        "captured_first_time",
        (6,),
        "first attempt",
        "No action",
    ),
    "late_result_after_retry": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            failed(1, "A", "timeout"),
            retry(1),
            routed(2, "B", "failover"),
            auth(2, "B", "approved"),
            authorized(2, "B"),
            cap(2, "B", "captured"),
            captured(2, "B"),
            final("captured"),
            late(1, "A", "stale_attempt", "authorize", "declined"),
        ),
        "late_result_after_retry",
        (3, 11),
        "ignored",
        "no action",
    ),
    "orphaned_authorization": (
        timeline(
            RECEIVED,
            routed(1, "A", "static"),
            failed(1, "A", "timeout"),
            final("failed"),
            late(1, "A", "after_timeout", "authorize", "approved"),
        ),
        "orphaned_authorization",
        (3, 5),
        "orphaned authorization",
        "void",
    ),
    "late_capture_after_timeout": (
        timeline(
            RECEIVED,
            routed(1, "A"),
            auth(1, "A", "approved"),
            authorized(1, "A"),
            failed(1, "A", "timeout"),
            final("failed"),
            late(1, "A", "after_timeout", "capture", "captured"),
        ),
        "late_capture_after_timeout",
        (5, 7),
        "money was collected",
        "refund",
    ),
    "stalled_and_redriven": (
        timeline(
            RECEIVED,
            ev("payment.redriven"),
            routed(1, "A"),
            auth(1, "A", "approved"),
            authorized(1, "A"),
            cap(1, "A", "captured"),
            captured(1, "A"),
            final("captured"),
        ),
        "stalled_and_redriven",
        (2, 7),
        "stalled",
        "No action",
    ),
    "static_no_retry": (
        timeline(
            RECEIVED,
            routed(1, "A", "static"),
            auth(1, "A", "failed", "outage"),
            failed(1, "A", "outage"),
            final("failed"),
        ),
        "static_no_retry",
        (2, 3, 4),
        "not retried",
        "retries",
    ),
    "in_progress": (
        timeline(RECEIVED, routed(1, "A"), auth(1, "A", "approved"), authorized(1, "A")),
        "in_progress",
        (4,),
        "still in progress",
        "Check again",
    ),
    "captured_first_time_adaptive": (
        timeline(
            RECEIVED,
            routed(1, "B", "adaptive"),
            auth(1, "B", "approved"),
            authorized(1, "B"),
            cap(1, "B", "captured"),
            captured(1, "B"),
            final("captured"),
        ),
        "captured_first_time_adaptive",
        (2, 6),
        "adaptive routing",
        "No action",
    ),
    "unknown": (
        timeline(RECEIVED, routed(1, "A"), final("failed")),
        "unknown",
        (3,),
        "could not",
        "timeline",
    ),
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario(name: str) -> None:
    events, pattern, cited, cause_phrase, step_phrase = SCENARIOS[name]
    result = explain(events)
    assert result.pattern == pattern == name
    assert result.cited_event_seqs == cited
    assert result.source == "rules"
    assert cause_phrase.lower() in result.cause.lower()
    assert step_phrase.lower() in result.next_step.lower()
    assert (result.cause, result.next_step) == PATTERNS[pattern]


def test_every_pattern_has_a_scenario() -> None:
    assert PATTERNS
    assert set(SCENARIOS) == set(PATTERNS)


def test_texts_are_short_plain_and_unique() -> None:
    assert PATTERNS
    assert len(set(PATTERNS.values())) == len(PATTERNS)
    for cause, next_step in PATTERNS.values():
        for text in (cause, next_step):
            assert text.endswith(".")
            assert text.count(". ") <= 1  # one or two sentences
            assert len(text) <= 260
            assert "transaction" not in text.lower()


def dict_events(events: list[ExplainEvent]) -> list[dict[str, Any]]:
    return [dataclasses.asdict(e) for e in events]


@pytest.mark.parametrize("name", SCENARIOS)
def test_deterministic_and_input_not_mutated(name: str) -> None:
    events = SCENARIOS[name][0]
    snapshot = list(events)
    first = explain(events)
    assert first.pattern == name
    assert explain(events) == first
    assert explain(list(events)) == first
    assert explain(dict_events(events)) == first
    assert events == snapshot
    assert list(first.cited_event_seqs) == sorted(set(first.cited_event_seqs))


def test_explanation_is_frozen() -> None:
    result = explain(SCENARIOS["captured_first_time"][0])
    assert isinstance(result, Explanation)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.cause = "x"  # type: ignore[misc]


def test_order_of_input_does_not_matter() -> None:
    events = SCENARIOS["failed_after_retry"][0]
    assert explain(list(reversed(events))) == explain(events)
    assert explain(events).pattern == "failed_after_retry"


def test_free_text_never_reaches_the_output() -> None:
    events = timeline(
        RECEIVED,
        routed(1, "A"),
        ev(
            "attempt.authorize_result",
            1,
            "A",
            "insufficient_funds",
            result="declined",
            description="SECRET-DESC",
            note="SECRET-NOTE",
        ),
        declined(1, "A", "insufficient_funds"),
        final("declined"),
    )
    result = explain(events)
    assert result.pattern == "decline_insufficient_funds"
    assert "SECRET" not in f"{result.cause} {result.next_step}"


def test_late_decline_after_timeout_is_harmless() -> None:
    events = timeline(
        RECEIVED,
        routed(1, "A", "static"),
        failed(1, "A", "timeout"),
        final("failed"),
        late(1, "A", "after_timeout", "authorize", "declined"),
    )
    assert explain(events).pattern == "static_no_retry"


def test_empty_timeline_is_an_error() -> None:
    with pytest.raises(ValueError, match="no events"):
        explain([])
