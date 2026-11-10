"""Payment mix: seeded currencies and amounts, plus the deterministic reference and Idempotency-Key."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

CURRENCIES = ("USD", "EUR", "GBP", "JPY")
MAX_AMOUNT_MINOR = 1_000_000_000_000  # the API's upper limit


@dataclass(frozen=True)
class Mix:
    """Currency weights and amount ranges in minor units (JPY has no minor unit, so its range is whole yen)."""

    weights: dict[str, float] = field(default_factory=lambda: {"USD": 55, "EUR": 25, "GBP": 15, "JPY": 5})
    min_minor: int = 500  # 5.00 in a two-decimal currency
    max_minor: int = 250_000  # 2,500.00
    min_jpy: int = 500
    max_jpy: int = 300_000

    def __post_init__(self) -> None:
        if not self.weights or any(c not in CURRENCIES for c in self.weights):
            raise ValueError(f"currencies must be among {', '.join(CURRENCIES)}")
        if any(w < 0 for w in self.weights.values()) or sum(self.weights.values()) <= 0:
            raise ValueError("currency weights must be non-negative with a positive total")
        for low, high in ((self.min_minor, self.max_minor), (self.min_jpy, self.max_jpy)):
            if not 1 <= low <= high <= MAX_AMOUNT_MINOR:
                raise ValueError("amount range must lie within 1 to 1,000,000,000,000")


def parse_mix(text: str) -> Mix:
    """Parse `USD=50,EUR=30,GBP=15,JPY=5` into a Mix."""
    weights: dict[str, float] = {}
    for part in text.split(","):
        name, sep, value = part.partition("=")
        if not sep:
            raise ValueError(f"bad mix entry {part!r}; expected CURRENCY=WEIGHT")
        weights[name.strip().upper()] = float(value)
    return Mix(weights=weights)


@dataclass(frozen=True)
class GeneratedPayment:
    index: int
    reference: str
    idempotency_key: str
    body: dict


def reference_for(scenario: str, seed: int, index: int) -> str:
    return f"{scenario}-{seed}-{index:06d}"


def idempotency_key_for(scenario: str, seed: int, index: int) -> str:
    digest = hashlib.sha256(f"relay-load:{scenario}:{seed}:{index}".encode()).hexdigest()
    return digest[:32]


def build_payment(scenario: str, seed: int, index: int, mix: Mix) -> GeneratedPayment:
    """One payment, fully determined by (scenario, seed, index, mix)."""
    rng = random.Random(f"{seed}:{index}")  # noqa: S311 - synthetic data, not security
    names = [c for c in CURRENCIES if mix.weights.get(c, 0) > 0]
    currency = rng.choices(names, weights=[mix.weights[c] for c in names])[0]
    low, high = (mix.min_jpy, mix.max_jpy) if currency == "JPY" else (mix.min_minor, mix.max_minor)
    reference = reference_for(scenario, seed, index)
    body = {"amount_minor": rng.randint(low, high), "currency": currency, "reference": reference}
    return GeneratedPayment(index, reference, idempotency_key_for(scenario, seed, index), body)
