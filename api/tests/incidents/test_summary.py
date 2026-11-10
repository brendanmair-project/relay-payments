"""REL-35.3/35.4 (ADR-0005, ADR-0013): the rules summary is deterministic from the linked events; the model summary
cites only linked events and agrees with the rules cause, otherwise the rules summary is stored with its reason."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.incidents.summary import (
    CAUSES,
    AffectedPayment,
    IncidentFacts,
    LinkedEvent,
    build_prompt,
    generate_summary,
    rules_summary,
)
from tests.explain.fakes import FakeModel

T0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)
SENTINEL = "relay-test-sentinel-description"


def event(event_id: int, payment: str, reason: str, seconds: int = 0, type_: str = "payment.failed") -> LinkedEvent:
    return LinkedEvent(event_id, payment, type_, reason, "A", T0 + timedelta(seconds=seconds))


def payment(pid: str, rescued: bool = False, amount_minor: int = 1250) -> AffectedPayment:
    return AffectedPayment(pid, "captured" if rescued else "failed", amount_minor, "USD", rescued)


def facts(
    events: list[LinkedEvent], payments: list[AffectedPayment], recovered: int | None = 120, resolved: int | None = None
) -> IncidentFacts:
    return IncidentFacts(
        processor="A",
        opened_at=T0,
        recovered_at=T0 + timedelta(seconds=recovered) if recovered is not None else None,
        resolved_at=T0 + timedelta(seconds=resolved) if resolved is not None else None,
        payments=payments,
        events=events,
    )


def outage_facts() -> IncidentFacts:
    return facts(
        [event(11, "p1", "outage", 1), event(12, "p2", "outage", 2), event(13, "p3", "outage", 3)],
        [payment("p1", rescued=True), payment("p2", rescued=True), payment("p3")],
    )


def reply(text: str = "Processor A had an outage.", ids: object = (11, 12), cause: object = "outage") -> str:
    return json.dumps({"text": text, "cited_event_ids": ids, "cause": cause})


def test_the_cause_list_is_fixed() -> None:
    assert set(CAUSES) == {"outage", "timeouts", "mixed"}


def test_the_rules_summary_covers_processor_counts_rescues_and_recovery() -> None:
    summary = rules_summary(outage_facts())
    assert summary.cause == "outage"
    assert "Processor A" in summary.text
    assert "3 payments" in summary.text
    assert "3 outage" in summary.text
    assert "2 " in summary.text and "rescued" in summary.text
    assert "120 seconds" in summary.text
    assert "2026-11-01T12:00:01.000Z" in summary.text and "2026-11-01T12:00:03.000Z" in summary.text
    assert set(summary.cited_event_ids) <= {11, 12, 13}
    assert summary.cited_event_ids


def test_the_rules_summary_is_deterministic() -> None:
    assert rules_summary(outage_facts()) == rules_summary(outage_facts())


def test_timeouts_and_mixed_causes() -> None:
    timeouts = facts([event(1, "p1", "timeout"), event(2, "p2", "timeout")], [payment("p1"), payment("p2")])
    assert rules_summary(timeouts).cause == "timeouts"
    assert "2 timeout" in rules_summary(timeouts).text
    mixed = facts([event(1, "p1", "timeout"), event(2, "p2", "outage")], [payment("p1"), payment("p2")])
    assert rules_summary(mixed).cause == "mixed"
    assert "1 outage" in rules_summary(mixed).text and "1 timeout" in rules_summary(mixed).text


def test_a_payment_failing_twice_counts_once() -> None:
    twice = facts(
        [event(1, "p1", "outage", 1, "attempt.authorize_result"), event(2, "p1", "outage", 1)], [payment("p1")]
    )
    assert "1 payment " in rules_summary(twice).text


def test_without_recovery_the_summary_says_so() -> None:
    open_ = facts([event(1, "p1", "outage")], [payment("p1")], recovered=None)
    assert "not recovered" in rules_summary(open_).text
    resolved = facts([event(1, "p1", "outage")], [payment("p1")], recovered=None, resolved=300)
    assert "resolved" in rules_summary(resolved).text


def test_the_model_summary_is_used_when_valid() -> None:
    model = FakeModel(reply())
    generated = generate_summary(outage_facts(), model)
    assert (generated.source, generated.model, generated.fallback_reason) == ("model", "granite3.3:2b", None)
    assert generated.text == "Processor A had an outage."
    assert generated.cited_event_ids == (11, 12)
    assert generated.cause == "outage"


@pytest.mark.parametrize(
    "bad",
    [
        reply(ids=(11, 999)),  # an event that is not linked
        reply(ids=[]),
        reply(ids=["11"]),
        reply(ids=[True]),
        reply(text="  "),
        "not json",
        json.dumps({"text": "x"}),
    ],
)
def test_a_bad_citation_falls_back_to_the_rules_summary(bad: str) -> None:
    generated = generate_summary(outage_facts(), FakeModel(bad))
    assert generated.source == "rules" and generated.model is None
    assert generated.fallback_reason == "citation_check_failed"
    assert generated.text == rules_summary(outage_facts()).text
    assert generated.cause == "outage"


@pytest.mark.parametrize("reason", ["model_timeout", "model_unreachable", "model_error"])
def test_a_model_failure_falls_back_with_its_reason(reason: str) -> None:
    generated = generate_summary(outage_facts(), FakeModel(unavailable=reason))
    assert (generated.source, generated.fallback_reason) == ("rules", reason)
    assert generated.text == rules_summary(outage_facts()).text


def test_no_model_is_model_unreachable() -> None:
    assert generate_summary(outage_facts(), None).fallback_reason == "model_unreachable"


@pytest.mark.parametrize("cause", ["timeouts", "mixed", "something else", None])
def test_a_cause_that_disagrees_with_the_rules_falls_back(cause: object) -> None:
    generated = generate_summary(outage_facts(), FakeModel(reply(cause=cause)))
    assert (generated.source, generated.fallback_reason) == ("rules", "cause_mismatch")
    assert generated.text == rules_summary(outage_facts()).text


def test_no_linked_events_means_no_model_call() -> None:
    model = FakeModel(reply())
    generated = generate_summary(facts([], []), model)
    assert model.prompts == []
    assert (generated.source, generated.fallback_reason, generated.cause) == ("rules", "no_linked_events", "none")


def test_the_prompt_names_the_linked_events_and_formats_amounts_from_minor_units() -> None:
    prompt = build_prompt(outage_facts())
    for number in ("[11]", "[12]", "[13]"):
        assert number in prompt
    assert "37.50 USD" in prompt  # 3 payments of 1250 minor units
    assert "3750" not in prompt and "1250" not in prompt
    for cause in CAUSES:
        assert cause in prompt


def test_the_prompt_is_bounded_for_a_large_incident() -> None:
    many = facts([event(i, f"p{i}", "outage", i) for i in range(1, 501)], [payment(f"p{i}") for i in range(1, 501)])
    prompt = build_prompt(many)
    assert prompt.count("\n[") <= 40
    assert "[1]" in prompt and "[500]" in prompt
    generated = generate_summary(many, FakeModel(reply(ids=(250,))))  # linked, though not shown: still valid
    assert generated.source == "model"
    assert generate_summary(many, FakeModel(reply(ids=(501,)))).fallback_reason == "citation_check_failed"


def test_the_prompt_carries_no_payment_description() -> None:
    model = FakeModel(reply())
    generate_summary(outage_facts(), model)
    assert model.prompts and all(SENTINEL not in p for p in model.prompts)
