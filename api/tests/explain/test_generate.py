"""REL-25.1/25.3: model answers are checked against the timeline; anything else falls back to the rules, labelled."""

import json

import pytest

from app.explain import ExplainEvent, explain
from app.explain.generate import generate_explanation
from tests.explain.fakes import FakeModel, answer

EVENTS = [
    ExplainEvent(seq=1, type="payment.received", attempt_no=0),
    ExplainEvent(seq=2, type="payment.routed", attempt_no=1, processor="A", reason="initial"),
    ExplainEvent(
        seq=3,
        type="attempt.authorize_result",
        attempt_no=1,
        processor="A",
        reason="insufficient_funds",
        data={"result": "declined"},
    ),
    ExplainEvent(seq=4, type="payment.declined", attempt_no=1, reason="insufficient_funds"),
    ExplainEvent(seq=5, type="payment.final", data={"outcome": "declined"}),
]


RIGHT_CAUSE = "decline_insufficient_funds"


def run(model: FakeModel | None):  # type: ignore[no-untyped-def]
    return generate_explanation(EVENTS, amount_minor=1250, currency="USD", model=model)


def test_valid_model_answer_is_used_and_labelled_model() -> None:
    model = FakeModel(answer("The card was declined for insufficient funds (event 3).", [3, 4], cause=RIGHT_CAUSE))
    result = run(model)
    assert result.source == "model"
    assert result.model == "granite3.3:2b"
    assert result.text.startswith("The card was declined")
    assert result.cited_event_seqs == (3, 4)
    assert result.fallback_reason is None
    assert len(model.prompts) == 1


def test_citation_outside_the_timeline_falls_back_to_rules() -> None:
    result = run(FakeModel(answer("Declined.", [3, 99])))
    expected = explain(EVENTS)
    assert result.source == "rules"
    assert result.model is None
    assert result.fallback_reason == "citation_check_failed"
    assert result.cited_event_seqs == expected.cited_event_seqs
    assert expected.cause in result.text


@pytest.mark.parametrize(
    "reply",
    [
        "not json at all",
        json.dumps(["a list"]),
        json.dumps({"text": "no citations"}),
        json.dumps({"text": "empty", "cited_event_seqs": []}),
        json.dumps({"text": "", "cited_event_seqs": [1]}),
        json.dumps({"text": "bad type", "cited_event_seqs": ["3"]}),
        json.dumps({"text": "bool", "cited_event_seqs": [True]}),
    ],
)
def test_unparseable_or_ungrounded_answers_fall_back(reply: str) -> None:
    result = run(FakeModel(reply))
    assert (result.source, result.fallback_reason) == ("rules", "citation_check_failed")


@pytest.mark.parametrize("reason", ["model_timeout", "model_unreachable", "model_error"])
def test_unavailable_model_falls_back_and_says_why(reason: str) -> None:
    result = run(FakeModel(unavailable=reason))
    assert (result.source, result.model, result.fallback_reason) == ("rules", None, reason)
    assert result.text


def test_no_model_configured_is_unreachable() -> None:
    result = run(None)
    assert (result.source, result.fallback_reason) == ("rules", "model_unreachable")


def test_different_cause_uses_rules_text_with_cause_mismatch() -> None:
    result = run(FakeModel(answer("The processor timed out (event 3).", [3, 4], cause="authorize_timeout")))
    expected = explain(EVENTS)
    assert result.source == "rules"
    assert result.model is None
    assert result.fallback_reason == "cause_mismatch"
    assert expected.cause in result.text
    assert "timed out" not in result.text
    assert result.cited_event_seqs == expected.cited_event_seqs


def test_missing_cause_is_a_mismatch() -> None:
    result = run(FakeModel(answer("The card was declined (event 3).", [3, 4])))
    assert (result.source, result.fallback_reason) == ("rules", "cause_mismatch")


def test_same_cause_keeps_model_text() -> None:
    result = run(FakeModel(answer("Declined for funds (event 3).", [3, 4], cause=RIGHT_CAUSE)))
    assert (result.source, result.fallback_reason) == ("model", None)
    assert result.text.startswith("Declined for funds")
