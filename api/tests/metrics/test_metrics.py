"""REL-33: each metric moves when its code path runs (default registry; values are read as deltas)."""

import urllib.request
import uuid
from collections.abc import Callable
from datetime import timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app import metrics
from app.domain.lifecycle import Event, PaymentState
from app.outbox.publisher import publish_batch
from app.services.transitions import apply_transition, create_payment
from app.worker.consumer import Consumer
from app.worker.sweeper import SweepConfig, sweep
from tests.worker.conftest import CAPTURE_FAILED, DECLINED, OUTAGE, TIMEOUT, FakeProcessor, trigger

Factory = sessionmaker[Session]
Watch = Callable[..., Callable[[], float]]


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def delta() -> Watch:
    """`delta(name, **labels)` returns a function giving how much the sample grew since the call."""

    def watch(name: str, **labels: str) -> Callable[[], float]:
        before = value(name, **labels)
        return lambda: value(name, **labels) - before

    return watch


@pytest.fixture(autouse=True)
def static_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "static")  # processor A, no retry: one attempt per payment


def run_worker(factory: Factory, redis_client: Redis, fake: FakeProcessor, pid: uuid.UUID) -> None:
    consumer = Consumer(factory, redis_client, fake.client, "c1", reclaim_idle_ms=30000)
    consumer.ensure_group()
    trigger(redis_client, pid)
    consumer.run_once()


def test_api_counts_and_times_every_request_by_route_template(client: TestClient, api_key: str, delta: Watch) -> None:
    ok = delta("relay_http_requests_total", method="GET", route="/health", status="200")
    timed = delta("relay_http_request_duration_seconds_count", route="/health")
    client.get("/health", headers={"X-API-Key": api_key})
    assert ok() == 1
    assert timed() == 1


def test_api_counts_a_rejected_key_and_labels_unknown_paths_without_the_raw_path(
    client: TestClient, api_key: str, delta: Watch
) -> None:
    # The key check runs before routing, so a rejected request has no route template either.
    rejected = delta("relay_http_requests_total", method="GET", route="<unmatched>", status="401")
    unknown = delta("relay_http_requests_total", method="GET", route="<unmatched>", status="404")
    client.get("/health", headers={"X-API-Key": "wrong"})
    client.get("/no-such-path-0123", headers={"X-API-Key": api_key})
    assert rejected() == 1
    assert unknown() == 1
    labels = [label for family in REGISTRY.collect() for s in family.samples for label in s.labels.values()]
    assert not any("no-such-path-0123" in label for label in labels)


def test_api_counts_a_server_error_as_5xx(
    client: TestClient, api_key: str, delta: Watch, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> bool:
        raise RuntimeError("database down")

    monkeypatch.setattr("app.main._database_ok", boom)
    failed = delta("relay_http_requests_total", method="GET", route="/health", status="500")
    client.get("/health", headers={"X-API-Key": api_key})
    assert failed() == 1


def test_a_created_payment_is_counted_once_and_a_replay_is_not(client: TestClient, api_key: str, delta: Watch) -> None:
    created = delta("relay_payments_created_total")
    headers = {"X-API-Key": api_key, "Idempotency-Key": "metrics-test-1"}
    body = {"amount_minor": 1200, "currency": "USD", "reference": "metrics-ref-1"}
    assert client.post("/payments", json=body, headers=headers).status_code == 201
    assert client.post("/payments", json=body, headers=headers).headers["Idempotent-Replayed"] == "true"
    assert created() == 1


def test_a_captured_payment_counts_both_calls_and_one_final(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID, delta: Watch
) -> None:
    authorized = delta("relay_processor_calls_total", processor="A", operation="authorize", outcome="approved")
    captured = delta("relay_processor_calls_total", processor="A", operation="capture", outcome="captured")
    seconds = delta("relay_processor_call_duration_seconds_sum", processor="A", operation="authorize")
    final = delta("relay_payments_final_total", processor="A", outcome="captured")
    run_worker(factory, redis_client, FakeProcessor(), payment_id)
    assert (authorized(), captured(), final()) == (1, 1, 1)
    assert seconds() == pytest.approx(0.12)  # the simulated processor reported 120 ms


def test_a_decline_is_a_call_outcome_and_a_final_outcome(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID, delta: Watch
) -> None:
    declined = delta("relay_processor_calls_total", processor="A", operation="authorize", outcome="declined")
    final = delta("relay_payments_final_total", processor="A", outcome="declined")
    run_worker(factory, redis_client, FakeProcessor(authorize=DECLINED), payment_id)
    assert (declined(), final()) == (1, 1)


@pytest.mark.parametrize(("answer", "outcome"), [(TIMEOUT, "timeout"), (OUTAGE, "outage")])
def test_timeouts_and_outages_are_counted_per_processor_and_end_the_payment_failed(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID, delta: Watch, answer: object, outcome: str
) -> None:
    errors = delta("relay_processor_calls_total", processor="A", operation="authorize", outcome=outcome)
    final = delta("relay_payments_final_total", processor="A", outcome="failed")
    run_worker(factory, redis_client, FakeProcessor(authorize=answer), payment_id)
    assert (errors(), final()) == (1, 1)


def test_a_failed_capture_is_counted_as_a_failed_call(
    factory: Factory, redis_client: Redis, payment_id: uuid.UUID, delta: Watch
) -> None:
    failed = delta("relay_processor_calls_total", processor="A", operation="capture", outcome="failed")
    run_worker(factory, redis_client, FakeProcessor(capture=CAPTURE_FAILED), payment_id)
    assert failed() == 1


def test_publishing_counts_events_and_records_their_age(factory: Factory, redis_client: Redis, delta: Watch) -> None:
    published = delta("relay_outbox_events_published_total")
    observed = delta("relay_outbox_publish_lag_seconds_count")
    with factory.begin() as session:
        for index in range(3):
            create_payment(session, amount_minor=100, currency="USD", reference=f"lag-{index}")
    assert publish_batch(factory, redis_client) == 3
    assert published() == 3
    assert observed() == 3
    assert value("relay_outbox_publish_lag_seconds_sum") >= 0


def test_the_metrics_server_serves_the_registry_without_a_key() -> None:
    port = metrics.start_metrics_server(0)
    assert port > 0
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=3) as response:  # noqa: S310
        text = response.read().decode()
    assert response.status == 200
    assert "relay_http_requests_total" in text
    assert "relay_outbox_publish_lag_seconds" in text


def test_a_payment_the_sweeper_fails_for_good_counts_as_a_final_failure(
    factory: Factory, payment_id: uuid.UUID, delta: Watch, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "static")  # no retry: the timeout is final
    with factory.begin() as session:
        apply_transition(
            session,
            payment_id,
            Event.ROUTE,
            expected_status=PaymentState.RECEIVED,
            expected_attempt=0,
            retries_enabled=False,
            processor="B",
            reason="static",
        )
    final = delta("relay_payments_final_total", processor="B", outcome="failed")
    with factory() as session:
        now = session.execute(sa.select(sa.func.now())).scalar_one() + timedelta(seconds=60)
    sweep(factory, SweepConfig(5, 5, 30), now=now)
    assert final() == 1


def test_every_known_series_exists_at_zero_before_its_first_event() -> None:
    # Prometheus rate() sees no increase when a series first appears already above zero, so a burst that creates a new
    # label value between two scrapes (for example 10 outage errors in 5 s) would never show on a dashboard.
    from prometheus_client import REGISTRY

    for processor in ("A", "B"):
        for operation, outcomes in (
            ("authorize", ("approved", "declined", "timeout", "outage")),
            ("capture", ("captured", "failed", "timeout", "outage")),
        ):
            for outcome in outcomes:
                labels = {"processor": processor, "operation": operation, "outcome": outcome}
                assert REGISTRY.get_sample_value("relay_processor_calls_total", labels) is not None, labels
        for outcome in ("captured", "declined", "failed"):
            labels = {"processor": processor, "outcome": outcome}
            assert REGISTRY.get_sample_value("relay_payments_final_total", labels) is not None, labels
