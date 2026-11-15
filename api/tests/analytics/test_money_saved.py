"""REL-64: `money_saved` in /analytics. Fixtures are written through the real event code (apply_transition and
append_event); the time-saved arithmetic is checked against the stored event times and, exactly, on fixed times."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.analytics.figures import analytics_figures
from app.domain.lifecycle import Event, PaymentState
from app.domain.reasons import EventType
from app.reporting.metrics import EventRow, PaymentRow, money_saved
from app.reporting.report import Window, load_rows
from app.services.transitions import append_event, apply_transition, create_payment

Factory = sessionmaker[Session]
LABEL = "estimated against the 2-hour manual baseline"
BASELINE = 7200


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


def fail_first(factory: Factory, pid: uuid.UUID) -> None:
    step(factory, pid, Event.ROUTE, PaymentState.RECEIVED, 0, processor="A", reason="initial")
    step(factory, pid, Event.FAIL, PaymentState.ROUTED, 1, reason="timeout")


def rescue(factory: Factory, amount: int, currency: str, path: str) -> uuid.UUID:
    """Failed on A, then captured on B on the second attempt, routed with reason `path`."""
    pid = new_payment(factory, amount, currency)
    fail_first(factory, pid)
    step(factory, pid, Event.ROUTE, PaymentState.FAILED, 1, processor="B", reason=path)
    step(factory, pid, Event.AUTHORIZE, PaymentState.ROUTED, 2)
    step(factory, pid, Event.CAPTURE, PaymentState.AUTHORIZED, 2)
    return pid


def failed_on_both(factory: Factory, amount: int, currency: str) -> uuid.UUID:
    pid = new_payment(factory, amount, currency)
    fail_first(factory, pid)
    step(factory, pid, Event.ROUTE, PaymentState.FAILED, 1, processor="B", reason="retry")
    step(factory, pid, Event.FAIL, PaymentState.ROUTED, 2, reason="timeout")
    return pid


def captured_first_try(factory: Factory, amount: int, currency: str, reason: str = "initial") -> uuid.UUID:
    pid = new_payment(factory, amount, currency)
    step(factory, pid, Event.ROUTE, PaymentState.RECEIVED, 0, processor="A", reason=reason)
    step(factory, pid, Event.AUTHORIZE, PaymentState.ROUTED, 1)
    step(factory, pid, Event.CAPTURE, PaymentState.AUTHORIZED, 1)
    return pid


def explain(factory: Factory, pid: uuid.UUID) -> None:
    data = {"source": "rules", "explanation_id": 1, "trigger": "final_failure"}
    with factory.begin() as session:
        append_event(session, pid, EventType.PAYMENT_EXPLAINED, data=data)


def span() -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "from": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "to": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }


def saved(client: TestClient, headers: dict[str, str], params: dict[str, str] | None = None) -> Any:
    response = client.get("/analytics", params=params or span(), headers=headers)
    assert response.status_code == 200
    return response.json()["money_saved"]


def test_each_rescue_path_is_counted_with_its_money(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    rescue(factory, 2000, "USD", "retry")
    rescue(factory, 5000, "USD", "failover")
    rescue(factory, 700, "USD", "failover")
    body = saved(client, headers)
    assert body["payments_rescued"]["count"] == 3
    assert body["payments_rescued"]["by_rescue_path"] == {
        "failover": {"count": 2, "amount_minor_by_currency": {"USD": 5700}},
        "retry": {"count": 1, "amount_minor_by_currency": {"USD": 2000}},
    }
    assert body["revenue_recovered"]["amount_minor_by_currency"] == {"USD": 7700}


def test_a_payment_that_failed_on_both_processors_is_not_rescued(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    failed_on_both(factory, 9000, "USD")
    body = saved(client, headers)
    assert body["payments_rescued"]["count"] == 0
    assert body["revenue_recovered"]["amount_minor_by_currency"] == {}


def test_a_payment_captured_on_its_first_attempt_is_not_rescued(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    captured_first_try(factory, 1000, "USD")
    captured_first_try(factory, 1000, "USD", reason="failover")  # routed away from a degraded processor, never failed
    assert saved(client, headers)["payments_rescued"]["count"] == 0


def test_currencies_are_kept_separate(client: TestClient, headers: dict[str, str], factory: Factory) -> None:
    rescue(factory, 2000, "USD", "retry")
    rescue(factory, 3000, "EUR", "failover")
    rescue(factory, 800, "JPY", "retry")
    rescue(factory, 100, "USD", "retry")
    body = saved(client, headers)
    assert body["revenue_recovered"]["amount_minor_by_currency"] == {"EUR": 3000, "JPY": 800, "USD": 2100}
    assert body["payments_rescued"]["by_rescue_path"]["retry"]["amount_minor_by_currency"] == {"JPY": 800, "USD": 2100}


def test_time_saved_is_the_baseline_minus_the_stored_time_to_explanation(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    for pid in [failed_on_both(factory, 100, "USD"), failed_on_both(factory, 200, "EUR")]:
        explain(factory, pid)
    with factory() as session:
        gaps = (
            session.execute(
                sa.text(
                    "SELECT extract(epoch FROM x.occurred_at - f.occurred_at) FROM payment_events x "
                    "JOIN payment_events f ON f.payment_id = x.payment_id AND f.type = 'payment.final' "
                    "WHERE x.type = 'payment.explained'"
                )
            )
            .scalars()
            .all()
        )
    assert len(gaps) == 2
    body = saved(client, headers)["investigation_time_saved"]
    assert body["explained_failures"] == 2
    assert body["seconds_saved"] == pytest.approx(sum(BASELINE - float(g) for g in gaps), abs=0.002)
    assert BASELINE * 2 - 5 < body["seconds_saved"] <= BASELINE * 2


def test_time_saved_is_labelled_as_an_estimate_with_its_definition(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    explain(factory, failed_on_both(factory, 100, "USD"))
    body = saved(client, headers)["investigation_time_saved"]
    assert body["label"] == LABEL
    assert body["estimated"] is True
    assert body["baseline_seconds"] == BASELINE
    assert "2-hour" in body["definition"]
    assert "not measured" in body["definition"]


def test_an_unexplained_failure_saves_no_time(client: TestClient, headers: dict[str, str], factory: Factory) -> None:
    failed_on_both(factory, 100, "USD")
    body = saved(client, headers)["investigation_time_saved"]
    assert (body["explained_failures"], body["seconds_saved"]) == (0, 0)


def test_empty_window_reports_zeros_not_nulls(client: TestClient, headers: dict[str, str], factory: Factory) -> None:
    rescue(factory, 2000, "USD", "retry")
    body = saved(client, headers, {"from": "2020-01-01T00:00:00Z", "to": "2020-01-02T00:00:00Z"})
    assert body["payments_rescued"] == {
        "count": 0,
        "by_rescue_path": {
            "failover": {"count": 0, "amount_minor_by_currency": {}},
            "retry": {"count": 0, "amount_minor_by_currency": {}},
        },
    }
    assert body["revenue_recovered"]["amount_minor_by_currency"] == {}
    assert body["investigation_time_saved"]["seconds_saved"] == 0
    assert body["investigation_time_saved"]["explained_failures"] == 0
    assert body["investigation_time_saved"]["label"] == LABEL


def test_the_endpoint_equals_the_reporting_function(
    client: TestClient, headers: dict[str, str], factory: Factory
) -> None:
    rescue(factory, 2000, "USD", "retry")
    explain(factory, failed_on_both(factory, 100, "USD"))
    with factory() as session:
        payments, events = load_rows(session, Window())
    assert saved(client, headers) == analytics_figures(payments, events)["money_saved"]


T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


def _ev(pid: str, seq: int, type_: str, t: float, **kw: Any) -> EventRow:
    return EventRow(payment_id=pid, seq=seq, attempt_no=1, type=type_, occurred_at=T0 + timedelta(seconds=t), **kw)


def test_time_saved_arithmetic_on_fixed_times() -> None:
    def failure(pid: str, gap: float) -> tuple[PaymentRow, list[EventRow]]:
        row = PaymentRow(pid, "USD", 100, True, "failed", T0, T0, "A")
        return row, [
            _ev(pid, 1, "payment.final", 10, data={"outcome": "failed"}),
            _ev(pid, 2, "payment.explained", 10 + gap, data={"source": "model", "trigger": "final_failure"}),
        ]

    p1, e1 = failure("a", 30)  # saves 7200 - 30
    p2, e2 = failure("b", 90)  # saves 7200 - 90
    p3, e3 = failure("c", 7500)  # slower than the baseline: saves nothing, never negative
    result = money_saved([p1, p2, p3], e1 + e2 + e3)["investigation_time_saved"]
    assert result["explained_failures"] == 3
    assert result["seconds_saved"] == (7200 - 30) + (7200 - 90)
    # An explanation stamped before the final failure (clock skew) never claims more than the baseline.
    p4, e4 = failure("d", -60)
    early = money_saved([p4], e4)["investigation_time_saved"]
    assert early["seconds_saved"] == 7200
