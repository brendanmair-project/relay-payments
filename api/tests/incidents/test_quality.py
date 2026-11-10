"""REL-35.8 (PR-31): the quality check runs 6 fixed synthetic incidents and reports citation validity and the
fallback rate per reason."""

import json

from app.incidents.quality import SCENARIOS, run_quality
from app.incidents.summary import generate_summary, rules_summary
from tests.explain.fakes import FakeModel


class Echo:
    """Answers each scenario with its rules cause and the first linked event, unless told otherwise."""

    name = "granite3.3:2b"

    def __init__(self, cause: str | None = None, ids: list[int] | None = None) -> None:
        self.cause, self.ids, self.calls = cause, ids, 0

    def generate(self, prompt: str) -> str:
        scenario = SCENARIOS[self.calls]
        self.calls += 1
        first = scenario.facts.events[0].id
        cause = self.cause or rules_summary(scenario.facts).cause
        return json.dumps({"text": "t", "cited_event_ids": self.ids or [first], "cause": cause})


def test_there_are_six_fixed_incidents_whose_rules_causes_are_as_named() -> None:
    assert len(SCENARIOS) == 6
    assert len({s.name for s in SCENARIOS}) == 6
    for scenario in SCENARIOS:
        assert rules_summary(scenario.facts).cause == scenario.cause, scenario.name
    causes = {s.cause for s in SCENARIOS}
    assert {"outage", "timeouts", "mixed"} <= causes
    assert any(s.facts.recovered_at is not None and s.facts.resolved_at is None for s in SCENARIOS)
    assert any(any(p.rescued for p in s.facts.payments) for s in SCENARIOS)
    assert all(s.facts.events for s in SCENARIOS)
    assert min(len(s.facts.payments) for s in SCENARIOS) <= 3


def test_every_scenario_yields_a_valid_model_summary_for_a_faithful_model() -> None:
    for scenario in SCENARIOS:
        model = FakeModel(
            json.dumps(
                {
                    "text": "t",
                    "cited_event_ids": [scenario.facts.events[0].id],
                    "cause": scenario.cause,
                }
            )
        )
        assert generate_summary(scenario.facts, model).source == "model", scenario.name


def test_all_valid_reports_no_fallbacks() -> None:
    lines: list[str] = []
    summary = run_quality(Echo(), out=lines.append)
    assert (summary.total, summary.citations_valid, summary.cause_matches, summary.fallbacks) == (6, 6, 6, {})
    assert summary.passed
    assert len(lines) == 7
    assert lines[-1].startswith("SUMMARY model=granite3.3:2b")
    assert "citations_valid=6/6" in lines[-1] and "cause_match=6/6" in lines[-1] and "fallback_rate=0/6" in lines[-1]


def test_fallbacks_are_counted_per_reason() -> None:
    lines: list[str] = []
    mismatch = run_quality(Echo(cause="timeouts"), out=lines.append)
    assert mismatch.citations_valid == 6
    assert mismatch.fallbacks["cause_mismatch"] >= 1
    assert sum(mismatch.fallbacks.values()) == mismatch.total - mismatch.cause_matches
    assert "cause_mismatch=" in lines[-1]
    assert "cause_match=no" in "\n".join(lines[:-1])
    outside = run_quality(Echo(ids=[10**9]), out=lambda line: None)
    assert (outside.citations_valid, outside.fallbacks) == (0, {"citation_check_failed": 6})
    assert not outside.passed


def test_an_unavailable_model_is_a_fallback_with_its_reason() -> None:
    lines: list[str] = []
    summary = run_quality(FakeModel(unavailable="model_unreachable"), out=lines.append)
    assert summary.fallbacks == {"model_unreachable": 6}
    assert (summary.citations_valid, summary.cause_matches) == (0, 0)
    assert "model_unreachable" in lines[0]
