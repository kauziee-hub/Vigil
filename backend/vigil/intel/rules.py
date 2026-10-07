"""Rule engine: windowed port of the original rule_based_detection (ccmule detection.py:16-62).

Same six rules and point weights as the original. Thresholds are raised and every feature is measured
over the 72 h window (audit A15: unwindowed `in_degree >= 2` fired for almost any active account).
Thresholds are set a priori from the rule semantics, NOT tuned on the test worlds. The value is a
point SCORE (points / max points), never a probability.
"""

from __future__ import annotations

from typing import Any

RULES_VERSION = "rules-v2.0"
FLAG_POINTS = 4            # two independent rules, or shared device + one more

# (rule_id, label, points, predicate, reason template, old threshold for the record)
_RULES: list[tuple[str, str, int, Any, str, str]] = [
    ("R_FAN_IN", "High in-degree", 2, lambda f: f["in_degree"] >= 4,
     "Received money from {in_degree:.0f} distinct accounts in 72 h", "in_degree >= 2 (unwindowed)"),
    ("R_FAN_OUT", "High out-degree", 2, lambda f: f["out_degree"] >= 4,
     "Sent money to {out_degree:.0f} distinct accounts in 72 h", "out_degree >= 2 (unwindowed)"),
    ("R_LOW_RETENTION", "Low retention", 2, lambda f: f["retention_ratio"] < 0.2 and f["total_in_amount"] >= 10_000,
     "Kept only {retention_ratio:.0%} of ₹{total_in_amount:,.0f} received in 72 h", "retention < 0.2"),
    ("R_SHARED_DEVICE", "Shared device cluster", 3, lambda f: f["device_cluster_size"] >= 3,
     "Its device is bound to {device_cluster_size:.0f} accounts", "device_cluster_size > 2"),
    ("R_CHANNEL_DIVERSITY", "High channel diversity", 2, lambda f: f["unique_channels"] >= 3,
     "Used {unique_channels:.0f} different payment rails in 72 h", "unique_channels > 2"),
    ("R_VELOCITY", "High transaction count", 1, lambda f: f["transaction_count"] >= 8,
     "{transaction_count:.0f} postings in 72 h", "transaction_count >= 3 (unwindowed)"),
]
MAX_POINTS = sum(r[2] for r in _RULES)


def evaluate(f: dict[str, float]) -> dict[str, Any]:
    fired = []
    points = 0
    for rule_id, label, pts, pred, reason, _old in _RULES:
        if pred(f):
            points += pts
            fired.append({"rule_id": rule_id, "label": label, "points": pts, "reason": reason.format(**f)})
    return {"points": points, "max_points": MAX_POINTS, "score": round(points / MAX_POINTS, 4),
            "flagged": points >= FLAG_POINTS, "fired": fired}


def describe() -> list[dict[str, Any]]:
    return [{"rule_id": r[0], "label": r[1], "points": r[2], "old_threshold": r[5]} for r in _RULES]
