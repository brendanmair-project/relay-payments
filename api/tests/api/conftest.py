"""Fixtures for the POST /payments tests: real commits on relay_test, so tables are truncated around each test."""

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import get_settings
from tests.db.conftest import API_DIR


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(os.environ["DATABASE_URL"], pool_size=10)
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(config, "head")
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_tables(engine: Engine) -> Iterator[None]:
    # CASCADE also empties idempotency_keys, which references payments; it is named for clarity.
    sql = text("TRUNCATE payments, payment_events, idempotency_keys, payment_explanations RESTART IDENTITY CASCADE")
    with engine.begin() as connection:
        connection.execute(sql)
    yield
    with engine.begin() as connection:
        connection.execute(sql)


@pytest.fixture
def api_key() -> str:
    return get_settings().relay_api_key
