"""Live-world (world v3) behavioural acceptance checks for the live detection stream. Not metrics.

    cd backend
    <venv>/python ml/eval_live_world.py            # ~5 min; writes models/live_world_v3.json
    <venv>/python ml/eval_live_world.py --quick    # 0 / 150 ambient postings, attacks unchanged; writes nothing

Runs in a throw-away database (like the tests). EVALUATION CODE: it reads `seed_role` (to pick ordinary accounts)
and the simulator's ground-truth mule lists (`vigil.sim.runs.ground_truth_mules`, via the AttackRun record);
nothing on the detection path does.

1. Ambient: a freshly seeded world v3, the live stream warm, then the ambient stream's own tick (`ambient._tick`,
   routine-preserving person-to-merchant payments through the full payment pipeline) until 600 and 1800 postings.
   At 0 / 600 / 1800: live statuses of ordinary (`legit`) accounts, accounts flagged by >= 1 / >= 2 detector
   families, and the lead's check (drift HIGH, early warning, calibrated RF or GNN >= 0.5); hook latency.
2. Attacks: for s2 and each of the ten attack scenarios, a fresh seed, the stream warm, then `scenarios.run_sync`
   (all steps back to back, evaluated as an AttackRun by vigil.sim.runs). Recorded: detected / warned / missed
   injected accounts, false positives, the attack posting after which the first injected account was warned /
   detected (from the live events themselves), compute latency from the first attack posting (sync run: no step
   delays — the live UI adds STEP_DELAY_S between steps), and each injected account's final status / role /
   model evidence / flagging families.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
OUT = BACKEND / "models" / "live_world_v3.json"
LABEL = "SIMULATED live world v3 — behavioural acceptance checks of the live stream, not accuracy metrics."
SCENARIOS = ["s2", "atk_fan_in", "atk_fan_out", "atk_circular", "atk_velocity_chain", "atk_cross_channel",
             "atk_shared_device", "atk_behavioural_drift", "atk_volume_spike", "atk_smurfing", "atk_dormant"]


def _isolate() -> None:
    tmp = tempfile.mkdtemp(prefix="vigil-eval-live-")
    os.environ["VIGIL_DB_PATH"] = os.path.join(tmp, "eval.db")
    os.environ["VIGIL_AMBIENT"] = "0"
    os.environ["VIGIL_PAYMENT_PROVIDER"] = "mock"


def _pct(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(q * (len(s) - 1) + 0.5))], 2)


def _latency(vals: list[float]) -> dict[str, Any]:
    return {"n": len(vals), "p50": _pct(vals, 0.5), "p95": _pct(vals, 0.95), "max": round(max(vals), 2) if vals else None,
            "mean": round(statistics.mean(vals), 2) if vals else None}


def _fresh_world() -> None:
    from vigil.graph.pathgraph import GRAPH
    from vigil.intel import live
    from vigil.intel import stream as S
    from vigil.sim import seed
    seed.seed()
    GRAPH.load()
    live.CACHE.clear()
    S.status_map()                      # warm: full snapshot + baseline statuses for this world


def _ordinary() -> list[str]:
    from vigil import db
    return [r["id"] for r in db.q("SELECT id FROM accounts WHERE kind = 'customer' AND seed_role = 'legit' "
                                  "AND is_demo_customer = 0 ORDER BY id")]


def ambient_checkpoint(n: int) -> dict[str, Any]:
    from vigil import db
    from vigil.intel import live, service
    from vigil.intel import stream as S
    from vigil.sim import ambient
    sm = S.status_map()
    snap = live.CACHE.current(allow_full=False) or live.CACHE.current()
    ordinary = _ordinary()
    counts: dict[str, int] = {}
    for a in ordinary:
        counts[sm[a]["status"]] = counts.get(sm[a]["status"], 0) + 1
    warned = {a: {"status": sm[a]["status"], "reason": sm[a]["reason"]} for a in ordinary
              if sm[a]["status"] in ("early_warning", "flagged")}
    fam = {a: [f for f, v in (snap.flags.get(a) or {}).items() if v] for a in ordinary if a in snap.flags}
    legit_all = [r["id"] for r in db.q("SELECT id FROM accounts WHERE seed_role = 'legit' AND kind = 'customer'")]
    scores = service.scores()["scores"]
    lead_check = sorted(a for a in legit_all if a in scores and (
        scores[a]["drift_level"] == "HIGH" or scores[a]["early_warning"] or (scores[a]["rf"] or 0) >= 0.5
        or (scores[a]["gnn"] or 0) >= 0.5))
    return {"ambient_postings": ambient.STATE["count"], "target": n, "ordinary_accounts": len(ordinary),
            "status_counts": dict(sorted(counts.items())), "ordinary_warned_or_flagged": warned,
            "ordinary_with_ge1_family": sorted(a for a, f in fam.items() if f),
            "ordinary_with_ge1_family_by_family": {f: sum(1 for x in fam.values() if f in x)
                                                   for f in sorted({f for x in fam.values() for f in x})},
            "ordinary_with_ge2_families": {a: f for a, f in fam.items() if len(f) >= 2},
            "lead_check_legit_flagged": lead_check,
            "hook_latency_ms_since_last_checkpoint": _latency(list(S.STATE.latencies))}


def run_ambient(targets: list[int]) -> list[dict[str, Any]]:
    from vigil.intel import stream as S
    from vigil.sim import ambient
    _fresh_world()
    ambient.STATE.update(count=0, errors=0, skipped=0)
    S.STATE.latencies.clear()
    out = [ambient_checkpoint(0)]
    t0 = time.perf_counter()
    for n in targets:
        S.STATE.latencies.clear()
        guard = 0
        while ambient.STATE["count"] < n and guard < 4 * n:
            ambient._tick()
            guard += 1
        row = ambient_checkpoint(n)
        row["wall_s"] = round(time.perf_counter() - t0, 1)
        out.append(row)
        print(f"  ambient {row['ambient_postings']}: statuses {row['status_counts']} warned/flagged "
              f"{len(row['ordinary_warned_or_flagged'])} >=2 families {len(row['ordinary_with_ge2_families'])} "
              f"lead-check {len(row['lead_check_legit_flagged'])} latency {row['hook_latency_ms_since_last_checkpoint']}",
              flush=True)
    return out


def run_attack(sid: str) -> dict[str, Any]:
    from vigil.intel import live
    from vigil.intel import stream as S
    from vigil.realtime import HUB
    from vigil.sim import runs, scenarios
    import asyncio
    _fresh_world()
    S.STATE.latencies.clear()
    q: asyncio.Queue = asyncio.Queue()              # unbounded (HUB.subscribe queues drop beyond 500 events)
    HUB._subs.setdefault("console", set()).add(q)
    try:
        scenarios.run_sync(sid)
        events = []
        while not q.empty():
            events.append(q.get_nowait())
    finally:
        HUB.unsubscribe(q)
    run = runs.all_runs()[0].model_dump(mode="json")
    injected = set(run["injected"])
    # posting index (1-based, attack postings incl. funding credits) after which an injected account was warned / flagged
    k = 0
    first_warn = first_flag = None
    for ev in events:
        if ev["type"] == "intel.tx_scored":
            k += 1
        elif ev["type"] == "intel.account_status" and ev["data"]["account_id"] in injected:
            st = ev["data"]["status"]
            if first_warn is None and st in ("early_warning", "flagged", "confirmed_fraud"):
                first_warn = k
            if first_flag is None and st in ("flagged", "confirmed_fraud"):
                first_flag = k
    sm = S.status_map()
    snap = live.CACHE.snap
    accounts = {}
    for a in sorted(injected):
        v = sm.get(a, {})
        accounts[a] = {"status": v.get("status"), "role": v.get("role"), "model_risk": v.get("model_risk"),
                       "families": [f for f, x in (snap.flags.get(a) or {}).items() if x], "reason": v.get("reason")}
    return {"scenario": sid, "postings": k, "injected": sorted(injected), "detected": run["detected"],
            "warned": run["warned"], "missed": run["missed"], "false_positives": run["false_positives"],
            "recall": run["recall"], "precision": run["precision"],
            "first_warning_after_posting": first_warn, "detection_after_posting": first_flag,
            "first_warning_ms": run["first_warning_ms"], "detection_ms": run["detection_ms"],
            "model_threshold": run["model_threshold"], "accounts": accounts,
            "hook_latency_ms": _latency(list(S.STATE.latencies)),
            "threshold_after_run": S.current_threshold(), "threshold_reason": S.threshold_history()[-1]["reason"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    _isolate()
    from vigil import db
    from vigil.intel import live
    from vigil.intel import stream as S
    from vigil.intel.models import STORE
    import vigil.intel.api  # noqa: F401  (registers the hook listener, as the app does)
    db.connect()
    t0 = time.perf_counter()
    STORE.load()
    print("ambient ...", flush=True)
    amb = run_ambient([150] if args.quick else [600, 1800])
    print("attacks ...", flush=True)
    attacks = []
    for sid in SCENARIOS:
        r = run_attack(sid)
        attacks.append(r)
        print(f"  {sid:22s} detected {len(r['detected'])}/{len(r['injected'])} warned {len(set(r['warned']) & set(r['injected']))} "
              f"FP {r['false_positives']} warn@{r['first_warning_after_posting']} flag@{r['detection_after_posting']}"
              f"/{r['postings']} ({r['first_warning_ms']} / {r['detection_ms']} ms) hook p95 {r['hook_latency_ms']['p95']}",
              flush=True)
    snap = live.CACHE.snap
    result = {
        "label": LABEL, "command": "python ml/eval_live_world.py" + (" --quick" if args.quick else ""),
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "world": {"accounts": len(live.GRAPH.accounts), "scored": len(snap.ids) if snap else None,
                  "postings": int(db.scalar("SELECT COUNT(*) FROM transactions"))},
        "artefacts": {"random_forest": STORE.rf_meta.get("version"), "gnn": STORE.gnn_meta.get("version"),
                      "trained_at": STORE.rf_meta.get("trained_at")},
        "stream": {"version": S.STREAM_VERSION, "initial_threshold": S.STATE.initial},
        "ambient": amb, "attacks": attacks, "wall_s": round(time.perf_counter() - t0, 1),
    }
    if not args.quick:
        OUT.write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
        print(f"written {OUT} [{result['wall_s']}s]")
    else:
        print(f"quick run, nothing written [{result['wall_s']}s]")


if __name__ == "__main__":
    main()
