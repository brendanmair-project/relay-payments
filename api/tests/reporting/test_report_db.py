"""REL-51: the report over real stored events written through the transition service (relay_test database).

`apply_transition` stamps events with the database clock, so exact timings are covered by the pure tests in
test_metrics.py; here the expected latency and lag are recomputed from the stored timestamps.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.db.events import mark_published
from app.domain.lifecycle import Event, PaymentState
from app.domain.reasons import EventType
from app.reporting.metrics import nearest_rank
from app.reporting.report import Window, build_report
from app.services.transitions import append_event, apply_transition, create_payment

Factory = sessionmaker[Session]
FAR_FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
STUCK_AFTER = timedelta(seconds=40)


def step(factory: Factory, pid: uuid.UUID, event: Event, status: PaymentState, attempt: int, **kw: Any) -> None:
    with factory.begin() as session:
        apply_transition(
            session, pid, event, expected_status=status, expected_attempt=attempt, retries_enabled=True, **kw
        )


def new_payment(factory: Factory, reference: str, amount: int, currency: str) -> uuid.UUID:
    with factory.begin() as session:
        return create_payment(session, amount_minor=amount, currency=currency, reference=reference)


def capture_first_attempt(factory: Factory, pid: uuid.UUID, processor: str, reason: str) -> None:
    step(factory, pid, Event.ROUTE, PaymentState.RECEIVED, 0, processor=processor, reason=reason)
    step(factory, pid, Event.AUTHORIZE, PaymentState.ROUTED, 1)
    step(factory, pid, Event.CAPTURE, PaymentState.AUTHORIZED, 1)


def seed(factory: Factory) -> dict[str, uuid.UUID]:
    """Run A (prefix scn-1-): captured, retry-rescued, failover-rescued, declined, retrying. Run B: one captured."""
    ids = {
        "direct": new_payment(factory, "scn-1-a", 1000, "USD"),
        "retry": new_payment(factory, "scn-1-b", 2000, "USD"),
        "failover": new_payment(factory, "scn-1-c", 3000, "EUR"),
        "declined": new_payment(factory, "scn-1-d", 500, "USD"),
        "retrying": new_payment(factory, "scn-1-e", 900, "USD"),
        "other_run": new_payment(factory, "scn-2-a", 777, "USD"),
    }
    capture_first_attempt(factory, ids["direct"], "A", "initial")
    step(factory, ids["retry"], Event.ROUTE, PaymentState.RECEIVED, 0, processor="A", reason="initial")
    step(factory, ids["retry"], Event.FAIL, PaymentState.ROUTED, 1, reason="timeout")
    step(factory, ids["retry"], Event.ROUTE, PaymentState.FAILED, 1, processor="B", reason="retry")
    step(factory, ids["retry"], Event.AUTHORIZE, PaymentState.ROUTED, 2)
    step(factory, ids["retry"], Event.CAPTURE, PaymentState.AUTHORIZED, 2)
    capture_first_attempt(factory, ids["failover"], "B", "failover")
    step(factory, ids["declined"], Event.ROUTE, PaymentState.RECEIVED, 0, processor="A", reason="initial")
    step(factory, ids["declined"], Event.DECLINE, PaymentState.ROUTED, 1, reason="do_not_honor")
    step(factory, ids["retrying"], Event.ROUTE, PaymentState.RECEIVED, 0, processor="A", reason="initial")
    step(factory, ids["retrying"], Event.FAIL, PaymentState.ROUTED, 1, reason="outage")
    capture_first_attempt(factory, ids["other_run"], "A", "initial")
    return ids


def report(factory: Factory, window: Window | None = None, **kw: Any) -> dict[str, Any]:
    with factory() as session:
        return build_report(
            session, window or Window(), as_of=kw.pop("as_of", FAR_FUTURE), stuck_after=STUCK_AFTER, **kw
        )


def test_whole_database_report(factory: Factory) -> None:
    ids = seed(factory)
    result = report(factory)
    assert result["payments"] == {"selected": 6, "final": 5}
    assert result["latency"]["count"] == 5
    assert result["processor_success"] == {
        # REL-57: counted per final payment (the retried payment is final on B): A has no failure, rate 2 of 3.
        "A": {"captured": 2, "failed": 0, "declined": 1, "success_rate": 0.6667},
        "B": {"captured": 2, "failed": 0, "declined": 0, "success_rate": 1.0},
    }
    # The retrying payment's failed attempt is not final, so it is not counted (A failed is only the retry payment's).
    assert result["rescue_paths"] == {
        "retry": {"count": 1, "amount_minor_by_currency": {"USD": 2000}},
        "failover": {"count": 1, "amount_minor_by_currency": {"EUR": 3000}},
        "redrive": {"count": 0, "amount_minor_by_currency": {}},
    }
    assert result["not_final"]["count"] == 1
    assert result["not_final"]["payments"][0]["payment_id"] == str(ids["retrying"])
    assert result["not_final"]["payments"][0]["status"] == "failed"
    assert result["explanations"] == {"available": False, "note": "not available yet"}


def test_reference_prefix_selects_one_scenario_run(factory: Factory) -> None:
    seed(factory)
    result = report(factory, Window(reference_prefix="scn-1-"))
    assert result["payments"] == {"selected": 5, "final": 4}
    assert result["processor_success"]["A"] == {"captured": 1, "failed": 0, "declined": 1, "success_rate": 0.5}
    only_other = report(factory, Window(reference_prefix="scn-2-"))
    assert only_other["payments"] == {"selected": 1, "final": 1}
    assert only_other["rescue_paths"]["retry"]["count"] == 0
    assert report(factory, Window(reference_prefix="nope-"))["payments"] == {"selected": 0, "final": 0}


def test_reference_prefix_wildcards_are_literal(factory: Factory) -> None:
    seed(factory)
    assert report(factory, Window(reference_prefix="scn%"))["payments"]["selected"] == 0
    assert report(factory, Window(reference_prefix="scn_1-"))["payments"]["selected"] == 0


def test_time_window_is_since_inclusive_until_exclusive_on_creation(factory: Factory) -> None:
    seed(factory)
    with factory() as session:
        created = [r[0] for r in session.execute(sa.text("SELECT created_at FROM payments ORDER BY created_at"))]
    assert len(created) == 6
    assert report(factory, Window(since=created[0]))["payments"]["selected"] == 6
    assert report(factory, Window(since=created[2]))["payments"]["selected"] == 4
    assert report(factory, Window(until=created[2]))["payments"]["selected"] == 2
    assert report(factory, Window(since=created[1], until=created[4]))["payments"]["selected"] == 3
    assert report(factory, Window(since=FAR_FUTURE))["payments"]["selected"] == 0
    assert report(factory, Window(until=created[0]))["payments"]["selected"] == 0


def test_latency_and_lag_match_the_stored_timestamps(factory: Factory) -> None:
    ids = seed(factory)
    with factory.begin() as session:
        event_ids = [
            r[0]
            for r in session.execute(
                sa.text("SELECT id FROM payment_events WHERE payment_id = :p ORDER BY id"), {"p": ids["direct"]}
            )
        ]
        assert mark_published(session, event_ids) == len(event_ids)
    with factory() as session:
        stored = session.execute(
            sa.text(
                "SELECT f.occurred_at - r.occurred_at FROM payment_events f "
                "JOIN payment_events r ON r.payment_id = f.payment_id AND r.type = 'payment.received' "
                "WHERE f.type = 'payment.final' ORDER BY 1"
            )
        ).all()
        lags = session.execute(
            sa.text("SELECT published_at - occurred_at FROM payment_events WHERE published_at IS NOT NULL ORDER BY 1")
        ).all()
        total = session.execute(sa.text("SELECT count(*) FROM payment_events")).scalar_one()

    def micros(delta: timedelta) -> int:
        return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds

    latencies = [micros(r[0]) for r in stored]
    expected = nearest_rank(latencies, 95)
    assert expected is not None
    result = report(factory)
    assert result["latency"]["count"] == len(latencies) == 5
    assert result["latency"]["p95_ms"] == round(expected / 1000, 3)
    assert result["publish_lag"]["published"] == len(lags) == len(event_ids)
    assert result["publish_lag"]["unpublished"] == total - len(event_ids)
    expected_lag = nearest_rank([micros(r[0]) for r in lags], 50)
    assert expected_lag is not None
    assert result["publish_lag"]["p50_ms"] == round(expected_lag / 1000, 3)
    assert result["publish_lag"]["p50_ms"] >= 0


def test_explanations_come_from_explained_events(factory: Factory) -> None:
    ids = seed(factory)
    with factory.begin() as session:
        append_event(
            session,
            ids["declined"],
            EventType.PAYMENT_EXPLAINED,
            data={"explanation_id": 1, "source": "rules", "trigger": "final_failure"},
        )
    result = report(factory)["explanations"]
    assert result["available"] is True
    assert set(result["sources"]) == {"rules"}
    assert result["sources"]["rules"]["count"] == 1
    assert result["fallback_rate"] == 1.0
    assert result["backlog_end"] == 0
    assert result["backlog_max"] == 1


def test_five_xx_rate_comes_from_the_request_log_file(factory: Factory, tmp_path: Path) -> None:
    seed(factory)
    log = tmp_path / "api-requests.jsonl"
    lines = [{"time": "2026-10-27T10:00:00Z", "status": s} for s in (200, 200, 500, 200)]
    log.write_text("\n".join(json.dumps(x) for x in lines) + "\ngarbage\n", encoding="utf-8")
    result = report(factory, request_log_path=str(log))["api_5xx"]
    assert result == {"available": True, "total": 4, "server_errors": 1, "rate_5xx": 0.25, "malformed": 1}


def test_missing_request_log_is_reported_not_guessed(factory: Factory, tmp_path: Path) -> None:
    seed(factory)
    result = report(factory, request_log_path=str(tmp_path / "absent.jsonl"))["api_5xx"]
    assert result == {"available": False, "note": "request log not found"}


def test_empty_database_reports_zeros_and_nulls(factory: Factory) -> None:
    result = report(factory)
    assert result["payments"] == {"selected": 0, "final": 0}
    assert result["latency"]["count"] == 0
    assert result["not_final"]["count"] == 0


@pytest.mark.parametrize("window", [Window(), Window(reference_prefix="scn-1-")])
def test_same_data_gives_the_same_report(factory: Factory, window: Window) -> None:
    seed(factory)
    assert json.dumps(report(factory, window)) == json.dumps(report(factory, window))


def test_fallback_reasons_come_from_the_stored_explanation_rows(factory: Factory) -> None:
    ids = seed(factory)
    with factory.begin() as session:
        row_id = session.execute(
            sa.text(
                "INSERT INTO payment_explanations (payment_id, source, text, cited_event_seqs, trigger, "
                "fallback_reason, final_event_at, generated_at) VALUES (:pid, 'rules', 'x', '{}', 'final_failure', "
                "'cause_mismatch', now(), now()) RETURNING id"
            ),
            {"pid": ids["declined"]},
        ).scalar_one()
        append_event(
            session,
            ids["declined"],
            EventType.PAYMENT_EXPLAINED,
            data={"explanation_id": row_id, "source": "rules", "trigger": "final_failure"},
        )
    result = report(factory)["explanations"]
    assert result["fallback_reasons"] == {"cause_mismatch": 1}
    assert result["fallback_cause_mismatch"] == 1
    assert result["fallback_model_failures"] == 0
