"""REL-25.7: `payment_explanations` matches docs/architecture/data-model.md and the migration round-trips."""

import pytest
from alembic import command
from sqlalchemy import Connection, Engine, inspect, text

from tests.db.conftest import PAYMENT_ID, alembic_config, insert_event, insert_payment, rejected

TZ = "timestamp with time zone"
COLUMNS = {
    "id": ("bigint", "NO"),
    "payment_id": ("uuid", "NO"),
    "source": ("text", "NO"),
    "model": ("text", "YES"),
    "text": ("text", "NO"),
    "cited_event_seqs": ("ARRAY", "NO"),
    "trigger": ("text", "NO"),
    "fallback_reason": ("text", "YES"),
    "final_event_at": (TZ, "NO"),
    "generated_at": (TZ, "NO"),
}
INSERT = (
    "INSERT INTO payment_explanations (payment_id, source, model, text, cited_event_seqs, trigger, final_event_at,"
    " generated_at) VALUES (:p, :source, :model, 't', ARRAY[1], :trigger, now(), now())"
)


def add(conn: Connection, **overrides: object) -> None:
    values = {"p": PAYMENT_ID, "source": "rules", "model": None, "trigger": "final_failure"} | overrides
    conn.execute(text(INSERT), values)


@pytest.fixture
def payment(conn: Connection) -> None:
    insert_payment(conn)
    insert_event(conn)


def test_columns_match_the_data_model(conn: Connection) -> None:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'payment_explanations'"
        )
    ).all()
    assert {r[0]: (r[1], r[2]) for r in rows} == COLUMNS


def test_indexes_exist(conn: Connection) -> None:
    defs = {
        r[0]: r[1]
        for r in conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'payment_explanations'")
        )
    }
    joined = " ".join(defs.values()).lower()
    assert "(payment_id, generated_at desc)" in joined
    unique = [d.lower() for d in defs.values() if "unique" in d.lower() and "where" in d.lower()]
    assert len(unique) == 1
    assert "(payment_id)" in unique[0]
    assert "final_failure" in unique[0]


def test_valid_rows_are_accepted(conn: Connection, payment: None) -> None:
    add(conn)
    add(conn, source="model", model="granite3.3:2b", trigger="on_request")
    add(conn, trigger="regenerate")


@pytest.mark.parametrize(
    "overrides",
    [
        {"source": "llm"},
        {"trigger": "manual"},
        {"source": "model", "model": None},
        {"source": "rules", "model": "granite3.3:2b"},
    ],
)
def test_checks_reject_bad_values(conn: Connection, payment: None, overrides: dict[str, object]) -> None:
    values = {"p": PAYMENT_ID, "source": "rules", "model": None, "trigger": "final_failure"} | overrides
    assert rejected(conn, INSERT, values)


def test_only_one_final_failure_explanation_per_payment(conn: Connection, payment: None) -> None:
    add(conn)
    assert rejected(conn, INSERT, {"p": PAYMENT_ID, "source": "rules", "model": None, "trigger": "final_failure"})
    add(conn, trigger="on_request")
    add(conn, trigger="on_request")


def test_payment_must_exist(conn: Connection) -> None:
    assert rejected(
        conn,
        INSERT,
        {"p": "22222222-2222-2222-2222-222222222222", "source": "rules", "model": None, "trigger": "on_request"},
    )


def test_migration_downgrade_removes_only_the_explanations_table(engine: Engine) -> None:
    config = alembic_config()
    try:
        command.downgrade(config, "0001")
        tables = set(inspect(engine).get_table_names())
        assert "payment_explanations" not in tables
        assert {"payments", "payment_events", "idempotency_keys"} <= tables
    finally:
        command.upgrade(config, "head")
    assert "payment_explanations" in set(inspect(engine).get_table_names())
