"""The strategy registry (REL-43): lookup, fallback to `rules`, the payment reaching the strategy, retries."""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.routing import registry
from app.routing.config import retries_enabled, strategy
from app.routing.registry import RouteDecision, Strategy
from app.routing.router import decide_initial

Factory = sessionmaker[Session]


def test_both_built_in_strategies_are_registered() -> None:
    assert {"rules", "static"} <= set(registry.names())
    assert registry.get("rules").name == "rules"
    assert registry.get("static").name == "static"


def test_retries_belong_to_the_strategy() -> None:
    assert registry.get("rules").retries is True
    assert registry.get("static").retries is False


def test_unknown_name_falls_back_to_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    assert registry.get("no-such-strategy").name == "rules"
    monkeypatch.setenv("ROUTING_STRATEGY", "no-such-strategy")
    assert (strategy(), retries_enabled()) == ("rules", True)


def test_name_is_trimmed_and_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "  Static ")
    assert (strategy(), retries_enabled()) == ("static", False)


def test_a_registered_strategy_is_selected_and_gets_the_payment(
    factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []

    def decide(session: Session, payment: object) -> RouteDecision:
        seen.append(payment)
        return RouteDecision("B", "initial")

    monkeypatch.setitem(registry._REGISTRY, "probe", Strategy("probe", decide, retries=False))
    monkeypatch.setenv("ROUTING_STRATEGY", "probe")
    payment = SimpleNamespace(reference="ref-1")
    with factory() as session:
        decision = decide_initial(session, payment)
    assert (decision.processor, decision.reason) == ("B", "initial")
    assert seen == [payment]
    assert (strategy(), retries_enabled()) == ("probe", False)


def test_duplicate_registration_is_refused() -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Strategy("rules", lambda session, payment: RouteDecision("A", "initial")))
