"""Run a scenario: pace payments, apply control steps at their indexes, count HTTP statuses."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .client import RelayClient
from .mix import Mix, build_payment
from .scenarios import ControlStep, ProfileStep, Scenario

# The sweeper re-drives a stuck payment after REDRIVE_AFTER_SECONDS (30) plus SWEEP_TIMEOUT_GRACE_SECONDS (5):
# two cycles of that and 30 s of slack, so a payment that needs one re-drive still drains.
DEFAULT_DRAIN_TIMEOUT_SECONDS = 2 * (30 + 5) + 30


class DrainTimeout(Exception):
    """Earlier payments did not all become final before an outage switch.

    `unfinished` lists, sorted by id, {"id", "status", "attempt_no"} for each payment still not final.
    """

    def __init__(self, message: str, unfinished: list[dict] | None = None) -> None:
        super().__init__(message)
        self.unfinished = unfinished or []


@dataclass
class RunResult:
    sent: int = 0
    statuses: Counter = field(default_factory=Counter)
    control_calls: list[tuple[int, str, bool, int]] = field(default_factory=list)  # index, processor, enabled, status
    # One entry per profile change (partial degradation): index, processor, timeout_rate set, HTTP status.
    profile_calls: list[tuple[int, str, float, int]] = field(default_factory=list)
    unreachable: bool = False
    # One entry per outage switched off with drain on: processor, lag_seconds (None: not recovered), waited_seconds.
    recovery_lags: list[dict] = field(default_factory=list)
    # One entry per outage switch: index, processor, outage (bool) and `at`, the wall-clock UTC time right after the
    # control call returned (the switch is in effect from then). MTTD and the recovery time start from these.
    switch_times: list[dict] = field(default_factory=list)


def wait_until_final(
    client: RelayClient,
    pending: set[str],
    sent: int,
    timeout: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> None:
    """Poll the public API until every id in `pending` is final; raises DrainTimeout after `timeout` seconds."""
    deadline = clock() + timeout
    while True:
        pending.difference_update([pid for pid in sorted(pending) if client.is_final(pid)])
        if not pending:
            return
        if clock() >= deadline:
            unfinished = []
            for pid in sorted(pending):
                status, attempt = client.last_seen.get(pid, ("unknown", None))
                unfinished.append({"id": pid, "status": status, "attempt_no": attempt})
            raise DrainTimeout(
                f"{len(pending)} of the {sent} payments sent so far did not become final within {timeout:g} s",
                unfinished,
            )
        sleep(0.5)


DEFAULT_HEALTH_WINDOW_SECONDS = 60
HEALTH_WAIT_MARGIN_SECONDS = 5


def _avoided(health: dict, processor: str) -> bool:
    return any(
        str(p.get("name", "")).lower() == processor and p.get("state") == "avoided"
        for p in health.get("processors", [])
    )


def wait_for_health_window(
    client: RelayClient, processor: str, sleep: Callable[[float], None], clock: Callable[[], float]
) -> dict:
    """After an outage ends, wait `window_seconds + 5` s from the switch, polling the health once a second.

    The router's health window still holds the outage failures, so payments sent right away would be routed by
    timing. Returns the processor, the lag in seconds until its state is no longer `avoided` (None when it never
    changed) and the seconds waited. `window_seconds` comes from GET /processors/health.
    """
    switched = clock()
    window = client.processor_health().get("window_seconds", DEFAULT_HEALTH_WINDOW_SECONDS)
    total = float(window) + HEALTH_WAIT_MARGIN_SECONDS
    lag: float | None = None
    while True:
        elapsed = clock() - switched
        if lag is None and not _avoided(client.processor_health(), processor):
            lag = round(elapsed, 1)
        if elapsed >= total:
            return {"processor": processor, "lag_seconds": lag, "waited_seconds": round(elapsed, 1)}
        sleep(1.0)


def run_scenario(
    scenario: Scenario,
    client: RelayClient,
    seed: int,
    rate: float,
    count: int | None = None,
    duration: float | None = None,
    mix: Mix | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    drain: bool = True,
    drain_timeout: float = DEFAULT_DRAIN_TIMEOUT_SECONDS,
    wall_clock: Callable[[], float] = time.time,
) -> RunResult:
    if rate <= 0:
        raise ValueError("rate must be positive")
    if count is None and duration is None:
        count = scenario.default_count
    mix = mix or scenario.mix
    steps: dict[int, list[ControlStep | ProfileStep]] = {}
    for step in scenario.steps:
        steps.setdefault(step.at_index, []).append(step)
    result = RunResult()
    outages_on: set[str] = set()
    degraded: set[str] = set()
    unfinished: set[str] = set()
    start = clock()
    index = 0
    try:
        while (count is None or index < count) and (duration is None or index / rate < duration):
            wait = start + index / rate - clock()
            if wait > 0:
                sleep(wait)
            if drain and index in steps:
                # A switch must not race the worker: every earlier payment is final before the outage changes.
                wait_until_final(client, unfinished, result.sent, drain_timeout, sleep, clock)
                start = clock() - index / rate
            for step in steps.get(index, []):
                if isinstance(step, ProfileStep):
                    status = client.set_profile(step.processor, step.profile)
                    result.profile_calls.append((index, step.processor, step.profile["timeout_rate"], status))
                    if step.profile == ProfileStep.default_profile(step.processor):
                        degraded.discard(step.processor)
                    else:
                        degraded.add(step.processor)
                    continue
                status = client.set_outage(step.processor, step.outage)
                result.control_calls.append((index, step.processor, step.outage, status))
                result.switch_times.append(
                    {
                        "index": index,
                        "processor": step.processor,
                        "outage": step.outage,
                        "at": datetime.fromtimestamp(wall_clock(), UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
                    }
                )
                if drain and not step.outage:
                    # Recovery starts from a clean health window; the pacing resumes from here, with no burst.
                    result.recovery_lags.append(wait_for_health_window(client, step.processor, sleep, clock))
                    start = clock() - index / rate
                if step.outage:
                    outages_on.add(step.processor)
                else:
                    outages_on.discard(step.processor)
            payment = build_payment(scenario.name, seed, index, mix)
            status, payment_id = client.create_payment_with_id(payment.idempotency_key, payment.body)
            if payment_id:
                unfinished.add(payment_id)
            result.sent += 1
            result.statuses[status] += 1
            index += 1
            if status == 0:
                result.unreachable = True
                break
    finally:
        # Never leave a simulated outage switched on after the run ends early.
        for processor in sorted(outages_on):
            status = client.set_outage(processor, False)
            result.control_calls.append((index, processor, False, status))
        for processor in sorted(degraded):
            status = client.set_profile(processor, ProfileStep.default_profile(processor))
            rate_back = ProfileStep.default_profile(processor)["timeout_rate"]
            result.profile_calls.append((index, processor, rate_back, status))
    return result
