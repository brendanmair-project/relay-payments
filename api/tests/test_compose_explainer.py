"""REL-25.9: the compose file runs the explainer as its own service from the api image (skipped inside the image)."""

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


def test_explainer_service_is_its_own_container_from_the_api_image(text: str) -> None:
    block = service(text, "explainer")
    assert "<<: *api-image" in block
    assert '["python", "-m", "app.explainer"]' in block
    assert "restart: unless-stopped" in block
    assert "host.docker.internal:host-gateway" in block
    for dependency in ("migrate", "postgres", "redis"):
        assert f"{dependency}:" in block
    assert "healthcheck:" in block


def test_ollama_url_defaults_to_the_host_install(text: str) -> None:
    assert "OLLAMA_URL: ${OLLAMA_URL:-http://host.docker.internal:11434}" in text


def test_the_payment_worker_has_no_model_settings(text: str) -> None:
    assert "app.explain" not in service(text, "worker")
