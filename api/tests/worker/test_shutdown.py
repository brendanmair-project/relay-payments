"""REL-48.3: on stop the worker finishes the entry in hand, starts none and leaves the rest pending for reclaim."""

import threading
import uuid

from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import bind_correlation_id
from app.services.transitions import create_payment
from app.worker.consumer import Consumer
from tests.worker.conftest import FakeProcessor, pending, trigger
from tests.worker.test_worker import make_consumer, payment

Factory = sessionmaker[Session]


def _payments(factory: Factory, count: int) -> list[uuid.UUID]:
    ids = []
    for index in range(count):
        with bind_correlation_id("corr-test"), factory.begin() as session:
            ids.append(create_payment(session, amount_minor=500, currency="EUR", reference=f"stop-{index}"))
    return ids


def test_stop_during_an_entry_finishes_it_and_leaves_the_rest_pending_for_reclaim(
    factory: Factory, redis_client: Redis
) -> None:
    first, second, third = _payments(factory, 3)
    stop = threading.Event()
    consumer = make_consumer(factory, redis_client, FakeProcessor(on_call=lambda _op: stop.set()))
    for pid in (first, second, third):
        trigger(redis_client, pid)

    assert consumer.run_once(stop=stop) == 1  # SIGTERM arrived inside the first entry's processor call

    assert payment(factory, first).status == "captured"  # the entry in hand ran to its end and was acknowledged
    assert payment(factory, second).status == "received"
    assert payment(factory, third).status == "received"
    assert pending(redis_client) == 2

    successor = Consumer(factory, redis_client, FakeProcessor().client, "c2", reclaim_idle_ms=0)
    assert successor.run_once() == 2  # a restarted worker reclaims what was left
    assert pending(redis_client) == 0
    assert payment(factory, second).status == "captured"
    assert payment(factory, third).status == "captured"


def test_run_returns_once_stop_is_set(factory: Factory, redis_client: Redis, tmp_path) -> None:  # type: ignore[no-untyped-def]
    consumer = make_consumer(factory, redis_client, FakeProcessor())
    stop = threading.Event()
    stop.set()
    consumer.run(stop, tmp_path / "heartbeat")  # returns immediately instead of blocking on the stream
