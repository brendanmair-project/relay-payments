"""REL-37 (api-contract.md): GET /analytics over real stored events, filters, validation and the API key."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.figures import analytics_figures
from app.domain.lifecycle import Event, PaymentState
from app.reporting.metrics import rescue_paths, timelines_by_payment
from app.reporting.report import Window, load_rows
from app.services.transitions import apply_transition, create_payment

Factory = sessionmaker[Session]


@pytest.fixture
def headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def step(factory: Factory, pid: uuid.UUID, event: Event, status: PaymentState, attempt: int, **kw: Any) -> None:
    with factory.begin() as session:
        apply_transition(
            session, pid, event, expected_status=status, expected_attempt=attempt, retries_enabled=True, **kw
        )


def new_payment(factory: Factory, amount: int, currency: str) -> uuid.UUID:
    with factory.begin() as session:
        return create_payment(session, amount_minor=amount, currency=currency)


def capture(factory: Factory, pid: uuid.UUID, processor: str, reason: str) -> None:
    step(factory, pid, Event.ROUTE, PaymentState.RECEIVED, 0, processor=processor, reason=reason)
    step(factory, pid, Event.AUTHORIZE, PaymentState.ROUTED, 1)
    step(factory, pid, Event.CAPTURE, PaymentState.AUTHORIZED, 1)


def seed(factory: Factory) -> None:
    """direct on A (USD), retried A to B (USD), failover straight to B (EUR), declined on A."""
    capture(factory, new_payment(factory, 1000, "USD"), "A", "initial")
    retry = new_payment(factory, 2000, "USD")
    step(factory, retry, Event.ROUTE, PaymentState.RECEIVED, 0, processor="A", reason="initial")
    step(factory, retry, Event.FAIL, PaymentState.ROUTED, 1, reason="timeout")
    step(factory, retry, Event.ROUTE, PaymentState.FAILED, 1, processor="B", reason="retry")
    step(factory, retry, Event.AUTHORIZE, PaymentState.ROUTED, 2)
    step(factory, retry, Event.CAPTURE, PaymentState.AUTHORIZED, 2)
    capture(factory, new_payment(factory, 3000, "EUR"), "B", "failover")
    declined = new_payment(factory, 500, "USD")
    step(factory, declined, Event.ROUTE, PaymentState.RECEIVED, 0, processor="A", reason="initial")
    step(factory, declined, Event.DECLINE, PaymentState.ROUTED, 1, reason="do_not_honor")


def span(**extra: str) -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "from": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "to": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        **extra,
    }


def get(client: TestClient, headers: dict[str, str], **params: str) -> Any:
    return client.get("/analytics", params=params, headers=headers)


def test_every_figure_over_stored_events_with_money_and_processor_joined_from_payments(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    seed(factory)
    body = get(client, headers, **span()).json()
    assert body["volume"] == {"payments": 4, "final": 4}
    a, b = body["processors"]["A"], body["processors"]["B"]
    assert (a["volume"], a["captured"], a["failed"], a["declined"]) == (3, 1, 0, 1)
    assert a["success_rate"] == 0.5  # REL-57: captured 1 over final 2 (one capture, one decline); the old rule gave 1.0
    assert (b["volume"], b["captured"], b["failed"]) == (2, 2, 0)
    assert b["success_rate"] == 1.0
    assert a["failure_reasons"] == {"do_not_honor": 1, "timeout": 1}
    assert b["failure_reasons"] == {}
    assert body["latency"]["count"] == 4
    # The retried payment is handled by B (payments.processor), the other three final payments: A has 2, B has 2.
    assert (a["latency"]["count"], b["latency"]["count"]) == (2, 2)
    assert body["revenue_recovered_by_rescue_path"] == {
        "retry": {"count": 1, "amount_minor_by_currency": {"USD": 2000}},
        "failover": {"count": 1, "amount_minor_by_currency": {"EUR": 3000}},
        "redrive": {"count": 0, "amount_minor_by_currency": {}},
    }
    assert body["time_to_explanation"] == {"available": False, "note": "not available yet"}
    assert body["window"]["processor"] is None


def test_the_figures_equal_a_direct_call_to_the_reporting_functions(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    seed(factory)
    body = get(client, headers, **span()).json()
    with factory() as session:
        payments, events = load_rows(session, Window())
    direct = rescue_paths(payments, timelines_by_payment(events))
    assert body["revenue_recovered_by_rescue_path"] == direct
    expected = analytics_figures(payments, events)
    assert body["processors"]["A"]["success_rate"] == expected["processors"]["A"]["success_rate"]
    assert body["latency"] == expected["latency"]


def test_the_processor_filter_keeps_payments_routed_to_that_processor(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    seed(factory)
    only_b = get(client, headers, **span(processor="B")).json()
    assert list(only_b["processors"]) == ["B"]
    assert only_b["volume"]["payments"] == 2
    assert only_b["window"]["processor"] == "B"
    assert only_b["revenue_recovered_by_rescue_path"]["failover"]["amount_minor_by_currency"] == {"EUR": 3000}
    only_a = get(client, headers, **span(processor="A")).json()
    assert list(only_a["processors"]) == ["A"]
    assert only_a["volume"]["payments"] == 3
    assert only_a["processors"]["A"]["failure_reasons"] == {"do_not_honor": 1, "timeout": 1}
    assert only_a["revenue_recovered_by_rescue_path"]["failover"]["count"] == 0


def test_the_time_range_filters_payments_by_creation_time(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    seed(factory)
    past = {"from": "2020-01-01T00:00:00Z", "to": "2020-01-02T00:00:00Z"}
    empty = get(client, headers, **past).json()
    assert empty["volume"] == {"payments": 0, "final": 0}
    assert empty["processors"]["A"]["success_rate"] is None
    assert get(client, headers, **span()).json()["volume"]["payments"] == 4


def test_the_default_range_is_the_last_24_hours(client: TestClient, headers: dict[str, str]) -> None:
    window = get(client, headers).json()["window"]
    start = datetime.fromisoformat(window["from"].replace("Z", "+00:00"))
    stop = datetime.fromisoformat(window["to"].replace("Z", "+00:00"))
    assert stop - start == timedelta(hours=24)
    assert abs(datetime.now(UTC) - stop) < timedelta(minutes=1)


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-11-02T00:00:00Z", "to": "2026-11-01T00:00:00Z"},
        {"from": "2026-11-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"},
        {"from": "2026-10-01T00:00:00Z", "to": "2026-11-02T00:00:00Z"},
        {"processor": "C"},
        {"processor": "a"},
        {"from": "yesterday"},
        {"to": "not-a-time"},
    ],
)
def test_invalid_input_is_422_in_the_shared_error_format(
    client: TestClient, headers: dict[str, str], params: dict[str, str]
) -> None:
    response = get(client, headers, **params)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_failed"
    assert error["correlation_id"]


def test_a_range_of_exactly_31_days_is_accepted(client: TestClient, headers: dict[str, str]) -> None:
    response = get(client, headers, **{"from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"})
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/analytics", "/analytics/baseline"])
def test_the_api_key_is_required(client: TestClient, path: str) -> None:
    for bad in ({}, {"X-API-Key": "wrong"}):
        response = client.get(path, headers=bad)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
