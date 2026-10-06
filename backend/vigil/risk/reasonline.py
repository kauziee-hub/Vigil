"""ReasonLine — one decision, three representations. Deterministic templates only.

CUSTOMER: plain language, checkable facts, no accusations, no jargon.
ANALYST : contributions, every fired rule with raw evidence, journey, registry, network.
AUDIT   : exact inputs, scores, policy version, action — hashed (integrity check, not a signature).

No LLM is involved anywhere. Every sentence is rendered from evidence values.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from vigil.contracts import AnalystReason, CustomerReason, Intervention, PolicyAdjustment, ReasonLine, RiskSignal
from vigil.risk.ringwatch import _rupees

# Words the customer-facing text must never contain (accusatory or alarming).
BANNED_CUSTOMER_WORDS = ("fraud", "mule", "criminal", "illegal", "frozen", "blocked", "scammer")

DIMENSION_NAMES = {
    "external": "external intelligence",
    "network": "recipient's network",
    "sequence": "your recent account activity",
    "behaviour": "your usual behaviour",
    "context": "the conversation context",
}


def _customer_fact(sig: RiskSignal) -> str | None:
    e = sig.evidence
    r = sig.rule_id
    if r.startswith("EXT_"):
        return {
            "EXT_CONFIRMED_MULE": "A payment-safety registry (simulated) has confirmed problems with this recipient account.",
            "EXT_REPORTED": "Other customers have reported payments to this recipient to a payment-safety registry (simulated).",
            "EXT_WATCHLIST": "This recipient is on a payment-safety watchlist (simulated).",
        }.get(r)
    if r == "NET_PASS_THROUGH":
        return f"Money sent to this account is usually moved on within {int(e.get('median_forward_minutes') or 60)} minutes."
    if r == "NET_FAN_IN":
        return f"{e['first_time_senders']} people who had never paid this account before sent it money in the last {e['window_hours'] // 24} days."
    if r == "NET_NEW_ACCOUNT_INFLOW":
        return f"This account was opened {e['age_days']} days ago and has already received {_rupees(e['total_in_paise'])}."
    if r in {"NET_LABELLED_ACCOUNT", "NET_LABELLED_NEIGHBOUR"}:
        return "This account is directly linked to money the bank has confirmed was taken from another customer."
    if r == "NET_TAINT_EXPOSURE":
        return f"{_rupees(e['attributable_paise'])} now in this account traces back to a payment the bank confirmed was stolen."
    if r == "NET_FAN_OUT":
        return f"This account quickly sends money on to many others ({e['distinct_recipients']} in 3 days)."
    if r == "SEQ_ORDERED_CHAIN":
        return f"In the last {e['span_minutes']} minutes: new device → new payee → limit raised → this payment."
    if r == "SEQ_LOGIN_NEW_DEVICE":
        return f"Your account was signed in on a new device {e['minutes_ago']} minutes ago."
    if r == "SEQ_LIMIT_RAISED":
        return f"Your transfer limit was raised {e['minutes_ago']} minutes ago."
    if r == "SEQ_PAYEE_ADDED":
        return f"This payee was added {e['minutes_ago']} minutes ago."
    if r == "BEH_FIRST_TIME_PAYEE":
        return "You have never paid this recipient before."
    if r == "BEH_BALANCE_DRAIN":
        return f"This payment is {round(e['balance_fraction'] * 100)}% of your available balance."
    if r == "BEH_AMOUNT_OUTLIER":
        return f"This is much larger than your usual payments (typically {_rupees(e['median_paise'])})."
    if r == "CTX_FEAR_AUTHORITY":
        return "Police, CBI, customs or RBI officials never ask you to transfer money to avoid arrest. There is no 'digital arrest'."
    if r == "CTX_SECRECY":
        return "You were asked to keep this secret. Genuine officials and banks never ask that."
    if r == "CTX_URGENCY":
        return "You are being rushed. A genuine request can wait while you check."
    if r == "CTX_BYPASS_APPROVAL":
        return "No genuine official asks you to move money to a 'safe account' or skip bank checks."
    if r == "CTX_GREED":
        return "Guaranteed or unusually high returns are a common lure."
    return None


# Order in which facts are most useful to a customer.
_FACT_PRIORITY = [
    "CTX_FEAR_AUTHORITY", "SEQ_ORDERED_CHAIN", "NET_TAINT_EXPOSURE", "NET_LABELLED_ACCOUNT",
    "NET_LABELLED_NEIGHBOUR", "EXT_CONFIRMED_MULE", "EXT_REPORTED", "NET_PASS_THROUGH",
    "BEH_FIRST_TIME_PAYEE", "BEH_BALANCE_DRAIN", "CTX_SECRECY", "NET_FAN_IN", "NET_NEW_ACCOUNT_INFLOW",
    "BEH_AMOUNT_OUTLIER", "CTX_BYPASS_APPROVAL", "CTX_URGENCY", "SEQ_LOGIN_NEW_DEVICE",
    "SEQ_LIMIT_RAISED", "SEQ_PAYEE_ADDED", "EXT_WATCHLIST", "NET_FAN_OUT", "CTX_GREED",
]


def _summary_sentence(amount_paise: int, by_rule: dict[str, RiskSignal]) -> str:
    parts = [f"You're sending {_rupees(amount_paise)}"]
    parts.append(" to a recipient you've never paid before." if "BEH_FIRST_TIME_PAYEE" in by_rule else ".")
    clauses = []
    if "NET_TAINT_EXPOSURE" in by_rule or "NET_LABELLED_ACCOUNT" in by_rule or "NET_LABELLED_NEIGHBOUR" in by_rule:
        clauses.append("this recipient is linked to money the bank confirmed was stolen")
    elif "NET_PASS_THROUGH" in by_rule:
        clauses.append("this recipient is linked to a rapid pass-through network")
    elif "EXT_REPORTED" in by_rule or "EXT_CONFIRMED_MULE" in by_rule:
        clauses.append("this recipient has been reported to a payment-safety registry (simulated)")
    if "SEQ_ORDERED_CHAIN" in by_rule:
        clauses.append("your account had a new device, a new payee and a limit increase in the last few minutes")
    if "BEH_BALANCE_DRAIN" in by_rule:
        clauses.append(f"this payment is {round(by_rule['BEH_BALANCE_DRAIN'].evidence['balance_fraction'] * 100)}% of your available balance")
    if not clauses:
        return "".join(parts)
    sentence = clauses[0] if len(clauses) == 1 else ", ".join(clauses[:-1]) + " and " + clauses[-1]
    return "".join(parts) + " " + sentence[0].upper() + sentence[1:] + "."


def _approved_summary(by_rule: dict[str, RiskSignal]) -> str:
    if not by_rule:
        return "Known recipient, usual amount, no warning signs."
    noted = ", ".join(sorted({s.label.lower() for s in by_rule.values()}))
    return f"Approved. Noted ({noted}), but the overall evidence does not justify interrupting you."


def _headline(tier: int, top_dim: str) -> str:
    if tier == 0:
        return "Payment approved"
    sender_side = top_dim in {"sequence", "context"}
    if tier == 1:
        return "Quick heads-up before you pay"
    if tier == 2:
        return "Please confirm before you pay" if not sender_side else "Pause: please check who is asking you to pay"
    if tier == 3:
        return "We're holding this payment while the bank checks the recipient"
    return "We've paused this payment to protect you"


def _next_step(intervention: Intervention, contact_name: str | None, review_minutes: int) -> str:
    if intervention.kind == "pass":
        return "Your payment is going through."
    if intervention.kind == "inform":
        return "You can continue with one tap, or cancel."
    if intervention.kind == "confirm_purpose":
        return "Tell us what this payment is for to continue, or cancel. Nothing has been sent."
    if intervention.kind == "scoped_hold":
        return (f"Only this payment's amount is on hold — your account works normally. "
                f"The bank will review within {review_minutes} minutes. You can cancel any time.")
    who = f"your trusted contact {contact_name}" if contact_name else "your trusted contact"
    return (f"Only this payment's amount is on hold — your account works normally. We've let {who} know, "
            f"and the bank will call you. Hang up on anyone pressuring you. You can cancel any time.")


def assert_customer_safe(reason: CustomerReason) -> None:
    blob = " ".join([reason.headline, reason.summary, reason.what_happens_next, *reason.facts]).lower()
    for word in BANNED_CUSTOMER_WORDS:
        if word in blob:
            raise ValueError(f"banned word in customer reason: {word}")


def canonical_sha256(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build(
    *,
    amount_paise: int,
    tier: int,
    intervention: Intervention,
    signals: list[RiskSignal],
    adjustments: list[PolicyAdjustment],
    dims: list[Any],
    counterfactual: str,
    final_score: float,
    journey: list[dict[str, Any]],
    external: dict[str, Any] | None,
    network: dict[str, Any],
    contact_name: str | None,
    review_minutes: int,
    audit: dict[str, Any],
) -> tuple[ReasonLine, str]:
    by_rule = {s.rule_id: s for s in signals}
    top = max(dims, key=lambda d: d.contribution)
    facts: list[str] = []
    if tier > 0:
        for rule_id in _FACT_PRIORITY:
            if rule_id in by_rule:
                text = _customer_fact(by_rule[rule_id])
                if text and text not in facts:
                    facts.append(text)
            if len(facts) == 4:
                break
    customer = CustomerReason(
        headline=_headline(tier, top.dimension),
        summary=_summary_sentence(amount_paise, by_rule) if tier > 0 else _approved_summary(by_rule),
        facts=facts,
        what_happens_next=_next_step(intervention, contact_name, review_minutes),
    )
    assert_customer_safe(customer)

    ranked = sorted(dims, key=lambda d: -d.contribution)
    top_dims = [f"{d.dimension} {d.contribution:.2f}" for d in ranked if d.contribution > 0][:3]
    analyst = AnalystReason(
        summary=(f"Final score {final_score:.2f} → Tier {tier} ({intervention.kind.replace('_', ' ')}). "
                 + (f"Main drivers: {', '.join(DIMENSION_NAMES[d.dimension] for d in ranked[:2] if d.contribution > 0)}."
                    if top.contribution > 0 else "No risk signals fired.")),
        top_dimensions=top_dims,
        signals=sorted(signals, key=lambda s: -s.contribution),
        adjustments=adjustments,
        counterfactual=counterfactual,
        journey=journey,
        external=external,
        network=network,
    )
    audit_payload = {**audit, "customer_text": customer.model_dump()}
    digest = canonical_sha256(audit_payload)
    audit_payload["payload_sha256"] = digest
    audit_payload["integrity_note"] = "SHA-256 of the canonical payload: an integrity check, not a signature."
    return ReasonLine(customer=customer, analyst=analyst, audit=audit_payload), digest
