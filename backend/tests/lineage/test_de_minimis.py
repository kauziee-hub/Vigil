"""The de-minimis floor (spec §6.2).

Conservation (§3) bounds the trace in *value* -- nothing is created or lost.
It does not bound it in *cardinality*. An adversary who picks the split depth
grows the parcel list without bound: branching factor 2 to depth 40 is 2^40
leaves. The floor closes that: any share a split would credit to a customer
account below the floor F is not tracked as its own parcel -- its value goes
to that incident's ``extinguished_paise`` instead. Because splitting divides
value and every tracked parcel is >= F, an origin of value V can produce at
most V // F tracked parcels, whatever depth the adversary picks.

This is a trace.py-only change. The incremental engine is already immune
(§7.1 -- it collapses to {incident: paise} regardless of parcel count) and is
not touched.
"""
import time
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from prima.attribution.rules import DEFAULT_RULES, TracingRule
from prima.attribution.trace import Incident, trace, trace_envelope, trace_multi
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


def incident(incident_id, journal, minutes=9999):
    return Incident(
        id=incident_id, origin_journal_ids={journal.id}, reported_at=at(minutes)
    )


def accounts_of(ledger):
    return {a.id: a for a in ledger.accounts()}


def conserves_exactly(derivation) -> bool:
    """sum(claims) + left_perimeter + extinguished == origin, exact.

    Holds on every scenario without origin re-tagging -- which is every
    scenario here. (With retagging the identity needs a + retagged_paise term;
    see the report and spec §5.3.3. None of these scenarios retag.)
    """
    claimed = sum(int(c.amount_paise) for c in derivation.claims)
    return (
        claimed
        + int(derivation.left_perimeter_paise)
        + int(derivation.extinguished_paise)
        == int(derivation.origin_paise)
    )


# --------------------------------------------------------- scenario builders


class _Clock:
    def __init__(self):
        self.n = 2

    def tick(self):
        self.n += 1
        return at(self.n)


def build_comb(origin_paise: int, floor: int, requested_depth: int):
    """Branching factor 2, genuine depth. Each spine node sends exactly ``floor``
    to a fresh terminal leaf and the rest to the next spine node. Reaches
    ``requested_depth`` levels (or terminates earlier when the remainder can no
    longer feed a leaf). The terminal remainder, if below the floor, splits in
    half so both halves are extinguished -- so extinguished_paise is exercised
    as a real, non-degenerate term.
    """
    ledger = world(["src", "s0"])
    ledger.external_credit("src", origin_paise, source_account_id="ext", occurred_at=at(0))
    origin = ledger.transfer("src", "s0", origin_paise, occurred_at=at(1))
    clock = _Clock()

    def spine(node, value, depth):
        if depth == 0 or value < floor:
            return
        if value < 2 * floor:
            a, b = f"{node}_a", f"{node}_b"
            ledger.open_account(a)
            ledger.open_account(b)
            ledger.post(
                JournalKind.TRANSFER,
                (Entry(node, -value), Entry(a, value // 2), Entry(b, value - value // 2)),
                occurred_at=clock.tick(),
            )
            return
        leaf, nxt = f"{node}_L", f"{node}_N"
        ledger.open_account(leaf)
        ledger.open_account(nxt)
        ledger.post(
            JournalKind.TRANSFER,
            (Entry(node, -value), Entry(leaf, floor), Entry(nxt, value - floor)),
            occurred_at=clock.tick(),
        )
        spine(nxt, value - floor, depth - 1)

    spine("s0", origin_paise, requested_depth)
    return ledger, incident("I1", origin)


def build_balanced_tree(depth: int):
    """A pure binary split tree: value 2^depth into the root, halved at every
    level, 2^depth leaves each holding exactly 1 paisa. Journal count is
    2^depth - 1 -- keep depth modest."""
    value = 1 << depth
    ledger = world(["src", "root"])
    ledger.external_credit("src", value, source_account_id="ext", occurred_at=at(0))
    origin = ledger.transfer("src", "root", value, occurred_at=at(1))
    clock = _Clock()

    def rec(node, v, d):
        if d == 0 or v <= 1:
            return
        half = v // 2
        left, right = f"{node}0", f"{node}1"
        ledger.open_account(left)
        ledger.open_account(right)
        ledger.post(
            JournalKind.TRANSFER,
            (Entry(node, -v), Entry(left, half), Entry(right, v - half)),
            occurred_at=clock.tick(),
        )
        rec(left, half, d - 1)
        rec(right, v - half, d - 1)

    rec("root", value, depth)
    return ledger, incident("I1", origin)


# ------------------------------------------------------ 1. adversarial bound


def test_adversarial_split_to_depth_40_is_bounded_by_the_floor():
    """The scenario the spec's own numbers describe: branching factor 2, depth
    40. With a floor, the parcel count is bounded by origin // floor -- NOT by
    2^40 -- and the trace runs in milliseconds, not the 'astronomically large'
    the spec warns about."""
    origin_paise = 405_000        # Rs 4,050
    floor = 10_000                # Rs 100  ->  origin // floor = 40
    ledger, inc = build_comb(origin_paise, floor, requested_depth=40)
    accounts = accounts_of(ledger)

    start = time.perf_counter()
    d = trace_multi(ledger.journals(), [inc], TracingRule.LIBR, accounts,
                    de_minimis_floor=floor)["I1"]
    elapsed = time.perf_counter() - start

    # In a pure split tree every surviving parcel sits on its own leaf account,
    # so the number of claims IS the parcel count.
    parcel_count = len(d.claims)
    print(
        f"\n[adversarial] requested depth 40 -> journals built = {len(ledger.journals())}, "
        f"parcel count = {parcel_count}, origin // floor = {origin_paise // floor}, "
        f"trace wall time = {elapsed * 1000:.2f} ms"
    )

    assert parcel_count <= origin_paise // floor
    assert parcel_count < 2 ** 40
    assert elapsed < 2.0, f"trace took {elapsed:.2f}s"
    assert all(int(c.amount_paise) >= 0 for c in d.claims)
    assert int(d.extinguished_paise) > 0     # the remainder really was floored
    assert conserves_exactly(d)


def test_deep_build_pruned_tree_still_bounded_regardless_of_requested_depth():
    """A balanced binary tree, requested depth 40, with the construction pruned
    where a child would fall below the floor (the engine would extinguish it
    anyway -- see the exponential test for the engine doing it on an unpruned
    tree). The point: depth 40 does not mean 2^40 anything."""
    origin_paise = 1_000_000      # Rs 10,000
    floor = 10_000                # origin // floor = 100
    ledger = world(["src", "root"])
    ledger.external_credit("src", origin_paise, source_account_id="ext", occurred_at=at(0))
    origin = ledger.transfer("src", "root", origin_paise, occurred_at=at(1))
    clock = _Clock()

    def rec(node, v, d):
        if d == 0 or v < floor:
            return
        half = v // 2
        left, right = f"{node}0", f"{node}1"
        ledger.open_account(left)
        ledger.open_account(right)
        ledger.post(
            JournalKind.TRANSFER,
            (Entry(node, -v), Entry(left, half), Entry(right, v - half)),
            occurred_at=clock.tick(),
        )
        if half >= floor:
            rec(left, half, d - 1)
        if v - half >= floor:
            rec(right, v - half, d - 1)

    rec("root", origin_paise, 40)
    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", origin)], TracingRule.LIBR,
                    accounts, de_minimis_floor=floor)["I1"]

    assert len(ledger.journals()) < 4 * (origin_paise // floor)
    assert len(d.claims) <= origin_paise // floor
    assert conserves_exactly(d)


# ------------------------------------------------ 2. exponential without a floor


def test_balanced_binary_tree_without_a_floor_is_exponential_in_depth():
    """The attack is real: no floor, the parcel count is exactly 2^depth and
    doubles with every extra level."""
    counts = {}
    for depth in (8, 10, 12):
        ledger, inc = build_balanced_tree(depth)
        d = trace_multi(ledger.journals(), [inc], TracingRule.LIBR,
                        accounts_of(ledger))["I1"]
        counts[depth] = len(d.claims)

    assert counts == {8: 256, 10: 1024, 12: 4096}
    assert counts[10] == 4 * counts[8]     # +2 levels -> x4, i.e. 2^depth
    assert counts[12] == 4 * counts[10]

    # Same depth-12 tree, now with a floor: the engine does the extinguishing
    # on an UNPRUNED tree and the count collapses.
    ledger, inc = build_balanced_tree(12)
    floored = trace_multi(ledger.journals(), [inc], TracingRule.LIBR,
                          accounts_of(ledger), de_minimis_floor=64)["I1"]
    assert len(floored.claims) < 4096
    assert len(floored.claims) <= int(floored.origin_paise) // 64
    assert conserves_exactly(floored)


# --------------------------------------------- 3. conservation, extinguished term


def test_conservation_exact_on_the_adversarial_scenario():
    ledger, inc = build_comb(400_000, 10_000, requested_depth=40)
    d = trace_multi(ledger.journals(), [inc], TracingRule.LIBR,
                    accounts_of(ledger), de_minimis_floor=10_000)["I1"]
    claimed = sum(int(c.amount_paise) for c in d.claims)
    assert (
        claimed + int(d.left_perimeter_paise) + int(d.extinguished_paise)
        == int(d.origin_paise)
    )


def test_conservation_exact_on_a_worked_example_with_the_floor_biting():
    """test_two_incidents_no_longer_claim_the_same_rupees' shape, but the mule
    fans out into shares that fall below the floor so extinguished is a real
    term rather than zero."""
    ledger = world(["v1", "v2", "mule", "a", "b", "c"],
                   {"v1": 30_000_00, "v2": 30_000_00})
    o1 = ledger.transfer("v1", "mule", 30_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "mule", 30_000_00, occurred_at=at(2))
    # mule (60,000) fans out three ways: two big shares, one tiny one
    ledger.post(
        JournalKind.TRANSFER,
        (Entry("mule", -60_000_00), Entry("a", 30_000_00), Entry("b", 29_999_00),
         Entry("c", 1_00)),
        occurred_at=at(3),
    )
    ledger.check_invariants()

    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts, de_minimis_floor=50_00)  # Rs 50 floor
    for inc_id in ("I1", "I2"):
        deriv = d[inc_id]
        claimed = sum(int(c.amount_paise) for c in deriv.claims)
        assert (
            claimed + int(deriv.left_perimeter_paise) + int(deriv.extinguished_paise)
            == int(deriv.origin_paise)
        ), inc_id
    # the Rs 1 share to c is below the Rs 50 floor -> extinguished, for whichever
    # incident LIBR assigned that sliver to
    total_extinguished = sum(int(d[i].extinguished_paise) for i in ("I1", "I2"))
    assert total_extinguished == 1_00


# ---------------------------------------- 4. default None reproduces existing


def test_floor_none_is_identical_to_omitting_the_argument():
    ledger = world(["v", "B", "C", "D"], {"v": 50_000_00, "B": 5_000_00})
    origin = ledger.transfer("v", "B", 50_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 20_000_00, occurred_at=at(2))
    ledger.external_debit("B", 10_000_00, destination_account_id="ext", occurred_at=at(3))
    ledger.transfer("B", "D", 15_000_00, occurred_at=at(4))
    accounts = accounts_of(ledger)
    inc = incident("I1", origin)

    for rule in list(TracingRule):
        omitted = trace_multi(ledger.journals(), [inc], rule, accounts)["I1"]
        explicit_none = trace_multi(ledger.journals(), [inc], rule, accounts,
                                    de_minimis_floor=None)["I1"]
        assert omitted.payload() == explicit_none.payload(), rule
        assert omitted.digest == explicit_none.digest, rule
        assert int(omitted.extinguished_paise) == 0


def test_extinguished_paise_defaults_to_zero_and_is_in_the_payload():
    ledger = world(["v", "B"], {"v": 10_000_00})
    origin = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    d = trace_multi(ledger.journals(), [incident("I1", origin)], TracingRule.LIBR,
                    accounts_of(ledger))["I1"]
    assert int(d.extinguished_paise) == 0
    assert d.payload()["extinguished_paise"] == 0


def test_floor_threads_through_trace_and_trace_envelope():
    ledger, inc = build_comb(200_000, 10_000, requested_depth=20)
    accounts = accounts_of(ledger)
    journals = ledger.journals()

    ref = trace_multi(journals, [inc], TracingRule.LIBR, accounts, de_minimis_floor=10_000)["I1"]

    via_trace = trace(journals, inc, TracingRule.LIBR, accounts, de_minimis_floor=10_000)
    assert via_trace.payload() == ref.payload()

    env = trace_envelope(journals, inc, [TracingRule.LIBR], accounts, de_minimis_floor=10_000)
    assert env[TracingRule.LIBR].payload() == ref.payload()


# ------------------------------------------------------------- 5. validation


@pytest.mark.parametrize("bad", [0, -1, -500])
def test_floor_must_be_positive(bad):
    ledger = world(["v", "B"], {"v": 10_000_00})
    origin = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    with pytest.raises(ValueError, match="de_minimis_floor must be >= 1"):
        trace_multi(ledger.journals(), [incident("I1", origin)], TracingRule.LIBR,
                    accounts_of(ledger), de_minimis_floor=bad)


@pytest.mark.parametrize("bad", [1.5, "500", True, [500]])
def test_floor_must_be_an_int(bad):
    ledger = world(["v", "B"], {"v": 10_000_00})
    origin = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    with pytest.raises((TypeError, ValueError)):
        trace_multi(ledger.journals(), [incident("I1", origin)], TracingRule.LIBR,
                    accounts_of(ledger), de_minimis_floor=bad)


# --------------------------------------------------------- 6. property test


ACCT_LETTERS = "abcdefghijklmnop"


def build_random_split_tree(origin_paise, plan):
    """A pure split tree (value only ever divides going down, never merges
    back). ``plan`` is a nested structure of branch factors from Hypothesis.
    Returns (ledger, incident, leaf_count_if_no_floor)."""
    ledger = world(["src", "n0"])
    ledger.external_credit("src", origin_paise, source_account_id="ext", occurred_at=at(0))
    origin = ledger.transfer("src", "n0", origin_paise, occurred_at=at(1))
    clock = _Clock()
    name_counter = [1]

    def fresh():
        name_counter[0] += 1
        n = f"n{name_counter[0]}"
        ledger.open_account(n)
        return n

    leaves = [0]

    def expand(node, value, subplan):
        if not subplan or value < 2:
            leaves[0] += 1
            return
        branch = subplan[0]
        k = min(max(2, branch["k"]), value)
        # split `value` into k shares as evenly as possible
        base, rem = divmod(value, k)
        shares = [base + (1 if i < rem else 0) for i in range(k)]
        children = [fresh() for _ in range(k)]
        ledger.post(
            JournalKind.TRANSFER,
            (Entry(node, -value), *[Entry(c, s) for c, s in zip(children, shares)]),
            occurred_at=clock.tick(),
        )
        for c, s, child_plan in zip(children, shares, branch["children"] + [[]] * k):
            expand(c, s, child_plan)

    expand("n0", origin_paise, plan)
    return ledger, incident("I1", origin), leaves[0]


_leaf = st.just([])
_tree = st.recursive(
    _leaf,
    lambda inner: st.builds(
        lambda k, kids: [{"k": k, "children": kids}],
        k=st.integers(min_value=2, max_value=4),
        kids=st.lists(inner, min_size=0, max_size=4),
    ),
    max_leaves=12,
)


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    origin_paise=st.integers(min_value=1_000, max_value=5_000_000),
    plan=_tree,
    floor=st.integers(min_value=1, max_value=200_000),
    rule=st.sampled_from(list(TracingRule)),
)
def test_property_floor_bounds_cardinality_and_conserves(origin_paise, plan, floor, rule):
    ledger, inc, _ = build_random_split_tree(origin_paise, plan)
    accounts = accounts_of(ledger)

    d = trace_multi(ledger.journals(), [inc], rule, accounts,
                    de_minimis_floor=floor)["I1"]

    # (a) cardinality: pure split tree -> one parcel per leaf account with a
    #     claim, every tracked parcel is >= floor, sum(claims) <= origin.
    assert len(d.claims) <= int(d.origin_paise) // floor

    # (b) conservation, exact, with extinguished as a term
    claimed = sum(int(c.amount_paise) for c in d.claims)
    assert (
        claimed + int(d.left_perimeter_paise) + int(d.extinguished_paise)
        == int(d.origin_paise)
    )

    # (c) no negative claims
    assert all(int(c.amount_paise) >= 0 for c in d.claims)
