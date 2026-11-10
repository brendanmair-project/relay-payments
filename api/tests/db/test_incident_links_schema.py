"""REL-35.2/35.3: `incident_payments` and `incident_summaries` match data-model.md."""

from sqlalchemy import Connection, text

TZ = "timestamp with time zone"


def columns(conn: Connection, table: str) -> dict[str, tuple[str, str]]:
    rows = conn.execute(
        text("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def test_incident_payments_columns_and_primary_key(conn: Connection) -> None:
    assert columns(conn, "incident_payments") == {
        "incident_id": ("uuid", "NO"),
        "payment_id": ("uuid", "NO"),
        "linked_at": (TZ, "NO"),
        "first_event_id": ("bigint", "NO"),
    }
    key = conn.execute(
        text(
            "SELECT a.attname FROM pg_index i"
            " JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)"
            " WHERE i.indrelid = 'incident_payments'::regclass AND i.indisprimary ORDER BY a.attname"
        )
    ).scalars()
    assert list(key) == ["incident_id", "payment_id"]


def test_incident_summaries_columns(conn: Connection) -> None:
    assert columns(conn, "incident_summaries") == {
        "id": ("bigint", "NO"),
        "incident_id": ("uuid", "NO"),
        "source": ("text", "NO"),
        "model": ("text", "YES"),
        "text": ("text", "NO"),
        "cited_event_ids": ("ARRAY", "NO"),
        "cause": ("text", "NO"),
        "fallback_reason": ("text", "YES"),
        "generated_at": (TZ, "NO"),
        "trigger": ("text", "NO"),
    }
    element = conn.execute(
        text(
            "SELECT e.data_type FROM information_schema.element_types e JOIN information_schema.columns c"
            " ON e.object_name = c.table_name AND e.collection_type_identifier = c.dtd_identifier"
            " WHERE c.table_name = 'incident_summaries' AND c.column_name = 'cited_event_ids'"
        )
    ).scalar_one()
    assert element == "bigint"
