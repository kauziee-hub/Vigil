"""v3 live platform routes (Claude 1): the 3D transaction universe, live statistics, attack runs.

All `async def` (single-threaded DB access). Push updates arrive over the WebSocket:
`ledger.posted`, `intel.tx_scored`, `intel.account_status` (Claude 2), `attack.run_updated`.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Query

from vigil import clock, db
from vigil.contracts import LiveStats, LiveUniverse, UniverseAccount, UniverseEdge
from vigil.engine import livestatus
from vigil.graph.pathgraph import GRAPH
from vigil.sim import runs

router = APIRouter(prefix="/api")

_ORIGIN = {"seed": "history", "ambient": "ambient", "scenario": "scenario", "user": "user"}


def _edge(r: dict[str, Any]) -> UniverseEdge:
    origin = _ORIGIN.get(r["source"], "user")
    return UniverseEdge(id=r["id"], source=r["sender_id"], target=r["recipient_id"], amount_paise=r["amount_paise"],
                        ts=r["ts"], channel=r["channel"] or "upi", kind=r["kind"], origin=origin,
                        scenario=r["seed_attack"] if origin == "scenario" else None)


def _group(meta: dict[str, Any]) -> str:
    if meta.get("kind") == "external":
        return "external"
    if meta.get("persona") == "merchant":
        return "merchant"
    if meta.get("is_demo_customer"):
        return "demo"
    return "customer"


@router.get("/live/universe")
async def live_universe(window_minutes: int = Query(10, ge=1, le=240), history: int = Query(600, ge=0, le=3000),
                        max_edges: int = Query(1500, ge=50, le=5000)):
    started = time.perf_counter()
    now = clock.now()
    since = clock.iso(now - timedelta(minutes=window_minutes))
    rows = db.q("SELECT id, display_name, kind, persona, is_demo_customer, opened_at, balance_paise FROM accounts")
    last_active = {r["a"]: r["ts"] for r in db.q(
        "SELECT sender_id AS a, MAX(ts) AS ts FROM transactions WHERE kind != 'opening' GROUP BY sender_id")}
    sts = livestatus.statuses([r["id"] for r in rows])
    accounts = []
    for r in rows:
        st = sts.get(r["id"], {})
        accounts.append(UniverseAccount(
            id=r["id"], label=r["display_name"], kind="external" if r["kind"] == "external" else "customer",
            group=_group(r), status=st.get("status", "normal"), risk=round(float(st.get("risk") or 0.0), 3),
            model_risk=st.get("model_risk"), role=st.get("role"), opened_at=r["opened_at"],
            balance_paise=r["balance_paise"], last_active=last_active.get(r["id"])))
    live_rows = db.q("SELECT id, sender_id, recipient_id, amount_paise, ts, channel, kind, source, seed_attack "
                     "FROM transactions WHERE ts >= ? AND kind != 'opening' AND source != 'seed' "
                     "ORDER BY seq DESC LIMIT ?", (since, max_edges))
    live_rows.reverse()
    hist: list[dict[str, Any]] = []
    if history:
        recent = db.q("SELECT id, sender_id, recipient_id, amount_paise, ts, channel, kind, source, seed_attack "
                      "FROM transactions WHERE source = 'seed' AND kind = 'transfer' AND ts >= ? ORDER BY seq",
                      (clock.iso(now - timedelta(hours=72)),))
        step = max(1, len(recent) // history)
        hist = recent[::step][:history]
    totals = {
        "accounts": len(rows),
        "customers": sum(1 for a in accounts if a.group in {"customer", "demo"}),
        "merchants": sum(1 for a in accounts if a.group == "merchant"),
        "transactions": int(db.scalar("SELECT COUNT(*) FROM transactions WHERE kind != 'opening'") or 0),
        "live_edges": len(live_rows),
        "build_ms": int(round((time.perf_counter() - started) * 1000)),
    }
    return LiveUniverse(version=f"{GRAPH.version}:{totals['transactions']}", as_of=clock.iso(now),
                        window_minutes=window_minutes, accounts=accounts, edges=[_edge(r) for r in live_rows],
                        history_edges=[_edge(r) for r in hist], totals=totals).model_dump(mode="json")


@router.get("/live/stats")
async def live_stats():
    now = clock.now()
    now_t = now.timestamp()
    since10 = clock.iso(now - timedelta(minutes=10))
    live = db.q("SELECT ts, channel, source, seed_attack FROM transactions WHERE ts >= ? AND source != 'seed' "
                "AND kind != 'opening'", (since10,))
    buckets: dict[int, dict[str, int]] = {}
    start_b = int((now_t - 600) // 10)
    for b in range(start_b, int(now_t // 10) + 1):
        buckets[b] = {"normal": 0, "attack": 0}
    for r in live:
        b = int(clock.parse(r["ts"]).timestamp() // 10)
        if b in buckets:
            buckets[b]["attack" if r["source"] == "scenario" and r["seed_attack"] else "normal"] += 1
    volume = [{"t": clock.iso(clock.parse("1970-01-01T00:00:00Z") + timedelta(seconds=b * 10)), **v}
              for b, v in sorted(buckets.items())]
    recent_tps = sum(1 for r in live if clock.parse(r["ts"]).timestamp() >= now_t - 10) / 10.0
    ch_rows = db.q("SELECT channel, COUNT(*) AS n FROM transactions WHERE source != 'seed' AND kind = 'transfer' "
                   "GROUP BY channel")
    if not ch_rows:
        ch_rows = db.q("SELECT channel, COUNT(*) AS n FROM transactions WHERE kind = 'transfer' AND ts >= ? "
                       "GROUP BY channel", (clock.iso(now - timedelta(hours=24)),))
    tiers = {str(t): 0 for t in range(5)}
    for r in db.q("SELECT tier, COUNT(*) AS n FROM risk_decisions GROUP BY tier"):
        tiers[str(r["tier"])] = int(r["n"])
    tot: dict[int, dict[str, int]] = {}
    for r in db.q("SELECT created_at, tier FROM risk_decisions WHERE created_at >= ?",
                  (clock.iso(now - timedelta(minutes=15)),)):
        m = int(clock.parse(r["created_at"]).timestamp() // 60)
        tot.setdefault(m, {f"t{i}": 0 for i in range(5)})[f"t{r['tier']}"] += 1
    tiers_over_time = [{"t": clock.iso(clock.parse("1970-01-01T00:00:00Z") + timedelta(minutes=m)), **v}
                       for m, v in sorted(tot.items())]
    all_runs = runs.all_runs()
    by_type: dict[str, dict[str, Any]] = {}
    for r in reversed(all_runs):
        e = by_type.setdefault(r.scenario_id, {"scenario_id": r.scenario_id, "name": r.name, "runs": 0, "detected_runs": 0})
        e["runs"] += 1
        e["detected_runs"] += 1 if r.detected and set(r.detected) & set(r.injected) else 0
    sts = livestatus.statuses()
    counts = Counter(v["status"] for v in sts.values())
    roles: dict[str, int] = {}
    threshold_history: list[dict[str, Any]] = []
    try:
        from vigil.intel import stream  # type: ignore[import-not-found]
        roles = dict(stream.roles_flagged())
        threshold_history = list(stream.threshold_history())
    except Exception:
        for v in sts.values():
            if v["status"] in {"flagged", "confirmed_fraud"} and v.get("role"):
                roles[v["role"]] = roles.get(v["role"], 0) + 1
    active = sum(1 for v in sts.values() if v["status"] not in {"idle", "external"})
    return LiveStats(
        as_of=clock.iso(now), throughput_tps=round(recent_tps, 2), volume=volume,
        channels={r["channel"] or "upi": int(r["n"]) for r in ch_rows}, tiers=tiers, tiers_over_time=tiers_over_time,
        runs_by_type=list(by_type.values()), runs=all_runs, roles_flagged=roles, threshold_history=threshold_history,
        counts={
            "transactions": int(db.scalar("SELECT COUNT(*) FROM transactions WHERE kind != 'opening'") or 0),
            "live_transactions": int(db.scalar("SELECT COUNT(*) FROM transactions WHERE source != 'seed'") or 0),
            "accounts": len(sts), "active": active,
            "early_warning": counts.get("early_warning", 0), "flagged": counts.get("flagged", 0),
            "held": counts.get("held", 0), "confirmed_fraud": counts.get("confirmed_fraud", 0),
            "new": counts.get("new", 0), "attacks_spawned": len(all_runs),
            "attacks_detected": sum(1 for r in all_runs if set(r.detected) & set(r.injected)),
        },
    ).model_dump(mode="json")


@router.get("/attacks/runs")
async def attack_runs():
    return [r.model_dump(mode="json") for r in runs.all_runs()]


@router.get("/attacks/runs/{run_id}")
async def attack_run(run_id: str):
    return runs.get(run_id).model_dump(mode="json")
