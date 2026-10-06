"""Benchmark the Vigil pipeline in-process on the deterministic demo world.

    backend\\.venv\\Scripts\\python.exe scripts\\benchmark_demo.py [--n 200] [--json] [--write]

Uses an isolated temp database (never touches data/vigil.db), mock payments,
no network. Reports risk-evaluation p50/p95, full intent-creation latency,
graph query time, TaintTrace time, scenario processing time and indexed DB
query timings. --write also saves docs/BENCHMARK_RESULTS.md.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("VIGIL_DB_PATH", str(Path(tempfile.mkdtemp(prefix="vigil-bench-")) / "bench.db"))
os.environ["VIGIL_PAYMENT_PROVIDER"] = "mock"
os.environ["VIGIL_AMBIENT"] = "0"

from vigil import clock, db  # noqa: E402
from vigil.api import views  # noqa: E402
from vigil.contracts import CreateIntentRequest  # noqa: E402
from vigil.engine import decide, lifecycle  # noqa: E402
from vigil.risk import taint  # noqa: E402
from vigil.sim import scenarios, seed  # noqa: E402


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(p * (len(ordered) - 1))))], 3)


def timed(fn, repeat: int = 1) -> list[float]:
    out = []
    for _ in range(repeat):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    db.connect()
    results: dict[str, object] = {"machine": f"{platform.system()} {platform.machine()} · Python {platform.python_version()}",
                                  "when": clock.now_iso()}
    t = time.perf_counter()
    info = seed.seed()
    results["seed_ms"] = round((time.perf_counter() - t) * 1000, 1)
    results["world"] = {"accounts": info["accounts"], "transactions": info["transactions"]}

    # scenario processing (full pipeline incl. persistence and monitoring)
    scen_ms = {}
    for sid in ("s0", "s1", "s4", "s3", "s2"):
        scen_ms[sid] = round(timed(lambda s=sid: scenarios.run_sync(s))[0], 1)
    results["scenario_processing_ms"] = scen_ms

    # TaintTrace after labelling the mule-ring source
    tx = db.q1("SELECT id FROM transactions WHERE sender_id='anita.s@vigil' AND recipient_id='kiran.traders@vigil'")
    with db.tx():
        db.insert("fraud_labels", {"id": "LBL-BENCH", "transaction_id": tx["id"], "grade": "bank_confirmed",
                                   "label": "scam", "labelled_by": "benchmark", "ts": clock.now_iso()})
    taint_ms = timed(lambda: taint.run(force=True), 5)
    results["tainttrace_ms"] = {"p50": pct(taint_ms, 0.5), "max": round(max(taint_ms), 2),
                                "journals": taint.run()["journals_considered"]}

    # risk evaluation only (no persistence) across representative intents
    cases = [("ramesh@vigil", "meena.grocer@vigil", 500_00), ("ramesh@vigil", "kiran.traders@vigil", 45_000_00),
             ("ramesh@vigil", "landlord.iyer@vigil", 1_20_000_00), ("sunita@vigil", "rk.legal.services@vigil", 5_00_000_00)]
    eval_ms: list[float] = []
    for i in range(args.n):
        s, r, a = cases[i % len(cases)]
        intent = {"id": f"BENCH-{i}", "sender_id": s, "recipient_id": r, "amount_paise": a, "note": None,
                  "device_id": None, "channel": "upi"}
        eval_ms += timed(lambda it=intent: decide.evaluate(it))
    results["risk_evaluation_ms"] = {"n": args.n, "p50": pct(eval_ms, 0.5), "p95": pct(eval_ms, 0.95),
                                     "max": round(max(eval_ms), 2), "target_p95": 150}

    # full intent creation (persist intent, transitions, decision, alerts; then cancel to free holds)
    create_ms: list[float] = []
    for i in range(min(60, args.n)):
        s, r, a = cases[i % len(cases)]
        a = min(a, 20_000_00)  # stay within available balance (scenario 3 leaves Sunita's savings on hold)
        t = time.perf_counter()
        intent, _ = lifecycle.create(CreateIntentRequest(sender_id=s, recipient_id=r, amount_paise=a), auto_pay=False)
        create_ms.append((time.perf_counter() - t) * 1000)
        if intent.state.value in {"CHALLENGED", "HELD", "ESCALATED", "APPROVED"}:
            lifecycle.cancel(intent.intent_id)
    results["intent_create_ms"] = {"n": len(create_ms), "p50": pct(create_ms, 0.5), "p95": pct(create_ms, 0.95)}

    # graph queries the UI makes
    g = timed(views.suspicious_graph, 20)
    n = timed(lambda: views.neighbourhood("kiran.traders@vigil"), 20)
    sg = views.suspicious_graph()
    results["graph_query_ms"] = {"suspicious_p50": pct(g, 0.5), "suspicious_p95": pct(g, 0.95),
                                 "neighbourhood_p50": pct(n, 0.5), "nodes_returned": len(sg.nodes),
                                 "edges_returned": len(sg.edges)}
    results["metrics_query_ms"] = pct(timed(views.metrics, 20), 0.5)

    # indexed DB queries
    now = clock.now_iso()
    queries = {
        "tx_by_sender_ts": ("SELECT COUNT(*) FROM transactions WHERE sender_id=? AND ts>=?", ("ramesh@vigil", "2026-01-01")),
        "tx_by_recipient_ts": ("SELECT COUNT(*) FROM transactions WHERE recipient_id=? AND ts>=?", ("meena.grocer@vigil", "2026-01-01")),
        "events_by_account_ts": ("SELECT COUNT(*) FROM events WHERE account_id=? AND ts<=?", ("sunita@vigil", now)),
        "decision_by_intent": ("SELECT COUNT(*) FROM risk_decisions WHERE intent_id=?", ("INT-000001",)),
        "alerts_by_account_ts": ("SELECT COUNT(*) FROM alerts WHERE account_id=? AND ts<=?", ("ramesh@vigil", now)),
    }
    results["db_query_ms"] = {k: pct(timed(lambda q=q, p=p: db.q(q, p), 50), 0.5) for k, (q, p) in queries.items()}

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"\nVigil benchmark — {results['machine']}")
        print(f"  world: {results['world']}  (seed {results['seed_ms']} ms)")
        r = results["risk_evaluation_ms"]
        print(f"  risk evaluation  p50 {r['p50']} ms   p95 {r['p95']} ms   max {r['max']} ms   (target p95 < 150 ms, n={r['n']})")
        c = results["intent_create_ms"]
        print(f"  intent create    p50 {c['p50']} ms   p95 {c['p95']} ms   (persisted, incl. ReasonLine + audit hash)")
        gq = results["graph_query_ms"]
        print(f"  graph suspicious p50 {gq['suspicious_p50']} ms ({gq['nodes_returned']} nodes / {gq['edges_returned']} edges), neighbourhood p50 {gq['neighbourhood_p50']} ms")
        print(f"  TaintTrace       p50 {results['tainttrace_ms']['p50']} ms over {results['tainttrace_ms']['journals']} journals (LIBR + pro rata)")
        print(f"  scenarios (ms)   {results['scenario_processing_ms']}")
        print(f"  metrics query    {results['metrics_query_ms']} ms")
        print(f"  db (ms)          {results['db_query_ms']}")
    if args.write:
        out = ROOT / "docs" / "BENCHMARK_RESULTS.md"
        out.write_text(
            "# Benchmark results\n\nGenerated by `scripts/benchmark_demo.py --write` on the deterministic demo world "
            "(isolated temp DB, mock payments, no network). Re-run on the demo laptop before presenting.\n\n"
            f"```json\n{json.dumps(results, indent=2)}\n```\n", encoding="utf-8")
        print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()
