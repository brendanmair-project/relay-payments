"""REL-34.4/34.7 (ADR-0014): the `incidents` consumer opens one incident per avoided processor, records recovery, and
survives duplicate, late and redelivered entries and a crash between commit and acknowledgement."""

import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from prometheus_client import REGISTRY
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.incidents.consumer import GROUP, STREAM, IncidentConsumer
from tests.db.conftest import API_DIR
from tests.incidents.helpers import incidents, occurred_at, push, routed, routed_entry

Factory = sessionmaker[Session]

INSERT_MANUAL = sa.text(
    "INSERT INTO incidents (id, processor, source, status, title, opened_at)"
    " VALUES (:i, 'A', 'manual', 'detected', 'by hand', now())"
)


def make(factory: Factory, client: Redis, name: str = "i1", reclaim_idle_ms: int = 30000) -> IncidentConsumer:
    consumer = IncidentConsumer(factory, client, name, reclaim_idle_ms=reclaim_idle_ms)
    consumer.ensure_group()
    return consumer


def pending(client: Redis) -> int:
    return int(client.xpending(STREAM, GROUP)["pending"])


def resolve_all(factory: Factory) -> None:
    with factory.begin() as session:
        session.execute(sa.text("UPDATE incidents SET status = 'resolved', resolved_at = now()"))


def test_group_and_stream_names() -> None:
    assert GROUP == "incidents"
    assert STREAM == "relay:payment-events"


def test_an_avoided_processor_opens_exactly_one_incident(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    event_id = routed_entry(redis_client, factory, a="avoided")
    assert consumer.run_once() == 1
    rows = incidents(factory)
    assert len(rows) == 1
    row = rows[0]
    assert (row["processor"], row["source"], row["status"]) == ("A", "rule", "detected")
    assert row["opened_by_event_id"] == event_id
    assert row["opened_at"] == occurred_at(factory, event_id)
    assert row["recovered_at"] is None
    assert pending(redis_client) == 0


def test_a_second_avoided_event_opens_none(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    routed_entry(redis_client, factory, a="avoided")
    assert consumer.run_once() == 2
    assert len(incidents(factory)) == 1


def test_preferred_and_unknown_health_open_nothing(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="preferred", b="unknown")
    assert consumer.run_once() == 1
    assert incidents(factory) == []


def test_each_processor_gets_its_own_incident(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided", b="avoided")
    consumer.run_once()
    assert sorted(str(r["processor"]) for r in incidents(factory)) == ["A", "B"]


def test_a_manual_open_incident_blocks_a_rule_incident(factory: Factory, redis_client: Redis) -> None:
    with factory.begin() as session:
        session.execute(INSERT_MANUAL, {"i": uuid.uuid4()})
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    assert consumer.run_once() == 1
    assert [r["source"] for r in incidents(factory)] == ["manual"]


def test_other_event_types_and_odd_entries_are_acknowledged_and_ignored(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    redis_client.xadd(STREAM, {"event_id": "1", "type": "payment.received"})
    redis_client.xadd(STREAM, {"type": "payment.routed"})  # no event id
    redis_client.xadd(STREAM, {"event_id": "not-a-number", "type": "payment.routed"})
    redis_client.xadd(STREAM, {"event_id": "999999", "type": "payment.routed"})  # no such row
    assert consumer.run_once() == 4
    assert incidents(factory) == []
    assert pending(redis_client) == 0


def test_recovery_sets_recovered_at_once_and_keeps_the_incident_open(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    healthy = routed_entry(redis_client, factory, a="preferred")
    consumer.run_once()
    row = incidents(factory)[0]
    assert row["status"] == "detected"
    assert row["recovered_at"] == occurred_at(factory, healthy)
    routed_entry(redis_client, factory, a="preferred")
    consumer.run_once()
    assert incidents(factory)[0]["recovered_at"] == row["recovered_at"]
    assert incidents(factory)[0]["status"] == "detected"


def test_unknown_health_is_not_recovery(factory: Factory, redis_client: Redis) -> None:
    # While a processor is avoided it gets no traffic, so its failures age out and its state drops to `unknown` even
    # if it is still down. Only `preferred` (fresh successful attempts) shows that health returned.
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    routed_entry(redis_client, factory, a="unknown")
    consumer.run_once()
    assert incidents(factory)[0]["recovered_at"] is None
    routed_entry(redis_client, factory, a="preferred")
    consumer.run_once()
    assert incidents(factory)[0]["recovered_at"] is not None


def test_recovery_does_not_touch_an_incident_opened_by_hand(factory: Factory, redis_client: Redis) -> None:
    with factory.begin() as session:
        session.execute(INSERT_MANUAL, {"i": uuid.uuid4()})
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="preferred")
    consumer.run_once()
    assert incidents(factory)[0]["recovered_at"] is None


def test_a_new_incident_opens_after_the_old_one_is_resolved(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    resolve_all(factory)
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    assert sorted(str(r["status"]) for r in incidents(factory)) == ["detected", "resolved"]


def test_a_redelivered_avoided_entry_never_reopens_a_resolved_incident(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    event_id = routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    resolve_all(factory)
    push(redis_client, factory, event_id)  # the same event delivered again
    assert consumer.run_once() == 1
    assert [r["status"] for r in incidents(factory)] == ["resolved"]


def test_a_late_older_avoided_entry_changes_nothing(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    older = routed(factory, a="avoided")
    newer = routed(factory, a="preferred")
    assert older < newer
    push(redis_client, factory, newer)  # the newer event arrives first
    consumer.run_once()
    push(redis_client, factory, older)  # then the late one
    consumer.run_once()
    assert incidents(factory) == []


def test_a_late_older_entry_cannot_move_recovered_at(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    first = routed(factory, a="preferred")
    second = routed(factory, a="preferred")
    push(redis_client, factory, second)
    consumer.run_once()
    recovered = incidents(factory)[0]["recovered_at"]
    assert recovered == occurred_at(factory, second)
    push(redis_client, factory, first)  # older than the one applied
    consumer.run_once()
    assert incidents(factory)[0]["recovered_at"] == recovered


def test_a_crash_after_commit_and_before_ack_is_harmless_on_redelivery(factory: Factory, redis_client: Redis) -> None:
    crashing = make(factory, redis_client, "dies")
    routed_entry(redis_client, factory, a="avoided")

    def die(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("killed before the acknowledgement")

    real_xack = redis_client.xack
    redis_client.xack = die  # type: ignore[method-assign]
    assert crashing.run_once() == 0  # the entry failed: left pending
    redis_client.xack = real_xack  # type: ignore[method-assign]
    assert len(incidents(factory)) == 1  # the change was committed before the ack
    assert pending(redis_client) == 1

    survivor = make(factory, redis_client, "lives", reclaim_idle_ms=0)  # reclaims the stale entry
    assert survivor.run_once() == 1
    assert len(incidents(factory)) == 1
    assert pending(redis_client) == 0


def test_a_deleted_stream_is_recovered_by_creating_the_group_again(factory: Factory, redis_client: Redis) -> None:
    """The demo reset deletes the stream and its groups while the container keeps running."""
    consumer = make(factory, redis_client)
    redis_client.delete(STREAM)
    assert consumer.run_once() == 0  # NOGROUP: no crash, the group is created again
    routed_entry(redis_client, factory, a="avoided")
    assert consumer.run_once() == 1
    assert len(incidents(factory)) == 1


def test_a_failed_write_loses_nothing(factory: Factory, redis_client: Redis) -> None:
    """A crash before the commit leaves no incident and no bookkeeping, so the redelivery opens it."""
    consumer = make(factory, redis_client, "dies", reclaim_idle_ms=0)
    event_id = routed_entry(redis_client, factory, a="avoided")
    with factory.begin() as session:  # a broken bookkeeping table makes the transaction fail as a whole
        session.execute(sa.text("ALTER TABLE incident_detector_state RENAME TO incident_detector_state_gone"))
    try:
        assert consumer.run_once() == 0
        assert incidents(factory) == []
        assert pending(redis_client) == 1
    finally:
        with factory.begin() as session:
            session.execute(sa.text("ALTER TABLE incident_detector_state_gone RENAME TO incident_detector_state"))
    assert consumer.run_once() == 1
    assert [r["opened_by_event_id"] for r in incidents(factory)] == [event_id]


def race(consumer: IncidentConsumer, barrier: threading.Barrier, errors: list[BaseException]) -> None:
    try:
        barrier.wait()
        consumer.run_once()
    except BaseException as error:  # noqa: BLE001
        errors.append(error)


def test_concurrent_detectors_open_one_incident(factory: Factory, redis_client: Redis) -> None:
    for _ in range(3):
        with factory.begin() as session:
            session.execute(
                sa.text("TRUNCATE incidents, incident_detector_state, incident_payments, incident_summaries")
            )
        redis_client.delete(STREAM)
        first = make(factory, redis_client, "d1")
        second = make(factory, redis_client, "d2")
        for _n in range(6):
            routed_entry(redis_client, factory, a="avoided")
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []
        threads = [threading.Thread(target=race, args=(c, barrier, errors)) for c in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert not errors
        assert len(incidents(factory)) == 1
        redis_client.xgroup_destroy(STREAM, GROUP)


def test_the_unique_index_alone_rejects_a_second_open_incident(factory: Factory) -> None:
    insert = sa.text(
        "INSERT INTO incidents (id, processor, source, status, title, opened_at)"
        " VALUES (:i, 'A', 'rule', 'detected', 't', now())"
    )
    with factory.begin() as session:
        session.execute(insert, {"i": uuid.uuid4()})
    with pytest.raises(sa.exc.IntegrityError), factory.begin() as session:
        session.execute(insert, {"i": uuid.uuid4()})


def _counter(processor: str, source: str) -> float:
    return REGISTRY.get_sample_value("relay_incidents_opened_total", {"processor": processor, "source": source}) or 0.0


def test_opened_counter_is_zero_initialised_and_counts_only_new_incidents(
    factory: Factory, redis_client: Redis
) -> None:
    assert REGISTRY.get_sample_value("relay_incidents_opened_total", {"processor": "B", "source": "manual"}) is not None
    before = _counter("A", "rule")
    consumer = make(factory, redis_client)
    event_id = routed_entry(redis_client, factory, a="avoided")
    routed_entry(redis_client, factory, a="avoided")
    push(redis_client, factory, event_id)
    consumer.run_once()
    assert _counter("A", "rule") - before == 1


def test_the_detector_never_loads_the_payment_worker() -> None:
    code = "import sys, app.incidents.consumer; sys.exit(1 if 'app.worker' in sys.modules else 0)"
    result = subprocess.run(  # noqa: S603 - fixed arguments, the interpreter running the tests
        [sys.executable, "-c", code], cwd=Path(API_DIR), capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
