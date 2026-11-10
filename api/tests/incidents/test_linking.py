"""REL-35.2: the detector links an incident to the payments that failed on its processor, in the same transaction as
its bookkeeping: at open from the lookback window, while open until recovery or resolution, once per payment."""

import uuid

import pytest
import sqlalchemy as sa
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.incidents.consumer import IncidentConsumer
from tests.incidents.helpers import (
    incidents,
    links,
    push,
    routed,
    routed_entry,
    seed_failure,
    the_incident,
)

Factory = sessionmaker[Session]


def make(factory: Factory, client: Redis) -> IncidentConsumer:
    consumer = IncidentConsumer(factory, client, "i1")
    consumer.ensure_group()
    return consumer


def test_at_open_it_links_the_failures_in_the_lookback_window(factory: Factory, redis_client: Redis) -> None:
    inside, _ = seed_failure(factory, "A", "timeout", age_seconds=30)
    outage, _ = seed_failure(factory, "A", "outage", age_seconds=10, kind="attempt.authorize_result")
    capture, _ = seed_failure(factory, "A", "timeout", age_seconds=5, kind="attempt.capture_result")
    too_old, _ = seed_failure(factory, "A", "timeout", age_seconds=600)
    other_processor, _ = seed_failure(factory, "B", "timeout", age_seconds=10)
    declined, _ = seed_failure(factory, "A", "do_not_honor", age_seconds=10, kind="attempt.authorize_result")
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    linked = links(factory)
    assert linked == {inside, outage, capture}
    assert not linked & {too_old, other_processor, declined}


def test_a_link_records_the_first_failure_event_and_the_time(factory: Factory, redis_client: Redis) -> None:
    pid, event_id = seed_failure(factory, "A", "timeout", age_seconds=20)
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    with factory() as session:
        row = session.execute(sa.text("SELECT payment_id, first_event_id, linked_at FROM incident_payments")).one()
    assert (row[0], row[1]) == (pid, event_id)
    assert row[2] is not None


def test_while_open_it_links_new_failures_on_that_processor(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    assert links(factory) == set()
    later, _ = seed_failure(factory, "A", "outage")
    other, _ = seed_failure(factory, "B", "outage")
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    assert links(factory) == {later}
    assert other not in links(factory)


def test_a_failure_before_recovery_is_linked_and_one_after_is_not(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    before, _ = seed_failure(factory, "A", "timeout")
    routed_entry(redis_client, factory, a="preferred")  # recovery
    consumer.run_once()
    assert incidents(factory)[0]["recovered_at"] is not None
    after, _ = seed_failure(factory, "A", "timeout")
    routed_entry(redis_client, factory, a="avoided")
    routed_entry(redis_client, factory, a="preferred")
    consumer.run_once()
    assert links(factory) == {before}
    assert after not in links(factory)


def test_nothing_is_linked_after_the_incident_is_resolved(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    incident = the_incident(factory)
    with factory.begin() as session:
        session.execute(sa.text("UPDATE incidents SET status = 'resolved', resolved_at = now()"))
    after, _ = seed_failure(factory, "A", "timeout")
    routed_entry(redis_client, factory, a="preferred")
    consumer.run_once()
    assert after not in links(factory, incident)
    assert links(factory, incident) == set()


def test_a_redelivered_entry_links_nothing_twice(factory: Factory, redis_client: Redis) -> None:
    pid, _ = seed_failure(factory, "A", "timeout", age_seconds=10)
    consumer = make(factory, redis_client)
    event_id = routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    push(redis_client, factory, event_id)
    consumer.run_once()
    with factory() as session:
        count = session.execute(sa.text("SELECT count(*) FROM incident_payments")).scalar_one()
    assert count == 1
    assert links(factory) == {pid}


def test_a_late_older_entry_links_nothing(factory: Factory, redis_client: Redis) -> None:
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    older = routed(factory, a="avoided")
    newer = routed(factory, a="avoided")
    push(redis_client, factory, newer)
    consumer.run_once()
    backdated, _ = seed_failure(factory, "A", "timeout", age_seconds=0.001)  # failed before the older event
    push(redis_client, factory, older)  # the late one arrives after the newer
    consumer.run_once()
    assert backdated not in links(factory)


def test_a_payment_failing_twice_is_linked_once(factory: Factory, redis_client: Redis) -> None:
    pid, _ = seed_failure(factory, "A", "outage", age_seconds=20, kind="attempt.authorize_result")
    with factory.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO payment_events (payment_id, seq, attempt_no, type, processor, reason, correlation_id)"
                " VALUES (:p, 4, 1, 'payment.failed', 'A', 'outage', 'seed')"
            ),
            {"p": pid},
        )
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    assert links(factory) == {pid}


def test_a_manual_incident_without_a_processor_links_nothing(factory: Factory, redis_client: Redis) -> None:
    seed_failure(factory, "A", "timeout", age_seconds=10)
    with factory.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO incidents (id, processor, source, status, title, opened_at)"
                " VALUES (:i, NULL, 'manual', 'detected', 'by hand', now())"
            ),
            {"i": uuid.uuid4()},
        )
    consumer = make(factory, redis_client)
    routed_entry(redis_client, factory, a="avoided")
    consumer.run_once()
    manual = [r for r in incidents(factory) if r["source"] == "manual"]
    assert len(manual) == 1
    assert links(factory, uuid.UUID(str(manual[0]["id"]))) == set()


def test_the_link_primary_key_alone_rejects_a_duplicate(factory: Factory) -> None:
    pid, event_id = seed_failure(factory, "A", "timeout")
    incident = uuid.uuid4()
    with factory.begin() as session:
        session.execute(
            sa.text(
                "INSERT INTO incidents (id, processor, source, status, title, opened_at)"
                " VALUES (:i, 'A', 'rule', 'detected', 't', now())"
            ),
            {"i": incident},
        )
    insert = sa.text("INSERT INTO incident_payments (incident_id, payment_id, first_event_id) VALUES (:i, :p, :e)")
    with factory.begin() as session:
        session.execute(insert, {"i": incident, "p": pid, "e": event_id})
    with pytest.raises(sa.exc.IntegrityError), factory.begin() as session:
        session.execute(insert, {"i": incident, "p": pid, "e": event_id})


def test_a_failed_link_write_loses_nothing(factory: Factory, redis_client: Redis) -> None:
    """Linking shares the detector's transaction: when it fails no incident and no bookkeeping remain."""
    consumer = IncidentConsumer(factory, redis_client, "dies", reclaim_idle_ms=0)
    consumer.ensure_group()
    pid, _ = seed_failure(factory, "A", "timeout", age_seconds=10)
    routed_entry(redis_client, factory, a="avoided")
    with factory.begin() as session:
        session.execute(sa.text("ALTER TABLE incident_payments RENAME TO incident_payments_gone"))
    try:
        assert consumer.run_once() == 0
        assert incidents(factory) == []
    finally:
        with factory.begin() as session:
            session.execute(sa.text("ALTER TABLE incident_payments_gone RENAME TO incident_payments"))
    assert consumer.run_once() == 1
    assert links(factory) == {pid}
