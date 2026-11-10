"""Analytics figures as a pure function over stored payments and events (REL-37).

Everything event-derived comes from `payment_events`; amounts, currency and the handling processor come from the
`payments` rows (events carry no money, and terminal events have no processor). The per-processor success rate, the
end-to-end latency, the rescue paths and the explanation timings are the `app.reporting` functions (ADR-0009, ADR-0012),
not a second implementation. Added here: processor call latency from the attempt events, and failure reasons.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from app.reporting.metrics import (
    PROCESSORS,
    EventRow,
    PaymentRow,
    explanation_metrics,
    latency_metrics,
    nearest_rank,
    processor_success,
    rescue_paths,
    timelines_by_payment,
)

ATTEMPT_RESULTS = ("attempt.authorize_result", "attempt.capture_result")
FAILURE_TYPES = ("payment.failed", "payment.declined")
UNKNOWN_REASON = "unknown"
PERCENTILES = (50, 95, 99)


def _call_latency(events: Sequence[EventRow], processor: str) -> dict[str, Any]:
    """Processor call latency: `data.latency_ms` of the attempt events of this processor (nearest rank, in ms)."""
    micros = sorted(
        round(float(e.data["latency_ms"]) * 1000)
        for e in events
        if e.type in ATTEMPT_RESULTS and e.processor == processor and isinstance(e.data.get("latency_ms"), int | float)
    )
    out: dict[str, Any] = {"count": len(micros)}
    for pct in PERCENTILES:
        rank = nearest_rank(micros, pct)
        out[f"p{pct}_ms"] = None if rank is None else round(rank / 1000, 3)
    return out


def _failure_reasons(timelines: Mapping[str, list[EventRow]]) -> dict[str, dict[str, int]]:
    """Counts of failed and declined events by reason per processor; a terminal event takes its attempt's processor."""
    reasons: dict[str, dict[str, int]] = {p: defaultdict(int) for p in PROCESSORS}
    for items in timelines.values():
        routed = {e.attempt_no: e.processor for e in items if e.type == "payment.routed"}
        for event in items:
            if event.type not in FAILURE_TYPES:
                continue
            processor = event.processor or routed.get(event.attempt_no)
            if processor in reasons:
                reasons[processor][event.reason or UNKNOWN_REASON] += 1
    return {p: dict(sorted(counts.items())) for p, counts in reasons.items()}


def analytics_figures(
    payments: Sequence[PaymentRow],
    events: Sequence[EventRow],
    *,
    processor: str | None = None,
    fallback_reasons: Mapping[int, str | None] | None = None,
) -> dict[str, Any]:
    timelines = timelines_by_payment(events)
    success = processor_success(payments, timelines)
    reasons = _failure_reasons(timelines)
    routed_to: dict[str, set[str]] = {p: set() for p in PROCESSORS}
    for event in events:
        if event.type == "payment.routed" and event.processor in routed_to:
            routed_to[event.processor].add(event.payment_id)
    processors: dict[str, Any] = {}
    for name in PROCESSORS:
        if processor is not None and name != processor:
            continue
        handled = [p for p in payments if p.processor == name]
        processors[name] = {
            "volume": len(routed_to[name]),
            **success[name],
            "latency": latency_metrics(handled, timelines),
            "call_latency": _call_latency(events, name),
            "failure_reasons": reasons[name],
        }
    return {
        "volume": {"payments": len(payments), "final": sum(p.is_final for p in payments)},
        "latency": latency_metrics(payments, timelines),
        "processors": processors,
        "revenue_recovered_by_rescue_path": rescue_paths(payments, timelines),
        "time_to_explanation": explanation_metrics(payments, timelines, fallback_reasons),
    }
