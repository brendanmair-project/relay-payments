"""Guardrail metrics as pure functions over stored payments and events (REL-51, docs/product/metrics.md).

Definitions (also printed by the report):
- Percentiles use the nearest-rank method: the value at rank ceil(p/100 * n) of the sorted list (rank at least 1).
- Only final payments count for latency and per-processor success. Latency is the time from the payment's
  `payment.received` event to its `payment.final` event.
- Success rate per processor is captured / (captured + failed + declined) over final payments (REL-57, the one
  definition of docs/product/metrics.md, also used by the Grafana panel and `/analytics`): declines are final outcomes
  and count. Each final payment belongs to the processor of its final attempt's `payment.routed` event.
- Rescue paths classify each final captured payment by how its capturing attempt was routed: `retry` (routed with
  reason retry), `failover` (reason failover), or `redrive` (routed normally but the sweeper re-drove the payment).
  Only retry and failover are routing rescues; the static baseline has neither (ADR-0012). Money is summed as integer
  minor units per currency, never mixed.
- Explanation time is the first `final_failure` `payment.explained` event minus the `payment.final` event, per
  `data.source`; `all` is the same over every source. The backlog counts declined/failed final payments still waiting
  for that explanation.
- Fallbacks are the rules explanations among those. Each is counted under the `fallback_reason` of its stored row
  (REL-30.10, ADR-0013): `cause_mismatch` (the model answered with another cause) apart from the model failures
  (`model_timeout`, `model_unreachable`, `model_error`, citation failures), so a model that disagrees is not counted as
  a model outage. `unknown` means no stored row was supplied.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

PERCENTILES = (50, 95, 99)
PROCESSORS = ("A", "B")
RESCUE_PATHS = ("retry", "failover", "redrive")
NOT_AVAILABLE = "not available yet"
CAUSE_MISMATCH = "cause_mismatch"  # ADR-0013: the model answered, but named a different cause than the rules
UNKNOWN_REASON = "unknown"  # a rules explanation whose stored row (and so its fallback_reason) was not supplied


@dataclass(frozen=True)
class PaymentRow:
    id: str
    currency: str
    amount_minor: int
    is_final: bool
    status: str
    created_at: datetime
    status_changed_at: datetime
    processor: str | None = None  # the handling processor (payments.processor), joined for analytics


@dataclass(frozen=True)
class EventRow:
    payment_id: str
    seq: int
    attempt_no: int
    type: str
    occurred_at: datetime
    processor: str | None = None
    reason: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    published_at: datetime | None = None


def nearest_rank(sorted_values: Sequence[int], pct: int) -> int | None:
    """Nearest-rank percentile of an ascending list; None for an empty list. Integer math avoids float rounding."""
    if not sorted_values:
        return None
    rank = max(1, -(-pct * len(sorted_values) // 100))
    return sorted_values[rank - 1]


def _micros(delta: timedelta) -> int:
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _ms(micros: int | None) -> float | None:
    return None if micros is None else round(micros / 1000, 3)


def _percentile_fields(values: Iterable[int], pcts: Sequence[int] = PERCENTILES) -> dict[str, float | None]:
    ordered = sorted(values)
    return {f"p{p}_ms": _ms(nearest_rank(ordered, p)) for p in pcts}


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _by_payment(events: Sequence[EventRow]) -> dict[str, list[EventRow]]:
    grouped: dict[str, list[EventRow]] = defaultdict(list)
    for event in events:
        grouped[event.payment_id].append(event)
    for items in grouped.values():
        items.sort(key=lambda e: e.seq)
    return grouped


def timelines_by_payment(events: Sequence[EventRow]) -> dict[str, list[EventRow]]:
    """Each payment's events in `seq` order (public for the analytics, REL-37)."""
    return _by_payment(events)


def _first(items: Iterable[EventRow], type_: str) -> EventRow | None:
    return next((e for e in items if e.type == type_), None)


def _routed_for(items: Sequence[EventRow], attempt_no: int) -> EventRow | None:
    routed = [e for e in items if e.type == "payment.routed" and e.attempt_no == attempt_no]
    return routed[-1] if routed else None


def latency_metrics(payments: Sequence[PaymentRow], timelines: dict[str, list[EventRow]]) -> dict[str, Any]:
    values: list[int] = []
    for payment in payments:
        if not payment.is_final:
            continue
        received = _first(timelines.get(payment.id, []), "payment.received")
        final = _first(timelines.get(payment.id, []), "payment.final")
        if received and final:
            values.append(_micros(final.occurred_at - received.occurred_at))
    return {"count": len(values), **_percentile_fields(values)}


def publish_lag_metrics(events: Sequence[EventRow]) -> dict[str, Any]:
    lags = [_micros(e.published_at - e.occurred_at) for e in events if e.published_at is not None]
    return {"published": len(lags), "unpublished": len(events) - len(lags), **_percentile_fields(lags)}


def processor_success(payments: Sequence[PaymentRow], timelines: dict[str, list[EventRow]]) -> dict[str, Any]:
    """The one success-rate definition (REL-57, docs/product/metrics.md): captured over final payments.

    Each final payment counts once, under the processor of its final attempt (the `payment.routed` event of the
    `payment.final` event's attempt, else `payments.processor`), with the outcome `payment.final` records. Declines
    are final outcomes and stay in the denominator; a retried first attempt is not a final payment.
    """
    counts = {p: {"captured": 0, "failed": 0, "declined": 0} for p in PROCESSORS}
    for payment in payments:
        if not payment.is_final:
            continue
        items = timelines.get(payment.id, [])
        final = _first(items, "payment.final")
        outcome = final.data.get("outcome") if final else payment.status
        if outcome not in ("captured", "failed", "declined"):
            continue
        routed = _routed_for(items, final.attempt_no) if final else None
        processor = (routed.processor if routed else None) or payment.processor
        if processor in counts:
            counts[processor][str(outcome)] += 1
    return {
        p: {**c, "success_rate": _rate(c["captured"], c["captured"] + c["failed"] + c["declined"])}
        for p, c in counts.items()
    }


def not_final_payments(payments: Sequence[PaymentRow], as_of: datetime, stuck_after: timedelta) -> dict[str, Any]:
    stuck = [
        {
            "payment_id": p.id,
            "status": p.status,
            "seconds_since_change": round((as_of - p.status_changed_at).total_seconds(), 3),
        }
        for p in payments
        if not p.is_final and as_of - p.status_changed_at > stuck_after
    ]
    stuck.sort(key=lambda s: str(s["payment_id"]))
    return {"threshold_seconds": stuck_after.total_seconds(), "count": len(stuck), "payments": stuck}


def rescue_paths(payments: Sequence[PaymentRow], timelines: dict[str, list[EventRow]]) -> dict[str, Any]:
    counts = dict.fromkeys(RESCUE_PATHS, 0)
    money: dict[str, dict[str, int]] = {path: defaultdict(int) for path in RESCUE_PATHS}
    for payment in payments:
        if not (payment.is_final and payment.status == "captured"):
            continue
        items = timelines.get(payment.id, [])
        captured = _first(items, "payment.captured")
        routed = _routed_for(items, captured.attempt_no) if captured else None
        reason = routed.reason if routed else None
        if reason in ("retry", "failover"):
            path: str | None = reason
        elif _first(items, "payment.redriven"):
            path = "redrive"
        else:
            path = None
        if path is not None:
            counts[path] += 1
            money[path][payment.currency] += payment.amount_minor
    return {
        path: {"count": counts[path], "amount_minor_by_currency": dict(sorted(money[path].items()))}
        for path in RESCUE_PATHS
    }


def explanation_metrics(
    payments: Sequence[PaymentRow],
    timelines: dict[str, list[EventRow]],
    fallback_reasons: Mapping[int, str | None] | None = None,
) -> dict[str, Any]:
    if not any(e.type == "payment.explained" for items in timelines.values() for e in items):
        return {"available": False, "note": NOT_AVAILABLE}
    durations: dict[str, list[int]] = defaultdict(list)
    reasons: dict[str, int] = defaultdict(int)
    changes: list[tuple[datetime, int]] = []
    waiting_at_end = 0
    for payment in payments:
        items = timelines.get(payment.id, [])
        final = _first(items, "payment.final")
        if final is None:
            continue
        explained = next(
            (
                e
                for e in items
                if e.type == "payment.explained" and e.data.get("trigger", "final_failure") == "final_failure"
            ),
            None,
        )
        if explained is not None:
            source = str(explained.data.get("source", "unknown"))
            durations[source].append(_micros(explained.occurred_at - final.occurred_at))
            if source == "rules":
                stored = (fallback_reasons or {}).get(explained.data.get("explanation_id", -1))
                reasons[stored or UNKNOWN_REASON] += 1
        if final.data.get("outcome") in ("declined", "failed"):
            changes.append((final.occurred_at, 1))
            if explained is None:
                waiting_at_end += 1
            else:
                changes.append((explained.occurred_at, -1))
    backlog = peak = 0
    for _, delta in sorted(changes, key=lambda c: (c[0], -c[1])):  # a tie counts the arrival first: the larger backlog
        backlog += delta
        peak = max(peak, backlog)
    total = sum(len(v) for v in durations.values())
    every = [d for values in durations.values() for d in values]
    return {
        "available": True,
        "sources": {
            source: {"count": len(values), **_percentile_fields(values, (50, 95))}
            for source, values in sorted(durations.items())
        },
        "all": {"count": len(every), **_percentile_fields(every, (50, 95))},
        "fallback_rate": _rate(len(durations.get("rules", [])), total),
        "fallback_reasons": dict(sorted(reasons.items())),
        "fallback_cause_mismatch": reasons.get(CAUSE_MISMATCH, 0),
        "fallback_model_failures": sum(n for r, n in reasons.items() if r not in (CAUSE_MISMATCH, UNKNOWN_REASON)),
        "backlog_max": peak,
        "backlog_end": waiting_at_end,
    }


def compute_metrics(
    payments: Sequence[PaymentRow],
    events: Sequence[EventRow],
    *,
    as_of: datetime,
    stuck_after: timedelta,
    fallback_reasons: Mapping[int, str | None] | None = None,
) -> dict[str, Any]:
    timelines = _by_payment(events)
    return {
        "latency": latency_metrics(payments, timelines),
        "publish_lag": publish_lag_metrics(events),
        "processor_success": processor_success(payments, timelines),
        "not_final": not_final_payments(payments, as_of, stuck_after),
        "rescue_paths": rescue_paths(payments, timelines),
        "explanations": explanation_metrics(payments, timelines, fallback_reasons),
    }
