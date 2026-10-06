"""Incremental LIBR, checked against the batch engine.

There is exactly one thing that matters here, and every test is a restatement of
it: after each individual posting, for every account and every live incident,
the incremental state equals what the batch trace would say. Not at the end --
after each one. A real-time number that is only right eventually is not a
real-time number, it is a stale one.

The batch engine is the reference. Where the two disagree the incremental one is
wrong by definition.
"""
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from prima.attribution.incremental import IncrementalLineage
from prima.attribution.rules import TracingRule
from prima.attribution.trace import Incident, trace_multi
from prima.ledger.engine import InsufficientFunds, Ledger
from prima.ledger.models import AccountKind, Entry, JournalKind

T0 = datetime(2026, 3, 12, 9, 0, tzinfo=timezone.utc)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def world(customers, funding=None):
    ledger = Ledger()
    ledger.open_account("ext", AccountKind.EXTERNAL, institution="ELSEWHERE")
    for name in customers:
        ledger.open_account(name)
    for name, amount in (funding or {}).items():
        if amount:
            ledger.external_credit(name, amount, source_account_id="ext", occurred_at=at(0))
    return ledger


def incident(incident_id, journal, minutes=1000):
    return Incident(
        id=incident_id, origin_journal_ids={journal.id}, reported_at=at(minutes)
    )


def customers_of(ledger):
    return [a.id for a in ledger.accounts() if a.is_customer]


def accounts_of(ledger):
    return {a.id: a for a in ledger.accounts()}


def balance_at(journals, account_id, seq):
    """The balance as it stood after ``seq``.

    C2 and C4 are about the balance *at that moment*, not the one the account
    ends up with. Comparing a mid-history claim against a final balance is a
    test bug that looks exactly like an engine bug.
    """
    return sum(int(j.delta_for(account_id)) for j in journals if j.seq <= seq)


def assert_matches_batch_after_every_posting(ledger, incidents):
    """The property, applied to a ledger that is already fully built.

    Replays the log one posting at a time and compares against a batch trace
    truncated to the same point, which is what "after every posting" means.
    Returns the maintainer so a caller can make further assertions on it.
    """
    accounts = accounts_of(ledger)
    customers = customers_of(ledger)
    journals = ledger.journals()
    live = IncrementalLineage(incidents, customers)

    for journal in journals:
        live.apply(journal)
        batch = trace_multi(
            journals, incidents, TracingRule.LIBR, accounts, through_seq=journal.seq
        )
        for inc in incidents:
            derivation = batch[inc.id]
            for account_id in customers:
                assert live.claim(account_id, inc.id) == int(
                    derivation.claim_for(account_id)
                ), (
                    f"seq {journal.seq}: claim on {account_id} for {inc.id} -- "
                    f"incremental {live.claim(account_id, inc.id)} != batch "
                    f"{int(derivation.claim_for(account_id))}"
                )
            assert live.left_perimeter(inc.id) == int(
                derivation.left_perimeter_paise
            ), f"seq {journal.seq}: left_perimeter for {inc.id}"
            assert live.retagged(inc.id) == int(derivation.retagged_paise), (
                f"seq {journal.seq}: retagged for {inc.id}"
            )
        # C4 and non-negativity, at every step rather than only at the end.
        for account_id in customers:
            held = balance_at(journals, account_id, journal.seq)
            assert live.total_claimed(account_id) <= held
            for inc in incidents:
                assert live.claim(account_id, inc.id) >= 0
    return live


# ------------------------------------------------------------ worked examples


def test_the_brief_worked_example_incrementally():
    """The scenario from the brief, but maintained rather than recomputed.

    Same numbers as the batch worked example: the claim survives to Rs 15,000
    on B, Rs 15,000 lands on C, Rs 10,000 on D, Rs 10,000 leaves the perimeter.
    """
    ledger = world(["victim", "B", "C", "D"], {"victim": 50_000_00, "B": 5_000_00})
    origin = ledger.transfer("victim", "B", 50_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 20_000_00, occurred_at=at(2))
    ledger.external_debit("B", 10_000_00, destination_account_id="ext", occurred_at=at(3))
    ledger.external_credit("B", 20_000_00, source_account_id="ext", occurred_at=at(4))
    ledger.transfer("B", "D", 30_000_00, occurred_at=at(5))
    ledger.check_invariants()

    inc = incident("inc_1", origin)
    live = assert_matches_batch_after_every_posting(ledger, [inc])
    assert live.claim("B", "inc_1") == 15_000_00
    assert live.claim("C", "inc_1") == 15_000_00
    assert live.claim("D", "inc_1") == 10_000_00
    assert live.left_perimeter("inc_1") == 10_000_00


def test_two_incidents_incrementally_respect_c4():
    """The spec's Rs 60,000-against-Rs 30,000 case, maintained live."""
    ledger = world(["v1", "v2", "mule"], {"v1": 30_000_00, "v2": 30_000_00})
    o1 = ledger.transfer("v1", "mule", 30_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "mule", 30_000_00, occurred_at=at(2))
    ledger.external_debit("mule", 30_000_00, destination_account_id="ext", occurred_at=at(3))

    incidents = [incident("I1", o1), incident("I2", o2)]
    live = assert_matches_batch_after_every_posting(ledger, incidents)
    assert live.claim("mule", "I1") == 0
    assert live.claim("mule", "I2") == 30_000_00
    assert live.left_perimeter("I1") == 30_000_00
    assert live.total_claimed("mule") == int(ledger.balance("mule"))


def test_normal_transfers():
    ledger = world(["v", "B", "C", "D"], {"v": 12_000_00, "B": 3_000_00})
    origin = ledger.transfer("v", "B", 12_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 6_000_00, occurred_at=at(2))
    ledger.transfer("C", "D", 2_000_00, occurred_at=at(3))
    assert_matches_batch_after_every_posting(ledger, [incident("I1", origin)])


def test_external_debits():
    ledger = world(["v1", "v2", "B"], {"v1": 9_000_00, "v2": 4_000_00})
    o1 = ledger.transfer("v1", "B", 9_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 4_000_00, occurred_at=at(2))
    ledger.external_debit("B", 11_000_00, destination_account_id="ext", occurred_at=at(3))
    live = assert_matches_batch_after_every_posting(
        ledger, [incident("I1", o1), incident("I2", o2)]
    )
    assert live.left_perimeter("I1") == 9_000_00
    assert live.left_perimeter("I2") == 2_000_00


def test_multi_credit_split():
    """One debit, several uneven credits -- the case that exposed the drift."""
    ledger = world(["v1", "v2", "B", "X", "Y", "Z"], {"v1": 10_001, "v2": 10_001})
    o1 = ledger.transfer("v1", "B", 10_001, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 10_001, occurred_at=at(2))
    ledger.post(
        JournalKind.TRANSFER,
        (Entry("B", -20_002), Entry("X", 6_667), Entry("Y", 6_667), Entry("Z", 6_668)),
        occurred_at=at(3),
    )
    ledger.check_invariants()
    live = assert_matches_batch_after_every_posting(
        ledger, [incident("I1", o1), incident("I2", o2)]
    )
    for account in ("X", "Y", "Z"):
        assert live.total_claimed(account) <= int(ledger.balance(account))


def test_multi_debit_journal():
    """Several debits into one credit -- a sweep."""
    ledger = world(["v1", "v2", "B", "C", "sink"], {"v1": 5_000_00, "v2": 5_000_00})
    o1 = ledger.transfer("v1", "B", 5_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "C", 5_000_00, occurred_at=at(2))
    ledger.post(
        JournalKind.TRANSFER,
        (Entry("B", -5_000_00), Entry("C", -5_000_00), Entry("sink", 10_000_00)),
        occurred_at=at(3),
    )
    ledger.check_invariants()
    live = assert_matches_batch_after_every_posting(
        ledger, [incident("I1", o1), incident("I2", o2)]
    )
    assert live.claim("sink", "I1") == 5_000_00
    assert live.claim("sink", "I2") == 5_000_00


def test_fan_out():
    ledger = world(["v", "B", "C0", "C1", "C2"], {"v": 30_000_00, "B": 30_000_00})
    origin = ledger.transfer("v", "B", 30_000_00, occurred_at=at(1))
    for index in range(3):
        ledger.transfer("B", f"C{index}", 20_000_00, occurred_at=at(2 + index))
    assert_matches_batch_after_every_posting(ledger, [incident("I1", origin)])


def test_fan_in():
    ledger = world(["v1", "v2", "B", "C", "sink"], {"v1": 7_000_00, "v2": 11_000_00})
    o1 = ledger.transfer("v1", "B", 7_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "C", 11_000_00, occurred_at=at(2))
    ledger.transfer("B", "sink", 7_000_00, occurred_at=at(3))
    ledger.transfer("C", "sink", 11_000_00, occurred_at=at(4))
    live = assert_matches_batch_after_every_posting(
        ledger, [incident("I1", o1), incident("I2", o2)]
    )
    assert live.claim("sink", "I1") == 7_000_00
    assert live.claim("sink", "I2") == 11_000_00


def test_dilution_does_not_move_the_claim():
    ledger = world(["v", "B"], {"v": 5_000_00})
    origin = ledger.transfer("v", "B", 5_000_00, occurred_at=at(1))
    for index in range(4):
        ledger.external_credit("B", 100_000_00, source_account_id="ext",
                               occurred_at=at(2 + index))
    live = assert_matches_batch_after_every_posting(ledger, [incident("I1", origin)])
    assert live.claim("B", "I1") == 5_000_00


def test_cycles():
    ledger = world(["v", "A", "B", "C"], {"v": 9_000_00, "A": 3_000_00})
    origin = ledger.transfer("v", "A", 9_000_00, occurred_at=at(1))
    ledger.transfer("A", "B", 12_000_00, occurred_at=at(2))
    ledger.transfer("B", "C", 12_000_00, occurred_at=at(3))
    ledger.transfer("C", "A", 12_000_00, occurred_at=at(4))
    ledger.transfer("A", "B", 6_000_00, occurred_at=at(5))
    assert_matches_batch_after_every_posting(ledger, [incident("I1", origin)])


def test_repeated_downstream_transfers():
    ledger = world(["v1", "v2", "B", "C", "D", "E"], {"v1": 4_000_00, "v2": 6_000_00})
    o1 = ledger.transfer("v1", "B", 4_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 6_000_00, occurred_at=at(2))
    ledger.transfer("B", "C", 10_000_00, occurred_at=at(3))
    ledger.transfer("C", "D", 10_000_00, occurred_at=at(4))
    ledger.transfer("D", "E", 10_000_00, occurred_at=at(5))
    live = assert_matches_batch_after_every_posting(
        ledger, [incident("I1", o1), incident("I2", o2)]
    )
    assert live.claim("E", "I1") == 4_000_00
    assert live.claim("E", "I2") == 6_000_00


def test_reversal_matches_batch_exactly():
    """A reversing journal after lineage has already propagated."""
    ledger = world(["v1", "v2", "B", "C"], {"v1": 8_000_00, "v2": 8_000_00})
    o1 = ledger.transfer("v1", "B", 8_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 8_000_00, occurred_at=at(2))
    ledger.transfer("B", "C", 16_000_00, occurred_at=at(3))
    ledger.transfer("C", "B", 16_000_00, occurred_at=at(4))
    ledger.check_invariants()

    incidents = [incident("I1", o1), incident("I2", o2)]
    live = assert_matches_batch_after_every_posting(ledger, incidents)
    batch = trace_multi(ledger.journals(), incidents, TracingRule.LIBR, accounts_of(ledger))
    for inc in incidents:
        for account in customers_of(ledger):
            assert live.claim(account, inc.id) == int(batch[inc.id].claim_for(account))
        assert live.left_perimeter(inc.id) == int(batch[inc.id].left_perimeter_paise)


def test_account_reaching_exactly_zero():
    ledger = world(["v", "B", "C"], {"v": 3_000_00})
    origin = ledger.transfer("v", "B", 3_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 3_000_00, occurred_at=at(2))
    assert int(ledger.balance("B")) == 0
    live = assert_matches_batch_after_every_posting(ledger, [incident("I1", origin)])
    assert live.claim("B", "I1") == 0
    # An emptied account should not leave an empty shell behind in the state.
    assert "B" not in live.state or live.state["B"] == {}


def test_origin_retagging_incrementally():
    ledger = world(["v1", "B", "C"], {"v1": 10_000_00})
    o1 = ledger.transfer("v1", "B", 10_000_00, occurred_at=at(1))
    o2 = ledger.transfer("B", "C", 10_000_00, occurred_at=at(2))
    live = assert_matches_batch_after_every_posting(
        ledger, [incident("I1", o1), incident("I2", o2)]
    )
    assert live.claim("C", "I2") == 10_000_00
    assert live.retagged("I1") == 10_000_00


def test_rejected_transfer_changes_nothing():
    """A posting the ledger refuses never reaches the maintainer at all."""
    ledger = world(["v", "B", "C"], {"v": 5_000_00})
    origin = ledger.transfer("v", "B", 5_000_00, occurred_at=at(1))
    live = IncrementalLineage([incident("I1", origin)], customers_of(ledger))
    live.apply_all(ledger.journals())
    before = {k: dict(v) for k, v in live.state.items()}

    with pytest.raises(InsufficientFunds):
        ledger.transfer("B", "C", 50_000_00, occurred_at=at(2))

    assert len(ledger.journals()) == 2  # funding + origin; nothing was appended
    assert {k: dict(v) for k, v in live.state.items()} == before


def test_unobserved_history_is_counted_not_raised():
    """Starting mid-history leaves a gap, and the gap is reported."""
    ledger = world(["v", "B", "C"], {"v": 5_000_00, "B": 20_000_00})
    origin = ledger.transfer("v", "B", 5_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 12_000_00, occurred_at=at(2))

    class NothingSeen:
        def journals(self):
            return ()
        def balance(self, account_id):
            return 0

    live = IncrementalLineage([incident("I1", origin)], customers_of(ledger))
    # Declare, explicitly, that the funding postings (seq 0-1) were never
    # observed -- not inferred from apply() being handed seq 2 first.
    live.seed_from(NothingSeen(), accounts_of(ledger), customers_of(ledger),
                   through_seq=1)
    live.apply_all(ledger.journals()[2:])
    assert live.coverage_gap > 0
    assert live.claim("B", "I1") >= 0


def test_apply_does_not_read_the_ledger():
    """apply() must work from the journal it is handed and nothing else."""
    ledger = world(["v", "B", "C"], {"v": 6_000_00})
    origin = ledger.transfer("v", "B", 6_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 2_000_00, occurred_at=at(2))
    journals = ledger.journals()

    live = IncrementalLineage([incident("I1", origin)], customers_of(ledger))
    del ledger  # nothing below may depend on it
    live.apply_all(journals)
    assert live.claim("C", "I1") == 2_000_00
    assert live.claim("B", "I1") == 4_000_00


def test_non_libr_rules_are_not_offered():
    """The collapse is exact for LIBR only; do not imply otherwise."""
    assert IncrementalLineage.rule is TracingRule.LIBR


# ------------------------------------------------------- retroactive seeding


def _random_history(seed_value, moves, injections, names=("B", "C", "D")):
    ledger = world(["v1", "v2", *names],
                   {"v1": 40_000, "v2": 30_000, **{n: 15_000 for n in names}})
    o1 = ledger.transfer("v1", names[0], 40_000, occurred_at=at(1))
    o2 = ledger.transfer("v2", names[1], 30_000, occurred_at=at(2))
    clock = 3
    for account, amount in injections:
        ledger.external_credit(account, amount, source_account_id="ext",
                               occurred_at=at(clock))
        clock += 1
    for sender, receiver, amount in moves:
        if sender == receiver:
            continue
        try:
            if receiver == "ext":
                ledger.external_debit(sender, amount, destination_account_id="ext",
                                      occurred_at=at(clock))
            else:
                ledger.transfer(sender, receiver, amount, occurred_at=at(clock))
        except InsufficientFunds:
            pass
        clock += 1
    return ledger, [incident("I1", o1), incident("I2", o2)]


@pytest.mark.parametrize("cut", [2, 3, 4, 5, 6])
def test_seed_from_a_batch_trace_then_continue(cut):
    """Incidents are reported after the money has moved. That seam must hold.

    Trace in batch up to a point, seed from it, apply the rest one posting at a
    time, and land on exactly what a full batch trace says.
    """
    moves = [("B", "C", 9_000), ("C", "D", 4_000), ("B", "ext", 7_000),
             ("D", "B", 2_500), ("C", "ext", 1_200), ("B", "D", 3_300)]
    injections = [("C", 6_000), ("D", 2_000)]
    ledger, incidents = _random_history(cut, moves, injections)
    journals = ledger.journals()
    accounts = accounts_of(ledger)
    customers = customers_of(ledger)
    if cut >= len(journals):
        pytest.skip("history shorter than the cut")

    class _FrozenLedger:
        """The ledger as it stood at the cut, which is all seeding may see."""

        def __init__(self, upto):
            self._upto = upto

        def journals(self):
            return tuple(journals[: self._upto + 1])

        def balance(self, account_id):
            return sum(
                int(j.delta_for(account_id)) for j in journals[: self._upto + 1]
            )

    live = IncrementalLineage(incidents, customers)
    # _FrozenLedger(cut).journals() is already truncated to the cut, so
    # seed_from computes the batch trace over exactly that prefix -- no
    # through_seq needed. It computes the trace itself now; passing one in is
    # no longer possible.
    live.seed_from(_FrozenLedger(cut), accounts, customers)
    for journal in journals[cut + 1:]:
        live.apply(journal)

    final = trace_multi(journals, incidents, TracingRule.LIBR, accounts)
    for inc in incidents:
        for account in customers:
            assert live.claim(account, inc.id) == int(final[inc.id].claim_for(account)), (
                f"cut {cut}: {account}/{inc.id}"
            )
        assert live.left_perimeter(inc.id) == int(final[inc.id].left_perimeter_paise)


# ------------------------------------------------------ the equality property


ACCOUNTS = ["B", "C", "D", "E"]

_moves = st.lists(
    st.tuples(
        st.sampled_from(ACCOUNTS),
        st.sampled_from([*ACCOUNTS, "ext"]),
        st.integers(min_value=1, max_value=40_000),
    ),
    min_size=0,
    max_size=22,
)
_injections = st.lists(
    st.tuples(st.sampled_from(ACCOUNTS), st.integers(min_value=1, max_value=50_000)),
    max_size=6,
)
_splits = st.lists(
    st.tuples(st.sampled_from(ACCOUNTS), st.integers(min_value=3, max_value=9_999)),
    max_size=4,
)


def _build(moves, injections, splits, incident_count):
    """A ledger containing transfers, external credits and debits, multi-credit
    splits, cycles, and transfers the ledger refuses for insufficient funds."""
    ledger = world(["v1", "v2", *ACCOUNTS],
                   {"v1": 60_000, "v2": 40_000, **{a: 20_000 for a in ACCOUNTS}})
    o1 = ledger.transfer("v1", "B", 60_000, occurred_at=at(1))
    incidents = [incident("I1", o1)]
    if incident_count == 2:
        o2 = ledger.transfer("v2", "C", 40_000, occurred_at=at(2))
        incidents.append(incident("I2", o2))

    clock = 3
    for account, amount in injections:
        ledger.external_credit(account, amount, source_account_id="ext",
                               occurred_at=at(clock))
        clock += 1
    for sender, amount in splits:
        # One debit fanned across three uneven credits, which is where
        # independent rounding used to leak a paisa.
        targets = [a for a in ACCOUNTS if a != sender][:3]
        if len(targets) < 3:
            continue
        third = amount // 3
        remainder = amount - 2 * third
        try:
            ledger.post(
                JournalKind.TRANSFER,
                (
                    Entry(sender, -amount),
                    Entry(targets[0], third),
                    Entry(targets[1], third),
                    Entry(targets[2], remainder),
                ),
                occurred_at=at(clock),
            )
        except InsufficientFunds:
            pass
        clock += 1
    for sender, receiver, amount in moves:
        if sender == receiver:
            continue
        try:
            if receiver == "ext":
                ledger.external_debit(sender, amount, destination_account_id="ext",
                                      occurred_at=at(clock))
            else:
                ledger.transfer(sender, receiver, amount, occurred_at=at(clock))
        except InsufficientFunds:
            pass
        clock += 1
    return ledger, incidents


def _check_equality(ledger, incidents):
    accounts = accounts_of(ledger)
    customers = customers_of(ledger)
    journals = ledger.journals()
    live = IncrementalLineage(incidents, customers)

    for journal in journals:
        live.apply(journal)
        batch = trace_multi(
            journals, incidents, TracingRule.LIBR, accounts, through_seq=journal.seq
        )
        for inc in incidents:
            derivation = batch[inc.id]
            # 1. claims agree, account by account
            for account_id in customers:
                assert live.claim(account_id, inc.id) == int(
                    derivation.claim_for(account_id)
                ), f"seq {journal.seq} {account_id}/{inc.id}"
                # 6. never negative
                assert live.claim(account_id, inc.id) >= 0
            # 2. left_perimeter agrees
            assert live.left_perimeter(inc.id) == int(derivation.left_perimeter_paise)
            # 3. C1: nothing attributed beyond the origin
            accounted = (
                int(derivation.attributable_total)
                + int(derivation.left_perimeter_paise)
            )
            assert accounted <= int(derivation.origin_paise), f"C1 {inc.id}"
        for account_id in customers:
            balance = balance_at(journals, account_id, journal.seq)
            # 4. C2 and 5. C4
            for inc in incidents:
                assert live.claim(account_id, inc.id) <= balance, f"C2 {account_id}"
            assert live.total_claimed(account_id) <= balance, f"C4 {account_id}"


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(moves=_moves, injections=_injections, splits=_splits)
def test_equality_holds_after_every_posting_one_incident(moves, injections, splits):
    ledger, incidents = _build(moves, injections, splits, incident_count=1)
    _check_equality(ledger, incidents)


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(moves=_moves, injections=_injections, splits=_splits)
def test_equality_holds_after_every_posting_two_incidents(moves, injections, splits):
    ledger, incidents = _build(moves, injections, splits, incident_count=2)
    _check_equality(ledger, incidents)
