from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from prima.ledger.engine import InsufficientFunds, Ledger, LedgerError
from prima.ledger.models import AccountKind, Entry, Journal, JournalKind, verify_chain
from prima.money import MoneyError


def build(names=("a", "b", "c"), funded=100_000):
    ledger = Ledger()
    ledger.open_account("ext", AccountKind.EXTERNAL, institution="BANKX")
    for name in names:
        ledger.open_account(name)
        if funded:
            ledger.external_credit(name, funded, source_account_id="ext")
    return ledger


def test_unbalanced_journal_is_impossible():
    ledger = build(("a", "b"), funded=0)
    with pytest.raises(ValueError, match="does not balance"):
        ledger.post(JournalKind.TRANSFER, (Entry("a", -100), Entry("b", 99)))


def test_system_total_is_always_zero():
    ledger = build()
    ledger.transfer("a", "b", 25_000)
    ledger.transfer("b", "c", 10_000)
    ledger.external_debit("c", 5_000, destination_account_id="ext")
    assert int(ledger.total_in_system()) == 0
    ledger.check_invariants()


def test_idempotency_key_prevents_double_credit():
    """A retried webhook must not credit twice — the classic payments bug."""
    ledger = build(("a",), funded=0)
    first = ledger.external_credit("a", 50_000, source_account_id="ext", idempotency_key="rzp_1")
    second = ledger.external_credit("a", 50_000, source_account_id="ext", idempotency_key="rzp_1")
    assert first.id == second.id
    assert int(ledger.balance("a")) == 50_000
    assert len(ledger.journals()) == 1


def test_overdraft_is_refused_before_anything_is_written():
    ledger = build(("a", "b"))
    before = len(ledger.journals())
    with pytest.raises(InsufficientFunds):
        ledger.transfer("a", "b", 100_001)
    assert len(ledger.journals()) == before
    ledger.check_invariants()


def test_hold_reduces_available_but_not_balance():
    ledger = build(("a", "b"))
    hold = ledger.open_hold(
        "a", 40_000, reason_ref="PRIMA-1",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    assert int(ledger.balance("a")) == 100_000
    assert int(ledger.available_balance("a")) == 60_000
    with pytest.raises(InsufficientFunds):
        ledger.transfer("a", "b", 70_000)
    ledger.transfer("a", "b", 60_000)
    ledger.release_hold(hold.id, "released")
    assert int(ledger.available_balance("a")) == 40_000
    ledger.check_invariants()


def test_hold_cannot_exceed_available():
    ledger = build(("a",))
    with pytest.raises(InsufficientFunds):
        ledger.open_hold(
            "a", 100_001, reason_ref="x",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )


def test_hold_must_have_a_future_expiry():
    """There is no such thing as an indefinite hold in this system."""
    ledger = build(("a",))
    with pytest.raises(LedgerError):
        ledger.open_hold(
            "a", 1_000, reason_ref="x",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )


def test_holds_expire_on_their_own():
    ledger = build(("a",))
    now = datetime.now(timezone.utc)
    ledger.open_hold("a", 10_000, reason_ref="x", expires_at=now + timedelta(minutes=5))
    assert int(ledger.available_balance("a")) == 90_000
    expired = ledger.expire_holds(now + timedelta(minutes=6))
    assert len(expired) == 1 and expired[0].outcome == "expired"
    assert int(ledger.available_balance("a")) == 100_000


def test_there_is_no_freeze_account_function():
    """Design assertion, enforced as a test so it cannot quietly regress."""
    names = [n for n in dir(Ledger) if not n.startswith("_")]
    for banned in ("freeze", "freeze_account", "block_account", "lock_account"):
        assert banned not in names


def test_hash_chain_detects_reordering():
    ledger = build()
    ledger.transfer("a", "b", 1_000)
    ledger.transfer("b", "c", 500)
    journals = list(ledger.journals())
    verify_chain(journals)
    swapped = journals[:2] + [journals[-1], journals[-2]]
    with pytest.raises(ValueError):
        verify_chain(swapped)


@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    moves=st.lists(
        st.tuples(
            st.sampled_from(["a", "b", "c"]),
            st.sampled_from(["a", "b", "c"]),
            st.integers(min_value=1, max_value=30_000),
        ),
        min_size=0, max_size=25,
    )
)
def test_invariants_hold_under_arbitrary_traffic(moves):
    """Whatever sequence of transfers happens, money is neither created nor lost."""
    ledger = build()
    for sender, receiver, amount in moves:
        if sender == receiver:
            continue
        try:
            ledger.transfer(sender, receiver, amount)
        except InsufficientFunds:
            pass
        ledger.check_invariants()
    assert int(ledger.total_in_system()) == 0
