"""REL-58: `scripts/smoke_stack.py` checks every long-running service of the default compose profile.

The script lists the services by hand (standard library only, and `docker compose config` needs the daemon), so this
test compares that tuple with `docker-compose.yml`: every service with no `profiles:` and a `restart` policy other than
`"no"` must be in it, and nothing else may be.
"""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
SMOKE = ROOT / "scripts" / "smoke_stack.py"
SERVICE = r"^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|^\S|\Z)"


def smoke_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_stack_under_test", SMOKE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compose_services() -> dict[str, str]:
    text = "\n".join(
        line for line in COMPOSE.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")
    )
    section = re.search(r"^services:\n(.*?)(?=^\S|\Z)", text, re.S | re.M)
    assert section, "no services section"
    return {m.group(1): m.group(2) for m in re.finditer(SERVICE, section.group(1), re.S | re.M)}


def default_long_running_services() -> set[str]:
    names: set[str] = set()
    for name, block in compose_services().items():
        restart = re.search(r"^    restart: (\S+)$", block, re.M)
        if re.search(r"^    profiles:", block, re.M) or not restart or restart.group(1).strip("\"'") == "no":
            continue
        names.add(name)
    return names


@pytest.fixture
def smoke() -> ModuleType:
    if not (COMPOSE.exists() and SMOKE.exists()):
        pytest.skip("docker-compose.yml and scripts/ are not part of the api image")
    return smoke_module()


def test_the_smoke_script_checks_every_default_long_running_service(smoke: ModuleType) -> None:
    expected = default_long_running_services()
    assert {"publisher", "explainer", "incidents", "webhooks"} <= expected
    assert set(smoke.HEALTHY_SERVICES) == expected
    assert len(smoke.HEALTHY_SERVICES) == len(set(smoke.HEALTHY_SERVICES))


def test_every_checked_service_has_a_healthcheck_in_compose(smoke: ModuleType) -> None:
    services = compose_services()
    for name in smoke.HEALTHY_SERVICES:
        assert re.search(r"^    healthcheck:", services[name], re.M), name
