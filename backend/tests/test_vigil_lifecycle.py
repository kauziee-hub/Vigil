"""Critical-path tests: lifecycle, scenarios, feedback loop, ledger invariants."""

from __future__ import annotations

import sqlite3

import pytest

from vigil import db
from vigil.contracts import CreateIntentRequest, IntentState as S
from vigil.engine import ledger, lifecycle
from vigil.engine.ledger import VigilError
from vigil.graph.pathgraph import GRAPH
from vigil.risk import reasonline, taint
from vigil.sim import scenarios


def decision_of(result):
    return lifecycle.get_decision(result["decision_id"])


def run(sid):
    return [r for r in scenarios.run_sync(sid) if isinstance(r, dict) and r.get("decision_id")]


def test_seed_is_deterministic_and_balanced(world):
    from vigil.sim import seed

    first = db.q("SELECT id, seq, sender_id, recipient_id, amount_paise FROM transactions ORDER BY seq")
    seed.seed()
    second = db.q("SELECT id, seq, sender_id, recipient_id, amount_paise FROM transactions ORDER BY seq")
    assert first == second
    assert len(first) > 1500
    assert ledger.system_total() == 0
    negatives = db.q("SELECT id FROM accounts WHERE kind = 'customer' AND balance_paise < 0")
    assert negatives == []


def test_s0_normal_payment_passes_and_settles(world):
    sender_before = ledger.account("ramesh@vigil")["balance_paise"]
    recipient_before = ledger.account("meena.grocer@vigil")["balance_paise"]
    edges_before = len(GRAPH.inflows("meena.grocer@vigil"))
    [r] = run("s0")
    d = decision_of(r)
    assert d.tier == 0 and d.intervention.kind == "pass"
    intent = lifecycle.get_intent(r["intent_id"])
    assert intent.state == S.MONITORED
    states = [t.to_state for t in intent.transitions]
    assert states == ["CREATED", "RISK_EVALUATED", "APPROVED", "PAYMENT_INITIATED", "PAYMENT_SUCCEEDED", "MONITORED"]
    # debit AND credit, integer paise
    assert ledger.account("ramesh@vigil")["balance_paise"] == sender_before - 500_00
    assert ledger.account("meena.grocer@vigil")["balance_paise"] == recipient_before + 500_00
    assert len(GRAPH.inflows("meena.grocer@vigil")) == edges_before + 1
    assert ledger.system_total() == 0


def test_s1_risky_recipient_intervenes_before_payment(world):
    before = ledger.account("ramesh@vigil")["balance_paise"]
    [r] = run("s1")
    d = decision_of(r)
    assert d.tier == 2
    assert {"EXT_REPORTED", "NET_PASS_THROUGH", "BEH_FIRST_TIME_PAYEE"} <= set(d.rules_fired)
    intent = lifecycle.get_intent(r["intent_id"])
    assert intent.state == S.CHALLENGED
    assert ledger.account("ramesh@vigil")["balance_paise"] == before  # nothing moved
    with pytest.raises(VigilError) as err:
        lifecycle.acknowledge(r["intent_id"], "")
    assert err.value.code == "purpose_required"
    with pytest.raises(VigilError) as err:
        lifecycle.pay(r["intent_id"])
    assert err.value.code == "not_approved"
    cancelled = lifecycle.cancel(r["intent_id"])
    assert cancelled.state == S.CANCELLED
    assert ledger.account("ramesh@vigil")["balance_paise"] == before


def test_s3_coercion_escalates_with_scoped_hold_and_circuit_breaker(world):
    [r] = run("s3")
    d = decision_of(r)
    assert d.tier == 4
    assert d.intervention.circuit_breaker is True
    assert "SEQ_ORDERED_CHAIN" in d.rules_fired and "CTX_FEAR_AUTHORITY" in d.rules_fired
    intent = lifecycle.get_intent(r["intent_id"])
    assert intent.state == S.ESCALATED
    hold = db.q1("SELECT * FROM scoped_holds WHERE intent_id = ?", (r["intent_id"],))
    assert hold["held_paise"] == intent.amount_paise           # scoped to this payment's amount only
    acc = ledger.account("sunita@vigil")
    assert ledger.available_paise("sunita@vigil") == acc["balance_paise"] - intent.amount_paise
    cb = db.q1("SELECT * FROM circuit_breaker_events WHERE intent_id = ?", (r["intent_id"],))
    payload = db.loads(cb["payload"])
    assert "newly-added recipient" in payload["headline"]
    for word in ("fraud", "scam", "mule", "criminal"):
        assert word not in payload["headline"].lower()
    resp = lifecycle.contact_respond("arjun", cb["id"], "calling_user")
    assert resp["response"] == "calling_user"
    # bank rejects → nothing sent, hold closed
    rejected = lifecycle.bank_action(r["intent_id"], "reject")
    assert rejected.state == S.REJECTED
    assert ledger.available_paise("sunita@vigil") == ledger.account("sunita@vigil")["balance_paise"]


def test_bank_release_then_payment(world):
    [r] = run("s3")
    released = lifecycle.bank_action(r["intent_id"], "release")
    # scenario-sourced intents complete automatically after release (mock provider)
    assert released.state == S.MONITORED
    assert ledger.system_total() == 0


def test_s4_false_positive_control_stays_low(world):
    [r] = run("s4")
    d = decision_of(r)
    assert d.tier <= 1
    assert lifecycle.get_intent(r["intent_id"]).state in {S.MONITORED, S.CHALLENGED}


def test_feedback_loop_mule_ring_raises_recipient_risk(world):
    [before] = run("s1")
    lifecycle.cancel(before["intent_id"])
    run("s2")
    tx = db.q1("SELECT id FROM transactions WHERE sender_id='anita.s@vigil' AND recipient_id='kiran.traders@vigil'")
    with db.tx():
        db.insert("fraud_labels", {"id": "LBL-T1", "transaction_id": tx["id"], "grade": "bank_confirmed",
                                   "label": "scam", "labelled_by": "test", "ts": "2026-10-06T00:00:00.000Z"})
    result = taint.run(force=True)
    inc = result["incidents"][0]
    for rule in ("libr", "pro_rata"):
        assert inc["rules"][rule]["conserved"]
        claims = sum(c["amount_paise"] for c in inc["rules"][rule]["claims"])
        assert claims + inc["rules"][rule]["left_perimeter_paise"] <= inc["origin_paise"]
    [after] = run("s1")
    d_before, d_after = decision_of(before), decision_of(after)
    assert d_after.final_score > d_before.final_score
    assert d_after.tier >= 3 > d_before.tier
    assert "NET_LABELLED_ACCOUNT" in d_after.rules_fired
    assert "NET_TAINT_EXPOSURE" in d_after.rules_fired
    # recipient risk alone never triggers the trusted-contact escalation
    assert d_after.tier == 3


def test_customer_text_is_never_accusatory(world):
    run("s2")
    for sid in ("s0", "s1", "s3", "s4"):
        for r in run(sid):
            d = decision_of(r)
            blob = " ".join([d.reasons.customer.headline, d.reasons.customer.summary, *d.reasons.customer.facts]).lower()
            for word in reasonline.BANNED_CUSTOMER_WORDS:
                assert word not in blob, (sid, word)


def test_decision_record_is_complete_and_append_only(world):
    [r] = run("s1")
    d = decision_of(r)
    contributions = round(sum(x.contribution for x in d.dimensions), 3)
    assert contributions == round(d.base_score, 3)
    for field in ("decision_id", "intent_id", "sender_id", "recipient_id", "amount_paise", "created_at",
                  "final_score", "tier", "intervention", "policy_version", "latency_ms", "payload_sha256"):
        assert getattr(d, field) is not None
    assert d.reasons.audit["payload_sha256"] == d.payload_sha256
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE risk_decisions SET tier = 0 WHERE id = ?", (d.decision_id,))


def test_invalid_transition_and_insufficient_funds(world):
    with pytest.raises(VigilError) as err:
        lifecycle.create(CreateIntentRequest(sender_id="ramesh@vigil", recipient_id="meena.grocer@vigil",
                                             amount_paise=10 ** 12))
    assert err.value.code == "insufficient_funds"
    [r] = run("s0")
    with pytest.raises(VigilError) as err:
        lifecycle.cancel(r["intent_id"])
    assert err.value.code == "invalid_transition"


def test_risk_evaluation_is_fast(world):
    run("s2")
    latencies = []
    for _ in range(10):
        for r in run("s1"):
            latencies.append(decision_of(r).latency_ms)
            lifecycle.cancel(r["intent_id"])  # release the scoped hold so funds stay available
    latencies.sort()
    assert latencies[int(0.95 * (len(latencies) - 1))] < 150


def test_victims_are_not_scored_for_paying_a_scam_account(world):
    from vigil.risk import ringwatch

    run("s2")
    tx = db.q1("SELECT id FROM transactions WHERE sender_id='anita.s@vigil' AND recipient_id='kiran.traders@vigil'")
    with db.tx():
        db.insert("fraud_labels", {"id": "LBL-T2", "transaction_id": tx["id"], "grade": "bank_confirmed",
                                   "label": "scam", "labelled_by": "test", "ts": "2026-10-06T00:00:00.000Z"})
    taint.run(force=True)
    for victim in ("anita.s@vigil", "vikram.p@vigil", "joseph.d@vigil"):
        signals, _ = ringwatch.evaluate(victim)
        assert ringwatch.score(signals) == 0, (victim, [s.rule_id for s in signals])
    downstream, _ = ringwatch.evaluate("zenith.exports@vigil")
    assert "NET_LABELLED_NEIGHBOUR" in {s.rule_id for s in downstream}
