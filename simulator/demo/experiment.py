"""Pure logic of the routing experiment harness (REL-43, ADR-0016); the host script `scripts/routing_experiment.py`
drives the compose stack and calls these. Standard library only.

Objective (fixed before any strategy is compared): the success rate, captured payments over final payments (the
REL-57 definition, declines included), compared per seed on identical payment references. Revenue captured per
currency is reported alongside; p95 creation-to-final latency (the reporting tool's `latency.p95_ms`) is a guardrail.

Pair: candidate minus baseline on the same scenario and seed. Per scenario: the mean paired difference, the share of
pairs where the candidate is strictly better, and the latency ratio (the candidate's mean p95 over the baseline's
mean p95 across the seeds). Win rule (ADR-0016, over every scenario and seed against the baseline): mean uplift at
least MEAN_UPLIFT_PP, strictly better on at least WIN_SHARE_PERCENT of the pairs, and the latency ratio at most
100 + LATENCY_MARGIN_PERCENT percent in every scenario. Every edge is inclusive and compared exactly (fractions).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from generator.scenarios import ControlStep, ProfileStep

from .compare import reproducibility

MEAN_UPLIFT_PP = 1
WIN_SHARE_PERCENT = 80
LATENCY_MARGIN_PERCENT = 10
FINAL_STATUSES = ("captured", "declined", "failed")
OBJECTIVE = (
    "Success rate: payments that ended captured over final payments (declines count as not captured), compared per "
    "seed on identical payment references. Revenue captured per currency is reported alongside; p95 "
    "creation-to-final latency is a guardrail (ADR-0016)."
)

Outcomes = dict[str, dict[str, Any]]


@dataclass(frozen=True)
class RunSpec:
    scenario: str
    seed: int
    strategy: str

    @property
    def name(self) -> str:
        return f"{self.scenario}-{self.seed}-{self.strategy}"

    @property
    def prefix(self) -> str:
        """The reference prefix the load generator gives this scenario and seed."""
        return f"{self.scenario}-{self.seed}-"


def plan_runs(scenarios: Iterable[str], seeds: Iterable[int], strategies: Iterable[str]) -> list[RunSpec]:
    """Scenario by seed by strategy, strategies innermost so a pair runs back to back."""
    scenarios, seeds, strategies = list(scenarios), list(seeds), list(strategies)
    for label, values in (("scenarios", scenarios), ("seeds", seeds), ("strategies", strategies)):
        if not values:
            raise ValueError(f"no {label} given")
        if len(set(values)) != len(values):
            raise ValueError(f"duplicate {label} given")
    return [RunSpec(sc, seed, st) for sc in scenarios for seed in seeds for st in strategies]


def _success(captured: int, final: int) -> Fraction:
    return Fraction(captured, final) if final else Fraction(0)


def _captured_by_currency(outcomes: Outcomes) -> dict[str, int]:
    totals: dict[str, int] = {}
    for o in outcomes.values():
        if o["status"] == "captured":
            totals[o["currency"]] = totals.get(o["currency"], 0) + o["amount_minor"]
    return dict(sorted(totals.items()))


def outcome_digest(outcomes: Outcomes) -> str:
    """A hash of every reference's status, handling processor and routing, so two runs can be compared exactly."""
    material = {ref: [o.get("status"), o.get("processor"), o.get("routing", [])] for ref, o in sorted(outcomes.items())}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


def compare_outcome_sets(first: Outcomes, second: Outcomes) -> list[str]:
    """References whose outcome differs between two runs of the same scenario and seed (missing ones included)."""
    keys = sorted(set(first) | set(second))
    return [ref for ref in keys if first.get(ref) != second.get(ref)]


Window = tuple[str, int, int]  # (processor "A" or "B", first payment index, index after the last)


def degraded_window(scenario: Any) -> Window | None:
    """The processor degraded or down and the payment indexes it was, from the scenario's control steps.

    A `ControlStep` switching an outage on and the next one switching it off, or a `ProfileStep` that changes the
    profile and the next one for that processor that restores the default. None when the scenario injects no fault.
    """
    steps = sorted(scenario.steps, key=lambda step: step.at_index)
    for i, step in enumerate(steps):
        later = [x for x in steps[i + 1 :] if x.processor == step.processor and type(x) is type(step)]
        if isinstance(step, ControlStep) and step.outage and later:
            return step.processor.upper(), step.at_index, later[0].at_index
        if isinstance(step, ProfileStep) and step.profile != ProfileStep.default_profile(step.processor) and later:
            return step.processor.upper(), step.at_index, later[0].at_index
    return None


def exploration_cost(outcomes: Outcomes, window: Window | None) -> dict[str, Any] | None:
    """Of the payments created while `window`'s processor was degraded, how many were first routed to it.

    A payment's index is the number after the last dash of its reference; only its first routed event (the
    initial route, not the retry) counts. None when there is no window; `share` is None with no payment in it.
    """
    if window is None:
        return None
    processor, start, end = window
    inside = [
        o
        for ref, o in outcomes.items()
        if ref.rsplit("-", 1)[-1].isdigit() and start <= int(ref.rsplit("-", 1)[-1]) < end
    ]
    to_degraded = sum(1 for o in inside if (o.get("routing") or [""])[0].startswith(f"{processor}:"))
    return {
        "processor": processor,
        "start": start,
        "end": end,
        "payments": len(inside),
        "to_degraded": to_degraded,
        "share": to_degraded / len(inside) if inside else None,
    }


def adaptive_outside_fault(outcomes: Outcomes, window: Window | None) -> dict[str, int]:
    """Initial routes with reason `adaptive` among the payments created outside the fault window (REL-60).

    Without a window (a calm scenario) every payment counts as outside. The reason is the part after the colon of a
    payment's first routing entry (`A:adaptive`); the retry entry is not counted.
    """
    inside = 0
    payments = adaptive = 0
    for ref, o in outcomes.items():
        tail = ref.rsplit("-", 1)[-1]
        if window is not None and tail.isdigit() and window[1] <= int(tail) < window[2]:
            inside += 1
            continue
        payments += 1
        first = (o.get("routing") or [""])[0]
        adaptive += first.endswith(":adaptive")
    return {"payments": payments, "adaptive": adaptive, "inside_fault": inside}


def summarize_run(
    spec: RunSpec, outcomes: Outcomes, report: dict[str, Any], duration_seconds: float, window: Window | None = None
) -> dict[str, Any]:
    final = sum(1 for o in outcomes.values() if o["status"] in FINAL_STATUSES)
    captured = sum(1 for o in outcomes.values() if o["status"] == "captured")
    return {
        "scenario": spec.scenario,
        "seed": spec.seed,
        "strategy": spec.strategy,
        "payments": len(outcomes),
        "final": final,
        "captured": captured,
        "success_rate_pct": round(float(_success(captured, final)) * 100, 2),
        "revenue_captured": _captured_by_currency(outcomes),
        "p95_latency_ms": report.get("latency", {}).get("p95_ms"),
        "duration_seconds": duration_seconds,
        "digest": outcome_digest(outcomes),
        "exploration": exploration_cost(outcomes, window),
    }


def _shape(outcomes: Outcomes) -> dict[str, tuple[str, int]]:
    return {ref: (o["currency"], o["amount_minor"]) for ref, o in outcomes.items()}


def run_plan(
    plan: list[RunSpec],
    reset: Callable[[RunSpec], None],
    run: Callable[[RunSpec], tuple[Outcomes, dict[str, Any]]],
    clock: Callable[[], float],
    on_summary: Callable[[RunSpec, dict[str, Any]], None] | None = None,
    window_for: Callable[[str], Window | None] | None = None,
) -> list[dict[str, Any]]:
    """Run the plan in order: a fresh `reset` before every run, then `run` (generator, wait, collect), timed.

    Every strategy of one scenario and seed must have met the same references with the same amounts.
    """
    summaries: list[dict[str, Any]] = []
    shapes: dict[tuple[str, int], dict[str, tuple[str, int]]] = {}
    for spec in plan:
        reset(spec)
        started = clock()
        outcomes, report = run(spec)
        duration = clock() - started
        shape = shapes.setdefault((spec.scenario, spec.seed), _shape(outcomes))
        if shape != _shape(outcomes):
            raise ValueError(f"{spec.name} did not run on the same references as the other strategies of its seed")
        summary = summarize_run(spec, outcomes, report, duration, window_for(spec.scenario) if window_for else None)
        summaries.append(summary)
        if on_summary:
            on_summary(spec, summary)
    return summaries


def _pair(base: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
    diff = (_success(cand["captured"], cand["final"]) - _success(base["captured"], base["final"])) * 100
    currencies = sorted(set(base["revenue_captured"]) | set(cand["revenue_captured"]))
    return {
        "scenario": base["scenario"],
        "seed": base["seed"],
        "baseline": base["strategy"],
        "candidate": cand["strategy"],
        "baseline_success_rate_pct": base["success_rate_pct"],
        "candidate_success_rate_pct": cand["success_rate_pct"],
        "diff_pp": round(float(diff), 4),
        "better": diff > 0,
        "revenue_diff": {
            c: cand["revenue_captured"].get(c, 0) - base["revenue_captured"].get(c, 0) for c in currencies
        },
        "baseline_p95_latency_ms": base["p95_latency_ms"],
        "candidate_p95_latency_ms": cand["p95_latency_ms"],
        "_exact_diff": diff,
    }


def _scenario_summary(scenario: str, candidate: str, pairs: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(pairs)
    mean = sum((p["_exact_diff"] for p in pairs), Fraction(0)) / n
    better = sum(1 for p in pairs if p["better"])
    base_total = sum((Fraction(_p95_of(p, "baseline")) for p in pairs), Fraction(0))
    cand_total = sum((Fraction(_p95_of(p, "candidate")) for p in pairs), Fraction(0))
    ratio = cand_total / base_total if base_total else Fraction(0)
    return {
        "scenario": scenario,
        "candidate": candidate,
        "pairs": n,
        "mean_diff_pp": round(float(mean), 4),
        "share_better": better / n,
        "latency_ratio": round(float(ratio), 4),
        "latency_ok": cand_total * 100 <= base_total * (100 + LATENCY_MARGIN_PERCENT),
        "_mean": mean,
    }


def _p95_of(pair: dict[str, Any], side: str) -> float:
    value = pair[f"{side}_p95_latency_ms"]
    if value is None:
        raise ValueError(f"{side} run of {pair['scenario']}-{pair['seed']} has no p95 latency")
    return float(value)


def _verdict(
    baseline: str, candidate: str, pairs: list[dict[str, Any]], scenarios: list[dict[str, Any]]
) -> dict[str, Any]:
    n = len(pairs)
    mean = sum((p["_exact_diff"] for p in pairs), Fraction(0)) / n
    better = sum(1 for p in pairs if p["better"])
    mean_ok = mean >= MEAN_UPLIFT_PP
    better_ok = better * 100 >= WIN_SHARE_PERCENT * n
    latency_ok = all(s["latency_ok"] for s in scenarios)
    return {
        "baseline": baseline,
        "candidate": candidate,
        "pairs": n,
        "mean_uplift_pp": round(float(mean), 4),
        "mean_uplift_required_pp": MEAN_UPLIFT_PP,
        "mean_uplift_ok": mean_ok,
        "better_share": better / n,
        "better_share_required": WIN_SHARE_PERCENT / 100,
        "better_ok": better_ok,
        "worst_latency_ratio": max(s["latency_ratio"] for s in scenarios),
        "latency_margin_percent": LATENCY_MARGIN_PERCENT,
        "latency_ok": latency_ok,
        "win": mean_ok and better_ok and latency_ok,
    }


def _exploration_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per scenario and strategy, the exploration cost pooled over the seeds (payments and routes summed)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in runs:
        if r.get("exploration"):
            groups.setdefault((r["scenario"], r["strategy"]), []).append(r)
    rows = []
    for (scenario, strategy), items in groups.items():
        payments = sum(r["exploration"]["payments"] for r in items)
        to_degraded = sum(r["exploration"]["to_degraded"] for r in items)
        rows.append(
            {
                "scenario": scenario,
                "strategy": strategy,
                "processor": items[0]["exploration"]["processor"],
                "payments": payments,
                "to_degraded": to_degraded,
                "share": to_degraded / payments if payments else None,
                "per_seed": {str(r["seed"]): r["exploration"]["share"] for r in items},
            }
        )
    return rows


def build_experiment(runs: list[dict[str, Any]], baseline: str, candidate: str | None = None) -> dict[str, Any]:
    """Pairs, per-scenario summaries and, when `candidate` is named, the ADR-0016 win-rule verdict."""
    by_key = {(r["scenario"], r["seed"], r["strategy"]): r for r in runs}
    strategies = list(dict.fromkeys(r["strategy"] for r in runs))
    candidates = [candidate] if candidate else [s for s in strategies if s != baseline]
    scenario_order = list(dict.fromkeys(r["scenario"] for r in runs))
    pairs: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    for cand in candidates:
        for scenario in scenario_order:
            seeds = sorted({r["seed"] for r in runs if r["scenario"] == scenario})
            scenario_pairs = []
            for seed in seeds:
                base_run, cand_run = by_key.get((scenario, seed, baseline)), by_key.get((scenario, seed, cand))
                if base_run is None or cand_run is None:
                    raise ValueError(f"run missing for {scenario} seed {seed}: need both {baseline} and {cand}")
                scenario_pairs.append(_pair(base_run, cand_run))
            pairs.extend(scenario_pairs)
            scenarios.append(_scenario_summary(scenario, cand, scenario_pairs))
    verdict = None
    if candidate:
        verdict = _verdict(baseline, candidate, pairs, scenarios)
    for item in pairs:
        item.pop("_exact_diff")
    for item in scenarios:
        item.pop("_mean")
    return {
        "synthetic": True,
        "objective": OBJECTIVE,
        "baseline": baseline,
        "candidate": candidate,
        "win_rule": {
            "mean_uplift_pp": MEAN_UPLIFT_PP,
            "better_share_percent": WIN_SHARE_PERCENT,
            "latency_margin_percent": LATENCY_MARGIN_PERCENT,
        },
        "runs": runs,
        "pairs": pairs,
        "scenarios": scenarios,
        "verdict": verdict,
        "exploration": _exploration_rows(runs),
        "total_duration_seconds": round(sum(r["duration_seconds"] for r in runs), 1),
    }


def rel30_agreement(baseline: Outcomes, relay: Outcomes, rel30: dict[str, Any]) -> dict[str, Any]:
    """Compare a `static` run and a `rules` run with REL-30's results (docs/evaluation/outage-demo/results.json).

    Success rates agree when within the REL-30 tolerance in percentage points; the revenue recovered per currency
    (rules minus static captured amount) within the REL-30 relative tolerance, as REL-30 compared its own runs.
    """
    tolerance = rel30["tolerance"]
    reference = rel30["runs"][0]

    def rate(outcomes: Outcomes) -> float:
        final = sum(1 for o in outcomes.values() if o["status"] in FINAL_STATUSES)
        captured = sum(1 for o in outcomes.values() if o["status"] == "captured")
        return round(float(_success(captured, final)) * 100, 2)

    success = {
        "baseline": reproducibility(
            [reference["baseline_success_rate_pct"], rate(baseline)], tolerance["success_rate_pp"], relative=False
        ),
        "relay": reproducibility(
            [reference["relay_success_rate_pct"], rate(relay)], tolerance["success_rate_pp"], relative=False
        ),
    }
    base_rev, rel_rev = _captured_by_currency(baseline), _captured_by_currency(relay)
    recovered = {c: rel_rev.get(c, 0) - base_rev.get(c, 0) for c in sorted(set(base_rev) | set(rel_rev))}
    revenue = {
        c: reproducibility(
            [reference["revenue_recovered"].get(c, 0), recovered.get(c, 0)],
            tolerance["revenue_recovered_pct"],
            relative=True,
        )
        for c in sorted(set(recovered) | set(reference["revenue_recovered"]))
    }
    return {
        "reference": {"scenario": rel30["scenario"], "seed": rel30["seed"], "tolerance": tolerance},
        "success_rate_pp": success,
        "revenue_recovered": revenue,
        "pass": all(v["pass"] for v in success.values()) and all(v["pass"] for v in revenue.values()),
    }


def _fmt_revenue(revenue: dict[str, int]) -> str:
    return ", ".join(f"{c} {v}" for c, v in revenue.items()) or "-"


def render_experiment_markdown(result: dict[str, Any], title: str = "Routing experiment results") -> str:
    lines = [
        f"# {title}",
        "",
        "**All data is synthetic** (simulated processors, generated payments, no real card data).",
        "",
        f"Objective: {result['objective']}",
        "",
        f"Baseline strategy: `{result['baseline']}`. Total wall-clock time of the runs: "
        f"{result['total_duration_seconds']:.0f} s.",
        "",
        "## Runs",
        "",
        "| Scenario | Seed | Strategy | Final | Success % | Revenue captured (minor units) | p95 ms | Duration s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in result["runs"]:
        p95 = "-" if r["p95_latency_ms"] is None else f"{r['p95_latency_ms']:.1f}"
        lines.append(
            f"| {r['scenario']} | {r['seed']} | {r['strategy']} | {r['final']} | {r['success_rate_pct']:.2f} | "
            f"{_fmt_revenue(r['revenue_captured'])} | {p95} | {r['duration_seconds']:.0f} |"
        )
    lines += [
        "",
        "## Paired differences (candidate minus baseline, same seed and references)",
        "",
        "| Scenario | Seed | Candidate | Baseline % | Candidate % | Difference pp | Better | Revenue difference |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in result["pairs"]:
        lines.append(
            f"| {p['scenario']} | {p['seed']} | {p['candidate']} | {p['baseline_success_rate_pct']:.2f} | "
            f"{p['candidate_success_rate_pct']:.2f} | {p['diff_pp']:+.2f} | {'yes' if p['better'] else 'no'} | "
            f"{_fmt_revenue(p['revenue_diff'])} |"
        )
    lines += [
        "",
        "## Per scenario",
        "",
        "| Scenario | Candidate | Pairs | Mean difference pp | Share better | Latency ratio (p95) |",
        "|---|---|---|---|---|---|",
    ]
    for s in result["scenarios"]:
        lines.append(
            f"| {s['scenario']} | {s['candidate']} | {s['pairs']} | {s['mean_diff_pp']:+.2f} | "
            f"{s['share_better'] * 100:.0f}% | {s['latency_ratio']:.3f} |"
        )
    exploration = result.get("exploration")
    if exploration:
        lines += [
            "",
            "## Exploration cost",
            "",
            "Share of initial routes (the first routed event, not the retry) sent to the processor that was "
            "degraded or down at the time, over the payments created while the fault was on; pooled over the seeds.",
            "",
            "| Scenario | Strategy | Degraded processor | Payments in the fault | Routed to it | Share | Per seed |",
            "|---|---|---|---|---|---|---|",
        ]
        for e in exploration:
            share = "-" if e["share"] is None else f"{e['share'] * 100:.1f}%"
            per_seed = ", ".join(
                f"{seed}: {'-' if v is None else f'{v * 100:.0f}%'}" for seed, v in e["per_seed"].items()
            )
            lines.append(
                f"| {e['scenario']} | {e['strategy']} | {e['processor']} | {e['payments']} | {e['to_degraded']} | "
                f"{share} | {per_seed} |"
            )
    verdict = result.get("verdict")
    if verdict:
        lines += [
            "",
            "## Win rule (ADR-0016)",
            "",
            f"`{verdict['candidate']}` against `{verdict['baseline']}` over {verdict['pairs']} pairs: "
            f"**{'WIN' if verdict['win'] else 'NO WIN'}**.",
            "",
            "| Condition | Observed | Required | Holds |",
            "|---|---|---|---|",
            f"| Mean paired uplift | {verdict['mean_uplift_pp']:+.2f} pp | at least "
            f"{verdict['mean_uplift_required_pp']} pp | {'yes' if verdict['mean_uplift_ok'] else 'no'} |",
            f"| Pairs where better | {verdict['better_share'] * 100:.0f}% | at least "
            f"{verdict['better_share_required'] * 100:.0f}% | {'yes' if verdict['better_ok'] else 'no'} |",
            f"| Worst scenario p95 latency ratio | {verdict['worst_latency_ratio']:.3f} | at most "
            f"{1 + verdict['latency_margin_percent'] / 100:.2f} | {'yes' if verdict['latency_ok'] else 'no'} |",
        ]
    agreement = result.get("rel30_agreement")
    if agreement:
        ref = agreement["reference"]
        lines += [
            "",
            f"## Agreement with REL-30 ({ref['scenario']}, seed {ref['seed']})",
            "",
            f"Overall: **{'PASS' if agreement['pass'] else 'FAIL'}** "
            f"(tolerance {ref['tolerance']['success_rate_pp']} pp on success rates, "
            f"{ref['tolerance']['revenue_recovered_pct']}% on revenue recovered).",
            "",
            "| Measure | REL-30 | This run | Spread | Holds |",
            "|---|---|---|---|---|",
        ]
        for label, key in (("Static success %", "baseline"), ("Rules success %", "relay")):
            m = agreement["success_rate_pp"][key]
            lines.append(
                f"| {label} | {m['values'][0]} | {m['values'][1]} | {m['spread']} | {'yes' if m['pass'] else 'no'} |"
            )
        for currency, m in agreement["revenue_recovered"].items():
            lines.append(
                f"| Revenue recovered {currency} | {m['values'][0]} | {m['values'][1]} | {m['spread']}% | "
                f"{'yes' if m['pass'] else 'no'} |"
            )
    determinism = result.get("determinism")
    if determinism:
        lines += [
            "",
            "## Determinism",
            "",
            f"Per-reference outcomes compared with the earlier run in `{determinism['compared_with']}`: "
            f"**{'IDENTICAL' if determinism['identical'] else 'DIFFERENT'}**.",
            "",
            "| Run | Differing references |",
            "|---|---|",
        ]
        for name, refs in determinism["differing_references"].items():
            lines.append(f"| {name} | {len(refs)} |")
    return "\n".join(lines) + "\n"


def merge_runs(parts: list[dict[str, Any]], seeds: Iterable[int]) -> list[dict[str, Any]]:
    """The runs of every part (a part's `results.json`) whose seed is in `seeds`, in part order.

    The same scenario, seed and strategy in two parts is an error: a completed run is never rerun or counted twice.
    """
    wanted = set(seeds)
    seen: set[tuple[str, int, str]] = set()
    merged: list[dict[str, Any]] = []
    for part in parts:
        for run in part["runs"]:
            key = (run["scenario"], run["seed"], run["strategy"])
            if key in seen:
                raise ValueError(f"run {key} appears twice in the parts")
            seen.add(key)
            if run["seed"] in wanted:
                merged.append(run)
    return merged


def build_split_experiment(
    parts: list[dict[str, Any]],
    deciding: Iterable[int],
    comparison: Iterable[int],
    baseline: str,
    candidate: str,
    earlier: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge parts into the deciding seed set (the ADR-0016 verdict) and a comparison-only seed set (REL-60).

    Both sets must hold every scenario with every seed of the set for both strategies, or this raises: a missing
    part must never become a smaller verdict. `earlier` is the previous iteration's result (REL-44), kept beside the
    comparison set as it is.
    """
    deciding, comparison = sorted(deciding), sorted(comparison)
    all_runs = [r for part in parts for r in part["runs"]]
    scenarios = list(dict.fromkeys(r["scenario"] for r in all_runs))
    sets = {}
    for label, seeds in (("deciding", deciding), ("comparison", comparison)):
        runs = merge_runs(parts, seeds)
        have = {(r["scenario"], r["seed"], r["strategy"]) for r in runs}
        for scenario in scenarios:
            for seed in seeds:
                for strategy in (baseline, candidate):
                    if (scenario, seed, strategy) not in have:
                        raise ValueError(f"{label} set is missing the run {scenario}-{seed}-{strategy}")
        sets[label] = build_experiment(runs, baseline, candidate)
    return {
        "synthetic": True,
        "baseline": baseline,
        "candidate": candidate,
        "deciding_seeds": deciding,
        "comparison_seeds": comparison,
        "deciding": sets["deciding"],
        "comparison": sets["comparison"],
        "earlier_iteration": earlier,
        "total_duration_seconds": round(sum(r["duration_seconds"] for r in all_runs), 1),
    }


def _outside_fault_rows(deciding: dict[str, Any], comparison: dict[str, Any]) -> list[str]:
    rows = []
    for label, result in (("deciding", deciding), ("comparison", comparison)):
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for r in result["runs"]:
            if r.get("outside_fault"):
                groups.setdefault((r["scenario"], r["strategy"]), []).append(r)
        for (scenario, strategy), items in groups.items():
            payments = sum(r["outside_fault"]["payments"] for r in items)
            adaptive = sum(r["outside_fault"]["adaptive"] for r in items)
            per_seed = ", ".join(f"{r['seed']}: {r['outside_fault']['adaptive']}" for r in items)
            rows.append(f"| {label} | {scenario} | {strategy} | {payments} | {adaptive} | {per_seed} |")
    return rows


def render_split_markdown(result: dict[str, Any], title: str = "Routing experiment results", notes: str = "") -> str:
    """Verdict on the deciding seeds first, then the comparison-only set beside the earlier iteration's numbers."""
    candidate, baseline = result["candidate"], result["baseline"]
    deciding, comparison, earlier = result["deciding"], result["comparison"], result.get("earlier_iteration")
    verdict = deciding["verdict"]
    lines = [
        f"# {title}",
        "",
        "**All data is synthetic** (simulated processors, generated payments, no real card data).",
        "",
        f"Verdict on the deciding seeds {result['deciding_seeds']}: `{candidate}` against `{baseline}` is "
        f"**{'WIN' if verdict['win'] else 'NO WIN'}** under the ADR-0016 win rule. Total wall-clock time of the "
        f"runs: {result['total_duration_seconds']:.0f} s.",
        "",
        notes.strip(),
        "",
        f"## Deciding seeds {result['deciding_seeds']}",
        "",
        render_experiment_markdown(deciding, "Deciding set").split("\n", 2)[2].replace("\n## ", "\n### "),
        f"## Comparison seeds {result['comparison_seeds']} (comparison only, not deciding)",
        "",
        render_experiment_markdown(comparison, "Comparison set").split("\n", 2)[2].replace("\n## ", "\n### "),
    ]
    rows = _outside_fault_rows(deciding, comparison)
    if rows:
        lines += [
            "## Adaptive routes outside the fault window",
            "",
            "Initial routes with reason `adaptive` among payments created outside the scenario's fault window (a calm "
            "scenario has none), counted from the saved per-run outcomes. Under `rules` this is always 0.",
            "",
            "| Set | Scenario | Strategy | Payments outside | Adaptive routes | Per seed |",
            "|---|---|---|---|---|---|",
            *rows,
            "",
        ]
    if earlier:
        ev = earlier["verdict"]
        lines += [
            "## Beside the earlier iteration (same seeds)",
            "",
            "| Strategy | Mean paired uplift pp | Pairs better | Worst scenario latency ratio |",
            "|---|---|---|---|",
            f"| {ev['candidate']} (earlier) | {ev['mean_uplift_pp']:+.2f} | {ev['better_share'] * 100:.0f}% | "
            f"{ev.get('worst_latency_ratio', float('nan')):.3f} |",
            f"| {candidate} (comparison set) | {comparison['verdict']['mean_uplift_pp']:+.2f} | "
            f"{comparison['verdict']['better_share'] * 100:.0f}% | "
            f"{comparison['verdict']['worst_latency_ratio']:.3f} |",
            "",
        ]
        if earlier.get("scenarios"):
            lines += [
                "| Scenario | Earlier mean pp | Earlier latency ratio | Now mean pp | Now latency ratio |",
                "|---|---|---|---|---|",
            ]
            now = {s["scenario"]: s for s in comparison["scenarios"]}
            for s in earlier["scenarios"]:
                n = now.get(s["scenario"])
                if n:
                    lines.append(
                        f"| {s['scenario']} | {s['mean_diff_pp']:+.2f} | {s['latency_ratio']:.3f} | "
                        f"{n['mean_diff_pp']:+.2f} | {n['latency_ratio']:.3f} |"
                    )
            lines.append("")
    return "\n".join(lines) + "\n"
