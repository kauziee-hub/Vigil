"""ACTIVE vs SHADOW mode, and the conventional-bank baseline used for comparison.

SHADOW: Vigil evaluates every intent and records its recommendation, but applies
nothing (no challenge, hold or CircuitBreaker). This is the realistic adoption
path: run in shadow, measure would-be interventions and false challenges against
the bank's existing rules, then enable tiers.
"""

from __future__ import annotations

from typing import Any

from vigil import clock, db
from vigil.contracts import BaselineDecision
from vigil.realtime import HUB

VALID = ("active", "shadow")


def current() -> dict[str, Any]:
    mode = db.get_meta("mode", "active") or "active"
    return {"mode": mode, "since": db.get_meta("mode_since"),
            "note": ("Vigil evaluates and records recommendations but does not intervene."
                     if mode == "shadow" else "Vigil's interventions are applied before payment.")}


def set_mode(mode: str) -> dict[str, Any]:
    if mode not in VALID:
        from vigil.engine.ledger import VigilError
        raise VigilError(400, "bad_mode", "mode must be 'active' or 'shadow'.")
    with db.tx():
        db.set_meta("mode", mode)
        db.set_meta("mode_since", clock.now_iso())
    view = current()
    HUB.publish("console", "mode.changed", view)
    return view


def is_shadow() -> bool:
    return (db.get_meta("mode", "active") or "active") == "shadow"


def baseline(amount_paise: int, prior_payments: int, external_status: str) -> BaselineDecision:
    """A deliberately conventional rule set (amount + new payee + hard registry hit).

    Hand-written stand-in for "what the bank would do without Vigil"; it is a
    comparison baseline, not a model of any specific bank.
    """
    if external_status == "confirmed_mule":
        return BaselineDecision(decision="decline", reason="Recipient on a confirmed-mule list.")
    if amount_paise >= 2_00_000_00:
        return BaselineDecision(decision="otp_step_up", reason="High-value payment (≥ ₹2,00,000): extra OTP.")
    if prior_payments == 0 and amount_paise >= 50_000_00:
        return BaselineDecision(decision="otp_step_up", reason="New payee and ≥ ₹50,000: extra OTP.")
    return BaselineDecision(decision="approve", reason="Within conventional limits.")
