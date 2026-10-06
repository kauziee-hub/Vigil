"""seed_from must not be trusted with a caller-supplied batch trace.

The multi-incident composability defect -- one trace() call per incident,
forgetting the others are live, so each treats the rest as the account holder's
own money -- has now been found and fixed at three call sites. seed_from was the
third. It used to accept a `derivations` mapping and trust it completely; its
"claims exceed balance" assertion only caught the subset of bad mappings that
happened to push some account's reconstructed own-money negative. Fuzzing found
that assertion missing roughly one in eight realistic multi-incident histories.

The fix is not a better check. It is removing the seam: seed_from now computes
the batch trace itself, in one combined trace_multi pass over the incidents the
object was constructed with. There is no longer a parameter through which a
wrong trace can arrive.

These tests pin that: the old call shape is a TypeError, and seeding then
continuing lands on exactly what a full batch trace_multi says.
"""
import inspect
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from prima.attribution.incremental import IncrementalLineage
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


def incident(incident_id, journal, minutes=9999):
    return Incident(
        id=incident_id, origin_journal_ids={journal.id}, reported_at=at(minutes)
    )


def accounts_of(ledger):
    return {a.id: a for a in ledger.accounts()}


def customers_of(ledger):
    return [a.id for a in ledger.accounts() if a.is_customer]


class FrozenLedger:
    """The ledger as it stood at ``cut`` -- all seeding is allowed to see.

    ``.journals()`` returns the truncated prefix, so seed_from's internal
    trace_multi runs over exactly that prefix. This is why no through_seq
    parameter is needed: the truncation happens on the ledger side.
    """

    def __init__(self, journals, cut):
        self._journals = tuple(j for j in journals if j.seq <= cut)

    def journals(self):
        return self._journals

    def balance(self, account_id):
        return sum(int(j.delta_for(account_id)) for j in self._journals)


def seed_then_apply(ledger, incidents, cut):
    """Seed at ``cut`` from a frozen view, then apply the rest one at a time."""
    journals = ledger.journals()
    accounts = accounts_of(ledger)
    customers = customers_of(ledger)
    live = IncrementalLineage(incidents, customers)
    live.seed_from(FrozenLedger(journals, cut), accounts, customers)
    for journal in journals:
        if journal.seq > cut:
            live.apply(journal)
    return live


def assert_equals_full_batch(ledger, incidents, live):
    reference = trace_multi(
        ledger.journals(), incidents, TracingRule.LIBR, accounts_of(ledger)
    )
    for inc in incidents:
        d = reference[inc.id]
        for account in customers_of(ledger):
            assert live.claim(account, inc.id) == int(d.claim_for(account)), (
                f"{account}/{inc.id}: {live.claim(account, inc.id)} != {int(d.claim_for(account))}"
            )
        assert live.left_perimeter(inc.id) == int(d.left_perimeter_paise), inc.id
        assert live.retagged(inc.id) == int(d.retagged_paise), inc.id


# ------------------------------------------------ the seam is gone


def test_old_call_shape_is_a_type_error():
    """seed_from(derivations, ledger, customer_ids) -- the pre-fix call -- must
    not be a possible-but-wrong call any more. It must not run at all."""
    ledger = world(["M"], {"M": 1_000_00})
    live = IncrementalLineage([], customers_of(ledger))

    with pytest.raises(TypeError):
        # the exact keyword the old signature had
        live.seed_from(derivations={}, ledger=ledger, customer_ids=["M"])


def test_signature_has_no_parameter_that_accepts_a_derivation_mapping():
    params = inspect.signature(IncrementalLineage.seed_from).parameters
    # through_seq (Step 5's ADDITIONAL CONTRACT) is keyword-only and names a
    # journal seq, not a trace -- the point of this test is unchanged: no
    # parameter through which a caller-computed derivations mapping can arrive.
    assert list(params) == ["self", "ledger", "accounts", "customer_ids", "through_seq"]
    assert "derivations" not in params
    for name, p in params.items():
        assert "Derivation" not in str(p.annotation), name


def test_the_review_fuzz_shape_now_matches_batch_every_time():
    """A scaled, deterministic version of the review's 500-trial harness.

    Before the fix, naively-assembled derivations produced silently-wrong
    claims in a measurable fraction. seed_from cannot accept those any more, so
    the only thing left to check is that its own computed trace matches
    trace_multi -- which it must, being the same call. Zero tolerance.
    """
    import random

    rng = random.Random(77)
    names = ["M", "B", "C"]
    mismatches = 0
    trials = 200
    for _ in range(trials):
        n_inc = rng.choice([2, 3])
        victims = [f"v{i}" for i in range(n_inc)]
        ledger = world(
            [*victims, *names],
            {
                **{v: 100_00 for v in victims},
                "M": rng.choice([50_00, 120_00, 200_00, 300_00]),
                "B": rng.randint(1, 50_00),
                "C": rng.randint(1, 50_00),
            },
        )
        incidents = []
        for i, v in enumerate(victims):
            origin = ledger.transfer(v, "M", 100_00, occurred_at=at(1 + i))
            incidents.append(incident(f"I{i}", origin))
        clock = 20
        for _ in range(rng.randint(2, 8)):
            sender = rng.choice(names)
            receiver = rng.choice([*names, "ext"])
            if sender == receiver:
                continue
            held = sum(int(j.delta_for(sender)) for j in ledger.journals())
            if held <= 0:
                continue
            amount = min(
                held, rng.randint(1, int(held * rng.choice([0.4, 0.7, 1.0, 1.3])) or 1)
            )
            try:
                if receiver == "ext":
                    ledger.external_debit(sender, amount,
                                          destination_account_id="ext", occurred_at=at(clock))
                else:
                    ledger.transfer(sender, receiver, amount, occurred_at=at(clock))
            except InsufficientFunds:
                pass
            clock += 1

        journals = ledger.journals()
        if len(journals) < 4:
            continue
        cut = rng.randint(1, len(journals) - 2)
        live = seed_then_apply(ledger, incidents, cut)
        ref = trace_multi(journals, incidents, TracingRule.LIBR, accounts_of(ledger))
        for inc in incidents:
            for account in customers_of(ledger):
                if live.claim(account, inc.id) != int(ref[inc.id].claim_for(account)):
                    mismatches += 1
            if live.left_perimeter(inc.id) != int(ref[inc.id].left_perimeter_paise):
                mismatches += 1
    assert mismatches == 0, f"{mismatches} mismatches across {trials} trials"


# ------------------------------------------------ correctness, shared accounts


@pytest.mark.parametrize("cut", [0, 1, 2, 3, 4, 5, 6, 7])
def test_two_incidents_into_one_account_seed_at_each_cut(cut):
    """I1 and I2 both land on M, which also holds its own money and then fans
    out. Seed at every point in that history and finish incrementally."""
    ledger = world(["v1", "v2", "M", "B", "C"],
                   {"v1": 30_000_00, "v2": 30_000_00, "M": 10_000_00})
    o1 = ledger.transfer("v1", "M", 30_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "M", 30_000_00, occurred_at=at(2))
    ledger.transfer("M", "B", 25_000_00, occurred_at=at(3))
    ledger.external_debit("M", 15_000_00, destination_account_id="ext", occurred_at=at(4))
    ledger.transfer("B", "C", 9_000_00, occurred_at=at(5))
    ledger.external_credit("M", 5_000_00, source_account_id="ext", occurred_at=at(6))
    ledger.transfer("M", "C", 8_000_00, occurred_at=at(7))
    ledger.check_invariants()

    if cut >= len(ledger.journals()):
        pytest.skip("history shorter than the cut")
    incidents = [incident("I1", o1), incident("I2", o2)]
    live = seed_then_apply(ledger, incidents, cut)
    assert_equals_full_batch(ledger, incidents, live)


@pytest.mark.parametrize("cut", [1, 2, 3, 4, 5, 6])
def test_three_incidents_into_one_account_seed_at_each_cut(cut):
    ledger = world(["v1", "v2", "v3", "M", "B", "C"],
                   {"v1": 12_000_00, "v2": 15_000_00, "v3": 9_000_00, "M": 4_000_00})
    o1 = ledger.transfer("v1", "M", 12_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "M", 15_000_00, occurred_at=at(2))
    o3 = ledger.transfer("v3", "M", 9_000_00, occurred_at=at(3))
    ledger.transfer("M", "B", 30_000_00, occurred_at=at(4))
    ledger.external_debit("B", 6_000_00, destination_account_id="ext", occurred_at=at(5))
    ledger.transfer("B", "C", 10_000_00, occurred_at=at(6))
    ledger.check_invariants()

    if cut >= len(ledger.journals()):
        pytest.skip("history shorter than the cut")
    incidents = [incident("I1", o1), incident("I2", o2), incident("I3", o3)]
    live = seed_then_apply(ledger, incidents, cut)
    assert_equals_full_batch(ledger, incidents, live)


# ------------------------------------ worked examples in the silently-wrong shape

# Each is: an account holding clean money plus two or three incidents' tagged
# money, an outflow that partially encroaches one tagged pool, then further
# hops. These are exactly the shapes the review's fuzzer flagged as passing the
# old assertion while producing wrong claims. Seeded the new way, mid-history,
# they must match trace_multi.

WORKED = [
    # (funding, incident_targets, hops)  -- hops: (sender, receiver, amount)
    (
        {"v0": 100_00, "v1": 100_00, "M": 120_00, "B": 3_00, "C": 1_00},
        ["M", "M"],
        [("M", "B", 260_00), ("B", "C", 90_00), ("B", "ext", 40_00),
         ("M", "C", 25_00)],
    ),
    (
        {"v0": 100_00, "v1": 100_00, "M": 200_00, "B": 50_00, "C": 10_00},
        ["M", "M"],
        [("M", "B", 220_00), ("B", "ext", 120_00), ("B", "C", 30_00),
         ("C", "M", 5_00), ("M", "B", 33_00)],
    ),
    (
        {"v0": 100_00, "v1": 100_00, "v2": 100_00, "M": 300_00, "B": 20_00, "C": 5_00},
        ["M", "M", "M"],
        [("M", "B", 450_00), ("B", "C", 60_00), ("C", "ext", 12_00),
         ("B", "M", 40_00), ("M", "C", 33_00)],
    ),
    (
        {"v0": 40_00, "v1": 60_00, "M": 50_00, "B": 8_00, "C": 8_00},
        ["M", "M"],
        [("M", "B", 100_00), ("B", "C", 55_00), ("M", "ext", 30_00),
         ("C", "B", 20_00)],
    ),
    (
        {"v0": 30_00, "v1": 30_00, "v2": 30_00, "M": 90_00, "B": 12_00},
        ["M", "M", "M"],
        [("M", "B", 150_00), ("B", "ext", 45_00), ("B", "M", 12_00),
         ("M", "B", 8_00)],
    ),
]


@pytest.mark.parametrize("case_index", range(len(WORKED)))
@pytest.mark.parametrize("cut", [1, 2, 3])
def test_silently_wrong_shape_is_seeded_correctly_now(case_index, cut):
    funding, targets, hops = WORKED[case_index]
    victims = sorted(k for k in funding if k.startswith("v"))
    others = [k for k in funding if not k.startswith("v")]
    ledger = world([*victims, *others], funding)

    incidents = []
    for i, (v, tgt) in enumerate(zip(victims, targets)):
        amount = funding[v]
        origin = ledger.transfer(v, tgt, amount, occurred_at=at(1 + i))
        incidents.append(incident(f"I{i}", origin))

    clock = 20
    for sender, receiver, amount in hops:
        held = sum(int(j.delta_for(sender)) for j in ledger.journals())
        if held <= 0:
            continue
        amount = min(amount, held)
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

    if cut >= len(ledger.journals()):
        pytest.skip("history shorter than the cut")
    live = seed_then_apply(ledger, incidents, cut)
    assert_equals_full_batch(ledger, incidents, live)

    # And C4 across the whole live set, from the seeded state.
    for account in customers_of(ledger):
        total = sum(live.claim(account, inc.id) for inc in incidents)
        assert total <= int(ledger.balance(account)), account


# --------------------------------------------------------- edges of history


def test_seed_at_cut_zero():
    """Almost nothing has happened -- only the first origin exists."""
    ledger = world(["v1", "v2", "M"], {"v1": 20_000_00, "v2": 20_000_00})
    o1 = ledger.transfer("v1", "M", 20_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "M", 20_000_00, occurred_at=at(2))
    ledger.transfer("M", "M" if False else "v1", 5_000_00, occurred_at=at(3))
    incidents = [incident("I1", o1), incident("I2", o2)]

    live = seed_then_apply(ledger, incidents, cut=0)
    assert_equals_full_batch(ledger, incidents, live)


def test_seed_at_the_last_journal_leaves_nothing_to_apply():
    ledger = world(["v1", "v2", "M", "B"], {"v1": 20_000_00, "v2": 20_000_00})
    o1 = ledger.transfer("v1", "M", 20_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "M", 20_000_00, occurred_at=at(2))
    ledger.transfer("M", "B", 30_000_00, occurred_at=at(3))
    incidents = [incident("I1", o1), incident("I2", o2)]

    last = ledger.journals()[-1].seq
    live = seed_then_apply(ledger, incidents, cut=last)
    assert_equals_full_batch(ledger, incidents, live)


def test_seeding_when_the_tagged_account_is_already_empty():
    """M receives the incident then forwards all of it before the report.

    Seeding at cut 2 -- after M is empty -- must leave M with no bucket at all,
    not a zero-valued shell, and put the value on B.
    """
    ledger = world(["v1", "M", "B"], {"v1": 10_000_00})
    origin = ledger.transfer("v1", "M", 10_000_00, occurred_at=at(1))
    ledger.transfer("M", "B", 10_000_00, occurred_at=at(2))
    inc = incident("I1", origin)

    live = seed_then_apply(ledger, [inc], cut=2)
    assert_equals_full_batch(ledger, [inc], live)
    assert live.claim("M", "I1") == 0
    assert live.claim("B", "I1") == 10_000_00
    assert "M" not in live.state or live.state["M"] == {}


# ------------------------------------------- the defensive assertion


def test_negative_own_money_assertion_still_fires_for_an_inconsistent_ledger():
    """Through correct use this is now unreachable: trace_multi guarantees C4,
    so claims never exceed the balance it was computed against. The check
    remains as a guard against a trace_multi regression or a ledger whose
    balance() disagrees with its journals(). Exercise it with the latter."""
    ledger = world(["v1", "v2", "M"], {"v1": 30_000_00, "v2": 30_000_00})
    o1 = ledger.transfer("v1", "M", 30_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "M", 30_000_00, occurred_at=at(2))
    incidents = [incident("I1", o1), incident("I2", o2)]
    real = accounts_of(ledger)

    class LyingLedger:
        def journals(self):
            return ledger.journals()

        def balance(self, account_id):
            # M really holds 60,000; claim 100 it holds far less.
            return 100 if account_id == "M" else int(ledger.balance(account_id))

    live = IncrementalLineage(incidents, customers_of(ledger))
    with pytest.raises(AssertionError, match="claims total"):
        live.seed_from(LyingLedger(), real, customers_of(ledger))


# -------------------------------------------------------- the property


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
        max_size=16,
    ),
    injections=st.lists(
        st.tuples(st.sampled_from(ACCOUNTS), st.integers(min_value=1, max_value=50_000)),
        max_size=4,
    ),
    cut_fraction=st.floats(min_value=0.0, max_value=1.0),
)
def test_seed_at_a_random_cut_then_continue_equals_full_batch(
    n_incidents, targets, moves, injections, cut_fraction
):
    """Seed at an arbitrary point, apply the rest, land on the full batch trace.

    Claims per account per incident, what left the perimeter, and what was
    re-tagged -- all equal, not close.
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

    ledger.check_invariants()
    journals = ledger.journals()
    last = journals[-1].seq
    cut = int(round(cut_fraction * last))

    live = seed_then_apply(ledger, incidents, cut)
    assert_equals_full_batch(ledger, incidents, live)

    for account in customers_of(ledger):
        total = sum(live.claim(account, inc.id) for inc in incidents)
        assert total <= int(ledger.balance(account)), f"C4 {account}"
