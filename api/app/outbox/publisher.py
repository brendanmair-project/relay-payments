"""Publisher: copy unpublished events to the stream, then mark them (at-least-once, ADR-0003 and ADR-0008).

One database transaction holds the row locks from the read to the mark. A crash after `XADD` but before the commit
leaves the rows unpublished, so the next pass sends them again (a duplicate, never a loss). Consumers therefore treat
entries as triggers and read the current state from PostgreSQL. Recovery reads only PostgreSQL, never the stream.
"""

import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis.exceptions import ResponseError
from sqlalchemy.orm import Session, sessionmaker

from app.db.events import mark_published
from app.metrics import EVENTS_PUBLISHED, PUBLISH_LAG, STREAM_GROUP_LAG, STREAM_GROUP_PENDING
from app.outbox.reader import OutboxEvent, fetch_unpublished

STREAM = "relay:payment-events"
logger = logging.getLogger("relay.publisher")


def entry_fields(event: OutboxEvent) -> dict[str, str]:
    """Stream entries carry ids, not payment data (data-model.md)."""
    return {
        "event_id": str(event.id),
        "payment_id": str(event.payment_id),
        "seq": str(event.seq),
        "attempt_no": str(event.attempt_no),
        "type": event.type,
        "correlation_id": event.correlation_id,
    }


def publish_batch(factory: sessionmaker[Session], client: Any, *, batch_size: int = 100, maxlen: int = 10000) -> int:
    """Publish one batch in id order and return how many events were sent (0 when nothing is unpublished)."""
    with factory.begin() as session:
        events = fetch_unpublished(session, batch_size)
        for event in events:
            client.xadd(STREAM, entry_fields(event), maxlen=maxlen, approximate=True)
        mark_published(session, [event.id for event in events])
    now = datetime.now(UTC)
    for event in events:  # recorded after the commit, so a rolled-back batch is not counted
        PUBLISH_LAG.observe(max((now - event.occurred_at).total_seconds(), 0.0))
    EVENTS_PUBLISHED.inc(len(events))
    return len(events)


def update_group_gauges(client: Any) -> None:
    """Set the lag and pending gauges of every consumer group `XINFO GROUPS` lists (REL-57).

    The group list is read, never fixed in code. A missing stream has no groups. `lag` is null when the server cannot
    work it out (entries deleted by trimming); that group's lag gauge then keeps its last value.
    """
    try:
        groups = client.xinfo_groups(STREAM)
    except ResponseError as error:  # a stream that does not exist yet has no groups
        if "no such key" in str(error).lower():
            return
        raise
    for group in groups:
        name = group["name"]
        STREAM_GROUP_PENDING.labels(name).set(group["pending"])
        if group.get("lag") is not None:
            STREAM_GROUP_LAG.labels(name).set(group["lag"])


def write_heartbeat(path: Path | str) -> None:
    """Touch the file the compose health check watches."""
    Path(path).touch()


def run_loop(
    stop: threading.Event,
    factory: sessionmaker[Session],
    client: Any,
    *,
    heartbeat_path: Path | str,
    batch_size: int = 100,
    maxlen: int = 10000,
    poll_interval: float = 0.5,
    gauge_interval: float = 5.0,
) -> None:
    """Publish until `stop` is set. A pass that fails is logged and retried; the heartbeat then goes stale."""
    last_gauges: float | None = None
    while not stop.is_set():
        if last_gauges is None or time.monotonic() - last_gauges >= gauge_interval:
            last_gauges = time.monotonic()
            try:
                update_group_gauges(client)
            except Exception:
                logger.exception("stream group gauges not updated; retrying later")
        try:
            sent = publish_batch(factory, client, batch_size=batch_size, maxlen=maxlen)
            write_heartbeat(heartbeat_path)
        except Exception:
            logger.exception("publish pass failed; retrying")
            sent = 0
        if sent < batch_size:  # a full batch means more may be waiting: go again at once
            stop.wait(poll_interval)
