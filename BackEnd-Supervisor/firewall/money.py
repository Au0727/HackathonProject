"""Safe monetary arithmetic on integer minor units (HKD cents).

HKD 300.00 is stored as 30000 minor units, so boundary comparisons such as
``300.00 <= 300.00`` and ``300.01 > 300.00`` are exact and never depend on
binary floating-point rounding.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union

from .types import Currency

__all__ = ["Money", "MoneyError", "HKD_ZERO"]

NumberLike = Union[int, float, str, Decimal]

_QUANTUM = Decimal("0.01")
_SCALE = Decimal("100")
_ONE = Decimal("1")


class MoneyError(ValueError):
    """Raised when a value cannot be represented as an exact amount of money."""


@dataclass(frozen=True)
class Money:
    """An exact monetary amount held as an integer number of minor units."""

    minor_units: int
    currency: Currency = Currency.HKD

    def __post_init__(self) -> None:
        if isinstance(self.minor_units, bool) or not isinstance(self.minor_units, int):
            raise MoneyError(
                f"Money requires integer minor units, received {self.minor_units!r}."
            )
        if not isinstance(self.currency, Currency):
            raise MoneyError(f"Money requires a Currency, received {self.currency!r}.")

    # -- construction ----------------------------------------------------
    @classmethod
    def zero(cls, currency: Currency = Currency.HKD) -> "Money":
        return cls(0, currency)

    @classmethod
    def from_minor_units(cls, minor_units: int, currency: Currency = Currency.HKD) -> "Money":
        return cls(minor_units, currency)

    @classmethod
    def parse(cls, value: NumberLike | "Money", currency: Currency = Currency.HKD) -> "Money":
        """Build Money from an int/float/str/Decimal amount of major units.

        Floats are converted through their repr so that ``116.92`` means exactly
        116.92 and never 116.91999999999999.
        """

        if isinstance(value, Money):
            if value.currency is not currency:
                raise MoneyError(
                    f"Cannot read {value.currency.value} as {currency.value}."
                )
            return value
        if isinstance(value, bool):
            raise MoneyError(f"Unsupported monetary value: {value!r}.")
        if isinstance(value, Decimal):
            amount = value
        elif isinstance(value, int):
            amount = Decimal(value)
        elif isinstance(value, float):
            amount = Decimal(repr(value))
        elif isinstance(value, str):
            try:
                amount = Decimal(value.strip())
            except InvalidOperation as error:
                raise MoneyError(f"Unsupported monetary value: {value!r}.") from error
        else:
            raise MoneyError(f"Unsupported monetary value: {value!r}.")
        if not amount.is_finite():
            raise MoneyError(f"Monetary value must be finite, received {value!r}.")
        return cls(int((amount * _SCALE).quantize(_ONE, rounding=ROUND_HALF_UP)), currency)

    # -- inspection ------------------------------------------------------
    @property
    def amount(self) -> Decimal:
        """The amount in major units, quantised to two decimal places."""

        return (Decimal(self.minor_units) / _SCALE).quantize(_QUANTUM)

    def amount_string(self) -> str:
        return f"{self.amount:.2f}"

    def format(self) -> str:
        """Human-readable form, e.g. ``HKD 310.00``."""

        return f"{self.currency.value} {self.amount_string()}"

    def is_zero(self) -> bool:
        return self.minor_units == 0

    def is_negative(self) -> bool:
        return self.minor_units < 0

    # -- arithmetic ------------------------------------------------------
    def _require_same_currency(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise MoneyError(f"Expected Money, received {type(other).__name__}.")
        if other.currency is not self.currency:
            raise MoneyError(
                f"Cannot combine {self.currency.value} with {other.currency.value}."
            )

    def __add__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.minor_units + other.minor_units, self.currency)

    def __radd__(self, other: object) -> "Money":
        if other == 0:  # allows sum([...])
            return self
        if isinstance(other, Money):
            return other.__add__(self)
        raise MoneyError(f"Expected Money, received {type(other).__name__}.")

    def __sub__(self, other: "Money") -> "Money":
        self._require_same_currency(other)
        return Money(self.minor_units - other.minor_units, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.minor_units, self.currency)

    # -- comparison ------------------------------------------------------
    def compare(self, other: "Money") -> int:
        """Return -1, 0 or 1 for a deterministic exact comparison."""

        self._require_same_currency(other)
        if self.minor_units < other.minor_units:
            return -1
        if self.minor_units > other.minor_units:
            return 1
        return 0

    def __lt__(self, other: "Money") -> bool:
        return self.compare(other) < 0

    def __le__(self, other: "Money") -> bool:
        return self.compare(other) <= 0

    def __gt__(self, other: "Money") -> bool:
        return self.compare(other) > 0

    def __ge__(self, other: "Money") -> bool:
        return self.compare(other) >= 0

    def __str__(self) -> str:
        return self.amount_string()


HKD_ZERO = Money.zero()
