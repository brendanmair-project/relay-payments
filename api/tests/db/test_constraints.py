"""REL-15.7: value rules fail in the database as well as in code (data-model.md)."""
# ruff: noqa: E501, S608

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.domain.reasons import EventType
from tests.db.conftest import PAYMENT_ID, insert_event, insert_payment, rejected

INSERT_PAYMENT = (
    "INSERT INTO payments (id, amount_minor, currency, status, attempt_no, correlation_id, reference) "
    "VALUES (gen_random_uuid(), :amount, :currency, 'received', 0, 'c', :reference)"
)


def _payment_insert_rejected(conn: Connection, **overrides: object) -> bool:
    params: dict[str, object] = {"amount": 100, "currency": "USD", "reference": None}
    params.update(overrides)
    return rejected(conn, INSERT_PAYMENT, params)


def test_valid_payment_and_event_insert(conn: Connection) -> None:
    assert not _payment_insert_rejected(conn, reference="order-1_A.2")
    insert_payment(conn)
    insert_event(conn)
    assert conn.execute(text("SELECT count(*) FROM payment_events")).scalar_one() == 1


@pytest.mark.parametrize("reference", ["has space", "bad/slash", "", "café"])
def test_invalid_reference_is_rejected(conn: Connection, reference: str) -> None:
    assert _payment_insert_rejected(conn, reference=reference)


def test_reference_of_64_allowed_characters_is_accepted(conn: Connection) -> None:
    assert not _payment_insert_rejected(conn, reference="aZ09._-" * 9 + "a")


@pytest.mark.parametrize("amount", [0, -5, 1_000_000_000_001])
def test_amount_out_of_range_is_rejected(conn: Connection, amount: int) -> None:
    assert _payment_insert_rejected(conn, amount=amount)


def test_amount_above_int32_is_stored(conn: Connection) -> None:
    assert not _payment_insert_rejected(conn, amount=1_000_000_000_000)


def test_unknown_currency_is_rejected(conn: Connection) -> None:
    assert _payment_insert_rejected(conn, currency="CAD")


def test_row_level_payment_checks(conn: Connection) -> None:
    base = "INSERT INTO payments (id, amount_minor, currency, correlation_id, {cols}) VALUES (gen_random_uuid(), 1, 'USD', 'c', {vals})"
    # attempt_no = 0 must go with status received and no processor
    assert rejected(conn, base.format(cols="status, attempt_no", vals="'routed', 0"))
    assert rejected(conn, base.format(cols="status, attempt_no, processor", vals="'received', 0, 'A'"))
    assert rejected(conn, base.format(cols="status, attempt_no", vals="'routed', 3"))
    assert rejected(conn, base.format(cols="status, attempt_no", vals="'bogus', 1"))
    # a routed attempt needs a processor
    assert rejected(conn, base.format(cols="status, attempt_no", vals="'routed', 1"))
    assert not rejected(conn, base.format(cols="status, attempt_no, processor", vals="'routed', 1, 'B'"))
    # is_final only for final statuses, and final_at tracks is_final
    assert rejected(
        conn,
        base.format(cols="status, attempt_no, processor, is_final, final_at", vals="'routed', 1, 'A', true, now()"),
    )
    assert rejected(conn, base.format(cols="status, attempt_no, processor, is_final", vals="'captured', 1, 'A', true"))
    assert rejected(conn, base.format(cols="status, attempt_no, processor, final_at", vals="'captured', 1, 'A', now()"))
    assert not rejected(
        conn,
        base.format(cols="status, attempt_no, processor, is_final, final_at", vals="'captured', 1, 'A', true, now()"),
    )


def test_unknown_reason_is_rejected(conn: Connection) -> None:
    insert_payment(conn)
    assert rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, reason, correlation_id) "
        "VALUES (:p, 1, 1, 'payment.declined', 'because', 'c')",
        {"p": PAYMENT_ID},
    )
    assert not rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, to_status, reason, correlation_id) "
        "VALUES (:p, 1, 1, 'payment.declined', 'declined', 'do_not_honor', 'c')",
        {"p": PAYMENT_ID},
    )


def test_unknown_event_type_is_rejected(conn: Connection) -> None:
    insert_payment(conn)
    assert rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, correlation_id) VALUES (:p, 1, 0, 'payment.bogus', 'c')",
        {"p": PAYMENT_ID},
    )


@pytest.mark.parametrize("event_type", [t.value for t in EventType])
def test_every_event_type_is_accepted(conn: Connection, event_type: str) -> None:
    insert_payment(conn)
    processor = "A" if event_type.startswith("attempt.") or event_type in ("payment.routed", "payment.failed") else None
    assert not rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, processor, correlation_id) "
        "VALUES (:p, 1, 0, :t, :proc, 'c')",
        {"p": PAYMENT_ID, "t": event_type, "proc": processor},
    )


def test_processor_is_required_on_routing_failure_and_attempt_events(conn: Connection) -> None:
    insert_payment(conn)
    for event_type in (
        "payment.routed",
        "payment.failed",
        "attempt.authorize_result",
        "attempt.capture_result",
        "attempt.late_result",
    ):
        assert rejected(
            conn,
            "INSERT INTO payment_events (payment_id, seq, attempt_no, type, correlation_id) VALUES (:p, 1, 1, :t, 'c')",
            {"p": PAYMENT_ID, "t": event_type},
        ), event_type


def test_from_status_requires_to_status(conn: Connection) -> None:
    insert_payment(conn)
    assert rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, from_status, correlation_id) "
        "VALUES (:p, 1, 0, 'payment.received', 'received', 'c')",
        {"p": PAYMENT_ID},
    )


def test_event_attempt_no_range_and_processor_values(conn: Connection) -> None:
    insert_payment(conn)
    assert rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, correlation_id) VALUES (:p, 1, 3, 'payment.received', 'c')",
        {"p": PAYMENT_ID},
    )
    assert rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, processor, correlation_id) "
        "VALUES (:p, 1, 1, 'payment.routed', 'C', 'c')",
        {"p": PAYMENT_ID},
    )


def test_duplicate_payment_seq_is_rejected(conn: Connection) -> None:
    insert_payment(conn)
    insert_event(conn, seq=1)
    assert rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, correlation_id) VALUES (:p, 1, 0, 'payment.redriven', 'c')",
        {"p": PAYMENT_ID},
    )
    assert not rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, correlation_id) VALUES (:p, 2, 0, 'payment.redriven', 'c')",
        {"p": PAYMENT_ID},
    )


def test_event_requires_an_existing_payment(conn: Connection) -> None:
    assert rejected(
        conn,
        "INSERT INTO payment_events (payment_id, seq, attempt_no, type, correlation_id) "
        "VALUES (gen_random_uuid(), 1, 0, 'payment.received', 'c')",
    )


def test_idempotency_key_rules(conn: Connection) -> None:
    insert_payment(conn)
    insert_sql = (
        "INSERT INTO idempotency_keys (key, request_hash, state, lease_token, lease_expires_at, expires_at, response_body) "
        "VALUES (:k, repeat('a', 64), :state, gen_random_uuid(), now() + interval '30 seconds', "
        "now() + interval '24 hours', CAST(:body AS jsonb))"
    )
    assert not rejected(conn, insert_sql, {"k": "k1", "state": "in_progress", "body": None})
    assert not rejected(conn, insert_sql, {"k": "k2", "state": "completed", "body": "{}"})
    # a duplicate key, a bad state, and a state/body mismatch are rejected
    assert rejected(conn, insert_sql, {"k": "k1", "state": "in_progress", "body": None})
    assert rejected(conn, insert_sql, {"k": "k3", "state": "other", "body": None})
    assert rejected(conn, insert_sql, {"k": "k4", "state": "completed", "body": None})
    assert rejected(conn, insert_sql, {"k": "k5", "state": "in_progress", "body": "{}"})


def test_reference_longer_than_64_characters_is_rejected(conn: Connection) -> None:
    # varchar(64) refuses it (a data error) before the CHECK is reached.
    with pytest.raises(DBAPIError), conn.begin_nested():
        conn.execute(text(INSERT_PAYMENT), {"amount": 1, "currency": "USD", "reference": "x" * 65})
