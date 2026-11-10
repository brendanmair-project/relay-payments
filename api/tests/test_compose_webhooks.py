"""REL-39 (ADR-0015): the compose file runs the webhooks consumer as its own default-stack service, and the demo sink
under the `webhooks-demo` profile."""

import re
from pathlib import Path

import pytest

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
PROMETHEUS = Path(__file__).resolve().parents[2] / "observability" / "prometheus" / "prometheus.yml"


@pytest.fixture
def text() -> str:
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml is not part of the api image")
    return COMPOSE.read_text(encoding="utf-8")


def service(text: str, name: str) -> str:
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", text, re.S | re.M)
    assert match, f"service {name} missing"
    return match.group(1)


def test_webhooks_is_its_own_container_from_the_api_image(text: str) -> None:
    block = service(text, "webhooks")
    assert "<<: *api-image" in block
    assert '["python", "-m", "app.webhooks"]' in block
    assert re.search(r"^    restart: unless-stopped$", block, re.M)
    assert re.search(r"^    stop_grace_period: \d+s$", block, re.M)
    assert re.search(r"^    healthcheck:$", block, re.M)
    assert "webhooks-heartbeat" in block
    assert re.search(r"^    logging: \*default-logging$", block, re.M)


def test_webhooks_waits_for_migrate_postgres_and_redis(text: str) -> None:
    block = service(text, "webhooks")
    assert re.search(r"^      migrate:\n        condition: service_completed_successfully$", block, re.M)
    assert re.search(r"^      redis:\n        condition: service_healthy$", block, re.M)
    assert re.search(r"^      postgres:\n        condition: service_healthy$", block, re.M)


def test_webhooks_is_in_the_default_stack_publishes_no_port_and_never_needs_the_sink(text: str) -> None:
    block = service(text, "webhooks")
    assert not re.search(r"^    profiles:", block, re.M)
    assert not re.search(r"^    ports:", block, re.M)
    assert not re.search(r"^      webhook-sink:", block, re.M)


def test_webhooks_gets_the_settings_it_reads_and_a_metrics_port_but_no_api_key(text: str) -> None:
    block = service(text, "webhooks")
    for name in (
        "DATABASE_URL",
        "REDIS_URL",
        "METRICS_PORT",
        "WEBHOOK_ALLOWED_HOSTS",
        "WEBHOOK_BACKOFF_BASE_SECONDS",
        "WEBHOOK_BACKOFF_FACTOR",
        "WEBHOOK_BACKOFF_MAX_SECONDS",
        "WEBHOOK_LOG_RETENTION_DAYS",
        "WEBHOOK_TIMEOUT_SECONDS",
    ):
        assert re.search(rf"^      {name}: ", block, re.M), name
    assert "RELAY_API_KEY" not in block


def test_the_api_receives_the_allowlist_it_checks_at_creation(text: str) -> None:
    assert re.search(
        r"^      WEBHOOK_ALLOWED_HOSTS: \$\{WEBHOOK_ALLOWED_HOSTS:-webhook-sink,localhost,127\.0\.0\.1\}$",
        service(text, "api"),
        re.M,
    )


def test_the_sink_is_profile_only_supervised_and_loopback_only(text: str) -> None:
    block = service(text, "webhook-sink")
    assert re.search(r'^    profiles: \["webhooks-demo"\]$', block, re.M)
    assert "<<: *api-image" in block
    assert "app.webhooks.sink" in block
    assert re.search(r"^    restart: unless-stopped$", block, re.M)
    assert re.search(r"^    healthcheck:$", block, re.M)
    assert re.search(r"^    logging: \*default-logging$", block, re.M)
    host_ports = re.findall(r'^      - "([^"]+)"$', block, re.M)
    assert host_ports and all(p.startswith("127.0.0.1:") for p in host_ports), host_ports


def test_the_sink_holds_no_database_or_api_key(text: str) -> None:
    block = service(text, "webhook-sink")
    for name in ("RELAY_API_KEY", "DATABASE_URL", "REDIS_URL"):
        assert name not in block, name


def test_prometheus_scrapes_the_webhooks_container() -> None:
    if not PROMETHEUS.exists():
        pytest.skip("observability/ is not part of the api image")
    scrape = PROMETHEUS.read_text(encoding="utf-8")
    assert re.search(r'- job_name: relay-webhooks\n    static_configs:\n      - targets: \["webhooks:9100"\]', scrape)
