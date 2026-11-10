"""The routing decision (REL-22): preference rule, failover reason, static strategy, retry target."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.routing.config import retries_enabled, strategy
from app.routing.router import decide_initial, decide_retry
from tests.routing.conftest import seed

Factory = sessionmaker[Session]


def decide(factory: Factory) -> tuple[str, str]:
    with factory() as session:
        d = decide_initial(session)
    return d.processor, d.reason


def bad(factory: Factory, name: str) -> None:
    seed(factory, name, routed=10, failed=10)


def good(factory: Factory, name: str) -> None:
    seed(factory, name, routed=10)


def test_no_history_prefers_a(factory: Factory) -> None:
    assert decide(factory) == ("A", "initial")


def test_a_preferred_stays_on_a_even_if_b_is_avoided(factory: Factory) -> None:
    good(factory, "A")
    bad(factory, "B")
    assert decide(factory) == ("A", "initial")


def test_a_avoided_and_b_preferred_fails_over(factory: Factory) -> None:
    bad(factory, "A")
    good(factory, "B")
    assert decide(factory) == ("B", "failover")


def test_a_avoided_and_b_unknown_fails_over(factory: Factory) -> None:
    bad(factory, "A")
    assert decide(factory) == ("B", "failover")


def test_a_unknown_stays_on_a(factory: Factory) -> None:
    seed(factory, "A", routed=2, failed=2)
    good(factory, "B")
    assert decide(factory) == ("A", "initial")


def test_both_avoided_stays_on_a(factory: Factory) -> None:
    bad(factory, "A")
    bad(factory, "B")
    assert decide(factory) == ("A", "initial")


def test_decision_carries_a_small_health_snapshot(factory: Factory) -> None:
    bad(factory, "A")
    with factory() as session:
        data = decide_initial(session).data
    assert data == {
        "health": {
            "A": {"state": "avoided", "attempts": 10, "errors": 10},
            "B": {"state": "unknown", "attempts": 0, "errors": 0},
        }
    }


def test_static_always_a_with_reason_static(factory: Factory, monkeypatch: pytest.MonkeyPatch) -> None:
    bad(factory, "A")
    good(factory, "B")
    monkeypatch.setenv("ROUTING_STRATEGY", "static")
    assert decide(factory) == ("A", "static")


def test_retry_goes_to_the_other_processor() -> None:
    assert (decide_retry("A").processor, decide_retry("A").reason) == ("B", "retry")
    assert (decide_retry("B").processor, decide_retry("B").reason) == ("A", "retry")


def test_strategy_and_retries_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    assert (strategy(), retries_enabled()) == ("rules", True)
    monkeypatch.setenv("ROUTING_STRATEGY", "rules")
    assert retries_enabled() is True
    monkeypatch.setenv("ROUTING_STRATEGY", "static")
    assert (strategy(), retries_enabled()) == ("static", False)
