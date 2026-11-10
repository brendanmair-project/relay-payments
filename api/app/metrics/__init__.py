"""Prometheus metrics of the api, worker and publisher (REL-33, ADR-0006; spec: dashboard-spec-observability.md).

One module defines every metric so the three processes and the dashboards agree on names. Labels are low-cardinality
(route templates, processor, operation, outcome): never a payment id, reference or key. Each process serves its own
registry on its own port inside the compose network only (`start_metrics_server`); metrics are never served on the keyed
public API.
"""

import os

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Seconds. Request buckets cover the API's millisecond answers; processor buckets reach the 5 s processor timeout.
REQUEST_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
PROCESSOR_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0)
LAG_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
# Creation to final spans processor calls, retries and the sweeper timeout (10 s by default): buckets reach 2 minutes.
PROCESSING_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0)

# Counter objects expose `<name>_total`.
PAYMENTS_CREATED = Counter("relay_payments_created", "Payments created by POST /payments (replays excluded)")
HTTP_REQUESTS = Counter("relay_http_requests", "API requests", ["method", "route", "status"])
HTTP_DURATION = Histogram(
    "relay_http_request_duration_seconds", "API request duration", ["route"], buckets=REQUEST_BUCKETS
)
PROCESSOR_CALLS = Counter(
    "relay_processor_calls",
    "Processor calls by outcome (approved, declined, captured, failed, timeout, outage)",
    ["processor", "operation", "outcome"],
)
PROCESSOR_DURATION = Histogram(
    "relay_processor_call_duration_seconds",
    "Processor call duration",
    ["processor", "operation"],
    buckets=PROCESSOR_BUCKETS,
)
PAYMENTS_FINAL = Counter(
    "relay_payments_final", "Payments that reached a final state (captured, declined, failed)", ["processor", "outcome"]
)
EVENTS_PUBLISHED = Counter("relay_outbox_events_published", "Outbox events copied to the stream")
PUBLISH_LAG = Histogram(
    "relay_outbox_publish_lag_seconds",
    "Seconds from event creation to stream publish",
    buckets=LAG_BUCKETS,
)
INCIDENTS_OPENED = Counter(
    "relay_incidents_opened", "Incidents opened, by processor and source (rule or manual)", ["processor", "source"]
)
WEBHOOK_DELIVERIES = Counter(
    "relay_webhook_deliveries", "Webhook delivery attempts by outcome (delivered, retried, failed)", ["outcome"]
)
WEBHOOK_PENDING = Gauge(
    "relay_webhook_pending", "Webhook deliveries waiting to be sent; set by the webhooks container only (REL-39)"
)

PAYMENT_PROCESSING = Histogram(
    "relay_payment_processing_seconds",
    "Seconds from payment creation to its final state (REL-57)",
    ["processor", "outcome"],
    buckets=PROCESSING_BUCKETS,
)
PAYMENTS_NOT_FINAL_OVERDUE = Gauge(
    "relay_payments_not_final_overdue",
    "Payments not final whose last state change is older than the sweeper timeout threshold; set each sweeper pass",
)
STREAM_GROUP_LAG = Gauge(
    "relay_stream_group_lag", "Stream entries not yet delivered to the consumer group (XINFO GROUPS lag)", ["group"]
)
STREAM_GROUP_PENDING = Gauge(
    "relay_stream_group_pending", "Stream entries delivered to the consumer group but not acknowledged", ["group"]
)

PROCESSORS = ("A", "B")
STREAM_GROUPS = (
    "processing",
    "explanations",
    "incidents",
    "webhooks",
)  # series start at zero; the publisher reads the real list
INCIDENT_SOURCES = ("rule", "manual")
CALL_OUTCOMES = {
    "authorize": ("approved", "declined", "timeout", "outage"),
    "capture": ("captured", "failed", "timeout", "outage"),
}
FINAL_OUTCOMES = ("captured", "declined", "failed")
WEBHOOK_OUTCOMES = ("delivered", "retried", "failed")


def _initialise_known_series() -> None:
    # Create every known label combination at zero. Prometheus rate() sees no increase when a series first appears
    # already above zero, so a burst that creates a new label value between two scrapes (for example ten outage errors
    # in a few seconds) would otherwise never show on a dashboard.
    for processor in PROCESSORS:
        for operation, outcomes in CALL_OUTCOMES.items():
            for outcome in outcomes:
                PROCESSOR_CALLS.labels(processor, operation, outcome)
        for outcome in FINAL_OUTCOMES:
            PAYMENTS_FINAL.labels(processor, outcome)
            PAYMENT_PROCESSING.labels(processor, outcome)
        for source in INCIDENT_SOURCES:
            INCIDENTS_OPENED.labels(processor, source)
    for group in STREAM_GROUPS:
        STREAM_GROUP_LAG.labels(group).set(0)
        STREAM_GROUP_PENDING.labels(group).set(0)
    for outcome in WEBHOOK_OUTCOMES:
        WEBHOOK_DELIVERIES.labels(outcome)
    WEBHOOK_PENDING.set(0)


_initialise_known_series()


def start_metrics_server(port: int) -> int:
    """Serve this process's registry on `port` (0 picks a free port) and return the bound port."""
    server, _thread = start_http_server(port)
    return int(server.server_port)


def start_metrics_server_from_env() -> int | None:
    """Start the server when METRICS_PORT is set (compose sets 9100); tests and bare runs leave it off."""
    port = os.environ.get("METRICS_PORT")
    return start_metrics_server(int(port)) if port else None
