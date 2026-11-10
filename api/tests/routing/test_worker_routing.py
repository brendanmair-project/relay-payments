"""Routing through the worker end to end (REL-22): failover, the single retry, and what is never retried."""

import uuid

import pytest
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Payment
from app.worker.consumer import Consumer
from tests.routing.conftest import PerProcessorFake, Seed
from tests.worker.conftest import CAPTURE_FAILED, DECLINED, OUTAGE, pending, timeline, trigger, types

Factory = sessionmaker[Session]


def run(factory: Factory, redis_client: Redis, fake: PerProcessorFake) -> None:
    consumer = Consumer(factory, redis_client, fake.client, "c1", reclaim_idle_ms=30000)
    consumer.ensure_group()
    consumer.run_once()


def row(factory: Factory, pid: uuid.UUID) -> Payment:
    with factory() as session:
        return session.get_one(Payment, pid)


def routed_events(factory: Factory, pid: uuid.UUID) -> list[tuple[str | None, str | None, int]]:
    return [(e.processor, e.reason, e.attempt_no) for e in timeline(factory, pid) if e.type == "payment.routed"]


def test_healthy_payment_is_routed_to_a_with_reason_initial(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = PerProcessorFake()
    trigger(redis_client, payment_id)
    run(factory, redis_client, fake)
    assert routed_events(factory, payment_id) == [("A", "initial", 1)]
    assert row(factory, payment_id).status == "captured"
    assert "health" in timeline(factory, payment_id)[1].data


def test_degraded_a_sends_new_payment_to_b_as_failover(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID, seeder: Seed
) -> None:
    seeder("A", routed=10, failed=8)
    fake = PerProcessorFake()
    trigger(redis_client, payment_id)
    run(factory, redis_client, fake)
    assert routed_events(factory, payment_id) == [("B", "failover", 1)]
    assert fake.calls == [("B", "authorize"), ("B", "capture")]
    assert row(factory, payment_id).processor == "B"


def test_outage_on_a_is_retried_once_on_b_and_captured(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = PerProcessorFake({("A", "authorize"): OUTAGE})
    trigger(redis_client, payment_id)
    run(factory, redis_client, fake)
    first = row(factory, payment_id)
    assert (first.status, first.is_final, first.attempt_no) == ("failed", False, 1)
    assert types(factory, payment_id)[-2:] == ["payment.failed", "payment.retry_scheduled"]

    trigger(redis_client, payment_id, "payment.retry_scheduled", attempt_no=1)
    run(factory, redis_client, fake)
    final = row(factory, payment_id)
    assert (final.status, final.is_final, final.attempt_no, final.processor) == ("captured", True, 2, "B")
    assert routed_events(factory, payment_id) == [("A", "initial", 1), ("B", "retry", 2)]
    assert fake.calls == [("A", "authorize"), ("B", "authorize"), ("B", "capture")]
    assert pending(redis_client) == 0


def test_retry_also_runs_on_a_redriven_trigger(factory: Factory, redis_client: Redis, payment_id: uuid.UUID) -> None:
    fake = PerProcessorFake({("A", "authorize"): "timeout"})
    trigger(redis_client, payment_id)
    run(factory, redis_client, fake)
    trigger(redis_client, payment_id, "payment.redriven", attempt_no=1)
    run(factory, redis_client, fake)
    assert routed_events(factory, payment_id) == [("A", "initial", 1), ("B", "retry", 2)]
    assert row(factory, payment_id).status == "captured"


def test_retry_failing_too_is_final_and_never_retried_again(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = PerProcessorFake({("A", "authorize"): OUTAGE, ("B", "authorize"): OUTAGE})
    trigger(redis_client, payment_id)
    run(factory, redis_client, fake)
    trigger(redis_client, payment_id, "payment.retry_scheduled", attempt_no=1)
    run(factory, redis_client, fake)
    final = row(factory, payment_id)
    assert (final.status, final.is_final, final.attempt_no) == ("failed", True, 2)
    assert types(factory, payment_id)[-2:] == ["payment.failed", "payment.final"]
    for kind in ("payment.retry_scheduled", "payment.redriven", "payment.received"):
        trigger(redis_client, payment_id, kind, attempt_no=2)
    run(factory, redis_client, fake)
    assert len(routed_events(factory, payment_id)) == 2
    assert fake.calls == [("A", "authorize"), ("B", "authorize")]


def test_retry_ignores_health_and_goes_to_the_other_processor(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID, seeder: Seed
) -> None:
    seeder("B", routed=10, failed=10)
    fake = PerProcessorFake({("A", "authorize"): OUTAGE})
    trigger(redis_client, payment_id)
    run(factory, redis_client, fake)
    trigger(redis_client, payment_id, "payment.retry_scheduled", attempt_no=1)
    run(factory, redis_client, fake)
    assert routed_events(factory, payment_id)[1] == ("B", "retry", 2)


def test_decline_is_never_retried(factory: Factory, redis_client: Redis, payment_id: uuid.UUID) -> None:
    fake = PerProcessorFake({("A", "authorize"): DECLINED})
    trigger(redis_client, payment_id)
    run(factory, redis_client, fake)
    trigger(redis_client, payment_id, "payment.retry_scheduled", attempt_no=1)
    trigger(redis_client, payment_id, "payment.redriven", attempt_no=1)
    run(factory, redis_client, fake)
    current = row(factory, payment_id)
    assert (current.status, current.is_final) == ("declined", True)
    assert "payment.retry_scheduled" not in types(factory, payment_id)
    assert fake.calls == [("A", "authorize")]


def test_capture_failure_after_authorization_is_final_and_never_retried(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = PerProcessorFake({("A", "capture"): CAPTURE_FAILED})
    trigger(redis_client, payment_id)
    run(factory, redis_client, fake)
    trigger(redis_client, payment_id, "payment.retry_scheduled", attempt_no=1)
    trigger(redis_client, payment_id, "payment.redriven", attempt_no=1)
    run(factory, redis_client, fake)
    current = row(factory, payment_id)
    assert (current.status, current.is_final, current.attempt_no) == ("failed", True, 1)
    assert "payment.retry_scheduled" not in types(factory, payment_id)
    assert fake.calls == [("A", "authorize"), ("A", "capture")]


def test_static_strategy_sends_everything_to_a_without_failover_or_retry(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID, seeder: Seed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "static")
    seeder("A", routed=10, failed=10)
    fake = PerProcessorFake({("A", "authorize"): OUTAGE})
    trigger(redis_client, payment_id)
    run(factory, redis_client, fake)
    trigger(redis_client, payment_id, "payment.retry_scheduled", attempt_no=1)
    trigger(redis_client, payment_id, "payment.redriven", attempt_no=1)
    run(factory, redis_client, fake)
    current = row(factory, payment_id)
    assert (current.status, current.is_final, current.attempt_no) == ("failed", True, 1)
    assert routed_events(factory, payment_id) == [("A", "static", 1)]
    assert fake.calls == [("A", "authorize")]
