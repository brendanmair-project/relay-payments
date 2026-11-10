"""Processor health from payment events in PostgreSQL (ADR-0008 decision 7), shared by the worker and the API.

An attempt is a `payment.routed` event in the window; an error is a `payment.failed` event in the window with reason
timeout, outage or capture_failed (sweeper timeouts included; declines are never errors). Each is counted by its own
event time. State: `unknown` below `min_attempts`, `avoided` when errors / attempts is strictly above the threshold
(a rate equal to the threshold stays `preferred`), else `preferred`.
"""

from dataclasses import dataclass
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import PaymentEvent
from app.domain.reasons import EventType, FailedReason
from app.routing.config import HealthSettings, health_settings

PROCESSORS = ("A", "B")
PREFERRED = "preferred"
AVOIDED = "avoided"
UNKNOWN = "unknown"
ERROR_REASONS = [r.value for r in FailedReason]


@dataclass(frozen=True)
class ProcessorHealth:
    name: str
    attempts: int
    errors: int
    error_rate: float
    state: str


def classify(attempts: int, errors: int, settings: HealthSettings) -> str:
    if attempts < settings.min_attempts:
        return UNKNOWN
    return AVOIDED if errors / attempts > settings.error_threshold else PREFERRED


def compute_health(session: Session, settings: HealthSettings | None = None) -> dict[str, ProcessorHealth]:
    """Health of A and B over the rolling window, measured against the database clock."""
    cfg = settings or health_settings()
    since = sa.func.now() - timedelta(seconds=cfg.window_seconds)
    attempts = sa.func.count().filter(PaymentEvent.type == EventType.PAYMENT_ROUTED.value)
    errors = sa.func.count().filter(
        PaymentEvent.type == EventType.PAYMENT_FAILED.value, PaymentEvent.reason.in_(ERROR_REASONS)
    )
    rows = session.execute(
        sa.select(PaymentEvent.processor, attempts, errors)
        .where(
            PaymentEvent.occurred_at >= since,
            PaymentEvent.type.in_([EventType.PAYMENT_ROUTED.value, EventType.PAYMENT_FAILED.value]),
            PaymentEvent.processor.in_(PROCESSORS),
        )
        .group_by(PaymentEvent.processor)
    ).all()
    counts = {row[0]: (int(row[1]), int(row[2])) for row in rows}
    result: dict[str, ProcessorHealth] = {}
    for name in PROCESSORS:
        n_attempts, n_errors = counts.get(name, (0, 0))
        rate = min(1.0, n_errors / n_attempts) if n_attempts else 0.0
        result[name] = ProcessorHealth(name, n_attempts, n_errors, round(rate, 4), classify(n_attempts, n_errors, cfg))
    return result
