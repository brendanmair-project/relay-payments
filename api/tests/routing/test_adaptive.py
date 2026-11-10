"""REL-44: the `adaptive` strategy (Thompson sampling, ADR-0016): posterior counts, seeding, behaviour, registry.

History is written through the real transition code (`create_payment`, `apply_transition`); only the age of the
events is changed afterwards, with the append-only trigger switched off for that one statement, because the code
stamps every event with the database clock.
"""

import hashlib
import json
import os
import subprocess
import sys
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from redis import Redis
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Payment
from app.domain.lifecycle import Event, PaymentState
from app.domain.reasons import REASONS_BY_EVENT_TYPE, EventType, RoutedReason
from app.routing import adaptive, registry
from app.routing.config import retries_enabled, strategy
from app.routing.router import decide_initial
from app.services.transitions import apply_transition, create_payment
from app.worker.consumer import Consumer
from tests.routing.conftest import PerProcessorFake
from tests.worker.conftest import OUTAGE, timeline, trigger

Factory = sessionmaker[Session]
SECONDS_TOLERANCE = 0.02  # the database clock moves a few milliseconds between writing and reading


@pytest.fixture(autouse=True)
def pre_registered_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The protocol runs a 120 s health window; the half-life and the prior are the defaults."""
    monkeypatch.setenv("HEALTH_WINDOW_SECONDS", "120")
    monkeypatch.delenv("ADAPTIVE_HALF_LIFE_SECONDS", raising=False)
    monkeypatch.delenv("ADAPTIVE_PRIOR", raising=False)


def write_attempt(factory: Factory, processor: str, outcome: str, *, age: float = 0, reason: str = "initial") -> None:
    """One attempt on `processor`, written by the real transition code: outcome is captured, declined, timeout,
    outage or capture_failed; `age` seconds old."""
    with factory.begin() as session:
        pid = create_payment(session, amount_minor=100, currency="USD")
        route = {
            "expected_status": PaymentState.RECEIVED,
            "expected_attempt": 0,
            "retries_enabled": True,
        }
        apply_transition(session, pid, Event.ROUTE, processor=processor, reason=reason, **route)
        step = {"expected_attempt": 1, "retries_enabled": True}
        if outcome == "declined":
            apply_transition(
                session, pid, Event.DECLINE, expected_status=PaymentState.ROUTED, reason="do_not_honor", **step
            )
        elif outcome in ("timeout", "outage"):
            apply_transition(session, pid, Event.FAIL, expected_status=PaymentState.ROUTED, reason=outcome, **step)
        else:
            apply_transition(session, pid, Event.AUTHORIZE, expected_status=PaymentState.ROUTED, **step)
            if outcome == "capture_failed":
                apply_transition(
                    session, pid, Event.FAIL, expected_status=PaymentState.AUTHORIZED, reason=outcome, **step
                )
            else:
                apply_transition(session, pid, Event.CAPTURE, expected_status=PaymentState.AUTHORIZED, **step)
    if age:
        with factory.begin() as session:
            session.execute(sa.text("ALTER TABLE payment_events DISABLE TRIGGER payment_events_append_only"))
            session.execute(
                sa.text(
                    "UPDATE payment_events SET occurred_at = occurred_at - make_interval(secs => :age) "
                    "WHERE payment_id = :pid"
                ),
                {"age": age, "pid": pid},
            )
            session.execute(sa.text("ALTER TABLE payment_events ENABLE TRIGGER payment_events_append_only"))


def history(factory: Factory, processor: str, outcome: str, count: int, *, age: float = 0) -> None:
    for _ in range(count):
        write_attempt(factory, processor, outcome, age=age)


def posterior(factory: Factory) -> dict[str, tuple[float, float]]:
    with factory() as session:
        return {n: (p.successes, p.errors) for n, p in adaptive.posterior(session).items()}


def references(count: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(reference=f"ref-{i}", id=uuid.UUID(int=i)) for i in range(count)]


def choices(factory: Factory, payments: list[SimpleNamespace]) -> list[str]:
    with factory() as session:
        return [adaptive.decide_adaptive(session, p).processor for p in payments]


# --- posterior counts ---------------------------------------------------------------------------------------------


def test_no_history_has_an_empty_posterior(factory: Factory) -> None:
    assert posterior(factory) == {"A": (0.0, 0.0), "B": (0.0, 0.0)}


def test_successes_are_attempts_minus_errors_and_declines_are_never_errors(factory: Factory) -> None:
    history(factory, "A", "captured", 2)
    history(factory, "A", "declined", 3)
    history(factory, "A", "timeout", 1)
    history(factory, "A", "outage", 1)
    history(factory, "A", "capture_failed", 1)
    successes, errors = posterior(factory)["A"]
    assert errors == pytest.approx(3, abs=0.1)
    assert successes == pytest.approx(5, abs=0.1)
    assert posterior(factory)["B"] == (0.0, 0.0)


def test_each_processor_is_counted_on_its_own(factory: Factory) -> None:
    history(factory, "A", "timeout", 2)
    history(factory, "B", "captured", 3)
    counts = posterior(factory)
    assert counts["A"][1] == pytest.approx(2, abs=0.1) and counts["A"][0] == pytest.approx(0, abs=0.1)
    assert counts["B"][0] == pytest.approx(3, abs=0.1) and counts["B"][1] == pytest.approx(0, abs=0.1)


def test_retry_routings_count_as_attempts_like_health(factory: Factory) -> None:
    write_attempt(factory, "B", "captured", reason="retry")
    assert posterior(factory)["B"][0] == pytest.approx(1, abs=0.1)


def test_an_event_loses_half_its_weight_every_half_life(factory: Factory) -> None:
    half_life = adaptive.adaptive_settings().half_life_seconds
    write_attempt(factory, "A", "captured", age=half_life)
    write_attempt(factory, "B", "timeout", age=2 * half_life)
    counts = posterior(factory)
    assert counts["A"][0] == pytest.approx(0.5, abs=SECONDS_TOLERANCE)
    assert counts["B"][1] == pytest.approx(0.25, abs=SECONDS_TOLERANCE)


def test_window_edges_an_event_inside_counts_and_one_outside_does_not(factory: Factory) -> None:
    window = adaptive.adaptive_settings().window_seconds
    write_attempt(factory, "A", "captured", age=window - 5)
    write_attempt(factory, "B", "captured", age=window + 5)
    counts = posterior(factory)
    assert counts["A"][0] > 0
    assert counts["B"] == (0.0, 0.0)


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTH_WINDOW_SECONDS", "90")
    monkeypatch.setenv("ADAPTIVE_HALF_LIFE_SECONDS", "15")
    monkeypatch.setenv("ADAPTIVE_PRIOR", "2")
    cfg = adaptive.adaptive_settings()
    assert (cfg.window_seconds, cfg.half_life_seconds, cfg.prior) == (90, 15.0, 2.0)


def test_defaults_are_the_pre_registered_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HEALTH_WINDOW_SECONDS", "ADAPTIVE_HALF_LIFE_SECONDS", "ADAPTIVE_PRIOR"):
        monkeypatch.delenv(name, raising=False)
    cfg = adaptive.adaptive_settings()
    assert (cfg.half_life_seconds, cfg.prior) == (30.0, 1.0)


# --- seeding ------------------------------------------------------------------------------------------------------


def test_the_seed_is_the_first_eight_bytes_of_sha256_of_the_reference() -> None:
    expected = int.from_bytes(hashlib.sha256(b"normal-day-11-7").digest()[:8], "big")
    assert adaptive.seed_for(SimpleNamespace(reference="normal-day-11-7", id=uuid.UUID(int=1))) == expected


def test_without_a_reference_the_seed_comes_from_the_payment_id() -> None:
    pid = uuid.UUID(int=99)
    expected = int.from_bytes(hashlib.sha256(str(pid).encode()).digest()[:8], "big")
    assert adaptive.seed_for(SimpleNamespace(reference=None, id=pid)) == expected


def test_the_same_references_route_the_same_way_twice(factory: Factory) -> None:
    history(factory, "A", "timeout", 3)
    history(factory, "A", "captured", 3)
    history(factory, "B", "captured", 4)
    payments = references(60)
    first = choices(factory, payments)
    assert choices(factory, payments) == first
    assert set(first) == {"A", "B"}  # not a constant: the draws really differ between references


def test_a_different_reference_can_route_differently(factory: Factory) -> None:
    decided = choices(factory, references(40))
    assert len(set(decided)) == 2


_CHILD = """
import json, sys, uuid
from types import SimpleNamespace
from app.routing import adaptive
refs = [SimpleNamespace(reference=f"ref-{i}", id=uuid.UUID(int=i)) for i in range(40)]
picks = [adaptive.choose(adaptive.seed_for(p), {"A": (3.0, 3.0), "B": (4.0, 0.0)}, 1.0) for p in refs]
print(json.dumps([adaptive.seed_for(p) for p in refs] + picks))
"""


def test_two_processes_with_different_hash_randomisation_agree() -> None:
    outputs = []
    for hash_seed in ("1", "2", "random"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        result = subprocess.run(  # noqa: S603 - runs this interpreter on a fixed script
            [sys.executable, "-c", _CHILD], env=env, capture_output=True, text=True, check=True, timeout=60
        )
        outputs.append(json.loads(result.stdout))
    assert outputs[0] == outputs[1] == outputs[2]
    local = [adaptive.seed_for(p) for p in references(40)]
    assert outputs[0][:40] == local
    assert len(set(outputs[0][40:])) == 2  # both processors are picked, so the equality above means something


def test_the_posterior_is_read_from_the_database_not_from_process_memory(factory: Factory) -> None:
    payments = references(40)
    before = choices(factory, payments)
    history(factory, "A", "timeout", 40)
    history(factory, "B", "captured", 40)
    after = choices(factory, payments)
    assert after != before
    assert after.count("A") < before.count("A") or before.count("A") == 0


# --- behaviour ----------------------------------------------------------------------------------------------------


def test_without_history_both_processors_are_tried_and_the_reason_is_adaptive(factory: Factory) -> None:
    with factory() as session:
        decisions = [adaptive.decide_adaptive(session, p) for p in references(60)]
    assert {d.processor for d in decisions} == {"A", "B"}
    assert {d.reason for d in decisions} == {"adaptive"}
    snapshot = decisions[0].data or {}
    assert set(snapshot["posterior"]) == {"A", "B"}


def test_a_strongly_degraded_processor_gets_rarely_chosen(factory: Factory) -> None:
    history(factory, "A", "timeout", 30)
    history(factory, "A", "captured", 10)
    history(factory, "B", "captured", 40)
    picks = choices(factory, references(200))
    assert picks.count("A") / len(picks) < 0.05


def test_a_fault_older_than_the_window_is_forgotten_and_the_processor_regains_traffic(factory: Factory) -> None:
    window = adaptive.adaptive_settings().window_seconds
    history(factory, "A", "timeout", 40, age=window + 5)
    history(factory, "B", "captured", 20)
    share_a = choices(factory, references(300)).count("A") / 300
    # A has no evidence left, so its wide prior-only posterior is sampled again (about 1 in 22 against B's record).
    assert 0.01 < share_a < 0.15


def test_a_fading_fault_gives_traffic_back_gradually(factory: Factory) -> None:
    payments = references(400)

    def share_with_fault_aged(age: float) -> float:
        history(factory, "A", "timeout", 20, age=age)
        history(factory, "A", "captured", 30)
        history(factory, "B", "captured", 30)
        share = choices(factory, payments).count("A") / len(payments)
        with factory.begin() as session:
            session.execute(sa.text("TRUNCATE payments, payment_events RESTART IDENTITY CASCADE"))
        return share

    fresh, fading = share_with_fault_aged(0), share_with_fault_aged(100)
    assert fresh < 0.05
    assert fading > 0.07
    assert fading > fresh


def test_a_clearly_better_processor_gets_most_traffic(factory: Factory) -> None:
    history(factory, "A", "captured", 40)
    history(factory, "B", "timeout", 20)
    history(factory, "B", "captured", 20)
    share_a = choices(factory, references(200)).count("A") / 200
    assert share_a > 0.9


def test_a_tie_goes_to_a(monkeypatch: pytest.MonkeyPatch) -> None:
    class Equal:
        def betavariate(self, alpha: float, beta: float) -> float:
            return 0.5

    monkeypatch.setattr(adaptive.random, "Random", lambda seed: Equal())
    assert adaptive.choose(5, {"A": (1.0, 1.0), "B": (1.0, 1.0)}, 1.0) == "A"


# --- registry, reason and the worker ------------------------------------------------------------------------------


def test_adaptive_is_registered_and_retries_like_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "adaptive" in registry.names()
    assert registry.get("adaptive").retries is True
    assert registry.DEFAULT == "rules"
    monkeypatch.delenv("ROUTING_STRATEGY", raising=False)
    assert (strategy(), retries_enabled()) == ("rules", True)
    monkeypatch.setenv("ROUTING_STRATEGY", "Adaptive")
    assert (strategy(), retries_enabled()) == ("adaptive", True)


def test_the_configured_strategy_routes_with_reason_adaptive(factory: Factory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "adaptive")
    with factory() as session:
        decision = decide_initial(session, references(1)[0])
    assert decision.reason == "adaptive"


def test_adaptive_is_a_routed_reason_and_the_database_accepts_it(factory: Factory) -> None:
    assert RoutedReason.ADAPTIVE.value == "adaptive"
    assert "adaptive" in {r.value for r in REASONS_BY_EVENT_TYPE[EventType.PAYMENT_ROUTED] or []}
    write_attempt(factory, "B", "captured", reason="adaptive")
    assert posterior(factory)["B"][0] > 0


def test_the_worker_routes_with_adaptive_and_keeps_the_rules_retry(
    factory: Factory, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROUTING_STRATEGY", "adaptive")
    with factory.begin() as session:
        pid = create_payment(session, amount_minor=500, currency="USD", reference="adaptive-1")
    with factory() as session:
        first = adaptive.decide_adaptive(session, SimpleNamespace(reference="adaptive-1", id=pid)).processor
    other = "B" if first == "A" else "A"
    fake = PerProcessorFake({(first, "authorize"): OUTAGE})
    consumer = Consumer(factory, redis_client, fake.client, "c1", reclaim_idle_ms=30000)
    consumer.ensure_group()
    trigger(redis_client, pid)
    consumer.run_once()
    trigger(redis_client, pid, "payment.retry_scheduled", attempt_no=1)
    consumer.run_once()
    routed = [(e.processor, e.reason, e.attempt_no) for e in timeline(factory, pid) if e.type == "payment.routed"]
    assert routed == [(first, "adaptive", 1), (other, "retry", 2)]
    with factory() as session:
        assert session.get_one(Payment, pid).status == "captured"


def test_the_worker_snapshot_seeds_a_payment_without_a_reference_from_its_id(factory: Factory) -> None:
    """REL-59: the snapshot the worker routes with carries the id, so a payment without a reference is never random."""
    from app.worker import handlers

    with factory.begin() as session:
        pid = create_payment(session, amount_minor=500, currency="USD")
    first, second = handlers._read(factory, pid), handlers._read(factory, pid)
    assert first is not None and second is not None
    expected = adaptive.seed_for(SimpleNamespace(reference=None, id=pid))
    assert adaptive.seed_for(first) == expected
    assert adaptive.seed_for(second) == expected
