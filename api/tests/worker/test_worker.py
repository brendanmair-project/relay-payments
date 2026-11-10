"""Worker lifecycle tests (REL-21): real Postgres and Valkey, fake processor."""

import json
import time
import uuid

import pytest
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Payment
from app.domain.lifecycle import Event, PaymentState
from app.services.transitions import apply_transition, create_payment
from app.worker import handlers
from app.worker.consumer import GROUP, STREAM, Consumer
from tests.worker.conftest import (
    CAPTURE_FAILED,
    DECLINED,
    OUTAGE,
    TIMEOUT,
    FakeProcessor,
    pending,
    timeline,
    trigger,
    types,
)

Factory = sessionmaker[Session]


@pytest.fixture(autouse=True)
def static_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    """These REL-21 tests describe the static baseline (ADR-0009): processor A, reason static, no retry."""
    monkeypatch.setenv("ROUTING_STRATEGY", "static")


def make_consumer(
    factory: Factory, redis_client: Redis, fake: FakeProcessor, name: str = "c1", idle: int = 30000
) -> Consumer:
    consumer = Consumer(factory, redis_client, fake.client, name, reclaim_idle_ms=idle)
    consumer.ensure_group()
    return consumer


def payment(factory: Factory, pid: uuid.UUID) -> Payment:
    with factory() as session:
        return session.get_one(Payment, pid)


def test_received_payment_is_captured(factory: Factory, redis_client: Redis, payment_id: uuid.UUID) -> None:
    fake = FakeProcessor()
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    assert consumer.run_once() == 1
    row = payment(factory, payment_id)
    assert (row.status, row.is_final, row.attempt_no, row.processor) == ("captured", True, 1, "A")
    assert types(factory, payment_id) == [
        "payment.received",
        "payment.routed",
        "attempt.authorize_result",
        "payment.authorized",
        "attempt.capture_result",
        "payment.captured",
        "payment.final",
    ]
    events = timeline(factory, payment_id)
    assert (events[1].reason, events[1].processor) == ("static", "A")
    assert events[2].data == {"result": "approved", "latency_ms": 120}
    assert events[4].data == {"result": "captured", "latency_ms": 80}
    assert events[-1].data == {"outcome": "captured"}
    assert pending(redis_client) == 0


def test_declined_payment_is_final_without_capture(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = FakeProcessor(authorize=DECLINED)
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    consumer.run_once()
    row = payment(factory, payment_id)
    assert (row.status, row.is_final) == ("declined", True)
    assert fake.operations() == ["authorize"]
    assert types(factory, payment_id)[-3:] == ["attempt.authorize_result", "payment.declined", "payment.final"]
    events = timeline(factory, payment_id)
    assert events[2].reason == "do_not_honor"
    assert events[3].reason == "do_not_honor"


@pytest.mark.parametrize(("answer", "reason"), [(TIMEOUT, "timeout"), (OUTAGE, "outage")])
def test_authorize_timeout_or_outage_fails_payment(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID, answer: object, reason: str
) -> None:
    fake = FakeProcessor(authorize=answer)
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    consumer.run_once()
    row = payment(factory, payment_id)
    assert (row.status, row.is_final) == ("failed", True)
    assert types(factory, payment_id)[2:] == ["attempt.authorize_result", "payment.failed", "payment.final"]
    events = timeline(factory, payment_id)
    assert events[2].reason == reason
    assert events[2].data["result"] == "failed"
    assert (events[3].reason, events[3].processor) == (reason, "A")
    assert fake.operations() == ["authorize"]


@pytest.mark.parametrize(
    ("answer", "reason"), [(TIMEOUT, "timeout"), (OUTAGE, "outage"), (CAPTURE_FAILED, "capture_failed")]
)
def test_capture_problem_fails_payment(factory: Factory, redis_client: Redis, answer: object, reason: str) -> None:
    with factory.begin() as session:
        pid = create_payment(session, amount_minor=500, currency="EUR", reference="r2")
    fake = FakeProcessor(capture=answer)
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, pid)
    consumer.run_once()
    row = payment(factory, pid)
    assert (row.status, row.is_final) == ("failed", True)
    assert types(factory, pid)[-4:] == [
        "payment.authorized",
        "attempt.capture_result",
        "payment.failed",
        "payment.final",
    ]
    events = timeline(factory, pid)
    assert events[-3].reason == reason
    assert events[-2].reason == reason
    assert events[-1].data == {"outcome": "failed"}


def test_processor_requests_carry_key_and_reference(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = FakeProcessor()
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    consumer.run_once()
    assert fake.operations() == ["authorize", "capture"]
    for request in fake.requests:
        assert request.headers["Idempotency-Key"] == f"{payment_id}:1"
        assert request.url.path.startswith("/processors/a/")
        assert json.loads(request.content) == {
            "payment_id": str(payment_id),
            "attempt_no": 1,
            "amount_minor": 1250,
            "currency": "USD",
            "reference": "ref-1",
        }


def test_duplicate_trigger_changes_nothing(factory: Factory, redis_client: Redis, payment_id: uuid.UUID) -> None:
    fake = FakeProcessor()
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    trigger(redis_client, payment_id)
    trigger(redis_client, payment_id, "payment.redriven")
    assert consumer.run_once() == 3
    event_types = types(factory, payment_id)
    assert event_types.count("payment.routed") == 1
    assert event_types.count("attempt.authorize_result") == 1
    assert event_types.count("attempt.capture_result") == 1
    assert fake.operations() == ["authorize", "capture"]
    assert pending(redis_client) == 0


def test_non_trigger_message_is_acked_and_ignored(factory: Factory, redis_client: Redis, payment_id: uuid.UUID) -> None:
    fake = FakeProcessor()
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id, "payment.routed")
    trigger(redis_client, uuid.uuid4(), "payment.received")  # unknown payment: nothing to do
    assert consumer.run_once() == 2
    assert fake.requests == []
    assert types(factory, payment_id) == ["payment.received"]
    assert pending(redis_client) == 0


def test_group_created_from_start_processes_earlier_entries(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    trigger(redis_client, payment_id)  # published before any worker exists
    consumer = make_consumer(factory, redis_client, FakeProcessor())
    consumer.run_once()
    assert payment(factory, payment_id).status == "captured"


def test_pending_message_of_crashed_consumer_is_reclaimed_once(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = FakeProcessor()
    survivor = make_consumer(factory, redis_client, fake, "survivor", idle=200)
    trigger(redis_client, payment_id)
    # "dead" reads the entry and never acknowledges it
    got = redis_client.xreadgroup(GROUP, "dead", {STREAM: ">"}, count=1)
    assert got
    assert pending(redis_client) == 1
    assert survivor.run_once() == 0  # not idle long enough yet
    assert fake.requests == []
    time.sleep(0.3)
    assert survivor.run_once() == 1
    assert pending(redis_client) == 0
    assert types(factory, payment_id).count("payment.routed") == 1
    assert fake.operations() == ["authorize", "capture"]
    assert survivor.run_once() == 0


def test_failure_before_commit_leaves_message_pending(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(handlers, "apply_transition", boom)
    consumer = make_consumer(factory, redis_client, FakeProcessor())
    trigger(redis_client, payment_id)
    consumer.run_once()
    assert pending(redis_client) == 1
    assert types(factory, payment_id) == ["payment.received"]
    assert payment(factory, payment_id).status == "received"


def _fail_current_attempt(factory: Factory, pid: uuid.UUID, *, retry: bool) -> None:
    """What the sweeper (REL-50) or router (REL-22) would do while the processor call is in flight."""
    with factory.begin() as session:
        apply_transition(
            session,
            pid,
            Event.FAIL,
            expected_status=PaymentState.ROUTED,
            expected_attempt=1,
            retries_enabled=retry,
            reason="timeout",
        )
        if retry:
            apply_transition(
                session,
                pid,
                Event.ROUTE,
                expected_status=PaymentState.FAILED,
                expected_attempt=1,
                retries_enabled=True,
                processor="B",
                reason="retry",
            )


def test_late_authorize_after_timeout_is_recorded_only(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = FakeProcessor(on_call=lambda op: _fail_current_attempt(factory, payment_id, retry=False))
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    consumer.run_once()
    row = payment(factory, payment_id)
    assert (row.status, row.is_final, row.attempt_no) == ("failed", True, 1)
    events = timeline(factory, payment_id)
    late = [e for e in events if e.type == "attempt.late_result"]
    assert len(late) == 1
    assert (late[0].reason, late[0].processor, late[0].attempt_no) == ("after_timeout", "A", 1)
    assert late[0].data["result"] == "approved"
    assert fake.operations() == ["authorize"]  # no capture for an orphaned authorization
    assert "attempt.authorize_result" not in [e.type for e in events]
    assert pending(redis_client) == 0


def test_late_authorize_for_old_attempt_is_stale(factory: Factory, redis_client: Redis, payment_id: uuid.UUID) -> None:
    fake = FakeProcessor(on_call=lambda op: _fail_current_attempt(factory, payment_id, retry=True))
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    consumer.run_once()
    row = payment(factory, payment_id)
    assert (row.status, row.attempt_no, row.processor) == ("routed", 2, "B")
    late = [e for e in timeline(factory, payment_id) if e.type == "attempt.late_result"]
    assert [(e.reason, e.attempt_no) for e in late] == [("stale_attempt", 1)]


def test_late_capture_after_timeout_is_recorded_only(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    def fail_authorized(op: str) -> None:
        if op == "capture":
            with factory.begin() as session:
                apply_transition(
                    session,
                    payment_id,
                    Event.FAIL,
                    expected_status=PaymentState.AUTHORIZED,
                    expected_attempt=1,
                    retries_enabled=False,
                    reason="timeout",
                )

    fake = FakeProcessor(on_call=fail_authorized)
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    consumer.run_once()
    row = payment(factory, payment_id)
    assert (row.status, row.is_final) == ("failed", True)
    event_types = types(factory, payment_id)
    assert event_types.count("attempt.late_result") == 1
    assert "attempt.capture_result" not in event_types
    assert "payment.captured" not in event_types


def test_gateway_timeout_answer_fails_payment_as_timeout(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = FakeProcessor(authorize=(504, {"error": {"code": "processor_timeout", "message": "slow"}}))
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    consumer.run_once()
    assert [e.reason for e in timeline(factory, payment_id) if e.type == "payment.failed"] == ["timeout"]


def test_unexpected_processor_answer_leaves_message_pending(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    fake = FakeProcessor(authorize=(422, {"error": {"code": "validation_error", "message": "bad"}}))
    consumer = make_consumer(factory, redis_client, fake)
    trigger(redis_client, payment_id)
    consumer.run_once()
    assert pending(redis_client) == 1
    assert "attempt.authorize_result" not in types(factory, payment_id)


def test_stop_requested_leaves_unstarted_entries_pending(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID
) -> None:
    import threading

    consumer = make_consumer(factory, redis_client, FakeProcessor())
    trigger(redis_client, payment_id)
    stop = threading.Event()
    stop.set()
    assert consumer.run_once(stop=stop) == 0
    assert pending(redis_client) == 1
    assert payment(factory, payment_id).status == "received"
