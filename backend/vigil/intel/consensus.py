"""Detector results, detector consensus, and the payment-path hook `corroboration()`.

`corroboration(account_id)` is called synchronously by engine/decide.py::_model_evidence for every
payment decision (wrapped in try/except; first 8 results kept). Contract:
  * < 20 ms once warm (`warm()` at app start; after new postings an INCREMENTAL snapshot refresh is used);
  * never raises; unknown / empty / external accounts -> [];
  * never imports shap / scikit-learn / torch (numpy only, and only if installed);
  * returns CORROBORATING evidence only. Nothing here changes the payment tier.

Consensus semantics (DetectorConsensus; consensus-v2.1):
  families_evaluated = results with status "ok"; families_flagging = of those, flagged (a plain count).
  agreement: none (0 flagging) · weak (1) · moderate (2-3) · strong (>= 4), with one cap:
  agreement above "weak" needs at least one MULE-EVIDENCE family (structural / model: random_forest, gnn,
  pattern_memory, ringwatch; or the external registry listing the account as reported / confirmed mule).
  Change and heuristic families (drift, early_warning, rules) and payment-journey families (trailscore,
  context) can corroborate mule evidence but cannot create agreement on their own: a salary arriving and
  rent leaving in the same 72 h trips drift + early warning on any salaried customer, and rules + early
  warning both fire on busy merchants (see docs/ML_VALIDATION_REPORT.md §7.2 for the test-world numbers).
  The families share inputs (the model families all read the same windowed features), so agreement is
  corroboration between different METHODS, not between statistically independent sources.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from vigil.contracts import DetectorConsensus, DetectorResult

log = logging.getLogger("vigil.intel")

LABELS = {
    "rules": "Rule engine",
    "random_forest": "Random Forest",
    "gnn": "GNN (GAT)",
    "drift": "Behavioural drift",
    "early_warning": "Early warning",
    "pattern_memory": "Pattern memory",
    "ringwatch": "RingWatch (network rules)",
    "external": "External registry (SIMULATED)",
    "trailscore": "TrailScore (journey)",
    "context": "ContextFlag (SIMULATED context)",
}
SHORT = {"rules": "rules", "random_forest": "RF", "gnn": "GNN", "drift": "drift", "early_warning": "early warning",
         "pattern_memory": "pattern memory", "ringwatch": "RingWatch", "external": "registry",
         "trailscore": "TrailScore", "context": "context"}
CORROBORATION_ORDER = ("random_forest", "gnn", "rules", "early_warning", "drift", "pattern_memory")
RINGWATCH_FLAG = 0.4            # the score at which the scenarios' "RingWatch scan" lists an account
SYNTHETIC_CAVEAT = "SYNTHETIC VALIDATION — trained and calibrated on computer-generated worlds; not real-bank accuracy."
CONSENSUS_VERSION = "consensus-v2.1"

# Families whose flag is evidence of mule STRUCTURE or mule IDENTITY. Validated on test worlds for RF, GNN and
# pattern memory (ML_VALIDATION_REPORT §7); RingWatch (the payment engine's network rules) and the SIMULATED
# registry exist only in the live world. Rules are deliberately NOT in this set: on test worlds rules + early
# warning flag 197 of 331 merchants, so counting rules as structural evidence restores those false agreements.
MULE_EVIDENCE_FAMILIES = frozenset({"random_forest", "gnn", "pattern_memory", "ringwatch", "external"})
CHANGE_FAMILIES = frozenset({"drift", "early_warning"})          # change vs own history / population anomaly
JOURNEY_FAMILIES = frozenset({"trailscore", "context"})          # one recent payment journey of a sender
# Families that describe the ACCOUNT (roles are assessed from these). TrailScore / ContextFlag describe one
# payment journey of a recent sender, not the account's position in a money flow.
ACCOUNT_FAMILIES = CORROBORATION_ORDER + ("ringwatch", "external")


# ── consensus ─────────────────────────────────────────────────────────────
def agreement_level(flagging: int, mule_evidence: bool = True) -> str:
    """none (0) · weak (1) · moderate (2-3) · strong (>= 4); capped at weak without mule evidence."""
    if flagging <= 0:
        return "none"
    if flagging == 1 or not mule_evidence:
        return "weak"
    if flagging <= 3:
        return "moderate"
    return "strong"


def agreement(flagged_families: Iterable[str]) -> str:
    """Agreement level for a set of flagging families (pure; shared by the API and ml/ evaluation)."""
    fams = set(flagged_families)
    return agreement_level(len(fams), bool(fams & MULE_EVIDENCE_FAMILIES))


def _names(fams: Iterable[str]) -> str:
    return ", ".join(SHORT.get(f, f) for f in fams)


def summarise(results: Iterable[DetectorResult]) -> DetectorConsensus:
    ok = [r for r in results if r.status == "ok"]
    flagging = [r for r in ok if r.flagged]
    n, m = len(flagging), len(ok)
    evidence = any(r.family in MULE_EVIDENCE_FAMILIES for r in flagging)
    if m == 0:
        summary = "No detector family could evaluate this account"
    elif n == 0:
        summary = f"No signal family flags this account ({m} evaluated)"
    elif n == 1:
        summary = f"1 of {m} signal families flags this account ({SHORT[flagging[0].family]}) — uncorroborated"
    elif not evidence:
        kinds = [k for k, fams in (("behaviour-change", CHANGE_FAMILIES), ("rule-heuristic", {"rules"}),
                                   ("payment-journey", JOURNEY_FAMILIES)) if any(r.family in fams for r in flagging)]
        what = ((", ".join(kinds[:-1]) + " and " + kinds[-1]) if len(kinds) > 1 else (kinds or ["non-structural"])[0]) \
            + " signals only"
        summary = (f"{n} of {m} signal families flag this account ({_names(r.family for r in flagging)}) — {what}, "
                   "no structural or model family agrees, so agreement stays weak")
    else:
        summary = f"{n} of {m} signal families agree ({_names(r.family for r in flagging)})"
    return DetectorConsensus(families_flagging=n, families_evaluated=m, agreement=agreement_level(n, evidence),
                             summary=summary)


# ── result builders ───────────────────────────────────────────────────────
def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(float(x), nd)


def _unavailable(family: str, kind: str, version: str, observed_at: str, reason: str) -> DetectorResult:
    return DetectorResult(family=family, label=LABELS[family], value=None, display="unavailable", kind=kind,
                          flagged=False, status="unavailable", version=version, observed_at=observed_at,
                          detail={"reason": reason})


def intel_results(snap: Any, account_id: str) -> list[DetectorResult]:
    """The six model/heuristic families for one account of a live Snapshot (vigil/intel/live.py)."""
    from vigil.intel import drift as D
    from vigil.intel import early_warning as EW
    from vigil.intel import live
    from vigil.intel import pattern_memory as PM
    from vigil.intel import rules as R
    from vigil.intel.models import STORE

    at = snap.as_of
    thr = live.thresholds()
    base = {"graph_version": snap.key[0], "evaluation": snap.mode, "window": "last 72 h"}
    out: dict[str, DetectorResult] = {}

    # Random Forest / GNN — calibrated (isotonic, validation worlds) probabilities
    for fam, store_map, meta in (("random_forest", snap.rf, STORE.rf_meta), ("gnn", snap.gnn, STORE.gnn_meta)):
        version = str(meta.get("version", "unavailable"))
        if snap.status.get(fam) != "ok" or account_id not in store_map:
            out[fam] = _unavailable(fam, "probability_calibrated", version, at,
                                    snap.errors.get(fam) or STORE.errors.get(fam) or "model artefacts or numpy not available")
            continue
        raw, cal = store_map[account_id]
        out[fam] = DetectorResult(
            family=fam, label=LABELS[fam], value=_r(cal), display=f"{cal:.2f}", kind="probability_calibrated",
            flagged=bool(cal >= thr[fam]), version=version, observed_at=at,
            detail={**base, "raw_score": _r(raw), "raw_kind": "probability_uncalibrated", "threshold": thr[fam],
                    "threshold_rule": meta.get("threshold_rule", "max F1 on validation worlds"),
                    "calibration": "isotonic regression fitted on validation worlds — calibrated on synthetic worlds, "
                                   "not a real-world probability",
                    "validation": SYNTHETIC_CAVEAT,
                    **({"scope": "whole 72 h window graph, 2-layer attention (2-hop receptive field)"} if fam == "gnn" else {})})

    rr = snap.rules[account_id]
    out["rules"] = DetectorResult(
        family="rules", label=LABELS["rules"], value=_r(rr["score"]), display=f"{rr['points']}/{rr['max_points']} pts",
        kind="score", flagged=bool(rr["flagged"]), version=R.RULES_VERSION, observed_at=at,
        detail={**base, "points": rr["points"], "flag_points": R.FLAG_POINTS, "fired": rr["fired"]})

    ew = snap.ew[account_id]
    out["early_warning"] = DetectorResult(
        family="early_warning", label=LABELS["early_warning"], value=_r(ew["score"]),
        display=(f"{ew['score']:.2f} · {len(ew['signals'])} signal{'s' if len(ew['signals']) != 1 else ''}"),
        kind="score", flagged=bool(ew["flagged"]), version=EW.EW_VERSION, observed_at=at,
        detail={**base, "signals": ew["signals"], "min_signals": EW.MIN_SIGNALS,
                "population_cutoff": _r(snap.ew_stats.get("cutoff_score")), "population": int(snap.ew_stats.get("n", 0)),
                "note": "Anomaly score relative to the current account population, not a probability."})

    dr = snap.drift[account_id]
    params = D.params()
    out["drift"] = DetectorResult(
        family="drift", label=LABELS["drift"], value=_r(dr["drift_score"]), display=dr["level"], kind="level",
        flagged=bool(dr["flagged"]), version=str(params.get("version", "drift")), observed_at=at,
        detail={**base, "drift_score": _r(dr["drift_score"]), "breadth": dr.get("breadth"),
                "baseline_blocks": dr["baseline_blocks"],
                "top_changes": [{k: f[k] for k in ("feature", "baseline", "current", "change")} for f in dr["features"][:3]],
                "levels": {"MEDIUM": params.get("medium"), "HIGH": params.get("high")}})

    pats = snap.patterns.get(account_id) or []
    mem = PM.memory() or {}
    if pats:
        top = pats[0]
        out["pattern_memory"] = DetectorResult(
            family="pattern_memory", label=LABELS["pattern_memory"], value=_r(top["similarity"]),
            display=f"{top['similarity']:.0%} similar · {top['name']}", kind="similarity",
            flagged=bool(top["similarity"] >= thr["pattern_memory"]), version=str(mem.get("version", "pattern-memory")),
            observed_at=at, detail={**base, "signature_id": top["signature_id"], "name": top["name"],
                                    "threshold": thr["pattern_memory"], "note": PM.NOTE})
    else:
        out["pattern_memory"] = _unavailable("pattern_memory", "similarity", str(mem.get("version", "pattern-memory")), at,
                                             "pattern memory artefact not available")
    return [out[f] for f in CORROBORATION_ORDER]


def ringwatch_result(account_id: str, observed_at: str) -> DetectorResult:
    from vigil.risk import ringwatch
    from vigil.settings import get_policy_version
    version = f"ringwatch · {get_policy_version()}"
    try:
        signals, feats = ringwatch.evaluate(account_id)
        score = ringwatch.score(signals)
        return DetectorResult(
            family="ringwatch", label=LABELS["ringwatch"], value=_r(score), display=f"{score:.2f}", kind="score",
            flagged=score >= RINGWATCH_FLAG, version=version, observed_at=observed_at,
            detail={"rules": [s.rule_id for s in signals], "labels": [s.label for s in signals], "threshold": RINGWATCH_FLAG,
                    "role": feats.get("role"), "note": "Transparent policy rules (the payment engine's network dimension)."})
    except Exception as exc:  # pragma: no cover - defensive
        return _unavailable("ringwatch", "score", version, observed_at, f"{type(exc).__name__}: {exc}")


def external_result(account_id: str, observed_at: str) -> DetectorResult:
    from vigil.risk import external_intel
    try:
        prov = external_intel.provider()
        intel = prov.lookup(account_id)
    except Exception as exc:  # pragma: no cover - defensive
        return _unavailable("external", "score", "registry", observed_at, f"{type(exc).__name__}: {exc}")
    if intel is None:
        return DetectorResult(family="external", label=LABELS["external"], value=None, display="not listed", kind="score",
                              flagged=False, version=prov.name, observed_at=observed_at,
                              detail={"simulated": True, "status": None})
    return DetectorResult(
        family="external", label=LABELS["external"], value=_r(intel.risk_score),
        display=intel.status.replace("_", " ").upper(), kind="score",
        flagged=intel.status in {"reported", "confirmed_mule"}, version=prov.name, observed_at=intel.last_updated,
        detail={"simulated": True, "status": intel.status, "reason_codes": intel.reason_codes, "source": intel.source})


def sender_results(account_id: str, max_age_h: float = 72.0) -> list[DetectorResult]:
    """TrailScore / ContextFlag, only when the account recently SENT a payment Vigil evaluated.

    Read from the recorded decision (no re-evaluation): these dimensions describe a payment journey, not
    an account, so they exist only for recent payers.
    """
    from vigil import clock, db
    from vigil.contracts import RiskDecision
    from vigil.settings import get_policy
    row = db.q1("SELECT record, created_at FROM risk_decisions WHERE sender_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (account_id,))
    if not row or clock.minutes_between(row["created_at"], clock.now_iso()) > max_age_h * 60:
        return []
    d = RiskDecision.model_validate_json(row["record"])
    thr = float(get_policy()["fusion"]["corroboration"]["dimension_threshold"])
    out = []
    for fam, dim in (("trailscore", "sequence"), ("context", "context")):
        ds = next((x for x in d.dimensions if x.dimension == dim), None)
        if ds is None:
            continue
        out.append(DetectorResult(
            family=fam, label=LABELS[fam], value=_r(ds.score), display=f"{ds.score:.2f}", kind="score",
            flagged=ds.score >= thr, version=d.policy_version, observed_at=d.created_at,
            detail={"decision_id": d.decision_id, "dimension": dim, "threshold": thr,
                    "signals": [s.rule_id for s in ds.signals],
                    **({"simulated": True} if fam == "context" else {}),
                    "note": "From the account's most recent payment decision as sender (last 72 h)."}))
    return out


# ── payment-path hook ─────────────────────────────────────────────────────
def corroboration(account_id: str) -> list[DetectorResult]:
    """Corroborating model evidence for engine/decide.py. Never raises; never changes the tier."""
    try:
        from vigil.intel import live
        if not isinstance(account_id, str) or not account_id or account_id.startswith("ext:"):
            return []
        if not live.known(account_id) or live.SRC.is_external(account_id):
            return []
        snap = live.CACHE.current(allow_full=False)
        if snap is None:                       # cold cache (warm() not called / after a reset): one full build
            snap = live.CACHE.current(allow_full=True)
        if snap is None or account_id not in snap.feats:
            return []
        return intel_results(snap, account_id)
    except Exception as exc:
        log.warning("intel corroboration failed for %s: %s", account_id, exc)
        return []


_shap_warm_started = False


def _warm_shap() -> None:
    try:
        from vigil.intel.models import STORE
        STORE.explainer()          # imports scikit-learn + shap (~3 s cold); no database access
    except Exception:
        pass


def warm(shap_in_background: bool = True) -> None:
    """Load artefacts and build the live snapshot once (app start). Safe to call twice; never raises.

    The SHAP explainer (scikit-learn + shap imports, seconds when cold) is prepared on a short-lived
    daemon thread that touches no database, so neither startup nor the payment path waits for it.
    """
    global _shap_warm_started
    try:
        from vigil.intel import drift, live, pattern_memory
        from vigil.intel.models import STORE
        STORE.load()
        drift.params()
        pattern_memory.memory()
        live.thresholds()
        live.CACHE.current(allow_full=True)
    except Exception as exc:
        log.warning("intel warm-up failed: %s", exc)
    if shap_in_background and not _shap_warm_started:
        try:
            import threading
            _shap_warm_started = True
            threading.Thread(target=_warm_shap, name="intel-shap-warmup", daemon=True).start()
        except Exception:
            pass
