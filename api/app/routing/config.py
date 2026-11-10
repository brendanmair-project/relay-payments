"""Routing settings, read from the environment at call time so the worker, the API and tests agree on one rule.

`ROUTING_STRATEGY` names a strategy in the registry (`app.routing.registry`): `rules` (default) or `static` (the
baseline of ADR-0009: every payment to Processor A, no failover, no retry) today. An unknown value means `rules`.
Retries are enabled when the strategy says so (not for `static`); every `retries_enabled=` in the worker and the
sweeper must come from `retries_enabled()`.
"""

import os
from dataclasses import dataclass

STATIC = "static"
RULES = "rules"


def strategy() -> str:
    from app.routing.registry import get  # noqa: PLC0415 - the registry loads the router, which imports this module

    return get(os.environ.get("ROUTING_STRATEGY", RULES)).name


def retries_enabled() -> bool:
    from app.routing.registry import get  # noqa: PLC0415

    return get(strategy()).retries


@dataclass(frozen=True)
class HealthSettings:
    window_seconds: int
    min_attempts: int
    error_threshold: float


def health_settings() -> HealthSettings:
    return HealthSettings(
        window_seconds=int(os.environ.get("HEALTH_WINDOW_SECONDS", "60")),
        min_attempts=int(os.environ.get("HEALTH_MIN_ATTEMPTS", "5")),
        error_threshold=float(os.environ.get("HEALTH_ERROR_THRESHOLD", "0.5")),
    )
