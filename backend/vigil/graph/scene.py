"""GraphScene — a capped, cached subgraph with a FROZEN, precomputed 3D layout.

Layout ("layered-3d-v1") is deterministic and computed once per cache key:
  * x = money-flow depth (sources on the left, cash-out on the right) — direction is obvious;
  * nodes in the same layer sit on a ring in the y/z plane, ordered by the
    barycentre of their upstream neighbours (one sweep) to reduce crossings;
  * no force simulation ever runs (server or client).
Cache key = graph version + labels/taint state + active holds + parameters.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from typing import Any

from vigil import clock, db
from vigil.contracts import GraphScene, SceneEdge, SceneNode, SceneTx
from vigil.graph.pathgraph import GRAPH
from vigil.risk import ringwatch, taint
from vigil.settings import get_policy

LAYER_SPACING = 140.0
_cache: dict[str, GraphScene] = {}
_stats = {"hits": 0, "misses": 0}


def _channels() -> dict[str, str]:
    return {r["id"]: r["channel"] for r in db.q("SELECT id, channel FROM transactions WHERE source != 'seed' OR ts >= ?",
                                                (clock.ago_iso(hours=96),))}


def _candidates(cap: int, focus: str | None, hops: int, scenario: str | None,
                window_t: float) -> tuple[list[str], set[str]]:
    """Ordered candidate ids + the core set that is kept even without an in-window edge.

    Default scene: everything suspicious (RingWatch-flagged, taint exposure, labelled).
    Scoped scene (focus and/or scenario): only that account / the scenario's accounts,
    expanded by 1–2 hops — the global suspicious set is NOT mixed in.
    """
    core: list[str] = []
    if focus:
        core.append(focus)
    if scenario:
        from vigil.sim import scenarios
        core += [a for a in scenarios.touched_accounts(scenario) if a not in core]
    if not (focus or scenario):
        flagged = [r["account_id"] for r in ringwatch.scan(min_score=0.3)]
        core += [a for a in flagged if a not in core]
        core += [a for a in taint.exposure() if a not in core]
        core += [a for a in ringwatch.labelled_accounts() if a not in core]
    seen = set(core)
    ordered = list(core)
    frontier = list(core)
    for _ in range(max(1, min(hops, 2))):
        nxt: list[tuple[int, str]] = []
        for nid in frontier:
            for e in GRAPH.inflows(nid, window_t) + GRAPH.outflows(nid, window_t):
                other = e.src if e.dst == nid else e.dst
                if other not in seen:
                    nxt.append((-e.amount_paise, other))
        frontier = []
        for _, other in sorted(nxt):
            if other not in seen and len(ordered) < cap * 2:
                seen.add(other)
                ordered.append(other)
                frontier.append(other)
    return ordered, set(core)


def _layers(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    succ: dict[str, set[str]] = defaultdict(set)
    indeg: dict[str, int] = {n: 0 for n in nodes}
    for s, d in edges:
        if d not in succ[s]:
            succ[s].add(d)
            indeg[d] += 1
    layer = {n: 0 for n in nodes}
    queue = deque(sorted(n for n in nodes if indeg[n] == 0))
    remaining = dict(indeg)
    visited: set[str] = set()
    while queue:
        n = queue.popleft()
        visited.add(n)
        for m in sorted(succ[n]):
            layer[m] = max(layer[m], layer[n] + 1)
            remaining[m] -= 1
            if remaining[m] == 0:
                queue.append(m)
    # cycles: place unvisited nodes one layer after their deepest visited predecessor
    for n in sorted(set(nodes) - visited):
        preds = [s for s, d in edges if d == n and s in visited]
        layer[n] = (max(layer[p] for p in preds) + 1) if preds else 0
    return layer


def build(cap: int = 60, focus: str | None = None, hops: int = 1, scenario: str | None = None) -> GraphScene:
    cap = max(10, min(cap, 400))
    holds = db.scalar("SELECT COUNT(*) || ':' || COALESCE(MAX(id),'') FROM scoped_holds WHERE released_at IS NULL")
    key = f"g{GRAPH.version}|t{taint._cache_key()}|h{holds}|c{cap}|f{focus}|n{hops}|s{scenario}"
    if key in _cache:
        _stats["hits"] += 1
        scene = _cache[key].model_copy()
        scene.cached = True
        return scene
    _stats["misses"] += 1
    started = time.perf_counter()
    window_t = clock.now().timestamp() - float(get_policy()["network"]["window_hours"]) * 3600
    candidates, scoped_core = _candidates(cap, focus, hops, scenario, window_t)
    keep = candidates[:cap]
    keep_set = set(keep)

    scan = {r["account_id"]: r for r in ringwatch.scan(min_score=0.0)}
    exposure = taint.exposure()
    labelled = set(ringwatch.labelled_accounts())
    victims = {r["sender_id"] for r in db.q(
        "SELECT t.sender_id FROM fraud_labels l JOIN transactions t ON t.id = l.transaction_id")}
    held = {r["account_id"] for r in db.q("SELECT account_id FROM scoped_holds WHERE released_at IS NULL")}
    channels = _channels()

    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for e in GRAPH.edges_between(keep):
        if e.t < window_t and not (focus and focus in (e.src, e.dst)):
            continue
        a = agg.setdefault((e.src, e.dst), {"amount": 0, "count": 0, "first": e.ts, "last": e.ts, "txs": [], "ch": set()})
        a["amount"] += e.amount_paise
        a["count"] += 1
        a["first"] = min(a["first"], e.ts)
        a["last"] = max(a["last"], e.ts)
        ch = channels.get(e.tx_id, "upi")
        a["ch"].add(ch)
        if len(a["txs"]) < 25:
            a["txs"].append(SceneTx(id=e.tx_id, ts=e.ts, amount_paise=e.amount_paise, channel=ch))
    # drop isolated nodes that have no edge in the window (except core evidence)
    linked = {n for k in agg for n in k}
    core = (scoped_core if (focus or scenario) else set(scan) & keep_set | labelled | set(exposure))
    keep = [n for n in keep if n in linked or n in core]
    layer = _layers(keep, list(agg))

    traced: dict[tuple[str, str], int] = {}
    for inc in taint.run()["incidents"]:
        for step in inc["rules"]["libr"]["steps"]:
            if step["traced_paise"] > 0:
                k = (step["from_account"], step["to_account"])
                traced[k] = traced.get(k, 0) + int(step["traced_paise"])

    # positions: ring per layer, barycentre ordering
    by_layer: dict[int, list[str]] = defaultdict(list)
    for n in keep:
        by_layer[layer[n]].append(n)
    max_layer = max(by_layer) if by_layer else 0
    angle: dict[str, float] = {}
    pos: dict[str, tuple[float, float, float]] = {}
    for lv in sorted(by_layer):
        members = by_layer[lv]
        def bary(n: str) -> float:
            preds = [angle[s] for (s, d) in agg if d == n and s in angle]
            return sum(preds) / len(preds) if preds else 0.0
        members.sort(key=lambda n: (bary(n), n))
        count = len(members)
        radius = 0.0 if count == 1 else 40.0 + 18.0 * count
        for i, n in enumerate(members):
            theta = (2 * math.pi * i / count) if count > 1 else 0.0
            angle[n] = theta
            x = (lv - max_layer / 2) * LAYER_SPACING
            pos[n] = (round(x, 2), round(radius * math.cos(theta), 2), round(radius * math.sin(theta) * 0.6, 2))

    nodes: list[SceneNode] = []
    for n in keep:
        meta = GRAPH.accounts.get(n, {"display_name": n, "kind": "customer"})
        row = scan.get(n)
        role = row["role"] if row and row["role"] else None
        if n in victims:
            role = "victim"
        if n.startswith("ext:atm"):
            role = "cash-out"
        if role is None:
            role = "normal" if not row or row["score"] < 0.3 else "suspected"
        x, y, z = pos[n]
        bal = db.scalar("SELECT balance_paise FROM accounts WHERE id = ?", (n,)) or 0
        nodes.append(SceneNode(
            id=n, label=meta["display_name"], kind="external" if meta.get("kind") == "external" else "customer",
            x=x, y=y, z=z, layer=layer[n], role=role, risk=row["score"] if row else 0.0,
            taint_paise=exposure.get(n, 0), labelled=n in labelled, victim=n in victims, held=n in held,
            balance_paise=int(bal), flags=row["labels"] if row else [],
        ))
    edges = [SceneEdge(id=f"{s}->{d}", source=s, target=d, amount_paise=a["amount"], count=a["count"],
                       first_ts=a["first"], last_ts=a["last"], tainted_paise=traced.get((s, d), 0),
                       channels=sorted(a["ch"]), txs=a["txs"])
             for (s, d), a in agg.items() if s in set(keep) and d in set(keep)]
    times = sorted(t.ts for e in edges for t in e.txs)
    scene = GraphScene(version=key, nodes=nodes, edges=edges, focus=focus, cap=cap,
                       truncated=len(candidates) > cap, total_candidates=len(candidates),
                       time_range=[times[0], times[-1]] if times else None,
                       built_ms=round((time.perf_counter() - started) * 1000, 2), cached=False)
    if len(_cache) > 32:
        _cache.clear()
    _cache[key] = scene
    return scene


def cache_stats() -> dict[str, Any]:
    return {"entries": len(_cache), **_stats}
