"""Behavioural drift: per-account baseline (ten 72 h blocks before the current window) vs current window.

Repairs audit A12: the original standardised with the mean/std of just the two vectors, so every changed
feature contributed exactly 2 regardless of magnitude. Here each feature's change is
    |current - baseline_mean| / (baseline_std + population_scale)
where population_scale is fitted on TRAINING-world populations (backend/models/drift_v2.json), so a jump
from 2 to 19 postings is large and 2 to 3 is not. drift_score = 1 - exp(-RMS(change) / K) in [0, 1).
Levels use cut-offs fitted on training-world non-mule accounts (MEDIUM ~ 90th, HIGH ~ 98th percentile).
The level is a LEVEL, not a probability.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from vigil.intel.features import DRIFT_FEATURES

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
DEFAULT_PARAMS: dict[str, Any] = {
    "version": "drift-v2.0-defaults",
    "k": 2.0,
    "cap": 10.0,
    "scales": {"transaction_count": 1.0, "unique_neighbors": 1.0, "in_degree": 1.0, "out_degree": 1.0,
               "total_in_amount": 5_000.0, "total_out_amount": 5_000.0, "retention_ratio": 0.25,
               "unique_channels": 0.5},
    "medium": 0.45,
    "high": 0.70,
}
_params: dict[str, Any] | None = None

LABELS = {"transaction_count": "transactions per 72 h", "unique_neighbors": "counterparties", "in_degree": "senders",
          "out_degree": "recipients", "total_in_amount": "₹ received", "total_out_amount": "₹ sent",
          "retention_ratio": "retention", "unique_channels": "payment rails"}


def params() -> dict[str, Any]:
    global _params
    if _params is None:
        try:
            _params = json.loads((MODELS_DIR / "drift_v2.json").read_text(encoding="utf-8"))
        except Exception:
            _params = dict(DEFAULT_PARAMS)
    return _params


def set_params(p: dict[str, Any] | None) -> None:
    """Training-time override (ml/train_all.py)."""
    global _params
    _params = p


def assess(profile: dict[str, Any], p: dict[str, Any] | None = None) -> dict[str, Any]:
    p = p or params()
    cur, mean, std = profile["current"], profile["baseline_mean"], profile["baseline_std"]
    rows = []
    sq = 0.0
    for f in DRIFT_FEATURES:
        change = abs(cur[f] - mean[f]) / (std[f] + float(p["scales"][f]))
        change = min(change, float(p["cap"]))
        sq += change * change
        rows.append({"feature": f, "baseline": round(mean[f], 3), "current": round(cur[f], 3),
                     "change": round(change, 3), "direction": "up" if cur[f] > mean[f] else ("down" if cur[f] < mean[f] else "flat")})
    rms = math.sqrt(sq / len(DRIFT_FEATURES))
    score = 1.0 - math.exp(-rms / float(p["k"]))
    level = "HIGH" if score >= p["high"] else ("MEDIUM" if score >= p["medium"] else "LOW")
    rows.sort(key=lambda r: (-r["change"], r["feature"]))
    return {"drift_score": round(score, 4), "level": level, "features": rows,
            "baseline_blocks": profile["baseline_blocks"], "flagged": level == "HIGH"}
