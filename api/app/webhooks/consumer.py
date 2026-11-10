"""Stream consumer of the `webhooks` group and the container's main loop (ADR-0015).

Reads the same stream as the payment worker, in its own group and its own container, so deliveries are never on the
payment path. Entries carry ids only: the event is re-read from PostgreSQL. For a lifecycle event the stored
deliveries and the bookkeeping commit together, and the entry is acknowledged afterwards, so a crash in between only
means a redelivery that the unique key on `(subscription_id, event_id)` turns into a no-op. An unexpected error leaves
the entry pending for reclaim. Other event types are acknowledged without work.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.metrics import WEBHOOK_PENDING
from app.outbox.publisher import STREAM
from app.webhooks.config import WebhookSettings
from app.webhooks.sender import Sender
from app.webhooks.store import cleanup, count_pending, fan_out
from app.webhooks.types import WEBHOOK_EVENT_TYPES

GROUP = "webhooks"
BATCH = 10
MAX_CONSECUTIVE_FAILURES = 30
CLEANUP_INTERVAL_SECONDS = 60.0

logger = logging.getLogger("relay.webhooks")


class WebhookConsumer:
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
        if fields.get("type") in WEBHOOK_EVENT_TYPES:
            try:
                event_id = int(fields["event_id"])
            except (KeyError, ValueError):
                logger.warning("entry without a valid event_id ignored", extra={"entry_id": entry_id})
            else:
                created = fan_out(self.factory, event_id)  # commits before the ack below
                if created:
                    logger.info("deliveries stored", extra={"event_id": event_id, "count": created})
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

    def run(self, stop: threading.Event, heartbeat_path: Path | str, sender: Sender, settings: WebhookSettings) -> None:
        """Consume, send and clean up until `stop` is set; raises after repeated failures so the container restarts."""
        failures = 0
        last_cleanup: float | None = None
        while not stop.is_set():
            try:
                self.run_once(block_ms=500, stop=stop, heartbeat_path=heartbeat_path)
                sender.send_due()
                WEBHOOK_PENDING.set(count_pending(self.factory))
                if last_cleanup is None or time.monotonic() - last_cleanup >= CLEANUP_INTERVAL_SECONDS:
                    last_cleanup = time.monotonic()
                    removed = cleanup(self.factory, settings.webhook_log_retention_days)
                    if removed:
                        logger.info("old deliveries removed", extra={"count": removed})
                Path(heartbeat_path).touch()
                failures = 0
            except Exception:
                failures += 1
                logger.exception("webhook pass failed", extra={"consecutive_failures": failures})
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    raise
                time.sleep(1)
