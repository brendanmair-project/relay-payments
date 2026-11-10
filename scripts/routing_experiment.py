"""Routing experiment harness: strategies compared on seeded scenarios on the real compose stack (REL-43, ADR-0016).

Run from the repository root with Docker and RELAY_API_KEY in the environment or the settings file:

    python scripts/routing_experiment.py --strategies static,rules --scenarios processor-a-outage --seeds 7 \\
        --out docs/evaluation/routing-experiments/rel30-reproduction --rel30

Standard library only. It reuses `scripts/outage_demo.py` for everything that touches the stack. For each scenario,
seed and strategy, in that order (strategies innermost, so a pair runs back to back), it:

1. restarts api and worker with `ROUTING_STRATEGY` set, resets the data, stream and simulator profiles (a fresh start,
   `outage_demo.prepare_run`);
2. runs the load generator on the same payment references for every strategy (`<scenario>-<seed>-<index>`), waits
   until every payment is final, and saves the per-reference outcomes and the reporting tool's JSON under --out.

Then it writes `results.json` and `results.md` there (simulator/demo/experiment.py): per run the success rate
(captured over final), revenue captured per currency and p95 creation-to-final latency; per pair (candidate minus
baseline, same seed) the paired difference; per scenario the mean difference, share of pairs better and latency
ratio; per strategy and scenario the exploration cost (share of initial routes sent to the processor that was
degraded at the time); with --candidate the ADR-0016 win-rule verdict against --baseline.
--merge DIRS (REL-60) merges the parts' results.json into the deciding and comparison seed sets (no runs).
Wall-clock duration is recorded per run and in total. --rel30 compares a `static` and a `rules` run of
processor-a-outage seed 7 with docs/evaluation/outage-demo.
--compare-with DIR compares each run's per-reference outcomes with the same run saved in DIR (determinism check).
--progress FILE appends one line when each run starts and ends. The stack is left running (`docker compose down -v`).
All data is synthetic.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import outage_demo

from demo.experiment import (
    RunSpec,
    adaptive_outside_fault,
    build_experiment,
    build_split_experiment,
    compare_outcome_sets,
    degraded_window,
    plan_runs,
    rel30_agreement,
    render_experiment_markdown,
    render_split_markdown,
    run_plan,
)

SCENARIOS = outage_demo.SCENARIOS
ROOT = outage_demo.ROOT
REL30_RESULTS = ROOT / "docs" / "evaluation" / "outage-demo" / "results.json"
DEFAULT_SCENARIOS = "normal-day,processor-a-outage,processor-a-degraded"
# The generator's own limit (100 s) is too short for processor-a-degraded: 35% of payments wait out the 5 s processor
# timeout on one worker, so the queue at 2 payments per second takes about 150 s longer to drain than it takes to send.
DRAIN_TIMEOUT_SECONDS = 400.0


def csv(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def note(progress: Path | None, message: str) -> None:
    outage_demo.log(message)
    if progress:
        with progress.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strategies", default="static,rules", help="comma-separated ROUTING_STRATEGY names")
    parser.add_argument("--scenarios", default=DEFAULT_SCENARIOS)
    parser.add_argument("--seeds", default="11", help="comma-separated seeds")
    parser.add_argument("--out", required=True, help="output directory under the repository")
    parser.add_argument("--baseline", help="strategy the others are compared with (default: the first)")
    parser.add_argument("--candidate", help="strategy to judge with the ADR-0016 win rule against --baseline")
    parser.add_argument("--rate", type=float, default=2.0, help="payments per second (as the REL-30 demo)")
    parser.add_argument("--count", type=int, help="payments per run (default: the scenario's own count)")
    parser.add_argument(
        "--drain-timeout",
        type=float,
        default=DRAIN_TIMEOUT_SECONDS,
        help="seconds the generator waits for earlier payments to be final before a fault switch",
    )
    parser.add_argument("--health-window", type=int, default=120, help="HEALTH_WINDOW_SECONDS for api and worker")
    parser.add_argument("--timeout", type=float, default=1800, help="seconds to wait for one run to complete")
    parser.add_argument("--rel30", action="store_true", help="compare static and rules (outage, seed 7) with REL-30")
    parser.add_argument("--compare-with", help="directory of an earlier run to compare per-reference outcomes with")
    parser.add_argument("--progress", help="file that receives one line when each run starts and ends")
    parser.add_argument("--merge", help="comma-separated part directories (each with results.json) to merge, no runs")
    parser.add_argument("--deciding-seeds", help="with --merge: the seeds the ADR-0016 verdict is judged on")
    parser.add_argument("--comparison-seeds", help="with --merge: seeds reported for comparison only")
    parser.add_argument("--notes", help="with --merge: a markdown file of findings shown right after the verdict")
    parser.add_argument("--earlier", help="with --merge: the earlier iteration's results.json, shown beside")
    return parser


def merge_parts(args: argparse.Namespace) -> int:
    """Merge the parts' results.json into one results.json and results.md under --out (REL-60); no stack needed."""
    if not (args.deciding_seeds and args.comparison_seeds and args.candidate):
        sys.exit("FAIL --merge needs --deciding-seeds, --comparison-seeds and --candidate")
    parts = []
    for d in csv(args.merge):
        part = json.loads(((ROOT / d) / "results.json").read_text(encoding="utf-8"))
        for run in part["runs"]:  # adaptive routes outside the fault window, from the saved per-run outcomes
            name = f"{run['scenario']}-{run['seed']}-{run['strategy']}"
            outcomes = json.loads(((ROOT / d) / f"{name}.outcomes.json").read_text(encoding="utf-8"))
            run["outside_fault"] = adaptive_outside_fault(outcomes, degraded_window(SCENARIOS[run["scenario"]]))
        parts.append(part)
    earlier = json.loads((ROOT / args.earlier).read_text(encoding="utf-8")) if args.earlier else None
    result = build_split_experiment(
        parts,
        [int(x) for x in csv(args.deciding_seeds)],
        [int(x) for x in csv(args.comparison_seeds)],
        args.baseline or "rules",
        args.candidate,
        earlier,
    )
    notes = (ROOT / args.notes).read_text(encoding="utf-8") if args.notes else ""
    result["merged_from"] = csv(args.merge)
    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (out / "results.md").write_text(render_split_markdown(result, notes=notes), encoding="utf-8")
    print("MERGED=" + ("WIN" if result["deciding"]["verdict"]["win"] else "NO_WIN"))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.merge:
        return merge_parts(args)
    if not outage_demo.setting("RELAY_API_KEY"):
        sys.exit("FAIL RELAY_API_KEY is not set in the environment or the settings file")
    strategies, scenarios = csv(args.strategies), csv(args.scenarios)
    seeds = [int(seed) for seed in csv(args.seeds)]
    baseline = args.baseline or strategies[0]
    if baseline not in strategies or (args.candidate and args.candidate not in strategies):
        sys.exit("FAIL --baseline and --candidate must be among --strategies")
    plan = plan_runs(scenarios, seeds, strategies)
    outage_demo.HEALTH_WINDOW = args.health_window
    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    progress = Path(args.progress) if args.progress else None
    saved: dict[str, dict] = {}

    def reset(spec: RunSpec) -> None:
        note(progress, f"START {spec.name} ({plan.index(spec) + 1} of {len(plan)})")
        outage_demo.prepare_run(spec.strategy)

    def run(spec: RunSpec) -> tuple[dict, dict]:
        run_args = argparse.Namespace(
            scenario=spec.scenario,
            seed=spec.seed,
            rate=args.rate,
            count=args.count,
            timeout=args.timeout,
            drain_timeout=args.drain_timeout,
        )
        outcomes, report, _ = outage_demo.generate_and_collect(run_args, spec.name, spec.strategy, out)
        saved[spec.name] = outcomes
        return outcomes, report

    def done(spec: RunSpec, summary: dict) -> None:
        note(
            progress,
            f"END {spec.name} success {summary['success_rate_pct']}% p95 {summary['p95_latency_ms']} ms "
            f"in {summary['duration_seconds']:.0f} s",
        )

    started = time.monotonic()
    runs = run_plan(
        plan, reset, run, time.monotonic, done, window_for=lambda scenario: degraded_window(SCENARIOS[scenario])
    )
    result = build_experiment(runs, baseline, args.candidate)
    result["command"] = "python scripts/routing_experiment.py " + " ".join(argv if argv is not None else sys.argv[1:])
    result["health_window_seconds"] = args.health_window
    result["rate_per_second"] = args.rate
    result["wall_clock_seconds"] = round(time.monotonic() - started, 1)
    exit_code = 0
    if args.rel30:
        needed = ("processor-a-outage-7-static", "processor-a-outage-7-rules")
        if not all(name in saved for name in needed):
            sys.exit("FAIL --rel30 needs static and rules runs of processor-a-outage with seed 7")
        rel30 = json.loads(REL30_RESULTS.read_text(encoding="utf-8"))
        result["rel30_agreement"] = rel30_agreement(saved[needed[0]], saved[needed[1]], rel30)
        exit_code = 0 if result["rel30_agreement"]["pass"] else 1
        print("REL30_AGREEMENT=" + ("PASS" if result["rel30_agreement"]["pass"] else "FAIL"))
    if args.compare_with:
        other = Path(args.compare_with)
        other = other if other.is_absolute() else ROOT / other
        determinism = {}
        for name, outcomes in saved.items():
            earlier = json.loads((other / f"{name}.outcomes.json").read_text(encoding="utf-8"))
            determinism[name] = compare_outcome_sets(earlier, outcomes)
        result["determinism"] = {
            "compared_with": args.compare_with,
            "differing_references": determinism,
            "identical": not any(determinism.values()),
        }
        (out / "determinism.json").write_text(json.dumps(result["determinism"], indent=2) + "\n", encoding="utf-8")
        print("DETERMINISM=" + ("PASS" if result["determinism"]["identical"] else "FAIL"))
        exit_code = exit_code or (0 if result["determinism"]["identical"] else 1)
    (out / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (out / "results.md").write_text(render_experiment_markdown(result), encoding="utf-8")
    note(progress, f"RESULTS saved under {out}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
