"""Scripted scenarios as data. To add one, append a Scenario to SCENARIOS."""

from __future__ import annotations

from dataclasses import dataclass, field

from .mix import Mix


@dataclass(frozen=True)
class ControlStep:
    """Before sending payment `at_index`, switch the outage of `processor` ("a" or "b") on or off."""

    at_index: int
    processor: str
    outage: bool


# Copies of the simulator's default profiles (simulator/processors/profiles.py; a test keeps them equal), so the
# generator stays free of the simulator's own modules.
_DEFAULT_PROFILES = {
    "a": {
        "latency_ms_p50": 120.0,
        "latency_ms_p95": 400.0,
        "decline_rate": 0.1,
        "timeout_rate": 0.02,
        "capture_failure_rate": 0.01,
    },
    "b": {
        "latency_ms_p50": 250.0,
        "latency_ms_p95": 800.0,
        "decline_rate": 0.08,
        "timeout_rate": 0.01,
        "capture_failure_rate": 0.01,
    },
}


@dataclass(frozen=True)
class ProfileStep:
    """Before sending payment `at_index`, replace the runtime profile of `processor` ("a" or "b") with `profile`.

    A partial degradation (a raised failure rate) rather than an outage; `profile` is the full control API body.
    """

    at_index: int
    processor: str
    profile: dict

    @staticmethod
    def default_profile(processor: str) -> dict:
        return dict(_DEFAULT_PROFILES[processor])


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    default_count: int
    steps: tuple[ControlStep | ProfileStep, ...] = ()
    mix: Mix = field(default_factory=Mix)


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (
        Scenario("normal-day", "Steady traffic with no injected faults.", default_count=200),
        Scenario(
            "processor-a-outage",
            "Processor A is down for payments 100 to 199 (switched on before 100, off before 200); unless drain "
            "is off, the generator first waits until every earlier payment is final, so no switch races the worker.",
            default_count=300,
            steps=(ControlStep(100, "a", True), ControlStep(200, "a", False)),
        ),
        Scenario(
            "processor-a-degraded",
            "Processor A times out on 35% of payments (timeout_rate 0.35 instead of 0.02) for payments 100 to 199, "
            "then its default profile returns. A partial degradation, not an outage; the same drain applies.",
            default_count=300,
            steps=(
                ProfileStep(100, "a", {**ProfileStep.default_profile("a"), "timeout_rate": 0.35}),
                ProfileStep(200, "a", ProfileStep.default_profile("a")),
            ),
        ),
    )
}
