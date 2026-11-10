"""The grounded prompt (REL-25.2, ADR-0012): built only from this payment's own timeline.

Per event: seq, type, time, attempt, processor, reason, and `data.result` / `data.outcome` (fixed vocabularies);
plus the amount in major units and the currency (never the raw minor-unit integer). The free-text `description`
and any other `data` value never reach the prompt.
The model must answer with JSON naming the cause, the text and the seqs it cites.
"""

import json
from collections.abc import Sequence

from app.domain.money import CURRENCY_DIGITS
from app.explain.rules import PATTERNS, ExplainEvent

INSTRUCTIONS = (
    "You explain one card payment to a payment analyst in plain language, in two or three sentences: what "
    "happened, and what to do next. Use only the timeline below. Do not invent facts, amounts, names or "
    "processors that are not listed. Quote the payment amount exactly as given. Each event starts with its number "
    "in brackets; cite every event you rely on by that number.\n"
    "Answer with one JSON object and nothing else, with these keys:\n"
    '  "cause": the one key from the list of causes that best matches the timeline,\n'
    '  "text": your explanation,\n'
    '  "cited_event_seqs": the bracketed numbers, as integers, of the events you used (for example [3, 4]).\n'
)


def _fact(name: str, value: object) -> str:
    return f" {name}={value}" if value is not None else ""


def _line(event: ExplainEvent) -> str:
    result, outcome = event.data.get("result"), event.data.get("outcome")
    return (
        f"[{event.seq}] type={event.type}"
        + _fact("time", event.occurred_at)
        + _fact("attempt", event.attempt_no)
        + _fact("processor", event.processor)
        + _fact("reason", event.reason)
        + _fact("result", result if isinstance(result, str) else None)
        + _fact("outcome", outcome if isinstance(outcome, str) else None)
    )


def format_amount(amount_minor: int, currency: str) -> str:
    """Major units with the currency's decimals, by integer arithmetic only: 1250 USD -> '12.50 USD'."""
    digits = CURRENCY_DIGITS.get(currency, 2)
    if digits == 0:
        return f"{amount_minor} {currency}"
    major, minor = divmod(amount_minor, 10**digits)
    return f"{major}.{minor:0{digits}d} {currency}"


def build_prompt(events: Sequence[ExplainEvent], *, amount_minor: int, currency: str) -> str:
    timeline = sorted(events, key=lambda e: e.seq)
    causes = "\n".join(f'  "{key}": {cause}' for key, (cause, _next) in PATTERNS.items())
    lines = "\n".join(_line(e) for e in timeline)
    return (
        f"{INSTRUCTIONS}\nCauses:\n{causes}\n\n"
        f"Payment amount={format_amount(amount_minor, currency)}\n"
        f"Timeline:\n{lines}\n"
    )


def parse_answer(raw: str) -> dict[str, object]:
    """The model's JSON object, or ValueError."""
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("answer is not an object")
    return value


ANSWER_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "cause": {"type": "string", "enum": list(PATTERNS)},
        "text": {"type": "string"},
        "cited_event_seqs": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
    },
    "required": ["cause", "text", "cited_event_seqs"],
}
