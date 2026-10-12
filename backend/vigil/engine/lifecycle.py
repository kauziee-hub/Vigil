"""Payment Intent Gateway — the TransactionIntent state machine.

CREATED → RISK_EVALUATED → APPROVED | CHALLENGED | HELD | ESCALATED
CHALLENGED → APPROVED | CANCELLED
HELD / ESCALATED → APPROVED (bank release) | REJECTED (bank) | CANCELLED (customer)
APPROVED → PAYMENT_INITIATED → PAYMENT_SUCCEEDED → MONITORED
                             → PAYMENT_FAILED → PAYMENT_INITIATED (retry / mock fallback)

Every transition is persisted in `intent_transitions` and pushed over the hub.
Money moves only in `_settle`, only after the provider reports success.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from vigil import clock, db
from vigil.contracts import (
    CreateIntentRequest, IntentState as S, PaymentInfo, RiskDecision, TransactionIntent, Transition,
)
from vigil.engine import decide, ledger
from vigil.engine.ledger import VigilError
from vigil.payments import providers
from vigil.realtime import HUB
from vigil.risk import ringwatch
from vigil.settings import get_policy

ALLOWED: dict[S, set[S]] = {
    S.CREATED: {S.RISK_EVALUATED},
    S.RISK_EVALUATED: {S.APPROVED, S.CHALLENGED, S.HELD, S.ESCALATED},
    S.CHALLENGED: {S.APPROVED, S.CANCELLED},
    S.HELD: {S.APPROVED, S.REJECTED, S.CANCELLED},
    S.ESCALATED: {S.APPROVED, S.REJECTED, S.CANCELLED},
    S.APPROVED: {S.PAYMENT_INITIATED, S.CANCELLED},
    S.PAYMENT_INITIATED: {S.PAYMENT_SUCCEEDED, S.PAYMENT_FAILED},
    S.PAYMENT_FAILED: {S.PAYMENT_INITIATED, S.CANCELLED},
    S.PAYMENT_SUCCEEDED: {S.MONITORED},
}
TERMINAL = {S.CANCELLED, S.REJECTED, S.MONITORED}
TIER_STATE = {0: S.APPROVED, 1: S.CHALLENGED, 2: S.CHALLENGED, 3: S.HELD, 4: S.ESCALATED}


# ── reads ─────────────────────────────────────────────────────────────────
def _row(intent_id: str) -> dict[str, Any]:
    row = db.q1("SELECT * FROM transaction_intents WHERE id = ?", (intent_id,))
    if row is None:
        raise VigilError(404, "unknown_intent", f"No payment intent '{intent_id}'.")
    return row


def get_intent(intent_id: str) -> TransactionIntent:
    row = _row(intent_id)
    transitions = [
        Transition(from_state=t["from_state"], to_state=t["to_state"], actor=t["actor"], detail=t["detail"], ts=t["ts"])
        for t in db.q("SELECT * FROM intent_transitions WHERE intent_id = ? ORDER BY id", (intent_id,))
    ]
    payment = None
    attempt = db.q1("SELECT * FROM payment_attempts WHERE intent_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                    (intent_id,))
    if attempt:
        detail = db.loads(attempt["detail"], {}) or {}
        payment = PaymentInfo(
            provider=attempt["provider"], status=attempt["status"], order_id=attempt["provider_order_id"],
            payment_id=attempt["provider_payment_id"],
            amount_paise=int(row["amount_paise"]),
            label=detail.get("label", providers.MOCK_LABEL),
        )
    return TransactionIntent(
        intent_id=row["id"], sender_id=row["sender_id"], recipient_id=row["recipient_id"],
        amount_paise=row["amount_paise"], note=row["note"], channel=row["channel"], device_id=row["device_id"],
        source=row["source"], state=S(row["state"]), tier=row["tier"], decision_id=row["decision_id"],
        purpose=row["purpose"], hold_id=row["hold_id"], transaction_id=row["transaction_id"], payment=payment,
        created_at=row["created_at"], updated_at=row["updated_at"], transitions=transitions,
    )


def get_decision(decision_id: str) -> RiskDecision:
    row = db.q1("SELECT record FROM risk_decisions WHERE id = ?", (decision_id,))
    if row is None:
        raise VigilError(404, "unknown_decision", f"No decision '{decision_id}'.")
    return RiskDecision.model_validate_json(row["record"])


def decision_summary(d: RiskDecision) -> dict[str, Any]:
    return {
        "decision_id": d.decision_id, "intent_id": d.intent_id, "sender_id": d.sender_id,
        "recipient_id": d.recipient_id, "amount_paise": d.amount_paise, "tier": d.tier,
        "kind": d.intervention.kind, "final_score": d.final_score, "headline": d.reasons.customer.headline,
        "labels": [s.label for s in sorted((s for dim in d.dimensions for s in dim.signals),
                                           key=lambda s: -s.contribution)][:4],
        "latency_ms": d.latency_ms, "created_at": d.created_at,
    }


# ── transitions ───────────────────────────────────────────────────────────
def _transition(intent_id: str, to: S, actor: str, detail: str | None = None, **fields: Any) -> None:
    row = _row(intent_id)
    current = S(row["state"])
    if to not in ALLOWED.get(current, set()):
        raise VigilError(409, "invalid_transition", f"Cannot go from {current.value} to {to.value}.",
                         {"from": current.value, "to": to.value})
    now = clock.now_iso()
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    db.execute(
        f"UPDATE transaction_intents SET state = :state, updated_at = :now{', ' + sets if sets else ''} WHERE id = :id",
        {"state": to.value, "now": now, "id": intent_id, **fields},
    )
    db.insert("intent_transitions", {"intent_id": intent_id, "from_state": current.value, "to_state": to.value,
                                     "actor": actor, "detail": detail, "ts": now})


def _publish(intent_id: str) -> TransactionIntent:
    intent = get_intent(intent_id)
    data = intent.model_dump(mode="json")
    HUB.publish("console", "intent.updated", data)
    HUB.publish(f"pay:{intent.sender_id}", "intent.updated", data)
    return intent


# ── create + evaluate ─────────────────────────────────────────────────────
def create(req: CreateIntentRequest, *, auto_pay: bool | None = None) -> tuple[TransactionIntent, RiskDecision]:
    sender = ledger.account(req.sender_id)
    ledger.account(req.recipient_id)
    if sender["kind"] != "customer":
        raise VigilError(400, "bad_sender", "Only customer accounts can initiate payments.")
    if req.sender_id == req.recipient_id:
        raise VigilError(400, "same_account", "Sender and recipient must differ.")
    if req.amount_paise > ledger.available_paise(req.sender_id):
        raise VigilError(400, "insufficient_funds", "Amount is more than the available balance.",
                         {"available_paise": ledger.available_paise(req.sender_id)})

    now = clock.now_iso()
    with db.tx():
        intent_id = db.next_id("INT")
        db.insert("transaction_intents", {
            "id": intent_id, "sender_id": req.sender_id, "recipient_id": req.recipient_id,
            "amount_paise": req.amount_paise, "note": req.note, "channel": "upi",
            "device_id": req.device_id or sender["primary_device"], "source": req.source,
            "state": S.CREATED.value, "created_at": now, "updated_at": now,
        })
        db.insert("intent_transitions", {"intent_id": intent_id, "from_state": None, "to_state": S.CREATED.value,
                                         "actor": req.source if req.source != "user" else "customer",
                                         "detail": "Payment intent received. No money has moved.", "ts": now})
        if req.context_text:
            db.insert("events", {
                "id": db.next_id("EV"), "account_id": req.sender_id, "event_type": "simulated_context",
                "payload": db.dumps({"text": req.context_text, "channel": "simulated call/message", "simulated": True}),
                "ts": now, "source": "simulated_context",
            })
        decision = decide.evaluate(_row(intent_id))
        db.insert("risk_decisions", {
            "id": decision.decision_id, "intent_id": intent_id, "sender_id": decision.sender_id,
            "recipient_id": decision.recipient_id, "amount_paise": decision.amount_paise,
            "final_score": decision.final_score, "tier": decision.tier, "intervention": decision.intervention.kind,
            "policy_version": decision.policy_version, "latency_ms": decision.latency_ms,
            "payload_sha256": decision.payload_sha256, "record": decision.model_dump_json(), "created_at": decision.created_at,
        })
        _transition(intent_id, S.RISK_EVALUATED, "vigil",
                    f"Score {decision.final_score:.2f} → Tier {decision.tier} in {decision.latency_ms:.0f} ms "
                    f"(policy {decision.policy_version}).", tier=decision.tier, decision_id=decision.decision_id)
        if decision.mode == "shadow":
            # SHADOW MODE: record the recommendation, apply nothing (the bank baseline governs).
            _transition(intent_id, S.APPROVED, "vigil",
                        f"SHADOW MODE — Vigil recommended Tier {decision.tier} ({decision.intervention.title}); "
                        f"not applied. Bank baseline: {decision.baseline.decision if decision.baseline else 'approve'}.")
        else:
            extra: dict[str, Any] = {}
            if decision.tier >= 3:
                extra["hold_id"] = _open_hold(intent_id, req.sender_id, req.amount_paise)
            _transition(intent_id, TIER_STATE[decision.tier], "vigil", decision.intervention.title, **extra)
            if decision.tier >= 1:
                db.insert("alerts", {
                    "id": db.next_id("ALR"), "intent_id": intent_id, "decision_id": decision.decision_id,
                    "account_id": req.sender_id, "recipient_id": req.recipient_id, "tier": decision.tier,
                    "kind": decision.intervention.kind, "status": "open",
                    "headline": decision.reasons.customer.headline,
                    "amount_paise": req.amount_paise, "ts": decision.created_at,
                })
            if decision.tier == 4:
                _fire_circuit_breaker(intent_id, decision)

    HUB.publish("console", "decision.created", {**decision_summary(decision), "source": req.source})
    intent = _publish(intent_id)
    should_auto = auto_pay if auto_pay is not None else req.source in {"ambient", "scenario"}
    if should_auto and intent.state == S.APPROVED:
        intent = pay(intent_id)
    return intent, decision


# ── customer / bank actions ───────────────────────────────────────────────
def acknowledge(intent_id: str, purpose: str | None) -> TransactionIntent:
    row = _row(intent_id)
    if row["state"] != S.CHALLENGED.value:
        raise VigilError(409, "not_challenged", "Only a challenged payment can be acknowledged.")
    if row["tier"] == 2 and len((purpose or "").strip()) < 3:
        raise VigilError(400, "purpose_required", "Please state what this payment is for (at least 3 characters).")
    with db.tx():
        if purpose:
            db.insert("events", {"id": db.next_id("EV"), "account_id": row["sender_id"], "event_type": "note_entered",
                                 "payload": db.dumps({"purpose": purpose.strip(), "intent_id": intent_id}),
                                 "ts": clock.now_iso(), "source": "user"})
        _transition(intent_id, S.APPROVED, "customer",
                    f"Customer confirmed purpose: “{purpose.strip()}”" if purpose else "Customer chose to continue after the heads-up.",
                    purpose=(purpose or "").strip() or None)
        _resolve_alert(intent_id, "customer_continued")
    return _publish(intent_id)


def cancel(intent_id: str) -> TransactionIntent:
    row = _row(intent_id)
    with db.tx():
        _transition(intent_id, S.CANCELLED, "customer", "Customer cancelled. Nothing was sent.")
        _close_hold(intent_id, "cancelled_by_customer")
        _resolve_alert(intent_id, "customer_cancelled")
    HUB.publish("console", "metrics.dirty", {})
    return _publish(row["id"])


def bank_action(intent_id: str, action: str, note: str | None = None) -> TransactionIntent:
    row = _row(intent_id)
    if row["state"] not in {S.HELD.value, S.ESCALATED.value}:
        raise VigilError(409, "not_held", "Only a held or escalated payment can be reviewed.")
    with db.tx():
        if action == "release":
            _close_hold(intent_id, "released")
            _transition(intent_id, S.APPROVED, "bank", note or "Analyst reviewed and released the scoped hold.")
            _resolve_alert(intent_id, "bank_released")
        elif action == "reject":
            _close_hold(intent_id, "rejected")
            _transition(intent_id, S.REJECTED, "bank", note or "Analyst rejected the payment. Nothing was sent.")
            _resolve_alert(intent_id, "bank_rejected")
        else:
            raise VigilError(400, "bad_action", "action must be 'release' or 'reject'.")
    intent = _publish(intent_id)
    if action == "release" and row["source"] in {"scenario", "ambient"}:
        intent = pay(intent_id)
    return intent


# ── holds ─────────────────────────────────────────────────────────────────
def _open_hold(intent_id: str, account_id: str, amount_paise: int) -> str:
    cfg = get_policy()["scoped_hold"]
    hold_id = db.next_id("HLD")
    now = clock.now()
    db.insert("scoped_holds", {
        "id": hold_id, "intent_id": intent_id, "account_id": account_id, "held_paise": amount_paise,
        "reference": f"{cfg['reference_prefix']}{hold_id.split('-')[1]}", "opened_at": clock.iso(now),
        "review_by": clock.iso(now + timedelta(minutes=int(cfg["review_minutes"]))),
    })
    return hold_id


def _close_hold(intent_id: str, outcome: str) -> None:
    db.execute("UPDATE scoped_holds SET released_at = ?, outcome = ? WHERE intent_id = ? AND released_at IS NULL",
               (clock.now_iso(), outcome, intent_id))


def _resolve_alert(intent_id: str, resolution: str) -> None:
    db.execute("UPDATE alerts SET status = 'resolved', resolution = ?, resolved_at = ? WHERE intent_id = ? AND status = 'open'",
               (resolution, clock.now_iso(), intent_id))


# ── CircuitBreaker ────────────────────────────────────────────────────────
def _fire_circuit_breaker(intent_id: str, decision: RiskDecision) -> None:
    contact = decide.trusted_contact(decision.sender_id)
    if contact is None:
        return
    sender = ledger.account(decision.sender_id)
    first = sender["display_name"].split()[0]
    facts: list[str] = []
    by_rule = {s.rule_id: s for d in decision.dimensions for s in d.signals}
    if "BEH_FIRST_TIME_PAYEE" in by_rule or "SEQ_PAYEE_ADDED" in by_rule:
        facts.append("The recipient was added as a payee only minutes ago.")
    if "SEQ_LOGIN_NEW_DEVICE" in by_rule:
        facts.append(f"{first}'s account was signed in on a new device {by_rule['SEQ_LOGIN_NEW_DEVICE'].evidence['minutes_ago']} minutes ago.")
    if "SEQ_LIMIT_RAISED" in by_rule:
        facts.append(f"The transfer limit was raised {by_rule['SEQ_LIMIT_RAISED'].evidence['minutes_ago']} minutes ago.")
    if "BEH_BALANCE_DRAIN" in by_rule:
        facts.append(f"The amount is {round(by_rule['BEH_BALANCE_DRAIN'].evidence['balance_fraction'] * 100)}% of the available balance.")
    payload = {
        "headline": f"An unusually large payment from {first}'s account to a newly-added recipient is awaiting confirmation.",
        "account_holder": sender["display_name"],
        "amount_paise": decision.amount_paise,
        "facts": facts[: int(get_policy()["circuit_breaker"]["facts_max"])],
        "status": "The payment is on hold. Nothing has been sent.",
        "asks": "Please check in with them. You can acknowledge, call them, or tell us this payment is expected.",
        "contact_name": contact["name"],
        "relation": contact["relation"],
    }
    cb_id = db.next_id("CB")
    db.insert("circuit_breaker_events", {"id": cb_id, "intent_id": intent_id, "decision_id": decision.decision_id,
                                         "contact_id": contact["id"], "payload": db.dumps(payload),
                                         "fired_at": clock.now_iso()})
    data = {"breaker_id": cb_id, "intent_id": intent_id, **payload}
    HUB.publish(f"contact:{contact['token']}", "breaker.fired", data)
    HUB.publish("console", "breaker.fired", {**data, "token": contact["token"]})


RESPONSES = {
    "acknowledged": "acknowledged the alert",
    "calling_user": "is calling",
    "marked_expected": "marked the payment as expected",
}


def contact_view(token: str) -> dict[str, Any]:
    contact = db.q1("SELECT * FROM trusted_contacts WHERE token = ?", (token,))
    if contact is None:
        raise VigilError(404, "unknown_token", "This trusted-contact link is not valid.")
    holder = ledger.account(contact["account_id"])
    rows = db.q("SELECT * FROM circuit_breaker_events WHERE contact_id = ? ORDER BY fired_at DESC LIMIT 5", (contact["id"],))
    alerts = [{"breaker_id": r["id"], "intent_id": r["intent_id"], "fired_at": r["fired_at"], "response": r["response"],
               "responded_at": r["responded_at"], **db.loads(r["payload"], {})} for r in rows]
    return {"contact_name": contact["name"], "relation": contact["relation"], "account_holder": holder["display_name"],
            "alerts": alerts}


def contact_respond(token: str, breaker_id: str, response: str) -> dict[str, Any]:
    if response not in RESPONSES:
        raise VigilError(400, "bad_response", f"response must be one of {sorted(RESPONSES)}.")
    contact = db.q1("SELECT * FROM trusted_contacts WHERE token = ?", (token,))
    if contact is None:
        raise VigilError(404, "unknown_token", "This trusted-contact link is not valid.")
    row = db.q1("SELECT * FROM circuit_breaker_events WHERE id = ? AND contact_id = ?", (breaker_id, contact["id"]))
    if row is None:
        raise VigilError(404, "unknown_alert", "No such alert for this contact.")
    now = clock.now_iso()
    with db.tx():
        db.execute("UPDATE circuit_breaker_events SET response = ?, responded_at = ? WHERE id = ?", (response, now, breaker_id))
        db.insert("events", {"id": db.next_id("EV"), "account_id": contact["account_id"],
                             "event_type": "trusted_contact_response",
                             "payload": db.dumps({"contact": contact["name"], "response": response, "intent_id": row["intent_id"]}),
                             "ts": now, "source": "contact"})
    data = {"breaker_id": breaker_id, "intent_id": row["intent_id"], "response": response,
            "text": f"{contact['name']} ({contact['relation']}) {RESPONSES[response]}.", "ts": now}
    HUB.publish("console", "breaker.responded", data)
    HUB.publish(f"pay:{contact['account_id']}", "breaker.responded", data)
    HUB.publish(f"contact:{token}", "breaker.responded", data)
    return data


# ── payment ───────────────────────────────────────────────────────────────
def pay(intent_id: str) -> TransactionIntent:
    row = _row(intent_id)
    if row["state"] not in {S.APPROVED.value, S.PAYMENT_FAILED.value}:
        raise VigilError(409, "not_approved", "Payment can only start after Vigil (or the bank) approves it.",
                         {"state": row["state"]})
    provider = providers.get_provider()
    result = provider.initiate(intent_id, int(row["amount_paise"]))
    now = clock.now_iso()
    with db.tx():
        _transition(intent_id, S.PAYMENT_INITIATED, "provider", f"{result.label}", provider=result.provider,
                    provider_ref=result.order_id)
        db.insert("payment_attempts", {
            "id": db.next_id("PAY"), "intent_id": intent_id, "provider": result.provider,
            "status": result.status if result.status != "succeeded" else "created",
            "provider_order_id": result.order_id, "provider_payment_id": result.payment_id,
            "detail": db.dumps({"label": result.label, "error": result.error}),
            "created_at": now, "updated_at": now,
        })
        if result.status == "failed":
            _transition(intent_id, S.PAYMENT_FAILED, "provider", result.error or "Gateway error.")
    if result.status == "succeeded":
        return _settle(intent_id, result.payment_id, result.label)
    return _publish(intent_id)


def _settle(intent_id: str, payment_ref: str | None, label: str) -> TransactionIntent:
    row = _row(intent_id)
    recipient = row["recipient_id"]
    before_signals, _ = ringwatch.evaluate(recipient)
    before = ringwatch.score(before_signals)
    with db.tx():
        tx = ledger.post(sender_id=row["sender_id"], recipient_id=recipient, amount_paise=int(row["amount_paise"]),
                         note=row["note"], intent_id=intent_id, source=row["source"], device_id=row["device_id"])
        db.execute("UPDATE payment_attempts SET status='succeeded', provider_payment_id=COALESCE(provider_payment_id, ?), "
                   "updated_at=? WHERE intent_id=? AND status != 'failed'", (payment_ref, clock.now_iso(), intent_id))
        _transition(intent_id, S.PAYMENT_SUCCEEDED, "provider", f"{label}. Ledger posting {tx['id']} (seq {tx['seq']}).",
                    transaction_id=tx["id"])
    after_signals, feats = ringwatch.evaluate(recipient)
    after = ringwatch.score(after_signals)
    new_rules = sorted({s.rule_id for s in after_signals} - {s.rule_id for s in before_signals})
    detail = (f"PathGraph edge added {row['sender_id']} → {recipient}. Recipient network score "
              f"{before:.2f} → {after:.2f}" + (f"; new evidence: {', '.join(new_rules)}." if new_rules else "; no new findings."))
    with db.tx():
        _transition(intent_id, S.MONITORED, "vigil", detail)
    if new_rules:
        HUB.publish("console", "monitor.finding", {"account_id": recipient, "before": before, "after": after,
                                                   "new_rules": new_rules, "intent_id": intent_id})
    HUB.publish("console", "ledger.posted", {**tx, "sender_name": row["sender_id"]})
    return _publish(intent_id)
