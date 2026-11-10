import dataclasses

import pytest

from app.domain.money import CURRENCY_DIGITS, InvalidMoneyError, Money

BIGINT_MAX = 2**63 - 1


def test_currency_table_matches_adr_0009() -> None:
    assert dict(CURRENCY_DIGITS) == {"USD": 2, "EUR": 2, "GBP": 2, "JPY": 0}


@pytest.mark.parametrize(("currency", "digits"), [("USD", 2), ("EUR", 2), ("GBP", 2), ("JPY", 0)])
def test_valid_money(currency: str, digits: int) -> None:
    money = Money(1999, currency)
    assert money.amount_minor == 1999
    assert money.currency == currency
    assert money.minor_digits == digits


def test_smallest_and_largest_amounts_are_valid() -> None:
    assert Money(1, "USD").amount_minor == 1
    assert Money(BIGINT_MAX, "JPY").amount_minor == BIGINT_MAX


@pytest.mark.parametrize("amount", [19.99, 1.0, "1999", None, True, False])
def test_non_integer_amounts_rejected(amount: object) -> None:
    with pytest.raises(InvalidMoneyError):
        Money(amount, "USD")  # type: ignore[arg-type]


@pytest.mark.parametrize("amount", [0, -1, -1999, BIGINT_MAX + 1])
def test_out_of_range_amounts_rejected(amount: int) -> None:
    with pytest.raises(InvalidMoneyError):
        Money(amount, "USD")


@pytest.mark.parametrize("currency", ["CAD", "usd", "US", "", "USDD", " USD", None, 840])
def test_other_currencies_rejected(currency: object) -> None:
    with pytest.raises(InvalidMoneyError):
        Money(100, currency)  # type: ignore[arg-type]


def test_money_is_immutable_and_comparable() -> None:
    money = Money(500, "EUR")
    with pytest.raises(dataclasses.FrozenInstanceError):
        money.amount_minor = 1  # type: ignore[misc]
    assert money == Money(500, "EUR")
    assert money != Money(500, "USD")
