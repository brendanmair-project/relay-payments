"""Money value object: integer minor units plus a currency from one table (ADR-0004, ADR-0009)."""

from dataclasses import dataclass
from types import MappingProxyType

# The single currency table: ISO 4217 code -> minor-unit digits. Any other code is rejected.
CURRENCY_DIGITS = MappingProxyType({"USD": 2, "EUR": 2, "GBP": 2, "JPY": 0})

# amount_minor is stored as BIGINT.
MAX_AMOUNT_MINOR = 2**63 - 1


class InvalidMoneyError(ValueError):
    """The amount or currency is not acceptable."""


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        # bool is an int subclass; True must not pass as 1.
        if type(self.amount_minor) is not int:
            raise InvalidMoneyError("amount_minor must be an integer number of minor units")
        if not 0 < self.amount_minor <= MAX_AMOUNT_MINOR:
            raise InvalidMoneyError("amount_minor must be positive and fit in a BIGINT")
        if not isinstance(self.currency, str) or self.currency not in CURRENCY_DIGITS:
            raise InvalidMoneyError(f"currency must be one of {', '.join(CURRENCY_DIGITS)}")

    @property
    def minor_digits(self) -> int:
        return CURRENCY_DIGITS[self.currency]
