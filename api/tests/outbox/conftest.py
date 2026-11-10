"""Outbox tests reuse the committing-session fixtures of the service tests and add a clean stream."""

import os
from collections.abc import Iterator

import pytest
from redis import Redis

from app.outbox.publisher import STREAM
from tests.services.conftest import clean_tables, correlation, engine, factory  # noqa: F401


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    client.delete(STREAM)
    yield client
    client.delete(STREAM)
    client.close()
