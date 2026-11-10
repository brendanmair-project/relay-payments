"""REL-16: state change and event are written together, in order, or not at all."""

import threading
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import bind_correlation_id
from app.domain.lifecycle import Event, InvalidTransitionError, LateResultError, PaymentState, StaleAttemptError
from app.domain.reasons import EventType
from app.services import transitions
from app.services.transitions import (
    StateMismatchError,
    append_event,
    apply_transition,
    record_late_result,
)

Factory = sessionmaker[Session]


def events(factory: Factory, pid: uuid.UUID) -> list[dict[str, Any]]:
    with factory() as s:
        rows = s.execute(
            text(
                "SELECT seq, type, from_status, to_status, processor, reason, data, correlation_id, attempt_no, "
                "occurred_at FROM payment_events WHERE payment_id = :p ORDER BY seq"
            ),
            {"p": pid},
        ).mappings()
        return [dict(r) for r in rows]


def payment(factory: Factory, pid: uuid.UUID) -> dict[str, Any]:
    with factory() as s:
        return dict(s.execute(text("SELECT * FROM payments WHERE id = :p"), {"p": pid}).mappings().one())


def move(
    factory: Factory,
    pid: uuid.UUID,
    event: Event,
    status: PaymentState,
    attempt: int,
    retries: bool = True,
    **kw: Any,
) -> None:
    with factory.begin() as s:
        apply_transition(s, pid, event, expected_status=status, expected_attempt=attempt, retries_enabled=retries, **kw)


def test_create_payment_writes_received_event(factory: Factory, payment_id: uuid.UUID) -> None:
    row = payment(factory, payment_id)
    assert (row["status"], row["attempt_no"], row["is_final"]) == ("received", 0, False)
    (ev,) = events(factory, payment_id)
    assert (ev["seq"], ev["type"], ev["from_status"], ev["to_status"]) == (1, "payment.received", None, "received")


def test_state_change_and_event_written_together(factory: Factory, payment_id: uuid.UUID) -> None:
    move(factory, payment_id, Event.ROUTE, PaymentState.RECEIVED, 0, processor="A", reason="initial")
    row = payment(factory, payment_id)
    assert (row["status"], row["attempt_no"], row["processor"], row["is_final"]) == ("routed", 1, "A", False)
    routed = events(factory, payment_id)[-1]
    assert (routed["seq"], routed["type"], routed["from_status"], routed["to_status"]) == (
        2,
        "payment.routed",
        "received",
        "routed",
    )
    assert (routed["processor"], routed["reason"], routed["attempt_no"]) == ("A", "initial", 1)


def test_forced_failure_after_state_update_leaves_neither(
    factory: Factory, payment_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("injected failure after the state update")

    monkeypatch.setattr(transitions, "insert_event", boom)
    with pytest.raises(RuntimeError, match="injected"), factory.begin() as s:
        apply_transition(
            s,
            payment_id,
            Event.ROUTE,
            expected_status=PaymentState.RECEIVED,
            expected_attempt=0,
            retries_enabled=True,
            processor="A",
            reason="initial",
        )
    monkeypatch.undo()
    row = payment(factory, payment_id)
    assert (row["status"], row["attempt_no"], row["processor"]) == ("received", 0, None)
    assert [e["type"] for e in events(factory, payment_id)] == ["payment.received"]


def test_failure_on_companion_event_rolls_back_state_and_first_event(
    factory: Factory, routed_payment: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = transitions.insert_event
    calls: list[str] = []

    def fail_on_final(*args: Any, **kwargs: Any) -> int:
        calls.append(kwargs["type"])
        if kwargs["type"] == "payment.final":
            raise RuntimeError("injected failure on payment.final")
        return real(*args, **kwargs)

    monkeypatch.setattr(transitions, "insert_event", fail_on_final)
    with pytest.raises(RuntimeError, match="payment.final"), factory.begin() as s:
        apply_transition(
            s,
            routed_payment,
            Event.DECLINE,
            expected_status=PaymentState.ROUTED,
            expected_attempt=1,
            retries_enabled=True,
            reason="do_not_honor",
        )
    monkeypatch.undo()
    assert calls == ["payment.declined", "payment.final"]
    row = payment(factory, routed_payment)
    assert (row["status"], row["is_final"], row["final_at"]) == ("routed", False, None)
    assert [e["type"] for e in events(factory, routed_payment)] == ["payment.received", "payment.routed"]


def test_mismatch_writes_nothing(factory: Factory, routed_payment: uuid.UUID) -> None:
    before_events = events(factory, routed_payment)
    before = payment(factory, routed_payment)
    for status, attempt in ((PaymentState.RECEIVED, 1), (PaymentState.ROUTED, 2), (PaymentState.AUTHORIZED, 1)):
        with pytest.raises(StateMismatchError), factory.begin() as s:
            apply_transition(
                s,
                routed_payment,
                Event.AUTHORIZE,
                expected_status=status,
                expected_attempt=attempt,
                retries_enabled=True,
            )
    assert payment(factory, routed_payment) == before
    assert events(factory, routed_payment) == before_events


def test_invalid_transition_writes_nothing(factory: Factory, payment_id: uuid.UUID) -> None:
    with pytest.raises(InvalidTransitionError), factory.begin() as s:
        apply_transition(
            s,
            payment_id,
            Event.CAPTURE,
            expected_status=PaymentState.RECEIVED,
            expected_attempt=0,
            retries_enabled=True,
        )
    assert payment(factory, payment_id)["status"] == "received"
    assert len(events(factory, payment_id)) == 1


def test_missing_correlation_id_is_refused_before_writing(factory: Factory, payment_id: uuid.UUID) -> None:
    with bind_correlation_id(""), pytest.raises(ValueError, match="correlation_id"), factory.begin() as s:
        apply_transition(
            s,
            payment_id,
            Event.ROUTE,
            expected_status=PaymentState.RECEIVED,
            expected_attempt=0,
            retries_enabled=True,
            processor="A",
            reason="initial",
        )
    assert payment(factory, payment_id)["status"] == "received"


def test_capture_is_final_with_final_event_in_same_transaction(factory: Factory, routed_payment: uuid.UUID) -> None:
    move(factory, routed_payment, Event.AUTHORIZE, PaymentState.ROUTED, 1)
    move(factory, routed_payment, Event.CAPTURE, PaymentState.AUTHORIZED, 1)
    row = payment(factory, routed_payment)
    assert (row["status"], row["is_final"]) == ("captured", True)
    evs = events(factory, routed_payment)
    assert [e["type"] for e in evs] == [
        "payment.received",
        "payment.routed",
        "payment.authorized",
        "payment.captured",
        "payment.final",
    ]
    assert evs[-1]["data"] == {"outcome": "captured"}
    assert [e["seq"] for e in evs] == [1, 2, 3, 4, 5]
    # final_at equals the final event's occurred_at (data-model.md)
    assert row["final_at"] == evs[-1]["occurred_at"]


def test_decline_is_final_with_reason(factory: Factory, routed_payment: uuid.UUID) -> None:
    move(factory, routed_payment, Event.DECLINE, PaymentState.ROUTED, 1, reason="insufficient_funds")
    evs = events(factory, routed_payment)
    assert [e["type"] for e in evs[-2:]] == ["payment.declined", "payment.final"]
    assert evs[-2]["reason"] == "insufficient_funds"
    assert evs[-1]["data"] == {"outcome": "declined"}


def test_retryable_failure_schedules_retry_not_final(factory: Factory, routed_payment: uuid.UUID) -> None:
    move(factory, routed_payment, Event.FAIL, PaymentState.ROUTED, 1, reason="timeout")
    row = payment(factory, routed_payment)
    assert (row["status"], row["is_final"], row["final_at"], row["attempt_no"]) == ("failed", False, None, 1)
    evs = events(factory, routed_payment)
    assert [e["type"] for e in evs[-2:]] == ["payment.failed", "payment.retry_scheduled"]
    assert (evs[-2]["processor"], evs[-2]["reason"]) == ("A", "timeout")
    # retry on the other processor starts attempt 2
    move(factory, routed_payment, Event.ROUTE, PaymentState.FAILED, 1, processor="B", reason="retry")
    row = payment(factory, routed_payment)
    assert (row["status"], row["attempt_no"], row["processor"]) == ("routed", 2, "B")


def test_failure_without_retries_is_final(factory: Factory, routed_payment: uuid.UUID) -> None:
    move(factory, routed_payment, Event.FAIL, PaymentState.ROUTED, 1, retries=False, reason="outage")
    evs = events(factory, routed_payment)
    assert [e["type"] for e in evs[-2:]] == ["payment.failed", "payment.final"]
    assert evs[-1]["data"] == {"outcome": "failed"}
    assert payment(factory, routed_payment)["is_final"] is True


def test_every_event_stores_correlation_id(factory: Factory, routed_payment: uuid.UUID) -> None:
    move(factory, routed_payment, Event.FAIL, PaymentState.ROUTED, 1, reason="timeout", correlation_id="explicit-1")
    append_event((s := factory()), routed_payment, EventType.PAYMENT_REDRIVEN, correlation_id="explicit-2")
    s.commit()
    s.close()
    evs = events(factory, routed_payment)
    assert all(e["correlation_id"] for e in evs)
    assert [e["correlation_id"] for e in evs[-3:]] == ["explicit-1", "explicit-1", "explicit-2"]
    assert evs[0]["correlation_id"] == "corr-test"


def test_append_event_uses_next_seq_and_current_attempt(factory: Factory, routed_payment: uuid.UUID) -> None:
    with factory.begin() as s:
        seq = append_event(
            s,
            routed_payment,
            EventType.ATTEMPT_AUTHORIZE_RESULT,
            processor="A",
            data={"result": "approved", "latency_ms": 12},
        )
    assert seq == 3
    last = events(factory, routed_payment)[-1]
    assert (last["type"], last["attempt_no"], last["from_status"], last["to_status"]) == (
        "attempt.authorize_result",
        1,
        None,
        None,
    )
    assert last["data"] == {"result": "approved", "latency_ms": 12}


def test_append_event_rejects_state_change_types_and_bad_reasons(factory: Factory, routed_payment: uuid.UUID) -> None:
    with pytest.raises(ValueError, match="apply_transition"), factory.begin() as s:
        append_event(s, routed_payment, EventType.PAYMENT_CAPTURED)
    with pytest.raises(ValueError, match="not allowed"), factory.begin() as s:
        append_event(s, routed_payment, EventType.ATTEMPT_CAPTURE_RESULT, processor="A", reason="initial")
    assert len(events(factory, routed_payment)) == 2


def test_unknown_payment_raises(factory: Factory) -> None:
    with pytest.raises(transitions.PaymentNotFoundError), factory.begin() as s:
        append_event(s, uuid.uuid4(), EventType.PAYMENT_REDRIVEN)


def test_stale_attempt_is_recorded_as_late_result(factory: Factory, routed_payment: uuid.UUID) -> None:
    with pytest.raises(StaleAttemptError) as caught, factory.begin() as s:
        apply_transition(
            s,
            routed_payment,
            Event.AUTHORIZE,
            expected_status=PaymentState.ROUTED,
            expected_attempt=1,
            retries_enabled=True,
            event_attempt=2,
        )
    with factory.begin() as s:
        record_late_result(s, routed_payment, caught.value, processor="B", data={"result": "approved"})
    last = events(factory, routed_payment)[-1]
    assert (last["type"], last["reason"], last["processor"]) == ("attempt.late_result", "stale_attempt", "B")


def test_after_timeout_is_recorded_as_late_result(factory: Factory, routed_payment: uuid.UUID) -> None:
    move(factory, routed_payment, Event.FAIL, PaymentState.ROUTED, 1, reason="timeout")
    with pytest.raises(LateResultError) as caught, factory.begin() as s:
        apply_transition(
            s,
            routed_payment,
            Event.AUTHORIZE,
            expected_status=PaymentState.FAILED,
            expected_attempt=1,
            retries_enabled=True,
        )
    with factory.begin() as s:
        record_late_result(s, routed_payment, caught.value, processor="A")
    last = events(factory, routed_payment)[-1]
    assert (last["type"], last["reason"]) == ("attempt.late_result", "after_timeout")


def test_concurrent_writers_get_gapless_unique_seqs(factory: Factory, routed_payment: uuid.UUID) -> None:
    """State-change and non-state-change writers on one payment, each with its own connection."""
    appenders, per_appender = 4, 15
    errors: list[BaseException] = []
    barrier = threading.Barrier(appenders + 1)

    def appender(n: int) -> None:
        try:
            barrier.wait()
            for i in range(per_appender):
                with factory.begin() as s:
                    append_event(
                        s,
                        routed_payment,
                        EventType.ATTEMPT_AUTHORIZE_RESULT,
                        processor="A",
                        data={"writer": n, "i": i},
                        correlation_id="corr-thread",
                    )
        except BaseException as exc:  # noqa: BLE001 - reported to the main thread
            errors.append(exc)

    def mover() -> None:
        try:
            barrier.wait()
            move(factory, routed_payment, Event.AUTHORIZE, PaymentState.ROUTED, 1, correlation_id="corr-thread")
            move(factory, routed_payment, Event.CAPTURE, PaymentState.AUTHORIZED, 1, correlation_id="corr-thread")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=appender, args=(n,)) for n in range(appenders)]
    threads.append(threading.Thread(target=mover))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    evs = events(factory, routed_payment)
    # received + routed + appended + authorized + captured + final
    assert [e["seq"] for e in evs] == list(range(1, 2 + appenders * per_appender + 3 + 1))
    types = [e["type"] for e in evs]
    assert types.count("attempt.authorize_result") == appenders * per_appender
    assert types.index("payment.authorized") < types.index("payment.captured") < types.index("payment.final")
    assert payment(factory, routed_payment)["status"] == "captured"
