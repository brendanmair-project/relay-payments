"""Pure comparison of a static-routing baseline run and a Relay run over the same references (REL-30, ADR-0012).

Every function takes `outcomes`: {reference: {"status", "currency", "amount_minor"}} saved from one run through the
public API. Standard library only; the host script `scripts/outage_demo.py` calls these and `demo.render`.

Definitions (also printed next to the results):
- Success rate: payments that ended `captured` divided by all payments of the run, as a percentage. Declines are
  cardholder outcomes and count as not captured in both modes alike.
- Uplift: Relay success rate minus baseline success rate, in percentage points.
- Revenue recovered: for each currency, the amount (minor units) captured in the Relay run minus the amount captured in
  the baseline run, over the same references. Currencies are never added together.
- Paired comparison: each reference is looked up in both runs; `improved` means not captured in the baseline and
  captured in the Relay run, `worsened` the reverse.
- Median time to explanation: median of (stored explanation time - final failure time) over every automatic
  explanation of the Relay run, from the reporting tool (`explanations.all.p50_ms`).
- Recovery lag: seconds from the generator switching an outage off until the router's health state for that processor
  is no longer `avoided` (polled once a second from GET /processors/health; None when it did not change within the
  wait of one health window plus 5 s).
- Reproducibility: the spread (max - min) over the runs, in percentage points for success rates and as a percentage of
  the largest value for revenue recovered per currency.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

MANUAL_BASELINE_SECONDS = 7200  # assumption (ADR-0009): 2 hours to reconstruct one failed payment by hand
SUCCESS_TOLERANCE_PP = 1.0
REVENUE_TOLERANCE_PCT = 1.0
RESCUE_PATHS = ("retry", "failover", "redrive")
BASELINE_DESCRIPTION = (
    "static routing: ROUTING_STRATEGY=static, every payment to Processor A, no failover, no retry (ADR-0009)"
)

Outcomes = dict[str, dict[str, Any]]


def success_rate(outcomes: Outcomes) -> float | None:
    """Captured payments over all payments, as a fraction; None for an empty run."""
    if not outcomes:
        return None
    return sum(1 for o in outcomes.values() if o["status"] == "captured") / len(outcomes)


def uplift_pp(baseline_rate: float, relay_rate: float) -> float:
    return (relay_rate - baseline_rate) * 100


def _require_same_payments(baseline: Outcomes, relay: Outcomes) -> None:
    same = baseline.keys() == relay.keys() and all(
        (baseline[ref]["currency"], baseline[ref]["amount_minor"])
        == (relay[ref]["currency"], relay[ref]["amount_minor"])
        for ref in baseline
    )
    if not same:
        raise ValueError("the baseline and Relay runs do not have the same references with the same amounts")


def _captured_by_currency(outcomes: Outcomes) -> dict[str, int]:
    totals: dict[str, int] = {}
    for o in outcomes.values():
        if o["status"] == "captured":
            totals[o["currency"]] = totals.get(o["currency"], 0) + o["amount_minor"]
    return totals


def revenue_recovered(baseline: Outcomes, relay: Outcomes) -> dict[str, int]:
    """Per currency, minor units captured by Relay minus captured by the baseline, over the same references."""
    _require_same_payments(baseline, relay)
    base, rel = _captured_by_currency(baseline), _captured_by_currency(relay)
    return {c: rel.get(c, 0) - base.get(c, 0) for c in sorted(set(base) | set(rel))}


def pair_outcomes(baseline: Outcomes, relay: Outcomes) -> dict[str, Any]:
    """Compare the two runs payment by payment, by reference."""
    _require_same_payments(baseline, relay)
    improved_from: Counter[str] = Counter()
    worsened: list[str] = []
    improved = 0
    for ref in sorted(baseline):
        before, after = baseline[ref]["status"], relay[ref]["status"]
        if before != "captured" and after == "captured":
            improved += 1
            improved_from[before] += 1
        elif before == "captured" and after != "captured":
            worsened.append(ref)
    return {
        "references": len(baseline),
        "improved": improved,
        "improved_from": dict(sorted(improved_from.items())),
        "worsened": len(worsened),
        "worsened_references": worsened,
        "unchanged": len(baseline) - improved - len(worsened),
    }


def reproducibility(values: list[float], tolerance: float, *, relative: bool) -> dict[str, Any]:
    """Spread of one measure over several runs against a tolerance (percentage points, or percent when relative)."""
    spread = max(values) - min(values)
    if relative:
        largest = max(abs(v) for v in values)
        spread = spread / largest * 100 if largest else 0.0
    return {"values": values, "spread": round(spread, 4), "tolerance": tolerance, "pass": spread <= tolerance}


def _pct(rate: float) -> float:
    return round(rate * 100, 2)


def _run_summary(number: int, run: dict[str, Any]) -> dict[str, Any]:
    base, rel = run["baseline"], run["relay"]
    base_rate, rel_rate = success_rate(base["outcomes"]), success_rate(rel["outcomes"])
    if base_rate is None or rel_rate is None:
        raise ValueError(f"run {number} has no payments")
    rescue = rel["report"]["rescue_paths"]
    relay_explanations = rel["report"]["explanations"]
    median = relay_explanations["all"]["p50_ms"] if relay_explanations.get("available") else None
    recovery = rel.get("recovery_lags", [])
    return {
        "run": number,
        "baseline_success_rate_pct": _pct(base_rate),
        "relay_success_rate_pct": _pct(rel_rate),
        "uplift_pp": round(uplift_pp(base_rate, rel_rate), 2),
        "revenue_recovered": revenue_recovered(base["outcomes"], rel["outcomes"]),
        "revenue_by_rescue_path": {path: rescue[path]["amount_minor_by_currency"] for path in RESCUE_PATHS},
        "rescued_payments_by_path": {path: rescue[path]["count"] for path in RESCUE_PATHS},
        "pairing": pair_outcomes(base["outcomes"], rel["outcomes"]),
        "median_time_to_explanation_ms": median,
        "manual_baseline_ratio": round(MANUAL_BASELINE_SECONDS * 1000 / median, 1) if median else None,
        "explanations": {"baseline": base["report"]["explanations"], "relay": relay_explanations},
        "recovery_lag_seconds": recovery[0]["lag_seconds"] if recovery else None,
        "recovery_lags": {"baseline": base.get("recovery_lags", []), "relay": recovery},
    }


def routing_from_events(events: list[dict[str, Any]]) -> list[str]:
    """The routed events of a payment timeline in order, as `<processor>:<reason>` (for example `A:initial`)."""
    routed = sorted((e for e in events if e.get("type") == "payment.routed"), key=lambda e: e.get("seq", 0))
    return [f"{e.get('processor')}:{e.get('reason')}" for e in routed]


def _signature(outcome: dict[str, Any]) -> tuple[Any, ...]:
    return outcome["status"], outcome.get("processor"), tuple(outcome.get("routing", []))


def routing_differences(runs: list[Outcomes]) -> list[dict[str, Any]]:
    """References whose status, handling processor or routing differ between the runs, with each run's values."""
    differing = []
    for reference in sorted(runs[0]):
        entries = [run[reference] for run in runs]
        if len({_signature(e) for e in entries}) > 1:
            differing.append(
                {
                    "reference": reference,
                    "per_run": [
                        {"status": e["status"], "processor": e.get("processor"), "routing": e.get("routing", [])}
                        for e in entries
                    ],
                }
            )
    return differing


def build_results(
    seed: int, scenario: str, runs: list[dict[str, Any]], health_window_seconds: int = 60
) -> dict[str, Any]:
    """Everything the results page and `results.json` report.

    `runs` holds, per run, the baseline and Relay `outcomes` and the reporting tool's `report` for each.
    """
    summaries = [_run_summary(i, run) for i, run in enumerate(runs, start=1)]
    repro = None
    if len(summaries) >= 2:
        currencies = sorted({c for s in summaries for c in s["revenue_recovered"]})
        revenue = {
            c: reproducibility(
                [s["revenue_recovered"].get(c, 0) for s in summaries], REVENUE_TOLERANCE_PCT, relative=True
            )
            for c in currencies
        }
        success = reproducibility(
            [s["relay_success_rate_pct"] for s in summaries], SUCCESS_TOLERANCE_PP, relative=False
        )
        baseline = reproducibility(
            [s["baseline_success_rate_pct"] for s in summaries], SUCCESS_TOLERANCE_PP, relative=False
        )
        repro = {
            "runs": len(summaries),
            "success_rate_pp": success,
            "baseline_success_rate_pp": baseline,
            "revenue_recovered": revenue,
            "differing_references": {
                mode: routing_differences([run[mode]["outcomes"] for run in runs]) for mode in ("baseline", "relay")
            },
            "pass": success["pass"] and baseline["pass"] and all(r["pass"] for r in revenue.values()),
        }
    return {
        "synthetic": True,
        "scenario": scenario,
        "seed": seed,
        "baseline_description": BASELINE_DESCRIPTION,
        "manual_baseline_seconds": MANUAL_BASELINE_SECONDS,
        "health_window_seconds": health_window_seconds,
        "tolerance": {"success_rate_pp": SUCCESS_TOLERANCE_PP, "revenue_recovered_pct": REVENUE_TOLERANCE_PCT},
        "runs": summaries,
        "reproducibility": repro,
    }
