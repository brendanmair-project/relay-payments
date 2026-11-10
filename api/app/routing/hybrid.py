"""The `hybrid` strategy: `rules` decides, the REL-44 sampler only inside the degraded zone (REL-60, ADR-0017).

Processor health is computed exactly as `rules` does (`compute_health`: the health window, the same error counting,
`HEALTH_MIN_ATTEMPTS`). A processor is in the degraded zone when it has at least the minimum attempts and an error
rate strictly above the gate (`HYBRID_GATE`, default 0.15) that `classify` does not call `avoided` (a rate equal to
the failover threshold stays `preferred`, so it is inside the zone; a rate equal to the gate is outside it).

- A zone and no `avoided` processor: the initial route goes to `adaptive.decide_adaptive` (the sampler, unchanged,
  seeded on the payment reference), reason `adaptive`.
- Otherwise (calm, too little history, or a processor above the failover threshold): exactly `rules`, same
  processor and reason (`initial` or `failover`). When one processor is `avoided` the failover rule keeps priority
  even if the other is in the zone.

Retries stay as `rules` does them (`decide_retry`). Nothing is kept in the process.
"""

import os
from typing import Any

from sqlalchemy.orm import Session

from app.routing import adaptive, registry
from app.routing.config import health_settings
from app.routing.health import AVOIDED, compute_health
from app.routing.registry import RouteDecision, Strategy
from app.routing.router import decide_rules

NAME = "hybrid"
DEFAULT_GATE = 0.15


def hybrid_gate() -> float:
    return float(os.environ.get("HYBRID_GATE", DEFAULT_GATE))


def decide_hybrid(session: Session, payment: Any = None) -> RouteDecision:
    gate = hybrid_gate()
    min_attempts = health_settings().min_attempts
    health = compute_health(session)
    zone = [
        name
        for name, h in health.items()
        if h.attempts >= min_attempts and h.state != AVOIDED and h.errors / h.attempts > gate
    ]
    if zone and not any(h.state == AVOIDED for h in health.values()):
        decision = adaptive.decide_adaptive(session, payment)
        data = {**(decision.data or {}), "hybrid": {"gate": gate, "zone": zone}}
        return RouteDecision(decision.processor, decision.reason, data)
    return decide_rules(session, payment)


registry.register(Strategy(NAME, decide_hybrid, retries=True))
