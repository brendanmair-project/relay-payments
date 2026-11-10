"""REL-37: compose mounts the REL-30 results file read-only into the api and passes its path as a setting."""

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


def test_the_api_mounts_the_results_file_read_only(text: str) -> None:
    block = service(text, "api")
    assert "- ./docs/evaluation/outage-demo/results.json:/app/baseline/results.json:ro" in block


def test_the_api_receives_the_baseline_path_with_a_default(text: str) -> None:
    block = service(text, "api")
    assert "BASELINE_RESULTS_PATH: ${BASELINE_RESULTS_PATH:-/app/baseline/results.json}" in block


def test_no_other_service_gets_the_baseline_variable_or_mount(text: str) -> None:
    for name in ("worker", "publisher", "explainer", "incidents", "frontend", "simulator"):
        assert "BASELINE_RESULTS_PATH" not in service(text, name), name
        assert "outage-demo" not in service(text, name), name


def test_the_results_file_exists_in_the_repository() -> None:
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml is not part of the api image")
    assert (COMPOSE.parent / "docs" / "evaluation" / "outage-demo" / "results.json").is_file()
