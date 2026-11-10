"""REL-15.1, REL-15.4: payment_events is append-only in the database (trigger) and in code (events module)."""
# ruff: noqa: E501, S608

import inspect

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from tests.db.conftest import PAYMENT_ID, insert_event, insert_payment, rejected

UPDATABLE_OTHER_COLUMNS = {
    "payment_id": "'22222222-2222-2222-2222-222222222222'",
    "seq": "99",
    "attempt_no": "2",
    "type": "'payment.redriven'",
    "from_status": "'received'",
    "to_status": "'failed'",
    "processor": "'B'",
    "reason": "'timeout'",
    "data": "'{\"x\": 1}'::jsonb",
    "correlation_id": "'other'",
    "occurred_at": "now() + interval '1 day'",
}


@pytest.fixture
def event_id(conn: Connection) -> int:
    insert_payment(conn)
    insert_payment(conn, "22222222-2222-2222-2222-222222222222")
    return insert_event(conn)


@pytest.mark.parametrize("column", sorted(UPDATABLE_OTHER_COLUMNS))
def test_update_of_any_other_column_is_rejected(conn: Connection, event_id: int, column: str) -> None:
    assert rejected(
        conn, f"UPDATE payment_events SET {column} = {UPDATABLE_OTHER_COLUMNS[column]} WHERE id = :i", {"i": event_id}
    )  # noqa: S608


def test_delete_is_rejected(conn: Connection, event_id: int) -> None:
    assert rejected(conn, "DELETE FROM payment_events WHERE id = :i", {"i": event_id})
    assert conn.execute(text("SELECT count(*) FROM payment_events")).scalar_one() == 1


def test_published_at_can_be_set_once_and_not_again(conn: Connection, event_id: int) -> None:
    assert not rejected(conn, "UPDATE payment_events SET published_at = now() WHERE id = :i", {"i": event_id})
    assert conn.execute(
        text("SELECT published_at IS NOT NULL FROM payment_events WHERE id = :i"), {"i": event_id}
    ).scalar_one()
    assert rejected(conn, "UPDATE payment_events SET published_at = now() WHERE id = :i", {"i": event_id})
    assert rejected(conn, "UPDATE payment_events SET published_at = NULL WHERE id = :i", {"i": event_id})


def test_published_at_cannot_change_together_with_another_column(conn: Connection, event_id: int) -> None:
    assert rejected(
        conn, "UPDATE payment_events SET published_at = now(), reason = 'timeout' WHERE id = :i", {"i": event_id}
    )


def test_setting_published_at_to_null_on_an_unpublished_event_is_rejected(conn: Connection, event_id: int) -> None:
    assert rejected(conn, "UPDATE payment_events SET published_at = NULL WHERE id = :i", {"i": event_id})


def test_events_module_exposes_only_insert_and_mark_published() -> None:
    from app.db import events

    public = {
        name
        for name, member in vars(events).items()
        if inspect.isfunction(member) and member.__module__ == events.__name__ and not name.startswith("_")
    }
    assert public == {"insert_event", "mark_published"}


def test_events_module_insert_and_mark_published(conn: Connection) -> None:
    from app.db import events

    insert_payment(conn)
    session = Session(bind=conn)
    first = events.insert_event(
        session,
        payment_id=PAYMENT_ID,
        seq=1,
        attempt_no=0,
        type="payment.received",
        to_status="received",
        correlation_id="c",
    )
    second = events.insert_event(
        session,
        payment_id=PAYMENT_ID,
        seq=2,
        attempt_no=1,
        type="payment.routed",
        from_status="received",
        to_status="routed",
        processor="A",
        reason="initial",
        data={"k": "v"},
        correlation_id="c",
    )
    assert second > first
    assert events.mark_published(session, [first]) == 1
    # Marking again changes nothing (only unpublished events are touched), and an empty list is a no-op.
    assert events.mark_published(session, [first]) == 0
    assert events.mark_published(session, []) == 0
    rows = conn.execute(text("SELECT id, published_at IS NOT NULL, data FROM payment_events ORDER BY id")).all()
    assert [(r[0], r[1]) for r in rows] == [(first, True), (second, False)]
    assert rows[1][2] == {"k": "v"}


def test_models_have_no_update_or_delete_helpers_for_events() -> None:
    from app.db import events, models

    for module in (events, models):
        names = {n.lower() for n in vars(module)}
        assert not {n for n in names if n.startswith(("update", "delete", "remove"))}
