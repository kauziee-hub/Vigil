"""Read models behind /api/intel/* (AccountIntel, IntelScores, IntelOverview, ScenarioCompare).

Shapes follow vigil/contracts.py and frontend/src/api/types.ts field for field. Everything is computed
from the cached live snapshot (vigil/intel/live.py); SHAP is computed lazily per account and cached.
Ground truth (`accounts.seed_role`, `transactions.seed_attack`) is read ONLY by `scenario_compare`, to
describe how each involved account took part in the scenario — never by any detector.
"""

from __future__ import annotations

from typing import Any

from vigil import db
from vigil.contracts import (
    AccountIntel, DetectorResult, DriftFeature, DriftReport, PatternMatch, RoleAssessment, ShapContribution,
    ShapExplanation,
)
from vigil.intel import consensus as C
from vigil.intel import features as F
from vigil.intel import live
from vigil.intel.models import SHAP_CATEGORIES, STORE

DRIFT_LABEL = {"current": "last 72 h", "baseline": "45 days before the current window (fifteen 72 h blocks)"}
_shap_cache: dict[tuple[Any, str], ShapExplanation | None] = {}


# ── helpers ───────────────────────────────────────────────────────────────
def _not_applicable(observed_at: str, reason: str) -> list[DetectorResult]:
    kinds = {"random_forest": "probability_calibrated", "gnn": "probability_calibrated", "rules": "score",
             "early_warning": "score", "drift": "level", "pattern_memory": "similarity"}
    return [DetectorResult(family=f, label=C.LABELS[f], value=None, display="n/a", kind=kinds[f], flagged=False,
                           status="not_applicable", version="-", observed_at=observed_at, detail={"reason": reason})
            for f in C.CORROBORATION_ORDER]


def detectors_for(snap: live.Snapshot, account_id: str, include_sender: bool = True) -> list[DetectorResult]:
    """All families for one account: six intel families + RingWatch + external registry
    (+ TrailScore / ContextFlag when the account recently sent a payment)."""
    out = C.intel_results(snap, account_id)
    out.append(C.ringwatch_result(account_id, snap.as_of))
    out.append(C.external_result(account_id, snap.as_of))
    if include_sender:
        try:
            out.extend(C.sender_results(account_id))
        except Exception:
            pass
    return out


def shap_explanation(snap: live.Snapshot, account_id: str) -> ShapExplanation | None:
    """TreeSHAP over the RF (raw predict_proba scale). None if shap / scikit-learn are unavailable."""
    key = (snap.key, snap.now_t, account_id)
    if key in _shap_cache:
        return _shap_cache[key]
    f = snap.feats[account_id]
    row = F.vector(f)
    try:
        import numpy as np
        row = [float(v) for v in np.asarray(row, dtype=np.float32)]       # same precision the forest sees
    except Exception:
        pass
    res = STORE.shap_values(row)
    if res is None:
        _shap_cache[key] = None
        return None
    base, contrib = res
    rows = [ShapContribution(feature=k, value=round(float(f[k]), 4), contribution=round(c, 6),
                             category=SHAP_CATEGORIES.get(k, "Other")) for k, c in zip(F.FEATURES, contrib)]
    categories: dict[str, float] = {}
    for r in rows:
        categories[r.category] = round(categories.get(r.category, 0.0) + abs(r.contribution), 6)
    raw = snap.rf.get(account_id, (base + sum(contrib), None))[0]
    exp = ShapExplanation(
        model_version=str(STORE.rf_meta.get("version", "rf")), base_value=round(base, 6), prediction=round(raw, 6),
        prediction_kind="probability_uncalibrated",
        top_positive=sorted([r for r in rows if r.contribution > 0], key=lambda r: -r.contribution)[:5],
        top_negative=sorted([r for r in rows if r.contribution < 0], key=lambda r: r.contribution)[:5],
        categories=dict(sorted(categories.items(), key=lambda kv: -kv[1])))
    if len(_shap_cache) > 512:
        _shap_cache.clear()
    _shap_cache[key] = exp
    return exp


def drift_report(snap: live.Snapshot, account_id: str) -> DriftReport:
    d = snap.drift[account_id]
    feats = [DriftFeature(feature=r["feature"], baseline=r["baseline"], current=r["current"], change=r["change"])
             for r in d["features"]]
    return DriftReport(baseline_window=f"{DRIFT_LABEL['baseline']}; {d['baseline_blocks']} block(s) with history",
                       current_window=DRIFT_LABEL["current"], drift_score=d["drift_score"], level=d["level"],
                       features=feats)


def patterns(snap: live.Snapshot, account_id: str) -> list[PatternMatch]:
    return [PatternMatch(signature_id=m["signature_id"], name=m["name"], similarity=m["similarity"],
                         description=m["description"], note=m["note"]) for m in snap.patterns.get(account_id, [])]


# ── read models ───────────────────────────────────────────────────────────
def account_intel(account_id: str) -> AccountIntel:
    snap = live.CACHE.current(allow_full=True)
    if snap is None or account_id not in snap.feats:
        at = snap.as_of if snap else ""
        reason = "External counterparty outside the bank's perimeter: no account behaviour to score."
        dets = _not_applicable(at, reason)
        if account_id.startswith("ext:") or live.SRC.is_external(account_id):
            dets.append(C.external_result(account_id, at))
        return AccountIntel(account_id=account_id, as_of=at, graph_version=snap.key[0] if snap else 0, detectors=dets,
                            consensus=C.summarise(dets), shap=None, drift=None,
                            role=RoleAssessment(role="unclassified", reason=reason), patterns=[], features={})
    dets = detectors_for(snap, account_id)
    role = live.role(snap, account_id)
    return AccountIntel(
        account_id=account_id, as_of=snap.as_of, graph_version=snap.key[0], detectors=dets,
        consensus=C.summarise(dets), shap=shap_explanation(snap, account_id), drift=drift_report(snap, account_id),
        role=RoleAssessment(role=role["role"], reason=role["reason"], evidence=role["evidence"]),
        patterns=patterns(snap, account_id),
        features={k: round(float(v), 4) for k, v in snap.feats[account_id].items()})


def scores() -> dict[str, Any]:
    """IntelScores for every scored account (a superset of the default scene and its neighbours)."""
    snap = live.CACHE.current(allow_full=True)
    cached = snap.views.get("scores")
    if cached is not None:
        return cached
    out: dict[str, Any] = {}
    network = live.role_network(snap)             # roles only inside corroborated mule structure (roles.gate)
    for a in snap.ids:
        rf = snap.rf.get(a)
        g = snap.gnn.get(a)
        out[a] = {
            "rules": round(snap.rules[a]["score"], 4),
            "rf": round(rf[1], 4) if rf else None,
            "gnn": round(g[1], 4) if g else None,
            "drift_level": snap.drift[a]["level"],
            "role": live.role(snap, a)["role"] if a in network else None,
            "early_warning": bool(snap.ew[a]["flagged"]),
        }
    result = {"graph_version": snap.key[0], "scores": out}
    snap.views["scores"] = result
    return result


def overview() -> dict[str, Any]:
    from vigil.intel.registry import models
    from vigil.risk import ringwatch
    snap = live.CACHE.current(allow_full=True)
    agreement = {f: sum(1 for a in snap.ids if snap.flags[a].get(f)) for f in C.CORROBORATION_ORDER}
    try:
        agreement["ringwatch"] = len(ringwatch.scan(min_score=C.RINGWATCH_FLAG))
    except Exception:
        pass
    try:
        listed = db.q("SELECT identifier FROM external_intel WHERE status IN ('reported', 'confirmed_mule')")
        agreement["external"] = sum(1 for r in listed if live.known(r["identifier"]))
    except Exception:
        pass
    ew = sorted(((a, snap.ew[a]) for a in snap.ids if snap.ew[a]["flagged"]), key=lambda x: (-x[1]["score"], x[0]))
    thr = live.thresholds()["pattern_memory"]
    pats = sorted(((a, snap.patterns[a][0]) for a in snap.ids if snap.patterns.get(a)
                   and snap.patterns[a][0]["similarity"] >= thr), key=lambda x: (-x[1]["similarity"], x[0]))
    roles: dict[str, int] = {r: 0 for r in ("coordinator", "collector", "distributor", "entry", "exit", "unclassified")}
    for a in sorted(live.role_network(snap)):
        r = live.role(snap, a)["role"]
        roles[r] = roles.get(r, 0) + 1
    return {
        "graph_version": snap.key[0],
        "detector_agreement": agreement,
        "early_warnings": [{"account_id": a, "score": round(e["score"], 4), "signals": e["signals"]} for a, e in ew[:25]],
        "pattern_alerts": [{"account_id": a, "match": PatternMatch(
            signature_id=m["signature_id"], name=m["name"], similarity=m["similarity"], description=m["description"],
            note=m["note"]).model_dump()} for a, m in pats[:25]],
        "role_counts": roles,
        "models": [m.model_dump() for m in models()],
    }


def _involvement(scenario_id: str, account_id: str, db_role: str | None, tag: str) -> str | None:
    """seed_role for ScenarioCompare: the seeded ground-truth role, plus how the account took part in the
    scenario's own (tagged) postings — 'involved' is not the same as 'mule'."""
    rows = db.q("SELECT sender_id, recipient_id FROM transactions WHERE seed_attack = ? AND source = 'scenario' "
                "AND (sender_id = ? OR recipient_id = ?)", (tag, account_id, account_id))
    sent = any(r["sender_id"] == account_id for r in rows)
    recv = any(r["recipient_id"] == account_id for r in rows)
    how = ("moved scenario funds in and out" if sent and recv else "sent scenario funds" if sent
           else "received scenario funds" if recv else None)
    if db_role and how:
        return f"{db_role} · {how}"
    return db_role or how


def scenario_compare(scenario_id: str) -> dict[str, Any]:
    from vigil.sim import scenarios
    accounts = scenarios.touched_accounts(scenario_id)          # 404 (VigilError) for unknown scenarios
    sc = scenarios.SCENARIOS.get(scenario_id)
    tag = (sc.tag if sc and sc.tag else scenario_id)
    snap = live.CACHE.current(allow_full=True)
    rows = []
    for a in accounts:
        acc = db.q1("SELECT seed_role FROM accounts WHERE id = ?", (a,))
        seed_role = _involvement(scenario_id, a, acc["seed_role"] if acc else None, tag) if acc else None
        if snap is not None and a in snap.feats:
            dets = detectors_for(snap, a, include_sender=False)
        else:
            dets = []                                             # account does not exist yet (scenario not run)
        rows.append({"account_id": a, "seed_role": seed_role, "detectors": [d.model_dump() for d in dets],
                     "consensus": C.summarise(dets).model_dump()})
    return {"scenario_id": scenario_id, "accounts": rows}
