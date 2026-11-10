"""Incident tests commit for real on relay_test: they reuse the explainer fixtures and empty the incident tables."""

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.api.conftest import api_key  # noqa: F401
from tests.services.conftest import clean_tables, correlation, engine, factory  # noqa: F401
from tests.worker.conftest import redis_client  # noqa: F401


@pytest.fixture(autouse=True)
def clean_incidents(engine: Engine) -> Iterator[None]:  # noqa: F811
    sql = text("TRUNCATE incidents, incident_detector_state, incident_payments, incident_summaries")
    with engine.begin() as connection:
        connection.execute(sql)
    yield
    with engine.begin() as connection:
        connection.execute(sql)
