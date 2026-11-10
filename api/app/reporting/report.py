"""Assemble the guardrail report from the database and the request log, and render it as a table (REL-51).

A run is a window over payments: those created in [since, until) whose `reference` starts with `reference_prefix`
(the load generator's `<scenario>-<seed>-`); no filter means all stored data. Every event of those payments is
measured. The request log has no payment reference, so the 5xx rate uses only the time window.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Payment, PaymentEvent, PaymentExplanation
from app.reporting.metrics import NOT_AVAILABLE, EventRow, PaymentRow, compute_metrics
from app.reporting.requestlog import read_request_log, summarize_request_log


@dataclass(frozen=True)
class Window:
    since: datetime | None = None
    until: datetime | None = None
    reference_prefix: str | None = None
    processor: str | None = None  # only payments with a `payment.routed` event for this processor (analytics)


def iso(moment: datetime | None) -> str | None:
    """UTC ISO 8601 with a `Z` suffix; None stays None."""
    return None if moment is None else moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _cohort(window: Window) -> Any:
    clauses: list[Any] = []
    if window.since is not None:
        clauses.append(Payment.created_at >= window.since)
    if window.until is not None:
        clauses.append(Payment.created_at < window.until)
    if window.reference_prefix:
        clauses.append(Payment.reference.startswith(window.reference_prefix, autoescape=True))
    if window.processor:
        routed = sa.select(PaymentEvent.payment_id).where(
            PaymentEvent.type == "payment.routed", PaymentEvent.processor == window.processor
        )
        clauses.append(Payment.id.in_(routed))
    return sa.and_(*clauses) if clauses else sa.true()


def load_rows(session: Session, window: Window) -> tuple[list[PaymentRow], list[EventRow]]:
    cohort = _cohort(window)
    payments = [
        PaymentRow(
            id=str(p.id),
            currency=p.currency,
            amount_minor=p.amount_minor,
            is_final=p.is_final,
            status=p.status,
            created_at=p.created_at,
            status_changed_at=p.status_changed_at,
            processor=p.processor,
        )
        for p in session.scalars(sa.select(Payment).where(cohort).order_by(Payment.created_at, Payment.id))
    ]
    ids = sa.select(Payment.id).where(cohort)
    events = [
        EventRow(
            payment_id=str(e.payment_id),
            seq=e.seq,
            attempt_no=e.attempt_no,
            type=e.type,
            occurred_at=e.occurred_at,
            processor=e.processor,
            reason=e.reason,
            data=e.data,
            published_at=e.published_at,
        )
        for e in session.scalars(
            sa.select(PaymentEvent).where(PaymentEvent.payment_id.in_(ids)).order_by(PaymentEvent.id)
        )
    ]
    return payments, events


def load_fallback_reasons(session: Session, window: Window) -> dict[int, str | None]:
    """`fallback_reason` of each stored explanation of the selected payments, by explanation id (ADR-0013)."""
    ids = sa.select(Payment.id).where(_cohort(window))
    rows = session.execute(
        sa.select(PaymentExplanation.id, PaymentExplanation.fallback_reason).where(
            PaymentExplanation.payment_id.in_(ids)
        )
    )
    return {row.id: row.fallback_reason for row in rows}


def build_report(
    session: Session,
    window: Window,
    *,
    as_of: datetime,
    stuck_after: timedelta,
    request_log_path: str | None = None,
) -> dict[str, Any]:
    payments, events = load_rows(session, window)
    metrics = compute_metrics(
        payments, events, as_of=as_of, stuck_after=stuck_after, fallback_reasons=load_fallback_reasons(session, window)
    )
    lines = read_request_log(request_log_path) if request_log_path else None
    api = (
        summarize_request_log(lines, window.since, window.until)
        if lines is not None
        else {"available": False, "note": "request log not found"}
    )
    return {
        "window": {
            "since": iso(window.since),
            "until": iso(window.until),
            "reference_prefix": window.reference_prefix,
            "as_of": iso(as_of),
        },
        "payments": {"selected": len(payments), "final": sum(p.is_final for p in payments)},
        **metrics,
        "api_5xx": api,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def render_table(report: dict[str, Any]) -> str:
    window = report["window"]
    lines = [
        "Relay guardrail metrics",
        f"  window: since={_fmt(window['since'])} until={_fmt(window['until'])} "
        f"reference_prefix={_fmt(window['reference_prefix'])} as_of={window['as_of']}",
        f"  payments: {report['payments']['selected']} selected, {report['payments']['final']} final",
        "  percentiles: nearest rank; success rate = captured / final payments (declines count)",
        "",
    ]

    def percentile_row(label: str, data: dict[str, Any], extra: str = "") -> str:
        return (
            f"  {label:<14} P50 {_fmt(data['p50_ms'])} ms   P95 {_fmt(data['p95_ms'])} ms"
            + (f"   P99 {_fmt(data['p99_ms'])} ms" if "p99_ms" in data else "")
            + extra
        )

    latency = report["latency"]
    lines += ["Processing latency (final payments)", percentile_row(f"n={latency['count']}", latency), ""]
    lag = report["publish_lag"]
    lines += [
        "Publish lag",
        percentile_row(f"n={lag['published']}", lag, f"   unpublished {lag['unpublished']}"),
        "",
        "Processor success",
    ]
    for processor, row in report["processor_success"].items():
        lines.append(
            f"  {processor}: captured {row['captured']}  failed {row['failed']}  declined {row['declined']}  "
            f"success rate {_fmt(row['success_rate'])}"
        )
    not_final = report["not_final"]
    lines += ["", f"Not final past {_fmt(not_final['threshold_seconds'])} s (target 0): {not_final['count']}"]
    lines += [f"  {p['payment_id']} {p['status']} {_fmt(p['seconds_since_change'])} s" for p in not_final["payments"]]
    lines += ["", "Revenue recovered by rescue path (minor units)"]
    for path, row in report["rescue_paths"].items():
        money = ", ".join(f"{c} {a}" for c, a in row["amount_minor_by_currency"].items()) or "-"
        lines.append(f"  {path:<9} count {row['count']}  {money}")
    explanations = report["explanations"]
    lines += ["", "Explanations (time from final failure to stored explanation)"]
    if not explanations["available"]:
        lines.append(f"  {NOT_AVAILABLE}")
    else:
        for source, row in explanations["sources"].items():
            lines.append(percentile_row(f"{source} n={row['count']}", row))
        lines.append(percentile_row(f"all n={explanations['all']['count']}", explanations["all"]))
        lines.append(
            f"  fallback rate {_fmt(explanations['fallback_rate'])}  backlog max {explanations['backlog_max']}  "
            f"backlog at end {explanations['backlog_end']}"
        )
        reasons = ", ".join(f"{r} {n}" for r, n in explanations["fallback_reasons"].items()) or "none"
        lines.append(
            f"  fallbacks by reason: {reasons} (cause_mismatch {explanations['fallback_cause_mismatch']}, "
            f"model failures {explanations['fallback_model_failures']})"
        )
    api = report["api_5xx"]
    lines += ["", "API 5xx rate (request log)"]
    if not api["available"]:
        lines.append(f"  {api['note']}")
    else:
        lines.append(
            f"  {api['server_errors']} of {api['total']}  rate {_fmt(api['rate_5xx'])}  "
            f"malformed lines {api['malformed']}"
        )
    return "\n".join(lines) + "\n"
