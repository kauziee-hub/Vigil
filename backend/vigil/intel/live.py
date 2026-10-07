"""Live inference on the in-memory PathGraph — the SAME feature function and detectors as training.

`LiveSource` adapts `vigil.graph.pathgraph.GRAPH` (+ the ledger's channel column, read-only) to the
`GraphSource` protocol of vigil/intel/features.py, so `features.extract` runs unchanged on synthetic
training worlds and on the live graph.

`Snapshot` holds every detector's raw output for every account at one graph state:
  * built in full (all accounts at a fresh evaluation time) by `build()`;
  * refreshed INCREMENTALLY by `refresh()` after new postings: only accounts touched by the new edges
    (and their window counterparties) are recomputed; population statistics (early warning) and the
    GNN forward pass are recomputed over everyone because they are cheap; roles are assessed lazily.
    This keeps the payment path (`consensus.corroboration`) inside its latency budget.
Cache: `CACHE.current()` — one snapshot per graph state (GRAPH.version + edge-store identity + seed
epoch, so a reset never serves stale results), incremental between versions, full after FULL_TTL_S.
Nothing here reads `seed_role`, `seed_attack` or fraud labels.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from vigil import clock, db
from vigil.graph.pathgraph import GRAPH
from vigil.intel import drift as D
from vigil.intel import early_warning as EW
from vigil.intel import features as F
from vigil.intel import pattern_memory as PM
from vigil.intel import roles as RO
from vigil.intel import rules as R
from vigil.intel.models import STORE, gnn_input_row

FULL_TTL_S = 120.0          # a full rebuild re-anchors every window at a fresh "now"
INTEL_FAMILIES: tuple[str, ...] = ("rules", "random_forest", "gnn", "drift", "early_warning", "pattern_memory")
ROLE_MIN_FAMILIES = RO.ROLE_MIN_FAMILIES   # role gate: roles.gate (validated in ml/eval_roles_consensus.py)


# ── graph adapter ─────────────────────────────────────────────────────────
class _Channels:
    """tx_id -> channel, loaded incrementally from the ledger (read-only)."""

    def __init__(self) -> None:
        self.by_tx: dict[str, str] = {}
        self.max_seq = -1
        self.epoch: Any = None

    def sync(self, epoch: Any) -> None:
        if epoch != self.epoch:
            self.by_tx, self.max_seq, self.epoch = {}, -1, epoch
        rows = db.q("SELECT id, seq, channel FROM transactions WHERE seq > ? ORDER BY seq", (self.max_seq,))
        for r in rows:
            self.by_tx[r["id"]] = r["channel"] or "upi"
        if rows:
            self.max_seq = int(rows[-1]["seq"])


CHANNELS = _Channels()
_opened_cache: dict[tuple[str, str], float] = {}


class LiveSource:
    """vigil.intel.features.GraphSource over the live PathGraph."""

    def inflows(self, account_id: str) -> list[Any]:
        return GRAPH.in_edges.get(account_id, [])

    def outflows(self, account_id: str) -> list[Any]:
        return GRAPH.out_edges.get(account_id, [])

    def channel(self, edge: Any) -> str:
        return CHANNELS.by_tx.get(edge.tx_id, "upi")

    def device_cluster_size(self, account_id: str) -> int:
        return max(1, len(GRAPH.device_peers(account_id)))

    def opened_t(self, account_id: str) -> float | None:
        acc = GRAPH.accounts.get(account_id)
        if not acc or not acc.get("opened_at"):
            return None
        key = (account_id, acc["opened_at"])
        t = _opened_cache.get(key)
        if t is None:
            t = clock.parse(acc["opened_at"]).timestamp()
            _opened_cache[key] = t
        return t

    def is_external(self, account_id: str) -> bool:
        if account_id.startswith("ext:"):
            return True
        return (GRAPH.accounts.get(account_id) or {}).get("kind") == "external"


SRC = LiveSource()


def graph_key() -> tuple[int, int, int, str]:
    """(GRAPH.version, ledger max seq, edge-store identity, seed epoch).

    key[2:] is the EPOCH: it changes when the graph is reloaded or the demo is reset, and then only a
    full rebuild is valid. Within an epoch, new postings / devices / accounts are applied incrementally.
    """
    try:
        seeded = db.get_meta("seeded_at", "") or ""
        max_seq = int(db.scalar("SELECT COALESCE(MAX(seq), -1) FROM transactions"))
    except Exception:
        seeded, max_seq = "", -1
    return (GRAPH.version, max_seq, id(GRAPH.in_edges), seeded)


def known(account_id: str) -> bool:
    return account_id in GRAPH.accounts


def scored_ids() -> list[str]:
    return sorted(a for a in GRAPH.accounts if not SRC.is_external(a))


_EXT_CACHE: dict[str, Any] = {"key": None, "ids": []}


def external_ids() -> list[str]:
    """External counterparties (cached per graph shape: accounts / edge-list owners only grow within an epoch)."""
    key = (id(GRAPH.in_edges), len(GRAPH.accounts), len(GRAPH.out_edges), len(GRAPH.in_edges))
    if _EXT_CACHE["key"] != key:
        ext = {a for a in GRAPH.accounts if SRC.is_external(a)}
        for edges in (GRAPH.out_edges, GRAPH.in_edges):
            ext |= {a for a in edges if a.startswith("ext:")}
        _EXT_CACHE.update(key=key, ids=sorted(ext))
    return list(_EXT_CACHE["ids"])


# ── snapshot ──────────────────────────────────────────────────────────────
@dataclass
class Snapshot:
    key: tuple[int, int, int, str]
    now_t: float
    as_of: str
    built_ms: float = 0.0
    mode: str = "full"                                  # full | incremental
    full_t: float = 0.0                                 # evaluation time of the last FULL rebuild in this chain
    ids: list[str] = field(default_factory=list)
    feats: dict[str, dict[str, float]] = field(default_factory=dict)
    ctx: dict[str, dict[str, Any]] = field(default_factory=dict)
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    ew: dict[str, dict[str, Any]] = field(default_factory=dict)
    ew_stats: dict[str, float] = field(default_factory=dict)
    drift: dict[str, dict[str, Any]] = field(default_factory=dict)
    patterns: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    rf: dict[str, tuple[float, float]] = field(default_factory=dict)       # account -> (raw, calibrated)
    gnn: dict[str, tuple[float, float]] = field(default_factory=dict)
    flags: dict[str, dict[str, bool]] = field(default_factory=dict)        # account -> family -> flagged
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)         # filled lazily by role()
    gnn_rows: dict[str, list[float]] = field(default_factory=dict)         # raw GNN input row per account
    n_edges: dict[str, int] = field(default_factory=dict)                  # account -> in+out postings seen
    status: dict[str, str] = field(default_factory=dict)                   # family -> ok | unavailable
    errors: dict[str, str] = field(default_factory=dict)
    views: dict[str, Any] = field(default_factory=dict)                    # derived read models cached per snapshot
    pairs_t: dict[tuple[str, str], float] = field(default_factory=dict)    # window graph: (src, dst) -> latest posting t
    pairs_version: int = 0                                                 # bumps when the window pair SET changes
    gnn_graph: Any = None                                                  # (pairs_version, n_nodes, edge index) cache
    ew_cache: dict[str, Any] = field(default_factory=dict)                 # early warning: per-account static parts
    recomputed: list[str] = field(default_factory=list)                    # incremental: accounts fully re-measured
    ctx_refreshed: list[str] = field(default_factory=list)                 # incremental: neighbourhood context only


def thresholds() -> dict[str, float]:
    STORE.load()
    pm_meta = _pm_meta()
    return {"random_forest": float(STORE.rf_meta.get("threshold", 0.5)),
            "gnn": float(STORE.gnn_meta.get("threshold", 0.5)),
            "pattern_memory": float(pm_meta.get("threshold", 0.6))}


_PM_META: dict[str, Any] | None = None


def _pm_meta() -> dict[str, Any]:
    global _PM_META
    if _PM_META is None:
        import json
        try:
            _PM_META = json.loads((PM.MODELS_DIR / "pattern_memory_meta_v2.json").read_text(encoding="utf-8"))
        except Exception:
            _PM_META = {}
    return _PM_META


def _per_account(snap: Snapshot, ids: list[str]) -> None:
    """Per-account detectors that only need the account's own (and its counterparties') features."""
    fo = lambda a: snap.feats.get(a) or F.zero_features()  # noqa: E731
    for a in ids:
        f = snap.feats[a]
        snap.ctx[a] = PM.context(SRC, a, snap.now_t, fo)
        snap.rules[a] = R.evaluate(f)
        snap.drift[a] = D.assess(F.drift_profile(SRC, a, snap.now_t))
        snap.patterns[a] = PM.match(PM.signature(f, snap.ctx[a]), top=3)


def _rf(snap: Snapshot, ids: list[str]) -> None:
    if not ids:
        return
    try:
        raw = STORE.rf_raw([F.vector(snap.feats[a]) for a in ids])
    except Exception as exc:
        raw, snap.errors["random_forest"] = None, f"{type(exc).__name__}: {exc}"
    if raw is None:
        snap.status["random_forest"] = "unavailable"
        return
    snap.status["random_forest"] = "ok"
    for a, p in zip(ids, raw):
        snap.rf[a] = (p, STORE.calibrate(p, "random_forest"))


def _window_pairs_t(nodes: list[str], now_t: float) -> dict[tuple[str, str], float]:
    """(sender, recipient) -> latest posting time inside the window, among `nodes`. Same pair SET as
    features.window_pairs (the training-time function); the latest time lets refresh() expire pairs exactly."""
    keep = set(nodes)
    start = now_t - F.WINDOW_S
    out: dict[tuple[str, str], float] = {}
    for a in keep:
        for e in SRC.outflows(a):
            if start < e.t <= now_t and e.dst in keep and e.dst != a:
                k = (a, e.dst)
                if e.t > out.get(k, -1.0):
                    out[k] = e.t
    return out


def _gnn(snap: Snapshot) -> None:
    """Whole-graph forward pass on the 72 h window graph (externals as indicator nodes, as in training).

    The window pair set is maintained incrementally (`snap.pairs_t`); the edge index (with its per-destination
    segments) is rebuilt only when the pair SET or the node list changes, which a habitual payment does not do.
    """
    try:
        ext = external_ids()
        nodes = ext + snap.ids
        if not snap.pairs_t:
            snap.pairs_t = _window_pairs_t(nodes, snap.now_t)
            snap.pairs_version += 1
        for a in snap.ids:
            if a not in snap.gnn_rows:
                snap.gnn_rows[a] = gnn_input_row(snap.feats[a], False)
        ext_row = gnn_input_row(None, True)
        rows = [ext_row for _ in ext] + [snap.gnn_rows[a] for a in snap.ids]
        gkey = (snap.pairs_version, tuple(ext), len(snap.ids))
        if snap.gnn_graph is None or snap.gnn_graph[0] != gkey:
            index = {a: i for i, a in enumerate(nodes)}
            pairs = sorted((index[s], index[d]) for s, d in snap.pairs_t if s in index and d in index)
            snap.gnn_graph = (gkey, STORE.gnn_graph(len(nodes), pairs))
        out = STORE.gnn_scores(rows, None, prepared=snap.gnn_graph[1])
    except Exception as exc:
        out, snap.errors["gnn"] = None, f"{type(exc).__name__}: {exc}"
    if out is None:
        snap.status["gnn"] = "unavailable"
        snap.gnn = {}
        return
    snap.status["gnn"] = "ok"
    n_ext = len(nodes) - len(snap.ids)
    snap.gnn = {a: (p, STORE.calibrate(p, "gnn")) for a, p in zip(snap.ids, out[n_ext:])}


def _population(snap: Snapshot) -> None:
    snap.ew, snap.ew_stats, snap.ew_cache = EW.evaluate_population_cached(snap.feats, snap.ew_cache)
    thr = thresholds()
    t_pm, t_rf, t_gnn = thr["pattern_memory"], thr["random_forest"], thr["gnn"]
    snap.roles = {}
    rules, ew, drift, patterns, rf, gnn = snap.rules, snap.ew, snap.drift, snap.patterns, snap.rf, snap.gnn
    flags = {}
    for a in snap.ids:
        pats = patterns.get(a)
        fl = {
            "rules": bool(rules[a]["flagged"]),
            "early_warning": bool(ew[a]["flagged"]),
            "drift": bool(drift[a]["flagged"]),
            "pattern_memory": (pats[0]["similarity"] if pats else 0.0) >= t_pm,
        }
        v = rf.get(a)
        if v is not None:
            fl["random_forest"] = v[1] >= t_rf
        v = gnn.get(a)
        if v is not None:
            fl["gnn"] = v[1] >= t_gnn
        flags[a] = fl
    snap.flags = flags


# ── roles (API path only; the payment path never needs them) ──────────────
def role_flags(snap: Snapshot) -> dict[str, dict[str, bool]]:
    """Account-level family flags for the role gate (roles.gate), cached per snapshot.

    The six intel families come from the snapshot. The registry and RingWatch are evaluated with the SAME
    functions as the AccountIntel detector list (consensus.external_result / ringwatch_result): the registry
    for every account (one indexed lookup each), RingWatch only where it can change the gate's answer: any
    account that already has a flag or is in the RingWatch scan (an account with no other flag would have
    at most one, which never passes the >= 2-family gate).
    """
    cached = snap.views.get("role_flags")
    if cached is not None:
        return cached
    from vigil.intel import consensus as C
    out = {a: dict(snap.flags[a]) for a in snap.ids}
    for a in snap.ids:
        out[a]["external"] = bool(C.external_result(a, snap.as_of).flagged)
    candidates = {a for a in snap.ids if any(out[a].values())}
    try:
        from vigil.risk import ringwatch
        candidates |= {r["account_id"] for r in ringwatch.scan(min_score=C.RINGWATCH_FLAG)} & set(out)
    except Exception:
        pass
    for a in sorted(candidates):
        rw = C.ringwatch_result(a, snap.as_of)
        out[a]["ringwatch"] = bool(rw.flagged and rw.status == "ok")
    snap.views["role_flags"] = out
    return out


def role_network(snap: Snapshot) -> set[str]:
    """Accounts that pass the role gate: the 'flagged network' that entry / exit positions refer to."""
    cached = snap.views.get("role_network")
    if cached is None:
        cached = {a for a, fl in role_flags(snap).items() if RO.gate(fl)[0]}
        snap.views["role_network"] = cached
    return cached


def role(snap: Snapshot, account_id: str) -> dict[str, Any]:
    """Role assessment (lazy, cached per snapshot)."""
    r = snap.roles.get(account_id)
    if r is None:
        r = RO.assess(SRC, account_id, snap.now_t, snap.feats[account_id], role_network(snap),
                      role_flags(snap)[account_id], bool(snap.ctx[account_id]["in_cycle"]))
        snap.roles[account_id] = r
    return r


def build(now_t: float | None = None) -> Snapshot:
    """Full rebuild: every account, every detector, at evaluation time now_t."""
    started = time.perf_counter()
    key = graph_key()
    CHANNELS.sync(key[2:])
    now_t = clock.now().timestamp() if now_t is None else now_t
    snap = Snapshot(key=key, now_t=now_t, as_of=clock.iso(_dt(now_t)), full_t=now_t)
    snap.ids = scored_ids()
    snap.feats = {a: F.extract(SRC, a, now_t) for a in snap.ids}
    snap.n_edges = {a: _edge_count(a) for a in snap.ids}
    _per_account(snap, snap.ids)
    _rf(snap, snap.ids)
    _gnn(snap)
    _population(snap)
    snap.built_ms = round((time.perf_counter() - started) * 1000, 2)
    return snap


def _fast(f: dict[str, float]) -> bool:
    """The neighbour property pattern_memory.context counts (fast_neighbor_share)."""
    return f["forwarded_fraction"] >= 0.7 and f["total_in_amount"] > 0


def _window_cps(a: str, start: float, now_t: float) -> set[str]:
    return {e.src for e in SRC.inflows(a) if start < e.t <= now_t} | {e.dst for e in SRC.outflows(a) if start < e.t <= now_t}


def _new_edges(dirty: set[str], after_seq: int) -> list[Any]:
    """Edges appended to the graph after ledger seq `after_seq`, found from the tails of the dirty accounts' lists."""
    seen: dict[str, Any] = {}
    for a in dirty:
        for lst in (GRAPH.out_edges.get(a, ()), GRAPH.in_edges.get(a, ())):
            for e in reversed(lst):
                if e.seq <= after_seq:
                    break
                seen[e.tx_id] = e
    return sorted(seen.values(), key=lambda e: e.seq)


def _reach(start_node: str, forward: bool, start: float, now_t: float, max_hops: int, budget: int = 600) -> set[str]:
    """Internal accounts reachable from start_node along window edges (forward = outflows) within max_hops."""
    seen = {start_node: 0}
    queue = [start_node]
    steps = 0
    while queue and steps < budget:
        node = queue.pop(0)
        steps += 1
        depth = seen[node]
        if depth >= max_hops:
            continue
        for e in (SRC.outflows(node) if forward else SRC.inflows(node)):
            nxt = e.dst if forward else e.src
            if not (start < e.t <= now_t) or SRC.is_external(nxt) or nxt in seen:
                continue
            seen[nxt] = depth + 1
            queue.append(nxt)
    return set(seen)


def _cycle_candidates(edges: list[Any], start: float, now_t: float) -> set[str]:
    """Accounts whose in_cycle can change because of the new edges: a new cycle through s -> d passes through
    accounts reachable from d that also reach s (bounded like features.in_cycle: <= 6 hops)."""
    out: set[str] = set()
    for e in edges:
        if SRC.is_external(e.src) or SRC.is_external(e.dst) or e.src == e.dst:
            continue
        fwd = _reach(e.dst, True, start, now_t, 5)
        if len(fwd) <= 1:
            continue                       # d moves no money to another internal account: no new cycle
        out |= fwd & _reach(e.src, False, start, now_t, 5)
    return out


def refresh(prev: Snapshot, now_t: float | None = None) -> Snapshot:
    """Incremental update after new postings / devices / accounts (same evaluation-time semantics).

    Fully re-measured (features, rules, drift, pattern memory, RF): accounts touched by edges newer than the
    previous snapshot, new accounts, accounts whose device cluster changed. Neighbourhood context only
    (pattern_memory.context: fast-forwarding neighbours, in_cycle): the window counterparties of a re-measured
    account whose fast-forwarding property changed, and accounts a new edge may have put on a cycle — the only
    parts of an untouched account that a new edge elsewhere can change. Population statistics (early warning),
    family flags and the GNN pass are recomputed for everyone (the GNN's window pair set incrementally); roles
    are re-assessed lazily. Accounts untouched by any change keep features measured at the previous evaluation
    time; a full rebuild (API path, after FULL_TTL_S) re-anchors them. v3: counterparties used to be fully
    re-measured, ~75 accounts per posting to a busy shop on world v3 (the hook's latency budget).
    """
    started = time.perf_counter()
    key = graph_key()
    CHANNELS.sync(key[2:])
    now_t = clock.now().timestamp() if now_t is None else now_t
    start = now_t - F.WINDOW_S
    snap = Snapshot(key=key, now_t=now_t, as_of=clock.iso(_dt(now_t)), mode="incremental", full_t=prev.full_t)
    snap.ids = prev.ids if len(prev.ids) == _n_scored() else scored_ids()
    snap.n_edges = {a: _edge_count(a) for a in snap.ids}
    # device / account changes bump GRAPH.version without a ledger posting: only then re-check device clusters
    devices_changed = (key[0] - prev.key[0]) != (key[1] - prev.key[1])
    dirty: set[str] = set()
    for a in snap.ids:
        if a not in prev.feats or snap.n_edges[a] != prev.n_edges.get(a) or (
                devices_changed and SRC.device_cluster_size(a) != int(prev.feats[a]["device_cluster_size"])):
            dirty.add(a)
    new_edges = _new_edges(dirty | {e for e in external_ids()}, prev.key[1])
    recompute = sorted(dirty)
    snap.feats = dict(prev.feats)
    for a in recompute:
        snap.feats[a] = F.extract(SRC, a, now_t)
    ctx_only: set[str] = set()
    for a in recompute:
        if a in prev.feats and _fast(prev.feats[a]) != _fast(snap.feats[a]):
            ctx_only |= _window_cps(a, start, now_t)
    ctx_only |= _cycle_candidates(new_edges, start, now_t)
    ctx_only = {a for a in ctx_only if a in snap.feats and a not in dirty and not SRC.is_external(a)}
    for attr in ("ctx", "rules", "drift", "patterns", "rf", "gnn_rows"):
        m = dict(getattr(prev, attr))
        for a in recompute:
            m.pop(a, None)
        setattr(snap, attr, m)
    snap.status = dict(prev.status)
    _per_account(snap, recompute)
    fo = lambda a: snap.feats.get(a) or F.zero_features()  # noqa: E731
    for a in sorted(ctx_only):
        snap.ctx[a] = PM.context(SRC, a, now_t, fo)
        snap.patterns[a] = PM.match(PM.signature(snap.feats[a], snap.ctx[a]), top=3)
    snap.recomputed, snap.ctx_refreshed = recompute, sorted(ctx_only)
    _rf(snap, recompute if prev.status.get("random_forest") == "ok" else snap.ids)
    # window graph for the GNN: add the new pairs, expire pairs whose latest posting left the window
    pairs = dict(prev.pairs_t)
    changed = False
    nodes = set(snap.ids) | set(external_ids())
    for e in new_edges:
        if e.src in nodes and e.dst in nodes and e.src != e.dst and start < e.t <= now_t:
            k = (e.src, e.dst)
            if k not in pairs:
                changed = True
            if e.t > pairs.get(k, -1.0):
                pairs[k] = e.t
    if pairs and min(pairs.values()) <= start:
        pairs = {k: t for k, t in pairs.items() if t > start}
        changed = True
    snap.pairs_t, snap.pairs_version = pairs, prev.pairs_version + (1 if changed else 0)
    snap.gnn_graph = prev.gnn_graph
    snap.ew_cache = prev.ew_cache
    if not pairs and prev.pairs_t:
        snap.pairs_version += 1
    _gnn(snap)
    _population(snap)
    snap.built_ms = round((time.perf_counter() - started) * 1000, 2)
    return snap


_SCORED_N: dict[str, Any] = {"key": None, "n": 0}


def _n_scored() -> int:
    """Number of scored (non-external) accounts, cached per graph account count."""
    n_all = len(GRAPH.accounts)
    if _SCORED_N["key"] != n_all:
        _SCORED_N.update(key=n_all, n=sum(1 for a in GRAPH.accounts if not SRC.is_external(a)))
    return _SCORED_N["n"]


def _edge_count(account_id: str) -> int:
    return len(GRAPH.in_edges.get(account_id, ())) + len(GRAPH.out_edges.get(account_id, ()))


def _dt(t: float):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, tz=timezone.utc)


# ── cache ─────────────────────────────────────────────────────────────────
class _Cache:
    def __init__(self) -> None:
        self.snap: Snapshot | None = None
        self.stats = {"full": 0, "incremental": 0, "hits": 0}

    def clear(self) -> None:
        self.snap = None

    def current(self, allow_full: bool = True) -> Snapshot | None:
        """Snapshot for the current graph state (cached per graph version).

        * same graph state -> cached snapshot;
        * new postings / devices / accounts since the cached snapshot -> incremental refresh;
        * no snapshot, a reset (new seed epoch), or (allow_full only) a snapshot older than FULL_TTL_S
          -> full rebuild. allow_full=False (payment path) never rebuilds in full while any snapshot of
          the same epoch exists, and returns None on a cold cache.
        """
        key = graph_key()
        snap = self.snap
        now = clock.now().timestamp()
        same_epoch = snap is not None and snap.key[2:] == key[2:]
        expired = snap is not None and allow_full and now - snap.full_t >= FULL_TTL_S
        if same_epoch and not expired:
            if snap.key == key:
                self.stats["hits"] += 1
                return snap
            self.snap = refresh(snap)
            self.stats["incremental"] += 1
            return self.snap
        if not allow_full:
            return None
        self.snap = build()
        self.stats["full"] += 1
        return self.snap


CACHE = _Cache()
