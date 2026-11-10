"""The routing strategy registry (REL-43, ADR-0016): `ROUTING_STRATEGY` names a strategy.

A strategy decides the processor of a new payment from the health data in `session` and the payment (so a later
strategy can seed its draws on the payment `reference`); the retry target stays `decide_retry`. `retries` says whether
the strategy retries a failed attempt on the other processor (the meaning of `retries_enabled()`). To add a strategy,
build a `Strategy` and `register` it from its own module; the worker does not change. Unknown names mean `rules`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

DEFAULT = "rules"


@dataclass(frozen=True)
class RouteDecision:
    processor: str
    reason: str
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class Strategy:
    name: str
    # (session, payment) -> decision; `payment` has `reference`, `amount_minor` and `currency`.
    decide: Callable[[Session, Any], RouteDecision]
    retries: bool = True


_REGISTRY: dict[str, Strategy] = {}


def register(strategy: Strategy) -> None:
    if strategy.name in _REGISTRY:
        raise ValueError(f"strategy {strategy.name!r} is already registered")
    _REGISTRY[strategy.name] = strategy


def _load_built_ins() -> None:
    # The built-in strategies register themselves when `app.routing.router` is imported (no import cycle at load).
    import app.routing.adaptive  # noqa: F401, PLC0415
    import app.routing.hybrid  # noqa: F401, PLC0415
    import app.routing.router  # noqa: F401, PLC0415


def names() -> list[str]:
    _load_built_ins()
    return sorted(_REGISTRY)


def get(name: str) -> Strategy:
    """The strategy called `name` (trimmed, case-insensitive); an unknown name gives `rules`."""
    _load_built_ins()
    return _REGISTRY.get(name.strip().lower(), _REGISTRY[DEFAULT])
