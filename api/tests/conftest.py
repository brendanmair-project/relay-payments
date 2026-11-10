"""Tests run against the relay_test database only (REL-12): DATABASE_URL is replaced before the app loads."""

import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

test_url = os.environ.get("TEST_DATABASE_URL", "")
if not test_url.rsplit("/", 1)[-1].endswith("_test"):
    raise pytest.UsageError("TEST_DATABASE_URL must point at a database whose name ends in _test")
os.environ["DATABASE_URL"] = test_url
dev_redis = os.environ.get("REDIS_URL", "")
test_redis = os.environ.get("TEST_REDIS_URL", "")
if not test_redis or test_redis == dev_redis or test_redis.rstrip("/").endswith("/0"):
    raise pytest.UsageError("TEST_REDIS_URL must be set and must not be the development Redis database (db 0)")
os.environ["REDIS_URL"] = test_redis
os.environ.setdefault("RELAY_API_KEY", "test-key")
# The request log never touches /var/log/relay in tests (REL-52).
os.environ["REQUEST_LOG_PATH"] = os.path.join(tempfile.mkdtemp(prefix="relay-test-logs-"), "api-requests.jsonl")


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client that runs the app lifespan (engine and Redis client are created at startup)."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
