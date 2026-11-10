"""REL-57: the guardrail series Phase 2 lacked (docs/architecture/dashboard-spec-observability.md).

Creation-to-final latency, payments not final past the sweeper threshold, and the stream lag and pending gauges per
consumer group. Every series exists at zero before its first event (lesson L-070).
"""

import uuid
from datetime import timedelta

import pytest
import sqlalchemy as sa
from prometheus_client import REGISTRY
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.domain.lifecycle import Event, PaymentState
from app.outbox.publisher import STREAM, update_group_gauges
from app.services.transitions import apply_transition
from app.worker.consumer import Consumer
from app.worker.sweeper import SweepConfig, sweep
from tests.worker.conftest import DECLINED, FakeProcessor, trigger

Factory = sessionmaker[Session]
PROCESSING = "relay_payment_processing_seconds"
OVERDUE = "relay_payments_not_final_overdue"
CONFIG = SweepConfig(processor_timeout_seconds=5, timeout_grace_seconds=5, redrive_after_seconds=30)


def value(name: str, **labels: str) -> float | None:
    return REGISTRY.get_sample_value(name, labels)


def num(name: str, **labels: str) -> float:
    return value(name, **labels) or 0.0


def backdate(factory: Factory, pid: uuid.UUID, seconds: int) -> None:
    with factory.begin() as session:
        session.execute(
            sa.text("UPDATE payments SET created_at = created_at - make_interval(secs => :s) WHERE id = :id"),
            {"s": seconds, "id": pid},
        )


def run_worker(factory: Factory, redis_client: Redis, fake: FakeProcessor, pid: uuid.UUID) -> None:
    consumer = Consumer(factory, redis_client, fake.client, "c1", reclaim_idle_ms=30000)
    consumer.ensure_group()
    trigger(redis_client, pid)
    consumer.run_once()


def route_static(factory: Factory, pid: uuid.UUID, processor: str) -> None:
    with factory.begin() as session:
        apply_transition(
            session,
            pid,
            Event.ROUTE,
            expected_status=PaymentState.RECEIVED,
            expected_attempt=0,
            retries_enabled=False,
            processor=processor,
            reason="static",
        )


@pytest.fixture(autouse=True)
def static_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "static")


def test_a_payment_final_in_the_worker_is_timed_from_creation_by_processor_and_outcome(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    backdate(factory, payment_id, 30)
    count_before = num(f"{PROCESSING}_count", processor="A", outcome="captured")
    sum_before = num(f"{PROCESSING}_sum", processor="A", outcome="captured")
    declined_before = num(f"{PROCESSING}_count", processor="A", outcome="declined")
    run_worker(factory, redis_client, FakeProcessor(), payment_id)
    assert num(f"{PROCESSING}_count", processor="A", outcome="captured") - count_before == 1
    grown = num(f"{PROCESSING}_sum", processor="A", outcome="captured") - sum_before
    assert 29 <= grown <= 45, grown  # created 30 s ago, final now
    assert num(f"{PROCESSING}_count", processor="A", outcome="declined") == declined_before


def test_a_decline_is_timed_under_its_own_outcome(factory: Factory, redis_client: Redis, payment_id: uuid.UUID) -> None:
    before = num(f"{PROCESSING}_count", processor="A", outcome="declined")
    run_worker(factory, redis_client, FakeProcessor(authorize=DECLINED), payment_id)
    assert num(f"{PROCESSING}_count", processor="A", outcome="declined") - before == 1


def test_a_payment_the_sweeper_fails_for_good_is_timed_too(factory: Factory, payment_id: uuid.UUID) -> None:
    route_static(factory, payment_id, "B")
    backdate(factory, payment_id, 60)
    before = num(f"{PROCESSING}_count", processor="B", outcome="failed")
    sum_before = num(f"{PROCESSING}_sum", processor="B", outcome="failed")
    with factory() as session:
        now = session.execute(sa.select(sa.func.now())).scalar_one() + timedelta(seconds=60)
    sweep(factory, CONFIG, now=now)
    assert num(f"{PROCESSING}_count", processor="B", outcome="failed") - before == 1
    assert num(f"{PROCESSING}_sum", processor="B", outcome="failed") - sum_before >= 59


def test_the_overdue_gauge_counts_payments_not_final_past_the_sweeper_threshold_after_each_pass(
    factory: Factory, payment_id: uuid.UUID
) -> None:
    # A received payment waits for the re-drive (30 s) but is overdue after the timeout threshold (10 s).
    with factory() as session:
        db_now = session.execute(sa.select(sa.func.now())).scalar_one()
    sweep(factory, CONFIG, now=db_now)
    assert value(OVERDUE) == 0
    sweep(factory, CONFIG, now=db_now + timedelta(seconds=20))
    assert value(OVERDUE) == 1
    with factory.begin() as session:
        session.execute(
            sa.text(
                "UPDATE payments SET is_final = true, status = 'captured', attempt_no = 1, processor = 'A', "
                "final_at = now() WHERE id = :id"
            ),
            {"id": payment_id},
        )
    sweep(factory, CONFIG, now=db_now + timedelta(seconds=20))
    assert value(OVERDUE) == 0


def test_the_overdue_gauge_does_not_count_a_payment_the_pass_just_failed_for_good(
    factory: Factory, payment_id: uuid.UUID
) -> None:
    route_static(factory, payment_id, "A")
    with factory() as session:
        now = session.execute(sa.select(sa.func.now())).scalar_one() + timedelta(seconds=60)
    sweep(factory, CONFIG, now=now)
    assert value(OVERDUE) == 0  # timed out into a final failure: it is no longer waiting


def test_group_gauges_report_lag_and_pending_for_every_group_the_stream_has(redis_client: Redis) -> None:
    for group in ("processing", "explanations", "incidents", "newcomer"):
        redis_client.xgroup_create(STREAM, group, id="0", mkstream=True)
    for index in range(5):
        redis_client.xadd(STREAM, {"n": str(index)})
    redis_client.xreadgroup("processing", "c1", {STREAM: ">"}, count=2)  # two delivered, none acknowledged
    update_group_gauges(redis_client)
    assert value("relay_stream_group_pending", group="processing") == 2
    assert value("relay_stream_group_lag", group="processing") == 3
    assert value("relay_stream_group_lag", group="explanations") == 5
    assert value("relay_stream_group_pending", group="explanations") == 0
    assert value("relay_stream_group_lag", group="newcomer") == 5  # read from the stream, not a fixed list
    redis_client.xack(STREAM, "processing", *[e[0] for e in redis_client.xrange(STREAM)[:2]])
    update_group_gauges(redis_client)
    assert value("relay_stream_group_pending", group="processing") == 0


def test_group_gauges_survive_a_missing_stream(redis_client: Redis) -> None:
    update_group_gauges(redis_client)  # no stream, no groups: nothing to read, nothing raised


def test_every_new_series_exists_at_zero_before_its_first_event() -> None:
    for processor in ("A", "B"):
        for outcome in ("captured", "declined", "failed"):
            labels = {"processor": processor, "outcome": outcome}
            assert value(f"{PROCESSING}_count", **labels) is not None, labels
    assert value(OVERDUE) is not None
    for group in ("processing", "explanations", "incidents", "webhooks"):
        assert value("relay_stream_group_lag", group=group) is not None, group
        assert value("relay_stream_group_pending", group=group) is not None, group
