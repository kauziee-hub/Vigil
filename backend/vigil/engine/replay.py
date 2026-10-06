"""Decision Replay, counterfactuals, decision records and risk evolution.

Everything here is DETERMINISTIC and reuses the live policy engine
(`risk.fusion.fuse`) on the evidence recorded in the decision. No LLM, no
re-query of live data: replay answers "given what was known at each moment,
what would the policy have said?".
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from vigil import clock, db
from vigil.contracts import (
    Counterfactual, DecisionReplay, DIMENSIONS, ReplayFrame, RiskDecision, RiskSignal,
)
from vigil.engine import lifecycle
from vigil.risk import fusion, trailscore
from vigil.settings import get_policy, get_policy_version

EVENT_LABELS = {
    "login_new_device": "Login from a new device",
    "credential_changed": "Credentials changed",
    "payee_added": "Payee added",
    "limit_raised": "Transfer limit increased",
    "screen_share_active": "Screen sharing active",
    "simulated_context": "Suspicious context captured (SIMULATED)",
    "note_entered": "Payment purpose entered",
    "trusted_contact_response": "Trusted contact responded",
}
SEQ_EVENT = {
    "SEQ_LOGIN_NEW_DEVICE": "login_new_device", "SEQ_CREDENTIAL_CHANGED": "credential_changed",
    "SEQ_PAYEE_ADDED": "payee_added", "SEQ_LIMIT_RAISED": "limit_raised", "SEQ_SCREEN_SHARE_ACTIVE": "screen_share_active",
}
# Signals that only exist once the payment itself is attempted.
AT_INTENT = {"SEQ_ORDERED_CHAIN", "SEQ_LARGE_AFTER_CHANGES"}


def _signals(d: RiskDecision) -> list[RiskSignal]:
    return [s for dim in d.dimensions for s in dim.signals]


def _facts(d: RiskDecision, *, external: bool = True, network: bool = True,
           prior_payments: int | None = None) -> dict[str, Any]:
    by = {s.rule_id: s for s in _signals(d)}
    ext = next((s for s in _signals(d) if s.dimension == "external"), None)
    beh = d.reasons.analyst.network.get("behaviour", {}) if isinstance(d.reasons.analyst.network, dict) else {}
    return {
        "external_status": (ext.evidence.get("status") if ext and external else "clean"),
        "attributable_paise": (by["NET_TAINT_EXPOSURE"].evidence.get("attributable_paise", 0)
                               if network and "NET_TAINT_EXPOSURE" in by else 0),
        "prior_payments": prior_payments if prior_payments is not None else int(beh.get("prior_payments_to_recipient", 0) or 0),
    }


def _score(signals: list[RiskSignal], facts: dict[str, Any]) -> tuple[dict[str, float], float, int]:
    by_dim: dict[str, list[RiskSignal]] = {dim: [] for dim in DIMENSIONS}
    for s in signals:
        by_dim[s.dimension].append(s)
    result = fusion.fuse(by_dim, facts)
    return {d.dimension: d.score for d in result.dimensions}, result.final_score, result.tier


# ── Decision Replay ───────────────────────────────────────────────────────
def replay(decision_id: str) -> DecisionReplay:
    d = lifecycle.get_decision(decision_id)
    intent = lifecycle.get_intent(d.intent_id)
    sigs = _signals(d)
    window = int(get_policy()["sequence"]["window_minutes"])
    journey = [j for j in trailscore.journey(d.sender_id, window_minutes=window, until_iso=d.created_at)
               if j["event_type"] not in {"payment_attempt", "trusted_contact_response", "note_entered"}]

    frames: list[ReplayFrame] = []
    active: list[RiskSignal] = []
    pre_facts = _facts(d, external=False, network=False)

    def add(kind: str, ts: str, label: str, detail: str = "", added: list[RiskSignal] | None = None,
            facts: dict[str, Any] | None = None) -> None:
        if added:
            active.extend(added)
        subs, final, tier = _score(active, facts or pre_facts)
        frames.append(ReplayFrame(index=len(frames), ts=ts, kind=kind, label=label, detail=detail,
                                  signals_added=[s.rule_id for s in added or []], subscores=subs,
                                  final_score=round(final, 4), tier=tier))

    start_ts = journey[0]["ts"] if journey else d.created_at
    add("event", clock.iso(clock.parse(start_ts) - timedelta(seconds=60)) if journey else intent.created_at,
        "Baseline — account behaving normally", "No recent journey events in the evaluation window.")
    ctx_signals = [s for s in sigs if s.dimension == "context"]
    for ev in journey:
        added = [s for s in sigs if SEQ_EVENT.get(s.rule_id) == ev["event_type"] and s not in active]
        if ev["event_type"] == "simulated_context":
            added += [s for s in ctx_signals if s not in active]
        detail = ""
        if ev["event_type"] == "simulated_context":
            detail = str((ev.get("payload") or {}).get("text", ""))[:180]
        elif ev["event_type"] == "limit_raised":
            p = ev.get("payload") or {}
            if p.get("new_limit_paise"):
                detail = f"Daily limit → ₹{int(p['new_limit_paise']) // 100:,}"
        add("event", ev["ts"], EVENT_LABELS.get(ev["event_type"], ev["label"]), detail, added)

    # the payment attempt itself: behaviour + intent-time sequence + note-only context
    at_intent = [s for s in sigs if s.dimension in {"behaviour"} or s.rule_id in AT_INTENT
                 or (s.dimension == "context" and s not in active)]
    add("event", intent.created_at, f"₹{d.amount_paise // 100:,} transfer attempted → {d.recipient_id}",
        "Payment intent created; nothing has moved.", at_intent)
    # recipient intelligence evaluated
    rec = [s for s in sigs if s.dimension in {"external", "network"}]
    add("evaluation", d.created_at, "External + network intelligence evaluated",
        ", ".join(sorted({s.label for s in rec})) or "No recipient-side evidence.", rec, _facts(d))
    leftover = [s for s in sigs if s not in active]
    if leftover:
        add("evaluation", d.created_at, "Remaining evidence", ", ".join(s.label for s in leftover), leftover, _facts(d))
    adj = "; ".join(f"{a.rule_id} {a.effect}" for a in d.adjustments)
    frames.append(ReplayFrame(index=len(frames), ts=d.created_at, kind="decision",
                              label=f"Tier {d.tier} generated — {d.intervention.title}",
                              detail=f"Final {d.final_score:.2f}" + (f" · {adj}" if adj else "") +
                                     (" · SHADOW MODE: not applied" if d.mode == "shadow" else ""),
                              subscores={x.dimension: x.score for x in d.dimensions},
                              final_score=d.final_score, tier=d.tier))
    last = frames[-1]
    for t in intent.transitions:
        if t.to_state in {"CREATED", "RISK_EVALUATED"}:
            continue
        label = {
            "HELD": "Scoped hold created", "ESCALATED": "Scoped hold created + escalation",
            "CHALLENGED": "Customer challenged", "APPROVED": "Approved", "CANCELLED": "Cancelled — nothing sent",
            "REJECTED": "Rejected by bank — nothing sent", "PAYMENT_INITIATED": "Payment provider called",
            "PAYMENT_SUCCEEDED": "Payment succeeded · ledger posted", "PAYMENT_FAILED": "Payment failed",
            "MONITORED": "Post-payment monitoring",
        }.get(t.to_state, t.to_state)
        frames.append(ReplayFrame(index=len(frames), ts=t.ts, kind="outcome" if t.to_state.startswith("PAYMENT") or
                                  t.to_state == "MONITORED" else "action", label=label, detail=t.detail or "",
                                  subscores=last.subscores, final_score=last.final_score, tier=last.tier))
    for cb in db.q("SELECT * FROM circuit_breaker_events WHERE intent_id = ? ORDER BY fired_at", (d.intent_id,)):
        payload = db.loads(cb["payload"], {}) or {}
        frames.append(ReplayFrame(index=0, ts=cb["fired_at"], kind="action",
                                  label=f"Trusted-contact alert dispatched → {payload.get('contact_name', 'contact')}",
                                  detail=payload.get("headline", ""), subscores=last.subscores,
                                  final_score=last.final_score, tier=last.tier))
        if cb["response"]:
            frames.append(ReplayFrame(index=0, ts=cb["responded_at"], kind="action",
                                      label=f"Trusted contact: {cb['response'].replace('_', ' ')}",
                                      subscores=last.subscores, final_score=last.final_score, tier=last.tier))
    head = frames[: next(i for i, f in enumerate(frames) if f.kind == "decision") + 1]
    tail = sorted(frames[len(head):], key=lambda f: f.ts)
    ordered = head + tail
    for i, f in enumerate(ordered):
        f.index = i
    note = DecisionReplay.model_fields["note"].default
    if d.policy_version != get_policy_version():
        note += f" Policy changed since the decision ({d.policy_version} → {get_policy_version()})."
    return DecisionReplay(decision_id=d.decision_id, intent_id=d.intent_id, policy_version=d.policy_version,
                          frames=ordered, note=note)


# ── Counterfactuals ───────────────────────────────────────────────────────
def counterfactuals(decision_id: str) -> list[Counterfactual]:
    d = lifecycle.get_decision(decision_id)
    if d.tier == 0:
        return []  # already the lowest tier: nothing would need to be different
    sigs = _signals(d)
    ids = {s.rule_id for s in sigs}
    seq_chain = {s.rule_id for s in sigs if s.dimension == "sequence"}
    ctx = {s.rule_id for s in sigs if s.dimension == "context"}
    rcpt_new = {"BEH_FIRST_TIME_PAYEE", "SEQ_PAYEE_ADDED"} & ids
    amount = {"BEH_AMOUNT_OUTLIER", "BEH_BALANCE_DRAIN", "SEQ_LARGE_AFTER_CHANGES"} & ids
    network = {s.rule_id for s in sigs if s.dimension == "network"}
    external = {s.rule_id for s in sigs if s.dimension == "external"}

    cases: list[tuple[str, str, set[str], dict[str, Any], list[str]]] = []
    if seq_chain:
        cases.append(("no_sequence", "Without the new-device / payee / limit sequence", seq_chain, {},
                      ["remove journey signals: " + ", ".join(sorted(seq_chain))]))
    if ctx:
        cases.append(("no_context", "Without the (simulated) pressure context", ctx, {},
                      ["remove context signals: " + ", ".join(sorted(ctx))]))
    if rcpt_new:
        cases.append(("established_recipient", "With an established recipient", rcpt_new, {"prior_payments": 6},
                      ["recipient paid 6 times before", "remove " + ", ".join(sorted(rcpt_new))]))
    if amount:
        cases.append(("normal_amount", "With a historically normal amount", amount, {},
                      ["amount within the customer's usual range", "remove " + ", ".join(sorted(amount))]))
    if rcpt_new and amount:
        cases.append(("established_and_normal", "Established recipient + historically normal amount",
                      rcpt_new | amount, {"prior_payments": 6}, ["recipient paid 6 times before", "usual amount"]))
    if rcpt_new and amount and (seq_chain or ctx):
        cases.append(("all_sender_side_normal", "Established recipient + normal amount + no journey/context signals",
                      rcpt_new | amount | seq_chain | ctx, {"prior_payments": 6},
                      ["recipient paid 6 times before", "usual amount", "no device/payee/limit changes", "no pressure context"]))
    if network or external:
        cases.append(("clean_recipient", "If the recipient had a clean network and registry record", network | external,
                      {"external_status": "clean", "attributable_paise": 0},
                      ["no recipient network evidence", "registry: clean"]))
    out: list[Counterfactual] = []
    for cid, label, removed, overrides, changes in cases:
        facts = {**_facts(d), **overrides}
        _, final, tier = _score([s for s in sigs if s.rule_id not in removed], facts)
        out.append(Counterfactual(id=cid, label=label, changes=changes, final_score=round(final, 4), tier=tier,
                                  tier_delta=tier - d.tier))
    out.sort(key=lambda c: (c.tier, c.final_score), reverse=True)
    return out


# ── Decision record (governance) ──────────────────────────────────────────
def record(decision_id: str) -> dict[str, Any]:
    d = lifecycle.get_decision(decision_id)
    intent = lifecycle.get_intent(d.intent_id)
    policy = get_policy()
    tx = db.q1("SELECT * FROM transactions WHERE intent_id = ?", (d.intent_id,))
    models: dict[str, str] = {"policy": d.policy_version, "ringwatch": f"rules · {d.policy_version}",
                              "tainttrace": "prima-lineage (vendored)", "reasonline": "templates-v1"}
    for m in d.model_evidence:
        models[m.family] = m.version
    return {
        "decision": d.model_dump(mode="json"),
        "intent": intent.model_dump(mode="json"),
        "provenance": [{"rule_id": s.rule_id, "dimension": s.dimension, "label": s.label,
                        "contribution": s.contribution, "provenance": s.provenance.model_dump() if s.provenance else None}
                       for s in _signals(d)],
        "model_versions": models,
        "thresholds": policy["ladder"],
        "weights": policy["fusion"]["weights"],
        "reason_codes": d.rules_fired + [a.rule_id for a in d.adjustments],
        "operator_actions": [t.model_dump() for t in intent.transitions if t.actor in {"customer", "bank", "contact"}],
        "payment_result": intent.payment.model_dump() if intent.payment else None,
        "ledger_transaction": tx,
    }


# ── Risk evolution ────────────────────────────────────────────────────────
def risk_timeline(account_id: str) -> list[dict[str, Any]]:
    rows = db.q("SELECT id FROM risk_decisions WHERE sender_id = ? ORDER BY created_at DESC LIMIT 1", (account_id,))
    points: list[dict[str, Any]] = []
    if rows:
        for f in replay(rows[0]["id"]).frames:
            if f.kind in {"event", "evaluation", "decision"}:
                points.append({"ts": f.ts, "score": f.final_score, "tier": f.tier, "label": f.label,
                               "reason": ", ".join(f.signals_added) or f.detail, "decision_id": rows[0]["id"]})
        return points
    # as a recipient: network dimension at each decision about it
    for r in db.q("SELECT record FROM risk_decisions WHERE recipient_id = ? ORDER BY created_at", (account_id,)):
        d = RiskDecision.model_validate_json(r["record"])
        net = next(x for x in d.dimensions if x.dimension == "network")
        points.append({"ts": d.created_at, "score": net.score, "tier": d.tier,
                       "label": f"Payment from {d.sender_id}", "reason": ", ".join(s.label for s in net.signals) or "no network evidence",
                       "decision_id": d.decision_id})
    return points
