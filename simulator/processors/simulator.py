"""In-memory state of both processors: profiles, outage switches and first results per idempotency key."""

from dataclasses import dataclass, field

from .outcomes import Outcome, decide
from .profiles import DEFAULT_PROFILES, PROCESSORS, Profile


@dataclass(frozen=True)
class ChargeRequest:
    payment_id: str
    attempt_no: int
    amount_minor: int
    currency: str
    reference: str | None = None


@dataclass
class Decision:
    """What the processor does with one call: answer, refuse (outage), conflict, or time out."""

    status: str  # "result", "outage", "conflict", "not_authorized" or "timeout"
    outcome: Outcome | None = None
    replayed: bool = False


@dataclass
class Simulator:
    seed: int
    timeout_seconds: float
    profiles: dict[str, Profile] = field(default_factory=lambda: dict(DEFAULT_PROFILES))
    outages: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(PROCESSORS, False))
    # (processor, operation, idempotency key) -> (request, first outcome). Outages store nothing.
    _results: dict[tuple[str, str, str], tuple[ChargeRequest, Outcome]] = field(default_factory=dict)

    def handle(self, processor: str, operation: str, key: str, request: ChargeRequest) -> Decision:
        # A processor in an outage answers nothing, not even a stored result.
        if self.outages[processor]:
            return Decision("outage")
        stored = self._results.get((processor, operation, key))
        if stored is not None:
            first_request, outcome = stored
            if first_request != request:
                return Decision("conflict")
            return Decision(outcome.kind, outcome, replayed=True)
        if operation == "capture":
            # Capture needs an approved authorize for the same attempt on this processor; the refusal is not
            # stored, so a capture sent after its authorize still succeeds.
            authorized = self._results.get((processor, "authorize", key))
            if authorized is None or authorized[1].result != "approved":
                return Decision("not_authorized")
        outcome = decide(
            self.seed,
            processor,
            operation,
            request.reference if request.reference is not None else request.payment_id,
            request.attempt_no,
            self.profiles[processor],
            max_latency_ms=max(1, int(self.timeout_seconds * 1000) - 100),
        )
        self._results[(processor, operation, key)] = (request, outcome)
        return Decision(outcome.kind, outcome)
