"""Timeout sweeper (REL-50, ADR-0008, ADR-0011 item 4, ADR-0012).

Each pass does two things, both driven only by PostgreSQL (never the stream):
- Timeouts: a payment in `routed` or `authorized` whose `status_changed_at` is older than
  PROCESSOR_TIMEOUT_SECONDS + SWEEP_TIMEOUT_GRACE_SECONDS is failed with reason `timeout` through `apply_transition`,
  which expects that status and attempt. A worker result that lands first, or another sweeper, makes the expectation
  fail harmlessly; a worker result that arrives later is recorded as `attempt.late_result` (`after_timeout`).
- Re-drive: a payment in `received`, or in `failed` and not final (retrying), whose `status_changed_at` and
  `last_driven_at` (if set) are both older than REDRIVE_AFTER_SECONDS gets `last_driven_at` set and a
  `payment.redriven` event in one transaction, with no state change; the publisher turns that event into a new trigger.

After each pass the gauge `relay_payments_not_final_overdue` is set to the number of payments still not final whose
last change is older than the timeout threshold (REL-57).

Candidates are selected with the `(status, status_changed_at)` index, batch-limited and without locks. Each one is then
handled in its own short transaction that takes the row with `FOR UPDATE SKIP LOCKED` and re-checks its conditions, so
two sweepers (or a sweeper and a worker) never act twice on the same payment: whoever loses the lock skips it and the
winner's committed change makes the re-check fail on the next look.
"""

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Payment
from app.domain.lifecycle import Event, PaymentState
from app.domain.reasons import EventType
from app.jobs.key_cleanup import cleanup_expired_keys
from app.metrics import PAYMENTS_FINAL, PAYMENTS_NOT_FINAL_OVERDUE
from app.routing.config import retries_enabled
from app.services.transitions import StateMismatchError, append_event, apply_transition
from app.worker.timing import observe_processing

logger = logging.getLogger("relay.sweeper")

KEY_CLEANUP_BATCH_SIZE = 500
KEY_CLEANUP_MAX_BATCHES = 20  # per run; a backlog continues at the next run so the sweep loop is never held up
TIMEOUT_REASON = "timeout"
_TIMEOUT_STATES = (PaymentState.ROUTED.value, PaymentState.AUTHORIZED.value)
_REDRIVE_STATES = (PaymentState.RECEIVED.value, PaymentState.FAILED.value)


@dataclass(frozen=True)
class SweepConfig:
    """Defaults per .env.example."""

    processor_timeout_seconds: float = 5
    timeout_grace_seconds: float = 5
    redrive_after_seconds: float = 30
    interval_seconds: float = 5
    key_cleanup_interval_seconds: float = 60

    @classmethod
    def from_env(cls) -> "SweepConfig":
        env = os.environ
        return cls(
            processor_timeout_seconds=float(env.get("PROCESSOR_TIMEOUT_SECONDS", "5")),
            timeout_grace_seconds=float(env.get("SWEEP_TIMEOUT_GRACE_SECONDS", "5")),
            redrive_after_seconds=float(env.get("REDRIVE_AFTER_SECONDS", "30")),
            interval_seconds=float(env.get("SWEEP_INTERVAL_SECONDS", "5")),
            key_cleanup_interval_seconds=float(env.get("KEY_CLEANUP_INTERVAL_SECONDS", "60")),
        )

    @property
    def timeout_after(self) -> timedelta:
        return timedelta(seconds=self.processor_timeout_seconds + self.timeout_grace_seconds)

    @property
    def redrive_after(self) -> timedelta:
        return timedelta(seconds=self.redrive_after_seconds)


@dataclass(frozen=True)
class SweepResult:
    timed_out: int = 0
    redriven: int = 0


def _redrive_due(cutoff: datetime) -> Any:
    return sa.and_(
        Payment.status.in_(_REDRIVE_STATES),
        Payment.is_final.is_(False),
        Payment.status_changed_at < cutoff,
        sa.or_(Payment.last_driven_at.is_(None), Payment.last_driven_at < cutoff),
    )


def _timeout_due(cutoff: datetime) -> Any:
    return sa.and_(Payment.status.in_(_TIMEOUT_STATES), Payment.status_changed_at < cutoff)


def _count_overdue(factory: sessionmaker[Session], cutoff: datetime) -> int:
    """Payments not final whose last state change is older than the timeout threshold (REL-57 guardrail)."""
    with factory() as session:
        return int(
            session.scalar(
                sa.select(sa.func.count())
                .select_from(Payment)
                .where(Payment.is_final.is_(False), Payment.status_changed_at < cutoff)
            )
            or 0
        )


def _candidates(factory: sessionmaker[Session], condition: Any, batch_size: int) -> list[uuid.UUID]:
    with factory() as session:
        return list(
            session.scalars(
                sa.select(Payment.id).where(condition).order_by(Payment.status_changed_at).limit(batch_size)
            )
        )


def _lock_if_due(session: Session, payment_id: uuid.UUID, condition: Any) -> Any:
    """Lock the payment if it is unlocked and still matches `condition`; None means skip it."""
    return session.execute(
        sa.select(Payment.status, Payment.attempt_no, Payment.processor, Payment.correlation_id)
        .where(Payment.id == payment_id, condition)
        .with_for_update(skip_locked=True)
    ).one_or_none()


def _time_out(factory: sessionmaker[Session], payment_id: uuid.UUID, cutoff: datetime) -> bool:
    try:
        with factory.begin() as session:
            row = _lock_if_due(session, payment_id, _timeout_due(cutoff))
            if row is None:
                return False
            new = apply_transition(
                session,
                payment_id,
                Event.FAIL,
                expected_status=PaymentState(row.status),
                expected_attempt=row.attempt_no,
                retries_enabled=retries_enabled(),
                reason=TIMEOUT_REASON,
                data={"source": "sweeper"},
                event_attempt=row.attempt_no,
                correlation_id=row.correlation_id,
            )
            if new.is_final:
                observe_processing(session, payment_id, row.processor, new.state.value)
    except StateMismatchError:
        return False  # a worker result or another sweeper moved it first
    if new.is_final:
        PAYMENTS_FINAL.labels(row.processor, new.state.value).inc()
    logger.info(
        "attempt timed out",
        extra={
            "payment_id": str(payment_id),
            "correlation_id": row.correlation_id,
            "from_status": row.status,
            "attempt_no": row.attempt_no,
            "outcome": new.state.value,
            "is_final": new.is_final,
        },
    )
    return True


def _redrive(factory: sessionmaker[Session], payment_id: uuid.UUID, cutoff: datetime, now: datetime) -> bool:
    with factory.begin() as session:
        row = _lock_if_due(session, payment_id, _redrive_due(cutoff))
        if row is None:
            return False
        session.execute(sa.update(Payment).where(Payment.id == payment_id).values(last_driven_at=now))
        append_event(session, payment_id, EventType.PAYMENT_REDRIVEN, correlation_id=row.correlation_id)
    logger.info(
        "payment re-driven",
        extra={
            "payment_id": str(payment_id),
            "correlation_id": row.correlation_id,
            "status": row.status,
            "attempt_no": row.attempt_no,
        },
    )
    return True


def sweep(
    factory: sessionmaker[Session], config: SweepConfig, *, now: datetime | None = None, batch_size: int = 100
) -> SweepResult:
    """One pass. `now` defaults to the database clock (the clock that stamps `status_changed_at`)."""
    if now is None:
        with factory() as session:
            now = session.execute(sa.select(sa.func.now())).scalar_one()
    redrive_cutoff = now - config.redrive_after
    timeout_cutoff = now - config.timeout_after
    # Re-drive first: a payment this pass fails below has a fresh `status_changed_at` and waits a full threshold.
    redriven = sum(
        _redrive(factory, pid, redrive_cutoff, now)
        for pid in _candidates(factory, _redrive_due(redrive_cutoff), batch_size)
    )
    timed_out = sum(
        _time_out(factory, pid, timeout_cutoff)
        for pid in _candidates(factory, _timeout_due(timeout_cutoff), batch_size)
    )
    # Set after the pass, so a payment the pass just failed (fresh status_changed_at) is not counted.
    PAYMENTS_NOT_FINAL_OVERDUE.set(_count_overdue(factory, timeout_cutoff))
    return SweepResult(timed_out=timed_out, redriven=redriven)


def run_loop(factory: sessionmaker[Session], config: SweepConfig, stop: threading.Event) -> None:
    """Sweep every `interval_seconds` until `stop` is set. A failed pass is logged and tried again next interval."""
    last_cleanup: float | None = None
    while not stop.is_set():
        try:
            result = sweep(factory, config)
            if result.timed_out or result.redriven:
                logger.info("sweep done", extra={"timed_out": result.timed_out, "redriven": result.redriven})
        except Exception:
            logger.exception("sweep failed; retrying next interval")
        if last_cleanup is None or time.monotonic() - last_cleanup >= config.key_cleanup_interval_seconds:
            last_cleanup = time.monotonic()
            try:
                _clean_keys(factory)
            except Exception:
                logger.exception("idempotency key cleanup failed; retrying later")
        stop.wait(config.interval_seconds)


def _clean_keys(factory: sessionmaker[Session]) -> None:
    """Delete expired idempotency keys batch by batch (REL-47) and log the total."""
    with factory() as session:
        now = session.execute(sa.select(sa.func.now())).scalar_one()
    removed = 0
    for _ in range(KEY_CLEANUP_MAX_BATCHES):
        count = cleanup_expired_keys(factory, now=now, batch_size=KEY_CLEANUP_BATCH_SIZE)
        removed += count
        if count < KEY_CLEANUP_BATCH_SIZE:
            break
    if removed:
        logger.info("expired idempotency keys removed", extra={"removed": removed})
