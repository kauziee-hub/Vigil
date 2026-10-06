"""Deterministic training + SYNTHETIC VALIDATION for detection intelligence v2.

    cd backend
    <venv>/python ml/train_all.py              # default run (< 10 min CPU), writes backend/models/*
    <venv>/python ml/train_all.py --quick      # smoke run, writes nothing
    <venv>/python ml/train_all.py --no-loao    # skip leave-one-attack-out (iteration only; artefacts say so)
    <venv>/python ml/train_all.py --full-loao  # LOAO GNN with the run-2 budget (60 epochs, patience 15; ~+6 min)

LOAO budget: the default run retrains the GNN ten times (once per held-out family) with at most
LOAO_GNN_EPOCHS epochs and early-stopping patience LOAO_GNN_PATIENCE on validation worlds; the main GNN
uses GNN_PARAMS (120 / 15). LOAO GNN numbers are therefore conservative (see ML_VALIDATION_REPORT §6).

Protocol (repairs docs/ML_VALIDATION_REPORT.md §1):
  * worlds are split BY WORLD: train / validation / test worlds are disjoint and independently generated;
  * all thresholds, calibration, early stopping and drift/pattern parameters use train or validation worlds
    only; every reported number is computed on untouched TEST worlds;
  * leave-one-attack-family-out (LOAO): retrain RF and GNN with one family's mules removed from training,
    measure recall / PR-AUC on that unseen family in the test worlds;
  * old-protocol replication: the original attack-window features + random row split, on the same worlds,
    to show the size of the original leakage.
"""

from __future__ import annotations

import argparse
import hashlib
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
import torch  # noqa: E402
from sklearn.ensemble import RandomForestClassifier  # noqa: E402
from sklearn.isotonic import IsotonicRegression  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from ml import datagen, metrics as M  # noqa: E402
from ml.gnn_torch import FraudGAT, export  # noqa: E402
from vigil.intel import drift as D  # noqa: E402
from vigil.intel import early_warning as EW  # noqa: E402
from vigil.intel import features as F  # noqa: E402
from vigil.intel import pattern_memory as PM  # noqa: E402
from vigil.intel import roles as RO  # noqa: E402
from vigil.intel import rules as R  # noqa: E402
from vigil.intel.models import SHAP_CATEGORIES, build_edge_index, forest_predict, gat_forward, gnn_input_row  # noqa: E402

SEED = 20261006
N_TRAIN, N_VAL, N_TEST = 90, 30, 30
MODELS = BACKEND / "models"
VERSION = "v2.1"
GENERATOR = "backend/ml/datagen.py v2.1 (world-level payday calendar)"
LOAO_GNN_EPOCHS, LOAO_GNN_PATIENCE = 30, 8
FULL_LOAO_GNN_EPOCHS, FULL_LOAO_GNN_PATIENCE = 60, 15
RF_PARAMS = dict(n_estimators=100, max_depth=10, min_samples_leaf=5, max_features="sqrt",
                 class_weight="balanced_subsample", random_state=SEED, n_jobs=-1)
GNN_PARAMS = dict(hidden=32, heads=4, dropout=0.1, lr=5e-3, weight_decay=5e-4, max_epochs=120, patience=15,
                  batch_worlds=10, pos_weight_cap=20.0)
OLD_FEATURES = ["in_degree", "out_degree", "total_in_amount", "total_out_amount", "retention_ratio",
                "unique_neighbors", "unique_channels", "device_cluster_size", "transaction_count"]
DETECTORS = ("rules", "random_forest", "gnn", "early_warning", "drift", "pattern_memory")
LABEL = "SYNTHETIC VALIDATION — computer-generated worlds; not real-bank accuracy."


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── per-world tables ──────────────────────────────────────────────────────
def process(w: datagen.World) -> dict[str, Any]:
    ids = w.scored_accounts()
    feats = {a: F.extract(w, a, w.now_t) for a in ids}
    zero = F.zero_features()
    fo = lambda a: feats.get(a, zero)  # noqa: E731
    ctx = {a: PM.context(w, a, w.now_t, fo) for a in ids}
    ew, _ = EW.evaluate_population(feats)
    rules = {a: R.evaluate(feats[a]) for a in ids}
    nodes = list(datagen.EXTERNALS) + ids
    index = {a: i for i, a in enumerate(nodes)}
    pairs = sorted((index[s], index[d]) for s, d in F.window_pairs(w, nodes, w.now_t))
    raw = [gnn_input_row(None, True) for _ in datagen.EXTERNALS] + [gnn_input_row(feats[a], False) for a in ids]
    return {
        "world": w, "ids": ids, "X": np.array([F.vector(feats[a]) for a in ids]),
        "y": np.array([w.labels[a] for a in ids], dtype=int), "fam": [w.family.get(a) for a in ids],
        "role": [w.role.get(a) for a in ids], "primary": np.array([a in w.primary for a in ids]),
        "kind": [w.kind_hint[a] for a in ids], "feats": feats, "ctx": ctx,
        "ew_score": np.array([ew[a]["score"] for a in ids]), "ew_flag": np.array([ew[a]["flagged"] for a in ids]),
        "rules_score": np.array([rules[a]["score"] for a in ids]), "rules_flag": np.array([rules[a]["flagged"] for a in ids]),
        "profiles": [F.drift_profile(w, a, w.now_t) for a in ids],
        "sigs": [PM.signature(feats[a], ctx[a]) for a in ids],
        "gnn_raw": np.array(raw), "pairs": pairs, "n_ext": len(datagen.EXTERNALS),
    }


def cat(tables: list[dict[str, Any]], key: str) -> Any:
    vals = [t[key] for t in tables]
    if isinstance(vals[0], np.ndarray):
        return np.concatenate(vals)
    return [x for v in vals for x in v]


# ── drift + pattern memory parameters (train worlds only) ────────────────
def fit_drift(train: list[dict[str, Any]]) -> dict[str, Any]:
    floors = {"transaction_count": 1.0, "unique_neighbors": 1.0, "in_degree": 1.0, "out_degree": 1.0,
              "total_in_amount": 2_000.0, "total_out_amount": 2_000.0, "retention_ratio": 0.1, "unique_channels": 0.5}
    devs: dict[str, list[float]] = {f: [] for f in F.DRIFT_FEATURES}
    for t in train:
        for prof, y in zip(t["profiles"], t["y"]):
            if y == 0:
                for f in F.DRIFT_FEATURES:
                    devs[f].append(abs(prof["current"][f] - prof["baseline_mean"][f]))
    scales = {f: round(max(floors[f], float(np.percentile(devs[f], 75))), 4) for f in F.DRIFT_FEATURES}
    p = {"version": f"drift-{VERSION}", "k": 2.0, "cap": 4.0, "breadth_min_features": 2, "breadth_min_change": 1.0,
         "scales": scales, "medium": 0.0, "high": 0.0}
    neg_scores = [D.assess(prof, p)["drift_score"] for t in train for prof, y in zip(t["profiles"], t["y"]) if y == 0]
    p["medium"] = round(float(np.percentile(neg_scores, 90)), 4)
    p["high"] = round(float(np.percentile(neg_scores, 98)), 4)
    p["fitted_on"] = ("training-world non-mule accounts: scales = 75th pct of |current - baseline|; MEDIUM/HIGH = 90th/98th pct "
                      "of drift score; HIGH also needs >= 2 features with change >= 1 (breadth)")
    return p


def fit_patterns(train: list[dict[str, Any]]) -> dict[str, Any]:
    by_fam: dict[str, list[list[float]]] = {}
    for t in train:
        for s, f, prim in zip(t["sigs"], t["fam"], t["primary"]):
            if prim and f:
                by_fam.setdefault(f, []).append(s)
    return PM.build(by_fam, f"pattern-memory-{VERSION}",
                    {"worlds": f"train worlds 0..{N_TRAIN - 1}", "seed": SEED, "accounts": "pattern-defining (primary) mules"})


# ── RF ────────────────────────────────────────────────────────────────────
def export_forest(rf: RandomForestClassifier) -> dict[str, np.ndarray]:
    pos = list(rf.classes_).index(1)
    left, right, feat, thr, p1, offs = [], [], [], [], [], [0]
    depth = 0
    for est in rf.estimators_:
        t = est.tree_
        v = t.value[:, 0, :]
        left.append(t.children_left.astype(np.int32))
        right.append(t.children_right.astype(np.int32))
        feat.append(t.feature.astype(np.int32))
        thr.append(t.threshold.astype(np.float64))
        p1.append((v[:, pos] / np.maximum(v.sum(axis=1), 1e-12)).astype(np.float64))
        offs.append(offs[-1] + t.node_count)
        depth = max(depth, int(t.max_depth))
    return {"left": np.concatenate(left), "right": np.concatenate(right), "feature": np.concatenate(feat),
            "threshold": np.concatenate(thr), "p1": np.concatenate(p1), "offsets": np.array(offs, dtype=np.int64),
            "max_depth": np.array(depth)}


def train_rf(X: np.ndarray, y: np.ndarray) -> RandomForestClassifier:
    rf = RandomForestClassifier(**RF_PARAMS)
    rf.fit(X, y)
    return rf


# ── GNN ───────────────────────────────────────────────────────────────────
def gnn_scaler(train: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    rows = np.concatenate([t["gnn_raw"][t["n_ext"]:] for t in train])
    mean, std = rows.mean(axis=0), rows.std(axis=0)
    mean[-1], std[-1] = 0.0, 1.0                 # is_external indicator stays 0/1
    std[std < 1e-6] = 1.0
    return mean, std


def _batch(tables: list[dict[str, Any]], mean: np.ndarray, std: np.ndarray, exclude_family: str | None = None):
    xs, src, dst, ys, masks = [], [], [], [], []
    off = 0
    for t in tables:
        n = len(t["gnn_raw"])
        xs.append((t["gnn_raw"] - mean) / std)
        for s, d in t["pairs"]:
            src.append(s + off)
            dst.append(d + off)
        y = np.zeros(n)
        y[t["n_ext"]:] = t["y"]
        m = np.zeros(n, dtype=bool)
        m[t["n_ext"]:] = True
        if exclude_family:
            fam = np.array([f or "" for f in t["fam"]])
            m[t["n_ext"]:] &= ~((fam == exclude_family) & (t["y"] == 1))
        ys.append(y)
        masks.append(m)
        off += n
    n_all = off
    loops = torch.arange(n_all)
    s_t, d_t = torch.tensor(src, dtype=torch.long), torch.tensor(dst, dtype=torch.long)
    edges = {"in": (torch.cat([s_t, loops]), torch.cat([d_t, loops])),
             "out": (torch.cat([d_t, loops]), torch.cat([s_t, loops]))}
    return (torch.tensor(np.concatenate(xs), dtype=torch.float32), edges,
            torch.tensor(np.concatenate(ys), dtype=torch.float32), torch.tensor(np.concatenate(masks)))


def gnn_predict_numpy(W: dict[str, Any], t: dict[str, Any], mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    x = (t["gnn_raw"] - mean) / std
    e_in, e_out = build_edge_index(len(x), t["pairs"])
    return gat_forward(W, x, e_in, e_out)[t["n_ext"]:]


def train_gnn(train: list[dict[str, Any]], val: list[dict[str, Any]], mean: np.ndarray, std: np.ndarray,
              exclude_family: str | None = None, max_epochs: int | None = None,
              patience: int | None = None) -> tuple[FraudGAT, dict[str, Any]]:
    torch.manual_seed(SEED)
    g = np.random.default_rng(SEED)
    p = GNN_PARAMS
    model = FraudGAT(din=len(mean), hidden=p["hidden"], heads=p["heads"], dropout=p["dropout"])
    opt = torch.optim.Adam(model.parameters(), lr=p["lr"], weight_decay=p["weight_decay"])
    y_tr = np.concatenate([t["y"] for t in train])
    if exclude_family:
        fam = np.array([f or "" for t in train for f in t["fam"]])
        y_tr = y_tr[~((fam == exclude_family) & (y_tr == 1))]
    pos_weight = torch.tensor(min(p["pos_weight_cap"], (len(y_tr) - y_tr.sum()) / max(1, y_tr.sum())))
    val_batch = [_batch([t], mean, std) for t in val]
    y_val = np.concatenate([t["y"] for t in val])
    if exclude_family:
        fam_v = np.array([f or "" for t in val for f in t["fam"]])
        keep_v = ~((fam_v == exclude_family) & (y_val == 1))
    else:
        keep_v = np.ones(len(y_val), dtype=bool)
    best, best_state, best_epoch, bad = -1.0, None, 0, 0
    order = np.arange(len(train))
    epochs = max_epochs or p["max_epochs"]
    for epoch in range(1, epochs + 1):
        model.train()
        g.shuffle(order)
        for k in range(0, len(order), p["batch_worlds"]):
            x, edges, y, mask = _batch([train[i] for i in order[k:k + p["batch_worlds"]]], mean, std, exclude_family)
            opt.zero_grad()
            logits = model(x, edges)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(logits[mask], y[mask], pos_weight=pos_weight)
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            pv = np.concatenate([torch.sigmoid(model(x, e)).numpy()[m.numpy()] for x, e, _, m in val_batch])
        ap = average_precision_score(y_val[keep_v], pv[keep_v])
        if ap > best + 1e-5:
            best, best_epoch, bad = ap, epoch, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= (patience or p["patience"]):
                break
    model.load_state_dict(best_state)
    model.eval()
    return model, {"best_epoch": best_epoch, "epochs_run": epoch, "val_pr_auc": round(best, 4),
                   "pos_weight": round(float(pos_weight), 3)}


# ── evaluation ────────────────────────────────────────────────────────────
def detector_scores(tables: list[dict[str, Any]], rf: RandomForestClassifier, cal: IsotonicRegression,
                    W: dict[str, Any], cal_g: IsotonicRegression, mean: np.ndarray, std: np.ndarray, drift_p: dict[str, Any],
                    mem: dict[str, Any], thr: dict[str, float]) -> dict[str, Any]:
    X = cat(tables, "X")
    rf_raw = rf.predict_proba(X)[:, list(rf.classes_).index(1)]
    rf_cal = cal.predict(rf_raw)
    gnn_raw = np.concatenate([gnn_predict_numpy(W, t, mean, std) for t in tables])
    gnn = cal_g.predict(gnn_raw)
    drift = [D.assess(p, drift_p) for t in tables for p in t["profiles"]]
    sims = np.array([max([m["similarity"] for m in PM.match(s, mem, top=10)] or [0.0]) for t in tables for s in t["sigs"]])
    out = {
        "y": cat(tables, "y"), "fam": cat(tables, "fam"), "kind": cat(tables, "kind"), "role": cat(tables, "role"),
        "X": X, "active": X[:, F.FEATURES.index("transaction_count")] > 0,
        "rules": (cat(tables, "rules_score"), cat(tables, "rules_flag")),
        "random_forest": (rf_cal, rf_cal >= thr["random_forest"]),
        "rf_raw": rf_raw,
        "gnn": (gnn, gnn >= thr["gnn"]),
        "gnn_raw": gnn_raw,
        "early_warning": (cat(tables, "ew_score"), cat(tables, "ew_flag")),
        "drift": (np.array([d["drift_score"] for d in drift]), np.array([d["level"] == "HIGH" for d in drift])),
        "pattern_memory": (sims, sims >= thr["pattern_memory"]),
    }
    count = sum(out[d][1].astype(int) for d in DETECTORS)
    out["consensus_3of6"] = (count / len(DETECTORS), count >= 3)
    return out


def summarise(s: dict[str, Any]) -> dict[str, Any]:
    res: dict[str, Any] = {}
    y, fam, kind = s["y"], s["fam"], np.array(s["kind"])
    for d in DETECTORS + ("consensus_3of6",):
        score, flag = s[d]
        r = M.binary(y, score, flag)
        act = s["active"]
        r["pr_auc_active_accounts"] = round(float(average_precision_score(y[act], score[act])), 4) if y[act].sum() else None
        r["per_attack"] = M.per_attack(y, flag, fam, score)
        neg = y == 0
        r["false_positives_by_persona"] = {k: {"flagged": int((flag & neg & (kind == k)).sum()), "of": int((neg & (kind == k)).sum())}
                                           for k in sorted(set(kind[neg]))}
        res[d] = r
    return res


def role_accuracy(tables: list[dict[str, Any]], s: dict[str, Any]) -> dict[str, Any]:
    flags = np.stack([s[d][1] for d in DETECTORS], axis=1)
    k = 0
    conf: dict[str, dict[str, int]] = {}
    for t in tables:
        w = t["world"]
        n = len(t["ids"])
        fl = flags[k:k + n]
        flagged = {a for a, row in zip(t["ids"], fl) if row.sum() >= 2}
        for a, row, truth, y in zip(t["ids"], fl, t["role"], t["y"]):
            if y != 1 or truth not in {"collector", "distributor", "entry", "exit", "coordinator"}:
                continue
            got = RO.assess(w, a, w.now_t, t["feats"][a], flagged, row.sum() >= 2, t["ctx"][a]["in_cycle"])["role"]
            conf.setdefault(truth, {}).setdefault(got, 0)
            conf[truth][got] += 1
        k += n
    acc = {r: round(c.get(r, 0) / sum(c.values()), 3) for r, c in conf.items()}
    return {"confusion": conf, "accuracy_by_true_role": acc,
            "note": "Ground-truth roles exist only where the generator assigns one; roles are only assigned to accounts flagged by >= 2 families."}


def old_protocol(worlds: list[datagen.World], honest_test: dict[str, Any]) -> dict[str, Any]:
    """Original protocol on the v2 generator: attack-only features, pooled rows, random 70/30 split."""
    rows, ys = [], []
    for w in worlds:
        view = datagen.AttackOnlyView(w)
        for a in w.scored_accounts():
            f = F.extract(view, a, w.now_t)
            rows.append([f[k] for k in OLD_FEATURES])
            ys.append(w.labels[a])
    X, y = np.array(rows), np.array(ys)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y)
    rf = RandomForestClassifier(n_estimators=200, random_state=42, class_weight="balanced", n_jobs=-1).fit(Xtr, ytr)
    p = rf.predict_proba(Xte)[:, 1]
    leaky = M.binary(yte, p, p >= 0.5)
    idx = [F.FEATURES.index(k) for k in OLD_FEATURES]
    p2 = rf.predict_proba(honest_test["X"][:, idx])[:, 1]
    transfer = M.binary(honest_test["y"], p2, p2 >= 0.5)
    return {"old_protocol_random_row_split": leaky, "old_model_on_honest_test_worlds": transfer,
            "note": "Same worlds. 'Old protocol' sees only injected transactions (attack-window graph, audit A1) and "
                    "splits pooled rows at random (A3). The same model applied to honest windowed features of the test worlds "
                    "shows how much of the old score was leakage."}


def loao(train, val, test, mean, std, base_s, quick: bool, gnn_epochs: int, gnn_patience: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    X_tr, y_tr = cat(train, "X"), cat(train, "y")
    fam_tr = np.array([f or "" for f in cat(train, "fam")])
    X_v, y_v = cat(val, "X"), cat(val, "y")
    fam_v = np.array([f or "" for f in cat(val, "fam")])
    X_te, y_te = cat(test, "X"), cat(test, "y")
    fam_te = np.array([f or "" for f in cat(test, "fam")])
    for fam in datagen.FAMILIES:
        t0 = time.perf_counter()
        keep = ~((fam_tr == fam) & (y_tr == 1))
        rf = RandomForestClassifier(**RF_PARAMS).fit(X_tr[keep], y_tr[keep])
        kv = ~((fam_v == fam) & (y_v == 1))
        pv = rf.predict_proba(X_v)[:, 1]
        thr = M.best_f1_threshold(y_v[kv], pv[kv])
        sub = (y_te == 0) | (fam_te == fam)
        pt = rf.predict_proba(X_te)[:, 1]
        heldout = (fam_te == fam) & (y_te == 1)
        row: dict[str, Any] = {"test_mules": int(heldout.sum())}
        row["random_forest"] = {"recall_unseen": round(float((pt[heldout] >= thr).mean()), 4) if heldout.any() else None,
                                "pr_auc_unseen": round(float(average_precision_score(y_te[sub], pt[sub])), 4),
                                "recall_seen": base_s["per_attack"]["random_forest"].get(fam, {}).get("recall"),
                                "pr_auc_seen": base_s["per_attack"]["random_forest"].get(fam, {}).get("pr_auc_vs_negatives")}
        if not quick:
            model, info = train_gnn(train, val, mean, std, exclude_family=fam, max_epochs=gnn_epochs,
                                    patience=gnn_patience)
            W = export(model)
            pv_g = np.concatenate([gnn_predict_numpy(W, t, mean, std) for t in val])
            thr_g = M.best_f1_threshold(y_v[kv], pv_g[kv])
            pt_g = np.concatenate([gnn_predict_numpy(W, t, mean, std) for t in test])
            row["gnn"] = {"recall_unseen": round(float((pt_g[heldout] >= thr_g).mean()), 4) if heldout.any() else None,
                          "pr_auc_unseen": round(float(average_precision_score(y_te[sub], pt_g[sub])), 4),
                          "recall_seen": base_s["per_attack"]["gnn"].get(fam, {}).get("recall"),
                          "pr_auc_seen": base_s["per_attack"]["gnn"].get(fam, {}).get("pr_auc_vs_negatives"),
                          "best_epoch": info["best_epoch"], "epochs_run": info["epochs_run"],
                          "budget": f"max {gnn_epochs} epochs, patience {gnn_patience}"}
        row["rules_reference_recall"] = base_s["per_attack"]["rules"].get(fam, {}).get("recall")
        out[fam] = row
        log(f"  LOAO {fam:18s} RF unseen recall={row['random_forest']['recall_unseen']} "
            f"(seen {row['random_forest']['recall_seen']})"
            + (f" GNN unseen={row['gnn']['recall_unseen']} (seen {row['gnn']['recall_seen']})" if "gnn" in row else "")
            + f" [{time.perf_counter() - t0:.1f}s]")
    return out


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="small smoke run; writes nothing")
    ap.add_argument("--no-loao", action="store_true", help="skip leave-one-attack-family-out (iteration only)")
    ap.add_argument("--full-loao", action="store_true",
                    help=f"LOAO GNN with {FULL_LOAO_GNN_EPOCHS} epochs / patience {FULL_LOAO_GNN_PATIENCE} (slower)")
    args = ap.parse_args()
    command = "python ml/train_all.py" + "".join(f" {a}" for a in sys.argv[1:])
    loao_epochs, loao_patience = ((FULL_LOAO_GNN_EPOCHS, FULL_LOAO_GNN_PATIENCE) if args.full_loao
                                  else (LOAO_GNN_EPOCHS, LOAO_GNN_PATIENCE))
    t_start = time.perf_counter()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    n_tr, n_va, n_te = (12, 6, 6) if args.quick else (N_TRAIN, N_VAL, N_TEST)
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    worlds = [datagen.make_world(i, SEED) for i in range(n_tr + n_va + n_te)]
    timings["generate_s"] = round(time.perf_counter() - t0, 1)
    t0 = time.perf_counter()
    tables = [process(w) for w in worlds]
    train, val, test = tables[:n_tr], tables[n_tr:n_tr + n_va], tables[n_tr + n_va:]
    timings["features_s"] = round(time.perf_counter() - t0, 1)
    log(f"worlds: train={len(train)} val={len(val)} test={len(test)}  [{timings['generate_s']}s gen, {timings['features_s']}s features]")

    drift_p = fit_drift(train)
    mem = fit_patterns(train)
    log(f"drift params: medium={drift_p['medium']} high={drift_p['high']}; pattern prototypes={len(mem['prototypes'])}")

    t0 = time.perf_counter()
    rf = train_rf(cat(train, "X"), cat(train, "y"))
    pv_raw = rf.predict_proba(cat(val, "X"))[:, 1]
    cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(pv_raw, cat(val, "y"))
    timings["rf_s"] = round(time.perf_counter() - t0, 1)

    t0 = time.perf_counter()
    mean, std = gnn_scaler(train)
    gnn_model, gnn_info = train_gnn(train, val, mean, std)
    W = export(gnn_model)
    timings["gnn_s"] = round(time.perf_counter() - t0, 1)
    log(f"RF trained [{timings['rf_s']}s]; GNN best epoch {gnn_info['best_epoch']} val PR-AUC {gnn_info['val_pr_auc']} [{timings['gnn_s']}s]")

    # thresholds on VALIDATION worlds
    y_v = cat(val, "y")
    pv_gnn_raw = np.concatenate([gnn_predict_numpy(W, t, mean, std) for t in val])
    cal_g = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(pv_gnn_raw, y_v)
    thr = {"random_forest": M.best_f1_threshold(y_v, cal.predict(pv_raw)),
           "gnn": M.best_f1_threshold(y_v, cal_g.predict(pv_gnn_raw)),
           "pattern_memory": M.best_f1_threshold(y_v, np.array([max(m["similarity"] for m in PM.match(s, mem, top=10)) for t in val for s in t["sigs"]]))}
    thr = {k: round(float(v), 4) for k, v in thr.items()}
    log(f"validation thresholds: {thr}")

    s_test = detector_scores(test, rf, cal, W, cal_g, mean, std, drift_p, mem, thr)
    summary = summarise(s_test)
    per_attack = {d: summary[d]["per_attack"] for d in DETECTORS}
    calib = {"random_forest_calibrated": M.calibration(s_test["y"], s_test["random_forest"][0]),
             "random_forest_raw": M.calibration(s_test["y"], s_test["rf_raw"]),
             "gnn_calibrated": M.calibration(s_test["y"], s_test["gnn"][0]),
             "gnn_raw": M.calibration(s_test["y"], s_test["gnn_raw"])}
    roles_eval = role_accuracy(test, s_test)

    # numpy ports equal the trained models
    Xc = cat(test, "X")[:400]
    arr = export_forest(rf)
    rf_check = float(np.abs(forest_predict(arr, Xc) - rf.predict_proba(Xc)[:, 1]).max())
    with torch.no_grad():
        xb, eb, _, mb = _batch([test[0]], mean, std)
        torch_out = torch.sigmoid(gnn_model(xb, eb)).numpy()[mb.numpy()]
    gnn_check = float(np.abs(torch_out - gnn_predict_numpy(W, test[0], mean, std)).max())
    log(f"port checks: RF max|numpy-sklearn|={rf_check:.2e}  GNN max|numpy-torch|={gnn_check:.2e}")
    assert rf_check < 1e-9 and gnn_check < 1e-4, "numpy inference does not match the trained models"

    # SHAP global importance on a test sample
    t0 = time.perf_counter()
    shap_global: dict[str, Any] = {}
    try:
        import shap
        y_te = s_test["y"]
        idx = np.concatenate([np.where(y_te == 1)[0][:150], np.where(y_te == 0)[0][::max(1, (y_te == 0).sum() // 250)][:250]])
        ex = shap.TreeExplainer(rf)
        sv = np.asarray(ex.shap_values(s_test["X"][idx], check_additivity=False))
        sv1 = sv[:, :, 1] if sv.ndim == 3 else sv
        imp = np.abs(sv1).mean(axis=0)
        shap_global = {"mean_abs_shap": {f: round(float(v), 5) for f, v in sorted(zip(F.FEATURES, imp), key=lambda z: -z[1])},
                       "by_category": {}, "rows": int(len(idx))}
        for f, v in zip(F.FEATURES, imp):
            c = SHAP_CATEGORIES[f]
            shap_global["by_category"][c] = round(shap_global["by_category"].get(c, 0.0) + float(v), 5)
    except Exception as exc:  # pragma: no cover
        shap_global = {"error": f"{type(exc).__name__}: {exc}"}
    timings["shap_s"] = round(time.perf_counter() - t0, 1)

    t0 = time.perf_counter()
    loao_res = ({} if args.no_loao else
                loao(train, val, test, mean, std, {"per_attack": per_attack}, args.quick, loao_epochs, loao_patience))
    timings["loao_s"] = round(time.perf_counter() - t0, 1)
    t0 = time.perf_counter()
    old = old_protocol(worlds, s_test)
    timings["old_protocol_s"] = round(time.perf_counter() - t0, 1)
    timings["total_s"] = round(time.perf_counter() - t_start, 1)

    # ── report ──
    print()
    print(LABEL)
    print(f"{'detector':16s} {'prec':>6s} {'recall':>6s} {'f1':>6s} {'rocauc':>7s} {'prauc':>6s} {'prauc_act':>9s}  confusion")
    for d in DETECTORS + ("consensus_3of6",):
        r = summary[d]
        print(f"{d:16s} {r['precision']:6.3f} {r['recall']:6.3f} {r['f1']:6.3f} {r['roc_auc'] or 0:7.3f} {r['pr_auc'] or 0:6.3f} "
              f"{r['pr_auc_active_accounts'] or 0:9.3f}  {r['confusion']}")
    print("per-attack recall:", {d: {f: v["recall"] for f, v in per_attack[d].items()} for d in ("rules", "random_forest", "gnn")})
    print("old protocol:", {k: (v["f1"], v["pr_auc"]) for k, v in old.items() if isinstance(v, dict)})
    print("timings:", timings)
    if args.quick:
        return

    # ── artefacts ──
    MODELS.mkdir(exist_ok=True)
    trained_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    split = (f"split-by-world: {N_TRAIN} train / {N_VAL} validation / {N_TEST} test worlds (disjoint, seed {SEED}); "
             "leave-one-attack-family-out on test worlds")
    dataset = {
        "worlds": len(worlds), "seed": SEED, "generator": GENERATOR,
        "accounts": {"train": int(len(cat(train, "y"))), "val": int(len(y_v)), "test": int(len(s_test["y"]))},
        "mules": {"train": int(cat(train, "y").sum()), "val": int(y_v.sum()), "test": int(s_test["y"].sum())},
        "attack_instances": {f: sum(1 for w in worlds for a in w.attacks if a["family"] == f) for f in datagen.FAMILIES},
        "evaluation_offset_hours": "attack start drawn uniformly 0.25-72 h before the evaluation time",
    }
    import joblib
    joblib.dump(rf, MODELS / "rf_v2.joblib", compress=3)
    np.savez_compressed(MODELS / "rf_v2.npz", **arr, check_X=Xc[:50], check_p=rf.predict_proba(Xc[:50])[:, 1])
    W_save = {k: v for k, v in W.items()}
    xc0 = (test[0]["gnn_raw"] - mean) / std
    np.savez_compressed(MODELS / "gnn_v2.npz", **W_save, mean=mean, std=std, check_x=xc0,
                        check_pairs=np.array(test[0]["pairs"], dtype=np.int64).reshape(-1, 2),
                        check_out=np.concatenate([np.zeros(test[0]["n_ext"]), torch_out]))
    D.set_params(None)
    (MODELS / "drift_v2.json").write_text(json.dumps(drift_p, indent=2), encoding="utf-8")
    (MODELS / "pattern_memory_v2.json").write_text(json.dumps(mem, indent=2), encoding="utf-8")

    common = {"trained_at": trained_at, "seed": SEED, "data": "SYNTHETIC", "split": split, "label": LABEL,
              "features": list(F.FEATURES), "dataset": dataset}
    rf_meta = {**common, "model_id": "rf-v2", "family": "random_forest", "version": f"rf-{VERSION}",
               "params": {k: v for k, v in RF_PARAMS.items() if k != "n_jobs"},
               "class_weight_reason": "Mules are ~3-5% of accounts per world; balanced_subsample keeps rare positives "
                                      "influential in each bootstrap; the resulting skewed scores are then calibrated.",
               "calibration_map": {"x": [round(float(v), 6) for v in cal.X_thresholds_], "y": [round(float(v), 6) for v in cal.y_thresholds_]},
               "calibration_method": "isotonic regression fitted on validation worlds (calibrated on synthetic worlds)",
               "threshold": thr["random_forest"], "threshold_rule": "max F1 on validation worlds (calibrated scale)",
               "metrics": summary["random_forest"], "per_attack": per_attack["random_forest"],
               "calibration": {"calibrated": calib["random_forest_calibrated"], "raw": calib["random_forest_raw"]},
               "loao": {f: v["random_forest"] for f, v in loao_res.items()}, "shap_global": shap_global,
               "artefacts": {"rf_v2.joblib": sha(MODELS / "rf_v2.joblib"), "rf_v2.npz": sha(MODELS / "rf_v2.npz")},
               "port_check_max_abs_diff": rf_check}
    gnn_meta = {**common, "model_id": "gnn-gat-v2", "family": "gnn", "version": f"gnn-gat-{VERSION}",
                "architecture": "2-layer relational GAT (sender->recipient and recipient->sender attention, 4 heads, hidden 32), "
                                "plain torch for training, numpy for serving; 72 h window graph",
                "params": GNN_PARAMS, "training": gnn_info, "threshold": thr["gnn"],
                "threshold_rule": "max F1 on validation worlds", "metrics": summary["gnn"], "per_attack": per_attack["gnn"],
                "calibration_map": {"x": [round(float(v), 6) for v in cal_g.X_thresholds_], "y": [round(float(v), 6) for v in cal_g.y_thresholds_]},
                "calibration_method": "isotonic regression fitted on validation worlds (calibrated on synthetic worlds)",
                "calibration": {"calibrated": calib["gnn_calibrated"], "raw": calib["gnn_raw"]},
                "loao": {f: v.get("gnn") for f, v in loao_res.items()},
                "artefacts": {"gnn_v2.npz": sha(MODELS / "gnn_v2.npz")}, "port_check_max_abs_diff": gnn_check}
    rules_meta = {**common, "model_id": "rules-v2", "family": "rules", "version": R.RULES_VERSION,
                  "rules": R.describe(), "flag_points": R.FLAG_POINTS, "metrics": summary["rules"], "per_attack": per_attack["rules"],
                  "early_warning": {"version": EW.EW_VERSION, "metrics": summary["early_warning"], "per_attack": per_attack["early_warning"]}}
    drift_meta = {**common, "model_id": "drift-v2", "family": "drift", "version": drift_p["version"], "params": drift_p,
                  "metrics": summary["drift"], "per_attack": per_attack["drift"]}
    pm_meta = {**common, "model_id": "pattern-memory-v2", "family": "pattern_memory", "version": mem["version"],
               "threshold": thr["pattern_memory"], "metrics": summary["pattern_memory"], "per_attack": per_attack["pattern_memory"]}
    for name, meta in (("rf_v2", rf_meta), ("gnn_v2", gnn_meta), ("rules_v2", rules_meta), ("drift_meta_v2", drift_meta),
                       ("pattern_memory_meta_v2", pm_meta)):
        (MODELS / f"{name}.json").write_text(json.dumps(meta, indent=2, default=float), encoding="utf-8")
    loao_cfg = ({"status": "not run (--no-loao)"} if args.no_loao else
                {"status": "run", "random_forest": "same RF_PARAMS as the main model",
                 "gnn": f"max {loao_epochs} epochs, early-stopping patience {loao_patience} (main GNN: "
                        f"{GNN_PARAMS['max_epochs']} / {GNN_PARAMS['patience']})"})
    report = {"label": LABEL, "trained_at": trained_at, "seed": SEED, "split": split, "dataset": dataset,
              "command": command, "version": VERSION, "thresholds": thr, "summary": summary, "calibration": calib,
              "roles": roles_eval, "loao_config": loao_cfg, "loao": loao_res,
              "old_protocol": old, "timings": timings, "gnn_training": gnn_info}
    (MODELS / "validation_v2.json").write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    log(f"artefacts written to {MODELS}  (total {timings['total_s']}s)")


if __name__ == "__main__":
    main()
