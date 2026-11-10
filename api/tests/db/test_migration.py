"""REL-15.1: the migration upgrades and downgrades on the test database and leaves it at head."""

from alembic import command
from sqlalchemy import Engine, inspect, text

from tests.db.conftest import alembic_config

TABLES = {
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


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_downgrade_base_then_upgrade_head_round_trips(engine: Engine) -> None:
    config = alembic_config()
    command.upgrade(config, "head")
    assert _tables(engine) >= TABLES
    try:
        command.downgrade(config, "base")
        assert not TABLES & _tables(engine)
        with engine.connect() as connection:
            leftovers = connection.execute(
                text("SELECT proname FROM pg_proc WHERE proname = 'payment_events_append_only'")
            ).all()
        assert leftovers == []
    finally:
        command.upgrade(config, "head")
    assert _tables(engine) >= TABLES
    # A second full cycle proves the downgrade left nothing behind that blocks a re-upgrade.
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert _tables(engine) >= TABLES
