"""The analyst-facing API, with more than one incident live.

Step 2 made the engine composable. It did not make the *callers* composable, and
that turned out to matter: ``trace()`` and ``trace_envelope()`` both routed
through ``trace_multi`` with a list of exactly one incident, which from inside
the engine is indistinguishable from "this is the only incident there is". Any
other live incident sharing an account was therefore treated as the account
holder's own clean money -- reintroducing, at the call site, the exact defect the
one-pass engine was built to eliminate.

These tests pin the fix: ``other_live_incidents`` lets a caller asking about one
incident name the others, and the result must then be identical to asking the
engine about all of them at once.

See 04-VALUE-LINEAGE-SPEC.md section 5.3.2.
"""
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from prima.attribution.rules import TracingRule
from prima.attribution.trace import Incident, trace, trace_envelope, trace_multi
from prima.ledger.engine import InsufficientFunds, Ledger
from prima.ledger.models import AccountKind, Entry, JournalKind

ALL_RULES = list(TracingRule)

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


def customers_of(ledger):
    return [a.id for a in ledger.accounts() if a.is_customer]


# ---------------------------------------------------------- the §3 repro


def build_shared_mule():
    """Two Rs 30,000 incidents into one mule, which then cashes out Rs 29,999.99.

    The near-total exit is the point: it leaves one paisa behind, so a correct
    trace has to decide *which* incident the exit belonged to. Splitting it
    evenly, or letting both claim it, are both wrong.
    """
    ledger = world(["v1", "v2", "mule"], {"v1": 30_000_00, "v2": 30_000_00})
    o1 = ledger.transfer("v1", "mule", 30_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "mule", 30_000_00, occurred_at=at(2))
    ledger.external_debit("mule", 29_999_99, destination_account_id="ext",
                          occurred_at=at(3))
    ledger.check_invariants()
    return ledger, incident("I1", o1), incident("I2", o2)


def test_the_reported_bug_overclaims_without_the_new_parameter():
    """The defect itself, kept as a test so it cannot come back unnoticed.

    Without naming the other live incident, each call claims the whole balance
    and the two together claim twice what the account holds.
    """
    ledger, i1, i2 = build_shared_mule()
    accounts = accounts_of(ledger)
    balance = int(ledger.balance("mule"))

    blind1 = trace_envelope(ledger.journals(), i1, [TracingRule.LIBR], accounts)
    blind2 = trace_envelope(ledger.journals(), i2, [TracingRule.LIBR], accounts)
    overclaim = (
        int(blind1[TracingRule.LIBR].claim_for("mule"))
        + int(blind2[TracingRule.LIBR].claim_for("mule"))
    )
    assert overclaim == 60_000_00
    assert overclaim > balance, "if this stops overclaiming the parameter is moot"


def test_naming_the_other_incident_restores_c4():
    """The same two calls, told about each other, now fit inside the balance."""
    ledger, i1, i2 = build_shared_mule()
    accounts = accounts_of(ledger)
    balance = int(ledger.balance("mule"))

    got1 = trace_envelope(ledger.journals(), i1, [TracingRule.LIBR], accounts,
                          other_live_incidents=[i2])[TracingRule.LIBR]
    got2 = trace_envelope(ledger.journals(), i2, [TracingRule.LIBR], accounts,
                          other_live_incidents=[i1])[TracingRule.LIBR]

    total = int(got1.claim_for("mule")) + int(got2.claim_for("mule"))
    assert total <= balance, f"C4: claimed {total} of {balance}"
    assert total == balance == 30_000_01

    # And each is exactly what the engine says when asked about both at once.
    reference = trace_multi(ledger.journals(), [i1, i2], TracingRule.LIBR, accounts)
    assert got1.payload() == reference["I1"].payload()
    assert got2.payload() == reference["I2"].payload()
    assert got1.digest == reference["I1"].digest
    assert got2.digest == reference["I2"].digest

    # The exit belonged to one incident, not to both and not to neither.
    left = (int(got1.left_perimeter_paise), int(got2.left_perimeter_paise))
    assert sorted(left) == [0, 29_999_99]


def test_trace_single_incident_also_takes_other_live_incidents():
    ledger, i1, i2 = build_shared_mule()
    accounts = accounts_of(ledger)
    got = trace(ledger.journals(), i1, TracingRule.LIBR, accounts,
                other_live_incidents=[i2])
    reference = trace_multi(ledger.journals(), [i1, i2], TracingRule.LIBR, accounts)
    assert got.payload() == reference["I1"].payload()


# ------------------------------------------------------- backward compatibility


def test_default_path_is_the_old_single_incident_call_exactly():
    """No ``other_live_incidents`` must mean precisely what it meant before.

    A multi-credit split is the case where rounding could plausibly diverge, so
    it is the one worth pinning, across all four rules and down to the digest.
    """
    ledger = world(["v", "B", "X", "Y", "Z"], {"v": 10_001, "B": 10_001})
    origin = ledger.transfer("v", "B", 10_001, occurred_at=at(1))
    ledger.post(
        JournalKind.TRANSFER,
        (Entry("B", -20_002), Entry("X", 6_667), Entry("Y", 6_667), Entry("Z", 6_668)),
        occurred_at=at(2),
    )
    ledger.check_invariants()

    accounts = accounts_of(ledger)
    inc = incident("solo", origin)
    envelope = trace_envelope(ledger.journals(), inc, ALL_RULES, accounts)
    for rule in ALL_RULES:
        # This is, verbatim, what the old implementation computed.
        old = trace_multi(ledger.journals(), [inc], rule, accounts)["solo"]
        assert envelope[rule].payload() == old.payload(), rule
        assert envelope[rule].digest == old.digest, rule
        assert trace(ledger.journals(), inc, rule, accounts).digest == old.digest, rule


def test_default_envelope_still_reports_a_range():
    """The envelope's whole purpose survives the change."""
    ledger = world(["victim", "B", "C"], {"victim": 10_000_00, "B": 10_000_00})
    origin = ledger.transfer("victim", "B", 10_000_00, occurred_at=at(1))
    ledger.transfer("B", "C", 10_000_00, occurred_at=at(2))
    accounts = accounts_of(ledger)
    env = trace_envelope(ledger.journals(), incident("i", origin), ALL_RULES, accounts)
    spread = {rule: int(d.claim_for("B")) for rule, d in env.items()}
    assert spread[TracingRule.LIBR] == 10_000_00
    assert spread[TracingRule.LIFO] == 0
    assert spread[TracingRule.PRO_RATA] == 5_000_00
    assert len(set(spread.values())) > 1


def test_sequence_call_is_unaffected():
    ledger, i1, i2 = build_shared_mule()
    accounts = accounts_of(ledger)
    via_trace = trace(ledger.journals(), [i1, i2], TracingRule.LIBR, accounts)
    direct = trace_multi(ledger.journals(), [i1, i2], TracingRule.LIBR, accounts)
    assert {k: v.digest for k, v in via_trace.items()} == {
        k: v.digest for k, v in direct.items()
    }


# ------------------------------------------------------------ order and arity


def build_three_incidents():
    ledger = world(["v1", "v2", "v3", "B", "C"],
                   {"v1": 10_000_00, "v2": 12_000_00, "v3": 8_000_00, "B": 3_000_00})
    o1 = ledger.transfer("v1", "B", 10_000_00, occurred_at=at(1))
    o2 = ledger.transfer("v2", "B", 12_000_00, occurred_at=at(2))
    o3 = ledger.transfer("v3", "B", 8_000_00, occurred_at=at(3))
    ledger.transfer("B", "C", 20_000_00, occurred_at=at(4))
    ledger.external_debit("B", 5_000_00, destination_account_id="ext", occurred_at=at(5))
    ledger.check_invariants()
    return ledger, incident("I1", o1), incident("I2", o2), incident("I3", o3)


def test_order_of_other_live_incidents_does_not_matter():
    """The engine ranks incidents itself; the argument order must be inert."""
    ledger, i1, i2, i3 = build_three_incidents()
    accounts = accounts_of(ledger)
    for rule in ALL_RULES:
        forward = trace_envelope(ledger.journals(), i1, [rule], accounts,
                                 other_live_incidents=[i2, i3])[rule]
        backward = trace_envelope(ledger.journals(), i1, [rule], accounts,
                                  other_live_incidents=[i3, i2])[rule]
        assert forward.payload() == backward.payload(), rule
        assert forward.digest == backward.digest, rule


def test_three_incidents_all_four_rules_match_the_one_pass_engine():
    ledger, i1, i2, i3 = build_three_incidents()
    accounts = accounts_of(ledger)
    incidents = [i1, i2, i3]
    for rule in ALL_RULES:
        reference = trace_multi(ledger.journals(), incidents, rule, accounts)
        for target in incidents:
            others = [i for i in incidents if i.id != target.id]
            got = trace_envelope(ledger.journals(), target, [rule], accounts,
                                 other_live_incidents=others)[rule]
            assert got.payload() == reference[target.id].payload(), (rule, target.id)


def test_three_incidents_respect_c4_through_the_envelope():
    ledger, i1, i2, i3 = build_three_incidents()
    accounts = accounts_of(ledger)
    incidents = [i1, i2, i3]
    for rule in ALL_RULES:
        for account_id in customers_of(ledger):
            total = 0
            for target in incidents:
                others = [i for i in incidents if i.id != target.id]
                got = trace_envelope(ledger.journals(), target, [rule], accounts,
                                     other_live_incidents=others)[rule]
                total += int(got.claim_for(account_id))
            assert total <= int(ledger.balance(account_id)), (rule, account_id)


# ------------------------------------------------------------- rejections


def test_sequence_plus_other_live_incidents_is_refused():
    """Merging the two would guess; ignoring one would answer a different
    question. Neither is acceptable, so it raises."""
    ledger, i1, i2 = build_shared_mule()
    accounts = accounts_of(ledger)
    with pytest.raises(ValueError, match="other_live_incidents applies only"):
        trace(ledger.journals(), [i1], TracingRule.LIBR, accounts,
              other_live_incidents=[i2])


def test_sequence_plus_empty_other_live_incidents_is_fine():
    """The default must not trip the guard."""
    ledger, i1, i2 = build_shared_mule()
    accounts = accounts_of(ledger)
    result = trace(ledger.journals(), [i1, i2], TracingRule.LIBR, accounts,
                   other_live_incidents=())
    assert set(result) == {"I1", "I2"}


def test_duplicate_id_in_other_live_incidents_raises_from_the_engine():
    """The existing check in trace_multi must fire through the new path.

    Deliberately not re-checked in trace(): a second, separately worded guard is
    how two checks drift apart.
    """
    ledger, i1, _ = build_shared_mule()
    accounts = accounts_of(ledger)
    clash = Incident(id="I1", origin_journal_ids={ledger.journals()[-1].id},
                     reported_at=at(99))
    with pytest.raises(ValueError, match="unique"):
        trace_envelope(ledger.journals(), i1, [TracingRule.LIBR], accounts,
                       other_live_incidents=[clash])
    with pytest.raises(ValueError, match="unique"):
        trace(ledger.journals(), i1, TracingRule.LIBR, accounts,
              other_live_incidents=[clash])


def test_origin_contradiction_in_other_live_incidents_raises_from_the_engine():
    ledger, i1, _ = build_shared_mule()
    accounts = accounts_of(ledger)
    same_origin = Incident(
        id="I9", origin_journal_ids=set(i1.origin_journal_ids), reported_at=at(99)
    )
    with pytest.raises(ValueError, match="origin"):
        trace_envelope(ledger.journals(), i1, [TracingRule.LIBR], accounts,
                       other_live_incidents=[same_origin])
    with pytest.raises(ValueError, match="origin"):
        trace(ledger.journals(), i1, TracingRule.LIBR, accounts,
              other_live_incidents=[same_origin])


# ------------------------------------------------------------ the property


ACCOUNTS = ["B", "C", "D", "E"]


@settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(
    n_incidents=st.integers(min_value=2, max_value=4),
    targets=st.lists(st.sampled_from(ACCOUNTS), min_size=4, max_size=4),
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
)
def test_envelope_with_others_named_equals_the_one_pass_engine(
    n_incidents, targets, moves, injections
):
    """The contract, over random traffic.

    For every incident, every rule, and the rest of the live set named, the
    envelope must equal what the engine says when asked about all of them at
    once. Not close -- equal, on claims, on what left the perimeter, on what was
    re-tagged, and on the total.
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
    accounts = accounts_of(ledger)
    customers = customers_of(ledger)
    journals = ledger.journals()

    for rule in ALL_RULES:
        reference = trace_multi(journals, incidents, rule, accounts)
        for target in incidents:
            others = [i for i in incidents if i.id != target.id]
            got = trace_envelope(journals, target, [rule], accounts,
                                 other_live_incidents=others)[rule]
            expected = reference[target.id]
            for account_id in customers:
                assert int(got.claim_for(account_id)) == int(
                    expected.claim_for(account_id)
                ), f"{rule}/{target.id}/{account_id}"
            assert int(got.left_perimeter_paise) == int(expected.left_perimeter_paise)
            assert int(got.retagged_paise) == int(expected.retagged_paise)
            assert int(got.attributable_total) == int(expected.attributable_total)

        # C4 across the whole live set, via the envelope rather than the engine.
        for account_id in customers:
            total = sum(
                int(
                    trace_envelope(
                        journals, target, [rule], accounts,
                        other_live_incidents=[i for i in incidents if i.id != target.id],
                    )[rule].claim_for(account_id)
                )
                for target in incidents
            )
            assert total <= int(ledger.balance(account_id)), f"C4 {rule}/{account_id}"
