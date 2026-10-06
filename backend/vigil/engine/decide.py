"""Risk orchestration: one intent in, one RiskDecision out. No money moves here.

Signal order mirrors the brief: A external, B network, C sequence,
D behaviour (+E transaction characteristics), F context.
"""

from __future__ import annotations

import time
from typing import Any

from vigil import clock, db
from vigil.contracts import Intervention, RiskDecision, RiskSignal
from vigil.engine import ledger
from vigil.risk import behaviour, contextflag, external_intel, fusion, reasonline, ringwatch, trailscore
from vigil.settings import get_policy, get_policy_version

INTERVENTION_TEXT = {
    "pass": ("Payment proceeds with no extra step.", "None. Decision logged."),
    "inform": ("Customer sees the reasons and can continue with one tap.", "Logged for pattern review."),
    "confirm_purpose": ("Customer must state the payment purpose to continue; nothing is sent until then.",
                        "Purpose recorded with the decision."),
    "scoped_hold": ("This payment's amount only is held; the account works normally. Customer may cancel.",
                    "Review within the window: release or reject this payment."),
    "hold_and_circuit_breaker": ("Amount held; pre-nominated trusted contact receives facts (not accusations).",
                                 "Priority review: call the customer on their registered number before releasing."),
}


def trusted_contact(account_id: str) -> dict[str, Any] | None:
    return db.q1("SELECT * FROM trusted_contacts WHERE account_id = ? ORDER BY nominated_at LIMIT 1", (account_id,))


def make_intervention(tier: int, amount_paise: int, has_contact: bool) -> Intervention:
    row = fusion.ladder_row(tier)
    kind = row["kind"]
    customer_action, bank_action = INTERVENTION_TEXT[kind]
    return Intervention(
        tier=tier, kind=kind, title=row["title"], customer_action=customer_action, bank_action=bank_action,
        hold_paise=amount_paise if tier >= 3 else 0,
        circuit_breaker=tier == 4 and has_contact,
    )


def evaluate(intent: dict[str, Any]) -> RiskDecision:
    started = time.perf_counter()
    sender_id, recipient_id = intent["sender_id"], intent["recipient_id"]
    amount = int(intent["amount_paise"])
    available = ledger.available_paise(sender_id)

    ext_signals, intel = external_intel.evaluate(recipient_id)
    net_signals, net_features = ringwatch.evaluate(recipient_id)
    seq_signals, journey = trailscore.evaluate(sender_id, amount, available)
    beh_signals, beh_facts = behaviour.evaluate(sender_id, recipient_id, amount, available)
    ctx_signals, ctx_facts = contextflag.evaluate(sender_id, intent.get("note"))

    by_dim: dict[str, list[RiskSignal]] = {
        "external": ext_signals, "network": net_signals, "sequence": seq_signals,
        "behaviour": beh_signals, "context": ctx_signals,
    }
    facts = {
        "external_status": intel.status if intel else "clean",
        "attributable_paise": net_features.get("attributable_paise", 0),
        "prior_payments": beh_facts["prior_payments_to_recipient"],
    }
    fused = fusion.fuse(by_dim, facts)
    contact = trusted_contact(sender_id)
    intervention = make_intervention(fused.tier, amount, contact is not None)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    decision_id = db.next_id("DEC")
    created_at = clock.now_iso()
    all_signals = [s for sigs in by_dim.values() for s in sigs]
    policy_version = get_policy_version()
    audit = {
        "decision_id": decision_id,
        "intent_id": intent["id"],
        "timestamp": created_at,
        "inputs": {
            "sender_id": sender_id, "recipient_id": recipient_id, "amount_paise": amount,
            "note": intent.get("note"), "device_id": intent.get("device_id"), "channel": intent.get("channel"),
            "available_paise": available,
        },
        "subscores": {d.dimension: d.score for d in fused.dimensions},
        "weights": dict(get_policy()["fusion"]["weights"]),
        "contributions": {d.dimension: d.contribution for d in fused.dimensions},
        "base_score": fused.base_score,
        "adjustments": [a.model_dump() for a in fused.adjustments],
        "final_score": fused.final_score,
        "ladder_tier": fused.ladder_tier,
        "tier": fused.tier,
        "intervention": intervention.kind,
        "rules_fired": [{"rule_id": s.rule_id, "evidence": s.evidence, "contribution": s.contribution}
                        for s in all_signals],
        "external_provider": external_intel.provider().name,
        "policy_version": policy_version,
        "evaluation_latency_ms": latency_ms,
        "ml_models_used": [],
    }
    reasons, digest = reasonline.build(
        amount_paise=amount, tier=fused.tier, intervention=intervention, signals=all_signals,
        adjustments=fused.adjustments, dims=fused.dimensions, counterfactual=fused.counterfactual,
        final_score=fused.final_score, journey=journey,
        external=intel.model_dump() if intel else None,
        network={**net_features, "behaviour": beh_facts, "context": ctx_facts},
        contact_name=contact["name"] if contact else None,
        review_minutes=int(get_policy()["scoped_hold"]["review_minutes"]),
        audit=audit,
    )
    return RiskDecision(
        decision_id=decision_id, intent_id=intent["id"], sender_id=sender_id, recipient_id=recipient_id,
        amount_paise=amount, created_at=created_at, dimensions=fused.dimensions, base_score=fused.base_score,
        adjustments=fused.adjustments, final_score=fused.final_score, tier=fused.tier,
        intervention=intervention, rules_fired=[s.rule_id for s in all_signals], reasons=reasons,
        policy_version=policy_version, latency_ms=latency_ms, payload_sha256=digest,
    )

