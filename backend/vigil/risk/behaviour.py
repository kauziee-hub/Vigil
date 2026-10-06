"""Behavioural evidence: this payment compared with the sender's own history.

Deliberately not called "AI". Robust statistics (median / MAD z-score) and
plain counts that an analyst can re-check by hand.
"""

from __future__ import annotations

import statistics
from datetime import timedelta
from typing import Any

from vigil import clock, db
from vigil.contracts import RiskSignal
from vigil.risk.ringwatch import _rupees
from vigil.settings import get_policy


def history(sender_id: str, recipient_id: str) -> dict[str, Any]:
    cfg = get_policy()["behaviour"]
    since = clock.iso(clock.now() - timedelta(days=int(cfg["history_days"])))
    rows = db.q(
        "SELECT recipient_id, amount_paise, ts FROM transactions "
        "WHERE sender_id = ? AND kind = 'transfer' AND ts >= ? ORDER BY ts",
        (sender_id, since),
    )
    amounts = [int(r["amount_paise"]) for r in rows]
    to_recipient = [r for r in rows if r["recipient_id"] == recipient_id]
    return {
        "count": len(rows),
        "amounts": amounts,
        "median_paise": int(statistics.median(amounts)) if amounts else None,
        "max_paise": max(amounts) if amounts else None,
        "prior_payments_to_recipient": len(to_recipient),
        "last_payment_to_recipient": to_recipient[-1]["ts"] if to_recipient else None,
        "typical_to_recipient_paise": int(statistics.median([int(r["amount_paise"]) for r in to_recipient]))
        if to_recipient else None,
        "last_outbound_ts": rows[-1]["ts"] if rows else None,
    }


def robust_z(value: int, amounts: list[int]) -> float:
    med = statistics.median(amounts)
    mad = statistics.median([abs(a - med) for a in amounts])
    scale = max(1.4826 * mad, 0.25 * med, 20_000)  # floor: ₹200 or 25% of median
    return (value - med) / scale


def evaluate(sender_id: str, recipient_id: str, amount_paise: int, available_paise: int) -> tuple[list[RiskSignal], dict[str, Any]]:
    cfg = get_policy()["behaviour"]
    h = history(sender_id, recipient_id)
    signals: list[RiskSignal] = []

    ao = cfg["amount_outlier"]
    z = None
    if h["count"] >= ao["min_history"]:
        z = round(robust_z(amount_paise, h["amounts"]), 2)
        # Paying an established payee roughly what you usually pay them is not an outlier.
        typical = h["typical_to_recipient_paise"]
        usual_for_payee = typical is not None and amount_paise <= 2.5 * typical
        if z >= ao["robust_z"] and not usual_for_payee:
            signals.append(RiskSignal(
                rule_id="BEH_AMOUNT_OUTLIER", dimension="behaviour", label="Unusually large for you",
                reason=(f"{_rupees(amount_paise)} is far above your usual payments "
                        f"(typical {_rupees(h['median_paise'])}, largest in 6 months {_rupees(h['max_paise'])})."),
                evidence={"robust_z": z, "median_paise": h["median_paise"], "max_paise": h["max_paise"],
                          "history_count": h["count"]},
                contribution=float(ao["contribution"]),
            ))
    if h["prior_payments_to_recipient"] == 0:
        signals.append(RiskSignal(
            rule_id="BEH_FIRST_TIME_PAYEE", dimension="behaviour", label="First payment to this recipient",
            reason="You have never paid this recipient before.",
            evidence={"prior_payments_to_recipient": 0}, contribution=float(cfg["first_time_payee"]["contribution"]),
        ))
    fraction = amount_paise / available_paise if available_paise > 0 else 1.0
    if fraction >= cfg["balance_drain"]["min_fraction"]:
        signals.append(RiskSignal(
            rule_id="BEH_BALANCE_DRAIN", dimension="behaviour", label="Most of your balance",
            reason=f"This payment is {round(fraction * 100)}% of your available balance.",
            evidence={"balance_fraction": round(fraction, 3), "available_paise": available_paise},
            contribution=float(cfg["balance_drain"]["contribution"]),
        ))
    nb = cfg["new_payee_burst"]
    since = clock.iso(clock.now() - timedelta(hours=int(nb["window_hours"])))
    new_payees = int(db.scalar("SELECT COUNT(*) FROM payees WHERE account_id = ? AND added_at >= ?", (sender_id, since)) or 0)
    if new_payees >= nb["min_new_payees"]:
        signals.append(RiskSignal(
            rule_id="BEH_NEW_PAYEE_BURST", dimension="behaviour", label="Several new payees",
            reason=f"{new_payees} new payees were added in the last {nb['window_hours']} hours.",
            evidence={"new_payees": new_payees}, contribution=float(nb["contribution"]),
        ))
    vel = cfg["velocity"]
    since_v = clock.iso(clock.now() - timedelta(minutes=int(vel["window_minutes"])))
    recent = int(db.scalar(
        "SELECT COUNT(*) FROM transaction_intents WHERE sender_id = ? AND created_at >= ?", (sender_id, since_v)) or 0)
    if recent >= vel["min_payments"]:
        signals.append(RiskSignal(
            rule_id="BEH_VELOCITY", dimension="behaviour", label="Many payments quickly",
            reason=f"{recent} payment attempts in the last {vel['window_minutes']} minutes.",
            evidence={"attempts": recent}, contribution=float(vel["contribution"]),
        ))
    ds = cfg["dormant_sender"]
    if h["last_outbound_ts"] is None and h["count"] == 0:
        pass  # brand-new sender: first-time payee already covers it
    elif h["last_outbound_ts"] and clock.minutes_between(h["last_outbound_ts"], clock.now_iso()) / 1440 >= ds["min_quiet_days"]:
        days = int(clock.minutes_between(h["last_outbound_ts"], clock.now_iso()) / 1440)
        signals.append(RiskSignal(
            rule_id="BEH_DORMANT_SENDER", dimension="behaviour", label="Account was quiet",
            reason=f"No outgoing payments for {days} days before this one.",
            evidence={"quiet_days": days}, contribution=float(ds["contribution"]),
        ))
    oh = cfg["odd_hour"]
    hour = clock.now().astimezone(clock.IST).hour
    if oh["start_hour_ist"] <= hour < oh["end_hour_ist"]:
        signals.append(RiskSignal(
            rule_id="BEH_ODD_HOUR", dimension="behaviour", label="Unusual hour",
            reason=f"Payment at {hour:02d}:xx IST, outside your usual hours.",
            evidence={"hour_ist": hour}, contribution=float(oh["contribution"]),
        ))
    facts = {
        "history_count": h["count"],
        "median_paise": h["median_paise"],
        "prior_payments_to_recipient": h["prior_payments_to_recipient"],
        "typical_to_recipient_paise": h["typical_to_recipient_paise"],
        "balance_fraction": round(fraction, 3),
        "robust_z": z,
        "available_paise": available_paise,
    }
    return signals, facts
