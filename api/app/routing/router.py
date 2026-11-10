"""The routing decision (REL-22, REL-43): which processor and which `payment.routed` reason.

`decide_initial` runs the strategy chosen by `ROUTING_STRATEGY` through the registry (`app.routing.registry`).
`rules`: prefer A; use B (reason `failover`) only when A is `avoided` and B is not; when both are avoided or unknown
the payment stays on A (reason `initial`). The retry (attempt 2) goes to the other processor (reason `retry`).
`static`: always A, reason `static`.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.domain.reasons import RoutedReason
from app.routing import registry
from app.routing.config import strategy
from app.routing.health import AVOIDED, compute_health
from app.routing.registry import RouteDecision, Strategy


def decide_rules(session: Session, payment: Any = None) -> RouteDecision:
    health = compute_health(session)
    snapshot = {
        "health": {n: {"state": h.state, "attempts": h.attempts, "errors": h.errors} for n, h in health.items()}
    }
    if health["A"].state == AVOIDED and health["B"].state != AVOIDED:
        return RouteDecision("B", RoutedReason.FAILOVER.value, snapshot)
    return RouteDecision("A", RoutedReason.INITIAL.value, snapshot)


def decide_static(session: Session, payment: Any = None) -> RouteDecision:
    return RouteDecision("A", RoutedReason.STATIC.value)


registry.register(Strategy("rules", decide_rules, retries=True))
registry.register(Strategy("static", decide_static, retries=False))


def decide_initial(session: Session, payment: Any = None) -> RouteDecision:
    return registry.get(strategy()).decide(session, payment)


def decide_retry(previous_processor: str) -> RouteDecision:
    return RouteDecision("B" if previous_processor == "A" else "A", RoutedReason.RETRY.value)
