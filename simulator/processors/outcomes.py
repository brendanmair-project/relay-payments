"""Seeded outcomes: every draw is a hash of the seed, processor, draw key, attempt and purpose.

The draw key is the payment reference when the request has one, otherwise the payment id (ADR-0012).

No shared random generator is advanced, so an outcome never depends on which request arrived first.
"""

import hashlib
import math
from dataclasses import dataclass
from statistics import NormalDist

from .profiles import Profile

DECLINE_REASONS = ("insufficient_funds", "do_not_honor", "card_expired")
_Z95 = NormalDist().inv_cdf(0.95)


def uniform(seed: int, processor: str, draw_key: str, attempt_no: int, purpose: str) -> float:
    """A stable number in [0, 1) for this combination of inputs."""
    digest = hashlib.sha256(f"{seed}|{processor}|{draw_key}|{attempt_no}|{purpose}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


@dataclass(frozen=True)
class Outcome:
    kind: str  # "result" (a 200 answer) or "timeout"
    result: str | None
    reason: str | None
    latency_ms: int


def latency_ms(profile: Profile, u: float) -> int:
    """Log-normal latency with the profile's median (p50) and 95th percentile (p95)."""
    sigma = math.log(profile.latency_ms_p95 / profile.latency_ms_p50) / _Z95
    z = NormalDist().inv_cdf(min(max(u, 1e-12), 1 - 1e-12))
    return max(1, round(profile.latency_ms_p50 * math.exp(sigma * z)))


def decide(
    seed: int,
    processor: str,
    operation: str,
    draw_key: str,
    attempt_no: int,
    profile: Profile,
    max_latency_ms: int,
) -> Outcome:
    def draw(purpose: str) -> float:
        return uniform(seed, processor, draw_key, attempt_no, f"{operation}:{purpose}")

    # An answer slower than the worker's timeout would be a timeout, so answers stay below it.
    latency = min(latency_ms(profile, draw("latency")), max_latency_ms)
    u = draw("outcome")
    if u < profile.timeout_rate:
        return Outcome("timeout", None, None, latency)
    if operation == "authorize":
        if u < profile.timeout_rate + profile.decline_rate:
            reason = DECLINE_REASONS[int(draw("reason") * len(DECLINE_REASONS))]
            return Outcome("result", "declined", reason, latency)
        return Outcome("result", "approved", None, latency)
    if u < profile.timeout_rate + profile.capture_failure_rate:
        return Outcome("result", "failed", "capture_failed", latency)
    return Outcome("result", "captured", None, latency)
