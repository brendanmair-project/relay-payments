"""Model quality check (REL-25.8, ADR-0010, ADR-0012): `python -m app.explain.quality`, run by hand outside CI.

Asks the configured Ollama model to explain 10 fixed timelines and prints, per timeline, whether every citation
is valid and whether the stated cause matches the cause of the rules explainer for the same timeline, then a
summary line. Exit status 0 only when all citations are valid (the REL-25.8 criterion); a cause mismatch is
reported for review (ADR-0012) and does not by itself fail the run.
"""

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.explain.generate import CitationCheckFailed, ask_model
from app.explain.model import ModelClient, ModelUnavailable, OllamaClient
from app.explain.prompt import format_amount
from app.explain.rules import ExplainEvent, explain

Spec = tuple[str, int | None, str | None, str | None, dict[str, Any]]
AMOUNT_MINOR = 1250
CURRENCY = "USD"


def _t(*specs: Spec) -> list[ExplainEvent]:
    return [
        ExplainEvent(
            seq=i, type=t, attempt_no=a, processor=p, reason=r, data=d, occurred_at=f"2026-10-01T12:00:{i:02d}.000Z"
        )
        for i, (t, a, p, r, d) in enumerate(specs, 1)
    ]


def _ev(
    type_: str, attempt: int | None = None, proc: str | None = None, reason: str | None = None, **data: Any
) -> Spec:
    return (type_, attempt, proc, reason, data)


RECEIVED = _ev("payment.received", 0)


def _routed(attempt: int, proc: str, reason: str = "initial") -> Spec:
    return _ev("payment.routed", attempt, proc, reason)


def _auth(attempt: int, proc: str, result: str, reason: str | None = None) -> Spec:
    return _ev("attempt.authorize_result", attempt, proc, reason, result=result, latency_ms=120)


def _failed(attempt: int, proc: str, reason: str) -> Spec:
    return _ev("payment.failed", attempt, proc, reason)


def _final(outcome: str) -> Spec:
    return _ev("payment.final", None, None, None, outcome=outcome)


@dataclass(frozen=True)
class QualityTimeline:
    name: str
    pattern: str  # the cause the rules explainer must give (checked by a test)
    events: list[ExplainEvent]


TIMELINES: list[QualityTimeline] = [
    QualityTimeline(
        "insufficient funds",
        "decline_insufficient_funds",
        _t(
            RECEIVED,
            _routed(1, "A"),
            _auth(1, "A", "declined", "insufficient_funds"),
            _ev("payment.declined", 1, None, "insufficient_funds"),
            _final("declined"),
        ),
    ),
    QualityTimeline(
        "do not honor",
        "decline_do_not_honor",
        _t(
            RECEIVED,
            _routed(1, "B"),
            _auth(1, "B", "declined", "do_not_honor"),
            _ev("payment.declined", 1, None, "do_not_honor"),
            _final("declined"),
        ),
    ),
    QualityTimeline(
        "card expired",
        "decline_card_expired",
        _t(
            RECEIVED,
            _routed(1, "A"),
            _auth(1, "A", "declined", "card_expired"),
            _ev("payment.declined", 1, None, "card_expired"),
            _final("declined"),
        ),
    ),
    QualityTimeline(
        "authorize timeout",
        "authorize_timeout",
        _t(RECEIVED, _routed(1, "A"), _failed(1, "A", "timeout"), _final("failed")),
    ),
    QualityTimeline(
        "authorize outage",
        "authorize_outage",
        _t(
            RECEIVED,
            _routed(1, "A"),
            _auth(1, "A", "failed", "outage"),
            _failed(1, "A", "outage"),
            _final("failed"),
        ),
    ),
    QualityTimeline(
        "capture timeout",
        "capture_timeout",
        _t(
            RECEIVED,
            _routed(1, "A"),
            _auth(1, "A", "approved"),
            _ev("payment.authorized", 1, "A"),
            _failed(1, "A", "timeout"),
            _final("failed"),
        ),
    ),
    QualityTimeline(
        "both processors failed",
        "failed_after_retry",
        _t(
            RECEIVED,
            _routed(1, "A"),
            _auth(1, "A", "failed", "outage"),
            _failed(1, "A", "outage"),
            _ev("payment.retry_scheduled", 1),
            _routed(2, "B", "failover"),
            _auth(2, "B", "failed", "timeout"),
            _failed(2, "B", "timeout"),
            _final("failed"),
        ),
    ),
    QualityTimeline(
        "captured after failover",
        "captured_after_retry",
        _t(
            RECEIVED,
            _routed(1, "A"),
            _auth(1, "A", "failed", "outage"),
            _failed(1, "A", "outage"),
            _ev("payment.retry_scheduled", 1),
            _routed(2, "B", "failover"),
            _auth(2, "B", "approved"),
            _ev("payment.authorized", 2, "B"),
            _ev("payment.captured", 2),
            _final("captured"),
        ),
    ),
    QualityTimeline(
        "captured first time",
        "captured_first_time",
        _t(
            RECEIVED,
            _routed(1, "A"),
            _auth(1, "A", "approved"),
            _ev("payment.authorized", 1, "A"),
            _ev("payment.captured", 1),
            _final("captured"),
        ),
    ),
    QualityTimeline(
        "static routing, no retry",
        "static_no_retry",
        _t(RECEIVED, _routed(1, "A", "static"), _failed(1, "A", "timeout"), _final("failed")),
    ),
]


_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_AMOUNT = re.compile(rf"[$€£¥]\s?({_NUMBER})|({_NUMBER})\s?(?:USD|EUR|GBP|JPY)\b")


def amount_check(text: str, amount_minor: int, currency: str) -> str:
    """`none` when the text names no amount, `ok` when every amount it names is the payment's, else `wrong`."""
    expected = Decimal(format_amount(amount_minor, currency).split()[0])
    mentioned = [Decimal((m[0] or m[1]).replace(",", "")) for m in _AMOUNT.findall(text)]
    if not mentioned:
        return "none"
    return "ok" if all(value == expected for value in mentioned) else "wrong"


@dataclass
class Summary:
    total: int = 0
    citations_valid: int = 0
    cause_matches: int = 0
    unavailable: int = 0
    wrong_amount: int = 0

    @property
    def passed(self) -> bool:
        return self.total > 0 and self.citations_valid == self.total


def run_quality(model: ModelClient, out: Callable[[str], object] = print) -> Summary:
    summary = Summary()
    for item in TIMELINES:
        summary.total += 1
        expected = explain(item.events).pattern
        try:
            answer = ask_model(item.events, amount_minor=AMOUNT_MINOR, currency=CURRENCY, model=model)
        except ModelUnavailable as unavailable:
            summary.unavailable += 1
            out(f"{item.name}: model unavailable ({unavailable.reason})")
            continue
        except CitationCheckFailed as failure:
            out(f"{item.name}: citations_valid=no ({failure}) cause_match=no")
            continue
        summary.citations_valid += 1
        matches = answer.cause == expected
        summary.cause_matches += matches
        amount = amount_check(answer.text, AMOUNT_MINOR, CURRENCY)
        summary.wrong_amount += amount == "wrong"
        out(
            f"{item.name}: citations_valid=yes cause_match={'yes' if matches else 'no'} amount={amount}"
            f" (model said {answer.cause!r}, rules say {expected!r})"
        )
    out(
        f"SUMMARY model={model.name} citations_valid={summary.citations_valid}/{summary.total}"
        f" cause_match={summary.cause_matches}/{summary.total} wrong_amount={summary.wrong_amount}"
        f" unavailable={summary.unavailable}"
    )
    return summary


def main() -> int:
    client = OllamaClient(
        os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434"),
        os.environ.get("OLLAMA_MODEL", "granite3.3:2b"),
        float(os.environ.get("QUALITY_TIMEOUT_SECONDS", "120")),
    )
    return 0 if run_quality(client).passed else 1


if __name__ == "__main__":
    sys.exit(main())
