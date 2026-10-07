"""Early warning: population-relative port of early_stage_detection (ccmule detection.py:251-359).

Six behavioural signals, each relative to the CURRENT account population (age percentile, velocity
z-score) or a fixed behavioural threshold; an account is flagged only if it has >= 2 signals AND sits
in the top EARLY_TOP_PCT of the population by anomaly score AND the score is >= 0.15 (as the original).
Change from the original: 'New account' is capped at 180 days (the population 30th percentile of a
mature customer base is years, which is not 'new'), pass-through needs >= ₹5,000 of inflow, and every
feature is windowed (vigil/intel/features.py). The score is an anomaly SCORE, not a probability.

v3.0 (world v3, ML_VALIDATION_REPORT §10): two signals measured routine busy-ness instead of change, so in a
world with an everyday economy they fired on accounts doing exactly what they always do —
  * 'High Velocity' was relative to the population only: every busy shop (200+ postings per 72 h against a
    population mean of ~9) was "high velocity" at its own normal rate. It now ALSO needs the account to be
    busier than its own 30-day baseline (transaction_count >= VELOCITY_OWN_MULT x baseline_tx_rate +
    VELOCITY_OWN_SLACK). A new account (no baseline) is judged on the population alone, as before.
  * 'High Fan-Out' counted any 3 recipients: an everyday payer who pays three habitual shops in 72 h fanned
    out. It now counts FIRST-TIME recipients (estimated from the windowed features: at most
    min(out_degree, new_counterparty_ratio x unique_neighbors)) — the same principle RingWatch adopted in
    policy 2026.10.07-v3.1 (fan-out = first-time recipients).
Both are evaluated on held-out synthetic worlds (before/after in ML_VALIDATION_REPORT §10.2).
"""

from __future__ import annotations

import math
from typing import Any, Iterable

EW_VERSION = "early-warning-v3.0"
EARLY_TOP_PCT = 0.08          # original config.py EARLY_DETECTION_TOP_PCT
MIN_SIGNALS = 2               # original EARLY_DETECTION_MIN_SIGS
MIN_SCORE = 0.15
NEW_ACCOUNT_CAP_DAYS = 180.0
VELOCITY_OWN_MULT = 2.0       # v3.0: High Velocity also needs >= 2x the account's own baseline rate ...
VELOCITY_OWN_SLACK = 2.0      # ... plus 2 postings (a quiet account going from 1 to 3 postings is not a spike)
FANOUT_MIN_NEW = 3            # v3.0: High Fan-Out = at least 3 (estimated) first-time recipients


def _quantile(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def new_recipients_estimate(f: dict[str, float]) -> float:
    """Upper estimate of first-time recipients in the window from the windowed features (no extra graph access):
    new counterparties (ratio x neighbours) can be senders or recipients, so cap by out_degree."""
    return min(f["out_degree"], round(f["new_counterparty_ratio"] * f["unique_neighbors"]))


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
    own = f["transaction_count"] >= VELOCITY_OWN_MULT * f["baseline_tx_rate"] + VELOCITY_OWN_SLACK
    if z > 1.5 and own:
        score += min(z * 0.08, 0.25)
        signals.append("High Velocity")
    new_out = new_recipients_estimate(f)
    if new_out >= FANOUT_MIN_NEW:
        score += 0.15 * min(new_out / 5.0, 1.0)
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
    """Population statistics + every account's result. raw() is computed once per account (the cutoff needs all
    scores first; the per-account results reuse them)."""
    rows = features
    ages = [r["account_age_days"] for r in rows.values()]
    tx = [r["transaction_count"] for r in rows.values()]
    n = len(tx)
    mean_tx = sum(tx) / n if n else 0.0
    std_tx = math.sqrt(sum((x - mean_tx) ** 2 for x in tx) / (n - 1)) if n > 1 else 1.0
    stats = {"age_p30": _quantile(ages, 0.30), "mean_tx": mean_tx, "std_tx": std_tx if std_tx > 0 else 1.0,
             "n": float(n)}
    raws = {a: raw(f, stats) for a, f in rows.items()}
    scores = sorted((r[0] for r in raws.values()), reverse=True)
    k = max(1, int(len(scores) * EARLY_TOP_PCT))
    stats["cutoff_score"] = scores[k - 1] if scores else 0.0
    cut = max(MIN_SCORE, stats["cutoff_score"])
    out = {a: {"score": s, "signals": sig, "flagged": len(sig) >= MIN_SIGNALS and s >= cut} for a, (s, sig) in raws.items()}
    return out, stats
