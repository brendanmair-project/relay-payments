"""REL-34.2: `incidents` and `incident_detector_state` match data-model.md; the migration round-trips."""

import uuid

from alembic import command
from sqlalchemy import Connection, Engine, inspect, text

from tests.db.conftest import alembic_config, rejected

TZ = "timestamp with time zone"
COLUMNS = {
    "id": ("uuid", "NO"),
    "processor": ("character", "YES"),
    "source": ("text", "NO"),
    "status": ("text", "NO"),
    "title": ("text", "NO"),
    "opened_at": (TZ, "NO"),
    "opened_by_event_id": ("bigint", "YES"),
    "recovered_at": (TZ, "YES"),
    "triaged_at": (TZ, "YES"),
    "resolved_at": (TZ, "YES"),
    "created_at": (TZ, "NO"),
}
INSERT = (
    "INSERT INTO incidents (id, processor, source, status, title, opened_at)"
    " VALUES (:id, :processor, :source, :status, 't', now())"
)


def add(conn: Connection, **overrides: object) -> bool:
    values = {"id": str(uuid.uuid4()), "processor": "A", "source": "rule", "status": "detected"} | overrides
    return rejected(conn, INSERT, values)


def test_columns_match_the_data_model(conn: Connection) -> None:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = 'incidents'"
        )
    ).all()
    assert {r[0]: (r[1], r[2]) for r in rows} == COLUMNS


def test_detector_state_columns(conn: Connection) -> None:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
            " WHERE table_name = 'incident_detector_state'"
        )
    ).all()
    assert {r[0]: (r[1], r[2]) for r in rows} == {"processor": ("character", "NO"), "last_event_id": ("bigint", "NO")}


def test_the_open_incident_index_is_unique_and_partial(conn: Connection) -> None:
    definition = conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_incidents_open_per_processor'")
    ).scalar_one()
    assert "UNIQUE" in definition and "(processor)" in definition
    assert "resolved" in definition and "processor IS NOT NULL" in definition


def test_check_constraints(conn: Connection) -> None:
    assert add(conn, processor="C")
    assert add(conn, source="bot")
    assert add(conn, status="closed")
    assert not add(conn, processor=None, source="manual")


def test_one_open_incident_per_processor_whatever_the_source_or_status(conn: Connection) -> None:
    assert not add(conn, processor="A", source="rule", status="triaged")
    assert add(conn, processor="A", source="manual", status="detected")
    assert not add(conn, processor="B")
    assert not add(conn, processor="A", status="resolved")
    assert not add(conn, processor="A", status="resolved")
    assert not add(conn, processor=None, source="manual")
    assert not add(conn, processor=None, source="manual")


def test_migration_downgrade_removes_only_the_incident_tables(engine: Engine) -> None:
    config = alembic_config()
    try:
        command.downgrade(config, "0002")
        tables = set(inspect(engine).get_table_names())
        assert not {"incidents", "incident_detector_state"} & tables
        assert {"payments", "payment_events", "idempotency_keys", "payment_explanations"} <= tables
    finally:
        command.upgrade(config, "head")
    assert {"incidents", "incident_detector_state"} <= set(inspect(engine).get_table_names())
