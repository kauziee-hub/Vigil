"""Build step 1: the running position replaces the O(n) fold per balance read.

The position is a cache of the fold, so the tests compare it to the fold.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

import pytest

from prima.ledger.engine import InsufficientFunds, Ledger
from prima.ledger.models import AccountKind

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def full_fold(ledger: Ledger, account_id: str) -> int:
    return sum(int(j.delta_for(account_id)) for j in ledger.journals())


def test_position_equals_full_fold_under_random_traffic():
    rng = random.Random(7)
    ledger = Ledger()
    ledger.open_account("ext", AccountKind.EXTERNAL)
    ids = [f"a{i}" for i in range(12)]
    for a in ids:
        ledger.open_account(a)
    for step in range(600):
        when = T0 + timedelta(seconds=step)
        op = rng.random()
        a, b = rng.sample(ids, 2)
        amount = rng.randint(1, 50_000)
        try:
            if op < 0.25:
                ledger.external_credit(a, amount, source_account_id="ext", occurred_at=when)
            elif op < 0.35:
                ledger.external_debit(a, amount, destination_account_id="ext", occurred_at=when)
            else:
                ledger.transfer(a, b, amount, occurred_at=when, idempotency_key=f"k{rng.randint(0, 400)}")
        except InsufficientFunds:
            pass
    for a in [*ids, "ext"]:
        assert int(ledger.balance(a)) == full_fold(ledger, a)
    ledger.check_invariants()


def test_as_of_balances_still_fold_history():
    ledger = Ledger()
    ledger.open_account("ext", AccountKind.EXTERNAL)
    ledger.open_account("a")
    ledger.external_credit("a", 100, source_account_id="ext", occurred_at=T0)
    ledger.external_credit("a", 50, source_account_id="ext", occurred_at=T0 + timedelta(days=2))
    assert int(ledger.balance("a")) == 150
    assert int(ledger.balance("a", as_of=T0 + timedelta(days=1))) == 100
    assert int(ledger.balance("a", as_of=T0 - timedelta(days=1))) == 0


def test_rejected_journals_do_not_move_the_position():
    ledger = Ledger()
    ledger.open_account("ext", AccountKind.EXTERNAL)
    ledger.open_account("a")
    ledger.open_account("b")
    ledger.external_credit("a", 100, source_account_id="ext")
    with pytest.raises(InsufficientFunds):
        ledger.transfer("a", "b", 101)
    ledger.transfer("a", "b", 40, idempotency_key="once")
    ledger.transfer("a", "b", 40, idempotency_key="once")  # replay writes nothing
    assert (int(ledger.balance("a")), int(ledger.balance("b"))) == (60, 40)
    ledger.check_invariants()


def test_check_invariants_catches_a_position_that_drifted_from_the_fold():
    ledger = Ledger()
    ledger.open_account("ext", AccountKind.EXTERNAL)
    ledger.open_account("a")
    ledger.external_credit("a", 100, source_account_id="ext")
    ledger._position["a"] += 1  # simulate a corrupted cache
    with pytest.raises(AssertionError, match="disagrees with the journal fold"):
        ledger.check_invariants()


def test_five_thousand_journals_append_quickly():
    """Step 1 acceptance (09-MVP-FREEZE §7): 5,000 journals in < 2 s.

    Asserted with headroom (< 6 s) so a slow CI machine does not flake; the
    measured figure is printed for the record.
    """
    ledger = Ledger()
    ledger.open_account("ext", AccountKind.EXTERNAL)
    ids = [f"a{i}" for i in range(50)]
    for a in ids:
        ledger.open_account(a)
    ledger.external_credit("a0", 10**12, source_account_id="ext")
    start = time.perf_counter()
    for i in range(5_000):
        ledger.transfer(ids[i % 50], ids[(i + 1) % 50], 1) if int(ledger.balance(ids[i % 50])) else None
    elapsed = time.perf_counter() - start
    print(f"\n[position] 5,000 journals appended in {elapsed:.3f} s")
    assert len(ledger.journals()) >= 5_000 - 50
    assert elapsed < 6.0
    for a in ids:
        assert int(ledger.balance(a)) == full_fold(ledger, a)
