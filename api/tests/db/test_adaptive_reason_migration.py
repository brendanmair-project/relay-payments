"""REL-44: migration 0007 adds the routed reason `adaptive` to the payment_events reason CHECK, and removes it again."""

from alembic import command
from sqlalchemy import Engine, text

from tests.db.conftest import alembic_config

CHECK_DEFINITION = "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_payment_events_reason'"


def _definition(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text(CHECK_DEFINITION)).scalar_one())


def test_head_allows_adaptive_and_the_previous_revision_does_not(engine: Engine) -> None:
    config = alembic_config()
    command.upgrade(config, "head")
    try:
        assert "'adaptive'" in _definition(engine)
        assert "'failover'" in _definition(engine)
        command.downgrade(config, "0006")
        assert "'adaptive'" not in _definition(engine)
        assert "'failover'" in _definition(engine)
    finally:
        command.upgrade(config, "head")
    assert "'adaptive'" in _definition(engine)


def test_downgrade_works_even_when_adaptive_events_exist(engine: Engine) -> None:
    config = alembic_config()
    command.upgrade(config, "head")
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE payments, payment_events RESTART IDENTITY CASCADE"))
        connection.execute(
            text(
                "INSERT INTO payments (id, amount_minor, currency, status, attempt_no, processor, correlation_id) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 100, 'USD', 'routed', 1, 'A', 'c')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO payment_events (payment_id, seq, attempt_no, type, processor, reason, correlation_id) "
                "VALUES ('00000000-0000-0000-0000-000000000001', 1, 1, 'payment.routed', 'A', 'adaptive', 'c')"
            )
        )
    try:
        command.downgrade(config, "0006")
        with engine.connect() as connection:
            reason = connection.execute(text("SELECT reason FROM payment_events")).scalar_one()
        assert reason == "initial"
    finally:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE payments, payment_events RESTART IDENTITY CASCADE"))
