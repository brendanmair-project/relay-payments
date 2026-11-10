"""Stream consumer for the `incidents` group (REL-34, ADR-0014).

Reads `payment.routed` entries from the same stream as the payment worker, in its own group and its own container, so
detection never runs on the payment path. Entries carry ids only: the event is re-read from PostgreSQL. The change and
its bookkeeping commit together and the entry is acknowledged afterwards, so a crash in between only means a redelivery
that the bookkeeping ignores. An unexpected error leaves the entry pending for reclaim.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.incidents.detector import apply_routed_event
from app.metrics import INCIDENTS_OPENED
from app.outbox.publisher import STREAM

GROUP = "incidents"
BATCH = 10
MAX_CONSECUTIVE_FAILURES = 30

logger = logging.getLogger("relay.incidents")


class IncidentConsumer:
    def __init__(self, factory: sessionmaker[Session], client: Any, name: str, reclaim_idle_ms: int = 30000) -> None:
        self.factory = factory
        self.client = client
        self.name = name
        self.reclaim_idle_ms = reclaim_idle_ms

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except Exception as error:
            if "BUSYGROUP" not in str(error):
                raise

    def _entries(self, block_ms: int) -> list[tuple[str, dict[str, str] | None]]:
        try:
            claimed = self.client.xautoclaim(
                STREAM, GROUP, self.name, min_idle_time=self.reclaim_idle_ms, start_id="0-0", count=BATCH
            )
            entries: list[tuple[str, dict[str, str] | None]] = list(claimed[1])
            fresh = self.client.xreadgroup(
                GROUP, self.name, {STREAM: ">"}, count=BATCH, block=block_ms if block_ms > 0 else None
            )
        except Exception as error:
            if "NOGROUP" not in str(error):  # the demo reset deletes the stream: create the group again
                raise
            logger.warning("stream or group missing; creating the group again")
            self.ensure_group()
            return []
        for _stream, messages in fresh or []:
            entries.extend(messages)
        return entries

    def _process(self, entry_id: str, fields: dict[str, str] | None) -> None:
        fields = fields or {}
        if fields.get("type") == "payment.routed":
            try:
                event_id = int(fields["event_id"])
            except (KeyError, ValueError):
                logger.warning("entry without a valid event_id ignored", extra={"entry_id": entry_id})
            else:
                for processor in apply_routed_event(self.factory, event_id):  # counted after the commit
                    INCIDENTS_OPENED.labels(processor, "rule").inc()
                    logger.info("incident opened", extra={"processor": processor, "event_id": event_id})
        self.client.xack(STREAM, GROUP, entry_id)

    def run_once(
        self, block_ms: int = 0, stop: threading.Event | None = None, heartbeat_path: Path | str | None = None
    ) -> int:
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
                logger.exception("incident pass failed", extra={"consecutive_failures": failures})
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    raise
                time.sleep(1)
