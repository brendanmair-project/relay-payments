"""Fixtures for the service tests: they commit for real (separate sessions), so they truncate around each test."""

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.correlation import bind_correlation_id
from app.domain.lifecycle import Event, PaymentState
from app.services.transitions import apply_transition, create_payment
from tests.db.conftest import API_DIR


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(os.environ["DATABASE_URL"], pool_size=10)
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(config, "head")
    yield eng
    eng.dispose()


def _truncate(engine: Engine) -> None:
    # The append-only trigger rejects DELETE, but not TRUNCATE (data-model.md "Retention").
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE payments, payment_events RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def clean_tables(engine: Engine) -> Iterator[None]:
    _truncate(engine)
    yield
    _truncate(engine)


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def correlation() -> Iterator[None]:
    with bind_correlation_id("corr-test"):
        yield


@pytest.fixture
def payment_id(factory: sessionmaker[Session]) -> uuid.UUID:
    with factory.begin() as session:
        return create_payment(session, amount_minor=1250, currency="USD", reference="ref-1")


@pytest.fixture
def routed_payment(factory: sessionmaker[Session], payment_id: uuid.UUID) -> uuid.UUID:
    with factory.begin() as session:
        apply_transition(
            session,
            payment_id,
            Event.ROUTE,
            expected_status=PaymentState.RECEIVED,
            expected_attempt=0,
            retries_enabled=True,
            processor="A",
            reason="initial",
        )
    return payment_id
