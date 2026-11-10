"""REL-48: the compose file as a whole (skipped inside the image, where docker-compose.yml is absent).

The file is parsed by indentation because PyYAML is not an api dependency (new libraries need an ADR).
"""

import re
from pathlib import Path

import pytest

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"

LONG_RUNNING = (
    "postgres",
    "redis",
    "api",
    "publisher",
    "worker",
    "explainer",
    "incidents",
    "webhooks",
    "simulator",
    "frontend",
)
OLLAMA_TAG = re.compile(r"^ollama/ollama:\d+\.\d+\.\d+$")
OBSERVABILITY = {"prometheus": "prom/prometheus:v3.15.1", "grafana": "grafana/grafana:13.3.0"}  # ADR-0006

ROUTING = {"ROUTING_STRATEGY", "HEALTH_WINDOW_SECONDS", "HEALTH_MIN_ATTEMPTS", "HEALTH_ERROR_THRESHOLD"}
SWEEP = {
    "PROCESSOR_TIMEOUT_SECONDS",
    "SWEEP_TIMEOUT_GRACE_SECONDS",
    "REDRIVE_AFTER_SECONDS",
    "SWEEP_INTERVAL_SECONDS",
    "KEY_CLEANUP_INTERVAL_SECONDS",
}
API_SETTINGS = {
    "RELAY_API_KEY",
    "DATABASE_URL",
    "REDIS_URL",
    "REQUEST_LOG_PATH",
    "BASELINE_RESULTS_PATH",
    "IDEMPOTENCY_TTL_HOURS",
    "IDEMPOTENCY_LEASE_SECONDS",
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "EXPLAIN_TIMEOUT_SECONDS",
}
WEBHOOKS = {
    "WEBHOOK_ALLOWED_HOSTS",
    "WEBHOOK_BACKOFF_BASE_SECONDS",
    "WEBHOOK_BACKOFF_FACTOR",
    "WEBHOOK_BACKOFF_MAX_SECONDS",
    "WEBHOOK_LOG_RETENTION_DAYS",
    "WEBHOOK_TIMEOUT_SECONDS",
}
# What each service's code reads (app/config.py, app/routing/config.py, app/worker/__main__.py, app/worker/sweeper.py,
# app/publisher.py, app/explainer/__main__.py, app/incidents/__main__.py, app/webhooks/__main__.py,
# app/webhooks/sink.py, app/reporting/__main__.py, migrations/env.py, simulator/app/apps.py,
# frontend/app/lib/upstream.ts). A variable outside a service's set must not be passed to it (ADR-0012).
READS: dict[str, set[str]] = {
    "api": API_SETTINGS | ROUTING | {"METRICS_PORT", "BASELINE_RESULTS_PATH", "WEBHOOK_ALLOWED_HOSTS"},
    "worker": {"DATABASE_URL", "REDIS_URL", "SIMULATOR_URL", "RECLAIM_IDLE_MS", "WORKER_HEARTBEAT_PATH", "METRICS_PORT"}
    | SWEEP
    | ROUTING,
    "publisher": {"DATABASE_URL", "REDIS_URL", "PUBLISHER_HEARTBEAT_PATH", "STREAM_MAXLEN", "METRICS_PORT"},
    "explainer": API_SETTINGS | {"EXPLAINER_HEARTBEAT_PATH"},
    "incidents": {"DATABASE_URL", "REDIS_URL", "INCIDENTS_HEARTBEAT_PATH", "METRICS_PORT"},
    "webhooks": {"DATABASE_URL", "REDIS_URL", "WEBHOOKS_HEARTBEAT_PATH", "METRICS_PORT"} | WEBHOOKS,
    "webhook-sink": {"WEBHOOK_SINK_SECRET"},
    "migrate": {"DATABASE_URL"},
    "reporting": {"DATABASE_URL", "REQUEST_LOG_PATH"} | SWEEP,
    "simulator": {"RELAY_API_KEY", "SIM_SEED", "PROCESSOR_TIMEOUT_SECONDS"},
    "frontend": {"RELAY_API_KEY", "API_URL", "SIMULATOR_CONTROL_URL"},
}


@pytest.fixture
def text() -> str:
    if not COMPOSE.exists():
        pytest.skip("docker-compose.yml is not part of the api image")
    return COMPOSE.read_text(encoding="utf-8")


def code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def service(text: str, name: str) -> str:
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|^\S|\Z)", "\n".join(code_lines(text)) + "\n", re.S | re.M)
    assert match, f"service {name} missing"
    return match.group(1)


def environment(block: str) -> dict[str, str]:
    """The `environment:` mapping of one service block (keys at six spaces, under `environment:` at four)."""
    match = re.search(r"^    environment:\n((?:      .*\n)+)", block, re.M)
    if not match:
        return {}
    return dict(re.findall(r"^      (\w+):\s*(.*)$", match.group(1), re.M))


def ports(block: str) -> list[str]:
    """The host port mappings of one service block (the list under `ports:` at four spaces)."""
    match = re.search(r"^    ports:\n((?:      - .*\n)+)", block, re.M)
    return re.findall(r'^      - "([^"]+)"$', match.group(1), re.M) if match else []


def test_no_service_or_anchor_loads_the_whole_env_file(text: str) -> None:
    assert not [line for line in code_lines(text) if "env_file" in line]


@pytest.mark.parametrize("name", LONG_RUNNING)
def test_long_running_services_have_a_health_check(text: str, name: str) -> None:
    assert re.search(r"^    healthcheck:$", service(text, name), re.M)


@pytest.mark.parametrize("name", LONG_RUNNING)
def test_long_running_services_declare_their_own_restart_policy(text: str, name: str) -> None:
    assert re.search(r"^    restart: unless-stopped$", service(text, name), re.M)


def test_the_stop_grace_period_covers_the_entry_in_hand_for_every_consumer(text: str) -> None:
    for name in ("worker", "explainer", "incidents", "webhooks", "publisher"):
        assert re.search(r"^    stop_grace_period: \d+s$", service(text, name), re.M), name


def test_ollama_is_profile_only_without_ports_and_pinned_exactly(text: str) -> None:
    block = service(text, "ollama")
    assert re.search(r'^    profiles: \["llm"\]$', block, re.M)
    assert not re.search(r"^    ports:", block, re.M)
    image = re.search(r"^    image: (\S+)$", block, re.M)
    assert image and OLLAMA_TAG.match(image.group(1)), image
    assert re.search(r"^    restart: unless-stopped$", block, re.M)
    assert re.search(r"^    healthcheck:$", block, re.M)
    assert re.search(r"^    volumes:\n      - ollama-models:", block, re.M)
    assert re.search(r"^  ollama-models:", text, re.M)


def test_no_default_service_waits_for_the_llm_profile(text: str) -> None:
    for name in LONG_RUNNING:
        assert not re.search(r"^      ollama:$", service(text, name), re.M), name


def test_the_api_key_is_required_wherever_it_is_passed(text: str) -> None:
    for name in ("api", "explainer", "simulator", "frontend"):
        value = environment(service(text, name)).get("RELAY_API_KEY", "")
        assert value.startswith("${RELAY_API_KEY:?"), name


@pytest.mark.parametrize("name", sorted(READS))
def test_each_service_receives_only_variables_its_code_reads(text: str, name: str) -> None:
    passed = set(environment(service(text, name)))
    assert passed, f"{name} has no environment"
    assert passed <= READS[name], f"{name} gets variables its code does not read: {sorted(passed - READS[name])}"


@pytest.mark.parametrize(
    ("name", "required"),
    [
        ("api", {"RELAY_API_KEY", "DATABASE_URL", "REDIS_URL", "METRICS_PORT"}),
        ("worker", {"DATABASE_URL", "REDIS_URL", "SIMULATOR_URL", "METRICS_PORT"}),
        ("publisher", {"DATABASE_URL", "REDIS_URL", "METRICS_PORT"}),
        ("explainer", {"RELAY_API_KEY", "DATABASE_URL", "REDIS_URL", "OLLAMA_URL"}),
        ("incidents", {"DATABASE_URL", "REDIS_URL", "METRICS_PORT"}),
        ("webhooks", {"DATABASE_URL", "REDIS_URL", "METRICS_PORT"} | WEBHOOKS),
        ("migrate", {"DATABASE_URL"}),
        ("simulator", {"RELAY_API_KEY"}),
        ("frontend", {"RELAY_API_KEY", "API_URL", "SIMULATOR_CONTROL_URL"}),
    ],
)
def test_each_service_receives_the_variables_it_cannot_run_without(text: str, name: str, required: set[str]) -> None:
    assert required <= set(environment(service(text, name)))


def test_variables_use_compose_interpolation_with_a_default(text: str) -> None:
    for name in READS:
        for key, value in environment(service(text, name)).items():
            assert value.startswith(f"${{{key}:-") or value.startswith(f"${{{key}:?"), (name, key, value)


def test_redis_persists_with_append_only(text: str) -> None:
    assert '"--appendonly", "yes"' in service(text, "redis")


def test_migrate_completes_before_api_worker_and_publisher_start(text: str) -> None:
    gate = r"^      migrate:\n        condition: service_completed_successfully$"
    for name in ("api", "worker", "publisher", "explainer", "incidents", "webhooks"):
        assert re.search(gate, service(text, name), re.M), name


def test_containers_reach_the_host_ollama_through_the_host_gateway(text: str) -> None:
    for name in ("api", "explainer"):
        assert "host.docker.internal:host-gateway" in service(text, name)


@pytest.mark.parametrize("name", sorted(OBSERVABILITY))
def test_observability_services_are_profile_only_pinned_and_supervised(text: str, name: str) -> None:
    block = service(text, name)
    assert re.search(r'^    profiles: \["observability"\]$', block, re.M)
    assert re.search(rf"^    image: {re.escape(OBSERVABILITY[name])}$", block, re.M)
    assert re.search(r"^    restart: unless-stopped$", block, re.M)
    assert re.search(r"^    healthcheck:$", block, re.M)
    assert re.search(r"^    logging: \*default-logging$", block, re.M)


@pytest.mark.parametrize(
    ("name", "mapping"),
    [
        ("prometheus", "127.0.0.1:${PROMETHEUS_HOST_PORT:-9090}:9090"),
        ("grafana", "127.0.0.1:${GRAFANA_HOST_PORT:-3001}:3000"),  # the frontend owns 3000
    ],
)
def test_observability_host_ports_are_loopback_only_and_configurable(text: str, name: str, mapping: str) -> None:
    assert ports(service(text, name)) == [mapping]


def test_observability_services_load_no_env_file_and_name_only_their_own_variables(text: str) -> None:
    assert not environment(service(text, "prometheus"))
    grafana = environment(service(text, "grafana"))
    assert grafana and all(key.startswith("GF_") for key in grafana), sorted(grafana)
    assert grafana["GF_AUTH_ANONYMOUS_ENABLED"] == "true"
    assert grafana["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"
    assert grafana["GF_SECURITY_DISABLE_INITIAL_ADMIN_CREATION"] == "true"
    assert not [key for key in grafana if "PASSWORD" in key or "SECRET" in key]


def test_observability_data_and_provisioning_mounts(text: str) -> None:
    prometheus, grafana = service(text, "prometheus"), service(text, "grafana")
    assert "--storage.tsdb.retention.time=7d" in prometheus
    assert "--config.file=/etc/prometheus/prometheus.yml" in prometheus
    assert "- ./observability/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro" in prometheus
    assert "- prometheus-data:/prometheus" in prometheus
    assert "- ./observability/grafana/provisioning:/etc/grafana/provisioning:ro" in grafana
    assert "- ./observability/grafana/dashboards:/var/lib/grafana/dashboards:ro" in grafana
    assert "- grafana-data:/var/lib/grafana" in grafana
    for volume in ("prometheus-data", "grafana-data"):
        assert re.search(rf"^  {volume}:", text, re.M)


def test_no_default_service_waits_for_the_observability_profile(text: str) -> None:
    for name in LONG_RUNNING:
        block = service(text, name)
        assert not re.search(r"^      (prometheus|grafana):$", block, re.M), name


def test_metrics_ports_are_not_published_on_the_host(text: str) -> None:
    """The api serves metrics on 9100 inside the compose network only; worker and publisher publish nothing."""
    assert ports(service(text, "api")) == ["127.0.0.1:${API_HOST_PORT:-8000}:8000"]
    for name in ("worker", "publisher", "webhooks"):
        assert not ports(service(text, name)), name
    for name in ("api", "worker", "publisher", "webhooks"):
        assert environment(service(text, name))["METRICS_PORT"] == "${METRICS_PORT:-9100}", name
