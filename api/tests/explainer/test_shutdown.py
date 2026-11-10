"""REL-48.3 and REL-48.6: explainer shutdown leaves entries pending, and the heartbeat survives a slow backlog."""

import os
import threading
from pathlib import Path

from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.explainer.consumer import GROUP, STREAM, ExplainerConsumer
from tests.explain.fakes import FakeModel
from tests.explainer.helpers import declined
from tests.worker.conftest import trigger

Factory = sessionmaker[Session]
STALE = 1_000_000_000  # an old mtime, so a fresh touch is easy to tell


class HeartbeatProbe(FakeModel):
    """A slow model: on every call it records how fresh the heartbeat was, then ages the file again."""

    def __init__(self, heartbeat: Path, stop: threading.Event | None = None) -> None:
        super().__init__(unavailable="model_timeout")
        self.heartbeat = heartbeat
        self.stop = stop
        self.stop_after = 1
        self.seen: list[float] = []

    def generate(self, prompt: str) -> str:
        self.seen.append(os.path.getmtime(self.heartbeat))
        os.utime(self.heartbeat, (STALE, STALE))
        if self.stop is not None and len(self.seen) >= self.stop_after:
            self.stop.set()
        return super().generate(prompt)


def _consumer(factory: Factory, client: Redis, model: FakeModel) -> ExplainerConsumer:
    consumer = ExplainerConsumer(factory, client, model, "e1", reclaim_idle_ms=30000)
    consumer.ensure_group()
    return consumer


def test_heartbeat_is_touched_after_every_entry_not_only_after_the_batch(
    factory: Factory, redis_client: Redis, tmp_path: Path
) -> None:
    heartbeat = tmp_path / "heartbeat"
    heartbeat.touch()
    os.utime(heartbeat, (STALE, STALE))
    stop = threading.Event()
    model = HeartbeatProbe(heartbeat)
    model.stop_after = 3
    model.stop = stop
    consumer = _consumer(factory, redis_client, model)
    for _ in range(3):
        trigger(redis_client, declined(factory), "payment.final")

    consumer.run(stop, heartbeat)  # one batch of three, then the stop set by the third model call ends the loop

    assert model.seen[0] == STALE  # nothing touched it before the first entry
    assert model.seen[1] > STALE and model.seen[2] > STALE  # entries 1 and 2 each refreshed it, mid-batch


def test_stop_during_an_entry_finishes_it_and_leaves_the_rest_pending(
    factory: Factory, redis_client: Redis, tmp_path: Path
) -> None:
    heartbeat = tmp_path / "heartbeat"
    heartbeat.touch()
    stop = threading.Event()
    model = HeartbeatProbe(heartbeat, stop)
    consumer = _consumer(factory, redis_client, model)
    for _ in range(3):
        trigger(redis_client, declined(factory), "payment.final")

    assert consumer.run_once(stop=stop) == 1

    assert len(model.seen) == 1  # no model call was started after the stop
    assert redis_client.xpending(STREAM, GROUP)["pending"] == 2
    idle_model = FakeModel(unavailable="model_timeout")
    successor = ExplainerConsumer(factory, redis_client, idle_model, "e2", reclaim_idle_ms=0)
    assert successor.run_once() == 2
    assert redis_client.xpending(STREAM, GROUP)["pending"] == 0
