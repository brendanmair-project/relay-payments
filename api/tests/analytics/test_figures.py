"""REL-37: each analytics figure on a small fixed set of events (pure functions, no database)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.analytics.figures import analytics_figures
from app.reporting.metrics import EventRow, PaymentRow, explanation_metrics, rescue_paths, timelines_by_payment

T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def pay(pid: str, currency: str, amount: int, status: str, processor: str) -> PaymentRow:
    return PaymentRow(pid, currency, amount, True, status, at(0), at(0), processor)


def ev(pid: str, seq: int, type_: str, t: float, attempt: int = 1, **kw: Any) -> EventRow:
    return EventRow(payment_id=pid, seq=seq, attempt_no=attempt, type=type_, occurred_at=at(t), **kw)


def routed(pid: str, seq: int, processor: str, reason: str, attempt: int = 1) -> EventRow:
    return ev(pid, seq, "payment.routed", 0.1 if attempt == 1 else 5.5, attempt, processor=processor, reason=reason)


def attempt(pid: str, seq: int, kind: str, processor: str, latency_ms: int, attempt_no: int = 1) -> EventRow:
    return ev(pid, seq, f"attempt.{kind}_result", 0.5, attempt_no, processor=processor, data={"latency_ms": latency_ms})


def final(pid: str, seq: int, t: float, outcome: str, attempt_no: int = 1) -> EventRow:
    return ev(pid, seq, "payment.final", t, attempt_no, data={"outcome": outcome})


PAYMENTS = [
    pay("p1", "USD", 1000, "captured", "A"),
    pay("p2", "USD", 2000, "captured", "B"),  # failed on A (timeout), retried on B: handled by B
    pay("p3", "EUR", 3000, "captured", "B"),  # failover to B
    pay("p4", "USD", 500, "declined", "A"),
    pay("p5", "JPY", 700, "failed", "A"),
]

EVENTS = [
    ev("p1", 1, "payment.received", 0, 0),
    routed("p1", 2, "A", "initial"),
    attempt("p1", 3, "authorize", "A", 100),
    attempt("p1", 4, "capture", "A", 200),
    ev("p1", 5, "payment.captured", 1.0),
    final("p1", 6, 1.0, "captured"),
    ev("p2", 1, "payment.received", 0, 0),
    routed("p2", 2, "A", "initial"),
    attempt("p2", 3, "authorize", "A", 5000),
    ev("p2", 4, "payment.failed", 5.0, 1, processor="A", reason="timeout"),
    routed("p2", 5, "B", "retry", 2),
    attempt("p2", 6, "authorize", "B", 300, 2),
    ev("p2", 7, "payment.captured", 6.0, 2),
    final("p2", 8, 6.0, "captured", 2),
    ev("p3", 1, "payment.received", 0, 0),
    routed("p3", 2, "B", "failover"),
    attempt("p3", 3, "authorize", "B", 400),
    ev("p3", 4, "payment.captured", 2.0),
    final("p3", 5, 2.0, "captured"),
    ev("p4", 1, "payment.received", 0, 0),
    routed("p4", 2, "A", "initial"),
    attempt("p4", 3, "authorize", "A", 150),
    ev("p4", 4, "payment.declined", 3.0, 1, reason="do_not_honor"),
    final("p4", 5, 3.0, "declined"),
    ev("p4", 6, "payment.explained", 5.0, 1, data={"source": "model", "explanation_id": 6, "trigger": "final_failure"}),
    ev("p5", 1, "payment.received", 0, 0),
    routed("p5", 2, "A", "initial"),
    attempt("p5", 3, "authorize", "A", 5000),
    ev("p5", 4, "payment.failed", 8.0, 1, processor="A", reason="outage"),
    final("p5", 5, 8.0, "failed"),
    ev(
        "p5", 6, "payment.explained", 11.0, 1, data={"source": "rules", "explanation_id": 7, "trigger": "final_failure"}
    ),
]


def figures(processor: str | None = None) -> dict[str, Any]:
    return analytics_figures(PAYMENTS, EVENTS, processor=processor, fallback_reasons={7: "model_timeout"})


def test_volume_counts_payments_and_final_ones() -> None:
    assert figures()["volume"] == {"payments": 5, "final": 5}
    assert {name: row["volume"] for name, row in figures()["processors"].items()} == {"A": 4, "B": 2}


def test_success_rate_is_captured_over_final_payments_and_declines_count() -> None:
    a, b = figures()["processors"]["A"], figures()["processors"]["B"]
    # REL-57: each final payment once, under its handling processor: p2 is final on B, so A's failures are p5 only.
    assert (a["captured"], a["failed"], a["declined"], a["success_rate"]) == (1, 1, 1, 0.3333)
    assert (b["captured"], b["failed"], b["declined"], b["success_rate"]) == (2, 0, 0, 1.0)


def test_end_to_end_latency_percentiles_overall_and_by_handling_processor() -> None:
    result = figures()
    assert result["latency"] == {"count": 5, "p50_ms": 3000.0, "p95_ms": 8000.0, "p99_ms": 8000.0}
    assert result["processors"]["A"]["latency"] == {"count": 3, "p50_ms": 3000.0, "p95_ms": 8000.0, "p99_ms": 8000.0}
    assert result["processors"]["B"]["latency"] == {"count": 2, "p50_ms": 2000.0, "p95_ms": 6000.0, "p99_ms": 6000.0}


def test_processor_call_latency_comes_from_the_attempt_events() -> None:
    result = figures()["processors"]
    assert result["A"]["call_latency"] == {"count": 5, "p50_ms": 200.0, "p95_ms": 5000.0, "p99_ms": 5000.0}
    assert result["B"]["call_latency"] == {"count": 2, "p50_ms": 300.0, "p95_ms": 400.0, "p99_ms": 400.0}


def test_failure_reasons_are_counted_per_processor_and_terminal_events_take_their_attempts_processor() -> None:
    result = figures()["processors"]
    assert result["A"]["failure_reasons"] == {"do_not_honor": 1, "outage": 1, "timeout": 1}
    assert result["B"]["failure_reasons"] == {}


def test_revenue_recovered_is_split_by_rescue_path_and_currency() -> None:
    assert figures()["revenue_recovered_by_rescue_path"] == {
        "retry": {"count": 1, "amount_minor_by_currency": {"USD": 2000}},
        "failover": {"count": 1, "amount_minor_by_currency": {"EUR": 3000}},
        "redrive": {"count": 0, "amount_minor_by_currency": {}},
    }


def test_time_to_explanation_per_source_with_fallback_reasons() -> None:
    explained = figures()["time_to_explanation"]
    assert explained["available"] is True
    assert explained["sources"] == {
        "model": {"count": 1, "p50_ms": 2000.0, "p95_ms": 2000.0},
        "rules": {"count": 1, "p50_ms": 3000.0, "p95_ms": 3000.0},
    }
    assert explained["fallback_rate"] == 0.5
    assert explained["fallback_reasons"] == {"model_timeout": 1}


def test_reporting_functions_are_reused_with_identical_numbers() -> None:
    timelines = timelines_by_payment(EVENTS)
    result = figures()
    assert result["revenue_recovered_by_rescue_path"] == rescue_paths(PAYMENTS, timelines)
    assert result["time_to_explanation"] == explanation_metrics(PAYMENTS, timelines, {7: "model_timeout"})


def test_the_processor_filter_keeps_only_that_processor() -> None:
    assert list(figures("B")["processors"]) == ["B"]
    assert list(figures("A")["processors"]) == ["A"]


def test_empty_input_gives_zero_counts_and_null_rates() -> None:
    result = analytics_figures([], [], processor=None)
    assert result["volume"] == {"payments": 0, "final": 0}
    assert result["processors"]["A"]["success_rate"] is None
    assert result["processors"]["A"]["call_latency"] == {"count": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None}
    assert result["time_to_explanation"]["available"] is False
