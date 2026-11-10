"""REL-39: the webhook tables match data-model.md; the unique key, the CHECKs and the migration behave."""

import uuid

from alembic import command
from sqlalchemy import Connection, Engine, inspect, text

from tests.db.conftest import alembic_config, rejected

TZ = "timestamp with time zone"
SUBSCRIPTION_COLUMNS = {
    "id": ("uuid", "NO"),
    "url": ("text", "NO"),
    "event_types": ("ARRAY", "NO"),
    "secret": ("text", "NO"),
    "active": ("boolean", "NO"),
    "created_at": (TZ, "NO"),
}
DELIVERY_COLUMNS = {
    "id": ("bigint", "NO"),
    "subscription_id": ("uuid", "NO"),
    "event_id": ("bigint", "NO"),
    "event_type": ("text", "NO"),
    "attempt": ("smallint", "NO"),
    "status": ("text", "NO"),
    "next_attempt_at": (TZ, "NO"),
    "last_status_code": ("integer", "YES"),
    "last_error": ("text", "YES"),
    "created_at": (TZ, "NO"),
    "updated_at": (TZ, "NO"),
}
SUBSCRIBE = "INSERT INTO webhook_subscriptions (id, url, event_types, secret) VALUES (:id, 'http://x/', :types, 's')"
DELIVER = (
    "INSERT INTO webhook_deliveries (subscription_id, event_id, event_type, status, attempt)"
    " VALUES (:s, :e, :t, :st, :a)"
)


def columns(conn: Connection, table: str) -> dict[str, tuple[str, str]]:
    rows = conn.execute(
        text("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def add_subscription(conn: Connection, types: list[str]) -> tuple[str, bool]:
    sid = str(uuid.uuid4())
    return sid, rejected(conn, SUBSCRIBE, {"id": sid, "types": types})


def deliver(conn: Connection, sid: str, **overrides: object) -> bool:
    values: dict[str, object] = {"s": sid, "e": 1, "t": "payment.final", "st": "pending", "a": 0} | overrides
    return rejected(conn, DELIVER, values)


def test_columns_match_the_data_model(conn: Connection) -> None:
    assert columns(conn, "webhook_subscriptions") == SUBSCRIPTION_COLUMNS
    assert columns(conn, "webhook_deliveries") == DELIVERY_COLUMNS
    assert columns(conn, "webhook_consumer_state") == {"id": ("smallint", "NO"), "last_event_id": ("bigint", "NO")}


def test_subscription_event_types_must_be_one_or_more_lifecycle_types(conn: Connection) -> None:
    assert not add_subscription(conn, ["payment.final", "payment.declined"])[1]
    assert add_subscription(conn, [])[1]
    assert add_subscription(conn, ["payment.routed"])[1]
    assert add_subscription(conn, ["payment.final", "attempt.authorize_result"])[1]
    assert add_subscription(conn, ["nonsense"])[1]


def test_deliveries_are_unique_per_subscription_and_event(conn: Connection) -> None:
    sid, refused = add_subscription(conn, ["payment.final"])
    assert not refused
    other, _ = add_subscription(conn, ["payment.final"])
    assert not deliver(conn, sid, e=1)
    assert deliver(conn, sid, e=1)  # a duplicate stream entry cannot make a second row
    assert not deliver(conn, sid, e=2)
    assert not deliver(conn, other, e=1)


def test_delivery_check_constraints_and_the_foreign_key(conn: Connection) -> None:
    sid, _ = add_subscription(conn, ["payment.final"])
    assert deliver(conn, sid, st="done")
    assert deliver(conn, sid, t="payment.routed")
    assert deliver(conn, sid, a=9)
    assert deliver(conn, sid, a=-1)
    assert not deliver(conn, sid, st="failed", a=8, e=3)
    assert deliver(conn, str(uuid.uuid4()), e=4)


def test_the_consumer_state_has_a_single_row(conn: Connection) -> None:
    assert not rejected(conn, "INSERT INTO webhook_consumer_state (id, last_event_id) VALUES (1, 5)")
    assert rejected(conn, "INSERT INTO webhook_consumer_state (id, last_event_id) VALUES (2, 5)")
    assert rejected(conn, "INSERT INTO webhook_consumer_state (id, last_event_id) VALUES (1, 6)")


def test_the_due_index_is_partial_on_pending(conn: Connection) -> None:
    definition = conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_webhook_deliveries_due'")
    ).scalar_one()
    assert "next_attempt_at" in definition and "pending" in definition


def test_migration_downgrade_removes_only_the_webhook_tables(engine: Engine) -> None:
    config = alembic_config()
    names = {"webhook_subscriptions", "webhook_deliveries", "webhook_consumer_state", "webhook_delivery_attempts"}
    try:
        command.downgrade(config, "0004")
        tables = set(inspect(engine).get_table_names())
        assert not names & tables
        assert {"payments", "incidents", "incident_summaries"} <= tables
    finally:
        command.upgrade(config, "head")
    assert names <= set(inspect(engine).get_table_names())


def test_attempt_columns_checks_and_cascade(conn: Connection) -> None:
    assert columns(conn, "webhook_delivery_attempts") == {
        "id": ("bigint", "NO"),
        "delivery_id": ("bigint", "NO"),
        "attempt": ("smallint", "NO"),
        "status_code": ("integer", "YES"),
        "error": ("text", "YES"),
        "duration_ms": ("integer", "NO"),
        "attempted_at": (TZ, "NO"),
    }
    sid, _ = add_subscription(conn, ["payment.final"])
    assert not deliver(conn, sid)
    delivery = conn.execute(text("SELECT id FROM webhook_deliveries")).scalar_one()
    insert = "INSERT INTO webhook_delivery_attempts (delivery_id, attempt, duration_ms) VALUES (:d, :a, :ms)"
    assert not rejected(conn, insert, {"d": delivery, "a": 1, "ms": 3})
    assert rejected(conn, insert, {"d": delivery, "a": 0, "ms": 3})
    assert rejected(conn, insert, {"d": delivery, "a": 9, "ms": 3})
    assert rejected(conn, insert, {"d": delivery, "a": 2, "ms": -1})
    assert rejected(conn, insert, {"d": delivery + 1000, "a": 2, "ms": 1})
    conn.execute(text("DELETE FROM webhook_deliveries WHERE id = :d"), {"d": delivery})
    assert conn.execute(text("SELECT count(*) FROM webhook_delivery_attempts")).scalar_one() == 0
