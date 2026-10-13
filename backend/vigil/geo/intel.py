"""Location intelligence (v12): impossible travel, coordinated cash-out and location-behaviour anomalies.

Inputs are the SIMULATED locations already stored on every posting (`transactions.geo_*`: city, point, basis,
accuracy). Nothing here reads ground truth (`seed_role`, `seed_attack`), changes a payment tier or touches
config/risk_policy.yaml. Thresholds: config/location_policy.yaml (+ the reused copilot_policy signals).

Which points count (location quality)
    precise  device_gps (±30 m), atm_terminal (±25 m), branch (±100 m)   → may give high-confidence evidence
    coarse   ip (±3–15 km)                                                → accuracy subtracted, LOW confidence only
    never    merchant_pos (the merchant's city; a card payment can be card-not-present)
             kyc_home (an address, not a presence)
Every distance used in a rule is the *effective* distance: haversine minus both points' accuracy radii, so a
±15 km IP estimate can never look like a 20 km move, and GPS jitter (tens of metres) is far below every minimum.

Rules (per sender account; a rule never compares sender with recipient — fraudsters need not be near each other)
    LOC_IMPOSSIBLE_TRAVEL   consecutive presence points: effective km ≥ min_km and km / hours > impossible_travel_kmh
    LOC_UNUSUAL_REGION      a recent point in a city absent from the account's baseline geography, ≥ unusual_region_min_km
                            (effective) from home and from every baseline point; needs ≥ min_baseline_points history
    LOC_MULTI_CITY_BURST    ≥ multi_city_min_cities precise points in distinct cities, each ≥ multi_city_min_km apart,
                            within multi_city_window_min

The result per account is a location EVIDENCE record (rules fired, threshold vs observed, basis/accuracy, reason,
a capped evidence score). It is corroborating only: vigil/intel/stream.py lets a high-confidence record add a
voice to detector families that already flag an account, never create a status on its own.

Incremental: postings are read by `seq` (primary key) after the last one seen, so the per-posting cost is a few
rows; the baseline of an account is read once (indexed by sender) and cached until the next reset.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import yaml

from datetime import datetime, timezone

from vigil import clock, db, geo
from vigil.settings import REPO_ROOT

log = logging.getLogger("vigil.geo.intel")
POLICY_PATH = REPO_ROOT / "config" / "location_policy.yaml"
RULE_LABEL = {"LOC_IMPOSSIBLE_TRAVEL": "Impossible travel", "LOC_UNUSUAL_REGION": "Unusual region",
              "LOC_MULTI_CITY_BURST": "Multi-city burst"}


@lru_cache(maxsize=1)
def policy() -> dict[str, Any]:
    return yaml.safe_load(POLICY_PATH.read_bytes())


def _copilot_signals() -> dict[str, Any]:
    from vigil import overview
    return overview.policy()["signals"]


def precise_bases() -> set[str]:
    return set(policy()["presence"]["precise"])


def coarse_bases() -> set[str]:
    return set(policy()["presence"]["coarse"])


def presence_bases() -> tuple[str, ...]:
    return tuple(sorted(precise_bases() | coarse_bases()))


def _acc_km(p: dict[str, Any]) -> float:
    return float(p.get("acc_m") or geo.ACCURACY_M.get(p.get("basis") or "", 5000)) / 1000.0


def effective_km(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, float]:
    """(raw haversine km, effective km = raw − both accuracy radii, never below 0)."""
    raw = geo.haversine_km((a["lat"], a["lng"]), (b["lat"], b["lng"]))
    return raw, max(0.0, raw - _acc_km(a) - _acc_km(b))


def _point(r: dict[str, Any]) -> dict[str, Any]:
    return {"tx_id": r["id"], "seq": r["seq"], "ts": r["ts"], "t": clock.parse(r["ts"]).timestamp(),
            "account": r["sender_id"], "city": r["geo_city"], "lat": r["geo_lat"], "lng": r["geo_lng"],
            "basis": r["geo_basis"], "acc_m": r["geo_accuracy_m"], "amount_paise": r["amount_paise"],
            "label": geo.label(r["geo_basis"], r["geo_accuracy_m"])}


def _confidence(*pts: dict[str, Any]) -> str:
    prec = precise_bases()
    return "high" if all(p["basis"] in prec for p in pts) else "low"


def _speed(km: float, a: dict[str, Any], b: dict[str, Any]) -> tuple[float, float]:
    secs = max(float(policy()["impossible_travel"]["min_elapsed_s"]), b["t"] - a["t"])
    hours = secs / 3600.0
    return hours, km / hours


def _speed_text(eff_km: float, hours: float, kmh: float) -> str:
    """Under a minute the exact seconds between two postings say little: state the honest lower bound instead
    (the speed if the move had taken a full minute)."""
    return f"over {round(eff_km * 60):,} km/h" if hours * 60 < 1 else f"{round(kmh):,} km/h"


# ── pure rule functions (unit-testable on plain point dicts) ──────────────
def travel_findings(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Impossible-travel pairs among ONE account's presence points (sorted by time)."""
    cfg = policy()["impossible_travel"]
    kmh_limit = float(_copilot_signals()["impossible_travel_kmh"])
    out = []
    for a, b in zip(points, points[1:]):
        raw, eff = effective_km(a, b)
        if eff < float(cfg["min_km"]):
            continue
        hours, kmh = _speed(eff, a, b)
        if kmh <= kmh_limit:
            continue
        conf = _confidence(a, b)
        out.append({
            "rule": "LOC_IMPOSSIBLE_TRAVEL", "account": b["account"], "confidence": conf,
            "from_city": a["city"], "to_city": b["city"], "km": round(raw), "effective_km": round(eff, 1),
            "minutes": round(hours * 60, 1), "kmh": round(kmh), "threshold_kmh": kmh_limit,
            "tx_ids": [a["tx_id"], b["tx_id"]], "ts": b["ts"],
            "points": [_pub(a), _pub(b)],
            "speed_text": _speed_text(eff, hours, kmh),
            "reason": (f"{a['city']} → {b['city']}: {round(raw):,} km in "
                       f"{'under a minute' if hours * 60 < 1 else f'{hours * 60:.0f} min'} = {_speed_text(eff, hours, kmh)} "
                       f"(limit {kmh_limit:,.0f} km/h; {round(eff):,} km after subtracting both accuracies)"
                       + ("" if conf == "high" else " — low precision (IP-based point): shown, not used as evidence")),
        })
    return out


def multi_city_findings(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cfg = policy()["anomaly"]
    need, min_km, win = int(cfg["multi_city_min_cities"]), float(cfg["multi_city_min_km"]), float(cfg["multi_city_window_min"]) * 60
    prec = [p for p in points if p["basis"] in precise_bases()]
    best: list[dict[str, Any]] = []
    for i, a in enumerate(prec):
        chosen = [a]
        for b in prec[i + 1:]:
            if b["t"] - a["t"] > win:
                break
            if all(b["city"] != c["city"] and effective_km(b, c)[1] >= min_km for c in chosen):
                chosen.append(b)
        if len(chosen) >= need and len(chosen) > len(best):
            best = chosen
    if not best:
        return []
    mins = (best[-1]["t"] - best[0]["t"]) / 60
    cities = [p["city"] for p in best]
    return [{"rule": "LOC_MULTI_CITY_BURST", "account": best[0]["account"], "confidence": "high",
             "cities": cities, "minutes": round(mins, 1), "threshold": f"≥ {need} cities ≥ {min_km:.0f} km apart within "
             f"{cfg['multi_city_window_min']} min", "observed": f"{len(best)} cities in {mins:.0f} min",
             "tx_ids": [p["tx_id"] for p in best], "ts": best[-1]["ts"], "points": [_pub(p) for p in best],
             "reason": f"Activity in {', '.join(cities)} within {mins:.0f} min (each ≥ {min_km:.0f} km apart)"}]


def unusual_region_findings(points: list[dict[str, Any]], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    cfg = policy()["anomaly"]
    if baseline["n"] < int(cfg["min_baseline_points"]):
        return []
    min_km = float(cfg["unusual_region_min_km"])
    home = baseline.get("home")
    out, seen = [], set()
    for p in points:
        if p["city"] in baseline["cities"] or p["city"] in seen:
            continue
        refs = list(baseline["points"]) + ([home] if home else [])
        if not refs:
            continue
        dists = [effective_km(p, r)[1] for r in refs]
        nearest = min(dists)
        if nearest < min_km:
            continue
        seen.add(p["city"])
        home_km = round(effective_km(p, home)[0]) if home else None
        conf = _confidence(p)
        out.append({"rule": "LOC_UNUSUAL_REGION", "account": p["account"], "confidence": conf, "city": p["city"],
                    "home_city": baseline.get("home_city"), "home_km": home_km, "nearest_baseline_km": round(nearest, 1),
                    "threshold": f"city not in the usual geography and ≥ {min_km:.0f} km (after accuracy) from home and "
                                 f"every usual point", "observed": f"{p['city']}: {round(nearest):,} km from the nearest usual point",
                    "baseline_cities": sorted(baseline["cities"]), "baseline_points": baseline["n"],
                    "tx_ids": [p["tx_id"]], "ts": p["ts"], "points": [_pub(p)],
                    "reason": (f"First activity in {p['city']} — usual geography {', '.join(sorted(baseline['cities'])) or '—'} "
                               f"({baseline['n']} points); {round(nearest):,} km from the nearest usual point"
                               + ("" if conf == "high" else " — low precision (IP-based point): shown, not used as evidence"))})
    return out


def _pub(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in ("tx_id", "ts", "city", "lat", "lng", "basis", "acc_m", "label")}


def score(rules: list[dict[str, Any]]) -> float:
    w = policy()["corroboration"]["weights"]
    return round(min(1.0, sum(float(w.get(r["rule"], 0)) for r in {r["rule"]: r for r in rules}.values())), 2)


# ── incremental state ─────────────────────────────────────────────────────
class _State:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.epoch: Any = None
        self.last_seq = 0
        self.recent: dict[str, list[dict[str, Any]]] = {}
        self.baseline: dict[str, dict[str, Any]] = {}
        self.evidence: dict[str, dict[str, Any]] = {}
        self.version = 0
        self.signature: tuple = ()


STATE = _State()


def reset() -> None:
    STATE.reset()


def _from_ts(t: float) -> datetime:
    return datetime.fromtimestamp(t, tz=timezone.utc)


def _epoch() -> Any:
    """Changes on every reseed (the reset restores postings with the same seq numbers, so seq alone is not enough)."""
    return (db.scalar("SELECT value FROM meta WHERE key = 'seeded_at'"), id(db._conn) if hasattr(db, "_conn") else None)


def _baseline(account: str, before_t: float) -> dict[str, Any]:
    hit = STATE.baseline.get(account)
    if hit is not None:
        return hit
    cfg = policy()["anomaly"]
    lo = clock.iso(_from_ts(before_t - float(cfg["baseline_days"]) * 86400))
    hi = clock.iso(_from_ts(before_t))
    marks = ",".join("?" * len(presence_bases()))
    rows = db.q(f"SELECT id, seq, ts, sender_id, amount_paise, geo_city, geo_lat, geo_lng, geo_basis, geo_accuracy_m "
                f"FROM transactions WHERE sender_id = ? AND ts >= ? AND ts < ? AND geo_lat IS NOT NULL "
                f"AND geo_basis IN ({marks}) ORDER BY ts", (account, lo, hi, *presence_bases()))
    pts = [_point(r) for r in rows]
    acc = db.q1("SELECT home_city, home_lat, home_lng FROM accounts WHERE id = ?", (account,))
    home = ({"lat": acc["home_lat"], "lng": acc["home_lng"], "acc_m": policy()["presence"]["home_accuracy_m"],
             "basis": "kyc_home", "city": acc["home_city"]} if acc and acc["home_lat"] is not None else None)
    # keep at most one point per city (the baseline is a set of places, not a time series)
    per_city: dict[str, dict[str, Any]] = {}
    for p in pts:
        per_city.setdefault(p["city"], p)
    out = {"n": len(pts), "cities": set(per_city), "points": list(per_city.values()), "home": home,
           "home_city": acc["home_city"] if acc else None}
    STATE.baseline[account] = out
    return out


def _evaluate(account: str, now_t: float) -> dict[str, Any] | None:
    cfg = policy()["anomaly"]
    win_start = now_t - float(cfg["window_hours"]) * 3600
    pts = [p for p in STATE.recent.get(account, []) if p["t"] >= win_start]
    STATE.recent[account] = pts
    if len(pts) == 0:
        return None
    rules = travel_findings(pts) + multi_city_findings(pts)
    first_t = pts[0]["t"]
    rules += unusual_region_findings(pts, _baseline(account, min(first_t, win_start)))
    if not rules:
        return None
    min_conf = policy()["corroboration"]["min_confidence"]
    used = [r for r in rules if r["confidence"] == "high" or min_conf == "low"]
    return {"account": account, "rules": rules, "corroborating_rules": [r["rule"] for r in used],
            "score": score(used) if used else 0.0, "corroborates": bool(used) and bool(policy()["corroboration"]["enabled"]),
            "last_ts": max(r["ts"] for r in rules)}


def refresh() -> int:
    """Bring the evidence map up to date with every posting since the last call. Returns the evidence version."""
    try:
        ep = _epoch()
        now_t = clock.now().timestamp()
        cfg = policy()["anomaly"]
        win_start = now_t - float(cfg["window_hours"]) * 3600
        marks = ",".join("?" * len(presence_bases()))
        cols = ("id, seq, ts, sender_id, amount_paise, geo_city, geo_lat, geo_lng, geo_basis, geo_accuracy_m")
        if ep != STATE.epoch:
            STATE.reset()
            STATE.epoch = ep
            rows = db.q(f"SELECT {cols} FROM transactions WHERE ts >= ? AND geo_lat IS NOT NULL AND geo_basis IN ({marks}) "
                        f"AND sender_id NOT LIKE 'ext:%' ORDER BY seq", (clock.iso(_from_ts(win_start)), *presence_bases()))
            STATE.last_seq = int(db.scalar("SELECT COALESCE(MAX(seq), 0) FROM transactions") or 0)
        else:
            rows = db.q(f"SELECT {cols} FROM transactions WHERE seq > ? AND geo_lat IS NOT NULL AND geo_basis IN ({marks}) "
                        f"AND sender_id NOT LIKE 'ext:%' ORDER BY seq", (STATE.last_seq, *presence_bases()))
            top = db.scalar("SELECT COALESCE(MAX(seq), 0) FROM transactions")
            STATE.last_seq = max(STATE.last_seq, int(top or 0))
        touched = set()
        for r in rows:
            p = _point(r)
            if p["t"] < win_start:
                continue
            lst = STATE.recent.setdefault(p["account"], [])
            lst.append(p)
            lst.sort(key=lambda x: x["t"])
            touched.add(p["account"])
        for a in touched | set(STATE.evidence):
            ev = _evaluate(a, now_t)
            if ev:
                STATE.evidence[a] = ev
            else:
                STATE.evidence.pop(a, None)
        sig = tuple(sorted((a, tuple(sorted({r["rule"] + ":" + r["confidence"] for r in e["rules"]})), e["last_ts"])
                           for a, e in STATE.evidence.items()))
        if sig != STATE.signature:
            first = not STATE.signature and STATE.version == 0
            STATE.signature = sig
            STATE.version += 1
            if not first or sig:
                _publish(STATE.version)
        return STATE.version
    except Exception as exc:   # location context must never break a posting or a status
        log.warning("location intelligence refresh failed: %s", exc)
        return STATE.version


def evidence_map() -> dict[str, dict[str, Any]]:
    refresh()
    return dict(STATE.evidence)


def corroborating(account: str) -> dict[str, Any] | None:
    """The account's location evidence when it may corroborate a detector status, else None."""
    ev = STATE.evidence.get(account)
    return ev if ev and ev["corroborates"] else None


def explain(ev: dict[str, Any]) -> str:
    """One line for a status reason / incident fact: which rule, observed vs threshold, basis and accuracy."""
    used = [r for r in ev["rules"] if r["rule"] in ev["corroborating_rules"]]
    if not used:
        return ""
    r = used[0]
    basis = ", ".join(sorted({f"{p['label'].replace('Simulated location · ', '')}" for p in r["points"]}))
    return f"location corroborates: {RULE_LABEL[r['rule']]} — {r['reason']} [{basis}]"


# ── signals over a time window (map, incidents, API) ─────────────────────
def _window_points(since_iso: str, bases: tuple[str, ...] | None = None) -> dict[str, list[dict[str, Any]]]:
    b = bases or presence_bases()
    marks = ",".join("?" * len(b))
    rows = db.q(f"SELECT id, seq, ts, sender_id, amount_paise, geo_city, geo_lat, geo_lng, geo_basis, geo_accuracy_m "
                f"FROM transactions WHERE ts >= ? AND geo_lat IS NOT NULL AND geo_basis IN ({marks}) "
                f"AND sender_id NOT LIKE 'ext:%' ORDER BY sender_id, ts", (since_iso, *b))
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r["sender_id"], []).append(_point(r))
    return out


def impossible_travel(since_iso: str, include_low: bool = False) -> list[dict[str, Any]]:
    out = []
    for pts in _window_points(since_iso).values():
        out += [f for f in travel_findings(pts) if include_low or f["confidence"] == "high"]
    return sorted(out, key=lambda f: f["ts"], reverse=True)


def account_geography(account: str, since_iso: str | None = None) -> dict[str, Any]:
    """Where an account normally is, where it was recently (chronological), and any location rule that fired."""
    refresh()
    now_t = clock.now().timestamp()
    cfg = policy()["anomaly"]
    since = since_iso or clock.iso(_from_ts(now_t - float(cfg["window_hours"]) * 3600))
    pts = _window_points(since).get(account, [])
    base = _baseline(account, clock.parse(since).timestamp())
    ev = STATE.evidence.get(account)
    return {"account": account, "home_city": base.get("home_city"),
            "home": {"lat": base["home"]["lat"], "lng": base["home"]["lng"]} if base.get("home") else None,
            "usual_cities": sorted(base["cities"]), "baseline_points": base["n"],
            "has_baseline": base["n"] >= int(cfg["min_baseline_points"]),
            "route": [_pub(p) for p in pts[-12:]], "evidence": ev,
            "verdict": ("suspicious" if ev and ev["corroborates"] else "unconfirmed" if ev else "normal")}


# ── Money Map insight (GET /api/geo/intel) ────────────────────────────────
def _publish(version: int) -> None:
    try:
        from vigil.realtime import HUB
        ev = STATE.evidence
        HUB.publish("console", "geo.location_intel", {
            "version": version, "accounts": len(ev), "corroborating": sum(1 for e in ev.values() if e["corroborates"]),
            "rules": sorted({r["rule"] for e in ev.values() for r in e["rules"]}), "ts": clock.now_iso()})
    except Exception:
        pass


def summary(window_s: int = 3600, account: str | None = None, city: str | None = None,
            cluster: str | None = None) -> dict[str, Any]:
    """Everything the Money Map's location-intelligence panel shows, from stored postings (no frontend values)."""
    from vigil import overview
    refresh()
    now_t = clock.now().timestamp()
    since = clock.iso(_from_ts(now_t - max(window_s, 3600)))
    nm = overview.names()
    sts = overview.statuses()
    per_acct = _window_points(since)
    travel_all = []
    for pts in per_acct.values():
        travel_all += travel_findings(pts)
    travel = sorted([t for t in travel_all if t["confidence"] == "high"], key=lambda t: t["ts"], reverse=True)
    low = sorted([t for t in travel_all if t["confidence"] != "high"], key=lambda t: t["ts"], reverse=True)
    clusters = overview.cash_out_clusters(since)
    for c in clusters:
        c["account_names"] = [nm.get(a, a) for a in c["accounts"]]
    anomalies = []
    for a, e in sorted(STATE.evidence.items(), key=lambda kv: (-kv[1]["score"], kv[0])):
        st = sts.get(a, {})
        anomalies.append({"account": a, "name": nm.get(a, a), "status": st.get("status", "normal"),
                          "score": e["score"], "corroborates": e["corroborates"],
                          "rules": [{k: v for k, v in r.items() if k != "points"} | {"points": r["points"]} for r in e["rules"]],
                          "contributed": bool((st.get("location") or {}).get("changed_status"))})
    for t in travel + low:
        t["name"] = nm.get(t["account"], t["account"])
        t["status"] = sts.get(t["account"], {}).get("status", "normal")
    # the "normal geography" picture: what was checked and found ordinary
    n_pts = sum(len(v) for v in per_acct.values())
    prec = sum(1 for v in per_acct.values() for p in v if p["basis"] in precise_bases())
    flagged_accts = {t["account"] for t in travel_all} | set(STATE.evidence)
    moves, fastest = 0, 0.0
    for a, pts in per_acct.items():
        if a in flagged_accts:
            continue
        for x, y in zip(pts, pts[1:]):
            moves += 1
            raw, eff = effective_km(x, y)
            if eff >= float(policy()["impossible_travel"]["min_km"]):
                fastest = max(fastest, _speed(eff, x, y)[1])
    normal = {"located_postings": n_pts, "precise_postings": prec, "coarse_postings": n_pts - prec,
              "accounts": len(per_acct), "cities": len({p["city"] for v in per_acct.values() for p in v}),
              "moves_checked": moves, "fastest_normal_kmh": round(fastest) if fastest else None,
              "accounts_with_signals": len(flagged_accts)}
    out: dict[str, Any] = {
        "generated_ts": clock.now_iso(), "since": since, "policy_version": policy()["version"], "synthetic": True,
        "thresholds": {"impossible_travel_kmh": float(_copilot_signals()["impossible_travel_kmh"]),
                       "min_km": float(policy()["impossible_travel"]["min_km"]),
                       "unusual_region_min_km": float(policy()["anomaly"]["unusual_region_min_km"]),
                       "multi_city": f"≥ {policy()['anomaly']['multi_city_min_cities']} cities ≥ {policy()['anomaly']['multi_city_min_km']} km apart in {policy()['anomaly']['multi_city_window_min']} min",
                       "cash_out": {k: _copilot_signals()[k] for k in ("cash_out_min_withdrawals", "cash_out_radius_km", "cash_out_window_min")}},
        "impossible_travel": travel[:12], "low_confidence": low[:12], "cash_out": clusters, "anomalies": anomalies[:20],
        "normal": normal, "corroboration_enabled": bool(policy()["corroboration"]["enabled"]),
    }
    if account:
        g = account_geography(account)
        g["name"] = nm.get(account, account)
        g["status"] = sts.get(account, {}).get("status", "normal")
        g["travel"] = [t for t in travel_all if t["account"] == account]
        out["selected"] = {"kind": "account", **g}
    elif city:
        out["selected"] = {"kind": "city", **_city_context(city, per_acct, travel_all, clusters, sts, nm, since)}
    elif cluster:
        c = next((c for c in clusters if c["id"] == cluster), None)
        if c:
            out["selected"] = {"kind": "cluster", **c}
    return out


def _city_context(city: str, per_acct: dict[str, list[dict[str, Any]]], travel_all: list[dict[str, Any]],
                  clusters: list[dict[str, Any]], sts: dict[str, dict[str, Any]], nm: dict[str, str], since: str) -> dict[str, Any]:
    """What matters about one city right now: risky accounts operating there, cash leaving through its ATMs,
    location signals that start or end there, and accounts that are new to it."""
    from vigil import overview
    here = {a: [p for p in pts if p["city"] == city] for a, pts in per_acct.items()}
    here = {a: v for a, v in here.items() if v}
    risky = sorted([{"account": a, "name": nm.get(a, a), "status": sts.get(a, {}).get("status", "normal"),
                     "postings": len(v), "value_paise": sum(p["amount_paise"] for p in v)}
                    for a, v in here.items() if sts.get(a, {}).get("status") in overview.RISKY | overview.WARN],
                   key=lambda r: -r["value_paise"])
    atm = db.q("SELECT sender_id, amount_paise FROM transactions WHERE ts >= ? AND geo_basis = 'atm_terminal' AND geo_city = ?",
               (since, city))
    atm_risky = [r for r in atm if sts.get(r["sender_id"], {}).get("status") in overview.RISKY]
    newcomers = [{"account": a, "name": nm.get(a, a), "home_city": e["rules"][0].get("home_city")}
                 for a, e in STATE.evidence.items() for r in e["rules"][:1]
                 if r["rule"] == "LOC_UNUSUAL_REGION" and r.get("city") == city]
    return {"city": city, "accounts_here": len(here), "precise_here": sum(1 for v in here.values() for p in v if p["basis"] in precise_bases()),
            "risky_accounts": risky[:6], "atm_withdrawals": len(atm), "atm_value_paise": sum(r["amount_paise"] for r in atm),
            "atm_risky": len(atm_risky), "atm_risky_value_paise": sum(r["amount_paise"] for r in atm_risky),
            "travel": [t for t in travel_all if city in (t["from_city"], t["to_city"])],
            "clusters": [c["id"] for c in clusters if c.get("city") == city], "newcomers": newcomers}
