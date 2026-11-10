"""REL-25.7/25.9: consumer group `explanations` on `payment.final`, and isolation from the payment worker."""

import threading
import time
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.explainer.consumer import GROUP, STREAM, ExplainerConsumer
from app.worker.consumer import Consumer
from tests.explain.fakes import FakeModel, answer
from tests.explainer.helpers import captured, declined, failed_final
from tests.worker.conftest import DECLINED, FakeProcessor, timeline, trigger

Factory = sessionmaker[Session]


def make(factory: Factory, redis_client: Redis, model: FakeModel, name: str = "e1") -> ExplainerConsumer:
    consumer = ExplainerConsumer(factory, redis_client, model, name, reclaim_idle_ms=30000)
    consumer.ensure_group()
    return consumer


def explanation_count(factory: Factory, pid: uuid.UUID) -> int:
    with factory() as session:
        return int(
            session.scalar(sa.text("SELECT count(*) FROM payment_explanations WHERE payment_id = :p"), {"p": pid}) or 0
        )


def test_group_is_explanations() -> None:
    assert GROUP == "explanations"
    assert STREAM == "relay:payment-events"


@pytest.mark.parametrize("build", [declined, failed_final])
def test_final_failure_entry_creates_one_explanation(factory: Factory, redis_client: Redis, build) -> None:  # type: ignore[no-untyped-def]
    pid = build(factory)
    consumer = make(factory, redis_client, FakeModel(unavailable="model_unreachable"))
    trigger(redis_client, pid, "payment.final")
    assert consumer.run_once() == 1
    assert explanation_count(factory, pid) == 1
    assert redis_client.xpending(STREAM, GROUP)["pending"] == 0


def test_redelivered_final_entry_changes_nothing(factory: Factory, redis_client: Redis) -> None:
    pid = declined(factory)
    consumer = make(factory, redis_client, FakeModel(unavailable="model_timeout"))
    trigger(redis_client, pid, "payment.final")
    trigger(redis_client, pid, "payment.final")
    assert consumer.run_once() == 2
    assert explanation_count(factory, pid) == 1
    events = [e.type for e in timeline(factory, pid)]
    assert events.count("payment.explained") == 1


def test_captured_payment_and_other_event_types_are_acknowledged_without_an_explanation(
    factory: Factory, redis_client: Redis
) -> None:
    pid = captured(factory)
    consumer = make(factory, redis_client, FakeModel(unavailable="model_timeout"))
    trigger(redis_client, pid, "payment.final")
    trigger(redis_client, pid, "payment.received")
    assert consumer.run_once() == 2
    assert explanation_count(factory, pid) == 0
    assert redis_client.xpending(STREAM, GROUP)["pending"] == 0


def test_runs_with_no_model_reachable(factory: Factory, redis_client: Redis) -> None:
    """CI has no Ollama: every explanation comes from the rules with model_unreachable."""
    pid = declined(factory)
    consumer = make(factory, redis_client, FakeModel(unavailable="model_unreachable"))
    trigger(redis_client, pid, "payment.final")
    consumer.run_once()
    with factory() as session:
        row = session.execute(sa.text("SELECT source, fallback_reason FROM payment_explanations")).one()
    assert tuple(row) == ("rules", "model_unreachable")


def test_a_model_that_hangs_does_not_delay_the_payment_worker(
    factory: Factory, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "static")
    final_pid = declined(factory)
    release = threading.Event()
    model = FakeModel(answer("late", [1]), block=release)
    explainer = make(factory, redis_client, model)
    trigger(redis_client, final_pid, "payment.final")
    thread = threading.Thread(target=explainer.run_once, daemon=True)
    thread.start()
    assert model.started.wait(timeout=10), "the explainer should be inside the (hanging) model call"

    from app.core.correlation import bind_correlation_id
    from app.services.transitions import create_payment

    fake = FakeProcessor(authorize=DECLINED)
    worker = Consumer(factory, redis_client, fake.client, "w1")
    worker.ensure_group()
    pids = []
    for i in range(5):
        with bind_correlation_id("corr-test"), factory.begin() as session:
            pid = create_payment(session, amount_minor=500, currency="EUR", reference=f"iso-{i}")
        pids.append(pid)
        # payment.received entries only: the worker group ignores the payment.final entry already in the stream
        trigger(redis_client, pid)
    started = time.monotonic()
    handled = 0
    while handled < 5 and time.monotonic() - started < 10:
        handled += worker.run_once()
    elapsed = time.monotonic() - started

    assert thread.is_alive(), "the model call is still hanging"
    assert handled >= 5  # the worker group also acknowledges the payment.final entry it does not act on
    assert elapsed < 5
    assert all("payment.final" in [e.type for e in timeline(factory, pid)] for pid in pids)

    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert explanation_count(factory, final_pid) == 1


def test_the_payment_worker_never_imports_the_model_client() -> None:
    worker_dir = Path(__file__).resolve().parents[2] / "app" / "worker"
    sources = [p.read_text(encoding="utf-8") for p in worker_dir.glob("*.py")]
    assert sources
    for source in sources:
        assert "app.explain" not in source
        assert "app.explainer" not in source
