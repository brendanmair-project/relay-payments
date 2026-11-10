"""REL-15.1, REL-15.7: the live schema matches docs/architecture/data-model.md."""

import re

import pytest
from sqlalchemy import Connection, text

from app.domain.lifecycle import PaymentState
from app.domain.money import CURRENCY_DIGITS
from app.domain.reasons import REASONS_BY_EVENT_TYPE, EventType

TZ = "timestamp with time zone"
# (data_type, character_maximum_length, is_nullable)
PAYMENTS = {
    "id": ("uuid", None, "NO"),
    "amount_minor": ("bigint", None, "NO"),
    "currency": ("character", 3, "NO"),
    "description": ("character varying", 200, "YES"),
    "reference": ("character varying", 64, "YES"),
    "status": ("text", None, "NO"),
    "processor": ("character", 1, "YES"),
    "attempt_no": ("smallint", None, "NO"),
    "is_final": ("boolean", None, "NO"),
    "correlation_id": ("character varying", 64, "NO"),
    "created_at": (TZ, None, "NO"),
    "status_changed_at": (TZ, None, "NO"),
    "last_driven_at": (TZ, None, "YES"),
    "final_at": (TZ, None, "YES"),
}
EVENTS = {
    "id": ("bigint", None, "NO"),
    "payment_id": ("uuid", None, "NO"),
    "seq": ("integer", None, "NO"),
    "attempt_no": ("smallint", None, "NO"),
    "type": ("text", None, "NO"),
    "from_status": ("text", None, "YES"),
    "to_status": ("text", None, "YES"),
    "processor": ("character", 1, "YES"),
    "reason": ("text", None, "YES"),
    "data": ("jsonb", None, "NO"),
    "correlation_id": ("character varying", 64, "NO"),
    "occurred_at": (TZ, None, "NO"),
    "published_at": (TZ, None, "YES"),
}
KEYS = {
    "key": ("character varying", 255, "NO"),
    "request_hash": ("character", 64, "NO"),
    "state": ("text", None, "NO"),
    "lease_token": ("uuid", None, "NO"),
    "lease_expires_at": (TZ, None, "NO"),
    "payment_id": ("uuid", None, "YES"),
    "response_status": ("smallint", None, "YES"),
    "response_body": ("jsonb", None, "YES"),
    "created_at": (TZ, None, "NO"),
    "expires_at": (TZ, None, "NO"),
}


def _columns(conn: Connection, table: str) -> dict[str, tuple[object, ...]]:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _constraint_def(conn: Connection, name: str) -> str:
    return str(
        conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"), {"n": name}
        ).scalar_one()
    )


def _literals(definition: str) -> set[str]:
    return set(re.findall(r"'([^']*)'", definition))


@pytest.mark.parametrize(
    ("table", "expected"), [("payments", PAYMENTS), ("payment_events", EVENTS), ("idempotency_keys", KEYS)]
)
def test_columns_match_the_data_model(conn: Connection, table: str, expected: dict[str, tuple[object, ...]]) -> None:
    assert _columns(conn, table) == expected


def test_amount_minor_is_bigint(conn: Connection) -> None:
    assert _columns(conn, "payments")["amount_minor"][0] == "bigint"


def test_every_timestamp_is_timestamptz(conn: Connection) -> None:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name IN ('payments','payment_events','idempotency_keys') "
            "AND (data_type LIKE 'timestamp%' OR column_name LIKE '%\\_at')"
        )
    ).all()
    assert len(rows) == 4 + 2 + 3  # payments, payment_events, idempotency_keys
    assert {r[1] for r in rows} == {TZ}


def test_event_id_is_identity_always(conn: Connection) -> None:
    row = conn.execute(
        text(
            "SELECT is_identity, identity_generation FROM information_schema.columns "
            "WHERE table_name = 'payment_events' AND column_name = 'id'"
        )
    ).one()
    assert tuple(row) == ("YES", "ALWAYS")


def test_column_defaults(conn: Connection) -> None:
    rows = conn.execute(
        text(
            "SELECT table_name, column_name, column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_default IS NOT NULL "
            "AND table_name IN ('payments','payment_events','idempotency_keys')"
        )
    ).all()
    defaults = {(r[0], r[1]): r[2] for r in rows}
    assert defaults[("payments", "attempt_no")] == "0"
    assert defaults[("payments", "is_final")] == "false"
    assert defaults[("payments", "created_at")] == "now()"
    assert defaults[("payment_events", "occurred_at")] == "now()"
    assert defaults[("payment_events", "data")].startswith("'{}'::jsonb")
    assert defaults[("idempotency_keys", "created_at")] == "now()"


def test_event_type_check_lists_all_13_types(conn: Connection) -> None:
    literals = _literals(_constraint_def(conn, "ck_payment_events_type"))
    assert literals == {t.value for t in EventType}
    assert len(literals) == 13


def test_reason_check_lists_exactly_the_decided_values(conn: Connection) -> None:
    literals = _literals(_constraint_def(conn, "ck_payment_events_reason"))
    assert literals == {m.value for enum in REASONS_BY_EVENT_TYPE.values() if enum for m in enum}
    assert len(literals) == 13


def test_reference_check_uses_the_documented_pattern(conn: Connection) -> None:
    assert "^[A-Za-z0-9._-]{1,64}$" in _constraint_def(conn, "ck_payments_reference")


def test_status_currency_and_state_checks(conn: Connection) -> None:
    assert _literals(_constraint_def(conn, "ck_payments_status")) == {s.value for s in PaymentState}
    assert _literals(_constraint_def(conn, "ck_payments_currency")) == set(CURRENCY_DIGITS)
    assert _literals(_constraint_def(conn, "ck_idempotency_keys_state")) == {"in_progress", "completed"}
    assert _literals(_constraint_def(conn, "ck_payments_processor")) == {"A", "B"}


def test_unique_payment_id_seq(conn: Connection) -> None:
    rows = (
        conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE contype = 'u' "
                "AND conrelid = CAST('payment_events' AS regclass)"
            )
        )
        .scalars()
        .all()
    )
    assert rows == ["UNIQUE (payment_id, seq)"]


def test_foreign_keys_and_primary_keys(conn: Connection) -> None:
    rows = conn.execute(
        text(
            "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE contype IN ('f', 'p') AND connamespace = 'public'::regnamespace"
        )
    ).all()
    found = {(r[0], r[1]) for r in rows}
    assert {
        ("payment_events", "FOREIGN KEY (payment_id) REFERENCES payments(id)"),
        ("idempotency_keys", "FOREIGN KEY (payment_id) REFERENCES payments(id)"),
        ("payments", "PRIMARY KEY (id)"),
        ("payment_events", "PRIMARY KEY (id)"),
        ("idempotency_keys", "PRIMARY KEY (key)"),
    } <= found


def _index_defs(conn: Connection, table: str) -> list[str]:
    return list(
        conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = :t"), {"t": table}
        ).scalars()
    )


@pytest.mark.parametrize(
    ("table", "fragment"),
    [
        ("payments", "(status, processor, created_at)"),
        ("payments", "(status, status_changed_at)"),
        ("payments", "(created_at DESC, id DESC)"),
        ("payment_events", "(type, processor, occurred_at)"),
        ("payment_events", "(id) WHERE (published_at IS NULL)"),
        ("idempotency_keys", "(expires_at)"),
    ],
)
def test_index_exists(conn: Connection, table: str, fragment: str) -> None:
    defs = _index_defs(conn, table)
    assert any(fragment in d for d in defs), defs
