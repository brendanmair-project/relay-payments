"""Stream consumer for the `processing` group (ADR-0003, ADR-0008).

Entries are triggers, not data: the handler re-reads the payment under a row lock, so a duplicate or late entry
changes nothing. An entry is acknowledged (XACK) only after `handle_trigger` returned, that is after its database
transactions committed, or when the entry needs no work. Anything that raises leaves the entry pending; it is
reclaimed with XAUTOCLAIM once it has been idle for `reclaim_idle_ms`, by this or another consumer.
"""

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import bind_correlation_id
from app.worker.handlers import TRIGGER_TYPES, handle_trigger
from app.worker.processor import ProcessorClient

STREAM = "relay:payment-events"
GROUP = "processing"
BATCH = 10
MAX_CONSECUTIVE_FAILURES = 30

logger = logging.getLogger("relay.worker")


class Consumer:
    def __init__(
        self,
        factory: sessionmaker[Session],
        client: Any,
        processors: ProcessorClient,
        name: str,
        reclaim_idle_ms: int = 30000,
    ) -> None:
        self.factory = factory
        self.client = client
        self.processors = processors
        self.name = name
        self.reclaim_idle_ms = reclaim_idle_ms

    def ensure_group(self) -> None:
        """Create the group (and the stream) if missing. It starts at `0`, so entries published before the first
        worker started are still processed; duplicates are harmless because of the state guard."""
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

    def _process(self, entry_id: str, fields: dict[str, str] | None) -> None:
        """Handle one entry; acknowledge it only when it is done or needs nothing."""
        fields = fields or {}
        if fields.get("type") in TRIGGER_TYPES:
            try:
                payment_id = uuid.UUID(fields["payment_id"])
            except (KeyError, ValueError):
                logger.warning("entry without a valid payment_id ignored", extra={"entry_id": entry_id})
            else:
                with bind_correlation_id(fields.get("correlation_id") or str(uuid.uuid4())):
                    handle_trigger(self.factory, self.processors, payment_id)
        self.client.xack(STREAM, GROUP, entry_id)

    def run_once(self, block_ms: int = 0, stop: threading.Event | None = None) -> int:
        """Reclaim idle entries, read new ones and handle them; return how many were handled (acknowledged).

        Once `stop` is set no further entry is started; the rest stay pending for reclaim.
        """
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
        return handled

    def run(self, stop: threading.Event, heartbeat_path: Path | str) -> None:
        """Consume until `stop` is set. Raises after repeated infrastructure failures so the container restarts."""
        failures = 0
        while not stop.is_set():
            try:
                self.run_once(block_ms=1000, stop=stop)
                Path(heartbeat_path).touch()
                failures = 0
            except Exception:
                failures += 1
                logger.exception("consumer pass failed", extra={"consecutive_failures": failures})
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    raise
                time.sleep(1)
