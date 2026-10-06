"""Evaluation helpers. Every number produced here is SYNTHETIC VALIDATION."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score


def _r(x: float) -> float:
    return round(float(x), 4)


def binary(y: np.ndarray, score: np.ndarray, flag: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y).astype(int)
    flag = np.asarray(flag).astype(bool)
    tp = int(((flag) & (y == 1)).sum())
    fp = int(((flag) & (y == 0)).sum())
    fn = int(((~flag) & (y == 1)).sum())
    tn = int(((~flag) & (y == 0)).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    out = {"precision": _r(p), "recall": _r(r), "f1": _r(f1), "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
           "n": int(len(y)), "positives": int(y.sum()), "prevalence": _r(y.mean() if len(y) else 0.0),
           "flag_rate": _r(flag.mean() if len(y) else 0.0)}
    if 0 < y.sum() < len(y):
        out["roc_auc"] = _r(roc_auc_score(y, score))
        out["pr_auc"] = _r(average_precision_score(y, score))
    else:
        out["roc_auc"] = None
        out["pr_auc"] = None
    return out


def best_f1_threshold(y: np.ndarray, score: np.ndarray) -> float:
    prec, rec, thr = precision_recall_curve(y, score)
    f1 = np.where(prec + rec > 0, 2 * prec * rec / np.maximum(prec + rec, 1e-12), 0.0)[:-1]
    if len(thr) == 0:
        return 0.5
    return float(thr[int(np.argmax(f1))])


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> dict[str, Any]:
    y = np.asarray(y).astype(float)
    p = np.clip(np.asarray(p, dtype=float), 0, 1)
    edges = np.linspace(0, 1, bins + 1)
    rows = []
    ece = 0.0
    for k in range(bins):
        lo, hi = edges[k], edges[k + 1]
        m = (p >= lo) & ((p < hi) if k < bins - 1 else (p <= hi))
        if m.sum() == 0:
            rows.append({"lo": _r(lo), "hi": _r(hi), "n": 0, "mean_predicted": None, "observed_rate": None})
            continue
        mp, orate = float(p[m].mean()), float(y[m].mean())
        ece += m.sum() / len(p) * abs(mp - orate)
        rows.append({"lo": _r(lo), "hi": _r(hi), "n": int(m.sum()), "mean_predicted": _r(mp), "observed_rate": _r(orate)})
    return {"bins": rows, "brier": _r(np.mean((p - y) ** 2)), "ece": _r(ece)}


def per_attack(y: np.ndarray, flag: np.ndarray, fam: list[str | None], score: np.ndarray | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    fam_arr = np.array([f or "" for f in fam])
    for f in sorted({x for x in fam if x}):
        m = (fam_arr == f) & (np.asarray(y) == 1)
        n = int(m.sum())
        det = int(np.asarray(flag)[m].sum())
        row = {"mules": n, "detected": det, "recall": _r(det / n) if n else None}
        if score is not None and n:
            neg = np.asarray(y) == 0
            sub = m | neg
            row["pr_auc_vs_negatives"] = _r(average_precision_score(np.asarray(y)[sub], np.asarray(score)[sub]))
        out[f] = row
    return out
