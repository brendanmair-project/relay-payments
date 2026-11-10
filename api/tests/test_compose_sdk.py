"""REL-41: the compose `sdk` service runs the SDK checks under its own profile, with no ports or secrets."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
API_DOCKERFILE = ROOT / "api" / "Dockerfile"
SDK_DOCKERFILE = ROOT / "sdk" / "python" / "Dockerfile"


@pytest.fixture
def block() -> str:
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml is not part of the api image")
    text = "\n".join(
        line for line in COMPOSE.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
    )
    match = re.search(r"^  sdk:\n(.*?)(?=^  \S|^\S|\Z)", text + "\n", re.S | re.M)
    assert match, "service sdk missing"
    return match.group(1)


def test_sdk_is_profile_only_and_built_from_the_sdk_directory(block: str) -> None:
    assert re.search(r'^    profiles: \["sdk"\]$', block, re.M)
    assert re.search(r"^    build: \./sdk/python$", block, re.M)
    assert re.search(r"^    logging: \*default-logging$", block, re.M)


def test_sdk_has_no_ports_secrets_environment_or_dependencies(block: str) -> None:
    for key in ("ports", "environment", "env_file", "depends_on", "volumes"):
        assert not re.search(rf"^    {key}:", block, re.M), key


def test_sdk_does_not_restart_and_default_services_do_not_wait_for_it() -> None:
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml is not part of the api image")
    text = COMPOSE.read_text(encoding="utf-8")
    assert not re.search(r"^      sdk:$", text, re.M)


def test_sdk_dockerfile_uses_the_same_pinned_python_image_as_the_api() -> None:
    if not (SDK_DOCKERFILE.exists() and API_DOCKERFILE.exists()):
        pytest.skip("sdk/ and api/Dockerfile are not part of the api image")
    api_from = re.search(r"^FROM (\S+)", API_DOCKERFILE.read_text(encoding="utf-8"), re.M)
    sdk_from = re.search(r"^FROM (\S+)", SDK_DOCKERFILE.read_text(encoding="utf-8"), re.M)
    assert api_from and sdk_from and sdk_from.group(1) == api_from.group(1)
    assert re.fullmatch(r"python:\d+\.\d+\.\d+-slim", sdk_from.group(1))
    assert "ruff check . && ruff format --check . && mypy src && pytest" in SDK_DOCKERFILE.read_text(encoding="utf-8")


def test_ci_runs_the_four_sdk_commands_in_a_path_filtered_job() -> None:
    if not CI.exists():
        pytest.skip(".github/ is not part of the api image")
    text = CI.read_text(encoding="utf-8")
    assert re.search(r"^      sdk: \$\{\{ steps\.diff\.outputs\.sdk \}\}$", text, re.M)
    assert re.search(r"flag sdk '\^\(sdk/", text)
    job = re.search(r"^  sdk:\n(.*?)(?=^  \S|\Z)", text, re.S | re.M)
    assert job, "ci.yml has no sdk job"
    body = job.group(1)
    assert "needs.changes.outputs.sdk == 'true'" in body
    assert re.search(r"^    timeout-minutes: \d+$", body, re.M)
    assert "working-directory: sdk/python" in body
    for command in ("ruff check .", "ruff format --check .", "mypy src", "pytest"):
        assert re.search(rf"^      - run: {re.escape(command)}$", body, re.M), command
