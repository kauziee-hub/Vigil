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
ROLE_MIN_FAMILIES = 2       # same rule as the validated role experiment (ml/train_all.py::role_accuracy)


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


def graph_key() -> tuple[int, int, str]:
    """Identifies one graph state: version, the edge-store identity (changes on reload) and the seed epoch."""
    try:
        seeded = db.get_meta("seeded_at", "") or ""
    except Exception:
        seeded = ""
    return (GRAPH.version, id(GRAPH.in_edges), seeded)


def known(account_id: str) -> bool:
    return account_id in GRAPH.accounts


def scored_ids() -> list[str]:
    return sorted(a for a in GRAPH.accounts if not SRC.is_external(a))


def external_ids() -> list[str]:
    ext = {a for a in GRAPH.accounts if SRC.is_external(a)}
    for edges in (GRAPH.out_edges, GRAPH.in_edges):
        ext |= {a for a in edges if a.startswith("ext:")}
    return sorted(ext)


# ── snapshot ──────────────────────────────────────────────────────────────
@dataclass
class Snapshot:
    key: tuple[int, int, str]
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
    suspicious: set[str] = field(default_factory=set)                      # >= ROLE_MIN_FAMILIES intel flags
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)         # filled lazily by role()
    gnn_rows: dict[str, list[float]] = field(default_factory=dict)         # raw GNN input row per account
    n_edges: dict[str, int] = field(default_factory=dict)                  # account -> in+out postings seen
    status: dict[str, str] = field(default_factory=dict)                   # family -> ok | unavailable
    errors: dict[str, str] = field(default_factory=dict)


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


def _gnn(snap: Snapshot) -> None:
    """Whole-graph forward pass on the 72 h window graph (externals as indicator nodes, as in training)."""
    try:
        ext = external_ids()
        nodes = ext + snap.ids
        index = {a: i for i, a in enumerate(nodes)}
        pairs = sorted((index[s], index[d]) for s, d in F.window_pairs(SRC, nodes, snap.now_t))
        for a in snap.ids:
            if a not in snap.gnn_rows:
                snap.gnn_rows[a] = gnn_input_row(snap.feats[a], False)
        ext_row = gnn_input_row(None, True)
        rows = [ext_row for _ in ext] + [snap.gnn_rows[a] for a in snap.ids]
        out = STORE.gnn_scores(rows, pairs)
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
    snap.ew, snap.ew_stats = EW.evaluate_population(snap.feats)
    thr = thresholds()
    snap.suspicious = set()
    snap.roles = {}
    for a in snap.ids:
        top = snap.patterns[a][0]["similarity"] if snap.patterns.get(a) else 0.0
        fl = {
            "rules": bool(snap.rules[a]["flagged"]),
            "early_warning": bool(snap.ew[a]["flagged"]),
            "drift": bool(snap.drift[a]["flagged"]),
            "pattern_memory": top >= thr["pattern_memory"],
        }
        if a in snap.rf:
            fl["random_forest"] = snap.rf[a][1] >= thr["random_forest"]
        if a in snap.gnn:
            fl["gnn"] = snap.gnn[a][1] >= thr["gnn"]
        snap.flags[a] = fl
        if sum(fl.values()) >= ROLE_MIN_FAMILIES:
            snap.suspicious.add(a)


def role(snap: Snapshot, account_id: str) -> dict[str, Any]:
    """Role assessment (lazy: the payment path never needs it)."""
    r = snap.roles.get(account_id)
    if r is None:
        r = RO.assess(SRC, account_id, snap.now_t, snap.feats[account_id], snap.suspicious,
                      account_id in snap.suspicious, bool(snap.ctx[account_id]["in_cycle"]))
        snap.roles[account_id] = r
    return r


def build(now_t: float | None = None) -> Snapshot:
    """Full rebuild: every account, every detector, at evaluation time now_t."""
    started = time.perf_counter()
    key = graph_key()
    CHANNELS.sync(key[1:])
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


def refresh(prev: Snapshot, now_t: float | None = None) -> Snapshot:
    """Incremental update after new postings / devices / accounts (same evaluation-time semantics).

    Recomputed: accounts touched by edges newer than the previous snapshot, new accounts, accounts whose
    device cluster changed, and the window counterparties of all of those (their pass-through / cycle
    context can change). Population statistics (early warning) and the GNN pass are recomputed for
    everyone; roles are re-assessed lazily. Accounts far from any change keep features measured at the
    previous evaluation time; a full rebuild (API path, after FULL_TTL_S) re-anchors them.
    """
    started = time.perf_counter()
    key = graph_key()
    CHANNELS.sync(key[1:])
    now_t = clock.now().timestamp() if now_t is None else now_t
    snap = Snapshot(key=key, now_t=now_t, as_of=clock.iso(_dt(now_t)), mode="incremental", full_t=prev.full_t)
    snap.ids = scored_ids()
    snap.n_edges = {a: _edge_count(a) for a in snap.ids}
    dirty: set[str] = set()
    for a in snap.ids:
        if a not in prev.feats or snap.n_edges[a] != prev.n_edges.get(a) \
                or SRC.device_cluster_size(a) != int(prev.feats[a]["device_cluster_size"]):
            dirty.add(a)
    # counterparties of changed accounts (window), so their context is re-measured too
    start = now_t - F.WINDOW_S
    ring: set[str] = set()
    for a in dirty:
        ring |= {e.src for e in SRC.inflows(a) if e.t > start} | {e.dst for e in SRC.outflows(a) if e.t > start}
    redo = (dirty | ring) & set(snap.ids)
    recompute = sorted(redo)
    keep = [a for a in snap.ids if a not in redo]
    snap.feats = {a: prev.feats[a] for a in keep}
    for a in recompute:
        snap.feats[a] = F.extract(SRC, a, now_t)
    for attr in ("ctx", "rules", "drift", "patterns", "rf", "gnn_rows"):
        src_map = getattr(prev, attr)
        setattr(snap, attr, {a: src_map[a] for a in keep if a in src_map})
    snap.status = dict(prev.status)
    _per_account(snap, recompute)
    _rf(snap, recompute if prev.status.get("random_forest") == "ok" else snap.ids)
    _gnn(snap)
    _population(snap)
    snap.built_ms = round((time.perf_counter() - started) * 1000, 2)
    return snap


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
        same_epoch = snap is not None and snap.key[1:] == key[1:]
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
