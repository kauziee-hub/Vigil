"""Signal map (v12.4): every signal working inside the eight detector families, and the supporting signals outside them.

The eight canonical families stay exactly as they are (rules, RingWatch, RF, GNN, drift, early warning, pattern
memory, registry). This module only makes their INSIDE visible: which checks each family runs, how many accounts
trip each check right now, and — for one focused account — which checks fire for it and why. It also lists the
supporting signals that are not families (the payment-time evidence the PRIMA decision uses, and location
intelligence) and says where each of them feeds.

Validation is labelled honestly, per family, from the model registry (backend/models):
    benchmarked   measured on held-out synthetic test worlds (precision / recall / PR-AUC exist)
    live_graded   exists only in the live world (no test-world counterpart); checked by graded attack runs
    lookup        a (simulated) external lookup; nothing to benchmark
    supporting    a sub-signal or supporting layer; NOT benchmarked on its own — no metric is shown for it
No metric is ever invented for a sub-signal. Read-only: nothing here changes a status, a tier or a score.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from vigil import clock, db

log = logging.getLogger("vigil.intel.signals")

# ── static catalogue (what each signal checks, in plain words) ────────────
RINGWATCH_RULES = [
    ("NET_FAN_IN", "Many first-time senders", "≥ 4 first-time senders in 72 h"),
    ("NET_FAN_OUT", "Splits money out", "≥ 4 first-time recipients in 72 h"),
    ("NET_PASS_THROUGH", "Rapid pass-through", "≥ 70% of ≥ ₹20,000 received sent on within 60 min"),
    ("NET_CIRCULAR", "Circular flow", "money returns to its origin through ≤ 4 hops"),
    ("NET_SMURFING", "Many small transfers", "≥ 4 transfers of ₹8,000–9,999"),
    ("NET_VELOCITY_CHAIN", "Part of a fast chain", "≥ 2 hops, each forwarded within 30 min"),
    ("NET_SHARED_DEVICE", "Shared device", "its device is bound to ≥ 3 accounts"),
    ("NET_DORMANT_WAKE", "Dormant account woke up", "quiet ≥ 30 days, then active"),
    ("NET_NEW_ACCOUNT_INFLOW", "New account, large inflow", "≤ 14 days old with ≥ ₹50,000 inflow"),
    ("NET_LABELLED_ACCOUNT", "Received a confirmed scam payment", "a bank-confirmed scam paid into it"),
    ("NET_LABELLED_NEIGHBOUR", "Money from a confirmed scam account", "one hop downstream of a labelled account"),
    ("NET_LABELLED_NEIGHBOUR_2HOP", "Two hops downstream of a scam account", "two hops downstream of a labelled account"),
    ("NET_TAINT_EXPOSURE", "Holds money traced to a scam", "≥ ₹1,000 attributable by TaintTrace (LIBR)"),
]
EW_SIGNALS = [
    ("New Account", "New account", "younger than the population's 30th percentile (capped at 180 days) and active"),
    ("Shared Device", "Shared device", "device bound to ≥ 3 accounts"),
    ("Pass-Through", "Pass-through", "most of ≥ ₹5,000 received sent on within the window"),
    ("High Velocity", "High velocity", "busier than the population AND ≥ 2× its own 30-day rate + 2"),
    ("High Fan-Out", "High fan-out", "≥ 3 (estimated) first-time recipients"),
    ("Multi-Channel", "Multi-channel", "≥ 3 payment rails in the window"),
]
REGISTRY_STATUSES = [
    ("watchlist", "Watchlist", "listed on a (simulated) telecom / risk watchlist"),
    ("reported", "Reported", "customers have reported payments to it"),
    ("confirmed_mule", "Confirmed mule", "confirmed as a mule by the (simulated) registry"),
]
PAYMENT_RULES = {
    "external": [("EXT_WATCHLIST", "Registry: watchlist"), ("EXT_REPORTED", "Registry: reported"),
                 ("EXT_CONFIRMED_MULE", "Registry: confirmed mule")],
    "sequence": [("SEQ_LOGIN_NEW_DEVICE", "Login from a new device"), ("SEQ_CREDENTIAL_CHANGED", "Credentials changed"),
                 ("SEQ_PAYEE_ADDED", "Payee added"), ("SEQ_LIMIT_RAISED", "Transfer limit raised"),
                 ("SEQ_SCREEN_SHARE_ACTIVE", "Screen sharing active"), ("SEQ_ORDERED_CHAIN", "Device → payee → limit, in order"),
                 ("SEQ_LARGE_AFTER_CHANGES", "Large transfer right after the changes")],
    "behaviour": [("BEH_AMOUNT_OUTLIER", "Unusually large for this sender"), ("BEH_FIRST_TIME_PAYEE", "First payment to this recipient"),
                  ("BEH_BALANCE_DRAIN", "Drains ≥ 80% of the balance"), ("BEH_NEW_PAYEE_BURST", "Several new payees in 24 h"),
                  ("BEH_VELOCITY", "≥ 5 payments in 60 min"), ("BEH_DORMANT_SENDER", "Sender quiet ≥ 45 days"),
                  ("BEH_ODD_HOUR", "Between 00:00 and 05:00 IST")],
    "context": [("CTX_URGENCY", "Urgency"), ("CTX_SECRECY", "Secrecy"), ("CTX_FEAR_AUTHORITY", "Fear / authority"),
                ("CTX_GREED", "Greed"), ("CTX_BYPASS_APPROVAL", "Bypass approval")],
}
PAYMENT_DIM_LABEL = {"external": "External intelligence (simulated registry)", "sequence": "TrailScore — the sender's last 30 minutes",
                     "behaviour": "Behaviour — this payment vs the sender's history",
                     "context": "ContextFlag — the (simulated) call / message", "network": "Network — RingWatch rules on the recipient"}
LOCATION_RULES = [
    ("LOC_IMPOSSIBLE_TRAVEL", "Impossible travel", "two precise points ≥ 50 km apart (after accuracy) faster than 900 km/h"),
    ("LOC_UNUSUAL_REGION", "Unusual region", "a city outside the account's usual places, ≥ 150 km from home and every usual point"),
    ("LOC_MULTI_CITY_BURST", "Multi-city burst", "≥ 3 cities, each ≥ 100 km apart, within 60 min"),
    ("CASH_OUT_CLUSTER", "Coordinated cash-out", "≥ 3 risky ATM withdrawals within 8 km and 45 min"),
]

FAMILY_META: dict[str, dict[str, Any]] = {
    "rules": {"label": "Rule engine", "kind": "heuristic",
              "purpose": "Six simple 72-hour checks with points; 4 of 12 points flags.",
              "role": "One family among eight. A busy shop trips it, so it never sets a status on its own.",
              "feeds": ["Live status (with another family)", "Detection · every account"]},
    "ringwatch": {"label": "RingWatch (network rules)", "kind": "network",
                  "purpose": "The transparent money-flow rules the payment engine itself uses.",
                  "role": "Mule-structure evidence; with 2+ families it can flag an account (structural route).",
                  "feeds": ["Payment tier (network dimension)", "Live status (structural route)", "Ring alerts", "Roles"]},
    "random_forest": {"label": "Random Forest", "kind": "model",
                      "purpose": "A learned mule probability from 15 windowed account features (calibrated).",
                      "role": "Model evidence; needs another family and onward money flow to flag. Never sets a payment tier.",
                      "feeds": ["Live status (model route)", "Decision record (evidence only)", "SHAP on Detection"]},
    "gnn": {"label": "Graph neural network", "kind": "model",
            "purpose": "A learned mule probability from the same features plus the account's payment neighbourhood.",
            "role": "Model evidence; needs another family and onward money flow to flag. Never sets a payment tier.",
            "feeds": ["Live status (model route)", "Decision record (evidence only)"]},
    "drift": {"label": "Behavioural drift", "kind": "change",
              "purpose": "This account's last 72 hours against its own previous 45 days, feature by feature.",
              "role": "Change evidence only (a salary week drifts too); corroborates, never alone.",
              "feeds": ["Live status (with another family)", "Close monitoring", "Account page"]},
    "early_warning": {"label": "Early warning", "kind": "change",
                      "purpose": "Six behaviour signals relative to the whole population; needs ≥ 2 signals and the top 8%.",
                      "role": "On its own it gives early warning, never flagged.",
                      "feeds": ["Live status (early warning)", "Close monitoring", "Mule pipeline"]},
    "pattern_memory": {"label": "Pattern memory", "kind": "memory",
                       "purpose": "How closely the account's money-flow shape matches ten stored mule signatures.",
                       "role": "Mule-structure evidence ('looks like', never attribution).",
                       "feeds": ["Live status (with another family)", "Detection · known patterns"]},
    "external": {"label": "External registry (simulated)", "kind": "registry",
                 "purpose": "What the (simulated) payment-safety registry says about the account.",
                 "role": "Direct external evidence; reported / confirmed counts as mule evidence.",
                 "feeds": ["Payment tier (external dimension)", "Live status (mule evidence)"]},
}
FAMILY_ORDER = ("ringwatch", "random_forest", "gnn", "rules", "drift", "early_warning", "pattern_memory", "external")
VALIDATION_TEXT = {
    "live_graded": "Exists only in the live world (the test worlds have no payment engine), so it has no held-out benchmark. "
                   "It is checked by every graded attack run (Detection · section 2) and the payment test suite.",
    "lookup": "A (simulated) external lookup, not a detector model: nothing to benchmark.",
    "supporting": "Supporting signals, not benchmarked on their own: no precision or ROC-AUC is claimed for them. "
                  "They are unit-tested and visible in every decision or status reason they change.",
}


def _validation(family: str, models: dict[str, Any]) -> dict[str, Any]:
    def head(m: dict[str, Any]) -> str:
        parts = [f"{k} {m[k]:.2f}" for k in ("pr_auc", "recall", "precision") if isinstance(m.get(k), (int, float))]
        return " · ".join(p.replace("pr_auc", "PR-AUC") for p in parts)
    if family == "ringwatch":
        return {"kind": "live_graded", "text": VALIDATION_TEXT["live_graded"]}
    if family == "external":
        return {"kind": "lookup", "text": VALIDATION_TEXT["lookup"]}
    m = models.get(family)
    if family == "early_warning":
        rules = models.get("rules") or {}
        m = rules.get("early_warning") if isinstance(rules.get("early_warning"), dict) else None
    if m and head(m):
        return {"kind": "benchmarked", "headline": head(m),
                "text": "Measured on held-out synthetic test worlds the detector never saw (SYNTHETIC VALIDATION, not real-bank accuracy)."
                        + (" Its numbers are stored with the rule engine's record." if family == "early_warning" else "")}
    return {"kind": "supporting", "text": VALIDATION_TEXT["supporting"]}


def _models() -> dict[str, Any]:
    try:
        from vigil.intel.registry import models
        return {m.family: dict(m.metrics or {}) for m in models()}
    except Exception:
        return {}


def _num(v: float, feature: str) -> str:
    if "amount" in feature:
        return f"₹{v:,.0f}"
    if feature == "retention_ratio":
        return f"{v:.0%}"
    return f"{v:,.1f}".rstrip("0").rstrip(".")


def _sig(sid: str, label: str, checks: str, firing: int, hit: bool | None = None, why: str | None = None,
         **extra: Any) -> dict[str, Any]:
    return {"id": sid, "label": label, "checks": checks, "firing": int(firing), "hit": hit, "why": why, **extra}


# ── the read model ────────────────────────────────────────────────────────
def signal_map(account: str | None = None, window_s: int = 3600) -> dict[str, Any]:
    from vigil.intel import live, pattern_memory, rules as rules_mod, stream
    from vigil.intel.drift import LABELS as DRIFT_LABELS
    from vigil.intel.features import DRIFT_FEATURES
    from vigil.risk import ringwatch

    snap = live.CACHE.current(allow_full=True)
    ids = list(snap.ids) if snap else []
    acct = account if (account and snap and account in snap.feats) else None
    thr = live.thresholds()
    live_thr = stream.current_threshold()
    models = _models()
    fams: dict[str, dict[str, Any]] = {}

    # rule engine
    fired_by: dict[str, int] = {}
    for a in ids:
        for f in snap.rules[a]["fired"]:
            fired_by[f["rule_id"]] = fired_by.get(f["rule_id"], 0) + 1
    a_rules = {f["rule_id"]: f["reason"] for f in snap.rules[acct]["fired"]} if acct else {}
    fams["rules"] = {"signals": [
        _sig(r["rule_id"], r["label"], f"{r['points']} point{'s' if r['points'] > 1 else ''} · {r['old_threshold'].split(' (')[0]} → now windowed",
             fired_by.get(r["rule_id"], 0), (r["rule_id"] in a_rules) if acct else None, a_rules.get(r["rule_id"]))
        for r in rules_mod.describe()],
        "flagged_now": sum(1 for a in ids if snap.flags[a].get("rules")),
        "account_flagged": bool(snap.flags[acct].get("rules")) if acct else None,
        "account_value": f"{snap.rules[acct]['points']} of {snap.rules[acct]['max_points']} points" if acct else None}
    # fix the rule-engine "checks" text from the live reason templates (thresholds are the windowed ones)
    _RULE_CHECKS = {"R_FAN_IN": "≥ 4 distinct senders in 72 h", "R_FAN_OUT": "≥ 4 distinct recipients in 72 h",
                    "R_LOW_RETENTION": "keeps < 20% of ≥ ₹10,000 received", "R_SHARED_DEVICE": "device bound to ≥ 3 accounts",
                    "R_CHANNEL_DIVERSITY": "≥ 3 payment rails in 72 h", "R_VELOCITY": "≥ 8 postings in 72 h"}
    for s in fams["rules"]["signals"]:
        pts = next(r["points"] for r in rules_mod.describe() if r["rule_id"] == s["id"])
        s["checks"] = f"{_RULE_CHECKS.get(s['id'], s['checks'])} · {pts} point{'s' if pts > 1 else ''}"

    # RingWatch
    rw_rows = ringwatch.scan(min_score=0.0)
    rw_by: dict[str, int] = {}
    for r in rw_rows:
        for rid in set(r["rules"]):
            rw_by[rid] = rw_by.get(rid, 0) + 1
    a_rw: dict[str, str] = {}
    a_rw_score = None
    if acct:
        try:
            sigs, _f = ringwatch.evaluate(acct)
            a_rw = {x.rule_id: x.reason for x in sigs}
            a_rw_score = ringwatch.score(sigs)
        except Exception:
            pass
    from vigil.intel.consensus import RINGWATCH_FLAG
    fams["ringwatch"] = {"signals": [_sig(rid, lab, chk, rw_by.get(rid, 0), (rid in a_rw) if acct else None, a_rw.get(rid))
                                     for rid, lab, chk in RINGWATCH_RULES],
                         "flagged_now": sum(1 for r in rw_rows if r["score"] >= RINGWATCH_FLAG),
                         "account_flagged": (a_rw_score or 0) >= RINGWATCH_FLAG if acct else None,
                         "account_value": f"score {a_rw_score:.2f} (flags at {RINGWATCH_FLAG:.2f})" if acct and a_rw_score is not None else None}

    # the two models: one learned score each (their 15 inputs are not separate signals)
    for fam, store in (("random_forest", snap.rf), ("gnn", snap.gnn)):
        t = float(thr.get(fam, 0.5))
        v = store.get(acct) if acct else None
        n_live = sum(1 for a in ids if (store.get(a) or (0, 0))[1] >= live_thr)
        fams[fam] = {"signals": [
            _sig(f"{fam}_prob", "Mule probability (calibrated)", f"≥ {t:.2f} = family flag · ≥ {live_thr:.2f} = live model route",
                 sum(1 for a in ids if snap.flags[a].get(fam)), (v[1] >= t) if v else (False if acct else None),
                 f"{v[1]:.2f}" if v else None, live_route=n_live)],
            "flagged_now": sum(1 for a in ids if snap.flags[a].get(fam)),
            "account_flagged": bool(snap.flags[acct].get(fam)) if acct else None,
            "account_value": f"{v[1]:.2f}" if v else None,
            "inputs": "15 windowed features: senders, recipients, ₹ in / out, retention, forwarding speed, rails, device sharing, "
                      "account age, dormancy, near-threshold amounts …" + (" plus the payment neighbourhood (graph attention)" if fam == "gnn" else "")}

    # drift: which aspects moved (counted among accounts whose drift is HIGH)
    high = [a for a in ids if snap.drift[a]["level"] == "HIGH"]
    moved: dict[str, int] = {f: 0 for f in DRIFT_FEATURES}
    for a in high:
        for row in snap.drift[a]["features"]:
            if row["change"] >= 1.0:
                moved[row["feature"]] += 1
    a_drift = {r["feature"]: r for r in snap.drift[acct]["features"]} if acct else {}
    fams["drift"] = {"signals": [
        _sig(f"DRIFT_{f.upper()}", DRIFT_LABELS.get(f, f).capitalize(), "changed by ≥ 1 scale unit vs its own 45-day baseline",
             moved[f], (a_drift[f]["change"] >= 1.0) if acct else None,
             (f"{_num(a_drift[f]['baseline'], f)} → {_num(a_drift[f]['current'], f)} (change {a_drift[f]['change']:.1f})" if acct else None))
        for f in DRIFT_FEATURES],
        "flagged_now": len(high),
        "account_flagged": bool(snap.flags[acct].get("drift")) if acct else None,
        "account_value": f"{snap.drift[acct]['level']} ({snap.drift[acct]['drift_score']:.2f})" if acct else None,
        "note": "HIGH needs a large overall change AND at least 2 aspects moving together; counts are among HIGH-drift accounts."}

    # early warning
    ew_by: dict[str, int] = {}
    for a in ids:
        for s in snap.ew[a]["signals"]:
            ew_by[s] = ew_by.get(s, 0) + 1
    a_ew = set(snap.ew[acct]["signals"]) if acct else set()
    fams["early_warning"] = {"signals": [_sig(f"EW_{k.upper().replace(' ', '_').replace('-', '_')}", lab, chk, ew_by.get(k, 0),
                                              (k in a_ew) if acct else None, None) for k, lab, chk in EW_SIGNALS],
                             "flagged_now": sum(1 for a in ids if snap.ew[a]["flagged"]),
                             "account_flagged": bool(snap.ew[acct]["flagged"]) if acct else None,
                             "account_value": f"score {snap.ew[acct]['score']:.2f}" if acct else None,
                             "note": "A signal is recorded only when an account shows at least two of them."}

    # pattern memory
    mem = pattern_memory.memory() or {}
    pthr = float(thr.get("pattern_memory", 0.6))
    pm_by: dict[str, int] = {}
    for a in ids:
        m = (snap.patterns.get(a) or [None])[0]
        if m and m["similarity"] >= pthr:
            pm_by[m["signature_id"]] = pm_by.get(m["signature_id"], 0) + 1
    a_pm = {m["signature_id"]: m["similarity"] for m in (snap.patterns.get(acct) or [])} if acct else {}
    fams["pattern_memory"] = {"signals": [
        _sig(p["signature_id"], p["name"], f"shape similarity ≥ {pthr:.0%}", pm_by.get(p["signature_id"], 0),
             (a_pm.get(p["signature_id"], 0) >= pthr) if acct else None,
             f"{a_pm[p['signature_id']]:.0%} similar" if acct and p["signature_id"] in a_pm else None)
        for p in mem.get("prototypes", [])],
        "flagged_now": sum(1 for a in ids if snap.flags[a].get("pattern_memory")),
        "account_flagged": bool(snap.flags[acct].get("pattern_memory")) if acct else None,
        "account_value": (f"{snap.patterns[acct][0]['name']} {snap.patterns[acct][0]['similarity']:.0%}"
                          if acct and snap.patterns.get(acct) else None)}

    # registry (simulated)
    known = set(ids)
    reg = db.q("SELECT identifier, status, source FROM external_intel")
    reg_by: dict[str, int] = {}
    a_reg = None
    for r in reg:
        if r["identifier"] in known:
            reg_by[r["status"]] = reg_by.get(r["status"], 0) + 1
        if acct and r["identifier"] == acct:
            a_reg = r
    fams["external"] = {"signals": [_sig(f"EXT_{s.upper()}", lab, chk, reg_by.get(s, 0),
                                         (a_reg is not None and a_reg["status"] == s) if acct else None,
                                         (a_reg["source"] if a_reg is not None and a_reg["status"] == s else None))
                                    for s, lab, chk in REGISTRY_STATUSES],
                        "flagged_now": reg_by.get("reported", 0) + reg_by.get("confirmed_mule", 0),
                        "account_flagged": (a_reg is not None and a_reg["status"] in ("reported", "confirmed_mule")) if acct else None,
                        "account_value": (a_reg["status"].replace("_", " ") if a_reg is not None else "not listed") if acct else None}

    families = []
    for fid in FAMILY_ORDER:
        f = fams[fid]
        sigs = f["signals"]
        families.append({"id": fid, **FAMILY_META[fid], **{k: v for k, v in f.items() if k != "signals"},
                         "validation": _validation(fid, models), "signals": sigs,
                         "signal_count": len(sigs), "firing_signals": sum(1 for s in sigs if s["firing"] > 0)})

    supporting = [_payment_evidence(window_s, acct), _location(acct)]
    fam_signals = sum(f["signal_count"] for f in families)
    sup_signals = sum(len(s["signals"]) for s in supporting)
    firing = sum(f["firing_signals"] for f in families) + sum(s["firing_signals"] for s in supporting)
    multi = sum(1 for a in ids if sum(1 for v in snap.flags[a].values() if v) >= 2)
    out: dict[str, Any] = {
        "as_of": snap.as_of if snap else clock.now_iso(), "synthetic": True,
        "totals": {"families": len(families), "family_signals": fam_signals, "supporting_signals": sup_signals,
                   "firing_now": firing, "accounts_scored": len(ids), "accounts_two_plus_families": multi},
        "families": families, "supporting": supporting,
        "validation_legend": [
            {"kind": "benchmarked", "label": "Benchmarked on held-out worlds",
             "text": "Precision, recall and PR-AUC measured on synthetic test worlds the detector never saw (Detection · section 4)."},
            {"kind": "live_graded", "label": "Live-world only", "text": VALIDATION_TEXT["live_graded"]},
            {"kind": "lookup", "label": "Lookup", "text": VALIDATION_TEXT["lookup"]},
            {"kind": "supporting", "label": "Supporting signal", "text": VALIDATION_TEXT["supporting"]},
        ],
        "top_accounts": _top_accounts(snap, ids),
    }
    if acct:
        st = stream.status_map().get(acct, {})
        nm = db.q1("SELECT display_name FROM accounts WHERE id = ?", (acct,))
        out["account"] = {"id": acct, "name": nm["display_name"] if nm else acct, "status": st.get("status"),
                          "families_flagging": st.get("families_flagging"), "reason": st.get("reason"),
                          "location": st.get("location")}
    elif account:
        out["account"] = {"id": account, "name": account, "status": None, "families_flagging": 0,
                          "reason": "Not a scored customer account (external, or unknown).", "location": None}
    return out


def _top_accounts(snap: Any, ids: list[str]) -> list[dict[str, Any]]:
    """Accounts with the most detector families flagging right now — quick picks for 'Focus an account'."""
    rows = sorted(((a, sum(1 for v in snap.flags[a].values() if v)) for a in ids), key=lambda x: (-x[1], x[0]))
    rows = [r for r in rows if r[1] >= 2][:8]
    names = {r["id"]: r["display_name"] for r in db.q("SELECT id, display_name FROM accounts")} if rows else {}
    return [{"id": a, "name": names.get(a, a), "families": n} for a, n in rows]


def _payment_evidence(window_s: int, acct: str | None) -> dict[str, Any]:
    """The PRIMA payment decision's own evidence (five dimensions): counted over decisions in the window."""
    from vigil.contracts import RiskDecision
    since = clock.iso(clock.now() - timedelta(seconds=window_s))
    rows = db.q("SELECT record FROM risk_decisions WHERE created_at >= ?", (since,))
    by: dict[str, int] = {}
    for r in rows:
        try:
            for rid in set(RiskDecision.model_validate_json(r["record"]).rules_fired):
                by[rid] = by.get(rid, 0) + 1
        except Exception:
            continue
    a_hits: dict[str, str] = {}
    a_dec = None
    if acct:
        row = db.q1("SELECT id, record FROM risk_decisions WHERE sender_id = ? OR recipient_id = ? ORDER BY created_at DESC LIMIT 1",
                    (acct, acct))
        if row:
            try:
                d = RiskDecision.model_validate_json(row["record"])
                a_dec = {"decision_id": d.decision_id, "tier": d.tier, "score": d.final_score,
                         "as": "sender" if d.sender_id == acct else "recipient"}
                for dim in d.dimensions:
                    for s in dim.signals:
                        a_hits[s.rule_id] = s.reason
            except Exception:
                pass
    signals = []
    for dim, items in PAYMENT_RULES.items():
        for rid, lab in items:
            signals.append(_sig(rid, lab, PAYMENT_DIM_LABEL[dim], by.get(rid, 0), (rid in a_hits) if acct else None,
                                a_hits.get(rid), group=dim))
    return {"id": "payment", "label": "Payment-time evidence (PRIMA decision)", "kind": "payment",
            "purpose": "Scored on every payment before money moves: five weighted dimensions. The network dimension reuses the "
                       "RingWatch rules on the recipient (listed under RingWatch, not repeated here).",
            "role": "Sets the payment tier (with floors and caps). It never changes an account's live status.",
            "feeds": ["Payment tier", "Customer screen", "Decision record and replay"],
            "validation": {"kind": "supporting", "text": "Policy rules, hand-set and versioned (config/risk_policy.yaml): checked by "
                                                         "the payment test suite and the demo test book, not benchmarked as a detector."},
            "signals": signals, "signal_count": len(signals), "firing_signals": sum(1 for s in signals if s["firing"] > 0),
            "window": f"decisions in the last {window_s // 60} min ({len(rows)})", "account_decision": a_dec}


def _location(acct: str | None) -> dict[str, Any]:
    """Location intelligence: supporting signals, never a family; where each one contributes."""
    from vigil import overview
    from vigil.geo import intel as geo_intel
    ev = geo_intel.evidence_map()
    by: dict[str, int] = {}
    for a, e in ev.items():
        for rid in {r["rule"] for r in e["rules"] if r["confidence"] == "high"}:
            by[rid] = by.get(rid, 0) + 1
    since = clock.iso(clock.now() - timedelta(hours=2))
    try:
        clusters = overview.cash_out_clusters(since)
    except Exception:
        clusters = []
    by["CASH_OUT_CLUSTER"] = sum(len(c["accounts"]) for c in clusters)
    a_hits: dict[str, str] = {}
    if acct:
        for r in (ev.get(acct) or {}).get("rules", []):
            if r["confidence"] == "high":
                a_hits.setdefault(r["rule"], r["reason"])
        for c in clusters:
            if acct in c["accounts"]:
                a_hits["CASH_OUT_CLUSTER"] = f"{len(c['accounts'])} risky accounts · {c.get('atm_count')} ATMs in {c['city']}"
    feeds_by = {"LOC_IMPOSSIBLE_TRAVEL": "Live status (corroboration) · Possible-account-takeover alert · Money Map",
                "LOC_UNUSUAL_REGION": "Live status (corroboration) · Money Map",
                "LOC_MULTI_CITY_BURST": "Live status (corroboration) · Money Map",
                "CASH_OUT_CLUSTER": "Cash-out alert · Money Map"}
    signals = [_sig(rid, lab, chk, by.get(rid, 0), (rid in a_hits) if acct else None, a_hits.get(rid), feeds=feeds_by[rid])
               for rid, lab, chk in LOCATION_RULES]
    changed = 0
    try:
        from vigil.intel import stream
        changed = sum(1 for v in stream.status_map().values() if (v.get("location") or {}).get("changed_status"))
    except Exception:
        pass
    return {"id": "location", "label": "Location intelligence", "kind": "location",
            "purpose": "Impossible travel, unusual geography and coordinated cash-out from the stored location of each posting "
                       "(only precise points: device GPS, ATM, branch).",
            "role": "Not a family. A high-confidence location rule can stand in for a missing second voice in the live status "
                    "— never on its own, never a payment tier.",
            "feeds": ["Live status (corroboration only)", "Account-takeover and cash-out alerts", "Money Map"],
            "validation": {"kind": "supporting", "text": VALIDATION_TEXT["supporting"]},
            "signals": signals, "signal_count": len(signals), "firing_signals": sum(1 for s in signals if s["firing"] > 0),
            "changed_status_now": changed}
