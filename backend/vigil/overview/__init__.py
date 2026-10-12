"""Overview read models (overview-v10 P2) — shared by `api/routes_overview.py` and the Copilot's read-only tools.

Everything here is a READ over the ledger, the in-memory PathGraph and the live status resolver. Nothing writes,
nothing changes a status or a payment tier, nothing reads ground truth (`seed_role`, `seed_attack`).

Vocabulary
* risk of a posting — "fraud" when either party is currently flagged / held / confirmed fraud or sits in a
  detected ring or cluster; "suspicious" when either party is under early warning; otherwise "normal".
  It describes the accounts as they are NOW (a posting made before an account was flagged turns red later).
* rail — the payment rail to display (`geo.rail`): ATM / international sinks show as such even on legacy rows.
* locations — simulated; always returned with basis + accuracy (`geo.label`).
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from datetime import timedelta
from functools import lru_cache
from typing import Any, Callable

import yaml

from vigil import clock, db, geo
from vigil.engine import livestatus
from vigil.graph.pathgraph import GRAPH
from vigil.settings import REPO_ROOT, get_policy

COPILOT_POLICY_PATH = REPO_ROOT / "config" / "copilot_policy.yaml"
RISKY = {"flagged", "held", "confirmed_fraud"}
WARN = {"early_warning"}
SINKS = ("ext:atm", "ext:other-bank", "ext:intl-wire")
SINK_LABEL = {"ext:atm": "Cash (ATM)", "ext:other-bank": "Other banks", "ext:intl-wire": "International wire"}
RAIL_LABEL = {"upi": "UPI", "imps": "IMPS", "neft": "NEFT", "rtgs": "RTGS", "card": "Card / POS", "atm": "ATM",
              "wallet": "Wallet", "intl_wire": "International"}
STOPPED_STATES = ("HELD", "ESCALATED", "CANCELLED", "REJECTED", "CHALLENGED")


@lru_cache(maxsize=1)
def policy() -> dict[str, Any]:
    return yaml.safe_load(COPILOT_POLICY_PATH.read_bytes())


# ── tiny TTL cache (single event-loop thread; values are recomputed at most every `ttl` seconds) ──
_CACHE: dict[str, tuple[float, Any]] = {}


def cached(key: str, ttl: float, fn: Callable[[], Any]) -> Any:
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = fn()
    _CACHE[key] = (now + ttl, value)
    return value


def invalidate() -> None:
    _CACHE.clear()


def statuses() -> dict[str, dict[str, Any]]:
    return cached("statuses", 2.0, livestatus.statuses)


def window_s(window: str) -> int:
    return int(policy()["windows"].get(window, 3600))


def names() -> dict[str, str]:
    return cached("names", 5.0, lambda: {r["id"]: r["display_name"] for r in db.q("SELECT id, display_name FROM accounts")})


# ── rings / clusters (reuses RingWatch output and the live statuses — no new detector) ──
def rings() -> list[dict[str, Any]]:
    def build() -> list[dict[str, Any]]:
        from vigil.risk import ringwatch
        sts = statuses()
        scan = {r["account_id"]: r for r in ringwatch.scan(min_score=0.3)}
        cand = {a for a, s in sts.items() if s["status"] in RISKY | WARN} | set(scan)
        cand = {a for a in cand if not a.startswith("ext:")}
        if not cand:
            return []
        since_t = clock.now().timestamp() - float(get_policy()["network"]["window_hours"]) * 3600
        parent = {a: a for a in cand}

        def find(a: str) -> str:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        value: Counter = Counter()
        for a in cand:
            for e in GRAPH.outflows(a, since_t):
                if e.dst in cand:
                    ra, rb = find(a), find(e.dst)
                    if ra != rb:
                        parent[ra] = rb
        groups: dict[str, list[str]] = defaultdict(list)
        for a in cand:
            groups[find(a)].append(a)
        out = []
        for members in groups.values():
            if len(members) < 2:
                continue
            ms = set(members)
            for a in members:
                for e in GRAPH.outflows(a, since_t):
                    if e.dst in ms:
                        value[find(a)] += e.amount_paise
            rules = sorted({lab for a in members for lab in (scan.get(a, {}).get("labels") or [])})
            roles = Counter(sts[a].get("role") for a in members if sts.get(a, {}).get("role"))
            kind = ("ring" if any("Circular" in r for r in rules) else "chain" if any("chain" in r for r in rules)
                    else "collection" if roles.get("collector") else "cluster")
            members.sort(key=lambda a: (-livestatus.RANK.get(sts.get(a, {}).get("status", "normal"), 0), a))
            marks = ",".join("?" * len(members))       # where the members actually transact (simulated), else home
            cities = Counter(r["geo_city"] for r in db.q(
                f"SELECT geo_city FROM transactions WHERE sender_id IN ({marks}) AND geo_city IS NOT NULL "
                f"ORDER BY seq DESC LIMIT 24", tuple(members)))
            if not cities:
                cities = Counter(geo.home_for(a) for a in members if geo.home_for(a))
            out.append({"id": "RING-" + members[0].split("@")[0], "kind": kind, "members": members,
                        "size": len(members), "value_paise": int(value[find(members[0])]),
                        "flagged": sum(1 for a in members if sts.get(a, {}).get("status") in RISKY),
                        "rules": rules, "roles": dict(roles), "city": cities.most_common(1)[0][0] if cities else None})
        out.sort(key=lambda r: (-r["flagged"], -r["value_paise"]))
        return out
    return cached("rings", 3.0, build)


def ring_members() -> set[str]:
    return {a for r in rings() for a in r["members"]}


def risk_of(a: str, b: str, sts: dict[str, dict[str, Any]] | None = None, members: set[str] | None = None) -> str:
    sts = sts if sts is not None else statuses()
    members = members if members is not None else ring_members()
    sa, sb = sts.get(a, {}).get("status"), sts.get(b, {}).get("status")
    if sa in RISKY or sb in RISKY or a in members or b in members:
        return "fraud"
    if sa in WARN or sb in WARN:
        return "suspicious"
    return "normal"


# ── postings in a window ──────────────────────────────────────────────────
_TX_COLS = ("id, seq, ts, kind, sender_id, recipient_id, amount_paise, channel, device_id, intent_id, source, "
            "geo_city, geo_lat, geo_lng, geo_basis, geo_accuracy_m, peer_geo_city, peer_geo_lat, peer_geo_lng")


def postings(seconds: int, channel: str = "all", end_offset_s: int = 0) -> list[dict[str, Any]]:
    now = clock.now()
    hi = clock.iso(now - timedelta(seconds=end_offset_s))
    lo = clock.iso(now - timedelta(seconds=end_offset_s + seconds))
    rows = db.q(f"SELECT {_TX_COLS} FROM transactions WHERE ts > ? AND ts <= ? AND kind != 'opening' ORDER BY seq",
                (lo, hi))
    for r in rows:
        r["rail"] = geo.rail(r["channel"], r["recipient_id"])
    if channel and channel != "all":
        rows = [r for r in rows if r["rail"] == channel]
    return rows


def _sum(rows: list[dict[str, Any]], pred: Callable[[dict[str, Any]], bool] = lambda r: True) -> int:
    return int(sum(r["amount_paise"] for r in rows if pred(r)))


# ── KPI strip ────────────────────────────────────────────────────────────
def kpis(window: str = "1h", channel: str = "all", accounts: set[str] | None = None) -> dict[str, Any]:
    secs = window_s(window)
    sts, members = statuses(), ring_members()
    cur, prev = postings(secs, channel), postings(secs, channel, end_offset_s=secs)
    if accounts:                                       # incident mode: only postings touching these accounts
        cur = [r for r in cur if r["sender_id"] in accounts or r["recipient_id"] in accounts]
        prev = [r for r in prev if r["sender_id"] in accounts or r["recipient_id"] in accounts]

    def fraud(r: dict[str, Any]) -> bool:
        return risk_of(r["sender_id"], r["recipient_id"], sts, members) == "fraud"

    def left(r: dict[str, Any]) -> bool:
        return r["recipient_id"] in SINKS

    def stopped(lo_off: int) -> int:
        now = clock.now()
        lo = clock.iso(now - timedelta(seconds=lo_off + secs))
        hi = clock.iso(now - timedelta(seconds=lo_off))
        return int(db.scalar(
            f"SELECT COALESCE(SUM(amount_paise), 0) FROM transaction_intents WHERE created_at > ? AND created_at <= ? "
            f"AND tier >= 2 AND state IN ({','.join('?' * len(STOPPED_STATES))})", (lo, hi, *STOPPED_STATES)) or 0)

    buckets = 12
    step = max(1, secs // buckets)
    spark = {k: [0] * buckets for k in ("moved", "fraud", "left")}
    now_t = clock.now().timestamp()
    for r in cur:
        i = min(buckets - 1, max(0, buckets - 1 - int((now_t - clock.parse(r["ts"]).timestamp()) // step)))
        spark["moved"][i] += r["amount_paise"]
        if fraud(r):
            spark["fraud"][i] += r["amount_paise"]
        if left(r):
            spark["left"][i] += r["amount_paise"]
    counts = Counter(s["status"] for s in sts.values())
    new30 = int(db.scalar("SELECT COUNT(*) FROM accounts WHERE kind = 'customer' AND opened_at >= ?",
                          (clock.iso(clock.now() - timedelta(days=30)),)) or 0)
    new_win = int(db.scalar("SELECT COUNT(*) FROM accounts WHERE kind = 'customer' AND opened_at >= ?",
                            (clock.iso(clock.now() - timedelta(seconds=secs)),)) or 0)

    def tile(key: str, value: int, previous: int | None, unit: str, label: str, how: str, sparkline: list[int] | None = None,
             tone: str | None = None) -> dict[str, Any]:
        delta = None if previous is None else value - previous
        return {"key": key, "label": label, "value": value, "previous": previous, "delta": delta, "unit": unit,
                "how": how, "spark": sparkline, "tone": tone}

    at_risk = counts.get("flagged", 0) + counts.get("held", 0) + counts.get("confirmed_fraud", 0)
    if accounts:
        at_risk = sum(1 for a in accounts if sts.get(a, {}).get("status") in RISKY)
    return {"window": window, "channel": channel, "generated_ts": clock.now_iso(),
            "scope": sorted(accounts) if accounts else None, "tiles": [
        tile("moved", _sum(cur), _sum(prev), "paise", "Money moved",
             f"Value of every posting in the last {window} (all rails, transfers + cash + external).", spark["moved"]),
        tile("fraud", _sum(cur, fraud), _sum(prev, fraud), "paise", "Fraud-linked",
             "Value of postings that touch an account that is flagged, held, confirmed fraud or in a detected ring.",
             spark["fraud"], "bad" if _sum(cur, fraud) else None),
        tile("at_risk", at_risk, None, "count", "Accounts at risk",
             f"{counts.get('flagged', 0)} flagged · {counts.get('held', 0)} held · {counts.get('confirmed_fraud', 0)} confirmed · "
             f"{counts.get('early_warning', 0)} early warning (right now).", None, "bad" if at_risk else "ok"),
        tile("stopped", stopped(0), stopped(secs), "paise", "Stopped before paying",
             "Tier ≥ 2 payments in the window that did not go through: held, escalated, rejected or abandoned by the "
             "customer after a warning.", None, "ok" if stopped(0) else None),
        tile("left", _sum(cur, left), _sum(prev, left), "paise", "Left the bank",
             "Value that moved outside our perimeter: ATM cash, other banks, international wires.", spark["left"]),
        tile("new", new30, None, "count", "New accounts · 30 d",
             f"Customer accounts opened in the last 30 days ({new_win} in this window).", None),
    ]}


# ── money map ────────────────────────────────────────────────────────────
def geo_map(window: str = "1h", channel: str = "all") -> dict[str, Any]:
    secs = window_s(window)
    sts, members = statuses(), ring_members()
    rows = postings(secs, channel)
    cities: dict[str, dict[str, Any]] = {}
    flows: dict[tuple[str, str], dict[str, Any]] = {}
    atm_terms = {(t["lat"], t["lng"]): t for t in geo.atm_terminals()}
    atm: dict[str, dict[str, Any]] = {}
    order = {"normal": 0, "suspicious": 1, "fraud": 2}
    for r in rows:
        c = r["geo_city"]
        if not c:
            continue
        rk = risk_of(r["sender_id"], r["recipient_id"], sts, members)
        cc = cities.setdefault(c, {"city": c, "tx_count": 0, "value_paise": 0, "fraud_linked_paise": 0,
                                   "suspicious_count": 0, "at_risk_accounts": 0})
        cc["tx_count"] += 1
        cc["value_paise"] += r["amount_paise"]
        if rk == "fraud":
            cc["fraud_linked_paise"] += r["amount_paise"]
        elif rk == "suspicious":
            cc["suspicious_count"] += 1
        pc = r["peer_geo_city"]
        if pc and pc != c:
            f = flows.setdefault((c, pc), {"from_city": c, "to_city": pc, "tx_count": 0, "value_paise": 0, "risk": "normal",
                                           "rails": Counter()})
            f["tx_count"] += 1
            f["value_paise"] += r["amount_paise"]
            f["rails"][r["rail"]] += 1
            if order[rk] > order[f["risk"]]:
                f["risk"] = rk
        if r["geo_basis"] == "atm_terminal":
            t = atm_terms.get((r["geo_lat"], r["geo_lng"]))
            if t:
                a = atm.setdefault(t["terminal_id"], {**t, "withdrawals": 0, "value_paise": 0, "risk_value_paise": 0})
                a["withdrawals"] += 1
                a["value_paise"] += r["amount_paise"]
                if rk == "fraud":
                    a["risk_value_paise"] += r["amount_paise"]
    for aid, s in sts.items():
        if s["status"] in RISKY:
            h = geo.home_for(aid)
            if h and h in cities:
                cities[h]["at_risk_accounts"] += 1
            elif h:
                cities[h] = {"city": h, "tx_count": 0, "value_paise": 0, "fraud_linked_paise": 0, "suspicious_count": 0,
                             "at_risk_accounts": 1}
    for c in cities.values():
        ref = geo.city(c["city"]) or {}
        c.update(lat=ref.get("lat"), lng=ref.get("lng"), state=ref.get("state"), kind=ref.get("kind"))
    for c in geo.FOREIGN:                               # foreign destinations always listed (grey unless used)
        cities.setdefault(c["city"], {"city": c["city"], "tx_count": 0, "value_paise": 0, "fraud_linked_paise": 0,
                                      "suspicious_count": 0, "at_risk_accounts": 0, "lat": c["lat"], "lng": c["lng"],
                                      "state": c["state"], "kind": "foreign"})
    flow_list = sorted(flows.values(), key=lambda f: (-order[f["risk"]], -f["value_paise"]))[:200]
    for f in flow_list:
        f["rails"] = dict(f["rails"])
        a, b = geo.city(f["from_city"]) or {}, geo.city(f["to_city"]) or {}
        f.update(from_lat=a.get("lat"), from_lng=a.get("lng"), to_lat=b.get("lat"), to_lng=b.get("lng"))
    since = clock.iso(clock.now() - timedelta(seconds=max(secs, 3600)))
    clusters = [{**c, "kind": "cash_out"} for c in cash_out_clusters(since)] + collection_points()
    return {"window": window, "channel": channel, "generated_ts": clock.now_iso(), "synthetic": True,
            "cities": sorted(cities.values(), key=lambda c: -c["value_paise"])[:40],
            "flows": flow_list, "atm": sorted(atm.values(), key=lambda a: -a["value_paise"]),
            "clusters": clusters, "totals": {"postings": len(rows), "value_paise": _sum(rows)}}


# ── derived signals (display / investigation only) ───────────────────────
def cash_out_clusters(since_iso: str) -> list[dict[str, Any]]:
    cfg = policy()["signals"]
    sts, members = statuses(), ring_members()
    rows = db.q("SELECT id, ts, sender_id, amount_paise, geo_city, geo_lat, geo_lng FROM transactions "
                "WHERE ts >= ? AND geo_basis = 'atm_terminal' ORDER BY ts", (since_iso,))
    risky = [r for r in rows if r["geo_lat"] is not None and
             (sts.get(r["sender_id"], {}).get("status") in RISKY or r["sender_id"] in members)]
    used: set[str] = set()
    out = []
    win = float(cfg["cash_out_window_min"]) * 60
    for i, a in enumerate(risky):
        if a["id"] in used:
            continue
        ta = clock.parse(a["ts"]).timestamp()
        group = [a]
        for b in risky[i + 1:]:
            if b["id"] in used:
                continue
            if clock.parse(b["ts"]).timestamp() - ta > win:
                break
            if geo.haversine_km((a["geo_lat"], a["geo_lng"]), (b["geo_lat"], b["geo_lng"])) <= cfg["cash_out_radius_km"]:
                group.append(b)
        if len(group) >= cfg["cash_out_min_withdrawals"]:
            used.update(g["id"] for g in group)
            lat = sum(g["geo_lat"] for g in group) / len(group)
            lng = sum(g["geo_lng"] for g in group) / len(group)
            radius = max(geo.haversine_km((lat, lng), (g["geo_lat"], g["geo_lng"])) for g in group)
            out.append({"id": f"CASH-{group[0]['id']}", "center": {"lat": round(lat, 5), "lng": round(lng, 5)},
                        "radius_km": round(max(radius, 0.3), 2), "city": group[0]["geo_city"],
                        "accounts": sorted({g["sender_id"] for g in group}), "tx_ids": [g["id"] for g in group],
                        "value_paise": _sum(group), "first_ts": group[0]["ts"], "last_ts": group[-1]["ts"]})
    return out


def collection_points() -> list[dict[str, Any]]:
    """Accounts whose distinct-sender fan-in in the live window is at or above the risk policy's fan-in rule."""
    net = get_policy()["network"]
    min_senders = int(net["fan_in"]["min_distinct_senders"])
    since_t = clock.now().timestamp() - float(net["window_hours"]) * 3600
    sts = statuses()
    out = []
    for aid, meta in GRAPH.accounts.items():
        if meta.get("kind") == "external" or meta.get("persona") == "merchant":
            continue
        ins = GRAPH.inflows(aid, since_t)
        senders = {e.src for e in ins if not e.src.startswith("ext:")}
        if len(senders) >= min_senders:
            hp = geo.home_point(aid)
            out.append({"id": f"COLL-{aid.split('@')[0]}", "kind": "collection", "account": aid,
                        "accounts": [aid], "senders": len(senders), "value_paise": int(sum(e.amount_paise for e in ins)),
                        "status": sts.get(aid, {}).get("status"), "city": geo.home_for(aid),
                        "center": {"lat": hp[0], "lng": hp[1]} if hp else None, "radius_km": 1.0,
                        "rule": f"≥ {min_senders} distinct senders in {net['window_hours']} h (risk policy fan-in)"})
    return sorted(out, key=lambda c: -c["senders"])


def impossible_travel(since_iso: str) -> list[dict[str, Any]]:
    kmh = float(policy()["signals"]["impossible_travel_kmh"])
    rows = db.q("SELECT id, ts, sender_id, geo_city, geo_lat, geo_lng FROM transactions WHERE ts >= ? "
                "AND geo_basis = 'device_gps' ORDER BY sender_id, ts", (since_iso,))
    out, last = [], {}
    for r in rows:
        p = last.get(r["sender_id"])
        if p:
            km = geo.haversine_km((p["geo_lat"], p["geo_lng"]), (r["geo_lat"], r["geo_lng"]))
            hours = max((clock.parse(r["ts"]).timestamp() - clock.parse(p["ts"]).timestamp()) / 3600, 1 / 3600)
            if km >= 50 and km / hours > kmh:
                out.append({"account": r["sender_id"], "from_city": p["geo_city"], "to_city": r["geo_city"],
                            "km": round(km), "minutes": round(hours * 60, 1), "kmh": round(km / hours),
                            "tx_ids": [p["id"], r["id"]], "ts": r["ts"]})
        last[r["sender_id"]] = r
    return out


# ── live transaction tape ────────────────────────────────────────────────
def _tier_map(intent_ids: list[str]) -> dict[str, int]:
    ids = [i for i in intent_ids if i]
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {r["id"]: r["tier"] for r in db.q(f"SELECT id, tier FROM transaction_intents WHERE id IN ({marks})", tuple(ids))}


def tape_row(r: dict[str, Any], sts: dict[str, Any], members: set[str], nm: dict[str, str],
             tiers: dict[str, int]) -> dict[str, Any]:
    s, t = sts.get(r["sender_id"], {}), sts.get(r["recipient_id"], {})
    return {"tx_id": r["id"], "seq": r["seq"], "ts": r["ts"], "kind": r["kind"],
            "sender_id": r["sender_id"], "sender_name": nm.get(r["sender_id"], r["sender_id"]),
            "recipient_id": r["recipient_id"], "recipient_name": nm.get(r["recipient_id"], r["recipient_id"]),
            "amount_paise": r["amount_paise"], "rail": r.get("rail") or geo.rail(r["channel"], r["recipient_id"]),
            "origin": {"seed": "history", "cohort_v10": "history"}.get(r["source"], r["source"]),
            "sender_status": s.get("status", "normal"), "recipient_status": t.get("status", "normal"),
            "risk": risk_of(r["sender_id"], r["recipient_id"], sts, members),
            "tier": tiers.get(r.get("intent_id") or ""),
            "geo": {"city": r["geo_city"], "lat": r["geo_lat"], "lng": r["geo_lng"], "basis": r["geo_basis"],
                    "accuracy_m": r["geo_accuracy_m"], "label": geo.label(r["geo_basis"], r["geo_accuracy_m"]),
                    "peer_city": r["peer_geo_city"], "peer_lat": r["peer_geo_lat"], "peer_lng": r["peer_geo_lng"]}}


def tape(limit: int = 100, since_id: str | None = None, channel: str = "all", only: str = "all",
         q: str | None = None, accounts: list[str] | None = None) -> dict[str, Any]:
    params: list[Any] = []
    where = "kind != 'opening'"
    if since_id:
        seq = db.scalar("SELECT seq FROM transactions WHERE id = ?", (since_id,))
        if seq is not None:
            where += " AND seq > ?"
            params.append(seq)
    if q:
        where += " AND (sender_id LIKE ? OR recipient_id LIKE ? OR id = ?)"
        params += [f"%{q.lower()}%", f"%{q.lower()}%", q.upper()]
    if accounts:
        marks = ",".join("?" * len(accounts[:40]))
        where += f" AND (sender_id IN ({marks}) OR recipient_id IN ({marks}))"
        params += accounts[:40] * 2
    scan_n = limit * (8 if (only != "all" or channel != "all") else 1)
    rows = db.q(f"SELECT {_TX_COLS} FROM transactions WHERE {where} ORDER BY seq DESC LIMIT ?", (*params, min(scan_n, 4000)))
    sts, members, nm = statuses(), ring_members(), names()
    tiers = _tier_map([r["intent_id"] for r in rows])
    out = []
    for r in rows:
        row = tape_row(r, sts, members, nm, tiers)
        if channel != "all" and row["rail"] != channel:
            continue
        if only == "fraud" and row["risk"] != "fraud":
            continue
        if only == "suspicious" and row["risk"] == "normal":
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return {"rows": out, "generated_ts": clock.now_iso()}


# ── connections drawer ───────────────────────────────────────────────────
def _account_card(aid: str, sts: dict[str, Any], nm: dict[str, str]) -> dict[str, Any]:
    s = sts.get(aid, {})
    return {"id": aid, "name": nm.get(aid, aid), "status": s.get("status", "external" if aid.startswith("ext:") else "normal"),
            "risk": s.get("risk"), "model_risk": s.get("model_risk"), "role": s.get("role"), "reason": s.get("reason"),
            "home_city": geo.home_for(aid)}


def _trace(start: str, t: float, direction: str, depth: int = 3, breadth: int = 12) -> list[dict[str, Any]]:
    """Up to `depth` hops of money into (upstream) or out of (downstream) `start`, ordered by ₹ then recency."""
    out: list[dict[str, Any]] = []
    frontier = [(start, t)]
    seen = {start}
    for hop in range(1, depth + 1):
        nxt = []
        for node, nt in frontier:
            if node.startswith("ext:"):
                continue
            edges = GRAPH.inflows_before(node, nt) if direction == "up" else GRAPH.outflows(node, nt)
            edges = sorted(edges, key=lambda e: (-e.amount_paise, -e.t))[:breadth]
            for e in edges:
                other = e.src if direction == "up" else e.dst
                out.append({"from": e.src, "to": e.dst, "account": other, "amount_paise": e.amount_paise, "ts": e.ts,
                            "tx_id": e.tx_id, "hops": hop})
                if other not in seen:
                    seen.add(other)
                    nxt.append((other, e.t))
        frontier = nxt[:breadth]
        if not frontier:
            break
    return out[:depth * breadth]


def connections(tx_id: str) -> dict[str, Any] | None:
    r = db.q1(f"SELECT {_TX_COLS} FROM transactions WHERE id = ?", (tx_id,))
    if r is None:
        return None
    sts, members, nm = statuses(), ring_members(), names()
    t = clock.parse(r["ts"]).timestamp()
    s, rc = r["sender_id"], r["recipient_id"]
    upstream = _trace(s, t, "up")
    downstream = _trace(rc, t, "down")
    shared = sorted((GRAPH.device_peers(s) | GRAPH.device_peers(rc)) - {s, rc})
    ring = next((g for g in rings() if s in g["members"] or rc in g["members"]), None)
    net = get_policy()["network"]
    since_t = clock.now().timestamp() - float(net["window_hours"]) * 3600
    linked = []
    if shared:
        linked.append("shared_device")
    if len({e.src for e in GRAPH.inflows(rc, since_t)}) >= int(net["fan_in"]["min_distinct_senders"]):
        linked.append("fan_in")
    if len({e.dst for e in GRAPH.outflows(s, since_t)}) >= int(net["fan_out"]["min_distinct_recipients"]):
        linked.append("fan_out")
    if ring and s in ring["members"] and rc in ring["members"]:
        linked.append("ring")
    common = ({e.dst for e in GRAPH.outflows(s, since_t)} & {e.dst for e in GRAPH.outflows(rc, since_t)}) - set(SINKS)
    if common:
        linked.append("same_payee")
    path = [{"city": r["geo_city"], "lat": r["geo_lat"], "lng": r["geo_lng"], "account": s}]
    if r["peer_geo_city"]:
        path.append({"city": r["peer_geo_city"], "lat": r["peer_geo_lat"], "lng": r["peer_geo_lng"], "account": rc})
    for d in downstream[:6]:
        c = geo.city(geo.home_for(d["account"]) or "")
        if c:
            path.append({"city": c["city"], "lat": c["lat"], "lng": c["lng"], "account": d["account"]})
    row = tape_row({**r, "rail": geo.rail(r["channel"], rc)}, sts, members, nm, _tier_map([r["intent_id"]]))
    for lst in (upstream, downstream):
        for d in lst:
            d["status"] = sts.get(d["account"], {}).get("status", "external" if d["account"].startswith("ext:") else "normal")
            d["name"] = nm.get(d["account"], d["account"])
    return {"tx": row, "sender": _account_card(s, sts, nm), "recipient": _account_card(rc, sts, nm),
            "upstream": upstream, "downstream": downstream,
            "shared_device": [_account_card(a, sts, nm) for a in shared[:12]],
            "same_ring": ring, "linked_by": linked, "common_payees": sorted(common)[:6], "geo_path": path}


# ── mule pipeline ────────────────────────────────────────────────────────
STAGES = ("opened", "funded", "active", "passing_through", "exited")
STAGE_LABEL = {"opened": "Opened", "funded": "Funded", "active": "Active", "passing_through": "Passing through",
               "exited": "Exited the bank"}


def pipeline(days: int | None = None) -> dict[str, Any]:
    cfg = policy()["pipeline"]
    days = int(days or cfg["days"])
    hours = float(cfg["pass_through_hours"]) * 3600
    frac = float(cfg["pass_through_fraction"])
    # the money must be worth moving: reuse the risk policy's pass-through floor (not duplicated here)
    min_in = int(get_policy()["network"]["pass_through"]["min_inflow_paise"])
    merchants = {a for a, m in GRAPH.accounts.items() if m.get("persona") == "merchant"}
    now = clock.now()
    sts, nm = statuses(), names()
    rows = db.q("SELECT id, display_name, opened_at, persona FROM accounts WHERE kind = 'customer' AND opened_at >= ? "
                "ORDER BY opened_at DESC", (clock.iso(now - timedelta(days=days)),))
    cols = {r["name"] for r in db.q("PRAGMA table_info(accounts)")}
    via = {r["id"]: (r.get("opened_via"), r.get("opened_city")) for r in db.q(
        "SELECT id, opened_via, opened_city FROM accounts")} if "opened_via" in cols else {}
    accounts = []
    counts = Counter()
    for a in rows:
        aid = a["id"]
        ins = [e for e in GRAPH.in_edges.get(aid, []) if e.kind != "opening"]
        outs = list(GRAPH.out_edges.get(aid, []))
        total_in = sum(e.amount_paise for e in ins)
        total_out = sum(e.amount_paise for e in outs)
        forwarded = 0
        for o in outs:
            if o.dst in merchants:                      # shopping is spending, not forwarding
                continue
            if any(0 <= o.t - i.t <= hours for i in ins):
                forwarded += o.amount_paise
        fwd_frac = min(1.0, forwarded / total_in) if total_in else 0.0
        exited = any(o.dst in SINKS for o in outs)
        stage = "opened"
        if ins:
            stage = "funded"
        if ins and outs:
            stage = "active"
        passing = bool(ins and outs and fwd_frac >= frac and total_in >= min_in)
        if passing:
            stage = "passing_through"
            if exited:
                stage = "exited"
        age = (now - clock.parse(a["opened_at"])).total_seconds() / 86400
        suspicious = passing and age <= float(cfg["new_account_days"])
        peers = sorted(GRAPH.device_peers(aid) - {aid})
        st = sts.get(aid, {}).get("status", "normal")
        benign_share = (len(peers) == 1 and st not in RISKY | WARN and sts.get(peers[0], {}).get("status") not in RISKY | WARN)
        for s in STAGES[:STAGES.index(stage) + 1]:
            counts[s] += 1
        ov, oc = via.get(aid, (None, None))
        accounts.append({
            "id": aid, "name": nm.get(aid, aid), "age_days": round(age, 1), "opened_at": a["opened_at"],
            "opened_via": ov, "opened_city": oc or geo.home_for(aid), "stage": stage, "suspicious_path": suspicious,
            "in_paise": int(total_in), "out_paise": int(total_out),
            "retention_pct": round(100 * max(0.0, 1 - total_out / total_in), 1) if total_in else None,
            "forwarded_pct": round(100 * fwd_frac, 1), "exited_via": sorted({SINK_LABEL[o.dst] for o in outs if o.dst in SINKS}),
            "device_shared_with": peers[:6],
            "shared_note": "Shared with one account, neither shows risk signals — family / shop pattern (display heuristic)"
            if benign_share else None,
            "status": st, "first_credit_ts": ins[0].ts if ins else None, "first_debit_ts": outs[0].ts if outs else None,
        })
    stage_vals = {s: 0 for s in STAGES}
    for acc in accounts:
        for s in STAGES[:STAGES.index(acc["stage"]) + 1]:
            stage_vals[s] += acc["in_paise"]
    return {"days": days, "generated_ts": clock.now_iso(),
            "rule": f"Passing through = received at least {_inr(min_in)} and moved ≥ {int(frac * 100)}% of it on to other "
                    f"people, other banks, cash or abroad within {int(hours / 3600)} h (shop purchases don't count); "
                    f"suspicious path = passing through while ≤ {cfg['new_account_days']} days old. Display heuristic "
                    f"(config/copilot_policy.yaml + the risk policy's pass-through floor), not a model and not a payment rule.",
            "stages": [{"key": s, "label": STAGE_LABEL[s], "count": counts.get(s, 0), "value_paise": stage_vals[s]}
                       for s in STAGES],
            "suspicious": sum(1 for a in accounts if a["suspicious_path"]), "accounts": accounts}


# ── exits, channels, brief ───────────────────────────────────────────────
def exits(window: str = "24h") -> dict[str, Any]:
    secs = window_s(window)
    sts, members = statuses(), ring_members()
    rows = [r for r in postings(secs) if r["recipient_id"] in SINKS]
    by_sink: dict[str, dict[str, Any]] = {}
    by_city: dict[str, dict[str, Any]] = {}
    for r in rows:
        fraud = risk_of(r["sender_id"], r["recipient_id"], sts, members) == "fraud"
        k = r["recipient_id"]
        s = by_sink.setdefault(k, {"sink": k, "label": SINK_LABEL[k], "count": 0, "value_paise": 0, "fraud_linked_paise": 0})
        s["count"] += 1
        s["value_paise"] += r["amount_paise"]
        s["fraud_linked_paise"] += r["amount_paise"] if fraud else 0
        city_key = r["peer_geo_city"] if k == "ext:intl-wire" and r["peer_geo_city"] else r["geo_city"] or "Unknown"
        c = by_city.setdefault(city_key, {"city": city_key, "count": 0, "value_paise": 0, "fraud_linked_paise": 0})
        c["count"] += 1
        c["value_paise"] += r["amount_paise"]
        c["fraud_linked_paise"] += r["amount_paise"] if fraud else 0
    return {"window": window, "by_sink": sorted(by_sink.values(), key=lambda s: -s["value_paise"]),
            "by_city": sorted(by_city.values(), key=lambda c: -c["value_paise"])[:15], "total_paise": _sum(rows)}


def channel_mix(window: str = "24h") -> dict[str, Any]:
    secs = window_s(window)
    sts, members = statuses(), ring_members()
    rows = postings(secs)
    val, fr, cnt = Counter(), Counter(), Counter()
    for r in rows:
        val[r["rail"]] += r["amount_paise"]
        cnt[r["rail"]] += 1
        if risk_of(r["sender_id"], r["recipient_id"], sts, members) == "fraud":
            fr[r["rail"]] += r["amount_paise"]
    tv, tf = sum(val.values()) or 1, sum(fr.values()) or 1
    rails = [{"rail": k, "label": RAIL_LABEL.get(k, k), "count": cnt[k], "value_paise": val[k], "fraud_linked_paise": fr[k],
              "share_value": round(val[k] / tv, 4), "share_fraud": round(fr[k] / tf, 4) if sum(fr.values()) else 0.0}
             for k in geo.CHANNELS if cnt[k] or k in ("upi", "imps", "neft", "card")]
    return {"window": window, "rails": rails, "total_paise": sum(val.values()), "fraud_total_paise": sum(fr.values())}


def _inr(paise: int) -> str:
    rupees = paise / 100
    if rupees >= 1_00_00_000:
        return f"₹{rupees / 1_00_00_000:.2f} Cr"
    if rupees >= 1_00_000:
        return f"₹{rupees / 1_00_000:.2f} L"
    return f"₹{rupees:,.0f}"


def brief(window: str = "1h") -> dict[str, Any]:
    """Deterministic three-line situation brief (also the Copilot's no-LLM fallback)."""
    k = {t["key"]: t for t in kpis(window)["tiles"]}
    mix = channel_mix(window)
    top_rail = max(mix["rails"], key=lambda r: r["value_paise"], default=None)
    sts = statuses()
    risky = sorted(((a, s) for a, s in sts.items() if s["status"] in RISKY),
                   key=lambda x: (-livestatus.RANK.get(x[1]["status"], 0), -(x[1].get("risk") or 0)))
    rg = rings()
    line1 = (f"{_inr(k['moved']['value'])} moved in the last {window}"
             + (f", mostly over {top_rail['label']} ({top_rail['share_value'] * 100:.0f}% of value)" if top_rail and top_rail['value_paise'] else "")
             + f"; {_inr(k['left']['value'])} left the bank.")
    if risky:
        names_ = ", ".join(a.split("@")[0] for a, _ in risky[:3])
        line2 = (f"{k['at_risk']['value']} account(s) at risk ({names_}{'…' if len(risky) > 3 else ''})"
                 + (f"; {len(rg)} connected cluster(s), largest {rg[0]['size']} accounts" if rg else "")
                 + f"; {_inr(k['fraud']['value'])} fraud-linked in the window.")
    else:
        line2 = "No account is flagged, held or confirmed fraud right now."
    stopped = k["stopped"]["value"]
    line3 = (f"{_inr(stopped)} stopped before paying in the window. " if stopped else "") + (
        f"Start with {risky[0][0].split('@')[0]}: {risky[0][1].get('reason') or risky[0][1]['status']}." if risky
        else "Nothing needs action; Copilot is watching.")
    return {"window": window, "lines": [line1, line2, line3], "generated_ts": clock.now_iso(), "llm_used": False}


# ── needs attention ──────────────────────────────────────────────────────
def attention() -> dict[str, Any]:
    """Accounts that need action now (flagged / held / confirmed / early warning) with 24 h money in and out, the
    ring they belong to and whether they are a collection point."""
    sts, nm = statuses(), names()
    rg = rings()
    ring_of = {a: r["id"] for r in rg for a in r["members"]}
    coll = {c["account"] for c in collection_points()}
    since_t = clock.now().timestamp() - 86400
    rows = []
    for aid, s in sts.items():
        if s["status"] not in RISKY | WARN or aid.startswith("ext:"):
            continue
        rows.append({"id": aid, "name": nm.get(aid, aid), "status": s["status"], "reason": s.get("reason"),
                     "role": s.get("role"), "since": s.get("since"), "families_flagging": int(s.get("families_flagging") or 0),
                     "risk": float(s.get("risk") or 0.0), "model_risk": s.get("model_risk"),
                     "in_paise_24h": int(sum(e.amount_paise for e in GRAPH.inflows(aid, since_t))),
                     "out_paise_24h": int(sum(e.amount_paise for e in GRAPH.outflows(aid, since_t))),
                     "ring_id": ring_of.get(aid), "collection_point": aid in coll, "home_city": geo.home_for(aid)})
    rows.sort(key=lambda r: (-livestatus.RANK.get(r["status"], 0), -max(r["risk"], r["model_risk"] or 0)))
    return {"accounts": rows, "rings": rg, "collection_points": collection_points()}


# ── account summary (Copilot get_account) ────────────────────────────────
def account_summary(aid: str) -> dict[str, Any] | None:
    acc = db.q1("SELECT id, display_name, kind, opened_at, persona FROM accounts WHERE id = ?", (aid,))
    if acc is None:
        return None
    sts = statuses()
    s = sts.get(aid, {})
    since_t = clock.now().timestamp() - 86400
    ins = GRAPH.inflows(aid, since_t)
    outs = GRAPH.outflows(aid, since_t)
    tin, tout = sum(e.amount_paise for e in ins), sum(e.amount_paise for e in outs)
    watch = db.q1("SELECT note FROM watchlist WHERE account_id = ?", (aid,))
    return {"id": aid, "display_name": acc["display_name"], "kind": acc["kind"], "status": s.get("status"),
            "reason": s.get("reason"), "role": s.get("role"), "risk": s.get("risk"), "model_risk": s.get("model_risk"),
            "families_flagging": s.get("families_flagging"),
            "age_days": round((clock.now() - clock.parse(acc["opened_at"])).total_seconds() / 86400, 1),
            "home_city": geo.home_for(aid), "devices": sorted(GRAPH.account_devices.get(aid, set())),
            "shared_device_with": sorted(GRAPH.device_peers(aid) - {aid})[:12],
            "in_paise_24h": int(tin), "out_paise_24h": int(tout),
            "retention_pct": round(100 * max(0.0, 1 - tout / tin), 1) if tin else None,
            "watchlisted": watch is not None, "persona": acc["persona"]}
