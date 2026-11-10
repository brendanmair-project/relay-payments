"""REL-34.7 (ADR-0014): the compose file runs the incident detector as its own default-stack service."""

import re
from pathlib import Path

import pytest

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


@pytest.fixture
def text() -> str:
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml is not part of the api image")
    return COMPOSE.read_text(encoding="utf-8")


def service(text: str, name: str) -> str:
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", text, re.S | re.M)
    assert match, f"service {name} missing"
    return match.group(1)


def test_incidents_is_its_own_container_from_the_api_image(text: str) -> None:
    block = service(text, "incidents")
    assert "<<: *api-image" in block
    assert '["python", "-m", "app.incidents"]' in block
    assert re.search(r"^    restart: unless-stopped$", block, re.M)
    assert re.search(r"^    stop_grace_period: \d+s$", block, re.M)
    assert re.search(r"^    healthcheck:$", block, re.M)
    assert "incidents-heartbeat" in block


def test_incidents_waits_for_migrate_postgres_and_redis(text: str) -> None:
    block = service(text, "incidents")
    assert re.search(r"^      migrate:\n        condition: service_completed_successfully$", block, re.M)
    assert re.search(r"^      redis:\n        condition: service_healthy$", block, re.M)
    assert re.search(r"^      postgres:\n        condition: service_healthy$", block, re.M)


def test_incidents_is_in_the_default_stack_and_publishes_no_host_port(text: str) -> None:
    block = service(text, "incidents")
    assert not re.search(r"^    profiles:", block, re.M)
    assert not re.search(r"^    ports:", block, re.M)


def test_the_payment_worker_does_not_run_detection(text: str) -> None:
    assert "app.incidents" not in service(text, "worker")
