"""Pattern memory: structural signatures of the ten known patterns vs an account's current neighbourhood.

Repairs audit A11: the original built signatures at RUNTIME from `is_fraud == 1` nodes (ground truth).
Here prototypes are built OFFLINE from training worlds only (ml/train_all.py) and versioned in
backend/models/pattern_memory_v2.json. At runtime only observed structure is compared, never labels.
Output wording: structural SIMILARITY to a known pattern, not criminal attribution.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

from vigil.intel.features import WINDOW_S, GraphSource, in_cycle

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
NOTE = "Structural similarity to a known pattern — not criminal attribution."
SIG_DIMS: tuple[str, ...] = (
    "log_in_degree", "log_out_degree", "retention_ratio", "forwarded_fraction", "new_counterparty_ratio",
    "log_near_threshold", "log_device_cluster", "log_age_days", "log_dormancy_days", "unique_channels",
    "in_cycle", "fast_neighbor_share", "log_transaction_count",
)
FLOORS = {"retention_ratio": 0.15, "forwarded_fraction": 0.15, "new_counterparty_ratio": 0.15,
          "unique_channels": 0.6, "in_cycle": 0.3, "fast_neighbor_share": 0.2}
DEFAULT_FLOOR = 0.35
TEMPERATURE = 2.0

PATTERNS = {
    "fan_in": ("Rapid Fan-In / Pass-Through", "Many first-time senders into one young account that forwards most of it within minutes."),
    "fan_out": ("Fan-Out Distribution", "A freshly funded account pays many new recipients in a short burst."),
    "circular": ("Circular Ring", "Money leaves and returns to the same account through a short loop."),
    "velocity_chain": ("Velocity Chain", "Funds hop through a line of accounts, each forwarding within minutes."),
    "cross_channel": ("Cross-Channel Burst", "One hub moves money in and out across several payment rails within minutes."),
    "shared_device": ("Shared-Device Cluster", "Several young accounts on one device collect and consolidate."),
    "behavioural_drift": ("Behavioural Drift / Activation", "An established account suddenly pays many new counterparties and stops retaining money."),
    "volume_spike": ("Early Volume Spike", "A days-old account with heavy volume in and out."),
    "smurfing": ("Smurfing / Structuring Cluster", "Money split into many transfers just under a reporting-style threshold."),
    "dormant": ("Dormant Activation", "A long-quiet account receives and empties a large sum."),
}
_memory: dict[str, Any] | None = None


def context(src: GraphSource, account_id: str, now_t: float,
            features_of: Callable[[str], dict[str, float]]) -> dict[str, Any]:
    """Neighbourhood facts used by the signature (and by role assessment)."""
    start = now_t - WINDOW_S
    cps = {e.src for e in src.inflows(account_id) if start < e.t <= now_t}
    cps |= {e.dst for e in src.outflows(account_id) if start < e.t <= now_t}
    cps = sorted(c for c in cps if c != account_id and not src.is_external(c))
    fast = 0
    for c in cps:
        fc = features_of(c)
        if fc["forwarded_fraction"] >= 0.7 and fc["total_in_amount"] > 0:
            fast += 1
    return {"in_cycle": in_cycle(src, account_id, now_t), "fast_neighbor_share": round(fast / len(cps), 4) if cps else 0.0,
            "internal_counterparties": cps}


def signature(f: dict[str, float], ctx: dict[str, Any]) -> list[float]:
    l1p = math.log1p
    return [
        l1p(f["in_degree"]), l1p(f["out_degree"]), f["retention_ratio"], f["forwarded_fraction"],
        f["new_counterparty_ratio"], l1p(f["near_threshold_outflows"]), l1p(f["device_cluster_size"] - 1),
        l1p(f["account_age_days"]), l1p(f["dormancy_days"]), min(f["unique_channels"], 5.0),
        1.0 if ctx["in_cycle"] else 0.0, ctx["fast_neighbor_share"], l1p(f["transaction_count"]),
    ]


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def build(sigs_by_family: dict[str, list[list[float]]], version: str, provenance: dict[str, Any]) -> dict[str, Any]:
    protos = []
    for fam in PATTERNS:
        rows = sigs_by_family.get(fam, [])
        if not rows:
            continue
        centre, scale = [], []
        for d, dim in enumerate(SIG_DIMS):
            col = [r[d] for r in rows]
            m = _median(col)
            mad = _median([abs(v - m) for v in col])
            centre.append(round(m, 4))
            scale.append(round(max(FLOORS.get(dim, DEFAULT_FLOOR), 1.4826 * mad), 4))
        name, desc = PATTERNS[fam]
        protos.append({"signature_id": f"sig-{fam}", "family": fam, "name": name, "description": desc,
                       "centre": centre, "scale": scale, "n_examples": len(rows)})
    return {"version": version, "dims": list(SIG_DIMS), "temperature": TEMPERATURE, "note": NOTE,
            "built_from": provenance, "prototypes": protos}


def memory() -> dict[str, Any] | None:
    global _memory
    if _memory is None:
        try:
            _memory = json.loads((MODELS_DIR / "pattern_memory_v2.json").read_text(encoding="utf-8"))
        except Exception:
            _memory = {}
    return _memory or None


def set_memory(m: dict[str, Any] | None) -> None:
    global _memory
    _memory = m


def match(sig: list[float], mem: dict[str, Any] | None = None, top: int = 3) -> list[dict[str, Any]]:
    mem = mem or memory()
    if not mem:
        return []
    temp = float(mem.get("temperature", TEMPERATURE))
    out = []
    for p in mem["prototypes"]:
        dist = 0.0
        for s, c, k in zip(sig, p["centre"], p["scale"]):
            z = (s - c) / k
            dist += min(z * z, 25.0)
        dist /= len(sig)
        out.append({"signature_id": p["signature_id"], "name": p["name"], "description": p["description"],
                    "similarity": round(math.exp(-0.5 * dist / temp), 4), "family": p["family"], "note": NOTE})
    out.sort(key=lambda x: (-x["similarity"], x["signature_id"]))
    return out[:top]
