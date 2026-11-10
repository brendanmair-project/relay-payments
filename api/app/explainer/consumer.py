"""Stream consumer for the `explanations` group (REL-25.9, ADR-0012).

Reads `payment.final` entries from the same stream as the payment worker, in its own group and its own container,
so a slow or hanging model can never delay payment processing. Entries are triggers: the payment is re-read from
PostgreSQL, a captured payment gets no automatic explanation, and a redelivered entry changes nothing because the
store inserts at most one `final_failure` row. An entry is acknowledged once handled; an unexpected error leaves it
pending for reclaim.
"""

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import bind_correlation_id
from app.db.models import Payment
from app.explain.model import ModelClient
from app.explain.store import PaymentNotFinalError, explain_payment
from app.outbox.publisher import STREAM
from app.services.transitions import PaymentNotFoundError

GROUP = "explanations"
BATCH = 10
MAX_CONSECUTIVE_FAILURES = 30
FINAL_FAILURE_STATUSES = ("declined", "failed")

logger = logging.getLogger("relay.explainer")


class ExplainerConsumer:
    def __init__(
        self,
        factory: sessionmaker[Session],
        client: Any,
        model: ModelClient | None,
        name: str,
        reclaim_idle_ms: int = 30000,
    ) -> None:
        self.factory = factory
        self.client = client
        self.model = model
        self.name = name
        self.reclaim_idle_ms = reclaim_idle_ms

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except Exception as error:
            if "BUSYGROUP" not in str(error):
                raise

    def _entries(self, block_ms: int) -> list[tuple[str, dict[str, str] | None]]:
        claimed = self.client.xautoclaim(
            STREAM, GROUP, self.name, min_idle_time=self.reclaim_idle_ms, start_id="0-0", count=BATCH
        )
        entries: list[tuple[str, dict[str, str] | None]] = list(claimed[1])
        fresh = self.client.xreadgroup(
            GROUP, self.name, {STREAM: ">"}, count=BATCH, block=block_ms if block_ms > 0 else None
        )
        for _stream, messages in fresh or []:
            entries.extend(messages)
        return entries

    def _is_final_failure(self, payment_id: uuid.UUID) -> bool:
        with self.factory() as session:
            status = session.scalar(sa.select(Payment.status).where(Payment.id == payment_id, Payment.is_final))
        return status in FINAL_FAILURE_STATUSES

    def _process(self, entry_id: str, fields: dict[str, str] | None) -> None:
        fields = fields or {}
        if fields.get("type") == "payment.final":
            try:
                payment_id = uuid.UUID(fields["payment_id"])
            except (KeyError, ValueError):
                logger.warning("entry without a valid payment_id ignored", extra={"entry_id": entry_id})
            else:
                with bind_correlation_id(fields.get("correlation_id") or str(uuid.uuid4())):
                    try:
                        if self._is_final_failure(payment_id):
                            explain_payment(self.factory, payment_id, "final_failure", self.model)
                    except (PaymentNotFoundError, PaymentNotFinalError):
                        logger.warning("payment not explainable; entry dropped", extra={"entry_id": entry_id})
        self.client.xack(STREAM, GROUP, entry_id)

    def run_once(
        self, block_ms: int = 0, stop: threading.Event | None = None, heartbeat_path: Path | str | None = None
    ) -> int:
        """Handle one batch. The heartbeat is touched after every entry, not only after the batch: a backlog of slow
        model calls (up to BATCH x the model timeout) would otherwise outlast the health check's window."""
        handled = 0
        for entry_id, fields in self._entries(block_ms):
            if stop is not None and stop.is_set():
                break
            try:
                self._process(entry_id, fields)
            except Exception:
                logger.exception("entry failed; left pending for reclaim", extra={"entry_id": entry_id})
            else:
                handled += 1
            if heartbeat_path is not None:
                Path(heartbeat_path).touch()
        return handled

    def run(self, stop: threading.Event, heartbeat_path: Path | str) -> None:
        """Consume until `stop` is set; raises after repeated infrastructure failures so the container restarts."""
        failures = 0
        while not stop.is_set():
            try:
                self.run_once(block_ms=1000, stop=stop, heartbeat_path=heartbeat_path)
                Path(heartbeat_path).touch()
                failures = 0
            except Exception:
                failures += 1
                logger.exception("explainer pass failed", extra={"consecutive_failures": failures})
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    raise
                time.sleep(1)
