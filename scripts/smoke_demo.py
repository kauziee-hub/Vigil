"""Five-scenario smoke test on an isolated temp DB. Run after every merge.

    backend\\.venv\\Scripts\\python.exe scripts\\smoke_demo.py

Exit code 0 = every act behaves as the demo script promises.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["VIGIL_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="vigil-smoke-")) / "smoke.db")
os.environ["VIGIL_PAYMENT_PROVIDER"] = "mock"
os.environ["VIGIL_AMBIENT"] = "0"

from vigil import clock, db  # noqa: E402
from vigil.engine import ledger, lifecycle  # noqa: E402
from vigil.risk import taint  # noqa: E402
from vigil.sim import scenarios, seed  # noqa: E402

failures: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    if not ok:
        failures.append(name)


def decision(sid: str):
    r = [x for x in scenarios.run_sync(sid) if isinstance(x, dict) and x.get("decision_id")][0]
    return lifecycle.get_decision(r["decision_id"]), lifecycle.get_intent(r["intent_id"])


def main() -> int:
    db.connect()
    seed.seed()
    print("Vigil smoke test")
    d, i = decision("s0")
    check("Act 1 normal payment", d.tier == 0 and i.state.value == "MONITORED", f"tier {d.tier}, {i.state.value}")
    d, i = decision("s1")
    check("Act 2 risky recipient", d.tier == 2 and i.state.value == "CHALLENGED", f"tier {d.tier}, score {d.final_score}")
    lifecycle.cancel(i.intent_id)
    scenarios.run_sync("s2")
    tx = db.q1("SELECT id FROM transactions WHERE sender_id='anita.s@vigil' AND recipient_id='kiran.traders@vigil'")
    with db.tx():
        db.insert("fraud_labels", {"id": "LBL-SMOKE", "transaction_id": tx["id"], "grade": "bank_confirmed",
                                   "label": "scam", "labelled_by": "smoke", "ts": clock.now_iso()})
    t = taint.run(force=True)
    conserved = all(r["conserved"] for inc in t["incidents"] for r in inc["rules"].values())
    check("Act 3 TaintTrace", conserved and t["exposure"].get("kiran.traders@vigil", 0) > 0,
          f"conserved={conserved}, kiran attributable={t['exposure'].get('kiran.traders@vigil', 0)} paise")
    d, i = decision("s1")
    check("Act 3 feedback loop", d.tier == 3 and "NET_TAINT_EXPOSURE" in d.rules_fired, f"tier {d.tier}, score {d.final_score}")
    lifecycle.cancel(i.intent_id)
    d, i = decision("s3")
    cb = db.q1("SELECT id FROM circuit_breaker_events WHERE intent_id = ?", (i.intent_id,))
    check("Act 4 coercion", d.tier == 4 and i.state.value == "ESCALATED" and cb is not None, f"tier {d.tier}, breaker {bool(cb)}")
    check("Act 5 audit record", bool(d.reasons.audit.get("payload_sha256")) and bool(d.reasons.customer.facts),
          f"{len(d.reasons.customer.facts)} customer facts, sha256 present")
    d, i = decision("s4")
    check("Control false positive", d.tier <= 1, f"tier {d.tier}")
    check("Ledger invariant", ledger.system_total() == 0, f"system total {ledger.system_total()} paise")
    print("OK" if not failures else f"FAILED: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
