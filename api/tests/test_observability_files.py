"""REL-33: the scrape config, the Grafana provisioning and the dashboards are files that parse and match the metrics.

Skipped inside the image, where `observability/` is absent. The scrape config is read by indentation because PyYAML is
not an api dependency (new libraries need an ADR); the dashboards are JSON.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
OBS = ROOT / "observability"
DASHBOARDS = OBS / "grafana" / "dashboards"
METRICS_SOURCE = Path(__file__).resolve().parents[1] / "app" / "metrics" / "__init__.py"

EXPECTED_DASHBOARDS = {"throughput", "success-rate", "latency", "processor-errors"}
SCRAPED = {
    "relay-api": "api:9100",
    "relay-worker": "worker:9100",
    "relay-publisher": "publisher:9100",
    "relay-incidents": "incidents:9100",
    "relay-webhooks": "webhooks:9100",
}


@pytest.fixture(autouse=True)
def observability_present() -> None:
    if not OBS.exists():
        pytest.skip("observability/ is not part of the api image")


def defined_metric_names() -> set[str]:
    """Every series name the metrics module can expose: base, counter total, histogram bucket, sum and count."""
    base = set(re.findall(r'"(relay_[a-z_]+)"', METRICS_SOURCE.read_text(encoding="utf-8")))
    assert base, "no metric names found in app/metrics"
    return {f"{n}{suffix}" for n in base for suffix in ("", "_total", "_bucket", "_sum", "_count")}


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DASHBOARDS / f"{name}.json").read_text(encoding="utf-8"))
    return data


def panels(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in dashboard["panels"] if p["type"] != "row"]


def queries(dashboard: dict[str, Any]) -> list[str]:
    return [t["expr"] for p in panels(dashboard) for t in p["targets"]]


def test_scrape_config_scrapes_the_three_processes_on_the_compose_network() -> None:
    text = (OBS / "prometheus" / "prometheus.yml").read_text(encoding="utf-8")
    jobs = dict(re.findall(r'^  - job_name: "?([\w-]+)"?\n(?:    .*\n)*?      - targets: \["([^"]+)"\]', text, re.M))
    assert jobs == SCRAPED
    assert not re.search(r"X-API-Key|authorization|password|bearer", text, re.I), "no key belongs in the scrape config"
    assert re.search(r"^  scrape_interval: \d+s$", text, re.M)


def test_grafana_provisions_the_prometheus_data_source_and_the_dashboard_folder() -> None:
    source = (OBS / "grafana" / "provisioning" / "datasources" / "prometheus.yml").read_text(encoding="utf-8")
    assert "uid: prometheus" in source
    assert "url: http://prometheus:9090" in source
    assert "isDefault: true" in source
    provider = (OBS / "grafana" / "provisioning" / "dashboards" / "dashboards.yml").read_text(encoding="utf-8")
    assert "path: /var/lib/grafana/dashboards" in provider
    assert not re.search(r"password|secret|token", source + provider, re.I)


def test_the_four_dashboards_exist() -> None:
    assert {p.stem for p in DASHBOARDS.glob("*.json")} == EXPECTED_DASHBOARDS


@pytest.mark.parametrize("name", sorted(EXPECTED_DASHBOARDS))
def test_each_dashboard_is_valid_json_with_identity_and_panels(name: str) -> None:
    dashboard = load(name)
    assert dashboard["uid"] == f"relay-{name}"
    assert dashboard["title"].startswith("Relay")
    assert dashboard["schemaVersion"] >= 39
    assert len(panels(dashboard)) >= 2


@pytest.mark.parametrize("name", sorted(EXPECTED_DASHBOARDS))
def test_every_panel_has_a_datasource_a_unit_a_description_and_a_query(name: str) -> None:
    for panel in panels(load(name)):
        title = panel["title"]
        assert panel["datasource"] == {"type": "prometheus", "uid": "prometheus"}, title
        assert panel["description"], title
        assert panel["fieldConfig"]["defaults"]["unit"], title
        assert panel["targets"], title
        for target in panel["targets"]:
            assert target["expr"].strip(), title
            assert target["datasource"] == panel["datasource"], title


@pytest.mark.parametrize("name", sorted(EXPECTED_DASHBOARDS))
def test_every_metric_a_dashboard_queries_is_defined_in_the_metrics_module(name: str) -> None:
    defined = defined_metric_names()
    used = {m for expr in queries(load(name)) for m in re.findall(r"\brelay_[a-z_]+", expr)}
    assert used, name
    assert used <= defined, sorted(used - defined)


def test_dashboards_cover_percentiles_5xx_rate_and_publish_lag() -> None:
    by_name = {name: " ".join(queries(load(name))) for name in EXPECTED_DASHBOARDS}
    for quantile in ("0.5", "0.95", "0.99"):
        assert f"histogram_quantile({quantile}," in by_name["latency"]
    assert "relay_http_request_duration_seconds_bucket" in by_name["latency"]
    assert "relay_processor_call_duration_seconds_bucket" in by_name["latency"]
    assert 'status=~"5.."' in by_name["throughput"]
    assert "relay_outbox_publish_lag_seconds_bucket" in by_name["throughput"]
    assert "relay_payments_created_total" in by_name["throughput"]
    assert "relay_payments_final_total" in by_name["success-rate"]
    assert 'outcome=~"timeout|outage"' in by_name["processor-errors"]


def test_the_dashboard_spec_names_every_panel_title() -> None:
    spec = (ROOT / "docs" / "architecture" / "dashboard-spec-observability.md").read_text(encoding="utf-8")
    for name in EXPECTED_DASHBOARDS:
        for panel in panels(load(name)):
            assert panel["title"] in spec, panel["title"]


def test_rel57_guardrail_panels_exist_and_their_metrics_are_defined_in_the_metrics_module() -> None:
    defined = defined_metric_names()
    by_name = {name: " ".join(queries(load(name))) for name in EXPECTED_DASHBOARDS}
    for quantile in ("0.5", "0.95", "0.99"):
        assert re.search(
            rf"histogram_quantile\({quantile}, sum by \(le, processor\) "
            r"\(rate\(relay_payment_processing_seconds_bucket",
            by_name["latency"],
        ), quantile
    assert "relay_payments_not_final_overdue" in by_name["success-rate"]
    assert "relay_stream_group_lag" in by_name["throughput"]
    assert "relay_stream_group_pending" in by_name["throughput"]
    for metric in (
        "relay_payment_processing_seconds_bucket",
        "relay_payments_not_final_overdue",
        "relay_stream_group_lag",
        "relay_stream_group_pending",
    ):
        assert metric in defined, metric


def test_rel57_panels_are_named_in_the_spec_with_their_legend_and_no_double_braces() -> None:
    spec = (ROOT / "docs" / "architecture" / "dashboard-spec-observability.md").read_text(encoding="utf-8")
    for title in (
        "Payment creation-to-final latency P50/P95/P99 by processor",
        "Payments not final past the sweeper threshold",
        "Stream lag and pending by consumer group",
    ):
        assert title in spec, title
    assert "{{" not in spec, "the template validator reads double braces as placeholders: write 'legend: processor'"


def test_the_success_rate_panel_is_captured_over_all_final_payments() -> None:
    # REL-57: one definition (docs/product/metrics.md): numerator captured, denominator every final outcome (declines
    # included), so the denominator must carry no outcome filter.
    panel = next(p for p in panels(load("success-rate")) if p["title"] == "Success rate by processor")
    expr = panel["targets"][0]["expr"]
    numerator, denominator = expr.split(" / ")
    assert 'outcome="captured"' in numerator
    assert "outcome" not in denominator


def test_single_owner_gauges_are_read_only_from_their_owning_process() -> None:
    # Every process imports app.metrics, so every process exports these gauges at zero; only one process sets them.
    # Without a job filter, a dead owner would still show 0 from the others, which reads as healthy.
    owners = {
        "relay_stream_group_lag": 'job="relay-publisher"',
        "relay_stream_group_pending": 'job="relay-publisher"',
        "relay_payments_not_final_overdue": 'job="relay-worker"',
        "relay_webhook_pending": 'job="relay-webhooks"',
    }
    queries = [t["expr"] for name in EXPECTED_DASHBOARDS for p in panels(load(name)) for t in p.get("targets", [])]
    for metric, selector in owners.items():
        using = [q for q in queries if metric in q]
        assert using, metric
        for query in using:
            assert selector in query, (metric, query)


def test_rel39_webhook_panels_exist_use_the_owning_job_and_are_named_in_the_spec() -> None:
    throughput = load("throughput")
    by_title = {p["title"]: [t["expr"] for t in p["targets"]] for p in panels(throughput)}
    rate = by_title["Webhook deliveries per second by outcome"]
    assert rate == ["sum by (outcome) (rate(relay_webhook_deliveries_total[1m]))"]
    waiting = by_title["Webhook deliveries waiting to be sent"]
    assert waiting == ['max(relay_webhook_pending{job="relay-webhooks"})']
    spec = (ROOT / "docs" / "architecture" / "dashboard-spec-observability.md").read_text(encoding="utf-8")
    for title in by_title:
        assert title in spec, title
    defined = defined_metric_names()
    assert {"relay_webhook_deliveries_total", "relay_webhook_pending"} <= defined
