"""Ordering guards on IncrementalLineage.

The class reproduces trace_multi one posting at a time. trace_multi is pure and
defends its own preconditions -- it sorts by seq before ranking incidents and
takes the minimum seq across an incident's origin journals. The incremental
maintainer, until Step 5, defended neither: apply() had no monotonicity check at
all, and seed_from's _first_seen reconstruction recorded whichever origin
journal it met first in iteration order.

Two reproduced failures, both silent:

  * apply() a journal it already applied -> the affected buckets are
    double-debited and double-credited, no exception, no counter.
  * seed_from a multi-origin incident through a ledger whose .journals()
    returns the origins out of seq order -> _first_seen records a later seq
    than the true earliest, LIBR's oldest-first rank between two incidents
    inverts, and the claim split disagrees with trace_multi on the same
    journals.

Step 5 makes apply() raise OutOfOrderJournal on anything that is not the
immediate successor of the last journal folded in, and makes seed_from sort
before ranking. This file pins both.
"""
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from prima.attribution.incremental import IncrementalLineage, OutOfOrderJournal
from prima.attribution.rules import TracingRule
from prima.attribution.trace import Incident, trace_multi
from prima.ledger.engine import InsufficientFunds, Ledger
from prima.ledger.models import AccountKind

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


def incident(incident_id, *journals, minutes=9999):
    return Incident(
        id=incident_id,
        origin_journal_ids={j.id for j in journals},
        reported_at=at(minutes),
    )


def accounts_of(ledger):
    return {a.id: a for a in ledger.accounts()}


def customers_of(ledger):
    return [a.id for a in ledger.accounts() if a.is_customer]


class ViewLedger:
    """A duck-typed ledger view over a fixed set of journals in a fixed order.

    Same informal interface FrozenLedger / LyingLedger in
    test_seed_composability.py already rely on: .journals() and .balance(id).
    The point of this one is that the caller controls the *order* .journals()
    returns -- which a real DB-backed view has no automatic guarantee about.
    """

    def __init__(self, journals):
        self._journals = tuple(journals)

    def journals(self):
        return self._journals

    def balance(self, account_id):
        return sum(int(j.delta_for(account_id)) for j in self._journals)


def snapshot_state(live):
    """A deep-enough copy of the mutable state to compare before/after."""
    return {
        "state": {k: dict(v) for k, v in live.state.items()},
        "left": {i: live.left_perimeter(i) for i in live._incident_ids},
        "retagged": {i: live.retagged(i) for i in live._incident_ids},
        "coverage_gap": live.coverage_gap,
        "max_seq_seen": live._max_seq_seen,
        "first_seen": dict(live._first_seen),
    }


# --------------------------------------------------------- apply() monotonicity


def test_fresh_object_accepts_seq_zero():
    ledger = world(["v", "B"], {"v": 10_000_00})
    origin = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    live = IncrementalLineage([incident("I1", origin)], customers_of(ledger))

    live.apply(ledger.journals()[0])  # seq 0 -- the funding credit
    assert live._max_seq_seen == 0


def test_fresh_object_rejects_seq_one_skipping_zero():
    ledger = world(["v", "B"], {"v": 10_000_00})
    origin = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    live = IncrementalLineage([incident("I1", origin)], customers_of(ledger))

    with pytest.raises(OutOfOrderJournal, match="expected journal seq 0, got 1"):
        live.apply(ledger.journals()[1])


def test_applying_the_same_journal_twice_raises_and_does_not_mutate():
    ledger = world(["v", "B", "C"], {"v": 10_000_00})
    o1 = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 4_000_00, occurred_at=at(2))
    incidents = [incident("I1", o1)]
    live = IncrementalLineage(incidents, customers_of(ledger))

    journals = ledger.journals()
    live.apply(journals[0])
    live.apply(journals[1])  # seq 1, the origin
    before = snapshot_state(live)

    with pytest.raises(OutOfOrderJournal, match="expected journal seq 2, got 1"):
        live.apply(journals[1])  # same object, second time

    assert snapshot_state(live) == before, "state changed on a rejected apply()"


def test_applying_a_journal_older_than_one_already_applied_raises():
    ledger = world(["v", "B", "C", "D"], {"v": 10_000_00})
    o1 = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 3_000_00, occurred_at=at(2))
    ledger.transfer("C", "D", 1_000_00, occurred_at=at(3))
    live = IncrementalLineage([incident("I1", o1)], customers_of(ledger))

    journals = ledger.journals()
    for j in journals:  # 0, 1, 2, 3 -- all in order
        live.apply(j)
    assert live._max_seq_seen == 3

    with pytest.raises(OutOfOrderJournal, match="expected journal seq 4, got 1"):
        live.apply(journals[1])  # far behind, not merely the previous one


def test_applying_a_journal_that_skips_ahead_raises():
    ledger = world(["v", "B", "C", "D"], {"v": 10_000_00})
    o1 = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 3_000_00, occurred_at=at(2))
    ledger.transfer("C", "D", 1_000_00, occurred_at=at(3))
    live = IncrementalLineage([incident("I1", o1)], customers_of(ledger))

    journals = ledger.journals()
    live.apply(journals[0])
    live.apply(journals[1])
    with pytest.raises(OutOfOrderJournal, match="expected journal seq 2, got 3"):
        live.apply(journals[3])  # a gap -- seq 2 would be silently skipped


# ------------------------------------------ apply() after seed_from


def _seed_history():
    ledger = world(["v1", "v2", "M", "B"], {"v1": 20_000_00, "v2": 20_000_00, "M": 5_000_00})
    o1 = ledger.transfer("v1", "M", 20_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "M", 20_000_00, occurred_at=at(2))
    ledger.transfer("M", "B", 30_000_00, occurred_at=at(3))
    ledger.external_debit("B", 4_000_00, destination_account_id="ext", occurred_at=at(4))
    ledger.check_invariants()
    return ledger, [incident("I1", o1), incident("I2", o2)]


def _frozen(journals, cut):
    return ViewLedger(j for j in journals if j.seq <= cut)


def test_apply_immediately_after_seed_requires_cut_plus_one():
    ledger, incidents = _seed_history()
    journals = ledger.journals()
    cut = 2
    live = IncrementalLineage(incidents, customers_of(ledger))
    live.seed_from(_frozen(journals, cut), accounts_of(ledger), customers_of(ledger))
    assert live._max_seq_seen == cut

    live.apply(journals[cut + 1])  # seq 3 -- succeeds, the existing pattern
    assert live._max_seq_seen == cut + 1


def test_apply_after_seed_rejects_a_journal_the_seed_already_covered():
    ledger, incidents = _seed_history()
    journals = ledger.journals()
    cut = 2
    live = IncrementalLineage(incidents, customers_of(ledger))
    live.seed_from(_frozen(journals, cut), accounts_of(ledger), customers_of(ledger))

    with pytest.raises(OutOfOrderJournal, match="expected journal seq 3, got 2"):
        live.apply(journals[cut])          # seq == cut, already in the seed
    with pytest.raises(OutOfOrderJournal, match="expected journal seq 3, got 1"):
        live.apply(journals[cut - 1])      # seq < cut


def test_seed_on_empty_ledger_then_first_apply_still_requires_seq_zero():
    ledger = world(["v", "B"])  # nothing funded, no journals
    assert ledger.journals() == ()
    live = IncrementalLineage([], customers_of(ledger))
    live.seed_from(ViewLedger(()), accounts_of(ledger), customers_of(ledger))
    assert live._max_seq_seen == -1

    real = world(["v", "B"], {"v": 1_000_00})       # seq 0: funding
    real.transfer("v", "B", 400_00, occurred_at=at(1))  # seq 1
    seq0, seq1 = real.journals()[0], real.journals()[1]
    with pytest.raises(OutOfOrderJournal, match="expected journal seq 0, got 1"):
        live.apply(seq1)
    live.apply(seq0)  # seq 0 -- fine


# --------------------------------- seed_from sorts before ranking (multi-origin)


def _two_origin_rank_scenario():
    """Incident A has two origin journals (seq 4 and seq 6); incident B has one
    (seq 5). True rank: A is older -- min(4, 6) = 4 < 5. Both land on M, which
    also holds its own money. An outflow then encroaches past the own money into
    exactly one incident's pool, so which incident LIBR treats as older changes
    the split.
    """
    ledger = world(["vA1", "vA2", "vB", "M", "sink"],
                   {"vA1": 20_000_00, "vA2": 20_000_00, "vB": 20_000_00, "M": 10_000_00})
    jA1 = ledger.transfer("vA1", "M", 10_000_00, occurred_at=at(4))   # seq 4
    jB = ledger.transfer("vB", "M", 10_000_00, occurred_at=at(5))     # seq 5
    jA2 = ledger.transfer("vA2", "M", 10_000_00, occurred_at=at(6))   # seq 6
    ledger.transfer("M", "sink", 22_000_00, occurred_at=at(7))        # seq 7: own 10k + 12k
    ledger.check_invariants()
    return ledger, incident("A", jA1, jA2), incident("B", jB)


def test_two_origin_incident_first_seen_is_the_minimum_regardless_of_order():
    ledger, A, B = _two_origin_rank_scenario()
    journals = ledger.journals()
    customers = customers_of(ledger)
    accounts = accounts_of(ledger)

    def origins_out_of_order(cut):
        kept = [j for j in journals if j.seq <= cut]
        # deliberately put A's later origin (seq 6) before its earlier one (seq 4)
        return ViewLedger(sorted(kept, key=lambda j: {6: -1, 4: 99}.get(j.seq, j.seq)))

    cut = 6
    live = IncrementalLineage([A, B], customers)
    live.seed_from(origins_out_of_order(cut), accounts, customers)

    # min(4, 6) == 4, not "whichever came first in the shuffled view" (== 6)
    assert live._first_seen["A"] == 4
    assert live._first_seen["B"] == 5

    live.apply(journals[7])  # the encroaching outflow

    reference = trace_multi(journals, [A, B], TracingRule.LIBR, accounts)
    for inc_id in ("A", "B"):
        d = reference[inc_id]
        for account in customers:
            assert live.claim(account, inc_id) == int(d.claim_for(account)), (
                f"{account}/{inc_id}"
            )
        assert live.left_perimeter(inc_id) == int(d.left_perimeter_paise)

    # and the split is the one where A (older) took the encroachment, not B
    assert live.claim("M", "A") == 8_000_00
    assert live.claim("M", "B") == 10_000_00
    assert live.claim("sink", "A") == 12_000_00
    assert live.claim("sink", "B") == 0


def test_two_origin_incident_adjacent_vs_far_apart_give_the_same_first_seen():
    """Whether the two origins are next to each other or spread out, _first_seen
    must be the earliest of them -- the gap between them is irrelevant."""
    # adjacent: the two origins are consecutive journals
    la = world(["a1", "a2", "M"], {"a1": 10_000_00, "a2": 10_000_00, "M": 1_000_00})
    j1 = la.transfer("a1", "M", 10_000_00, occurred_at=at(4))
    j2 = la.transfer("a2", "M", 10_000_00, occurred_at=at(5))
    earliest_adj = min(j1.seq, j2.seq)
    A_adj = incident("A", j1, j2)
    live_a = IncrementalLineage([A_adj], customers_of(la))
    live_a.seed_from(ViewLedger(reversed(la.journals())), accounts_of(la), customers_of(la))
    assert live_a._first_seen["A"] == earliest_adj

    # far apart: several unrelated journals between the two origins
    lf = world(["a1", "a2", "M", "x"], {"a1": 10_000_00, "a2": 10_000_00, "M": 1_000_00})
    k1 = lf.transfer("a1", "M", 10_000_00, occurred_at=at(4))
    lf.transfer("M", "x", 2_000_00, occurred_at=at(5))
    lf.transfer("x", "M", 1_000_00, occurred_at=at(6))
    lf.transfer("M", "x", 1_000_00, occurred_at=at(7))
    k2 = lf.transfer("a2", "M", 10_000_00, occurred_at=at(8))
    earliest_far = min(k1.seq, k2.seq)
    assert k2.seq - k1.seq >= 4  # genuinely far apart
    A_far = incident("A", k1, k2)
    live_f = IncrementalLineage([A_far], customers_of(lf))
    live_f.seed_from(ViewLedger(reversed(lf.journals())), accounts_of(lf), customers_of(lf))
    assert live_f._first_seen["A"] == earliest_far
    assert earliest_adj == earliest_far == k1.seq == j1.seq


def test_single_origin_incident_is_unaffected_by_an_out_of_order_view():
    """This shape was already safe before the sort -- confirm it stays safe."""
    ledger = world(["v", "M", "B"], {"v": 10_000_00, "M": 2_000_00})
    origin = ledger.transfer("v", "M", 10_000_00, occurred_at=at(1))
    ledger.transfer("M", "B", 8_000_00, occurred_at=at(2))
    inc = incident("I1", origin)
    accounts = accounts_of(ledger)
    customers = customers_of(ledger)

    forward = IncrementalLineage([inc], customers)
    forward.seed_from(ViewLedger(ledger.journals()), accounts, customers)
    backward = IncrementalLineage([inc], customers)
    backward.seed_from(ViewLedger(list(reversed(ledger.journals()))), accounts, customers)

    assert forward._first_seen == backward._first_seen == {"I1": origin.seq}
    for account in customers:
        assert forward.claim(account, "I1") == backward.claim(account, "I1")


# --------------------------------- the guard the sort must not disturb


def test_existing_inconsistent_ledger_assertion_still_fires():
    """test_negative_own_money_assertion_still_fires_for_an_inconsistent_ledger
    in test_seed_composability.py, restated here so a regression shows up in
    either file. The new sort must not swallow the C4 guard."""
    ledger = world(["v1", "v2", "M"], {"v1": 30_000_00, "v2": 30_000_00})
    o1 = ledger.transfer("v1", "M", 30_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "M", 30_000_00, occurred_at=at(2))
    incidents = [incident("I1", o1), incident("I2", o2)]

    class LyingLedger:
        def journals(self):
            return ledger.journals()

        def balance(self, account_id):
            return 100 if account_id == "M" else int(ledger.balance(account_id))

    live = IncrementalLineage(incidents, customers_of(ledger))
    with pytest.raises(AssertionError, match="claims total"):
        live.seed_from(LyingLedger(), accounts_of(ledger), customers_of(ledger))


# ------------------------------- seed_from(through_seq=...) -- the position marker
#
# ADDITIONAL CONTRACT (Step 5):
#   through_seq must be an int >= -1.
#     -1  -> no observed history before the first journal; next apply() takes seq 0.
#     0+  -> seq 0..through_seq are intentionally unobserved; next apply() takes
#            exactly through_seq + 1.
#   < -1        -> ValueError, raised before any state is mutated.
#   non-integer -> ValueError/TypeError, likewise before mutation.


def _minus_history():
    """funding at seq 0-2, origin at seq 3, then two hops."""
    ledger = world(["v", "M", "B"], {"v": 20_000_00, "M": 5_000_00})
    origin = ledger.transfer("v", "M", 20_000_00, occurred_at=at(3))   # seq 2
    ledger.transfer("M", "B", 12_000_00, occurred_at=at(4))            # seq 3
    ledger.external_debit("B", 3_000_00, destination_account_id="ext", occurred_at=at(5))  # seq 4
    ledger.check_invariants()
    return ledger, incident("I1", origin)


def test_through_seq_minus_one_makes_next_apply_expect_seq_zero():
    ledger, inc = _minus_history()
    journals = ledger.journals()
    live = IncrementalLineage([inc], customers_of(ledger))
    live.seed_from(ViewLedger(()), accounts_of(ledger), customers_of(ledger),
                   through_seq=-1)
    assert live._max_seq_seen == -1

    with pytest.raises(OutOfOrderJournal, match="expected journal seq 0, got 1"):
        live.apply(journals[1])
    live.apply(journals[0])  # seq 0 -- accepted


def test_through_seq_zero_plus_makes_next_apply_exactly_that_plus_one():
    ledger, inc = _minus_history()
    journals = ledger.journals()
    cut = 3  # seq 0..3 declared covered by the seed
    live = IncrementalLineage([inc], customers_of(ledger))
    live.seed_from(_frozen(journals, cut), accounts_of(ledger), customers_of(ledger),
                   through_seq=cut)
    assert live._max_seq_seen == cut

    with pytest.raises(OutOfOrderJournal, match=f"expected journal seq {cut + 1}, got {cut}"):
        live.apply(journals[cut])          # already covered
    with pytest.raises(OutOfOrderJournal, match=f"expected journal seq {cut + 1}, got {cut - 1}"):
        live.apply(journals[cut - 1])      # behind
    live.apply(journals[cut + 1])          # exactly through_seq + 1 -- accepted
    assert live._max_seq_seen == cut + 1


def test_through_seq_overrides_an_inferred_position_that_would_fall_short():
    """The reason the parameter exists: a truncated view missing its own last
    journal would infer max(seq) too low and let apply() re-consume a posting
    the seed already covered."""
    ledger, inc = _minus_history()
    journals = ledger.journals()
    # A view that stops at seq 2 but the caller knows the seed conceptually
    # covers through seq 3 (they applied seq 3's effect out of band, say).
    view = ViewLedger(j for j in journals if j.seq <= 2)
    live = IncrementalLineage([inc], customers_of(ledger))

    # inferred position would be 2 -> next apply seq 3 (a replay of covered work)
    live_inferred = IncrementalLineage([inc], customers_of(ledger))
    live_inferred.seed_from(view, accounts_of(ledger), customers_of(ledger))
    assert live_inferred._max_seq_seen == 2

    # with through_seq the position is authoritative
    live.seed_from(view, accounts_of(ledger), customers_of(ledger), through_seq=3)
    assert live._max_seq_seen == 3
    with pytest.raises(OutOfOrderJournal, match="expected journal seq 4, got 3"):
        live.apply(journals[3])
    live.apply(journals[4])


def test_through_seq_default_none_is_the_inferred_max_unchanged():
    ledger, inc = _minus_history()
    journals = ledger.journals()
    cut = 3
    a = IncrementalLineage([inc], customers_of(ledger))
    a.seed_from(_frozen(journals, cut), accounts_of(ledger), customers_of(ledger))
    b = IncrementalLineage([inc], customers_of(ledger))
    b.seed_from(_frozen(journals, cut), accounts_of(ledger), customers_of(ledger),
               through_seq=None)
    assert a._max_seq_seen == b._max_seq_seen == cut
    assert snapshot_state(a) == snapshot_state(b)


def test_through_seq_on_an_empty_ledger_with_minus_one_lands_at_minus_one():
    ledger = world(["v", "B"])  # no journals
    live = IncrementalLineage([], customers_of(ledger))
    live.seed_from(ViewLedger(()), accounts_of(ledger), customers_of(ledger),
                   through_seq=-1)
    assert live._max_seq_seen == -1


@pytest.mark.parametrize("bad", [-2, -3, -100])
def test_through_seq_below_minus_one_raises_value_error_before_mutating(bad):
    ledger, inc = _minus_history()
    live = IncrementalLineage([inc], customers_of(ledger))
    before = snapshot_state(live)

    with pytest.raises(ValueError, match=r"through_seq must be >= -1"):
        live.seed_from(_frozen(ledger.journals(), 3), accounts_of(ledger),
                       customers_of(ledger), through_seq=bad)

    assert snapshot_state(live) == before, "state changed on a rejected through_seq"


@pytest.mark.parametrize(
    "bad",
    [1.5, 0.0, -1.0, "3", "-1", [1], (1,), {1}, object(), True, False],
    ids=["float_1.5", "float_0.0", "float_-1.0", "str_3", "str_-1",
         "list", "tuple", "set", "object", "bool_true", "bool_false"],
)
def test_through_seq_non_integer_raises_before_mutating(bad):
    """Floats, strings, bools -- anything that is not a plain int -- must raise
    (ValueError or TypeError) rather than being coerced into _max_seq_seen.
    bool is rejected too: True would otherwise silently mean position 1."""
    ledger, inc = _minus_history()
    live = IncrementalLineage([inc], customers_of(ledger))
    before = snapshot_state(live)

    with pytest.raises((ValueError, TypeError)):
        live.seed_from(_frozen(ledger.journals(), 3), accounts_of(ledger),
                       customers_of(ledger), through_seq=bad)

    assert snapshot_state(live) == before, "state changed on a rejected through_seq"


def test_through_seq_zero_is_a_valid_integer_not_rejected_as_falsey():
    """0 is a legitimate value -- seq 0 is unobserved, next apply is seq 1.
    It must not be mistaken for 'unset' the way None is."""
    ledger, inc = _minus_history()
    journals = ledger.journals()
    live = IncrementalLineage([inc], customers_of(ledger))
    live.seed_from(_frozen(journals, 0), accounts_of(ledger), customers_of(ledger),
                   through_seq=0)
    assert live._max_seq_seen == 0
    with pytest.raises(OutOfOrderJournal, match="expected journal seq 1, got 0"):
        live.apply(journals[0])
    live.apply(journals[1])


def test_through_seq_declares_an_unobserved_prefix_and_the_gap_is_counted():
    """The scenario Step 5's review flagged: an object that genuinely never saw
    the funding postings. Declared via through_seq, the run is well-formed and
    the unaccounted outflow lands in coverage_gap rather than raising.

    Funding at seq 0, 1; I1's origin at seq 2; at seq 3 B spends money it was
    funded with at seq 1 -- a posting this object never observed.
    """
    ledger = world(["v", "M", "B"], {"v": 5_000_00, "B": 20_000_00})
    origin = ledger.transfer("v", "B", 5_000_00, occurred_at=at(3))   # seq 2
    ledger.transfer("B", "M", 12_000_00, occurred_at=at(4))           # seq 3
    journals = ledger.journals()

    class NothingSeen:
        def journals(self):
            return ()

        def balance(self, account_id):
            return 0

    live = IncrementalLineage([incident("I1", origin)], customers_of(ledger))
    live.seed_from(NothingSeen(), accounts_of(ledger), customers_of(ledger),
                   through_seq=1)  # seq 0, 1 (the funding) never observed
    assert live._max_seq_seen == 1

    live.apply(journals[2])  # seq 2: v -> B, I1's origin
    live.apply(journals[3])  # seq 3: B -> M 12,000, B only has I1's 5,000 tracked

    # coverage_gap counts every paisa spent that the observed stream cannot
    # account for: v's 5,000 (funded at the unseen seq 0) as it leaves at seq 2,
    # plus 7,000 of B's 12,000 outflow at seq 3 that its own funding (unseen
    # seq 1) would have covered. Counted, not raised -- which is the point.
    assert live.coverage_gap == 12_000_00
    assert live.claim("B", "I1") >= 0
    assert live.claim("M", "I1") >= 0


def test_seed_from_resets_coverage_gap():
    """seed_from re-initialises the object. coverage_gap is part of that state
    and was the one counter it forgot to clear -- a re-seed would carry a stale
    gap from the previous run forward into the new one."""
    ledger = world(["v", "M", "B"], {"v": 5_000_00, "B": 20_000_00})
    origin = ledger.transfer("v", "B", 5_000_00, occurred_at=at(3))   # seq 2
    ledger.transfer("B", "M", 12_000_00, occurred_at=at(4))           # seq 3
    journals = ledger.journals()

    class NothingSeen:
        def journals(self):
            return ()

        def balance(self, account_id):
            return 0

    live = IncrementalLineage([incident("I1", origin)], customers_of(ledger))
    live.seed_from(NothingSeen(), accounts_of(ledger), customers_of(ledger),
                   through_seq=1)
    live.apply_all(j for j in journals if j.seq > 1)
    assert live.coverage_gap > 0                      # a real gap accrued

    live.seed_from(NothingSeen(), accounts_of(ledger), customers_of(ledger),
                   through_seq=1)                     # identical re-seed
    assert live.coverage_gap == 0, "re-seed carried a stale coverage_gap forward"


def test_through_seq_from_a_live_untruncated_ledger_matches_a_truncated_view():
    """through_seq must define ONE observation boundary for ALL seed state --
    trace, _first_seen, own-money reconstruction, and the next apply()
    position -- not merely for attribution. Before the fix, seed_from used
    ledger.balance() (the ledger's CURRENT, present-day state) even when
    through_seq restricted everything else to a historical point, inflating
    own money by whatever activity happened after through_seq.

    Ground truth: seeding from an already-truncated view at N. Under test:
    seeding from the SAME, live, untruncated ledger with through_seq=N. The
    two must produce byte-identical seeded state.
    """
    ledger = world(["v", "M", "B", "C"], {"v": 20_000_00, "M": 5_000_00})
    origin = ledger.transfer("v", "M", 20_000_00, occurred_at=at(1))    # seq2
    ledger.transfer("M", "B", 10_000_00, occurred_at=at(2))             # seq3 -- N = 3
    # Large activity AFTER N that must not leak into the seeded state:
    ledger.external_credit("M", 500_000_00, source_account_id="ext", occurred_at=at(3))  # seq4
    ledger.transfer("M", "C", 300_000_00, occurred_at=at(4))            # seq5
    ledger.check_invariants()

    journals = ledger.journals()
    N = 3
    incidents = [incident("I1", origin)]
    accounts = accounts_of(ledger)
    customers = customers_of(ledger)

    truncated = IncrementalLineage(incidents, customers)
    truncated.seed_from(_frozen(journals, N), accounts, customers)   # ground truth

    live = IncrementalLineage(incidents, customers)
    live.seed_from(ledger, accounts, customers, through_seq=N)       # live, untruncated ledger

    assert live._max_seq_seen == truncated._max_seq_seen == N
    for account in customers:
        assert live.own_money(account) == truncated.own_money(account), account
        assert live.claim(account, "I1") == truncated.claim(account, "I1"), account
    assert live.left_perimeter("I1") == truncated.left_perimeter("I1")
    assert live.retagged("I1") == truncated.retagged("I1")

    # Demonstrate the OLD implementation's actual failure mode, not a
    # hypothetical: own money computed from ledger.balance() directly,
    # ignoring through_seq, on this exact scenario.
    tagged = int(trace_multi(journals, incidents, TracingRule.LIBR, accounts,
                              through_seq=N)["I1"].claim_for("M"))
    old_buggy_own_for_M = int(ledger.balance("M")) - tagged
    assert old_buggy_own_for_M != truncated.own_money("M"), (
        "scenario must actually exercise the bug -- if equal, the post-N "
        "activity didn't move M's balance enough to matter"
    )


# ---------------------------------------------------------------- property


ACCOUNTS = ["M", "B", "C", "D"]


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    n_incidents=st.integers(min_value=2, max_value=3),
    targets=st.lists(st.sampled_from(ACCOUNTS), min_size=3, max_size=3),
    moves=st.lists(
        st.tuples(
            st.sampled_from(ACCOUNTS),
            st.sampled_from([*ACCOUNTS, "ext"]),
            st.integers(min_value=1, max_value=40_000),
        ),
        min_size=1,
        max_size=16,
    ),
    injections=st.lists(
        st.tuples(st.sampled_from(ACCOUNTS), st.integers(min_value=1, max_value=50_000)),
        max_size=4,
    ),
    cut_fraction=st.floats(min_value=0.0, max_value=1.0),
    replay_pick=st.floats(min_value=0.0, max_value=1.0),
)
def test_a_correct_seed_then_apply_run_rejects_a_replayed_journal(
    n_incidents, targets, moves, injections, cut_fraction, replay_pick
):
    """Build a valid seed-then-apply run, then re-feed one already-applied
    journal. It must raise OutOfOrderJournal -- not silently double-count, not
    silently pass -- and the state must be exactly what it was before the
    rejected call.
    """
    victims = [f"v{i}" for i in range(n_incidents)]
    ledger = world(
        [*victims, *ACCOUNTS],
        {**{v: 60_000 for v in victims}, **{a: 20_000 for a in ACCOUNTS}},
    )
    incidents = []
    for index, victim in enumerate(victims):
        origin = ledger.transfer(victim, targets[index], 60_000, occurred_at=at(1 + index))
        incidents.append(incident(f"I{index}", origin))

    clock = 10
    for account, amount in injections:
        ledger.external_credit(account, amount, source_account_id="ext", occurred_at=at(clock))
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

    ledger.check_invariants()
    journals = ledger.journals()
    accounts = accounts_of(ledger)
    customers = customers_of(ledger)
    last = journals[-1].seq
    cut = int(round(cut_fraction * last))

    live = IncrementalLineage(incidents, customers)
    live.seed_from(_frozen(journals, cut), accounts, customers)
    applied = []
    for journal in journals:
        if journal.seq > cut:
            live.apply(journal)
            applied.append(journal)

    # sanity: the correct run matches the full batch
    reference = trace_multi(journals, incidents, TracingRule.LIBR, accounts)
    for inc in incidents:
        for account in customers:
            assert live.claim(account, inc.id) == int(
                reference[inc.id].claim_for(account)
            )

    if not applied:
        # nothing was applied after the seed; re-applying the seed's last
        # journal (seq == cut) must still be rejected
        if cut >= 0:
            before = snapshot_state(live)
            with pytest.raises(OutOfOrderJournal):
                live.apply(journals[cut])
            assert snapshot_state(live) == before
        return

    victim_journal = applied[min(int(replay_pick * len(applied)), len(applied) - 1)]
    before = snapshot_state(live)
    with pytest.raises(OutOfOrderJournal):
        live.apply(victim_journal)
    assert snapshot_state(live) == before, "state changed on a rejected replay"
