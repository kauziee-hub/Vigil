"""Multi-incident attribution.

The single-incident engine cannot be composed: two independent traces over the
same journal each treat the other incident's value as the account holder's own
money and, under LIBR, presume it was spent first. Both then claim the same
rupees. These tests are the specification for the one-pass engine that fixes
that, per 04-VALUE-LINEAGE-SPEC.md section 5.3.

The worked examples here are the specification. If behaviour changes, one of
these must change with it and somebody must justify why.
"""
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from prima.attribution.rules import DEFAULT_RULES, TracingRule
from prima.attribution.trace import (
    Incident,
    incident_rank_map,
    trace,
    trace_multi,
)
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


def accounts_of(ledger):
    return {a.id: a for a in ledger.accounts()}


def claims_on(derivations, account_id):
    return {k: int(d.claim_for(account_id)) for k, d in derivations.items()}


# ------------------------------------------------- the case that forced 5.3


def test_two_incidents_no_longer_claim_the_same_rupees():
    """The measured failure from the spec, worked by hand.

    Two victims each send Rs 30,000 to one mule; Rs 30,000 then leaves the
    perimeter. Independently traced, each incident claims the whole Rs 30,000
    balance -- Rs 60,000 against Rs 30,000 -- and neither sees the exit.

    Traced together there is one pool. LIBR consumes own money first, then the
    oldest incident, so the exit is I1's money and I2's survives.
    """
    ledger = world(["v1", "v2", "mule"], {"v1": 30_000_00, "v2": 30_000_00})
    o1 = ledger.transfer("v1", "mule", 30_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "mule", 30_000_00, occurred_at=at(2))
    ledger.external_debit("mule", 30_000_00, destination_account_id="ext", occurred_at=at(3))
    ledger.check_invariants()

    accounts = accounts_of(ledger)
    i1, i2 = incident("I1", o1), incident("I2", o2)

    # The old way, kept here so the regression is visible rather than asserted.
    solo1 = trace(ledger.journals(), i1, TracingRule.LIBR, accounts)
    solo2 = trace(ledger.journals(), i2, TracingRule.LIBR, accounts)
    assert int(solo1.claim_for("mule")) + int(solo2.claim_for("mule")) == 60_000_00
    assert int(solo1.left_perimeter_paise) == int(solo2.left_perimeter_paise) == 0

    both = trace_multi(ledger.journals(), [i1, i2], TracingRule.LIBR, accounts)
    assert int(both["I1"].claim_for("mule")) == 0
    assert int(both["I1"].left_perimeter_paise) == 30_000_00
    assert int(both["I2"].claim_for("mule")) == 30_000_00
    assert int(both["I2"].left_perimeter_paise) == 0

    # C4: across every incident, the claims fit inside the balance.
    total = sum(int(d.claim_for("mule")) for d in both.values())
    assert total == 30_000_00 == int(ledger.balance("mule"))


def test_single_incident_result_is_unchanged_by_the_multi_engine():
    """The one-element case must be the old case, exactly.

    Not "close enough": the same claims, the same steps, the same digest. This
    is what lets every pre-existing test stand unaltered.
    """
    ledger = world(["victim", "B", "C", "D"], {"victim": 50_000_00, "B": 5_000_00})
    origin = ledger.transfer("victim", "B", 50_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 20_000_00, occurred_at=at(2))
    ledger.external_debit("B", 10_000_00, destination_account_id="ext", occurred_at=at(3))
    ledger.external_credit("B", 20_000_00, source_account_id="ext", occurred_at=at(4))
    ledger.transfer("B", "D", 30_000_00, occurred_at=at(5))

    accounts = accounts_of(ledger)
    inc = incident("inc_1", origin)
    for rule in list(TracingRule):
        solo = trace(ledger.journals(), inc, rule, accounts)
        via_multi = trace_multi(ledger.journals(), [inc], rule, accounts)["inc_1"]
        assert solo.payload() == via_multi.payload(), rule
        assert solo.digest == via_multi.digest, rule


# ------------------------------------------------------- the global ordering


def test_consumption_order_is_oldest_incident_first():
    """Rule 2: untagged first, then incidents by first-seen journal sequence.

    B holds its own Rs 10,000, then I1's Rs 10,000, then I2's Rs 10,000, and
    pays out Rs 20,000. Own money goes first, then the older incident.
    """
    ledger = world(["v1", "v2", "B", "C"], {"v1": 10_000_00, "v2": 10_000_00, "B": 10_000_00})
    o1 = ledger.transfer("v1", "B", 10_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 10_000_00, occurred_at=at(2))
    ledger.transfer("B", "C", 20_000_00, occurred_at=at(3))

    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts)
    assert claims_on(d, "B") == {"I1": 0, "I2": 10_000_00}
    assert claims_on(d, "C") == {"I1": 10_000_00, "I2": 0}


def test_incident_order_does_not_depend_on_argument_order():
    """The order the caller lists incidents in must not change any number."""
    ledger = world(["v1", "v2", "B", "C"], {"v1": 10_000_00, "v2": 10_000_00, "B": 5_000_00})
    o1 = ledger.transfer("v1", "B", 10_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 10_000_00, occurred_at=at(2))
    ledger.transfer("B", "C", 18_000_00, occurred_at=at(3))

    accounts = accounts_of(ledger)
    i1, i2 = incident("I1", o1), incident("I2", o2)
    forward = trace_multi(ledger.journals(), [i1, i2], TracingRule.LIBR, accounts)
    backward = trace_multi(ledger.journals(), [i2, i1], TracingRule.LIBR, accounts)
    assert {k: v.payload() for k, v in forward.items()} == {
        k: v.payload() for k, v in backward.items()
    }


def test_rank_map_is_by_first_seen_sequence_then_id():
    ledger = world(["v", "B"], {"v": 30_000_00})
    early = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    late = ledger.transfer("v", "B", 10_000_00, occurred_at=at(2))
    ranks = incident_rank_map(
        ledger.journals(), [incident("zzz", early), incident("aaa", late)]
    )
    # "zzz" is named first even though "aaa" sorts earlier alphabetically:
    # sequence wins, the id is only the tie-break.
    assert ranks == {"zzz": 1, "aaa": 2}


# ------------------------------------------------------------ origin re-tagging


def test_origin_retagging_reports_the_displaced_amount():
    """Rule 3: a later report's assertion governs, and the loss is stated.

    I1's Rs 10,000 reaches B. B then sends Rs 10,000 to C, and *that* movement
    is reported as I2's origin. The value credited to C becomes I2's. I1 did
    not silently lose it -- it is reported as retagged.
    """
    ledger = world(["v1", "B", "C"], {"v1": 10_000_00})
    o1 = ledger.transfer("v1", "B", 10_000_00, occurred_at=at(1))
    o2 = ledger.transfer("B", "C", 10_000_00, occurred_at=at(2))

    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts)

    assert int(d["I2"].claim_for("C")) == 10_000_00
    assert int(d["I1"].claim_for("C")) == 0
    assert int(d["I1"].claim_for("B")) == 0
    assert int(d["I1"].retagged_paise) == 10_000_00
    # Nothing is unexplained: held + gone + retagged accounts for the origin.
    assert (
        int(d["I1"].attributable_total)
        + int(d["I1"].left_perimeter_paise)
        + int(d["I1"].retagged_paise)
        == int(d["I1"].origin_paise)
    )


def test_retagged_is_zero_when_the_origin_moves_clean_money():
    ledger = world(["v1", "B", "C"], {"v1": 10_000_00, "B": 10_000_00})
    o1 = ledger.transfer("v1", "B", 10_000_00, occurred_at=at(1))
    o2 = ledger.transfer("B", "C", 5_000_00, occurred_at=at(2))
    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts)
    # LIBR spent B's own money on the o2 movement, so I1 lost nothing.
    assert int(d["I1"].retagged_paise) == 0
    assert int(d["I1"].claim_for("B")) == 10_000_00


def test_two_incidents_cannot_share_an_origin_journal():
    """A contradiction in the input, refused rather than guessed at."""
    ledger = world(["v", "B"], {"v": 10_000_00})
    origin = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    with pytest.raises(ValueError, match="origin"):
        trace_multi(
            ledger.journals(),
            [incident("I1", origin), incident("I2", origin)],
            TracingRule.LIBR,
            accounts_of(ledger),
        )


def test_duplicate_incident_ids_are_refused():
    ledger = world(["v", "B"], {"v": 10_000_00})
    origin = ledger.transfer("v", "B", 10_000_00, occurred_at=at(1))
    with pytest.raises(ValueError, match="unique"):
        trace_multi(
            ledger.journals(),
            [incident("I1", origin), incident("I1", origin)],
            TracingRule.LIBR,
            accounts_of(ledger),
        )


# ------------------------------------------------------------- journal shapes


def test_multi_credit_split_divides_every_tag_without_rounding_loss():
    """One debit, three uneven credits. No paise created, none lost."""
    ledger = world(["v1", "v2", "B", "X", "Y", "Z"], {"v1": 10_001, "v2": 10_001})
    o1 = ledger.transfer("v1", "B", 10_001, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 10_001, occurred_at=at(2))
    ledger.post(
        JournalKind.TRANSFER,
        (
            Entry("B", -20_002),
            Entry("X", 6_667),
            Entry("Y", 6_667),
            Entry("Z", 6_668),
        ),
        occurred_at=at(3),
    )
    ledger.check_invariants()

    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts)
    for key, deriv in d.items():
        assert (
            int(deriv.attributable_total) + int(deriv.left_perimeter_paise)
            == int(deriv.origin_paise)
        ), key
    for account in ("X", "Y", "Z"):
        assert sum(int(x.claim_for(account)) for x in d.values()) <= int(
            ledger.balance(account)
        )


def test_fan_out_cannot_inflate_across_incidents():
    ledger = world(["v1", "v2", "B", "C0", "C1", "C2"],
                   {"v1": 100_000_00, "v2": 100_000_00, "B": 200_000_00})
    o1 = ledger.transfer("v1", "B", 100_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 100_000_00, occurred_at=at(2))
    for index in range(3):
        ledger.transfer("B", f"C{index}", 100_000_00, occurred_at=at(3 + index))
    ledger.check_invariants()

    accounts = accounts_of(ledger)
    for rule in DEFAULT_RULES:
        d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                        rule, accounts)
        for key, deriv in d.items():
            accounted = int(deriv.attributable_total) + int(deriv.left_perimeter_paise)
            assert accounted <= 100_000_00, f"{rule}/{key} inflated to {accounted}"


def test_fan_in_merges_two_incidents_into_one_account():
    ledger = world(["v1", "v2", "B", "C", "sink"],
                   {"v1": 10_000_00, "v2": 20_000_00})
    o1 = ledger.transfer("v1", "B", 10_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "C", 20_000_00, occurred_at=at(2))
    ledger.transfer("B", "sink", 10_000_00, occurred_at=at(3))
    ledger.transfer("C", "sink", 20_000_00, occurred_at=at(4))
    ledger.check_invariants()

    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts)
    assert claims_on(d, "sink") == {"I1": 10_000_00, "I2": 20_000_00}
    assert sum(claims_on(d, "sink").values()) == int(ledger.balance("sink"))


def test_dilution_does_not_reduce_either_libr_claim():
    """LIBR is dilution-resistant, and stays so with two incidents present."""
    ledger = world(["v1", "v2", "B"], {"v1": 5_000_00, "v2": 5_000_00})
    o1 = ledger.transfer("v1", "B", 5_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 5_000_00, occurred_at=at(2))
    accounts = accounts_of(ledger)
    before = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                         TracingRule.LIBR, accounts)
    ledger.external_credit("B", 500_000_00, source_account_id="ext", occurred_at=at(3))
    after = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                        TracingRule.LIBR, accounts_of(ledger))
    assert claims_on(before, "B") == claims_on(after, "B") == {
        "I1": 5_000_00, "I2": 5_000_00
    }


def test_cycle_does_not_duplicate_value():
    """Money going round a ring and back is the same money, not more of it."""
    ledger = world(["v1", "v2", "A", "B", "C"],
                   {"v1": 9_000_00, "v2": 9_000_00})
    o1 = ledger.transfer("v1", "A", 9_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "A", 9_000_00, occurred_at=at(2))
    ledger.transfer("A", "B", 12_000_00, occurred_at=at(3))
    ledger.transfer("B", "C", 12_000_00, occurred_at=at(4))
    ledger.transfer("C", "A", 12_000_00, occurred_at=at(5))
    ledger.check_invariants()

    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts)
    for key, deriv in d.items():
        assert (
            int(deriv.attributable_total) + int(deriv.left_perimeter_paise)
            <= int(deriv.origin_paise)
        ), key
    for account in ("A", "B", "C"):
        assert sum(int(x.claim_for(account)) for x in d.values()) <= int(
            ledger.balance(account)
        )


def test_repeated_downstream_transfers_carry_the_right_tag():
    ledger = world(["v1", "v2", "B", "C", "D", "E"],
                   {"v1": 4_000_00, "v2": 6_000_00})
    o1 = ledger.transfer("v1", "B", 4_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 6_000_00, occurred_at=at(2))
    ledger.transfer("B", "C", 10_000_00, occurred_at=at(3))
    ledger.transfer("C", "D", 10_000_00, occurred_at=at(4))
    ledger.transfer("D", "E", 10_000_00, occurred_at=at(5))
    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts)
    assert claims_on(d, "E") == {"I1": 4_000_00, "I2": 6_000_00}


def test_reversal_returns_value_to_the_incident_it_came_from():
    """Value that leaves an account and comes back is still traced."""
    ledger = world(["v1", "v2", "B", "C"], {"v1": 8_000_00, "v2": 8_000_00})
    o1 = ledger.transfer("v1", "B", 8_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 8_000_00, occurred_at=at(2))
    ledger.transfer("B", "C", 16_000_00, occurred_at=at(3))
    ledger.transfer("C", "B", 16_000_00, occurred_at=at(4))  # the reversal
    ledger.check_invariants()

    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts)
    assert claims_on(d, "B") == {"I1": 8_000_00, "I2": 8_000_00}
    assert claims_on(d, "C") == {"I1": 0, "I2": 0}


def test_external_debit_is_attributed_to_exactly_one_incident():
    ledger = world(["v1", "v2", "B"], {"v1": 5_000_00, "v2": 5_000_00})
    o1 = ledger.transfer("v1", "B", 5_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 5_000_00, occurred_at=at(2))
    ledger.external_debit("B", 7_000_00, destination_account_id="ext", occurred_at=at(3))
    accounts = accounts_of(ledger)
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts)
    # Oldest first: all of I1 and 2,000 of I2 went out.
    assert int(d["I1"].left_perimeter_paise) == 5_000_00
    assert int(d["I2"].left_perimeter_paise) == 2_000_00
    assert claims_on(d, "B") == {"I1": 0, "I2": 3_000_00}


def test_account_reaching_exactly_zero():
    ledger = world(["v1", "v2", "B", "C"], {"v1": 3_000_00, "v2": 3_000_00})
    o1 = ledger.transfer("v1", "B", 3_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 3_000_00, occurred_at=at(2))
    ledger.transfer("B", "C", 6_000_00, occurred_at=at(3))
    assert int(ledger.balance("B")) == 0
    d = trace_multi(ledger.journals(), [incident("I1", o1), incident("I2", o2)],
                    TracingRule.LIBR, accounts_of(ledger))
    assert claims_on(d, "B") == {"I1": 0, "I2": 0}
    assert claims_on(d, "C") == {"I1": 3_000_00, "I2": 3_000_00}


def test_retroactive_report_of_an_old_movement():
    """Incidents are reported after the money has already moved on."""
    ledger = world(["v1", "v2", "B", "C", "D"], {"v1": 7_000_00, "v2": 7_000_00})
    o1 = ledger.transfer("v1", "B", 7_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 7_000_00, occurred_at=at(2))
    o2 = ledger.transfer("v2", "B", 7_000_00, occurred_at=at(3))
    ledger.transfer("B", "D", 7_000_00, occurred_at=at(4))
    # Both reported only now, long after the fact.
    d = trace_multi(ledger.journals(), [incident("I1", o1, 900), incident("I2", o2, 950)],
                    TracingRule.LIBR, accounts_of(ledger))
    assert claims_on(d, "C") == {"I1": 7_000_00, "I2": 0}
    assert claims_on(d, "D") == {"I1": 0, "I2": 7_000_00}


def test_through_seq_gives_the_position_at_a_point_in_history():
    ledger = world(["v1", "v2", "B", "C"], {"v1": 5_000_00, "v2": 5_000_00})
    o1 = ledger.transfer("v1", "B", 5_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 5_000_00, occurred_at=at(2))
    moved = ledger.transfer("B", "C", 5_000_00, occurred_at=at(3))
    accounts = accounts_of(ledger)
    incidents = [incident("I1", o1), incident("I2", o2)]

    before = trace_multi(ledger.journals(), incidents, TracingRule.LIBR, accounts,
                         through_seq=moved.seq - 1)
    after = trace_multi(ledger.journals(), incidents, TracingRule.LIBR, accounts)
    assert claims_on(before, "B") == {"I1": 5_000_00, "I2": 5_000_00}
    assert claims_on(after, "B") == {"I1": 0, "I2": 5_000_00}


def test_empty_incident_list_is_an_empty_result():
    ledger = world(["v", "B"], {"v": 1_000_00})
    ledger.transfer("v", "B", 1_000_00, occurred_at=at(1))
    assert trace_multi(ledger.journals(), [], TracingRule.LIBR, accounts_of(ledger)) == {}


# --------------------------------------------------- conservation, C1 to C4


@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    moves=st.lists(
        st.tuples(
            st.sampled_from(["B", "C", "D", "E"]),
            st.sampled_from(["B", "C", "D", "E", "ext"]),
            st.integers(min_value=1, max_value=40_000),
        ),
        min_size=0, max_size=25,
    ),
    rule=st.sampled_from(list(TracingRule)),
    injections=st.lists(
        st.tuples(st.sampled_from(["B", "C", "D", "E"]),
                  st.integers(min_value=1, max_value=50_000)),
        max_size=6,
    ),
)
def test_c1_to_c4_hold_for_two_incidents_under_any_flow(moves, rule, injections):
    """C1: per incident, claims + what left <= the origin.
    C2: per incident, a claim never exceeds the account's balance.
    C4: across every incident, the claims fit inside the balance.

    C4 is the one independent traces violate. It is the reason 5.3 exists.
    """
    ledger = world(["v1", "v2", "B", "C", "D", "E"],
                   {"v1": 60_000, "v2": 40_000, "B": 20_000, "C": 20_000,
                    "D": 20_000, "E": 20_000})
    o1 = ledger.transfer("v1", "B", 60_000, occurred_at=at(1))
    o2 = ledger.transfer("v2", "C", 40_000, occurred_at=at(2))

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

    ledger.check_invariants()
    accounts = accounts_of(ledger)
    incidents = [incident("I1", o1), incident("I2", o2)]
    result = trace_multi(ledger.journals(), incidents, rule, accounts)

    customers = [a.id for a in ledger.accounts() if a.is_customer]
    for key, deriv in result.items():
        accounted = int(deriv.attributable_total) + int(deriv.left_perimeter_paise)
        assert accounted <= int(deriv.origin_paise), f"C1 {rule}/{key}"
        assert all(int(c.amount_paise) >= 0 for c in deriv.claims), f"non-negative {key}"
        for claim in deriv.claims:
            assert int(claim.amount_paise) <= int(ledger.balance(claim.account_id)), (
                f"C2 {rule}/{key}/{claim.account_id}"
            )
    for account in customers:
        total = sum(int(d.claim_for(account)) for d in result.values())
        assert total <= int(ledger.balance(account)), (
            f"C4 {rule}/{account}: claimed {total} of {int(ledger.balance(account))}"
        )


@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    moves=st.lists(
        st.tuples(
            st.sampled_from(["B", "C", "D"]),
            st.sampled_from(["B", "C", "D", "ext"]),
            st.integers(min_value=1, max_value=30_000),
        ),
        max_size=18,
    ),
    rule=st.sampled_from(list(TracingRule)),
)
def test_one_incident_through_the_multi_engine_matches_the_solo_call(moves, rule):
    """However complex the flow, one incident must give the old answer."""
    ledger = world(["v", "B", "C", "D"], {"v": 50_000, "B": 10_000, "C": 10_000,
                                          "D": 10_000})
    origin = ledger.transfer("v", "B", 50_000, occurred_at=at(1))
    clock = 2
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

    accounts = accounts_of(ledger)
    inc = incident("only", origin)
    solo = trace(ledger.journals(), inc, rule, accounts)
    multi = trace_multi(ledger.journals(), [inc], rule, accounts)["only"]
    assert solo.payload() == multi.payload()


# ---------------------------------------------- construction-time rejections


def test_zero_amount_entry_never_reaches_the_engine():
    """An entry of zero paise is refused when it is built, not when it is traced.

    Worth stating: it means neither engine has to carry a branch for it, and a
    journal that reached the trace can be assumed to move value.
    """
    with pytest.raises(ValueError, match="carries no information"):
        Entry("B", 0)


def test_self_transfer_is_refused_at_construction():
    ledger = world(["B"], {"B": 1_000_00})
    with pytest.raises(ValueError, match="same account"):
        ledger.transfer("B", "B", 500_00, occurred_at=at(1))


def test_multi_incident_derivation_is_byte_identical_on_re_run():
    """Purity: no clock, no randomness, no dict-insertion-order dependence."""
    ledger = world(["v1", "v2", "B", "C"], {"v1": 30_000_00, "v2": 30_000_00,
                                            "B": 4_000_00})
    o1 = ledger.transfer("v1", "B", 30_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 30_000_00, occurred_at=at(2))
    ledger.transfer("B", "C", 25_000_00, occurred_at=at(3))

    accounts = accounts_of(ledger)
    incidents = [incident("I1", o1), incident("I2", o2)]
    first = trace_multi(ledger.journals(), incidents, TracingRule.LIBR, accounts)
    second = trace_multi(ledger.journals(), incidents, TracingRule.LIBR, accounts)
    assert {k: v.digest for k, v in first.items()} == {
        k: v.digest for k, v in second.items()
    }
    assert {k: v.payload() for k, v in first.items()} == {
        k: v.payload() for k, v in second.items()
    }
