"""REL-43: the routing experiment's pure logic with fakes (no Docker): run plan, aggregation, win rule, files."""

import json

import pytest

from demo.experiment import (
    LATENCY_MARGIN_PERCENT,
    MEAN_UPLIFT_PP,
    WIN_SHARE_PERCENT,
    RunSpec,
    adaptive_outside_fault,
    build_experiment,
    build_split_experiment,
    compare_outcome_sets,
    degraded_window,
    exploration_cost,
    merge_runs,
    outcome_digest,
    plan_runs,
    rel30_agreement,
    render_experiment_markdown,
    render_split_markdown,
    run_plan,
    summarize_run,
)
from generator.scenarios import SCENARIOS, ControlStep, ProfileStep, Scenario


def test_plan_orders_scenario_then_seed_then_strategy() -> None:
    plan = plan_runs(["calm", "outage"], [11, 12], ["static", "rules"])
    assert [(s.scenario, s.seed, s.strategy) for s in plan] == [
        ("calm", 11, "static"),
        ("calm", 11, "rules"),
        ("calm", 12, "static"),
        ("calm", 12, "rules"),
        ("outage", 11, "static"),
        ("outage", 11, "rules"),
        ("outage", 12, "static"),
        ("outage", 12, "rules"),
    ]
    assert plan[0].name == "calm-11-static"
    assert plan[0].prefix == "calm-11-"


def test_plan_rejects_empty_or_duplicate_inputs() -> None:
    with pytest.raises(ValueError):
        plan_runs([], [1], ["rules"])
    with pytest.raises(ValueError):
        plan_runs(["calm"], [1, 1], ["rules"])
    with pytest.raises(ValueError):
        plan_runs(["calm"], [1], ["rules", "rules"])


def test_every_run_gets_a_fresh_reset_before_it_starts() -> None:
    calls: list[tuple[str, str]] = []
    ticks = iter(range(0, 1000, 10))

    def reset(spec: RunSpec) -> None:
        calls.append(("reset", spec.name))

    def run(spec: RunSpec) -> tuple[dict, dict]:
        calls.append(("run", spec.name))
        return {"r1": {"status": "captured", "currency": "USD", "amount_minor": 5}}, {"latency": {"p95_ms": 7.0}}

    plan = plan_runs(["calm"], [11], ["static", "rules"])
    summaries = run_plan(plan, reset, run, clock=lambda: next(ticks))
    assert calls == [
        ("reset", "calm-11-static"),
        ("run", "calm-11-static"),
        ("reset", "calm-11-rules"),
        ("run", "calm-11-rules"),
    ]
    assert [s["strategy"] for s in summaries] == ["static", "rules"]
    assert [s["duration_seconds"] for s in summaries] == [10, 10]


def test_same_references_are_required_for_every_strategy() -> None:
    def run(spec: RunSpec) -> tuple[dict, dict]:
        ref = "r1" if spec.strategy == "static" else "r2"
        return {ref: {"status": "captured", "currency": "USD", "amount_minor": 5}}, {"latency": {"p95_ms": 1.0}}

    with pytest.raises(ValueError, match="same references"):
        run_plan(plan_runs(["calm"], [11], ["static", "rules"]), lambda spec: None, run, clock=lambda: 0.0)


def outcomes(captured: int, declined: int = 0, failed: int = 0, pending: int = 0) -> dict:
    items = ["captured"] * captured + ["declined"] * declined + ["failed"] * failed + ["pending"] * pending
    currencies = ["USD", "EUR"]
    return {
        f"r{i:03d}": {"status": s, "currency": currencies[i % 2], "amount_minor": 100 + i} for i, s in enumerate(items)
    }


def report(p95: float) -> dict:
    return {"latency": {"p95_ms": p95}}


def summary(scenario: str, seed: int, strategy: str, captured: int, p95: float = 1000.0, final: int = 100) -> dict:
    spec = RunSpec(scenario, seed, strategy)
    return summarize_run(spec, outcomes(captured, failed=final - captured), report(p95), 12.5)


def test_summary_counts_captured_over_final_and_revenue_per_currency() -> None:
    spec = RunSpec("calm", 11, "rules")
    s = summarize_run(spec, outcomes(6, declined=2, failed=1, pending=1), report(321.5), 4.0)
    assert (s["scenario"], s["seed"], s["strategy"]) == ("calm", 11, "rules")
    assert (s["payments"], s["final"], s["captured"]) == (10, 9, 6)
    assert s["success_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert s["p95_latency_ms"] == 321.5
    assert s["duration_seconds"] == 4.0
    assert s["revenue_captured"] == {"EUR": 100 + 1 + 100 + 3 + 100 + 5, "USD": 100 + 100 + 2 + 100 + 4}
    assert len(s["digest"]) == 64


def test_digest_depends_on_every_reference_outcome() -> None:
    a = {"r1": {"status": "captured", "processor": "A", "routing": ["A:initial"]}}
    b = {"r1": {"status": "captured", "processor": "B", "routing": ["B:failover"]}}
    assert outcome_digest(a) == outcome_digest(json.loads(json.dumps(a)))
    assert outcome_digest(a) != outcome_digest(b)


def test_compare_outcome_sets_lists_references_that_differ() -> None:
    a = {"r1": {"status": "captured"}, "r2": {"status": "failed"}}
    assert compare_outcome_sets(a, dict(a)) == []
    assert compare_outcome_sets(a, {"r1": {"status": "captured"}, "r2": {"status": "captured"}}) == ["r2"]
    assert compare_outcome_sets(a, {"r1": {"status": "captured"}}) == ["r2"]


def test_pairs_are_candidate_minus_baseline_on_the_same_seed() -> None:
    runs = [
        summary("calm", 11, "static", 80),
        summary("calm", 11, "rules", 90, p95=500.0),
        summary("calm", 12, "static", 70),
        summary("calm", 12, "rules", 65, p95=1500.0),
    ]
    result = build_experiment(runs, baseline="static")
    pairs = {(p["scenario"], p["seed"]): p for p in result["pairs"]}
    assert pairs[("calm", 11)]["diff_pp"] == pytest.approx(10.0)
    assert pairs[("calm", 11)]["better"] is True
    assert pairs[("calm", 12)]["diff_pp"] == pytest.approx(-5.0)
    assert pairs[("calm", 12)]["better"] is False
    (scenario,) = result["scenarios"]
    assert scenario["mean_diff_pp"] == pytest.approx(2.5)
    assert scenario["share_better"] == pytest.approx(0.5)
    assert scenario["latency_ratio"] == pytest.approx(1.0)  # mean 1000 against mean 1000
    assert result["verdict"] is None


def test_pairs_include_revenue_difference_per_currency() -> None:
    runs = [summary("calm", 11, "static", 80), summary("calm", 11, "rules", 90)]
    (pair,) = build_experiment(runs, baseline="static")["pairs"]
    assert set(pair["revenue_diff"]) == {"EUR", "USD"}
    assert sum(pair["revenue_diff"].values()) > 0


def test_a_pair_needs_both_runs() -> None:
    with pytest.raises(ValueError, match="missing"):
        build_experiment([summary("calm", 11, "static", 80)], baseline="static", candidate="rules")


def _runs(diffs: list[int], p95_candidate: float = 1000.0, scenario: str = "calm", base: int = 50) -> list[dict]:
    runs = []
    for seed, diff in enumerate(diffs, start=11):
        runs.append(summary(scenario, seed, "rules", base))
        runs.append(summary(scenario, seed, "adaptive", base + diff, p95=p95_candidate))
    return runs


def verdict(runs: list[dict]) -> dict:
    result = build_experiment(runs, baseline="rules", candidate="adaptive")
    return result["verdict"]


def test_win_rule_constants_follow_adr_0016() -> None:
    assert (MEAN_UPLIFT_PP, WIN_SHARE_PERCENT, LATENCY_MARGIN_PERCENT) == (1, 80, 10)


def test_win_when_mean_uplift_is_exactly_one_point() -> None:
    v = verdict(_runs([1, 1, 1, 1, 1]))
    assert v["mean_uplift_pp"] == pytest.approx(1.0)
    assert v["mean_uplift_ok"] is True
    assert v["win"] is True


def test_no_win_just_under_one_point() -> None:
    v = verdict(_runs([1, 1, 1, 1, 0]))
    assert v["mean_uplift_pp"] == pytest.approx(0.8)
    assert v["mean_uplift_ok"] is False
    assert v["better_ok"] is True
    assert v["win"] is False


def test_win_when_exactly_eighty_percent_of_pairs_are_better() -> None:
    v = verdict(_runs([3, 3, 3, 3, -2]))
    assert v["better_share"] == pytest.approx(0.8)
    assert v["better_ok"] is True
    assert v["win"] is True


def test_no_win_below_eighty_percent_of_pairs_better() -> None:
    v = verdict(_runs([6, 6, 6, 0, 0]))  # large mean uplift, but only 3 of 5 better
    assert v["mean_uplift_ok"] is True
    assert v["better_share"] == pytest.approx(0.6)
    assert v["better_ok"] is False
    assert v["win"] is False


def test_equal_pairs_are_not_better() -> None:
    v = verdict(_runs([0, 0, 0, 0, 0]))
    assert v["better_share"] == 0.0


def test_latency_guardrail_holds_at_exactly_ten_percent() -> None:
    v = verdict(_runs([3] * 5, p95_candidate=1100.0))
    assert v["worst_latency_ratio"] == pytest.approx(1.1)
    assert v["latency_ok"] is True
    assert v["win"] is True


def test_latency_guardrail_fails_just_over_ten_percent() -> None:
    v = verdict(_runs([3] * 5, p95_candidate=1100.1))
    assert v["latency_ok"] is False
    assert v["win"] is False


def test_latency_guardrail_applies_in_every_scenario() -> None:
    runs = _runs([3] * 5, scenario="calm") + _runs([3] * 5, p95_candidate=1500.0, scenario="outage")
    v = verdict(runs)
    assert v["latency_ok"] is False
    assert v["win"] is False
    assert v["worst_latency_ratio"] == pytest.approx(1.5)


def test_results_file_shape_and_markdown() -> None:
    runs = _runs([3] * 5)
    result = build_experiment(runs, baseline="rules", candidate="adaptive")
    assert set(result) >= {"synthetic", "objective", "baseline", "candidate", "runs", "pairs", "scenarios", "verdict"}
    assert result["synthetic"] is True
    assert set(result["runs"][0]) >= {
        "scenario",
        "seed",
        "strategy",
        "success_rate_pct",
        "revenue_captured",
        "p95_latency_ms",
        "duration_seconds",
        "digest",
    }
    assert result["total_duration_seconds"] == pytest.approx(12.5 * len(runs))
    json.dumps(result)  # serialisable
    md = render_experiment_markdown(result)
    assert "synthetic" in md.lower()
    assert "calm" in md and "adaptive" in md
    assert "Win rule" in md
    assert "WIN" in md


def test_markdown_without_a_verdict_has_no_win_section() -> None:
    result = build_experiment([summary("calm", 11, "static", 80), summary("calm", 11, "rules", 90)], baseline="static")
    assert "Win rule" not in render_experiment_markdown(result)


REL30 = {
    "scenario": "processor-a-outage",
    "seed": 7,
    "tolerance": {"success_rate_pp": 1.0, "revenue_recovered_pct": 1.0},
    "runs": [
        {
            "baseline_success_rate_pct": 58.0,
            "relay_success_rate_pct": 89.0,
            "revenue_recovered": {"EUR": 1000, "USD": 2000},
        }
    ],
}


def _rel30_runs(static_captured: int, rules_captured: int) -> tuple[dict, dict]:
    base = outcomes(static_captured, failed=100 - static_captured)
    rules = outcomes(rules_captured, failed=100 - rules_captured)
    return base, rules


def test_rel30_agreement_passes_within_tolerance() -> None:
    base, rules = _rel30_runs(58, 89)
    agreement = rel30_agreement(base, rules, REL30)
    assert agreement["success_rate_pp"]["baseline"]["pass"] is True
    assert agreement["success_rate_pp"]["relay"]["pass"] is True
    assert agreement["reference"]["scenario"] == "processor-a-outage"


def test_rel30_agreement_fails_outside_tolerance() -> None:
    base, rules = _rel30_runs(58, 85)
    agreement = rel30_agreement(base, rules, REL30)
    assert agreement["success_rate_pp"]["relay"]["pass"] is False
    assert agreement["pass"] is False


def test_rel30_agreement_edge_is_inclusive() -> None:
    base, rules = _rel30_runs(59, 89)  # exactly 1.0 pp away on the baseline
    agreement = rel30_agreement(base, rules, REL30)
    assert agreement["success_rate_pp"]["baseline"]["pass"] is True


def test_markdown_reports_determinism_and_rel30_sections_when_present() -> None:
    result = build_experiment([summary("calm", 11, "static", 80), summary("calm", 11, "rules", 90)], baseline="static")
    result["determinism"] = {
        "compared_with": "earlier",
        "differing_references": {"calm-11-rules": []},
        "identical": True,
    }
    base, rules = _rel30_runs(58, 89)
    result["rel30_agreement"] = rel30_agreement(base, rules, REL30)
    md = render_experiment_markdown(result)
    assert "IDENTICAL" in md
    assert "Agreement with REL-30" in md


# --- exploration cost (REL-44): initial routes sent to the processor that was degraded at the time -------------------


def routed_run(prefix: str, first: dict[int, str], count: int = 10, status: str = "captured") -> dict:
    """Outcomes of `count` payments; payment `i` was first routed to `first.get(i, "A")`."""
    return {
        f"{prefix}{i}": {
            "status": status,
            "currency": "USD",
            "amount_minor": 100,
            "processor": first.get(i, "A"),
            "routing": [f"{first.get(i, 'A')}:adaptive"],
        }
        for i in range(count)
    }


def test_exploration_cost_counts_initial_routes_to_the_degraded_processor_inside_the_window() -> None:
    run = routed_run("x-11-", {4: "B", 5: "B", 6: "B"})  # window 3 to 7: indexes 3, 4, 5, 6
    cost = exploration_cost(run, ("A", 3, 7))
    assert cost is not None
    assert (cost["payments"], cost["to_degraded"]) == (4, 1)
    assert cost["share"] == pytest.approx(0.25)
    assert cost["processor"] == "A"


def test_exploration_cost_ignores_payments_outside_the_window_and_the_retry() -> None:
    run = routed_run("x-11-", {})
    run["x-11-5"]["routing"] = ["B:adaptive", "A:retry"]  # initial B, retried back to A: only the initial route counts
    run["x-11-9"]["routing"] = ["A:adaptive"]
    cost = exploration_cost(run, ("A", 5, 7))
    assert cost is not None and cost["payments"] == 2 and cost["to_degraded"] == 1


def test_exploration_cost_is_none_without_a_degraded_window() -> None:
    assert exploration_cost(routed_run("x-11-", {}), None) is None


def test_exploration_cost_of_a_run_with_no_payment_in_the_window_has_no_share() -> None:
    cost = exploration_cost(routed_run("x-11-", {}, count=2), ("A", 5, 7))
    assert cost is not None and cost["payments"] == 0 and cost["share"] is None


def test_degraded_window_comes_from_the_scenario_control_steps() -> None:
    assert degraded_window(SCENARIOS["normal-day"]) is None
    assert degraded_window(SCENARIOS["processor-a-outage"]) == ("A", 100, 200)
    assert degraded_window(SCENARIOS["processor-a-degraded"]) == ("A", 100, 200)


def test_degraded_window_of_a_made_up_scenario_on_processor_b() -> None:
    scenario = Scenario("b-outage", "x", 50, steps=(ControlStep(10, "b", True), ControlStep(30, "b", False)))
    assert degraded_window(scenario) == ("B", 10, 30)
    slow = Scenario(
        "b-slow",
        "x",
        50,
        steps=(
            ProfileStep(5, "b", {**ProfileStep.default_profile("b"), "timeout_rate": 0.4}),
            ProfileStep(15, "b", ProfileStep.default_profile("b")),
        ),
    )
    assert degraded_window(slow) == ("B", 5, 15)


def test_run_summary_and_results_carry_the_exploration_cost_per_strategy_and_scenario() -> None:
    window = ("A", 3, 7)
    runs = []
    for seed, to_b in ((11, {4: "B"}), (12, {3: "B", 4: "B", 5: "B", 6: "B"})):
        for strategy, firsts in (("rules", {}), ("adaptive", to_b)):
            run = routed_run(f"calm-{seed}-", firsts)
            runs.append(summarize_run(RunSpec("calm", seed, strategy), run, report(100.0), 1.0, window))
    by_name = {(r["seed"], r["strategy"]): r for r in runs}
    assert by_name[(11, "rules")]["exploration"]["to_degraded"] == 4
    assert by_name[(11, "adaptive")]["exploration"]["to_degraded"] == 3
    result = build_experiment(runs, baseline="rules", candidate="adaptive")
    rows = {(e["scenario"], e["strategy"]): e for e in result["exploration"]}
    assert rows[("calm", "adaptive")]["payments"] == 8
    assert rows[("calm", "adaptive")]["to_degraded"] == 3 + 0
    assert rows[("calm", "adaptive")]["share"] == pytest.approx(3 / 8)
    assert rows[("calm", "rules")]["share"] == pytest.approx(1.0)
    md = render_experiment_markdown(result)
    assert "Exploration cost" in md
    assert "37.5%" in md


def test_a_run_without_a_window_has_no_exploration_rows() -> None:
    runs = [summary("calm", 11, "static", 80), summary("calm", 11, "rules", 90)]
    assert build_experiment(runs, baseline="static")["exploration"] == []
    assert "Exploration cost" not in render_experiment_markdown(build_experiment(runs, baseline="static"))


def test_run_plan_gives_the_scenario_window_to_the_summary() -> None:
    def run(spec: RunSpec) -> tuple[dict, dict]:
        return routed_run(spec.prefix, {4: "B"}), report(1.0)

    plan = plan_runs(["calm", "flat"], [11], ["adaptive"])
    summaries = run_plan(
        plan,
        lambda spec: None,
        run,
        clock=lambda: 0.0,
        window_for=lambda scenario: ("A", 3, 7) if scenario == "calm" else None,
    )
    assert summaries[0]["exploration"]["to_degraded"] == 3
    assert summaries[1]["exploration"] is None


# --- REL-60: parts merged into a deciding seed set and a comparison-only seed set -------------------------------


def _part(scenario: str, seeds: range, diff: int, strategy: str = "hybrid") -> dict:
    runs = []
    for seed in seeds:
        runs.append(summary(scenario, seed, "rules", 50))
        runs.append(summary(scenario, seed, strategy, 50 + diff))
    return {"runs": runs}


def _six_parts(diff: int = 2) -> list[dict]:
    return [
        _part(scenario, seeds, diff)
        for scenario in ("calm", "outage", "degraded")
        for seeds in (range(21, 26), range(11, 16))
    ]


def test_merge_runs_keeps_only_the_requested_seeds_in_part_order() -> None:
    runs = merge_runs(_six_parts(), [21, 22, 23, 24, 25])
    assert len(runs) == 30
    assert {r["seed"] for r in runs} == {21, 22, 23, 24, 25}
    assert [r["scenario"] for r in runs][:1] == ["calm"]


def test_merge_runs_refuses_the_same_run_twice() -> None:
    parts = _six_parts()
    parts.append(parts[0])
    with pytest.raises(ValueError, match="twice"):
        merge_runs(parts, [21])


def test_the_deciding_verdict_uses_only_the_deciding_seeds_and_the_comparison_set_stays_separate() -> None:
    # deciding seeds: +2 everywhere (win); comparison seeds: -2 everywhere (loss) must not leak into the verdict
    parts = [
        _part(sc, seeds, 2 if seeds.start == 21 else -2)
        for sc in ("calm", "outage", "degraded")
        for seeds in (range(21, 26), range(11, 16))
    ]
    result = build_split_experiment(parts, [21, 22, 23, 24, 25], [11, 12, 13, 14, 15], "rules", "hybrid")
    assert result["deciding"]["verdict"]["win"] is True
    assert result["deciding"]["verdict"]["pairs"] == 15
    assert result["deciding"]["verdict"]["mean_uplift_pp"] == pytest.approx(2.0)
    assert result["comparison"]["verdict"]["win"] is False
    assert result["comparison"]["verdict"]["pairs"] == 15
    assert result["deciding_seeds"] == [21, 22, 23, 24, 25]
    assert result["comparison_seeds"] == [11, 12, 13, 14, 15]
    json.dumps(result)


def test_a_missing_part_is_an_error_not_a_smaller_verdict() -> None:
    with pytest.raises(ValueError):
        build_split_experiment(_six_parts()[:-1], [21, 22, 23, 24, 25], [11, 12, 13, 14, 15], "rules", "hybrid")


def test_split_markdown_gives_the_verdict_first_and_the_earlier_iteration_beside_the_comparison_set() -> None:
    earlier = {"verdict": {"candidate": "adaptive", "mean_uplift_pp": 1.8222, "better_share": 2 / 3}, "scenarios": []}
    seeds = ([21, 22, 23, 24, 25], [11, 12, 13, 14, 15])
    result = build_split_experiment(_six_parts(), *seeds, "rules", "hybrid", earlier)
    md = render_split_markdown(result)
    assert md.index("Deciding seeds") < md.index("Comparison seeds")
    assert "WIN" in md
    assert "adaptive" in md and "1.82" in md


def test_adaptive_routes_outside_the_fault_window_are_counted_from_first_routes() -> None:
    out = {
        "s-1-0": {"routing": ["A:adaptive"]},
        "s-1-1": {"routing": ["A:initial", "B:retry"]},
        "s-1-2": {"routing": ["B:adaptive", "A:retry"]},
        "s-1-5": {"routing": ["A:adaptive"]},  # inside the window 5 to 7
        "s-1-7": {"routing": ["A:failover"]},
        "s-1-8": {"routing": ["A:retry"]},  # a retry entry first is not adaptive
    }
    got = adaptive_outside_fault(out, ("A", 5, 7))
    assert got == {"payments": 5, "adaptive": 2, "inside_fault": 1}
    assert adaptive_outside_fault(out, None) == {"payments": 6, "adaptive": 3, "inside_fault": 0}


def test_split_markdown_reports_adaptive_routes_outside_the_fault_window() -> None:
    parts = _six_parts()
    for part in parts:
        for run in part["runs"]:
            run["outside_fault"] = {"payments": 100, "adaptive": 3 if run["strategy"] == "hybrid" else 0}
    result = build_split_experiment(parts, [21, 22, 23, 24, 25], [11, 12, 13, 14, 15], "rules", "hybrid")
    md = render_split_markdown(result)
    assert "Adaptive routes outside the fault window" in md
    assert "| deciding | calm | hybrid | 500 | 15 |" in md


def test_split_markdown_shows_the_notes_right_after_the_verdict() -> None:
    result = build_split_experiment(_six_parts(), [21, 22, 23, 24, 25], [11, 12, 13, 14, 15], "rules", "hybrid")
    md = render_split_markdown(result, notes="## Findings A finding.")
    assert md.index("under the ADR-0016 win rule") < md.index("## Findings") < md.index("Deciding seeds [")
