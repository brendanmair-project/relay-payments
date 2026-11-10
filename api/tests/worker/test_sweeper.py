"""REL-50: the sweeper fails timed-out attempts and re-drives stalled payments (ADR-0008, ADR-0011, ADR-0012).

`now` is passed explicitly (database clock plus an offset), so no test sleeps.
"""

import threading
import uuid
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Payment
from app.domain.lifecycle import Event, PaymentState
from app.outbox.publisher import publish_batch
from app.services.transitions import apply_transition, create_payment
from app.worker.consumer import STREAM, Consumer
from app.worker.handlers import handle_trigger
from app.worker.sweeper import SweepConfig, SweepResult, sweep
from tests.worker.conftest import APPROVED, CAPTURED, FakeProcessor, redis_client, timeline, types  # noqa: F401

CONFIG = SweepConfig(processor_timeout_seconds=5, timeout_grace_seconds=5, redrive_after_seconds=30)


def db_now(sf: sessionmaker[Session]) -> datetime:
    with sf() as session:
        return session.execute(sa.select(sa.func.now())).scalar_one()


def later(sf: sessionmaker[Session], seconds: float) -> datetime:
    return db_now(sf) + timedelta(seconds=seconds)


def payment_row(sf: sessionmaker[Session], pid: uuid.UUID) -> Payment:
    with sf() as session:
        return session.execute(sa.select(Payment).where(Payment.id == pid)).scalar_one()


@pytest.fixture
def routed_payment(factory: sessionmaker[Session], payment_id: uuid.UUID) -> uuid.UUID:
    with factory.begin() as session:
        apply_transition(
            session,
            payment_id,
            Event.ROUTE,
            expected_status=PaymentState.RECEIVED,
            expected_attempt=0,
            retries_enabled=True,
            processor="A",
            reason="initial",
        )
    return payment_id


@pytest.fixture
def authorized_payment(factory: sessionmaker[Session], routed_payment: uuid.UUID) -> uuid.UUID:
    with factory.begin() as session:
        apply_transition(
            session,
            routed_payment,
            Event.AUTHORIZE,
            expected_status=PaymentState.ROUTED,
            expected_attempt=1,
            retries_enabled=True,
        )
    return routed_payment


@pytest.fixture(autouse=True)
def rules_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROUTING_STRATEGY", raising=False)


def test_routed_payment_inside_the_timeout_is_left_alone(
    factory: sessionmaker[Session], routed_payment: uuid.UUID
) -> None:
    result = sweep(factory, CONFIG, now=later(factory, 9))  # timeout 5 + grace 5 = 10
    assert result == SweepResult(0, 0)
    assert payment_row(factory, routed_payment).status == "routed"


def test_routed_timeout_fails_the_attempt_and_schedules_the_retry(
    factory: sessionmaker[Session], routed_payment: uuid.UUID
) -> None:
    result = sweep(factory, CONFIG, now=later(factory, 11))
    assert result.timed_out == 1
    row = payment_row(factory, routed_payment)
    assert (row.status, row.is_final, row.attempt_no) == ("failed", False, 1)
    failed = [e for e in timeline(factory, routed_payment) if e.type == "payment.failed"]
    assert len(failed) == 1
    assert (failed[0].reason, failed[0].processor) == ("timeout", "A")
    assert types(factory, routed_payment)[-2:] == ["payment.failed", "payment.retry_scheduled"]


def test_routed_timeout_is_final_when_routing_is_static(
    factory: sessionmaker[Session], routed_payment: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "static")
    sweep(factory, CONFIG, now=later(factory, 11))
    assert payment_row(factory, routed_payment).is_final is True
    assert types(factory, routed_payment)[-2:] == ["payment.failed", "payment.final"]


def test_authorized_timeout_is_final_even_with_retries_enabled(
    factory: sessionmaker[Session], authorized_payment: uuid.UUID
) -> None:
    result = sweep(factory, CONFIG, now=later(factory, 11))
    assert result.timed_out == 1
    row = payment_row(factory, authorized_payment)
    assert (row.status, row.is_final) == ("failed", True)
    assert "payment.retry_scheduled" not in types(factory, authorized_payment)
    assert [e.reason for e in timeline(factory, authorized_payment) if e.type == "payment.failed"] == ["timeout"]


def test_repeated_sweeps_produce_one_timeout_transition(
    factory: sessionmaker[Session], routed_payment: uuid.UUID
) -> None:
    now = later(factory, 11)
    assert sweep(factory, CONFIG, now=now).timed_out == 1
    assert sweep(factory, CONFIG, now=now).timed_out == 0
    assert types(factory, routed_payment).count("payment.failed") == 1


def test_stalled_received_payment_is_redriven_once_per_threshold(
    factory: sessionmaker[Session], payment_id: uuid.UUID
) -> None:
    assert sweep(factory, CONFIG, now=later(factory, 29)).redriven == 0
    start = later(factory, 31)
    assert sweep(factory, CONFIG, now=start).redriven == 1
    assert sweep(factory, CONFIG, now=start + timedelta(seconds=1)).redriven == 0  # inside the threshold
    assert sweep(factory, CONFIG, now=start + timedelta(seconds=29)).redriven == 0
    assert types(factory, payment_id).count("payment.redriven") == 1
    row = payment_row(factory, payment_id)
    assert row.status == "received"
    assert row.last_driven_at is not None
    assert sweep(factory, CONFIG, now=start + timedelta(seconds=31)).redriven == 1
    assert types(factory, payment_id).count("payment.redriven") == 2


def test_stalled_retrying_payment_is_redriven_without_a_state_change(
    factory: sessionmaker[Session], routed_payment: uuid.UUID
) -> None:
    sweep(factory, CONFIG, now=later(factory, 11))  # routed -> failed (retrying)
    before = payment_row(factory, routed_payment)
    assert sweep(factory, CONFIG, now=later(factory, 20)).redriven == 0
    assert sweep(factory, CONFIG, now=later(factory, 45)).redriven == 1
    after = payment_row(factory, routed_payment)
    assert (after.status, after.attempt_no, after.is_final) == ("failed", 1, False)
    assert after.status_changed_at == before.status_changed_at
    assert types(factory, routed_payment)[-1] == "payment.redriven"


def test_final_payments_are_never_redriven(factory: sessionmaker[Session], authorized_payment: uuid.UUID) -> None:
    sweep(factory, CONFIG, now=later(factory, 11))  # authorized -> failed, final
    assert sweep(factory, CONFIG, now=later(factory, 600)) == SweepResult(0, 0)
    assert "payment.redriven" not in types(factory, authorized_payment)


def test_two_concurrent_sweepers_produce_one_move_per_payment(
    factory: sessionmaker[Session], routed_payment: uuid.UUID
) -> None:
    with factory.begin() as session:
        stalled = [create_payment(session, amount_minor=100 + i, currency="USD", reference=f"s-{i}") for i in range(5)]
    now = later(factory, 40)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            barrier.wait()
            sweep(factory, CONFIG, now=now)
        except BaseException as error:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert types(factory, routed_payment).count("payment.failed") == 1
    for pid in stalled:
        assert types(factory, pid).count("payment.redriven") == 1


def test_lost_stream_entry_still_ends_with_a_final_payment(
    factory: sessionmaker[Session],
    payment_id: uuid.UUID,
    redis_client: Redis,  # noqa: F811
) -> None:
    assert publish_batch(factory, redis_client) >= 1  # the received trigger reaches the stream ...
    redis_client.delete(STREAM)  # ... and is lost
    assert sweep(factory, CONFIG, now=later(factory, 31)).redriven == 1
    assert publish_batch(factory, redis_client) == 1  # the redriven event is the new trigger
    fake = FakeProcessor(authorize=APPROVED, capture=CAPTURED)
    consumer = Consumer(factory, redis_client, fake.client, "sweeper-test")
    consumer.ensure_group()
    assert consumer.run_once() == 1
    row = payment_row(factory, payment_id)
    assert (row.status, row.is_final) == ("captured", True)
    assert types(factory, payment_id).count("payment.redriven") == 1


def test_result_after_the_sweeper_failed_the_attempt_is_a_late_result(
    factory: sessionmaker[Session], payment_id: uuid.UUID
) -> None:
    def sweeper_runs_during_the_call(operation: str) -> None:
        if operation == "authorize":
            assert sweep(factory, CONFIG, now=later(factory, 100)).timed_out == 1

    fake = FakeProcessor(authorize=APPROVED, on_call=sweeper_runs_during_the_call)
    handle_trigger(factory, fake.client, payment_id)
    assert fake.operations() == ["authorize"]  # no capture: the payment is no longer authorized
    row = payment_row(factory, payment_id)
    assert (row.status, row.attempt_no) == ("failed", 1)
    late = [e for e in timeline(factory, payment_id) if e.type == "attempt.late_result"]
    assert len(late) == 1
    assert late[0].reason == "after_timeout"
