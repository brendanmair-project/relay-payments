"""Generate one explanation: ask the model, check its citations, fall back to the rules and say why (REL-25).

`ask_model` returns a checked `ModelAnswer` or raises: `ModelUnavailable` (timeout, unreachable, bad reply) or
`CitationCheckFailed` (unparseable, no text, no citations, or a cited seq outside this payment's timeline).
`generate_explanation` never raises for those: it returns the rules explanation with `fallback_reason` set.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.explain.model import ModelClient, ModelUnavailable
from app.explain.prompt import build_prompt, parse_answer
from app.explain.rules import ExplainEvent, explain

CITATION_CHECK_FAILED = "citation_check_failed"
MODEL_UNREACHABLE = "model_unreachable"
CAUSE_MISMATCH = "cause_mismatch"  # ADR-0013


class CitationCheckFailed(Exception):
    pass


@dataclass(frozen=True)
class ModelAnswer:
    text: str
    cited_event_seqs: tuple[int, ...]
    cause: str | None


@dataclass(frozen=True)
class Generated:
    source: str  # model or rules
    model: str | None
    text: str
    cited_event_seqs: tuple[int, ...]
    fallback_reason: str | None


def ask_model(events: Sequence[ExplainEvent], *, amount_minor: int, currency: str, model: ModelClient) -> ModelAnswer:
    raw = model.generate(build_prompt(events, amount_minor=amount_minor, currency=currency))
    try:
        answer = parse_answer(raw)
    except ValueError:
        raise CitationCheckFailed("unparseable answer") from None
    text, cited, cause = answer.get("text"), answer.get("cited_event_seqs"), answer.get("cause")
    if not isinstance(text, str) or not text.strip():
        raise CitationCheckFailed("no text")
    if not isinstance(cited, list) or not cited:
        raise CitationCheckFailed("no citations")
    if any(isinstance(s, bool) or not isinstance(s, int) for s in cited):
        raise CitationCheckFailed("citations are not integers")
    known = {e.seq for e in events}
    if not set(cited) <= known:
        raise CitationCheckFailed("cites a seq outside the payment's timeline")
    return ModelAnswer(text.strip(), tuple(sorted(set(cited))), cause if isinstance(cause, str) else None)


def rules_fallback(events: Sequence[ExplainEvent], reason: str) -> Generated:
    result = explain(events)
    return Generated("rules", None, f"{result.cause} {result.next_step}", result.cited_event_seqs, reason)


def generate_explanation(
    events: Sequence[ExplainEvent], *, amount_minor: int, currency: str, model: ModelClient | None
) -> Generated:
    if model is None:
        return rules_fallback(events, MODEL_UNREACHABLE)
    try:
        answer = ask_model(events, amount_minor=amount_minor, currency=currency, model=model)
    except ModelUnavailable as unavailable:
        return rules_fallback(events, unavailable.reason)
    except CitationCheckFailed:
        return rules_fallback(events, CITATION_CHECK_FAILED)
    if answer.cause != explain(events).pattern:
        return rules_fallback(events, CAUSE_MISMATCH)
    return Generated("model", model.name, answer.text, answer.cited_event_seqs, None)
