"""Money primitives.

Every monetary value in PRIMA is an integer number of paise. There are no
floats anywhere in the money path, and there is no implicit conversion from
one. ``Paise`` is a distinct type so that a bare ``int`` from an untrusted
source cannot be mistaken for a validated amount.

Two rules that the rest of the system depends on:

1. ``bool`` is rejected. Python's ``bool`` is a subclass of ``int``, so
   ``amount = True`` would otherwise silently become one paisa.
2. Arithmetic that would produce a non-integer is a programming error, not a
   rounding opportunity. Splitting is done by :func:`split_proportionally`,
   which distributes the remainder deterministically instead of rounding.
"""

from __future__ import annotations

from typing import Iterable, Sequence

__all__ = [
    "Paise",
    "ZERO",
    "as_paise",
    "format_inr",
    "split_proportionally",
]


class MoneyError(ValueError):
    """Raised when a value cannot be a valid amount of money."""


class Paise(int):
    """A non-negative-or-negative integer count of paise.

    Subclasses ``int`` so it is cheap and comparable, but construction is
    validated. Signed values are permitted because a double-entry system needs
    them; individual APIs narrow further where a negative amount is meaningless.
    """

    __slots__ = ()

    def __new__(cls, value: int) -> "Paise":
        if isinstance(value, bool):
            raise MoneyError("bool is not a valid amount of money")
        if isinstance(value, Paise):
            return value
        if not isinstance(value, int):
            raise MoneyError(
                f"money must be an int number of paise, got {type(value).__name__}"
            )
        return super().__new__(cls, value)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Paise({int(self)})"

    def __str__(self) -> str:
        return format_inr(self)


ZERO = Paise(0)


def as_paise(value: int) -> Paise:
    """Validate and wrap an integer as :class:`Paise`."""
    return Paise(value)


def require_positive(value: int, what: str = "amount") -> Paise:
    """Validate that ``value`` is a strictly positive amount."""
    amount = Paise(value)
    if amount <= 0:
        raise MoneyError(f"{what} must be positive, got {int(amount)}")
    return amount


def require_non_negative(value: int, what: str = "amount") -> Paise:
    """Validate that ``value`` is zero or positive."""
    amount = Paise(value)
    if amount < 0:
        raise MoneyError(f"{what} must not be negative, got {int(amount)}")
    return amount


def _group_indian(digits: str) -> str:
    """Group digits in the Indian system: 12,34,567."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts: list[str] = []
    while head:
        parts.append(head[-2:])
        head = head[:-2]
    return ",".join(reversed(parts)) + "," + tail


def format_inr(paise: int) -> str:
    """Render paise as rupees with Indian digit grouping.

    Display only. Never parse this back into an amount.
    """
    value = Paise(paise)
    sign = "-" if value < 0 else ""
    rupees, remainder = divmod(abs(int(value)), 100)
    return f"{sign}₹{_group_indian(str(rupees))}.{remainder:02d}"


def split_proportionally(total: int, weights: Sequence[int]) -> list[Paise]:
    """Split ``total`` across ``weights`` with no value created or destroyed.

    Uses the largest-remainder method: each recipient gets the floor of its
    exact share, and the leftover paise go one each to the recipients with the
    largest fractional remainders, ties broken by index so the result is
    deterministic. The sum of the result always equals ``total`` exactly.

    This is the only sanctioned way to divide money in PRIMA. Rounding each
    share independently is how attribution engines leak or invent paise.
    """
    amount = Paise(total)
    for weight in weights:
        if isinstance(weight, bool) or not isinstance(weight, int):
            raise MoneyError("weights must be ints")
        if weight < 0:
            raise MoneyError("weights must not be negative")

    weight_total = sum(weights)
    if not weights:
        if amount != 0:
            raise MoneyError("cannot split a non-zero amount across no recipients")
        return []
    if weight_total == 0:
        if amount != 0:
            raise MoneyError("cannot split a non-zero amount across zero weights")
        return [ZERO for _ in weights]

    base: list[int] = []
    remainders: list[tuple[int, int]] = []  # (remainder numerator, index)
    for index, weight in enumerate(weights):
        exact = int(amount) * weight
        share, remainder = divmod(exact, weight_total)
        base.append(share)
        remainders.append((remainder, index))

    leftover = int(amount) - sum(base)
    # Negative totals floor away from zero, so leftover can be negative; hand
    # out the shortfall in the same deterministic order.
    step = 1 if leftover >= 0 else -1
    order = sorted(remainders, key=lambda item: (-item[0], item[1]))
    position = 0
    while leftover != 0 and order:
        _, index = order[position % len(order)]
        base[index] += step
        leftover -= step
        position += 1

    result = [Paise(value) for value in base]
    if sum(result) != int(amount):
        raise AssertionError("split_proportionally lost value")  # pragma: no cover
    return result


def total(amounts: Iterable[int]) -> Paise:
    """Sum amounts, validating each."""
    return Paise(sum(int(Paise(a)) for a in amounts))
