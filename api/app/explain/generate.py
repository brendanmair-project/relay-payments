"""Generate one explanation: ask the model, check its citations, fall back to the rules and say why (REL-25).

`ask_model` returns a checked `ModelAnswer` or raises: `ModelUnavailable` (timeout, unreachable, bad reply) or
`CitationCheckFailed` (unparseable, no text, no citations, or a cited seq outside this payment's timeline).
`generate_explanation` never raises for those: it returns the rules explanation with `fallback_reason` set.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.explain.model import ModelClient, ModelUnavailable
from app.explain.prompt import build_prompt, parse_answer, prompt_inputs
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
    # REL-63: how the text was produced. `attempted_model` is set whenever a model was asked, even when the rules
    # text is shown; `generation_ms` is the wall time of that ask (null when no model was asked).
    attempted_model: str | None = None
    model_cause: str | None = None
    rules_cause: str | None = None
    generation_ms: int | None = None
    inputs: dict[str, Any] | None = None


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


def rules_fallback(events: Sequence[ExplainEvent], reason: str, **details: Any) -> Generated:
    result = explain(events)
    return Generated(
        "rules",
        None,
        f"{result.cause} {result.next_step}",
        result.cited_event_seqs,
        reason,
        rules_cause=result.pattern,
        **details,
    )


def generate_explanation(
    events: Sequence[ExplainEvent], *, amount_minor: int, currency: str, model: ModelClient | None
) -> Generated:
    inputs = prompt_inputs(events, amount_minor=amount_minor, currency=currency)
    if model is None:
        return rules_fallback(events, MODEL_UNREACHABLE, inputs=inputs)
    started = time.monotonic()
    answer: ModelAnswer | None = None
    reason: str | None = None
    try:
        answer = ask_model(events, amount_minor=amount_minor, currency=currency, model=model)
    except ModelUnavailable as unavailable:
        reason = unavailable.reason
    except CitationCheckFailed:
        reason = CITATION_CHECK_FAILED
    details: dict[str, Any] = {
        "attempted_model": model.name,
        "generation_ms": int((time.monotonic() - started) * 1000),
        "inputs": inputs,
    }
    if answer is None:
        assert reason is not None
        return rules_fallback(events, reason, **details)
    if answer.cause != explain(events).pattern:
        return rules_fallback(events, CAUSE_MISMATCH, model_cause=answer.cause, **details)
    return Generated(
        "model",
        model.name,
        answer.text,
        answer.cited_event_seqs,
        None,
        model_cause=answer.cause,
        rules_cause=answer.cause,
        **details,
    )
