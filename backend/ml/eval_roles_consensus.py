"""Role gate + consensus agreement rule: before / after on the TEST worlds, with the COMMITTED artefacts.

    cd backend
    <venv>/python ml/eval_roles_consensus.py      # ~30 s; writes models/validation_v2_roles_consensus.json

No model is fitted here. roles-v2.1 / consensus-v2.1 only change how existing detector flags are combined,
so the committed RF / GNN / drift / pattern-memory artefacts and thresholds are reused unchanged and scored
through the SERVING path (vigil.intel.models numpy ports + stored isotonic knots). Before writing anything
the script checks that the six families' confusion counts equal the committed models/validation_v2.json
(i.e. the same test worlds and the same flags as the reported metrics). Every number is SYNTHETIC VALIDATION.
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
from ml.train_all import (DETECTORS, LABEL, LEVELS, MODELS, N_TEST, N_TRAIN, N_VAL, SEED, cat, log, process,  # noqa: E402
                          roles_consensus_report, write_roles_consensus)
from vigil.intel import drift as D  # noqa: E402
from vigil.intel import pattern_memory as PM  # noqa: E402
from vigil.intel.models import STORE  # noqa: E402


def committed_scores(tables: list[dict[str, Any]]) -> dict[str, Any]:
    """Detector scores/flags of the committed artefacts, computed exactly as the live service does."""
    STORE.load()
    pm_meta = json.loads((MODELS / "pattern_memory_meta_v2.json").read_text(encoding="utf-8"))
    thr = {"random_forest": float(STORE.rf_meta["threshold"]), "gnn": float(STORE.gnn_meta["threshold"]),
           "pattern_memory": float(pm_meta["threshold"])}
    rf_raw = np.array(STORE.rf_raw([list(x) for x in cat(tables, "X")]))
    rf = np.array([STORE.calibrate(p, "random_forest") for p in rf_raw])
    g_raw = np.concatenate([np.array(STORE.gnn_scores([list(x) for x in t["gnn_raw"]], t["pairs"]))[t["n_ext"]:]
                            for t in tables])
    g = np.array([STORE.calibrate(p, "gnn") for p in g_raw])
    drift = [D.assess(p) for t in tables for p in t["profiles"]]
    sims = np.array([max([m["similarity"] for m in PM.match(s, top=10)] or [0.0]) for t in tables for s in t["sigs"]])
    return {
        "y": cat(tables, "y"), "fam": cat(tables, "fam"), "kind": cat(tables, "kind"), "role": cat(tables, "role"),
        "rules": (cat(tables, "rules_score"), cat(tables, "rules_flag")),
        "random_forest": (rf, rf >= thr["random_forest"]),
        "gnn": (g, g >= thr["gnn"]),
        "early_warning": (cat(tables, "ew_score"), cat(tables, "ew_flag")),
        "drift": (np.array([d["drift_score"] for d in drift]), np.array([d["level"] == "HIGH" for d in drift])),
        "pattern_memory": (sims, sims >= thr["pattern_memory"]),
    }


def check_against_committed(s: dict[str, Any]) -> dict[str, Any]:
    val = json.loads((MODELS / "validation_v2.json").read_text(encoding="utf-8"))
    y = s["y"]
    out: dict[str, Any] = {}
    for d in DETECTORS:
        f = s[d][1]
        got = {"tp": int((f & (y == 1)).sum()), "fp": int((f & (y == 0)).sum()),
               "fn": int((~f & (y == 1)).sum()), "tn": int((~f & (y == 0)).sum())}
        want = val["summary"][d]["confusion"]
        out[d] = {"reproduced": got, "committed": want, "equal": got == want}
    return out


def _fmt_roles(name: str, r: dict[str, Any]) -> str:
    acc = " ".join(f"{k[:5]}={v:.2f}" for k, v in r["accuracy_by_true_role"].items())
    fr = r["false_role_assignments"]
    sub = fr["by_subgroup"]
    return (f"{name:38s} {acc}  mules_with_role={r['mules_with_any_role']['assigned']}/{r['mules_with_any_role']['of']}"
            f"  false_roles={fr['total']} (victims {sub['victim']['flagged']}/{sub['victim']['of']}, salary+large "
            f"{sub['salary_and_large_payment']['flagged']}/{sub['salary_and_large_payment']['of']})")


def _fmt_consensus(name: str, c: dict[str, Any]) -> str:
    m, st = c["at_least_moderate"], c["at_least_strong"]
    return (f"{name:38s} >=moderate P={m['precision']:.3f} R={m['recall']:.3f} FP={m['confusion']['fp']:4d}  "
            f"strong P={st['precision']:.3f} R={st['recall']:.3f} FP={st['confusion']['fp']}")


def main() -> None:
    t0 = time.perf_counter()
    idx = range(N_TRAIN + N_VAL, N_TRAIN + N_VAL + N_TEST)
    tables = [process(datagen.make_world(i, SEED)) for i in idx]
    s = committed_scores(tables)
    check = check_against_committed(s)
    if not all(v["equal"] for v in check.values()):
        raise SystemExit(f"committed artefacts do not reproduce validation_v2.json: {check}")
    rep = roles_consensus_report(tables, s)
    print()
    print(LABEL)
    print(f"test worlds: {len(tables)}, accounts {len(s['y'])}, mules {int(s['y'].sum())}; "
          "six-family flags reproduce validation_v2.json exactly")
    print("ROLES")
    for name, r in rep["roles"].items():
        print(_fmt_roles(name, r))
    print("CONSENSUS (agreement level)")
    for name, c in rep["consensus"].items():
        print(_fmt_consensus(name, c))
    print("levels:", {k: v["level_distribution"] for k, v in rep["consensus"].items() if not k.startswith("alt")})
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    path = write_roles_consensus(rep, "python ml/eval_roles_consensus.py", stamp,
                                 "committed artefacts in backend/models (no retraining; trained_at "
                                 f"{STORE.rf_meta.get('trained_at')})",
                                 {"reproduces_validation_v2": {d: v["equal"] for d, v in check.items()},
                                  "levels": list(LEVELS)})
    log(f"written {path} [{time.perf_counter() - t0:.1f}s]")


if __name__ == "__main__":
    main()
