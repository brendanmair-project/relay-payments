"""Webhook tests commit for real on relay_test: they reuse the committing fixtures and empty the webhook tables."""

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.webhooks.config import WebhookSettings
from tests.api.conftest import api_key  # noqa: F401
from tests.services.conftest import clean_tables, correlation, engine, factory  # noqa: F401
from tests.worker.conftest import redis_client  # noqa: F401


@pytest.fixture(autouse=True)
def clean_webhooks(engine: Engine) -> Iterator[None]:  # noqa: F811
    sql = text("TRUNCATE webhook_delivery_attempts, webhook_deliveries, webhook_subscriptions, webhook_consumer_state")
    with engine.begin() as connection:
        connection.execute(sql)
    yield
    with engine.begin() as connection:
        connection.execute(sql)


@pytest.fixture(autouse=True)
def allowed_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The api and the consumer read the allowlist from the environment."""
    monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "hooks.test,localhost")


@pytest.fixture
def settings() -> WebhookSettings:
    return WebhookSettings(
        webhook_allowed_hosts="hooks.test,localhost",
        webhook_backoff_base_seconds=2,
        webhook_backoff_factor=2,
        webhook_backoff_max_seconds=60,
        webhook_log_retention_days=7,
        webhook_timeout_seconds=5,
    )


@pytest.fixture
def headers(api_key: str) -> dict[str, str]:  # noqa: F811
    return {"X-API-Key": api_key}
