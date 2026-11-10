"""REL-25.2: the prompt is built from the payment's own timeline only and asks for cited event seqs."""

import pytest

from app.explain import ExplainEvent
from app.explain.prompt import build_prompt, format_amount

EVENTS = [
    ExplainEvent(seq=1, type="payment.received", attempt_no=0, occurred_at="2026-10-01T12:00:00.000Z"),
    ExplainEvent(
        seq=2,
        type="payment.routed",
        attempt_no=1,
        processor="A",
        reason="initial",
        occurred_at="2026-10-01T12:00:01.000Z",
    ),
    ExplainEvent(
        seq=3,
        type="attempt.authorize_result",
        attempt_no=1,
        processor="A",
        reason="do_not_honor",
        data={"result": "declined", "latency_ms": 90, "note": "relay-test-sentinel-extra"},
        occurred_at="2026-10-01T12:00:02.000Z",
    ),
    ExplainEvent(seq=4, type="payment.final", data={"outcome": "declined"}, occurred_at="2026-10-01T12:00:03.000Z"),
]


def test_prompt_lists_every_event_with_its_seq_and_facts() -> None:
    prompt = build_prompt(EVENTS, amount_minor=1250, currency="USD")
    for seq in (1, 2, 3, 4):
        assert f"[{seq}] " in prompt
    assert "type=attempt.authorize_result" in prompt
    assert "processor=A" in prompt
    assert "reason=do_not_honor" in prompt
    assert "outcome=declined" in prompt
    assert "time=2026-10-01T12:00:02.000Z" in prompt
    assert "amount=12.50 USD" in prompt


def test_prompt_requires_cited_seqs_and_forbids_invented_facts() -> None:
    prompt = build_prompt(EVENTS, amount_minor=1250, currency="USD")
    assert "cited_event_seqs" in prompt
    assert "invent" in prompt.lower()


def test_prompt_carries_no_free_text_from_event_data() -> None:
    prompt = build_prompt(EVENTS, amount_minor=1250, currency="USD")
    assert "relay-test-sentinel-extra" not in prompt


def test_prompt_orders_events_by_seq() -> None:
    prompt = build_prompt(list(reversed(EVENTS)), amount_minor=1250, currency="USD")
    assert prompt.index("[1] ") < prompt.index("[2] ") < prompt.index("[3] ") < prompt.index("[4] ")


def test_amount_is_in_major_units_and_the_raw_minor_value_is_absent() -> None:
    prompt = build_prompt(EVENTS, amount_minor=1250, currency="USD")
    assert "amount=12.50 USD" in prompt
    assert "1250" not in prompt
    assert "amount_minor" not in prompt


def test_zero_decimal_currency_has_no_fraction() -> None:
    assert "amount=1250 JPY" in build_prompt(EVENTS, amount_minor=1250, currency="JPY")


@pytest.mark.parametrize(
    ("minor", "currency", "expected"),
    [(5, "EUR", "0.05 EUR"), (100, "GBP", "1.00 GBP"), (1_000_000_000_000, "USD", "10000000000.00 USD")],
)
def test_format_amount_uses_integer_arithmetic(minor: int, currency: str, expected: str) -> None:
    assert format_amount(minor, currency) == expected


def test_instructions_say_cited_seqs_are_the_bracketed_integers() -> None:
    prompt = build_prompt(EVENTS, amount_minor=1250, currency="USD")
    assert "bracketed numbers, as integers" in prompt
