"""The `adaptive` strategy: Thompson sampling over recent processor outcomes (REL-44, ADR-0016, ADR-0012).

Per processor a Beta-Bernoulli posterior, Beta(prior + successes, prior + errors), over the events of the health
window in PostgreSQL, each event weighted by exponential decay (half-life `ADAPTIVE_HALF_LIFE_SECONDS`). The events are
the ones `app.routing.health` counts: an attempt is a `payment.routed` event, an error a `payment.failed` event with
reason timeout, outage or capture_failed (declines are never errors), successes are attempts minus errors. Nothing is
kept in the process, so every worker and a restart see the same posterior.

One draw per processor from `random.Random(seed)`, the highest draw wins and a tie goes to A. The seed is the first
8 bytes of SHA-256 of the payment `reference` (the payment id when there is none): never `hash()`, which is
randomised per process, and never the global `random`, so a paired run repeats exactly. The parameters are fixed in
`docs/evaluation/routing-experiments/protocol.md`. Retries stay as `rules` does them (`decide_retry`).
"""

import hashlib
import os
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import PaymentEvent
from app.domain.reasons import EventType, RoutedReason
from app.routing import registry
from app.routing.config import health_settings
from app.routing.health import ERROR_REASONS, PROCESSORS
from app.routing.registry import RouteDecision, Strategy

NAME = "adaptive"
DEFAULT_HALF_LIFE_SECONDS = 30.0
DEFAULT_PRIOR = 1.0


@dataclass(frozen=True)
class AdaptiveSettings:
    window_seconds: int
    half_life_seconds: float
    prior: float


@dataclass(frozen=True)
class Posterior:
    """Decayed successes and errors of one processor (not yet including the prior)."""

    successes: float
    errors: float


def adaptive_settings() -> AdaptiveSettings:
    return AdaptiveSettings(
        window_seconds=health_settings().window_seconds,
        half_life_seconds=float(os.environ.get("ADAPTIVE_HALF_LIFE_SECONDS", DEFAULT_HALF_LIFE_SECONDS)),
        prior=float(os.environ.get("ADAPTIVE_PRIOR", DEFAULT_PRIOR)),
    )


def posterior(session: Session, settings: AdaptiveSettings | None = None) -> dict[str, Posterior]:
    """Decayed successes and errors of A and B over the window, measured against the database clock."""
    cfg = settings or adaptive_settings()
    age_seconds = sa.extract("epoch", sa.func.now() - PaymentEvent.occurred_at)
    weight = sa.func.power(0.5, age_seconds / cfg.half_life_seconds)
    attempts = sa.func.coalesce(sa.func.sum(weight).filter(PaymentEvent.type == EventType.PAYMENT_ROUTED.value), 0.0)
    errors = sa.func.coalesce(
        sa.func.sum(weight).filter(
            PaymentEvent.type == EventType.PAYMENT_FAILED.value, PaymentEvent.reason.in_(ERROR_REASONS)
        ),
        0.0,
    )
    rows = session.execute(
        sa.select(PaymentEvent.processor, attempts, errors)
        .where(
            PaymentEvent.occurred_at >= sa.func.now() - timedelta(seconds=cfg.window_seconds),
            PaymentEvent.type.in_([EventType.PAYMENT_ROUTED.value, EventType.PAYMENT_FAILED.value]),
            PaymentEvent.processor.in_(PROCESSORS),
        )
        .group_by(PaymentEvent.processor)
    ).all()
    counts = {row[0]: (float(row[1]), float(row[2])) for row in rows}
    result = {}
    for name in PROCESSORS:
        n_attempts, n_errors = counts.get(name, (0.0, 0.0))
        # An error event is a little younger than its own attempt, so the decayed difference can dip below zero.
        result[name] = Posterior(max(0.0, n_attempts - n_errors), n_errors)
    return result


def seed_for(payment: Any) -> int:
    """A stable seed: the first 8 bytes of SHA-256 of the payment reference, else of its id (else fresh entropy)."""
    key = getattr(payment, "reference", None) or getattr(payment, "id", None)
    if key is None:  # a payment with neither cannot be paired with another run
        return int.from_bytes(os.urandom(8), "big")
    return int.from_bytes(hashlib.sha256(str(key).encode("utf-8")).digest()[:8], "big")


def choose(seed: int, counts: dict[str, tuple[float, float]], prior: float) -> str:
    """One Beta draw per processor from `random.Random(seed)`, A then B; the highest wins, a tie goes to A."""
    rng = random.Random(seed)  # noqa: S311 - a seeded sampler for routing, not a security token
    draws = {name: rng.betavariate(prior + counts[name][0], prior + counts[name][1]) for name in PROCESSORS}
    return "B" if draws["B"] > draws["A"] else "A"


def decide_adaptive(session: Session, payment: Any = None) -> RouteDecision:
    cfg = adaptive_settings()
    counts = posterior(session, cfg)
    pairs = {name: (p.successes, p.errors) for name, p in counts.items()}
    processor = choose(seed_for(payment), pairs, cfg.prior)
    snapshot = {
        "posterior": {n: {"successes": round(s, 2), "errors": round(e, 2)} for n, (s, e) in pairs.items()},
        "half_life_seconds": cfg.half_life_seconds,
    }
    return RouteDecision(processor, RoutedReason.ADAPTIVE.value, snapshot)


# Retries stay exactly as `rules` does them, so a comparison isolates the initial choice.
registry.register(Strategy(NAME, decide_adaptive, retries=True))
