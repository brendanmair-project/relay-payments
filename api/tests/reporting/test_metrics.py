"""REL-51: exact metric values on a small fixed set of events (pure functions, no database)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.reporting.metrics import EventRow, PaymentRow, compute_metrics, nearest_rank

T0 = datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)
STUCK_AFTER = timedelta(seconds=40)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def pay(pid: str, currency: str, amount: int, status: str, final: bool, changed: float = 0.0) -> PaymentRow:
    return PaymentRow(pid, currency, amount, final, status, at(0), at(changed))


def ev(pid: str, seq: int, type_: str, t: float, attempt: int = 0, **kw: Any) -> EventRow:
    return EventRow(payment_id=pid, seq=seq, attempt_no=attempt, type=type_, occurred_at=at(t), **kw)


def captured_direct(pid: str, final_at: float, processor: str = "A", reason: str = "initial") -> list[EventRow]:
    return [
        ev(pid, 1, "payment.received", 0),
        ev(pid, 2, "payment.routed", 0.1, 1, processor=processor, reason=reason),
        ev(pid, 3, "payment.captured", final_at, 1),
        ev(pid, 4, "payment.final", final_at, 1, data={"outcome": "captured"}),
    ]


def scenario() -> tuple[list[PaymentRow], list[EventRow]]:
    payments = [
        pay("p1", "USD", 1000, "captured", True, 1.0),
        pay("p2", "USD", 2000, "captured", True, 6.0),
        pay("p3", "EUR", 3000, "captured", True, 2.0),
        pay("p4", "USD", 500, "declined", True, 3.0),
        pay("p5", "JPY", 700, "captured", True, 40.0),
        pay("p6", "USD", 900, "failed", False, 4.0),
        pay("p7", "USD", 100, "failed", True, 8.0),
    ]
    events = captured_direct("p1", 1.0)
    # p2: failed on A (timeout), retried on B, captured there.
    events += [
        ev("p2", 1, "payment.received", 0),
        ev("p2", 2, "payment.routed", 0.1, 1, processor="A", reason="initial"),
        ev("p2", 3, "payment.failed", 5.0, 1, processor="A", reason="timeout"),
        ev("p2", 4, "payment.retry_scheduled", 5.0, 1),
        ev("p2", 5, "payment.routed", 5.5, 2, processor="B", reason="retry"),
        ev("p2", 6, "payment.captured", 6.0, 2),
        ev("p2", 7, "payment.final", 6.0, 2, data={"outcome": "captured"}),
    ]
    events += captured_direct("p3", 2.0, processor="B", reason="failover")
    events += [
        ev("p4", 1, "payment.received", 0),
        ev("p4", 2, "payment.routed", 0.1, 1, processor="A", reason="initial"),
        ev("p4", 3, "payment.declined", 3.0, 1, reason="do_not_honor"),
        ev("p4", 4, "payment.final", 3.0, 1, data={"outcome": "declined"}),
    ]
    # p5: stalled in received, re-driven by the sweeper, then captured on its first attempt.
    events += [
        ev("p5", 1, "payment.received", 0),
        ev("p5", 2, "payment.redriven", 31),
        ev("p5", 3, "payment.routed", 32, 1, processor="A", reason="initial"),
        ev("p5", 4, "payment.captured", 40.0, 1),
        ev("p5", 5, "payment.final", 40.0, 1, data={"outcome": "captured"}),
    ]
    # p6: failed on A and still retrying: not final, not counted anywhere but the stuck list.
    events += [
        ev("p6", 1, "payment.received", 0),
        ev("p6", 2, "payment.routed", 0.1, 1, processor="A", reason="initial"),
        ev("p6", 3, "payment.failed", 4.0, 1, processor="A", reason="outage"),
        ev("p6", 4, "payment.retry_scheduled", 4.0, 1),
    ]
    # p7: final failure on A (no retry left).
    events += [
        ev("p7", 1, "payment.received", 0),
        ev("p7", 2, "payment.routed", 0.1, 1, processor="A", reason="initial"),
        ev("p7", 3, "payment.failed", 8.0, 1, processor="A", reason="timeout"),
        ev("p7", 4, "payment.final", 8.0, 1, data={"outcome": "failed"}),
    ]
    return payments, events


@pytest.mark.parametrize(
    ("pct", "expected"),
    [(0, 10), (10, 10), (11, 20), (50, 50), (51, 60), (90, 90), (95, 100), (99, 100), (100, 100)],
)
def test_nearest_rank_on_a_fixed_list(pct: int, expected: int) -> None:
    # Nearest rank: the value at rank ceil(pct/100 * n) of the sorted list (1-based), rank at least 1.
    assert nearest_rank([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], pct) == expected


def test_nearest_rank_of_nothing_is_none() -> None:
    assert nearest_rank([], 50) is None


def test_latency_percentiles_use_final_payments_only() -> None:
    payments, events = scenario()
    result = compute_metrics(payments, events, as_of=at(1000), stuck_after=STUCK_AFTER)
    # Final latencies in ms, sorted: 1000, 2000, 3000, 6000, 8000, 40000 (p6 is retrying and is excluded).
    assert result["latency"] == {"count": 6, "p50_ms": 3000.0, "p95_ms": 40000.0, "p99_ms": 40000.0}


def test_latency_of_nothing_is_empty_not_zero() -> None:
    result = compute_metrics([], [], as_of=at(1000), stuck_after=STUCK_AFTER)
    assert result["latency"] == {"count": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None}


def test_processor_success_counts_each_final_payment_once_for_its_handling_processor() -> None:
    payments, events = scenario()
    result = compute_metrics(payments, events, as_of=at(1000), stuck_after=STUCK_AFTER)
    # REL-57 (one success-rate definition, docs/product/metrics.md): captured over final payments, declines included,
    # each final payment counted once under the processor of its final attempt. The old test counted every attempt,
    # so p2's retried first attempt on A was a failure of A; the payment is final-captured on B, so A has failed 1 (p7).
    # A: p1 captured, p4 declined, p5 captured, p7 failed (p6 is not final: excluded). B: p2 and p3 captured.
    assert result["processor_success"] == {
        "A": {"captured": 2, "failed": 1, "declined": 1, "success_rate": 0.5},
        "B": {"captured": 2, "failed": 0, "declined": 0, "success_rate": 1.0},
    }


def test_declines_count_in_the_denominator_so_the_old_and_new_definitions_differ() -> None:
    # One capture and one decline on A. Old definition (captured over captured plus failed): 1 / 1 = 1.0.
    # REL-57 definition (captured over final payments): 1 / 2 = 0.5.
    payments = [pay("p1", "USD", 1000, "captured", True, 1.0), pay("p4", "USD", 500, "declined", True, 3.0)]
    events = captured_direct("p1", 1.0) + [
        ev("p4", 1, "payment.received", 0),
        ev("p4", 2, "payment.routed", 0.1, 1, processor="A", reason="initial"),
        ev("p4", 3, "payment.declined", 3.0, 1, reason="do_not_honor"),
        ev("p4", 4, "payment.final", 3.0, 1, data={"outcome": "declined"}),
    ]
    result = compute_metrics(payments, events, as_of=at(10), stuck_after=STUCK_AFTER)
    assert result["processor_success"]["A"] == {"captured": 1, "failed": 0, "declined": 1, "success_rate": 0.5}


def test_processor_without_final_payments_has_no_rate() -> None:
    payments = [pay("p4", "USD", 500, "declined", True, 3.0)]
    events = [
        ev("p4", 1, "payment.received", 0),
        ev("p4", 2, "payment.routed", 0.1, 1, processor="A", reason="initial"),
        ev("p4", 3, "payment.declined", 3.0, 1, reason="do_not_honor"),
        ev("p4", 4, "payment.final", 3.0, 1, data={"outcome": "declined"}),
    ]
    result = compute_metrics(payments, events, as_of=at(10), stuck_after=STUCK_AFTER)
    assert result["processor_success"]["A"] == {"captured": 0, "failed": 0, "declined": 1, "success_rate": 0.0}
    assert result["processor_success"]["B"] == {"captured": 0, "failed": 0, "declined": 0, "success_rate": None}


def test_revenue_recovered_is_split_by_rescue_path_and_currency() -> None:
    payments, events = scenario()
    result = compute_metrics(payments, events, as_of=at(1000), stuck_after=STUCK_AFTER)
    assert result["rescue_paths"] == {
        "retry": {"count": 1, "amount_minor_by_currency": {"USD": 2000}},
        "failover": {"count": 1, "amount_minor_by_currency": {"EUR": 3000}},
        "redrive": {"count": 1, "amount_minor_by_currency": {"JPY": 700}},
    }


def test_rescue_paths_never_mix_currencies_and_empty_paths_are_explicit() -> None:
    payments = [pay("a", "USD", 100, "captured", True, 2.0), pay("b", "EUR", 250, "captured", True, 2.0)]
    events = captured_direct("a", 2.0, reason="failover") + captured_direct("b", 2.0, reason="failover")
    result = compute_metrics(payments, events, as_of=at(10), stuck_after=STUCK_AFTER)
    assert result["rescue_paths"]["failover"] == {"count": 2, "amount_minor_by_currency": {"EUR": 250, "USD": 100}}
    assert result["rescue_paths"]["retry"] == {"count": 0, "amount_minor_by_currency": {}}


def test_publish_lag_percentiles_and_unpublished_count() -> None:
    lags = [0.1, 0.2, 0.3, 0.4, 0.5]
    events = [ev("p", i + 1, "payment.received", 10 * i, published_at=at(10 * i + lag)) for i, lag in enumerate(lags)]
    events += [ev("p", 6, "attempt.authorize_result", 60), ev("p", 7, "attempt.capture_result", 61)]
    result = compute_metrics([], events, as_of=at(100), stuck_after=STUCK_AFTER)
    assert result["publish_lag"] == {
        "published": 5,
        "unpublished": 2,
        "p50_ms": 300.0,
        "p95_ms": 500.0,
        "p99_ms": 500.0,
    }


def test_payments_not_final_past_the_threshold_are_listed_with_ids() -> None:
    payments, events = scenario()
    late = compute_metrics(payments, events, as_of=at(1000), stuck_after=STUCK_AFTER)
    assert late["not_final"] == {
        "threshold_seconds": 40.0,
        "count": 1,
        "payments": [{"payment_id": "p6", "status": "failed", "seconds_since_change": 996.0}],
    }
    # Exactly at the threshold is still inside it: the sweeper has not yet had its chance.
    early = compute_metrics(payments, events, as_of=at(44), stuck_after=STUCK_AFTER)
    assert early["not_final"] == {"threshold_seconds": 40.0, "count": 0, "payments": []}


def test_explanations_not_available_without_explained_events() -> None:
    payments, events = scenario()
    result = compute_metrics(payments, events, as_of=at(1000), stuck_after=STUCK_AFTER)
    assert result["explanations"] == {"available": False, "note": "not available yet"}


def test_explanations_per_source_with_fallback_rate_and_backlog() -> None:
    payments = [
        pay("p4", "USD", 500, "declined", True, 3.0),
        pay("p7", "USD", 100, "failed", True, 8.0),
        pay("p8", "USD", 100, "failed", True, 9.0),
    ]
    events = [
        ev("p4", 4, "payment.final", 3.0, 1, data={"outcome": "declined"}),
        ev("p4", 5, "payment.explained", 3.05, 1, data={"source": "rules", "trigger": "final_failure"}),
        # A later regeneration by the model is not the automatic explanation and must be ignored.
        ev("p4", 6, "payment.explained", 99.0, 1, data={"source": "model", "trigger": "regenerate"}),
        ev("p7", 4, "payment.final", 8.0, 1, data={"outcome": "failed"}),
        ev("p7", 5, "payment.explained", 18.0, 1, data={"source": "model", "trigger": "final_failure"}),
        ev("p8", 4, "payment.final", 9.0, 1, data={"outcome": "failed"}),
    ]
    result = compute_metrics(payments, events, as_of=at(100), stuck_after=STUCK_AFTER)
    assert result["explanations"] == {
        "available": True,
        "sources": {
            "model": {"count": 1, "p50_ms": 10000.0, "p95_ms": 10000.0},
            "rules": {"count": 1, "p50_ms": 50.0, "p95_ms": 50.0},
        },
        "all": {"count": 2, "p50_ms": 50.0, "p95_ms": 10000.0},
        "fallback_rate": 0.5,
        "fallback_reasons": {"unknown": 1},
        "fallback_cause_mismatch": 0,
        "fallback_model_failures": 0,
        "backlog_max": 2,
        "backlog_end": 1,
    }


def test_fallbacks_are_counted_per_reason_with_cause_mismatch_apart() -> None:
    """ADR-0013: a model that disagrees (cause_mismatch) is not counted as a model outage."""
    reasons = ("cause_mismatch", "cause_mismatch", "model_timeout", "model_unreachable", "model_error", None)
    payments = [pay(f"q{i}", "USD", 100, "declined", True, 1.0) for i in range(len(reasons) + 1)]
    events: list[EventRow] = []
    for i, _ in enumerate(reasons):
        pid = f"q{i}"
        events += [
            ev(pid, 1, "payment.final", 1.0, 1, data={"outcome": "declined"}),
            ev(pid, 2, "payment.explained", 2.0, 1, data={"explanation_id": 10 + i, "source": "rules"}),
        ]
    # A model explanation has no fallback reason and is not a fallback; a regenerated one is ignored.
    events += [
        ev("q6", 1, "payment.final", 1.0, 1, data={"outcome": "declined"}),
        ev("q6", 2, "payment.explained", 3.0, 1, data={"explanation_id": 99, "source": "model"}),
        ev(
            "q0",
            3,
            "payment.explained",
            9.0,
            1,
            data={"explanation_id": 98, "source": "rules", "trigger": "regenerate"},
        ),
    ]
    stored = {10 + i: reason for i, reason in enumerate(reasons)} | {99: None, 98: "model_error"}
    result = compute_metrics(payments, events, as_of=at(100), stuck_after=STUCK_AFTER, fallback_reasons=stored)
    explanations = result["explanations"]
    assert explanations["fallback_reasons"] == {
        "cause_mismatch": 2,
        "model_error": 1,
        "model_timeout": 1,
        "model_unreachable": 1,
        "unknown": 1,
    }
    assert explanations["fallback_cause_mismatch"] == 2
    assert explanations["fallback_model_failures"] == 3
    assert explanations["fallback_rate"] == round(6 / 7, 4)
    assert explanations["all"]["count"] == 7
