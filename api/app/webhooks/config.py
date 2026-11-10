"""Webhook settings (ADR-0015): read from the environment each time; the api and the webhooks container share them."""

from pydantic_settings import BaseSettings


class WebhookSettings(BaseSettings):
    # Comma-separated exact hostnames; the default allows the demo sink and the local machine only.
    webhook_allowed_hosts: str = "webhook-sink,localhost,127.0.0.1"
    # Delay after the n-th failed attempt: min(base * factor ** (n - 1), max). Demo-friendly defaults.
    webhook_backoff_base_seconds: float = 2.0
    webhook_backoff_factor: float = 2.0
    webhook_backoff_max_seconds: float = 60.0
    # Delivered and failed rows older than this are deleted by the cleanup step.
    webhook_log_retention_days: int = 7
    webhook_timeout_seconds: float = 5.0


def get_webhook_settings() -> WebhookSettings:
    return WebhookSettings()


def backoff_seconds(attempt: int, settings: WebhookSettings) -> float:
    """Seconds to wait after the `attempt`-th failed attempt (1-based)."""
    delay = settings.webhook_backoff_base_seconds * settings.webhook_backoff_factor ** (attempt - 1)
    return min(delay, settings.webhook_backoff_max_seconds)
