"""ADR-0015, item 1: one stored delivery per matching subscription, written with the bookkeeping, ack after commit."""

import json
from typing import Any

import pytest
import sqlalchemy as sa
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.outbox.publisher import STREAM
from app.webhooks.consumer import GROUP, WebhookConsumer
from app.webhooks.store import claim_due
from tests.incidents.helpers import push
from tests.webhooks.helpers import SENTINEL, deliveries, make_event, subscribe

Factory = sessionmaker[Session]
LIFECYCLE = [
    "payment.received",
    "payment.authorized",
    "payment.captured",
    "payment.declined",
    "payment.failed",
    "payment.final",
]


def consumer(factory: Factory, client: Redis, name: str = "c1", reclaim_idle_ms: int = 0) -> WebhookConsumer:
    c = WebhookConsumer(factory, client, name, reclaim_idle_ms=reclaim_idle_ms)
    c.ensure_group()
    return c


def pending(client: Redis) -> int:
    return int(client.xpending(STREAM, GROUP)["pending"])


def state(factory: Factory) -> list[int]:
    with factory() as session:
        return [int(r[0]) for r in session.execute(sa.text("SELECT last_event_id FROM webhook_consumer_state"))]


def test_the_consumer_group_is_named_webhooks() -> None:
    assert GROUP == "webhooks"


def test_a_matching_event_becomes_one_pending_delivery_per_matching_subscription(
    factory: Factory, redis_client: Redis
) -> None:
    both_a, _ = subscribe(factory, ["payment.final"])
    both_b, _ = subscribe(factory, ["payment.final", "payment.captured"])
    subscribe(factory, ["payment.captured"])  # another type: no delivery
    _pid, event_id = make_event(factory, "payment.final")
    c = consumer(factory, redis_client)
    push(redis_client, factory, event_id)
    assert c.run_once() == 1
    rows = deliveries(factory)
    assert sorted(str(r["subscription_id"]) for r in rows) == sorted([str(both_a), str(both_b)])
    for row in rows:
        assert (row["event_id"], row["event_type"], row["status"], row["attempt"]) == (
            event_id,
            "payment.final",
            "pending",
            0,
        )
        assert row["last_status_code"] is None and row["last_error"] is None
    assert pending(redis_client) == 0  # acknowledged after the commit


@pytest.mark.parametrize("type_", LIFECYCLE)
def test_every_lifecycle_type_is_delivered(factory: Factory, redis_client: Redis, type_: str) -> None:
    subscribe(factory, [type_])
    _pid, event_id = make_event(factory, type_)
    c = consumer(factory, redis_client)
    push(redis_client, factory, event_id)
    c.run_once()
    assert [r["event_type"] for r in deliveries(factory)] == [type_]


@pytest.mark.parametrize(
    "type_",
    [
        "payment.routed",
        "attempt.authorize_result",
        "attempt.capture_result",
        "payment.retry_scheduled",
        "attempt.late_result",
        "payment.redriven",
        "payment.explained",
    ],
)
def test_internal_event_types_are_acknowledged_and_never_delivered(
    factory: Factory, redis_client: Redis, type_: str
) -> None:
    subscribe(factory, LIFECYCLE)
    _pid, event_id = make_event(factory, type_)
    c = consumer(factory, redis_client)
    push(redis_client, factory, event_id)
    assert c.run_once() == 1
    assert deliveries(factory) == []
    assert pending(redis_client) == 0


def test_an_inactive_subscription_gets_nothing(factory: Factory, redis_client: Redis) -> None:
    sub, _ = subscribe(factory, ["payment.final"])
    with factory.begin() as session:
        session.execute(sa.text("UPDATE webhook_subscriptions SET active = false WHERE id = :i"), {"i": sub})
    _pid, event_id = make_event(factory, "payment.final")
    c = consumer(factory, redis_client)
    push(redis_client, factory, event_id)
    c.run_once()
    assert deliveries(factory) == []


def test_a_duplicate_stream_entry_produces_one_delivery(factory: Factory, redis_client: Redis) -> None:
    subscribe(factory, ["payment.final"])
    _pid, event_id = make_event(factory, "payment.final")
    c = consumer(factory, redis_client)
    push(redis_client, factory, event_id)
    push(redis_client, factory, event_id)  # at-least-once: the publisher can send an event twice
    assert c.run_once() == 2
    assert len(deliveries(factory)) == 1
    assert pending(redis_client) == 0


def test_the_bookkeeping_records_the_highest_event_id_applied_in_the_same_transaction(
    factory: Factory, redis_client: Redis
) -> None:
    subscribe(factory, ["payment.final"])
    _p1, first = make_event(factory, "payment.final")
    _p2, second = make_event(factory, "payment.final")
    c = consumer(factory, redis_client)
    push(redis_client, factory, second)
    push(redis_client, factory, first)  # out of order must not lose the delivery nor lower the record
    c.run_once()
    assert len(deliveries(factory)) == 2
    assert state(factory) == [second]


def test_a_crash_after_the_commit_but_before_the_ack_is_harmless_on_redelivery(
    factory: Factory, redis_client: Redis
) -> None:
    subscribe(factory, ["payment.final"])
    _pid, event_id = make_event(factory, "payment.final")
    push(redis_client, factory, event_id)

    class Crash(Exception):
        pass

    first = consumer(factory, redis_client, "dies")
    real_ack = redis_client.xack

    def die(*args: Any, **kwargs: Any) -> int:
        raise Crash

    redis_client.xack = die  # type: ignore[method-assign]
    try:
        assert first.run_once() == 0  # the entry failed to acknowledge, and is left pending
    finally:
        redis_client.xack = real_ack  # type: ignore[method-assign]
    assert len(deliveries(factory)) == 1  # the commit happened
    assert pending(redis_client) == 1
    second = consumer(factory, redis_client, "survivor")
    assert second.run_once() == 1  # reclaimed
    assert pending(redis_client) == 0
    assert len(deliveries(factory)) == 1  # still one


def test_a_crash_before_the_commit_loses_nothing(factory: Factory, redis_client: Redis) -> None:
    subscribe(factory, ["payment.final"])
    _pid, event_id = make_event(factory, "payment.final")
    push(redis_client, factory, event_id)
    broken = consumer(factory, redis_client, "dies")
    real = factory.begin

    def fail() -> Any:
        raise RuntimeError("database gone")

    factory.begin = fail  # type: ignore[method-assign]
    try:
        assert broken.run_once() == 0
    finally:
        factory.begin = real  # type: ignore[method-assign]
    assert deliveries(factory) == [] and pending(redis_client) == 1
    assert consumer(factory, redis_client, "survivor").run_once() == 1
    assert len(deliveries(factory)) == 1 and pending(redis_client) == 0


def test_an_entry_without_a_valid_event_id_is_acknowledged_and_ignored(factory: Factory, redis_client: Redis) -> None:
    subscribe(factory, ["payment.final"])
    c = consumer(factory, redis_client)
    redis_client.xadd(STREAM, {"type": "payment.final", "event_id": "nope"})
    redis_client.xadd(STREAM, {"type": "payment.final"})
    assert c.run_once() == 2
    assert deliveries(factory) == [] and pending(redis_client) == 0


def test_a_deleted_stream_or_group_is_recreated(factory: Factory, redis_client: Redis) -> None:
    subscribe(factory, ["payment.final"])
    c = consumer(factory, redis_client)
    redis_client.delete(STREAM)  # the demo reset does this
    assert c.run_once() == 0
    _pid, event_id = make_event(factory, "payment.final")
    push(redis_client, factory, event_id)
    assert c.run_once() == 1
    assert len(deliveries(factory)) == 1


def test_the_stored_message_never_carries_the_description(factory: Factory, redis_client: Redis) -> None:
    subscribe(factory, ["payment.final"])
    _pid, event_id = make_event(factory, "payment.final")
    c = consumer(factory, redis_client)
    push(redis_client, factory, event_id)
    c.run_once()
    claimed = claim_due(factory, 10, 30)
    assert len(claimed) == 1 and claimed[0].body is not None
    assert SENTINEL.encode() not in claimed[0].body
    body = json.loads(claimed[0].body)
    assert set(body) == {"id", "type", "created_at", "data"}
    assert set(body["data"]) == {"payment_id", "status", "amount_minor", "currency"}
