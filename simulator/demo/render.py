"""Render the results of the scripted outage demo as markdown (REL-30.4). Standard library only."""

from __future__ import annotations

from typing import Any

COMMAND = "python scripts/outage_demo.py --seed {seed} --runs {runs}"


def _num(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.1f}" if value != int(value) else str(int(value))
    return str(value)


def _money(amounts: dict[str, int]) -> str:
    return ", ".join(f"{c} {a}" for c, a in amounts.items()) or "-"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return lines + ["| " + " | ".join(row) + " |" for row in rows] + [""]


def _explanation_rows(label: str, data: dict[str, Any]) -> list[list[str]]:
    if not data.get("available"):
        return [[label, "-", "-", "-", "-", "-", "-"]]
    reasons = ", ".join(f"{r} {n}" for r, n in data["fallback_reasons"].items()) or "none"
    rows = []
    for source, row in data["sources"].items():
        rows.append([label, source, str(row["count"]), _num(row["p50_ms"]), _num(row["p95_ms"]), "", ""])
    rows.append(
        [
            label,
            "all",
            str(data["all"]["count"]),
            _num(data["all"]["p50_ms"]),
            _num(data["all"]["p95_ms"]),
            f"{_num(data['fallback_rate'])} ({reasons})",
            str(data["backlog_max"]),
        ]
    )
    return rows


def _lag(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "-"
    parts = []
    for e in entries:
        lag = "not recovered within the wait" if e["lag_seconds"] is None else f"{_num(e['lag_seconds'])} s"
        parts.append(f"processor {e['processor'].upper()}: {lag} after the outage ended")
    return "; ".join(parts)


def render_markdown(results: dict[str, Any]) -> str:
    runs = results["runs"]
    first = runs[0]
    tol = results["tolerance"]
    manual_hours = results["manual_baseline_seconds"] / 3600
    lines = [
        "# Outage demo results",
        "",
        "**All data is synthetic** (simulated processors, generated payments, no real card data). The baseline is "
        f"**{results['baseline_description']}**.",
        "",
        f"Scenario `{results['scenario']}`, seed {results['seed']}, {len(runs)} run(s). Command: "
        f"`{COMMAND.format(seed=results['seed'], runs=len(runs))}`. Each run resets the system first, runs the "
        "baseline and then Relay routing over the same deterministic payment references, and saves each mode's "
        "per-reference outcomes before the next reset.",
        "",
        "## Method",
        "",
        "- Reset before every mode: `python -m app.demo.reset` (TRUNCATE ... RESTART IDENTITY CASCADE, stream and "
        "groups recreated, request log truncated) and the simulator's outages and profiles restored.",
        "- Same references in both modes (`<scenario>-<seed>-<index>`); the simulator draws its outcomes from the "
        "reference, so a payment meets the same processor behaviour in both modes.",
        "- Drain: before each outage switch the load generator waits until every earlier payment is final (it "
        "polls `GET /payments/{id}` on the public API, 60 s limit, `--no-drain` turns it off). Without it the "
        "outage switch raced the worker: the payment sent just before the switch could meet the outage or not by a "
        "few milliseconds, which moved one EUR payment between runs. The drain makes the outage window exactly "
        "payments 100 to 199.",
        "- The generator waits one health window after an outage ends: the router's health state still holds the "
        "outage failures, so the generator waits one health window (`window_seconds` from `GET /processors/health`) "
        "plus 5 s from the switch before the next payment, and polls the health once a second to record the "
        "recovery lag. Recovery therefore starts from a clean state.",
        f"- Both modes use a health window of {results['health_window_seconds']} s (`HEALTH_WINDOW_SECONDS`; the "
        "default configuration stays 60 s). The scripted outage lasts 100 payments, so the window is set well "
        "above it: the health state never ages out during the outage, and the post-outage wait is one window "
        "plus 5 s.",
        "- The model is warmed with one request before each mode; "
        "payments are sent at a rate the worker keeps up with (2 per second).",
        "",
        "## Headline (run 1)",
        "",
    ]
    lines += _table(
        ["Measure", "Value"],
        [
            ["Success rate, static routing baseline", f"{_num(first['baseline_success_rate_pct'])}%"],
            ["Success rate, Relay routing", f"{_num(first['relay_success_rate_pct'])}%"],
            ["Uplift", f"{first['uplift_pp']:+.1f} percentage points"],
            ["Recovery lag (Relay)", _lag(first["recovery_lags"]["relay"])],
            [
                "Median time to explanation (Relay)",
                f"{_num(first['median_time_to_explanation_ms'])} ms"
                + (
                    f", {_num(first['manual_baseline_ratio'])} times faster than the {_num(manual_hours)}-hour manual "
                    "baseline (assumption)"
                    if first["manual_baseline_ratio"]
                    else ""
                ),
            ],
        ],
    )
    lines += ["### Revenue recovered per currency (minor units)", ""]
    lines += _table(
        ["Currency", "Revenue recovered"],
        [[c, str(a)] for c, a in first["revenue_recovered"].items()],
    )
    lines += ["### Revenue of rescued payments by rescue path (Relay run, minor units)", ""]
    lines += _table(
        ["Rescue path", "Payments", "Amount by currency"],
        [
            [path, str(first["rescued_payments_by_path"][path]), _money(amounts)]
            for path, amounts in first["revenue_by_rescue_path"].items()
        ],
    )
    pairing = first["pairing"]
    from_text = ", ".join(f"{n} from {s}" for s, n in pairing["improved_from"].items()) or "none"
    lines += [
        "### Paired comparison by reference",
        "",
        f"{pairing['references']} references were compared payment by payment: {pairing['improved']} improved to "
        f"captured ({from_text}), {pairing['worsened']} got worse"
        + (f" ({', '.join(pairing['worsened_references'])})" if pairing["worsened_references"] else "")
        + f", {pairing['unchanged']} unchanged.",
        "",
        "### Time to explanation per source (run 1, after warming the model)",
        "",
    ]
    rows = _explanation_rows("Relay", first["explanations"]["relay"])
    rows += _explanation_rows("Baseline", first["explanations"]["baseline"])
    lines += _table(
        ["Run", "Source", "Count", "P50 ms", "P95 ms", "Fallback rate (by reason)", "Largest backlog"], rows
    )
    lines += ["## Runs", ""]
    lines += _table(
        [
            "Run",
            "Baseline success %",
            "Relay success %",
            "Uplift pp",
            "Revenue recovered",
            "Median explanation ms",
            "Recovery lag (Relay)",
        ],
        [
            [
                str(r["run"]),
                _num(r["baseline_success_rate_pct"]),
                _num(r["relay_success_rate_pct"]),
                f"{r['uplift_pp']:+.1f}",
                _money(r["revenue_recovered"]),
                _num(r["median_time_to_explanation_ms"]),
                _lag(r["recovery_lags"]["relay"]),
            ]
            for r in runs
        ],
    )
    lines += ["## Reproducibility", ""]
    repro = results["reproducibility"]
    tolerance_text = (
        f"Tolerance: {_num(tol['success_rate_pp'])} percentage point on success rate and "
        f"{_num(tol['revenue_recovered_pct'])}% on revenue recovered (spread over runs, per currency)."
    )
    if repro is None:
        lines += [f"Reproducibility was not measured: one run. {tolerance_text}", ""]
    else:
        rows = [
            [
                "Success rate, Relay (pp)",
                ", ".join(_num(v) for v in repro["success_rate_pp"]["values"]),
                _num(repro["success_rate_pp"]["spread"]),
                "PASS" if repro["success_rate_pp"]["pass"] else "FAIL",
            ],
            [
                "Success rate, baseline (pp)",
                ", ".join(_num(v) for v in repro["baseline_success_rate_pp"]["values"]),
                _num(repro["baseline_success_rate_pp"]["spread"]),
                "PASS" if repro["baseline_success_rate_pp"]["pass"] else "FAIL",
            ],
        ]
        for currency, item in repro["revenue_recovered"].items():
            rows.append(
                [
                    f"Revenue recovered {currency} (%)",
                    ", ".join(str(v) for v in item["values"]),
                    _num(item["spread"]),
                    "PASS" if item["pass"] else "FAIL",
                ]
            )
        lines += [tolerance_text, ""]
        lines += _table(["Measure", "Values per run", "Spread", "Verdict"], rows)
        lines += [f"Overall: **{'PASS' if repro['pass'] else 'FAIL'}** over {repro['runs']} runs.", ""]
        lines += ["### Differing references", ""]
        differing = repro["differing_references"]
        if not differing["baseline"] and not differing["relay"]:
            lines += ["No reference differs in status, handling processor or routing between the runs.", ""]
        for mode, items in differing.items():
            for item in items:
                cells = [
                    f"{e['status']} via {e['processor']} ({' > '.join(e['routing']) or 'no routing'})"
                    for e in item["per_run"]
                ]
                lines.append(
                    f"- {mode} `{item['reference']}`: " + "; ".join(f"run {i}: {c}" for i, c in enumerate(cells, 1))
                )
        lines.append("")
    lines += [
        "## Metric definitions",
        "",
        "- Success rate: payments that ended `captured` divided by all payments of the run. Declines are cardholder "
        "outcomes and count as not captured in both modes alike.",
        "- Uplift: Relay success rate minus baseline success rate, in percentage points.",
        "- Revenue recovered: per currency, the amount captured in the Relay run minus the amount captured in the "
        "baseline run over the same references, in minor units (cents; whole yen for JPY). Currencies are never "
        "added together. It can differ from the rescue-path split, which sums only payments whose capturing attempt "
        "was routed with reason `retry` or `failover` (or a sweeper re-drive).",
        "- Median time to explanation: the median of the time from a payment's final failure to its stored "
        "automatic explanation, over every declined or failed payment of the Relay run. P95 is the nearest-rank 95th "
        "percentile. The model is warmed with one request before the Relay run.",
        "- Fallback rate: the share of those explanations that used the rules text. Fallbacks are counted per reason: "
        "`cause_mismatch` (the model answered with another cause than the rules, ADR-0013) apart from model "
        "failures (`model_timeout`, `model_unreachable`, `model_error`, citation failures).",
        "- Recovery lag: seconds from the generator switching an outage off until the router's health state for that "
        "processor is no longer `avoided`, polled once a second; measured per run for the Relay mode (the baseline "
        "does not route by health).",
        "- Largest backlog: the most declined or failed payments waiting for an explanation at once.",
        "",
        "## Assumptions",
        "",
        f"- Manual reconstruction baseline (assumption, ADR-0009): {_num(manual_hours)} hours ("
        f"{results['manual_baseline_seconds']} s) for an analyst to reconstruct why one payment failed. It is an "
        "assumption, not a measurement.",
        "- The baseline is static routing, not an industry benchmark: every payment goes to Processor A with no "
        "failover and no retry (ADR-0009, risk R10). The uplift is the benefit of Relay's rules over that "
        "baseline on synthetic data only.",
        "",
    ]
    return "\n".join(lines)
