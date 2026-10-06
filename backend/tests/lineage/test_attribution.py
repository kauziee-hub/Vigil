"""Attribution tests.

The worked examples here are the specification. If a rule's behaviour ever
changes, one of these must change with it and somebody must justify why — they
are the cases a court would be shown.
"""
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from prima.attribution.rules import DEFAULT_RULES, TracingRule
from prima.attribution.trace import Incident, ProvenanceGrade, trace, trace_envelope
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


def incident_from(journal, grade=ProvenanceGrade.REPORTED_UNVERIFIED):
    return Incident(
        id="inc_1",
        origin_journal_ids={journal.id},
        reported_at=at(1000),
        grade=grade,
    )


# ---------------------------------------------------------------- worked example


def test_worked_example_from_the_brief():
    """The scenario in the project brief, worked by hand.

    B opens with ₹5,000 of its own money. ₹50,000 arrives from a reported
    fraud. Then ₹20,000 out, ₹10,000 spent outside the perimeter, ₹20,000
    salary in, ₹30,000 out.

    Under LIBR the account holder is presumed to spend their own money first,
    so the claim survives until the balance forces it down, and the salary does
    not top it back up.
    """
    ledger = world(["victim", "B", "C", "D"], {"victim": 50_000_00, "B": 5_000_00})
    origin = ledger.transfer("victim", "B", 50_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 20_000_00, occurred_at=at(2))
    ledger.external_debit("B", 10_000_00, destination_account_id="ext", occurred_at=at(3))
    ledger.external_credit("B", 20_000_00, source_account_id="ext", occurred_at=at(4))
    ledger.transfer("B", "D", 30_000_00, occurred_at=at(5))
    ledger.check_invariants()

    inc = incident_from(origin)
    accounts = {a.id: a for a in ledger.accounts()}
    d = trace(ledger.journals(), inc, TracingRule.LIBR, accounts)

    # B: 55,000 -> pays 20,000 (5,000 own + 15,000 traced) -> claim 35,000
    #    -> spends 10,000 outside -> claim 25,000  (the low-water mark)
    #    -> +20,000 salary, claim stays 25,000 (no replenishment)
    #    -> pays 30,000 out of 45,000; own money is spent first (20,000),
    #       then 10,000 traced -> claim 15,000
    assert int(d.claim_for("B")) == 15_000_00
    assert int(d.claim_for("C")) == 15_000_00
    assert int(d.claim_for("D")) == 10_000_00
    assert int(d.left_perimeter_paise) == 10_000_00
    assert int(d.origin_paise) == 50_000_00
    # Everything is accounted for: still held + gone outside == the origin.
    assert int(d.attributable_total) + int(d.left_perimeter_paise) == 50_000_00


def test_rules_disagree_and_that_is_the_point():
    """The same facts, four rules, four answers. The engine reports the range."""
    ledger = world(["victim", "B", "C"], {"victim": 10_000_00, "B": 10_000_00})
    origin = ledger.transfer("victim", "B", 10_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 10_000_00, occurred_at=at(2))

    accounts = {a.id: a for a in ledger.accounts()}
    env = trace_envelope(ledger.journals(), incident_from(origin), list(TracingRule), accounts)

    # B held 10,000 own + 10,000 traced, then paid out exactly 10,000.
    assert int(env[TracingRule.LIBR].claim_for("B")) == 10_000_00   # own money spent first
    assert int(env[TracingRule.FIFO].claim_for("B")) == 10_000_00   # own money arrived first
    assert int(env[TracingRule.LIFO].claim_for("B")) == 0           # traced money spent first
    assert int(env[TracingRule.PRO_RATA].claim_for("B")) == 5_000_00  # half and half

    spread = {r: int(d.claim_for("B")) for r, d in env.items()}
    assert len(set(spread.values())) > 1, "if all rules agree the envelope is pointless"


# ----------------------------------------------- the bugs in the old engine


def test_fan_out_cannot_inflate_attributed_value():
    """The old taint engine turned ₹1,00,000 into ₹3,00,000 across three hops.

    Reproduces that exact shape. Conservation now makes it structurally
    impossible: the traced value is split, never copied.
    """
    ledger = world(
        ["victim", "B", "C0", "C1", "C2"],
        {"victim": 100_000_00, "B": 200_000_00},
    )
    origin = ledger.transfer("victim", "B", 100_000_00, occurred_at=at(1))
    for index in range(3):
        ledger.transfer("B", f"C{index}", 100_000_00, occurred_at=at(2 + index))
    ledger.check_invariants()

    accounts = {a.id: a for a in ledger.accounts()}
    for rule in DEFAULT_RULES:
        d = trace(ledger.journals(), incident_from(origin), rule, accounts)
        attributed = int(d.attributable_total) + int(d.left_perimeter_paise)
        assert attributed <= 100_000_00, f"{rule} inflated to {attributed}"


def test_small_fraud_does_not_contaminate_a_large_business():
    """₹1,000 of traced money reaching a business with ₹5,00,000 of turnover.

    The old engine attributed ₹10,00,000 across four uninvolved suppliers —
    a thousandfold overstatement. Under any rule here the exposure is bounded
    by the ₹1,000 that actually arrived.
    """
    suppliers = [f"supplier{i}" for i in range(4)]
    ledger = world(["victim", "biz", *suppliers], {"victim": 1_000_00, "biz": 0})
    origin = ledger.transfer("victim", "biz", 1_000_00, occurred_at=at(1))
    ledger.external_credit("biz", 500_000_00, source_account_id="ext", occurred_at=at(2))
    for index, supplier in enumerate(suppliers):
        ledger.transfer("biz", supplier, 125_000_00, occurred_at=at(3 + index))
    ledger.check_invariants()

    accounts = {a.id: a for a in ledger.accounts()}
    for rule in DEFAULT_RULES:
        d = trace(ledger.journals(), incident_from(origin), rule, accounts)
        total = int(d.attributable_total) + int(d.left_perimeter_paise)
        assert total <= 1_000_00
        for supplier in suppliers:
            assert int(d.claim_for(supplier)) <= 1_000_00


def test_libr_does_not_replenish_from_later_deposits():
    """Once the balance dips below the claim, later money is not the victim's."""
    ledger = world(["victim", "B"], {"victim": 10_000_00, "B": 0})
    origin = ledger.transfer("victim", "B", 10_000_00, occurred_at=at(1))
    ledger.external_debit("B", 9_000_00, destination_account_id="ext", occurred_at=at(2))
    ledger.external_credit("B", 50_000_00, source_account_id="ext", occurred_at=at(3))

    accounts = {a.id: a for a in ledger.accounts()}
    d = trace(ledger.journals(), incident_from(origin), TracingRule.LIBR, accounts)
    assert int(d.claim_for("B")) == 1_000_00  # not 10,000 — the rest was spent


# ------------------------------------------------------------------ perimeter


def test_value_leaving_the_perimeter_is_reported_not_guessed():
    ledger = world(["victim", "B"], {"victim": 20_000_00})
    origin = ledger.transfer("victim", "B", 20_000_00, occurred_at=at(1))
    ledger.external_debit("B", 12_000_00, destination_account_id="ext", occurred_at=at(2))

    accounts = {a.id: a for a in ledger.accounts()}
    d = trace(ledger.journals(), incident_from(origin), TracingRule.LIBR, accounts)
    assert int(d.left_perimeter_paise) == 12_000_00
    assert int(d.claim_for("B")) == 8_000_00
    assert d.coverage == pytest.approx(8_000_00 / 20_000_00)
    assert any(step.left_perimeter for step in d.steps)


# --------------------------------------------------------------- reproducible


def test_derivation_is_byte_identical_on_re_run():
    ledger = world(["victim", "B", "C"], {"victim": 30_000_00, "B": 4_000_00})
    origin = ledger.transfer("victim", "B", 30_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 9_000_00, occurred_at=at(2))

    accounts = {a.id: a for a in ledger.accounts()}
    inc = incident_from(origin)
    first = trace(ledger.journals(), inc, TracingRule.LIBR, accounts)
    second = trace(ledger.journals(), inc, TracingRule.LIBR, accounts)
    assert first.digest == second.digest
    assert first.payload() == second.payload()


def test_grade_does_not_change_the_arithmetic():
    """Confidence governs what may be done, never what the number is."""
    ledger = world(["victim", "B"], {"victim": 5_000_00})
    origin = ledger.transfer("victim", "B", 5_000_00, occurred_at=at(1))
    accounts = {a.id: a for a in ledger.accounts()}
    low = trace(ledger.journals(), incident_from(origin, ProvenanceGrade.REPORTED_UNVERIFIED),
                TracingRule.LIBR, accounts)
    high = trace(ledger.journals(), incident_from(origin, ProvenanceGrade.ADJUDICATED),
                 TracingRule.LIBR, accounts)
    assert int(low.claim_for("B")) == int(high.claim_for("B"))


# ----------------------------------------------------- conservation, always


@settings(max_examples=120, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    moves=st.lists(
        st.tuples(
            st.sampled_from(["B", "C", "D", "E"]),
            st.sampled_from(["B", "C", "D", "E", "ext"]),
            st.integers(min_value=1, max_value=40_000),
        ),
        min_size=0, max_size=30,
    ),
    rule=st.sampled_from(list(TracingRule)),
    injections=st.lists(
        st.tuples(st.sampled_from(["B", "C", "D", "E"]), st.integers(min_value=1, max_value=50_000)),
        max_size=8,
    ),
)
def test_conservation_holds_for_any_flow_and_any_rule(moves, rule, injections):
    """THE invariant.

    Across any sequence of splits, merges, dilutions, fan-outs and exits, the
    traced value still inside the perimeter plus the traced value that left it
    can never exceed what was reported. This is the property whose absence made
    the previous engine attribute more money than ever existed.
    """
    ledger = world(["victim", "B", "C", "D", "E"], {"victim": 60_000, "B": 20_000,
                                                    "C": 20_000, "D": 20_000, "E": 20_000})
    origin = ledger.transfer("victim", "B", 60_000, occurred_at=at(1))

    clock = 2
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
    accounts = {a.id: a for a in ledger.accounts()}
    d = trace(ledger.journals(), incident_from(origin), rule, accounts)

    accounted = int(d.attributable_total) + int(d.left_perimeter_paise)
    assert accounted <= int(d.origin_paise), (
        f"{rule}: attributed {accounted} from an origin of {int(d.origin_paise)}"
    )
    assert all(int(c.amount_paise) >= 0 for c in d.claims)
    # No account may be claimed for more than it actually holds.
    for claim in d.claims:
        assert int(claim.amount_paise) <= int(ledger.balance(claim.account_id))
