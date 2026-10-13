"""Demo test book — runs every case in docs/DEMO_TEST_BOOK.md against a RUNNING Vigil and checks the expected result.

    backend\\.venv\\Scripts\\python.exe scripts\\test_book_check.py --yes                 (server on :8000)
    backend\\.venv\\Scripts\\python.exe scripts\\test_book_check.py --yes --base http://127.0.0.1:8811
    backend\\.venv\\Scripts\\python.exe scripts\\test_book_check.py --yes --only A,B         (some suites only)

It uses the same HTTP API the screens use (Test inputs drawer, customer device, case page), so a PASS
means the presenter will see exactly what the book says. Each suite starts from "Reset demo world"
(about 25 s), which DISCARDS every posting, decision and attack run since seeding — hence --yes.
Suites A, B, D and E make payments directly, so time-of-day rules use the real hour: between 00:00 and 05:00 IST the
"unusual hour" signal (book, golden rule 4) moves some tiers. Run them in the daytime.
Background traffic is paused during a suite so it cannot add signals; it is switched back on at the end.

Exit code 0 = every expected result held. Results are also written as JSON (--out).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx

RAMESH, SUNITA = "ramesh@vigil", "sunita@vigil"
KIRAN, ZENITH = "kiran.traders@vigil", "zenith.exports@vigil"
COERCION = "Caller says he is from CBI, do not tell anyone, transfer immediately"
POLICE = "Caller says he is from the police, keep this secret, pay now or you will be arrested"

ATTACKS = ["s2", "atk_fan_in", "atk_fan_out", "atk_circular", "atk_velocity_chain", "atk_cross_channel",
           "atk_shared_device", "atk_behavioural_drift", "atk_volume_spike", "atk_smurfing", "atk_dormant"]


class Book:
    def __init__(self, base: str) -> None:
        self.api = base.rstrip("/") + "/api"
        self.c = httpx.Client(timeout=180)
        self.results: list[dict[str, Any]] = []
        self.failures: list[str] = []

    # ── plumbing ──────────────────────────────────────────────────────────
    def get(self, path: str, **params: Any) -> Any:
        r = self.c.get(self.api + path, params=params or None)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict | None = None) -> Any:
        r = self.c.post(self.api + path, json=body or {})
        if r.status_code >= 400:
            raise RuntimeError(f"POST {path} -> {r.status_code}: {r.text[:300]}")
        return r.json()

    def reset(self) -> None:
        self.post("/demo/reset")
        self.post("/ambient", {"enabled": False})

    def check(self, case: str, what: str, ok: bool, got: Any) -> None:
        print(f"    {'PASS' if ok else 'FAIL'}  {what}: {got}")
        if not ok:
            self.failures.append(f"{case} — {what}: {got}")

    def record(self, case: str, title: str, observed: dict[str, Any]) -> None:
        self.results.append({"case": case, "title": title, "observed": observed})

    # ── payments ──────────────────────────────────────────────────────────
    def pay(self, sender: str, recipient: str, rupees: int, note: str, context: str | None = None) -> dict[str, Any]:
        j = self.post("/intents", {"sender_id": sender, "recipient_id": recipient, "amount_paise": rupees * 100,
                                   "note": note, "context_text": context})
        d = j.get("decision") or {}
        return {
            "intent_id": j["intent"]["intent_id"], "state": j["intent"]["state"], "decision_id": d.get("decision_id"),
            "tier": d.get("tier"), "score": d.get("final_score"), "base": d.get("base_score"),
            "title": (d.get("intervention") or {}).get("title"),
            "dimensions": {x["dimension"]: round(x["score"], 2) for x in d.get("dimensions", [])},
            "rules": d.get("rules_fired", []),
            "adjustments": [f"{a['rule_id']} ({a['effect']})" for a in d.get("adjustments", [])],
            "mode": d.get("mode"),
            **self._words(d),
        }

    @staticmethod
    def _words(d: dict[str, Any]) -> dict[str, Any]:
        """What the customer reads on the phone and what the analyst reads on the case page."""
        cust, ana = (d.get("reasons") or {}).get("customer") or {}, (d.get("reasons") or {}).get("analyst") or {}
        iv = d.get("intervention") or {}
        return {"customer_headline": cust.get("headline"), "customer_summary": cust.get("summary"),
                "customer_facts": cust.get("facts", []), "customer_next": cust.get("what_happens_next"),
                "analyst_summary": ana.get("summary"), "counterfactual": ana.get("counterfactual"),
                "bank_action": iv.get("bank_action"), "customer_action": iv.get("customer_action")}

    def pay_case(self, case: str, title: str, args: tuple, tier: int, state: str | None = None,
                 rules_any: list[str] | None = None, adj_any: list[str] | None = None) -> dict[str, Any]:
        print(f"  {case}  {title}")
        p = self.pay(*args)
        self.check(case, "tier", p["tier"] == tier, f"Tier {p['tier']} · {p['title']} · score {p['score']}")
        if state:
            self.check(case, "intent state", p["state"] == state, p["state"])
        for r in rules_any or []:
            self.check(case, f"rule {r}", r in p["rules"], ", ".join(p["rules"]) or "none")
        for a in adj_any or []:
            self.check(case, f"policy adjustment {a}", any(x.startswith(a) for x in p["adjustments"]),
                       ", ".join(p["adjustments"]) or "none")
        self.record(case, title, p)
        return p

    # ── scenarios ─────────────────────────────────────────────────────────
    def run_scenario(self, sid: str, timeout_s: float = 120) -> dict[str, Any]:
        """Start a scenario the way the drawer does and wait until it (and its detection run) is finished."""
        started = self.post(f"/scenarios/{sid}/start")
        run_id = started["run_id"]
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            st = next(s for s in self.get("/scenarios") if s["id"] == sid)
            if st["state"] == "done":
                runs = [r for r in self.get("/attacks/runs") if r["run_id"] == run_id]
                if not runs or runs[0]["status"] == "completed":
                    return {"scenario": st, "run": runs[0] if runs else None, "seconds": round(time.time() - t0, 1)}
            time.sleep(0.5)
        raise RuntimeError(f"scenario {sid} did not finish in {timeout_s}s")

    def incidents(self, status: str = "all") -> list[dict[str, Any]]:
        self.post("/copilot/evaluate")
        return self.get("/copilot/incidents", status=status)["incidents"]

    def statuses(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        u = {a["id"]: a for a in self.get("/live/universe")["accounts"]}
        return {i: {"status": u[i]["status"], "role": u[i].get("role"), "families": u[i].get("families_flagging"),
                    "reason": u[i].get("reason")} for i in ids if i in u}

    # ── suites ────────────────────────────────────────────────────────────
    def suite_a(self) -> None:
        """A — the PRIMA tier ladder, one payment per tier (one reset, in this order)."""
        print("\nSuite A — tier ladder")
        self.reset()
        self.pay_case("A1", "Everyday payment · Ramesh → Meena Grocer ₹500", (RAMESH, "meena.grocer@vigil", 500, "groceries"),
                      0, "APPROVED")
        self.pay_case("A2", "New payee, unusual amount · Ramesh → MedPlus ₹8,000",
                      (RAMESH, "medplus.pharma@vigil", 8000, "medicines"), 0, "APPROVED",
                      rules_any=["BEH_FIRST_TIME_PAYEE", "BEH_AMOUNT_OUTLIER"])
        self.pay_case("A3", "Pressure words only · Sunita → RK Legal ₹50,000 + 'CBI, do not tell anyone'",
                      (SUNITA, "rk.legal.services@vigil", 50000, "fees", COERCION), 1, "CHALLENGED",
                      rules_any=["CTX_FEAR_AUTHORITY", "CTX_SECRECY", "CTX_URGENCY"])
        self.pay_case("A4", "Risky recipient · Ramesh → Kiran Traders ₹45,000",
                      (RAMESH, KIRAN, 45000, "advance for goods"), 2, "CHALLENGED",
                      rules_any=["EXT_REPORTED", "NET_PASS_THROUGH"])
        self.pay_case("A5", "Registry-confirmed mule · Ramesh → QuickLoan Agent ₹15,000",
                      (RAMESH, "quickloan.agent@vigil", 15000, "loan processing fee"), 3, "HELD",
                      rules_any=["EXT_CONFIRMED_MULE"], adj_any=["FLOOR_EXTERNAL_CONFIRMED"])
        print("  A6  Coerced 'digital arrest' journey (scenario s3) · Sunita → RK Legal ₹5,61,600")
        out = self.run_scenario("s3")
        res = next(x["result"] for x in reversed(out["scenario"]["log"]) if isinstance(x.get("result"), dict)
                   and x["result"].get("decision_id"))
        d = self.get(f"/decisions/{res['decision_id']}")
        p = {"tier": d["tier"], "score": d["final_score"], "rules": d.get("rules_fired", []),
             "adjustments": [f"{a['rule_id']} ({a['effect']})" for a in d.get("adjustments", [])],
             "dimensions": {x["dimension"]: round(x["score"], 2) for x in d.get("dimensions", [])},
             "decision_id": d["decision_id"], "intent_id": res["intent_id"], **self._words(d)}
        self.check("A6", "tier", d["tier"] == 4, f"Tier {d['tier']} · score {d['final_score']}")
        contact = self.get("/contact/arjun")
        alerts = contact.get("alerts") or contact.get("events") or []
        p["contact_alerts"] = len(alerts)
        self.check("A6", "trusted contact Arjun has the alert", len(alerts) >= 1, f"{len(alerts)} alert(s)")
        if alerts:
            p["contact_alert"] = alerts[0]
            bid = alerts[0].get("breaker_id") or alerts[0].get("id")
            self.post("/contact/arjun/respond", {"breaker_id": bid, "response": "calling_user"})
            held = [x for x in self.get("/interventions") if x["intent_id"] == res["intent_id"]]
            cb = (held[0].get("circuit_breaker") or {}) if held else {}
            self.check("A6", "Arjun's 'I'm calling them now' reaches the bank", cb.get("response") == "calling_user",
                       cb.get("response"))
        replay = self.get(f"/decisions/{d['decision_id']}/replay")
        frames = replay.get("frames", [])
        p["replay"] = [(f.get("label") or f.get("title") or f.get("event_type"), f.get("score")) for f in frames]
        self.check("A6", "Decision Replay has the journey frames", len(frames) >= 4, f"{len(frames)} frames")
        cf = self.get(f"/decisions/{d['decision_id']}/counterfactuals")
        p["counterfactuals"] = cf
        self.record("A6", "Coerced journey (s3)", p)
        inc = self.incidents("all")
        for kind in ("tier4_coercion", "payment_held_t3"):
            self.check("A6", f"Vigilance incident {kind}", any(i["kind"] == kind for i in inc),
                       next((f"{i['severity']} · {i['title']}" for i in inc if i["kind"] == kind), "missing"))
        self.record("A7", "Vigilance after suite A", {"incidents": [
            {k: i.get(k) for k in ("severity", "kind_label", "classification", "subject", "title", "respond_within")}
            for i in inc]})

    def suite_b(self) -> None:
        """B — how the policy combines evidence (each case from a fresh reset)."""
        print("\nSuite B — policy behaviour")
        self.reset()
        self.pay_case("B1", "Same pressure words, ordinary payee · Ramesh → RK Legal ₹30,000 + police script",
                      (RAMESH, "rk.legal.services@vigil", 30000, "fees", POLICE), 1, "CHALLENGED")
        self.reset()
        self.pay_case("B2", "Risky recipient + pressure words · Ramesh → Kiran ₹45,000 + police script",
                      (RAMESH, KIRAN, 45000, "advance for goods", POLICE), 3, "HELD", adj_any=["ADJ_CORROBORATION"])
        self.reset()
        self.pay_case("B3", "Large but legitimate · Ramesh → Landlord Iyer ₹1,20,000",
                      (RAMESH, "landlord.iyer@vigil", 120000, "deposit + October rent"), 0, "APPROVED")
        print("  B4  Velocity: four quick payments, then the risky recipient")
        for _ in range(4):
            self.pay(RAMESH, "meena.grocer@vigil", 500, "groceries")
        self.pay_case("B4", "Risky recipient after 5 payments in an hour · Ramesh → Kiran ₹45,000",
                      (RAMESH, KIRAN, 45000, "advance for goods"), 3, "HELD",
                      rules_any=["BEH_VELOCITY"], adj_any=["ADJ_CORROBORATION"])

    def suite_c(self) -> None:
        """C — inject every attack pattern (each from a fresh reset) and grade detection."""
        print("\nSuite C — attack injection")
        for sid in ATTACKS:
            self.reset()
            before = {i["id"] for i in self.incidents()}
            out = self.run_scenario(sid)
            run = out["run"] or {}
            new = [i for i in self.incidents() if i["id"] not in before]
            sts = self.statuses(run.get("injected", []))
            name = out["scenario"]["name"]
            print(f"  C·{sid}  {name}")
            self.check(sid, "pattern detected (≥1 injected mule flagged)", len(run.get("detected", [])) >= 1,
                       f"{len([a for a in run.get('detected', []) if a in run.get('injected', [])])} of "
                       f"{len(run.get('injected', []))} flagged")
            self.check(sid, "no false positives", not run.get("false_positives"), run.get("false_positives") or "none")
            missed_unwarned = [a for a in run.get("missed", []) if a not in run.get("warned", [])]
            self.check(sid, "every injected mule at early warning or above", not missed_unwarned, missed_unwarned or "all")
            self.check(sid, "Vigilance raised an incident", len(new) >= 1,
                       "; ".join(f"{i['severity'].upper()} · {i['kind_label']} · {i['subject']}" for i in new) or "none")
            self.record(sid, name, {
                "seconds": out["seconds"], "tx_count": run.get("tx_count"), "injected": run.get("injected"),
                "detected": run.get("detected"), "warned": run.get("warned"), "missed": run.get("missed"),
                "false_positives": run.get("false_positives"), "recall": run.get("recall"),
                "precision": run.get("precision"), "first_warning_ms": run.get("first_warning_ms"),
                "detection_ms": run.get("detection_ms"), "statuses": sts,
                "incidents": [{k: i.get(k) for k in ("kind_label", "severity", "classification", "typology", "subject",
                                                      "title", "respond_within", "value_paise", "situation")}
                              for i in new],
            })

    def suite_d(self) -> None:
        """D — the network learns: s2 → confirmed report → TaintTrace → the same payment is now held."""
        print("\nSuite D — confirmed scam feeds back into payments")
        self.reset()
        self.run_scenario("s2")
        txs = self.get(f"/accounts/{KIRAN}/transactions")
        inbound = sorted([t for t in txs if t["recipient_id"] == KIRAN and t["kind"] == "transfer" and t["sender_id"] != RAMESH],
                         key=lambda t: t["seq"])
        src = inbound[0]
        lab = self.post("/labels", {"transaction_id": src["id"]})
        exposure = lab["taint"]["exposure"]
        print(f"  D1  Report {src['id']} ({src['sender_id']} → Kiran ₹{src['amount_paise'] // 100:,}) as confirmed scam")
        self.check("D1", "TaintTrace finds accounts holding traced value", len(exposure) >= 1,
                   ", ".join(f"{e.get('account_id') or e.get('id')}" for e in exposure[:6]))
        self.record("D1", "Confirmed scam report → TaintTrace",
                    {"transaction": src["id"], "sender": src["sender_id"], "amount_paise": src["amount_paise"],
                     "exposure": exposure[:8], "label_id": lab["label_id"]})
        p = self.pay_case("D2", "Risky recipient again · Ramesh → Kiran ₹45,000", (RAMESH, KIRAN, 45000, "advance for goods"),
                          3, "HELD", rules_any=["NET_TAINT_EXPOSURE"], adj_any=["CAP_NO_SENDER_EVIDENCE"])
        allinc = self.incidents("all")
        self.record("D3", "Vigilance incidents after s2 + the report", {"incidents": [
            {k: i.get(k) for k in ("id", "kind", "kind_label", "severity", "classification", "subject", "title",
                                    "respond_within", "procedure")} for i in allinc]})
        print("  D3  Vigilance incidents: " + "; ".join(f"{i['severity'].upper()} · {i['kind_label']}" for i in allinc))
        for kind in ("ring_formed", "confirmed_scam_trace", "payment_held_t3"):
            self.check("D3", f"incident {kind}", any(i["kind"] == kind for i in allinc),
                       next((f"{i['severity']} · {i['title']}" for i in allinc if i["kind"] == kind), "missing"))
        for inc in [i for i in allinc if i["kind"] in {"ring_formed", "confirmed_scam_trace"}]:
            proc = self.get(f"/copilot/incidents/{inc['id']}/procedure")
            b = self.post(f"/copilot/incidents/{inc['id']}/brief", {"fast": True})["brief"]
            self.record("D4", f"Procedure + assessment · {inc['kind_label']}",
                        {"incident": inc["id"], "kind": inc["kind"], "procedure": proc, "brief": b})
            if inc["kind"] == "ring_formed":
                phases = {s.get("phase") for s in proc.get("steps", [])}
                self.check("D4", "ring procedure covers contain / investigate / report / close",
                           {"contain", "investigate", "report", "close"} <= phases, sorted(x for x in phases if x))
        # bank acts on the hold
        print("  D5  Interventions: release the held payment")
        r = self.post(f"/intents/{p['intent_id']}/bank-action", {"action": "release", "note": "verified with customer"})
        self.check("D5", "release changes the state", r["state"] != "HELD", r["state"])
        self.record("D5", "Bank releases the hold", {"state": r["state"]})

    def suite_f(self) -> None:
        """F — back to back: all eleven patterns injected one after another WITHOUT a reset (as in a long demo)."""
        print("\nSuite F — every pattern back to back, no reset in between")
        self.reset()
        for sid in ATTACKS:
            out = self.run_scenario(sid)
            run = out["run"] or {}
            hits = [a for a in run.get("detected", []) if a in run.get("injected", [])]
            print(f"  F·{sid}  {out['scenario']['name']}")
            self.check(f"F·{sid}", "detected", len(hits) >= 1, f"{len(hits)} of {len(run.get('injected', []))} flagged")
            self.check(f"F·{sid}", "no false positives", not run.get("false_positives"), run.get("false_positives") or "none")
            self.record(f"F·{sid}", out["scenario"]["name"], {"detected": run.get("detected"), "injected": run.get("injected"),
                                                             "false_positives": run.get("false_positives")})
        inc = self.incidents("open")
        self.record("F·incidents", "Open Vigilance incidents after all eleven", {"incidents": [
            {k: i.get(k) for k in ("severity", "kind_label", "subject", "title")} for i in inc]})
        print(f"  F   Vigilance bar now holds {len(inc)} open alerts, most urgent first: "
              + "; ".join(f"{i['severity'].upper()} {i['kind_label']}" for i in inc[:5]))

    def suite_g(self) -> None:
        """G — combination: three cash-outs in Mumbai within 45 minutes make a cash-out cluster."""
        print("\nSuite G — cash-out cluster (s2 → Velocity Chain → Shared Device)")
        self.reset()
        for sid in ("s2", "atk_velocity_chain", "atk_shared_device"):
            self.run_scenario(sid)
        inc = self.incidents("open")
        cl = [i for i in inc if i["kind"] == "cash_out_cluster"]
        self.check("G1", "Critical cash-out cluster in Mumbai", bool(cl) and cl[0]["subject"] == "Mumbai",
                   f"{cl[0]['severity']} · {cl[0]['title']}" if cl else "missing")
        self.record("G1", "Cash-out cluster", {"incidents": [
            {k: i.get(k) for k in ("severity", "kind_label", "subject", "title", "situation", "respond_within")} for i in inc]})

    def suite_l(self) -> None:
        """L — location intelligence (v12): normal geography, impossible travel, coordinated cash-out, corroboration."""
        print("\nSuite L — location intelligence")
        self.reset()
        g = self.get("/geo/intel", window="1h")
        self.check("L1", "fresh world: no location signals", not g["impossible_travel"] and not g["anomalies"] and not g["cash_out"],
                   f"{len(g['impossible_travel'])} travel · {len(g['anomalies'])} anomalies · {len(g['cash_out'])} clusters")
        self.record("L1", "Normal geography after a reset", {"normal": g["normal"]})
        self.run_scenario("atk_cross_channel")
        g = self.get("/geo/intel", window="1h")
        t = g["impossible_travel"][0] if g["impossible_travel"] else {}
        print("  L2  Cross-Channel Burst → impossible travel")
        self.check("L2", "impossible travel Delhi → Kolkata, high confidence",
                   (t.get("from_city"), t.get("to_city"), t.get("confidence")) == ("Delhi", "Kolkata", "high"),
                   f"{t.get('from_city')} → {t.get('to_city')} · {t.get('km')} km · {t.get('speed_text')} · {t.get('confidence')}")
        sel = self.get("/geo/intel", window="1h", account=t.get("account", "")).get("selected", {})
        self.check("L2", "the account's geography is 'suspicious' with its usual places", sel.get("verdict") == "suspicious"
                   and bool(sel.get("usual_cities")), f"{sel.get('verdict')} · home {sel.get('home_city')} · usual {sel.get('usual_cities')}")
        inc = [i for i in self.incidents("open") if i["kind"] == "impossible_travel"]
        self.check("L2", "Possible-account-takeover alert raised", bool(inc), inc[0]["title"] if inc else "missing")
        self.record("L2", "Impossible travel", {"finding": t, "selected": sel, "incident": inc[0] if inc else None})
        for sid in ("s2", "atk_velocity_chain", "atk_shared_device"):
            self.run_scenario(sid)
        g = self.get("/geo/intel", window="1h")
        c = next((x for x in g["cash_out"] if x["city"] == "Mumbai"), {})
        print("  L3  Money-mule network + Velocity Chain + Shared Device → coordinated cash-out")
        self.check("L3", "Mumbai cash-out cluster with its ATMs", bool(c) and c.get("atm_count", 0) >= 2 and len(c.get("accounts", [])) >= 3,
                   f"{len(c.get('accounts', []))} accounts · {c.get('atm_count')} ATMs · radius {c.get('radius_km')} km · "
                   f"₹{c.get('value_paise', 0) // 100:,}")
        anoms = [(a["name"], [r["rule"] for r in a["rules"]], a["status"], a["contributed"]) for a in g["anomalies"]]
        self.check("L3", "location never classifies alone (every account with location evidence has detector families)",
                   all(a[2] in {"flagged", "early_warning", "held", "confirmed_fraud"} for a in anoms), anoms)
        self.record("L3", "Coordinated cash-out and anomalies", {"cluster": c, "anomalies": anoms, "normal": g["normal"]})

    def suite_e(self) -> None:
        """E — governance and controls: false-positive control, shadow mode."""
        print("\nSuite E — controls")
        self.reset()
        out = self.run_scenario("s4")
        res = next(x["result"] for x in reversed(out["scenario"]["log"]) if isinstance(x.get("result"), dict)
                   and x["result"].get("decision_id"))
        d = self.get(f"/decisions/{res['decision_id']}")
        print("  E1  False-positive control (scenario s4)")
        self.check("E1", "tier", d["tier"] == 0, f"Tier {d['tier']} · score {d['final_score']}")
        self.record("E1", "False-positive control (s4)", {"tier": d["tier"], "score": d["final_score"],
                                                          "rules": d.get("rules_fired", [])})
        self.post("/mode", {"mode": "shadow"})
        p = self.pay_case("E2", "Shadow mode · Ramesh → Kiran ₹45,000", (RAMESH, KIRAN, 45000, "advance for goods"), 2)
        self.check("E2", "decision recorded in shadow mode", p["mode"] == "shadow", p["mode"])
        self.check("E2", "customer not interrupted", p["state"] not in {"CHALLENGED", "HELD"}, p["state"])
        self.post("/mode", {"mode": "active"})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--only", default="A,B,C,D,E,F,G,L", help="comma-separated suites")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "test_book_results.json"))
    ap.add_argument("--yes", action="store_true", help="confirm: each suite resets the demo world")
    a = ap.parse_args()
    if not a.yes:
        print("Each suite runs 'Reset demo world' on", a.base, "— rerun with --yes to confirm.")
        return 2
    book = Book(a.base)
    health = book.get("/health")
    print(f"Vigil at {a.base} · policy {health['policy_version']} · {health['accounts']} accounts")
    suites: dict[str, Callable[[], None]] = {"A": book.suite_a, "B": book.suite_b, "C": book.suite_c,
                                             "D": book.suite_d, "E": book.suite_e, "F": book.suite_f, "G": book.suite_g,
                                             "L": book.suite_l}
    t0 = time.time()
    try:
        for s in a.only.split(","):
            suites[s.strip().upper()]()
    finally:
        try:
            book.reset()
            book.post("/ambient", {"enabled": True})
        except Exception:
            pass
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"policy": health["policy_version"], "results": book.results,
                                       "failures": book.failures}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{'ALL EXPECTED RESULTS HELD' if not book.failures else f'{len(book.failures)} FAILED'} "
          f"· {round(time.time() - t0)} s · results → {a.out}")
    for f in book.failures:
        print("  FAIL", f)
    return 0 if not book.failures else 1


if __name__ == "__main__":
    sys.exit(main())
