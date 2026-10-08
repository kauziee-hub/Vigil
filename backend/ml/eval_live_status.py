"""Live status rule + adaptive model-evidence threshold (v3), with the COMMITTED artefacts. SYNTHETIC VALIDATION.

    cd backend
    <venv>/python ml/eval_live_status.py      # ~1-2 min; writes models/live_status_v1.json

1. The live "flagged" status (vigil/intel/stream.py::classify): strongest calibrated model evidence (RF / GNN)
   >= T AND at least one other detector family flags the account. The INITIAL T is chosen on the 30
   VALIDATION worlds (max F1 over T in [T_MIN, T_MAX], step 0.01; ties -> the higher T) and reported on the 30
   untouched TEST worlds.
2. Offline replay of the adaptive rule (stream.threshold_step) on the TEST worlds: every attack instance is one
   "run" (injected = its mules; false positives = non-mule participants of its tagged postings that are
   flagged), runs replayed in world order; adaptive versus fixed T on the same runs.
No model is fitted here; detector scores come from the serving path (eval_roles_consensus.committed_scores).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402

from ml import datagen  # noqa: E402
from ml.eval_roles_consensus import committed_scores  # noqa: E402
from ml.train_all import DETECTORS, LABEL, MODELS, N_TEST, N_TRAIN, N_VAL, SEED, log, process  # noqa: E402
from vigil.intel import stream as S  # noqa: E402

OUT = MODELS / "live_status_v1.json"
GRID = [round(x, 2) for x in np.arange(S.T_MIN, S.T_MAX + 1e-9, 0.01)]


def evidence(s: dict[str, Any]) -> tuple[np.ndarray, list[str], list[list[str]]]:
    rf, g = s["random_forest"][0], s["gnn"][0]
    risk = np.maximum(rf, g)
    fam = ["random_forest" if a >= b else "gnn" for a, b in zip(rf, g)]
    flagging = [[d for d in DETECTORS if s[d][1][k]] for k in range(len(rf))]
    return risk, fam, flagging


def statuses(risk: np.ndarray, fam: list[str], flagging: list[list[str]], T: float) -> np.ndarray:
    return np.array([S.classify(float(r), f, fl, T) or "" for r, f, fl in zip(risk, fam, flagging)])


def confusion(st: np.ndarray, y: np.ndarray, kind: list[str]) -> dict[str, Any]:
    flag = st == "flagged"
    warn = st == "early_warning"
    tp, fp = int((flag & (y == 1)).sum()), int((flag & (y == 0)).sum())
    fn = int((~flag & (y == 1)).sum())
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else 0.0
    neg = int((y == 0).sum())
    merchants = np.array([k == "merchant" for k in kind])
    return {"tp": tp, "fp": fp, "fn": fn, "precision": None if p is None else round(p, 4),
            "recall": None if r is None else round(r, 4), "f1": round(f1, 4),
            "fp_per_1000_non_mules": round(1000 * fp / neg, 3) if neg else None,
            "non_mules_early_warning_share": round(float((warn & (y == 0)).sum()) / neg, 4) if neg else None,
            "mules_warned_or_flagged": round(float(((warn | flag) & (y == 1)).sum()) / max(1, int((y == 1).sum())), 4),
            "merchants_flagged": int((flag & merchants & (y == 0)).sum())}


def sweep(s: dict[str, Any], grid: list[float] = GRID) -> list[dict[str, Any]]:
    risk, fam, flagging = evidence(s)
    return [{"threshold": T, **confusion(statuses(risk, fam, flagging, T), s["y"], s["kind"])} for T in grid]


def distribution(s: dict[str, Any]) -> dict[str, Any]:
    """Where the model evidence of mules and non-mules sits (why the threshold matters little inside the band)."""
    risk, _, _ = evidence(s)
    y = s["y"]
    edges = [0.0, 0.2, 0.45, 0.6, 0.85, 0.9, 1.0001]
    out = {}
    for name, mask in (("mules", y == 1), ("non_mules", y == 0)):
        h, _ = np.histogram(risk[mask], bins=edges)
        out[name] = {f"[{a:.2f},{min(b, 1.0):.2f}{']' if b > 1 else ')'}": int(c) for a, b, c in zip(edges[:-1], edges[1:], h)}
    return out


def replay(tables: list[dict[str, Any]], s: dict[str, Any], T0: float) -> dict[str, Any]:
    """Adaptive threshold replay over every attack instance of the test worlds, in world order."""
    risk, fam, flagging = evidence(s)
    corr = np.array([any(f != fm for f in fl) for fm, fl in zip(fam, flagging)])
    y = s["y"]
    offsets, o = [], 0
    for t in tables:
        offsets.append(o)
        o += len(t["ids"])
    T = T0
    trajectory, totals = [T0], {"adaptive": [0, 0, 0], "fixed": [0, 0, 0]}   # tp, fn, fp
    runs = []
    for t, off in zip(tables, offsets):
        w = t["world"]
        index = {a: off + k for k, a in enumerate(t["ids"])}
        for atk in w.attacks:
            injected = [index[m] for m in atk["mules"] if m in index]
            if not injected:
                continue
            part = set()
            for a in t["ids"]:
                if any(e.tag == atk["tag"] for e in w.outflows(a)) or any(e.tag == atk["tag"] for e in w.inflows(a)):
                    part.add(index[a])
            non = [k for k in sorted(part) if y[k] == 0]
            out = {}
            for name, thr in (("adaptive", T), ("fixed", T0)):
                flagged = {k for k in set(injected) | set(non)
                           if S.classify(float(risk[k]), fam[k], flagging[k], thr) == "flagged"}
                tp = sum(1 for k in injected if k in flagged)
                fps = [k for k in non if k in flagged]
                totals[name][0] += tp
                totals[name][1] += len(injected) - tp
                totals[name][2] += len(fps)
                out[name] = (tp, fps)
            tp, fps = out["adaptive"]
            missed = [k for k in injected if S.classify(float(risk[k]), fam[k], flagging[k], T) != "flagged"]
            inj = set(injected)

            def collateral(lowered: float, T=T, off=off, n=len(t["ids"]), inj=inj) -> int:
                return int(sum(1 for k in range(off, off + n)
                               if k not in inj and lowered <= risk[k] < T and corr[k]))

            new_t, reason = S.threshold_step(T, [float(risk[k]) for k in fps],
                                             [(float(risk[k]), bool(corr[k])) for k in missed], len(injected), collateral)
            runs.append({"world": w.index, "attack": atk["tag"], "threshold": T, "recall": round(tp / len(injected), 4),
                         "false_positives": len(fps), "next": new_t, "reason": reason})
            T = new_t
            trajectory.append(T)

    def summary(v: list[int]) -> dict[str, Any]:
        tp, fn, fp = v
        return {"tp": tp, "fn": fn, "fp": fp, "recall": round(tp / (tp + fn), 4) if tp + fn else None,
                "precision": round(tp / (tp + fp), 4) if tp + fp else None}

    changes = [r for r in runs if r["next"] != r["threshold"]]
    return {"runs": len(runs), "changes": len(changes), "raised": sum(1 for r in changes if r["next"] > r["threshold"]),
            "lowered": sum(1 for r in changes if r["next"] < r["threshold"]), "final_threshold": T,
            "min_threshold": min(trajectory), "max_threshold": max(trajectory),
            "adaptive": summary(totals["adaptive"]), "fixed": summary(totals["fixed"]),
            "final_threshold_population": confusion(statuses(risk, fam, flagging, T), y, s["kind"]),
            "first_changes": changes[:12]}


def main() -> None:
    t0 = time.perf_counter()
    val_tables = [process(datagen.make_world(i, SEED)) for i in range(N_TRAIN, N_TRAIN + N_VAL)]
    sv = committed_scores(val_tables)
    log(f"validation worlds scored [{time.perf_counter() - t0:.1f}s]")
    test_tables = [process(datagen.make_world(i, SEED)) for i in range(N_TRAIN + N_VAL, N_TRAIN + N_VAL + N_TEST)]
    st = committed_scores(test_tables)
    log(f"test worlds scored [{time.perf_counter() - t0:.1f}s]")
    val = sweep(sv)
    best = max(val, key=lambda r: (r["f1"], r["threshold"]))
    T0 = best["threshold"]
    test = {r["threshold"]: r for r in sweep(st)}
    rep = replay(test_tables, st, T0)
    result = {
        "version": S.STREAM_VERSION, "label": LABEL, "data": "SYNTHETIC",
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "command": "python ml/eval_live_status.py",
        "rule": "flagged = max(calibrated RF, calibrated GNN) >= T AND >= 1 other detector family flags; "
                "early_warning = any family flags or uncorroborated model evidence >= T",
        "threshold": T0,
        "threshold_rule": f"max F1 of the live flagged rule on {N_VAL} validation worlds (T in [{S.T_MIN}, {S.T_MAX}], "
                          "step 0.01, ties -> higher T)",
        "bounds": [S.T_MIN, S.T_MAX], "step": S.T_STEP,
        "validation_at_threshold": best,
        "test_at_threshold": test[T0],
        "test_at": {str(T): test[T] for T in (S.T_MIN, 0.5, 0.6, 0.7, S.T_MAX) if T in test},
        "validation_sweep": val,
        "test_sweep": list(test.values()),
        "test_sweep_beyond_bounds_informational": sweep(st, [0.88, 0.9, 0.92, 0.94, 0.96, 0.98]),
        "test_model_evidence_distribution": distribution(st),
        "adaptive_replay_test_worlds": rep,
        "worlds": {"validation": N_VAL, "test": N_TEST, "seed": SEED},
    }
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print()
    print(LABEL)
    print(f"initial T = {T0} (validation F1 {best['f1']}, P {best['precision']}, R {best['recall']})")
    for T in (S.T_MIN, 0.5, T0, 0.6, 0.7, S.T_MAX):
        r = test.get(T)
        if r:
            print(f"test T={T:.2f}: P={r['precision']} R={r['recall']} F1={r['f1']} FP={r['fp']} "
                  f"(per 1000 non-mules {r['fp_per_1000_non_mules']}), EW share non-mules {r['non_mules_early_warning_share']}, "
                  f"mules warned/flagged {r['mules_warned_or_flagged']}")
    for r in result["test_sweep_beyond_bounds_informational"]:
        print(f"  (beyond bounds, informational) T={r['threshold']}: P={r['precision']} R={r['recall']} F1={r['f1']} FP={r['fp']}")
    print("model evidence distribution (test):", result["test_model_evidence_distribution"])
    print("replay:", {k: rep[k] for k in ("runs", "changes", "raised", "lowered", "final_threshold", "min_threshold",
                                          "max_threshold", "adaptive", "fixed")})
    log(f"written {OUT} [{time.perf_counter() - t0:.1f}s]")


if __name__ == "__main__":
    main()
