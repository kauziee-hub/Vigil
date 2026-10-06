import pytest
from hypothesis import given, strategies as st

from prima.money import (
    MoneyError, Paise, format_inr, require_positive, split_proportionally,
)


def test_bool_is_not_money():
    # bool subclasses int; without this guard `amount=True` becomes one paisa.
    with pytest.raises(MoneyError):
        Paise(True)


def test_float_is_not_money():
    with pytest.raises(MoneyError):
        Paise(100.5)


def test_require_positive_rejects_zero():
    with pytest.raises(MoneyError):
        require_positive(0)


@pytest.mark.parametrize(
    "paise,expected",
    [
        (0, "₹0.00"),
        (5, "₹0.05"),
        (100, "₹1.00"),
        (123456789, "₹12,34,567.89"),
        (-100000, "-₹1,000.00"),
    ],
)
def test_indian_grouping(paise, expected):
    assert format_inr(paise) == expected


@given(
    total=st.integers(min_value=0, max_value=10**12),
    weights=st.lists(st.integers(min_value=0, max_value=10**9), min_size=1, max_size=25),
)
def test_split_conserves_value(total, weights):
    """The only way PRIMA divides money. It must never leak or invent a paisa."""
    if sum(weights) == 0:
        if total != 0:
            with pytest.raises(MoneyError):
                split_proportionally(total, weights)
        return
    shares = split_proportionally(total, weights)
    assert sum(shares) == total
    assert len(shares) == len(weights)
    assert all(s >= 0 for s in shares)


@given(total=st.integers(min_value=0, max_value=10**9))
def test_split_is_deterministic(total):
    weights = [7, 3, 11, 1]
    assert split_proportionally(total, weights) == split_proportionally(total, weights)


def test_split_largest_remainder_is_stable():
    # 100 across three equal claims: someone must get the extra paisa, and it
    # must always be the same someone.
    assert split_proportionally(100, [1, 1, 1]) == [34, 33, 33]
