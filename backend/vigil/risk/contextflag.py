"""ContextFlag — deterministic category detection over SIMULATED context.

Vigil cannot read calls, SMS, WhatsApp or Telegram, and does not pretend to.
In this demo the operator supplies "simulated call/message context" text (or
the customer types a payment note). In production, such signals could only
come from legitimate upstream channels with consent / institutional access.

Keyword-stem lexicon, case-insensitive, whole-word-prefix matching. No ML, no LLM.
"""

from __future__ import annotations

import re
from typing import Any

from vigil import clock, db
from vigil.contracts import RiskSignal
from vigil.settings import get_policy

LEXICON: dict[str, tuple[str, ...]] = {
    "urgency": (
        "immediately", "urgent", "right now", "within minutes", "in the next", "today itself",
        "last chance", "expires", "hurry", "asap", "before midnight", "deadline",
    ),
    "secrecy": (
        "don't tell", "do not tell", "dont tell", "keep this secret", "confidential", "tell anyone",
        "tell no one", "don't inform", "do not inform", "not even your family", "without telling", "keep it private", "between us",
    ),
    "fear_authority": (
        "arrest", "warrant", "police", "cbi", "customs", "narcotics", "money laundering",
        "digital arrest", "court", "case registered", "fir", "seized", "legal action", "inspector",
        "rbi officer", "income tax", "trai", "suspended",
    ),
    "greed": (
        "guaranteed return", "double your", "triple", "profit", "bonus", "lottery", "prize",
        "investment opportunity", "high yield", "crypto returns",
    ),
    "bypass_approval": (
        "share otp", "share the otp", "tell me the otp", "bypass", "skip verification",
        "turn off", "ignore the warning", "ignore any warning", "remote access", "anydesk",
        "screen share", "install this app", "verification account", "safe account",
    ),
}

LABELS = {
    "urgency": "Urgency pressure",
    "secrecy": "Told to keep it secret",
    "fear_authority": "Fear / authority impersonation",
    "greed": "Promise of returns",
    "bypass_approval": "Told to bypass safeguards",
}

REASONS = {
    "urgency": "The conversation pressures for an immediate payment",
    "secrecy": "The customer is told not to tell family or the bank",
    "fear_authority": "Someone claims to be police/officials and threatens arrest or legal action",
    "greed": "The conversation promises unusual returns",
    "bypass_approval": "The customer is told to bypass bank safeguards or move money to a 'safe' account",
}

_PATTERNS = {
    cat: [re.compile(r"(?<![a-z])" + re.escape(term).replace(r"\ ", r"\s+")) for term in terms]
    for cat, terms in LEXICON.items()
}


def match(text: str) -> dict[str, list[str]]:
    folded = (text or "").casefold().replace("’", "'")
    hits: dict[str, list[str]] = {}
    for cat, patterns in _PATTERNS.items():
        found = [LEXICON[cat][i] for i, p in enumerate(patterns) if p.search(folded)]
        if found:
            hits[cat] = found
    return hits


def recent_context(sender_id: str) -> list[dict[str, Any]]:
    minutes = int(get_policy()["context"]["window_minutes"])
    since = clock.ago_iso(minutes=minutes)
    rows = db.q(
        "SELECT payload, ts FROM events WHERE account_id = ? AND event_type = 'simulated_context' AND ts >= ? ORDER BY ts",
        (sender_id, since),
    )
    return [{"text": (db.loads(r["payload"], {}) or {}).get("text", ""), "ts": r["ts"],
             "channel": (db.loads(r["payload"], {}) or {}).get("channel", "simulated call")} for r in rows]


def evaluate(sender_id: str, note: str | None) -> tuple[list[RiskSignal], dict[str, Any]]:
    weights = get_policy()["context"]["categories"]
    contexts = recent_context(sender_id)
    corpus = " \n ".join([c["text"] for c in contexts] + ([note] if note else []))
    hits = match(corpus)
    signals = [
        RiskSignal(
            rule_id=f"CTX_{cat.upper()}", dimension="context", label=LABELS[cat],
            reason=f"{REASONS[cat]} (simulated context).",
            evidence={"matched_terms": terms[:4], "simulated": True,
                      "sources": len(contexts) + (1 if note else 0)},
            contribution=float(weights[cat]),
        )
        for cat, terms in hits.items()
    ]
    return signals, {"contexts": contexts, "note": note, "categories": sorted(hits)}
