"""REL-25.7: explanations are stored once per final failure, outside the payment path, with `payment.explained`."""

import uuid
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import PaymentEvent
from app.explain.store import PaymentNotFinalError, explain_payment, latest_explanation
from app.services.transitions import PaymentNotFoundError
from tests.explain.fakes import FakeModel, answer
from tests.explainer.helpers import SENTINEL, captured, declined, failed_final, retrying

Factory = sessionmaker[Session]


def rows(factory: Factory, pid: uuid.UUID) -> list[sa.Row[tuple[object, ...]]]:
    with factory() as session:
        return list(
            session.execute(
                sa.text(
                    "SELECT source, model, text, cited_event_seqs, trigger, fallback_reason, final_event_at,"
                    " generated_at FROM payment_explanations WHERE payment_id = :p ORDER BY id"
                ),
                {"p": pid},
            )
        )


def explained_events(factory: Factory, pid: uuid.UUID) -> list[PaymentEvent]:
    with factory() as session:
        return list(
            session.scalars(
                sa.select(PaymentEvent)
                .where(PaymentEvent.payment_id == pid, PaymentEvent.type == "payment.explained")
                .order_by(PaymentEvent.seq)
            )
        )


def good_model() -> FakeModel:
    return FakeModel(answer("Declined for insufficient funds.", [3, 4], "decline_insufficient_funds"))


def test_final_failure_stores_a_model_explanation_and_one_event(factory: Factory) -> None:
    pid = declined(factory)
    stored = explain_payment(factory, pid, "final_failure", good_model())
    assert stored is not None
    (row,) = rows(factory, pid)
    assert (row.source, row.model, row.trigger, row.fallback_reason) == (
        "model",
        "granite3.3:2b",
        "final_failure",
        None,
    )
    assert row.text == "Declined for insufficient funds."
    assert row.cited_event_seqs == [3, 4]
    (event,) = explained_events(factory, pid)
    assert event.seq > 4
    assert event.data["source"] == "model"
    assert event.data["trigger"] == "final_failure"


def test_unavailable_model_stores_the_rules_explanation_with_the_reason(factory: Factory) -> None:
    pid = failed_final(factory)
    explain_payment(factory, pid, "final_failure", FakeModel(unavailable="model_timeout"))
    (row,) = rows(factory, pid)
    assert (row.source, row.model, row.fallback_reason) == ("rules", None, "model_timeout")
    assert row.text
    assert row.cited_event_seqs


def test_redelivered_final_creates_no_second_row_or_event_and_no_model_call(factory: Factory) -> None:
    pid = declined(factory)
    model = good_model()
    assert explain_payment(factory, pid, "final_failure", model) is not None
    assert explain_payment(factory, pid, "final_failure", model) is None
    assert len(rows(factory, pid)) == 1
    assert len(explained_events(factory, pid)) == 1
    assert len(model.prompts) == 1


def test_concurrent_duplicate_insert_writes_neither_row_nor_event(factory: Factory) -> None:
    """The insert itself is conflict-safe: a second generation that raced past the pre-check adds nothing."""
    from app.explain import store

    pid = declined(factory)
    explain_payment(factory, pid, "final_failure", good_model())
    snapshot = store.read_snapshot(factory, pid)
    result = FakeModel(unavailable="model_unreachable")
    from app.explain.generate import generate_explanation

    generated = generate_explanation(
        snapshot.events, amount_minor=snapshot.amount_minor, currency=snapshot.currency, model=result
    )
    assert store.insert_explanation(factory, pid, "final_failure", generated, snapshot, "corr-test") is None
    assert len(rows(factory, pid)) == 1
    assert len(explained_events(factory, pid)) == 1


def test_time_to_explanation_is_generated_at_minus_final_event_at(factory: Factory) -> None:
    pid = declined(factory)
    explain_payment(factory, pid, "final_failure", good_model())
    (row,) = rows(factory, pid)
    with factory() as session:
        final_at = session.scalar(
            sa.select(PaymentEvent.occurred_at).where(
                PaymentEvent.payment_id == pid, PaymentEvent.type == "payment.final"
            )
        )
    assert row.final_event_at == final_at
    assert isinstance(row.generated_at, datetime)
    assert row.generated_at >= row.final_event_at


def test_prompt_never_contains_the_description(factory: Factory) -> None:
    pid = declined(factory)
    model = good_model()
    explain_payment(factory, pid, "final_failure", model)
    assert SENTINEL not in model.prompts[0]
    assert "[3] " in model.prompts[0]


def test_non_final_payment_is_refused(factory: Factory) -> None:
    pid = retrying(factory)
    with pytest.raises(PaymentNotFinalError):
        explain_payment(factory, pid, "on_request", good_model())
    assert rows(factory, pid) == []


def test_unknown_payment_is_refused(factory: Factory) -> None:
    with pytest.raises(PaymentNotFoundError):
        explain_payment(factory, uuid.uuid4(), "on_request", good_model())


def test_on_request_fills_a_captured_payment_and_regenerate_adds_rows(factory: Factory) -> None:
    pid = captured(factory)
    model = FakeModel(answer("Captured first time.", [4], "captured_first_time"))
    first = explain_payment(factory, pid, "on_request", model)
    second = explain_payment(factory, pid, "regenerate", model)
    third = explain_payment(factory, pid, "regenerate", model)
    assert first and second and third
    assert [r.trigger for r in rows(factory, pid)] == ["on_request", "regenerate", "regenerate"]
    assert len(explained_events(factory, pid)) == 3
    with factory() as session:
        latest = latest_explanation(session, pid)
    assert latest is not None and latest.id == third.id


def test_latest_is_none_without_rows(factory: Factory) -> None:
    pid = declined(factory)
    with factory() as session:
        assert latest_explanation(session, pid) is None
