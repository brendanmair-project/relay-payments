"""REL-60: the `hybrid` strategy (ADR-0017): `rules` decides, the REL-44 sampler only inside the degraded zone.

History is written through the real transition code (`write_attempt` of test_adaptive), as the adaptive tests do.
The zone: a processor with at least HEALTH_MIN_ATTEMPTS attempts and an error rate above the gate (0.15) and not
above the failover threshold (0.5). `classify` keeps a rate equal to the threshold `preferred`, so that rate is in
the zone; a rate equal to the gate is not.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.routing import adaptive, hybrid, registry
from app.routing.config import retries_enabled, strategy
from app.routing.router import decide_initial, decide_retry, decide_rules
from tests.routing.test_adaptive import history, write_attempt

Factory = sessionmaker[Session]


@pytest.fixture(autouse=True)
def protocol_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTH_WINDOW_SECONDS", "120")
    for name in ("HYBRID_GATE", "ADAPTIVE_HALF_LIFE_SECONDS", "ADAPTIVE_PRIOR"):
        monkeypatch.delenv(name, raising=False)


def refs(count: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(reference=f"hyb-{i}", id=uuid.UUID(int=i)) for i in range(count)]


def rate(factory: Factory, processor: str, attempts: int, errors: int) -> None:
    """`attempts` attempts on `processor`, `errors` of them timeouts, the rest captured."""
    history(factory, processor, "timeout", errors)
    history(factory, processor, "captured", attempts - errors)


def hybrid_choices(factory: Factory, payments: list[SimpleNamespace]) -> list[tuple[str, str]]:
    with factory() as session:
        return [(d.processor, d.reason) for d in (hybrid.decide_hybrid(session, p) for p in payments)]


def rules_choices(factory: Factory, payments: list[SimpleNamespace]) -> list[tuple[str, str]]:
    with factory() as session:
        return [(d.processor, d.reason) for d in (decide_rules(session, p) for p in payments)]


def test_hybrid_is_registered_retries_like_rules_and_rules_stays_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "hybrid" in registry.names()
    assert registry.get("hybrid").retries is True
    assert registry.DEFAULT == "rules"
    monkeypatch.delenv("ROUTING_STRATEGY", raising=False)
    assert (strategy(), retries_enabled()) == ("rules", True)
    monkeypatch.setenv("ROUTING_STRATEGY", " Hybrid ")
    assert (strategy(), retries_enabled()) == ("hybrid", True)


def test_the_gate_defaults_to_015_and_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert hybrid.hybrid_gate() == 0.15
    monkeypatch.setenv("HYBRID_GATE", "0.3")
    assert hybrid.hybrid_gate() == 0.3


def test_without_history_hybrid_equals_rules(factory: Factory) -> None:
    payments = refs(20)
    assert hybrid_choices(factory, payments) == rules_choices(factory, payments)
    assert {reason for _, reason in hybrid_choices(factory, payments)} == {"initial"}


def test_with_calm_history_hybrid_equals_rules(factory: Factory) -> None:
    rate(factory, "A", 40, 1)  # 0.025
    rate(factory, "B", 40, 1)
    payments = refs(20)
    assert hybrid_choices(factory, payments) == rules_choices(factory, payments)
    assert {reason for _, reason in hybrid_choices(factory, payments)} == {"initial"}


def test_declines_never_enter_the_zone(factory: Factory) -> None:
    history(factory, "A", "declined", 30)
    payments = refs(10)
    assert hybrid_choices(factory, payments) == rules_choices(factory, payments)


def test_a_processor_in_the_degraded_zone_is_sampled_with_reason_adaptive(factory: Factory) -> None:
    rate(factory, "A", 20, 7)  # 0.35, above the gate, below the failover threshold: rules would not fail over
    rate(factory, "B", 20, 0)
    payments = refs(40)
    assert {reason for _, reason in rules_choices(factory, payments)} == {"initial"}
    got = hybrid_choices(factory, payments)
    assert {reason for _, reason in got} == {"adaptive"}
    with factory() as session:
        expected = [adaptive.decide_adaptive(session, p).processor for p in payments]
    assert [p for p, _ in got] == expected
    assert "B" in expected  # the sampler moved traffic away from A, which `rules` would not


def test_the_sampling_is_deterministic_per_reference(factory: Factory) -> None:
    rate(factory, "A", 20, 7)
    rate(factory, "B", 20, 1)
    payments = refs(30)
    assert hybrid_choices(factory, payments) == hybrid_choices(factory, payments)


def test_a_degraded_b_is_sampled_too(factory: Factory) -> None:
    rate(factory, "A", 20, 0)
    rate(factory, "B", 20, 7)
    got = hybrid_choices(factory, refs(10))
    assert {reason for _, reason in got} == {"adaptive"}


def test_above_the_failover_threshold_the_decision_equals_rules(factory: Factory) -> None:
    rate(factory, "A", 10, 6)  # 0.6: avoided
    rate(factory, "B", 20, 0)
    payments = refs(10)
    got = hybrid_choices(factory, payments)
    assert got == rules_choices(factory, payments)
    assert set(got) == {("B", "failover")}


def test_an_avoided_processor_keeps_rules_even_when_the_other_is_degraded(factory: Factory) -> None:
    rate(factory, "A", 10, 6)  # avoided
    rate(factory, "B", 20, 5)  # 0.25: in the zone
    payments = refs(10)
    assert hybrid_choices(factory, payments) == rules_choices(factory, payments)


def test_a_rate_exactly_at_the_gate_stays_rules(factory: Factory) -> None:
    rate(factory, "A", 20, 3)  # 0.15 exactly, not above the gate
    payments = refs(10)
    got = hybrid_choices(factory, payments)
    assert got == rules_choices(factory, payments)
    assert {reason for _, reason in got} == {"initial"}


def test_a_rate_just_above_the_gate_is_sampled(factory: Factory) -> None:
    rate(factory, "A", 20, 4)  # 0.20
    assert {reason for _, reason in hybrid_choices(factory, refs(5))} == {"adaptive"}


def test_a_rate_exactly_at_the_threshold_is_preferred_for_rules_so_it_is_still_in_the_zone(factory: Factory) -> None:
    rate(factory, "A", 10, 5)  # 0.5: `classify` says preferred, so rules does not fail over
    payments = refs(10)
    assert {r for _, r in rules_choices(factory, payments)} == {"initial"}
    assert {reason for _, reason in hybrid_choices(factory, payments)} == {"adaptive"}


def test_fewer_than_the_minimum_attempts_stays_rules(factory: Factory) -> None:
    rate(factory, "A", 4, 4)  # 100% errors but only 4 attempts (minimum 5)
    payments = refs(10)
    got = hybrid_choices(factory, payments)
    assert got == rules_choices(factory, payments)
    assert {reason for _, reason in got} == {"initial"}


def test_exactly_the_minimum_attempts_counts(factory: Factory) -> None:
    rate(factory, "A", 5, 2)  # 0.4 at 5 attempts
    assert {reason for _, reason in hybrid_choices(factory, refs(5))} == {"adaptive"}


def test_the_gate_setting_moves_the_zone(factory: Factory, monkeypatch: pytest.MonkeyPatch) -> None:
    rate(factory, "A", 20, 4)  # 0.20
    monkeypatch.setenv("HYBRID_GATE", "0.25")
    payments = refs(5)
    assert hybrid_choices(factory, payments) == rules_choices(factory, payments)


def test_events_outside_the_window_do_not_open_the_zone(factory: Factory) -> None:
    for _ in range(10):
        write_attempt(factory, "A", "timeout", age=300)
    payments = refs(5)
    assert hybrid_choices(factory, payments) == rules_choices(factory, payments)


def test_the_configured_strategy_routes_through_decide_initial_and_retries_like_rules(
    factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "hybrid")
    rate(factory, "A", 20, 7)
    with factory() as session:
        assert decide_initial(session, refs(1)[0]).reason == "adaptive"
    assert decide_retry("A").processor == "B"
    assert decide_retry("A").reason == "retry"


def test_the_decision_carries_a_snapshot_of_the_zone(factory: Factory) -> None:
    rate(factory, "A", 20, 7)
    with factory() as session:
        decision = hybrid.decide_hybrid(session, refs(1)[0])
    assert decision.data is not None
    assert decision.data["hybrid"]["gate"] == 0.15
    assert decision.data["hybrid"]["zone"] == ["A"]
