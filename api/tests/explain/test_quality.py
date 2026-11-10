"""REL-25.8: the quality check covers 10 fixed timelines and compares each stated cause with the rules' cause."""

import pytest

from app.explain import explain
from app.explain.quality import TIMELINES, run_quality
from tests.explain.fakes import answer


class EchoModel:
    """Cites the first event and states the cause the test dictates for each timeline in turn."""

    name = "granite3.3:2b"

    def __init__(self, causes: list[str | None], seqs: list[int] | None = None, text: str = "text") -> None:
        self.text = text
        self.causes = causes
        self.seqs = seqs
        self.calls = 0

    def generate(self, prompt: str) -> str:
        cause = self.causes[self.calls]
        self.calls += 1
        return answer(self.text, self.seqs or [1], cause)


def correct_causes() -> list[str | None]:
    return [explain(t.events).pattern for t in TIMELINES]


def test_there_are_ten_fixed_timelines_with_distinct_rule_causes() -> None:
    assert len(TIMELINES) == 10
    patterns = [explain(t.events).pattern for t in TIMELINES]
    assert patterns == [t.pattern for t in TIMELINES]
    assert len(set(patterns)) == 10
    assert "unknown" not in patterns


def test_all_valid_and_matching() -> None:
    lines: list[str] = []
    summary = run_quality(EchoModel(correct_causes()), out=lines.append)
    assert (summary.total, summary.citations_valid, summary.cause_matches, summary.unavailable) == (10, 10, 10, 0)
    assert summary.passed
    assert len(lines) == 11
    assert lines[-1].startswith("SUMMARY ")
    assert "citations_valid=10/10" in lines[-1]
    assert "cause_match=10/10" in lines[-1]


def test_invalid_citation_and_cause_mismatch_are_reported_per_timeline() -> None:
    causes = correct_causes()
    causes[3] = "decline_card_expired"  # a wrong cause
    lines: list[str] = []
    summary = run_quality(EchoModel(causes), out=lines.append)
    assert summary.cause_matches == 9
    assert summary.citations_valid == 10
    assert "cause_match=no" in lines[3]
    assert "cause_match=yes" in lines[0]
    bad = run_quality(EchoModel(correct_causes(), seqs=[999]), out=lambda line: None)
    assert bad.citations_valid == 0
    assert not bad.passed


def test_missing_cause_counts_as_a_mismatch() -> None:
    summary = run_quality(EchoModel([None] * 10), out=lambda line: None)
    assert (summary.citations_valid, summary.cause_matches) == (10, 0)


def test_unavailable_model_is_counted_and_fails_the_check() -> None:
    class Down:
        name = "granite3.3:2b"

        def generate(self, prompt: str) -> str:
            from app.explain.model import ModelUnavailable

            raise ModelUnavailable("model_unreachable")

    lines: list[str] = []
    summary = run_quality(Down(), out=lines.append)
    assert summary.unavailable == 10
    assert not summary.passed
    assert "model_unreachable" in lines[0]


def test_a_wrong_amount_is_flagged_and_counted() -> None:
    lines: list[str] = []
    summary = run_quality(EchoModel(correct_causes(), text="Declined for $1250.00 on the card."), out=lines.append)
    assert summary.wrong_amount == 10
    assert "amount=wrong" in lines[0]
    assert "wrong_amount=10" in lines[-1]


@pytest.mark.parametrize(
    "text", ["The payment of $12.50 was declined.", "Declined (12.50 USD).", "Event 3 shows a decline.", "12.5 USD"]
)
def test_correct_or_absent_amounts_are_not_flagged(text: str) -> None:
    lines: list[str] = []
    summary = run_quality(EchoModel(correct_causes(), text=text), out=lines.append)
    assert summary.wrong_amount == 0
    assert "wrong_amount=0" in lines[-1]
    assert ("amount=ok" in lines[0]) == ("12.5" in text)
    assert ("amount=none" in lines[0]) == ("12.5" not in text)
