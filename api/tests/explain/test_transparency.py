"""REL-63: every generation path records the attempted model, both causes, the time taken and the inputs."""

import json

import pytest

from app.explain import ExplainEvent, explain
from app.explain import prompt as prompt_module
from app.explain.generate import generate_explanation
from tests.explain.fakes import FakeModel, answer
from tests.explain.test_generate import EVENTS, RIGHT_CAUSE

SENTINEL = "relay-test-sentinel-description"


def run(model: FakeModel | None):  # type: ignore[no-untyped-def]
    return generate_explanation(EVENTS, amount_minor=1250, currency="USD", model=model)


def test_inputs_are_the_facts_the_prompt_uses() -> None:
    inputs = prompt_module.prompt_inputs(EVENTS, amount_minor=1250, currency="USD")
    assert inputs["status"] == "declined"
    assert inputs["reason_codes"] == ["initial", "insufficient_funds"]
    assert inputs["amount"] == "12.50 USD"
    events = inputs["events"]
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]
    assert events[2] == {
        "seq": 3,
        "type": "attempt.authorize_result",
        "time": None,
        "attempt": 1,
        "processor": "A",
        "reason": "insufficient_funds",
        "result": "declined",
        "outcome": None,
    }
    assert events[4]["outcome"] == "declined"


def test_inputs_never_contain_a_free_text_value() -> None:
    hostile = [
        ExplainEvent(seq=1, type="payment.received", attempt_no=0, data={"description": SENTINEL, "result": 7}),
        ExplainEvent(seq=2, type="payment.final", data={"outcome": 5, "note": SENTINEL, "description": SENTINEL}),
    ]
    inputs = prompt_module.prompt_inputs(hostile, amount_minor=100, currency="USD")
    assert SENTINEL not in json.dumps(inputs)
    assert all(e["result"] is None and e["outcome"] is None for e in inputs["events"])


def test_agreed_records_everything() -> None:
    result = run(FakeModel(answer("Declined for funds (event 3).", [3, 4], cause=RIGHT_CAUSE)))
    assert result.source == "model"
    assert result.attempted_model == "granite3.3:2b"
    assert result.model_cause == RIGHT_CAUSE
    assert result.rules_cause == explain(EVENTS).pattern == RIGHT_CAUSE
    assert result.generation_ms is not None and result.generation_ms >= 0
    assert result.inputs == prompt_module.prompt_inputs(EVENTS, amount_minor=1250, currency="USD")


def test_disagreement_keeps_both_causes_and_the_attempted_model() -> None:
    result = run(FakeModel(answer("The processor timed out (event 3).", [3, 4], cause="authorize_timeout")))
    assert (result.source, result.model, result.fallback_reason) == ("rules", None, "cause_mismatch")
    assert result.attempted_model == "granite3.3:2b"
    assert result.model_cause == "authorize_timeout"
    assert result.rules_cause == RIGHT_CAUSE
    assert result.generation_ms is not None and result.generation_ms >= 0
    assert result.inputs is not None


@pytest.mark.parametrize("reason", ["model_timeout", "model_unreachable", "model_error"])
def test_unavailable_model_records_the_attempt_and_time(reason: str) -> None:
    result = run(FakeModel(unavailable=reason))
    assert (result.source, result.fallback_reason) == ("rules", reason)
    assert result.attempted_model == "granite3.3:2b"
    assert result.model_cause is None
    assert result.rules_cause == RIGHT_CAUSE
    assert result.generation_ms is not None and result.generation_ms >= 0
    assert result.inputs is not None


def test_unusable_answer_records_the_attempt_without_a_model_cause() -> None:
    result = run(FakeModel(answer("Declined.", [3, 99], cause=RIGHT_CAUSE)))
    assert result.fallback_reason == "citation_check_failed"
    assert result.attempted_model == "granite3.3:2b"
    assert result.model_cause is None
    assert result.generation_ms is not None


def test_rules_only_has_no_attempt_and_no_time() -> None:
    result = run(None)
    assert (result.source, result.fallback_reason) == ("rules", "model_unreachable")
    assert result.attempted_model is None
    assert result.model_cause is None
    assert result.generation_ms is None
    assert result.rules_cause == RIGHT_CAUSE
    assert result.inputs is not None
