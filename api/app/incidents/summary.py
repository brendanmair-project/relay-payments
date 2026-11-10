"""The incident summary (REL-35, ADR-0005, ADR-0013): rules first, the model only when it can be checked.

`rules_summary` is deterministic from the linked events. `generate_summary` asks the model for `text`,
`cited_event_ids` and `cause` and keeps its answer only when every cited id is a linked event and its cause equals
the rules cause; otherwise it returns the rules summary with the `fallback_reason`. It never raises for a model
problem. The prompt holds event ids, types, reasons, processors, times and amounts in major units: never a payment
`description`, and no payment id.
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.api.schemas import iso_utc
from app.explain.generate import CAUSE_MISMATCH, CITATION_CHECK_FAILED, MODEL_UNREACHABLE, CitationCheckFailed
from app.explain.model import ModelClient, ModelUnavailable
from app.explain.prompt import format_amount, parse_answer

CAUSES = ("outage", "timeouts", "mixed")  # what the model may answer
NO_CAUSE = "none"  # an incident with no linked events: never sent to the model
NO_LINKED_EVENTS = "no_linked_events"
KINDS = ("outage", "timeout", "capture_failed")  # the failure reasons of linked events
MAX_PROMPT_EVENTS = 30  # the first and the last 15 by time when more are linked

INSTRUCTIONS = (
    "You summarise one payment-processing incident for a payment analyst, in two or three sentences: which "
    "processor was affected, what kind of failures, how many payments, and how it ended. Use only the facts and "
    "events below. Do not invent facts, amounts, names or processors that are not listed. Each event starts with "
    "its number in brackets; cite every event you rely on by that number.\n"
    "Answer with one JSON object and nothing else, with these keys:\n"
    '  "cause": the one key from the list of causes that matches the failures,\n'
    '  "text": your summary,\n'
    '  "cited_event_ids": the bracketed numbers, as integers, of the events you used (for example [4, 9]).\n'
)
CAUSE_HELP = {
    "outage": "every linked failure was an outage",
    "timeouts": "every linked failure was a timeout",
    "mixed": "a mix of outages, timeouts or capture failures",
}
ANSWER_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "cause": {"type": "string", "enum": list(CAUSES)},
        "text": {"type": "string"},
        "cited_event_ids": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
    },
    "required": ["cause", "text", "cited_event_ids"],
}


@dataclass(frozen=True)
class LinkedEvent:
    id: int
    payment_id: str
    type: str
    reason: str | None
    processor: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class AffectedPayment:
    id: str
    status: str
    amount_minor: int
    currency: str
    rescued: bool  # captured after a failover or retry
    processor: str | None = None


@dataclass(frozen=True)
class IncidentFacts:
    processor: str | None
    opened_at: datetime
    recovered_at: datetime | None
    resolved_at: datetime | None
    payments: list[AffectedPayment]
    events: list[LinkedEvent]


@dataclass(frozen=True)
class RulesSummary:
    text: str
    cited_event_ids: tuple[int, ...]
    cause: str


@dataclass(frozen=True)
class GeneratedSummary:
    source: str  # model or rules
    model: str | None
    text: str
    cited_event_ids: tuple[int, ...]
    cause: str
    fallback_reason: str | None


@dataclass(frozen=True)
class ModelAnswer:
    text: str
    cited_event_ids: tuple[int, ...]
    cause: str | None


def _ordered(events: list[LinkedEvent]) -> list[LinkedEvent]:
    return sorted(events, key=lambda e: (e.occurred_at, e.id))


def _payments_by_kind(events: list[LinkedEvent]) -> dict[str, set[str]]:
    kinds: dict[str, set[str]] = defaultdict(set)
    for e in events:
        if e.reason:
            kinds[e.reason].add(e.payment_id)
    return kinds


def rules_cause(events: list[LinkedEvent]) -> str:
    kinds = {k for k, v in _payments_by_kind(events).items() if v}
    if not events:
        return NO_CAUSE
    if kinds == {"outage"}:
        return "outage"
    if kinds == {"timeout"}:
        return "timeouts"
    return "mixed"


def _name(processor: str | None) -> str:
    return f"Processor {processor}" if processor else "The incident (no processor)"


def _recovery(facts: IncidentFacts) -> str:
    if facts.recovered_at is not None:
        seconds = round((facts.recovered_at - facts.opened_at).total_seconds())
        return f"Routing saw the processor healthy again {seconds} seconds after the incident opened."
    if facts.resolved_at is not None:
        return "The incident was resolved without routing seeing the processor recover."
    return "The processor has not recovered yet."


def rules_summary(facts: IncidentFacts) -> RulesSummary:
    events = _ordered(facts.events)
    name = _name(facts.processor)
    if not events:
        return RulesSummary(f"{name}: no failures are linked to this incident. {_recovery(facts)}", (), NO_CAUSE)
    count = len(facts.payments)
    kinds = _payments_by_kind(events)
    by_kind = ", ".join(f"{len(kinds.get(k, ()))} {k}" for k in KINDS)
    rescued = sum(1 for p in facts.payments if p.rescued)
    text = (
        f"{name}: {count} {'payment was' if count == 1 else 'payments were'} affected. "
        f"Failures by kind: {by_kind}. They ran from {iso_utc(events[0].occurred_at)} "
        f"to {iso_utc(events[-1].occurred_at)}. "
        f"{rescued} of the affected payments were rescued by failover or retry. {_recovery(facts)}"
    )
    first_per_kind = {min(e.id for e in events if e.reason == k) for k in KINDS if any(e.reason == k for e in events)}
    return RulesSummary(text, tuple(sorted(first_per_kind)), rules_cause(events))


def _line(event: LinkedEvent) -> str:
    return (
        f"[{event.id}] type={event.type} time={iso_utc(event.occurred_at)}"
        f" processor={event.processor} reason={event.reason}"
    )


def build_prompt(facts: IncidentFacts) -> str:
    events = _ordered(facts.events)
    shown = (
        events
        if len(events) <= MAX_PROMPT_EVENTS
        else events[: MAX_PROMPT_EVENTS // 2] + events[-(MAX_PROMPT_EVENTS // 2) :]
    )
    totals: Counter[str] = Counter()
    for p in facts.payments:
        totals[p.currency] += p.amount_minor
    amounts = ", ".join(format_amount(minor, currency) for currency, minor in sorted(totals.items())) or "none"
    kinds = _payments_by_kind(events)
    by_kind = ", ".join(f"{len(kinds.get(k, ()))} {k}" for k in KINDS)
    causes = "\n".join(f'  "{c}": {CAUSE_HELP[c]}' for c in CAUSES)
    window = f"{iso_utc(events[0].occurred_at)} to {iso_utc(events[-1].occurred_at)}" if events else "none"
    rescued = sum(1 for p in facts.payments if p.rescued)
    facts_text = (
        f"Processor: {facts.processor}\n"
        f"Incident opened: {iso_utc(facts.opened_at)}\n"
        f"Recovered: {iso_utc(facts.recovered_at) if facts.recovered_at else 'not yet'}\n"
        f"Resolved: {iso_utc(facts.resolved_at) if facts.resolved_at else 'not yet'}\n"
        f"Failure window: {window}\n"
        f"Affected payments: {len(facts.payments)} (payments with each failure kind: {by_kind})\n"
        f"Rescued by failover or retry: {rescued}\n"
        f"Total amount of affected payments: {amounts}\n"
    )
    lines = "\n".join(_line(e) for e in shown)
    note = f" (showing {len(shown)} of {len(events)})" if len(shown) < len(events) else ""
    return f"{INSTRUCTIONS}\nCauses:\n{causes}\n\nFacts:\n{facts_text}\nEvents{note}:\n{lines}\n"


def ask_model(facts: IncidentFacts, model: ModelClient) -> ModelAnswer:
    """The model's checked answer, or `ModelUnavailable` / `CitationCheckFailed`."""
    bind: Any = getattr(model, "with_schema", None)
    client: ModelClient = bind(ANSWER_SCHEMA) if callable(bind) else model
    raw = client.generate(build_prompt(facts))
    try:
        answer = parse_answer(raw)
    except (ValueError, json.JSONDecodeError):
        raise CitationCheckFailed("unparseable answer") from None
    text, cited, cause = answer.get("text"), answer.get("cited_event_ids"), answer.get("cause")
    if not isinstance(text, str) or not text.strip():
        raise CitationCheckFailed("no text")
    if not isinstance(cited, list) or not cited:
        raise CitationCheckFailed("no citations")
    if any(isinstance(i, bool) or not isinstance(i, int) for i in cited):
        raise CitationCheckFailed("citations are not integers")
    if not set(cited) <= {e.id for e in facts.events}:
        raise CitationCheckFailed("cites an event that is not linked to the incident")
    return ModelAnswer(text.strip(), tuple(sorted(set(cited))), cause if isinstance(cause, str) else None)


def _rules(facts: IncidentFacts, reason: str) -> GeneratedSummary:
    rules = rules_summary(facts)
    return GeneratedSummary("rules", None, rules.text, rules.cited_event_ids, rules.cause, reason)


def generate_summary(facts: IncidentFacts, model: ModelClient | None) -> GeneratedSummary:
    if not facts.events:
        return _rules(facts, NO_LINKED_EVENTS)
    if model is None:
        return _rules(facts, MODEL_UNREACHABLE)
    try:
        answer = ask_model(facts, model)
    except ModelUnavailable as unavailable:
        return _rules(facts, unavailable.reason)
    except CitationCheckFailed:
        return _rules(facts, CITATION_CHECK_FAILED)
    if answer.cause != rules_cause(facts.events):
        return _rules(facts, CAUSE_MISMATCH)
    return GeneratedSummary("model", model.name, answer.text, answer.cited_event_ids, answer.cause, None)
