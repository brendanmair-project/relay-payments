"""REL-30.1/30.7: success-rate uplift, revenue recovered, payment-by-payment pairing, reproducibility and results."""

import pytest

from demo.compare import (
    MANUAL_BASELINE_SECONDS,
    build_results,
    pair_outcomes,
    reproducibility,
    revenue_recovered,
    routing_differences,
    routing_from_events,
    success_rate,
    uplift_pp,
)


def o(status: str, currency: str = "USD", amount: int = 1000) -> dict:
    return {"status": status, "currency": currency, "amount_minor": amount}


BASELINE = {
    "r1": o("captured", "USD", 1000),
    "r2": o("failed", "USD", 2000),
    "r3": o("failed", "EUR", 3000),
    "r4": o("declined", "USD", 500),
    "r5": o("captured", "JPY", 700),
}
RELAY = {
    "r1": o("captured", "USD", 1000),
    "r2": o("captured", "USD", 2000),
    "r3": o("captured", "EUR", 3000),
    "r4": o("declined", "USD", 500),
    "r5": o("failed", "JPY", 700),  # got worse
}


def test_success_rate_is_captured_over_all_payments() -> None:
    assert success_rate(BASELINE) == pytest.approx(0.4)
    assert success_rate(RELAY) == pytest.approx(0.6)
    assert success_rate({}) is None


def test_uplift_is_in_percentage_points() -> None:
    assert uplift_pp(0.4, 0.6) == pytest.approx(20.0)
    assert uplift_pp(0.6, 0.4) == pytest.approx(-20.0)


def test_revenue_recovered_is_relay_minus_baseline_captured_per_currency() -> None:
    assert revenue_recovered(BASELINE, RELAY) == {"EUR": 3000, "JPY": -700, "USD": 2000}


def test_pairing_counts_improved_and_worsened_by_reference() -> None:
    paired = pair_outcomes(BASELINE, RELAY)
    assert paired["references"] == 5
    assert paired["improved"] == 2
    assert paired["improved_from"] == {"failed": 2}
    assert paired["worsened"] == 1
    assert paired["worsened_references"] == ["r5"]
    assert paired["unchanged"] == 2


@pytest.mark.parametrize(
    "relay",
    [
        {k: v for k, v in RELAY.items() if k != "r5"},  # a reference is missing
        {**RELAY, "r6": o("captured")},  # an extra reference
        {**RELAY, "r1": o("captured", "USD", 1001)},  # same reference, different amount
    ],
)
def test_pairing_refuses_runs_that_are_not_the_same_payments(relay: dict) -> None:
    with pytest.raises(ValueError, match="same references"):
        pair_outcomes(BASELINE, relay)
    with pytest.raises(ValueError, match="same references"):
        revenue_recovered(BASELINE, relay)


def test_reproducibility_spread_and_tolerance() -> None:
    inside = reproducibility([80.0, 80.5, 80.9], 1.0, relative=False)
    assert inside["pass"] is True
    assert inside["spread"] == pytest.approx(0.9)
    outside = reproducibility([80.0, 81.1], 1.0, relative=False)
    assert outside["pass"] is False
    relative = reproducibility([1000, 1005, 995], 1.0, relative=True)
    assert relative["spread"] == pytest.approx(1.0, abs=0.01) and relative["pass"] is True
    assert reproducibility([1000, 980], 1.0, relative=True)["pass"] is False
    assert reproducibility([0, 0], 1.0, relative=True)["pass"] is True


def report(rescue_usd: int, source_p50: float) -> dict:
    zero = {"count": 0, "amount_minor_by_currency": {}}
    return {
        "rescue_paths": {
            "retry": {"count": 1, "amount_minor_by_currency": {"USD": rescue_usd}},
            "failover": {"count": 1, "amount_minor_by_currency": {"EUR": 3000}},
            "redrive": zero,
        },
        "explanations": {
            "available": True,
            "sources": {"rules": {"count": 2, "p50_ms": source_p50, "p95_ms": source_p50}},
            "all": {"count": 2, "p50_ms": source_p50, "p95_ms": source_p50},
            "fallback_rate": 1.0,
            "fallback_reasons": {"cause_mismatch": 2},
            "backlog_max": 2,
        },
    }


def run() -> dict:
    lag = {"processor": "a", "lag_seconds": 12.0, "waited_seconds": 65.0}
    return {
        "baseline": {"outcomes": BASELINE, "report": report(0, 10.0), "recovery_lags": [lag]},
        "relay": {"outcomes": RELAY, "report": report(2000, 1500.0), "recovery_lags": [lag]},
    }


def test_build_results_for_one_run() -> None:
    results = build_results(7, "processor-a-outage", [run()])
    assert results["synthetic"] is True
    assert results["health_window_seconds"] == 60  # the default when the caller does not say
    assert "static" in results["baseline_description"]
    assert results["manual_baseline_seconds"] == MANUAL_BASELINE_SECONDS == 7200
    assert results["tolerance"] == {"success_rate_pp": 1.0, "revenue_recovered_pct": 1.0}
    first = results["runs"][0]
    assert first["baseline_success_rate_pct"] == 40.0
    assert first["relay_success_rate_pct"] == 60.0
    assert first["uplift_pp"] == 20.0
    assert first["revenue_recovered"] == {"EUR": 3000, "JPY": -700, "USD": 2000}
    assert first["revenue_by_rescue_path"]["retry"] == {"USD": 2000}
    assert first["revenue_by_rescue_path"]["failover"] == {"EUR": 3000}
    assert first["pairing"]["improved"] == 2
    assert first["median_time_to_explanation_ms"] == 1500.0
    assert first["manual_baseline_ratio"] == pytest.approx(7_200_000 / 1500.0, rel=1e-3)
    assert first["explanations"]["relay"]["fallback_reasons"] == {"cause_mismatch": 2}
    assert first["recovery_lag_seconds"] == 12.0
    assert first["recovery_lags"]["relay"] == [{"processor": "a", "lag_seconds": 12.0, "waited_seconds": 65.0}]
    assert results["reproducibility"] is None  # one run proves nothing about reproducibility


def test_build_results_reproducibility_over_three_runs() -> None:
    drifted = run()
    drifted["relay"]["outcomes"] = {**RELAY, "r4": o("captured", "USD", 500)}
    results = build_results(7, "processor-a-outage", [run(), run(), drifted])
    repro = results["reproducibility"]
    assert repro["runs"] == 3
    assert repro["success_rate_pp"]["values"] == [60.0, 60.0, 80.0]
    assert repro["success_rate_pp"]["pass"] is False
    assert repro["revenue_recovered"]["EUR"]["pass"] is True
    assert repro["revenue_recovered"]["USD"]["pass"] is False  # 2000, 2000, 2500
    assert repro["pass"] is False


def test_a_run_without_recovery_data_has_no_lag() -> None:
    bare = run()
    del bare["relay"]["recovery_lags"], bare["baseline"]["recovery_lags"]
    first = build_results(7, "processor-a-outage", [bare])["runs"][0]
    assert first["recovery_lag_seconds"] is None and first["recovery_lags"] == {"baseline": [], "relay": []}


def test_routing_is_read_from_the_routed_events_in_order() -> None:
    events = [
        {"seq": 1, "type": "payment.received", "processor": None, "reason": None},
        {"seq": 2, "type": "payment.routed", "processor": "A", "reason": "initial"},
        {"seq": 3, "type": "payment.failed", "processor": "A", "reason": "timeout"},
        {"seq": 5, "type": "payment.routed", "processor": "B", "reason": "retry"},
        {"seq": 4, "type": "payment.captured", "processor": "B", "reason": None},
    ]
    assert routing_from_events(events) == ["A:initial", "B:retry"]
    assert routing_from_events([]) == []


def routed(status: str, processor: str, routing: list[str]) -> dict:
    return {"status": status, "currency": "USD", "amount_minor": 100, "processor": processor, "routing": routing}


def test_routing_differences_show_each_runs_outcome_and_routing() -> None:
    same = routed("captured", "A", ["A:initial"])
    runs = [
        {"r1": same, "r2": routed("captured", "B", ["A:initial", "B:failover"])},
        {"r1": same, "r2": routed("declined", "B", ["B:initial"])},
        {"r1": same, "r2": routed("captured", "B", ["A:initial", "B:failover"])},
    ]
    differing = routing_differences(runs)
    assert [d["reference"] for d in differing] == ["r2"]
    assert [x["status"] for x in differing[0]["per_run"]] == ["captured", "declined", "captured"]
    assert differing[0]["per_run"][1]["routing"] == ["B:initial"]
    assert routing_differences([runs[0], runs[0]]) == []


def test_same_status_with_different_routing_is_a_difference() -> None:
    a = routed("captured", "B", ["A:initial", "B:failover"])
    b = routed("captured", "B", ["B:initial"])
    assert [d["reference"] for d in routing_differences([{"r": a}, {"r": b}])] == ["r"]


def test_reproducibility_lists_the_differing_references_per_mode() -> None:
    first, second = run(), run()
    first["relay"]["outcomes"] = {
        **RELAY,
        "r4": routed("declined", "A", ["A:initial"]) | {"currency": "USD", "amount_minor": 500},
    }
    second["relay"]["outcomes"] = {
        **RELAY,
        "r4": routed("declined", "B", ["B:initial"]) | {"currency": "USD", "amount_minor": 500},
    }
    repro = build_results(7, "processor-a-outage", [first, second], health_window_seconds=120)["reproducibility"]
    assert [d["reference"] for d in repro["differing_references"]["relay"]] == ["r4"]
    assert repro["differing_references"]["baseline"] == []
