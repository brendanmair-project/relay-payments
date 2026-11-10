"""REL-15.2: the SQLAlchemy models describe the same tables the migration builds."""

from sqlalchemy import Connection, text

from app.db.models import Base, IdempotencyKey, Payment, PaymentEvent


def test_metadata_tables_and_columns_match_the_live_schema(conn: Connection) -> None:
    assert set(Base.metadata.tables) == {
        "payments",
        "payment_events",
        "idempotency_keys",
        "payment_explanations",
        "incidents",
        "incident_detector_state",
        "incident_payments",
        "incident_summaries",
        "webhook_subscriptions",
        "webhook_deliveries",
        "webhook_consumer_state",
        "webhook_delivery_attempts",
    }
    for table in Base.metadata.tables.values():
        live = {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": table.name}
            )
        }
        assert {c.name for c in table.columns} == live, table.name


def test_metadata_constraint_and_index_names_match_the_live_schema(conn: Connection) -> None:
    for table in Base.metadata.tables.values():
        live_checks = set(
            conn.execute(
                text("SELECT conname FROM pg_constraint WHERE contype = 'c' AND conrelid = CAST(:t AS regclass)"),
                {"t": table.name},
            ).scalars()
        )
        model_checks = {c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"}
        assert model_checks == live_checks, table.name
        live_indexes = set(
            conn.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = :t"), {"t": table.name}).scalars()
        )
        model_indexes = {i.name for i in table.indexes}
        # primary key and unique-constraint indexes exist only in the database listing
        assert model_indexes <= live_indexes, table.name


def test_models_map_the_tables() -> None:
    assert Payment.__tablename__ == "payments"
    assert PaymentEvent.__tablename__ == "payment_events"
    assert IdempotencyKey.__tablename__ == "idempotency_keys"
    assert Payment.__table__.c.amount_minor.type.__class__.__name__ == "BigInteger"
