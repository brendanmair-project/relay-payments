"""Incident summary quality check (REL-35, PR-31): `python -m app.incidents.quality`, run by hand outside CI.

Runs the configured Ollama model on 6 fixed synthetic incidents through the same path as the API
(`generate_summary`) and prints, per incident, whether the answer was kept or which `fallback_reason` replaced it,
then a summary line: citation validity (answers whose citations are all linked events, of all runs), cause match
and the fallback count per reason. Exit status 0 only when every citation is valid; a cause mismatch is a counted
fallback, not a failure (ADR-0013).
"""

import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.explain.model import ModelClient, OllamaClient
from app.incidents.summary import (
    AffectedPayment,
    IncidentFacts,
    LinkedEvent,
    generate_summary,
    rules_summary,
)

T0 = datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC)
CITATION_FALLBACKS = {"citation_check_failed"}
NOT_ANSWERED = {"model_timeout", "model_unreachable", "model_error"}


@dataclass(frozen=True)
class Scenario:
    name: str
    cause: str  # the cause the rules summary must give (checked by a test)
    facts: IncidentFacts


def _facts(
    reasons: list[str], *, rescued: int = 0, recovered: int | None = 90, both_events: int = 0, start_id: int = 5000
) -> IncidentFacts:
    """One payment per reason: its `payment.failed` event, plus an attempt result for the first `both_events`."""
    events: list[LinkedEvent] = []
    payments: list[AffectedPayment] = []
    next_id = start_id
    for i, reason in enumerate(reasons):
        pid = f"payment-{i + 1}"
        at = T0 + timedelta(seconds=3 * i)
        if i < both_events and reason in ("outage", "timeout"):
            events.append(LinkedEvent(next_id, pid, "attempt.authorize_result", reason, "A", at))
            next_id += 1
        events.append(LinkedEvent(next_id, pid, "payment.failed", reason, "A", at))
        next_id += 3  # other events of other payments sit between the linked ones
        saved = i < rescued
        payments.append(
            AffectedPayment(pid, "captured" if saved else "failed", 1250 + 100 * i, "USD", saved, "B" if saved else "A")
        )
    return IncidentFacts(
        "A",
        T0,
        T0 + timedelta(seconds=recovered) if recovered is not None else None,
        None,
        payments,
        events,
    )


SCENARIOS: list[Scenario] = [
    Scenario("pure outage", "outage", _facts(["outage"] * 12, both_events=4)),
    Scenario("pure timeouts", "timeouts", _facts(["timeout"] * 10)),
    Scenario(
        "mixed outage, timeouts and capture failures",
        "mixed",
        _facts(["outage"] * 5 + ["timeout"] * 5 + ["capture_failed"] * 2),
    ),
    Scenario("outage with failover rescues", "outage", _facts(["outage"] * 15, rescued=11, both_events=6)),
    Scenario("small incident", "timeouts", _facts(["timeout"] * 2, rescued=1)),
    Scenario("recovery without resolution", "outage", _facts(["outage"] * 8, rescued=3, recovered=45)),
]


@dataclass
class Summary:
    total: int = 0
    citations_valid: int = 0
    cause_matches: int = 0
    fallbacks: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return (
            self.total > 0
            and self.fallbacks.get("citation_check_failed", 0) == 0
            and not any(reason in self.fallbacks for reason in NOT_ANSWERED)
        )


def run_quality(model: ModelClient, out: Callable[[str], object] = print) -> Summary:
    summary = Summary()
    reasons: Counter[str] = Counter()
    for scenario in SCENARIOS:
        summary.total += 1
        generated = generate_summary(scenario.facts, model)
        reason = generated.fallback_reason
        if reason is not None:
            reasons[reason] += 1
        answered = reason not in CITATION_FALLBACKS | NOT_ANSWERED
        summary.citations_valid += answered
        matched = reason is None
        summary.cause_matches += matched
        expected = rules_summary(scenario.facts).cause
        out(
            f"{scenario.name}: citations_valid={'yes' if answered else 'no'} cause_match={'yes' if matched else 'no'}"
            f" fallback_reason={reason or 'none'} (rules say {expected!r})"
        )
    summary.fallbacks = dict(reasons)
    per_reason = " ".join(f"{reason}={count}" for reason, count in sorted(reasons.items())) or "none"
    out(
        f"SUMMARY model={model.name} citations_valid={summary.citations_valid}/{summary.total}"
        f" cause_match={summary.cause_matches}/{summary.total}"
        f" fallback_rate={sum(reasons.values())}/{summary.total} by_reason: {per_reason}"
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
