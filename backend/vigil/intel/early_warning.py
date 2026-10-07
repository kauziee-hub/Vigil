"""Early warning: population-relative port of early_stage_detection (ccmule detection.py:251-359).

Six behavioural signals, each relative to the CURRENT account population (age percentile, velocity
z-score) or a fixed behavioural threshold; an account is flagged only if it has >= 2 signals AND sits
in the top EARLY_TOP_PCT of the population by anomaly score AND the score is >= 0.15 (as the original).
Change from the original: 'New account' is capped at 180 days (the population 30th percentile of a
mature customer base is years, which is not 'new'), pass-through needs >= ₹5,000 of inflow, and every
feature is windowed (vigil/intel/features.py). The score is an anomaly SCORE, not a probability.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

EW_VERSION = "early-warning-v2.0"
EARLY_TOP_PCT = 0.08          # original config.py EARLY_DETECTION_TOP_PCT
MIN_SIGNALS = 2               # original EARLY_DETECTION_MIN_SIGS
MIN_SCORE = 0.15
NEW_ACCOUNT_CAP_DAYS = 180.0


def _quantile(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def raw(f: dict[str, float], stats: dict[str, float]) -> tuple[float, list[str]]:
    signals: list[str] = []
    score = 0.0
    age_ref = min(stats["age_p30"], NEW_ACCOUNT_CAP_DAYS)
    if f["account_age_days"] < age_ref and f["transaction_count"] > 0:
        score += 0.25 * (1.0 - f["account_age_days"] / max(age_ref, 1.0))
        signals.append("New Account")
    if f["device_cluster_size"] >= 3:
        score += 0.20 * min(f["device_cluster_size"] / 10.0, 1.0)
        signals.append("Shared Device")
    if f["retention_ratio"] < 0.20 and f["total_in_amount"] >= 5_000:
        score += 0.20 * (1.0 - f["retention_ratio"] / 0.20)
        signals.append("Pass-Through")
    z = (f["transaction_count"] - stats["mean_tx"]) / stats["std_tx"]
    if z > 1.5:
        score += min(z * 0.08, 0.25)
        signals.append("High Velocity")
    if f["out_degree"] >= 3:
        score += 0.15 * min(f["out_degree"] / 5.0, 1.0)
        signals.append("High Fan-Out")
    if f["unique_channels"] >= 3:
        score += 0.15
        signals.append("Multi-Channel")
    if len(signals) < MIN_SIGNALS:
        score *= 0.2                 # dampen single-signal accounts (original behaviour)
    return round(score, 4), signals


def population_stats(rows: Iterable[dict[str, float]]) -> dict[str, float]:
    rows = list(rows)
    ages = [r["account_age_days"] for r in rows]
    tx = [r["transaction_count"] for r in rows]
    mean_tx = sum(tx) / len(tx) if tx else 0.0
    std_tx = math.sqrt(sum((x - mean_tx) ** 2 for x in tx) / (len(tx) - 1)) if len(tx) > 1 else 1.0
    stats = {"age_p30": _quantile(ages, 0.30), "mean_tx": mean_tx, "std_tx": std_tx if std_tx > 0 else 1.0,
             "n": float(len(rows))}
    scores = sorted((raw(r, stats)[0] for r in rows), reverse=True)
    k = max(1, int(len(scores) * EARLY_TOP_PCT))
    stats["cutoff_score"] = scores[k - 1] if scores else 0.0
    return stats


def evaluate(f: dict[str, float], stats: dict[str, float]) -> dict[str, Any]:
    score, signals = raw(f, stats)
    flagged = len(signals) >= MIN_SIGNALS and score >= max(MIN_SCORE, stats["cutoff_score"])
    return {"score": score, "signals": signals, "flagged": flagged}


def evaluate_population(features: dict[str, dict[str, float]]) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    stats = population_stats(features.values())
    return {a: evaluate(f, stats) for a, f in features.items()}, stats
