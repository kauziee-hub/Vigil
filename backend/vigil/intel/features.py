"""ONE windowed per-account feature extractor, used IDENTICALLY for synthetic training worlds
(backend/ml/datagen.py) and for live inference on vigil.graph.pathgraph.GRAPH (vigil/intel/live.py).

Repairs audit findings A1/A15 (docs/ML_VALIDATION_REPORT.md §1): every feature is measured over a
window anchored at the EVALUATION time `now_t` (never at an attack start), from observed ledger
edges only. No feature reads labels, seed_role, seed_attack or anything a production system would
not have at `now_t`.

Pure python (no numpy) so the intel layer works even when ML dependencies are missing.
"""

from __future__ import annotations

import bisect
import math
from typing import Any, Iterable, Protocol, Sequence

DAY = 86400.0
WINDOW_S = 72 * 3600.0           # current window, same as RingWatch (config network.window_hours)
BASELINE_S = 30 * DAY            # behavioural baseline before the current window (baseline_tx_rate)
DRIFT_BASELINE_S = 45 * DAY      # drift baseline: > one monthly cycle, so last month's salary is inside it (v2.1)
FORWARD_S = 60 * 60.0            # "forwarded quickly" = left within 60 min of an inflow (RingWatch pass_through)
NEAR_THRESHOLD_LOW = 8_000_00    # paise; structuring band just below ₹10,000
NEAR_THRESHOLD_HIGH = 10_000_00
DORMANCY_CAP_DAYS = 400.0
AGE_CAP_DAYS = 3650.0

# Order matters: models are trained on this exact vector.
FEATURES: tuple[str, ...] = (
    # the original project's ten (features.py:217-230), now windowed
    "in_degree",               # distinct senders in window
    "out_degree",              # distinct recipients in window
    "total_in_amount",         # rupees received in window
    "total_out_amount",        # rupees sent in window
    "retention_ratio",         # max(0,(in-out)/in); 1.0 when nothing came in (nothing passed through)
    "unique_neighbors",        # distinct counterparties in window
    "unique_channels",         # distinct rails used in window (upi/imps/neft/card)
    "device_cluster_size",     # accounts bound to any of this account's devices (incl. itself)
    "transaction_count",       # postings in window (in + out)
    "account_age_days",        # at now_t
    # v2 additions (each mirrors a documented mule behaviour, all observable at now_t)
    "forwarded_fraction",      # share of window inflow value forwarded within 60 min (pass-through speed)
    "new_counterparty_ratio",  # share of window counterparties never seen before the window
    "near_threshold_outflows", # outflows in [₹8,000, ₹10,000) in window (structuring)
    "dormancy_days",           # quiet gap before the first window posting (0 if no window activity)
    "baseline_tx_rate",        # postings per 72 h over the 30-day baseline before the window
)

DRIFT_FEATURES: tuple[str, ...] = (
    "transaction_count", "unique_neighbors", "in_degree", "out_degree",
    "total_in_amount", "total_out_amount", "retention_ratio", "unique_channels",
)


class GraphSource(Protocol):
    """What the feature function needs. Edges expose .src .dst .amount_paise .t"""

    def inflows(self, account_id: str) -> Sequence[Any]: ...
    def outflows(self, account_id: str) -> Sequence[Any]: ...
    def channel(self, edge: Any) -> str: ...
    def device_cluster_size(self, account_id: str) -> int: ...
    def opened_t(self, account_id: str) -> float | None: ...
    def is_external(self, account_id: str) -> bool: ...


def zero_features() -> dict[str, float]:
    f = {k: 0.0 for k in FEATURES}
    f["retention_ratio"] = 1.0
    f["device_cluster_size"] = 1.0
    return f


def extract(src: GraphSource, account_id: str, now_t: float, window_s: float = WINDOW_S) -> dict[str, float]:
    """Windowed features for one account at evaluation time now_t."""
    if src.is_external(account_id):
        return zero_features()
    start = now_t - window_s
    base_start = start - BASELINE_S

    # one pass per direction: the window edges, and history strictly before the window (prior counterparties,
    # last activity, baseline rate). v3: was two passes; identical values.
    w_in: list[Any] = []
    w_out: list[Any] = []
    prior: set[str] = set()
    last_before: float | None = None
    baseline_n = 0
    for e in src.inflows(account_id):
        t = e.t
        if t <= start:
            prior.add(e.src)
            if last_before is None or t > last_before:
                last_before = t
            if t > base_start:
                baseline_n += 1
        elif t <= now_t:
            w_in.append(e)
    for e in src.outflows(account_id):
        t = e.t
        if t <= start:
            prior.add(e.dst)
            if last_before is None or t > last_before:
                last_before = t
            if t > base_start:
                baseline_n += 1
        elif t <= now_t:
            w_out.append(e)
    total_in = sum(e.amount_paise for e in w_in)
    total_out = sum(e.amount_paise for e in w_out)

    senders = {e.src for e in w_in}
    recipients = {e.dst for e in w_out}
    neighbours = (senders | recipients) - {account_id}

    # forwarded quickly: outflow value leaving within FORWARD_S after the most recent window inflow
    in_times = sorted(e.t for e in w_in)
    quick = 0
    if in_times:
        for e in w_out:
            i = bisect.bisect_right(in_times, e.t)
            if i and e.t - in_times[i - 1] <= FORWARD_S:
                quick += e.amount_paise
    forwarded = min(1.0, quick / total_in) if total_in else 0.0

    channels = {src.channel(e) for e in w_in} | {src.channel(e) for e in w_out}
    opened = src.opened_t(account_id)
    age_days = min(AGE_CAP_DAYS, max(0.0, (now_t - opened) / DAY)) if opened is not None else 365.0

    dormancy = 0.0
    window_times = [e.t for e in w_in] + [e.t for e in w_out]
    if window_times:
        quiet_from = last_before if last_before is not None else opened
        if quiet_from is not None:
            dormancy = min(DORMANCY_CAP_DAYS, max(0.0, (min(window_times) - quiet_from) / DAY))

    return {
        "in_degree": float(len(senders - {account_id})),
        "out_degree": float(len(recipients - {account_id})),
        "total_in_amount": total_in / 100.0,
        "total_out_amount": total_out / 100.0,
        "retention_ratio": max(0.0, (total_in - total_out) / total_in) if total_in else 1.0,
        "unique_neighbors": float(len(neighbours)),
        "unique_channels": float(len(channels)),
        "device_cluster_size": float(max(1, src.device_cluster_size(account_id))),
        "transaction_count": float(len(w_in) + len(w_out)),
        "account_age_days": round(age_days, 3),
        "forwarded_fraction": round(forwarded, 4),
        "new_counterparty_ratio": round(len(neighbours - prior) / len(neighbours), 4) if neighbours else 0.0,
        "near_threshold_outflows": float(sum(1 for e in w_out if NEAR_THRESHOLD_LOW <= e.amount_paise < NEAR_THRESHOLD_HIGH)),
        "dormancy_days": round(dormancy, 3),
        "baseline_tx_rate": round(baseline_n * (window_s / BASELINE_S), 4),
    }


def extract_all(src: GraphSource, account_ids: Iterable[str], now_t: float) -> dict[str, dict[str, float]]:
    return {a: extract(src, a, now_t) for a in account_ids}


def vector(f: dict[str, float]) -> list[float]:
    return [float(f[k]) for k in FEATURES]


def window_pairs(src: GraphSource, account_ids: Iterable[str], now_t: float,
                 window_s: float = WINDOW_S) -> set[tuple[str, str]]:
    """Distinct directed (sender, recipient) pairs with a posting inside the window, among account_ids."""
    keep = set(account_ids)
    start = now_t - window_s
    pairs: set[tuple[str, str]] = set()
    for a in keep:
        for e in src.outflows(a):
            if start < e.t <= now_t and e.dst in keep and e.dst != a:
                pairs.add((a, e.dst))
    return pairs


def in_cycle(src: GraphSource, account_id: str, now_t: float, max_hops: int = 6,
             window_s: float = WINDOW_S, budget: int = 600) -> bool:
    """Bounded search: does money leave this account and come back within the window (≤ max_hops)?"""
    start = now_t - window_s
    stack: list[tuple[str, int]] = [(account_id, 0)]
    best = {account_id: 0}
    steps = 0
    while stack and steps < budget:
        node, depth = stack.pop()
        steps += 1
        if depth >= max_hops:
            continue
        for e in src.outflows(node):
            if not (start < e.t <= now_t) or src.is_external(e.dst):
                continue
            if e.dst == account_id and depth >= 1:
                return True
            if e.dst != account_id and best.get(e.dst, max_hops + 1) > depth + 1:
                best[e.dst] = depth + 1
                stack.append((e.dst, depth + 1))
    return False


def drift_profile(src: GraphSource, account_id: str, now_t: float) -> dict[str, Any]:
    """Baseline (fifteen 72 h blocks = 45 days before the current window) vs current window, per DRIFT_FEATURE.

    Blocks that end before the account was opened are ignored, so a young account has a short
    (or empty) baseline instead of a fake 'zero activity' one.
    """
    n_blocks = int(DRIFT_BASELINE_S // WINDOW_S)
    start = now_t - WINDOW_S
    opened = src.opened_t(account_id)
    # index 0 = current window, 1..n = baseline blocks going back in time; per-block accumulators (one pass over
    # the edges; v3 — same values as collecting each block's edges first, ~2x faster on a busy shop's history)
    nb = n_blocks + 1
    n_in, n_out, t_in, t_out = [0] * nb, [0] * nb, [0] * nb, [0] * nb
    snd: list[set[str]] = [set() for _ in range(nb)]
    rcv: list[set[str]] = [set() for _ in range(nb)]
    chs: list[set[str]] = [set() for _ in range(nb)]
    channel, ceil, W = src.channel, math.ceil, WINDOW_S
    for e in src.inflows(account_id):
        t = e.t
        if t > now_t:
            continue
        k = int(ceil((now_t - t) / W)) - 1 if t < now_t else 0
        if 0 <= k <= n_blocks:
            n_in[k] += 1
            t_in[k] += e.amount_paise
            snd[k].add(e.src)
            chs[k].add(channel(e))
    for e in src.outflows(account_id):
        t = e.t
        if t > now_t:
            continue
        k = int(ceil((now_t - t) / W)) - 1 if t < now_t else 0
        if 0 <= k <= n_blocks:
            n_out[k] += 1
            t_out[k] += e.amount_paise
            rcv[k].add(e.dst)
            chs[k].add(channel(e))

    def stats(k: int) -> dict[str, float]:
        tin, tout = t_in[k], t_out[k]
        s = snd[k] - {account_id}
        r = rcv[k] - {account_id}
        return {
            "transaction_count": float(n_in[k] + n_out[k]),
            "unique_neighbors": float(len(s | r)),
            "in_degree": float(len(s)),
            "out_degree": float(len(r)),
            "total_in_amount": tin / 100.0,
            "total_out_amount": tout / 100.0,
            "retention_ratio": max(0.0, (tin - tout) / tin) if tin else 1.0,
            "unique_channels": float(len(chs[k])),
        }

    current = stats(0)
    base_rows = []
    for k in range(1, n_blocks + 1):
        block_end = start - (k - 1) * WINDOW_S
        if opened is not None and block_end <= opened:
            break
        base_rows.append(stats(k))
    mean: dict[str, float] = {}
    std: dict[str, float] = {}
    for f in DRIFT_FEATURES:
        vals = [r[f] for r in base_rows]
        if not vals:
            mean[f], std[f] = (1.0 if f == "retention_ratio" else 0.0), 0.0
            continue
        m = sum(vals) / len(vals)
        mean[f] = m
        std[f] = math.sqrt(sum((v - m) ** 2 for v in vals) / len(vals))
    return {"current": current, "baseline_mean": mean, "baseline_std": std, "baseline_blocks": len(base_rows)}
