"""Fixtures for the schema tests: they migrate relay_test (never the development database) and leave it at head."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

API_DIR = Path(__file__).resolve().parents[2]
PAYMENT_ID = "11111111-1111-1111-1111-111111111111"


def alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    return config


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(os.environ["DATABASE_URL"])
    yield eng
    eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated(engine: Engine) -> Iterator[None]:
    """Rebuild from base so the tests always run against this checkout's migration, not a schema (or trigger)
    left at head by an earlier run; the suite leaves the schema at head for every other test."""
    command.downgrade(alembic_config(), "base")
    command.upgrade(alembic_config(), "head")
    yield
    command.upgrade(alembic_config(), "head")


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    """A connection whose work is always rolled back."""
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


def rejected(connection: Connection, sql: str, params: dict[str, object] | None = None) -> bool:
    """True when the database rejects the statement; the savepoint keeps the outer transaction usable."""
    try:
        with connection.begin_nested():
            connection.execute(text(sql), params or {})
    except IntegrityError:  # SQLSTATE class 23 only: a missing table or a typo must not count as a rejection
        return True
    return False


def insert_payment(connection: Connection, payment_id: str = PAYMENT_ID, **overrides: object) -> None:
    values: dict[str, object] = {
        "id": payment_id,
        "amount_minor": 1250,
        "currency": "USD",
        "status": "received",
        "attempt_no": 0,
        "correlation_id": "corr-1",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    connection.execute(text(f"INSERT INTO payments ({columns}) VALUES ({placeholders})"), values)  # noqa: S608


def insert_event(connection: Connection, payment_id: str = PAYMENT_ID, **overrides: object) -> int:
    values: dict[str, object] = {
        "payment_id": payment_id,
        "seq": 1,
        "attempt_no": 0,
        "type": "payment.received",
        "to_status": "received",
        "correlation_id": "corr-1",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f":{name}" for name in values)
    sql = f"INSERT INTO payment_events ({columns}) VALUES ({placeholders}) RETURNING id"  # noqa: S608
    return int(connection.execute(text(sql), values).scalar_one())
