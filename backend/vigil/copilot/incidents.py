"""Deterministic incident engine (overview-v10 P7). NO LLM in this path.

A background task listens to the console topic of the existing WebSocket hub (postings, status changes, decisions,
attack runs, labels, resets). Events only mark the engine dirty; at most every DEBOUNCE_S it re-evaluates nine
detectors over the current state and upserts incidents:

    ring_formed · account_flagged · cash_out_cluster · impossible_travel · payment_held_t3 · tier4_coercion
    fast_pass_through_new_account · device_farm · confirmed_scam_trace

Severity is a hand-set, explainable rubric from config/copilot_policy.yaml (base by kind + ₹ at stake + number of
accounts + confirmed + recency − contained). The components are stored so the UI can say WHY. It is NOT validated
against real data. Incidents never change a status, a hold or a payment tier.

Dedupe: an open incident of the same kind that shares accounts with a new finding is updated in place (a ring that
grows stays one incident); otherwise a new incident is created with dedupe_key = kind + accounts + time bucket.
A WebSocket `copilot.incident` is pushed on create, on severity change and on close — not on every refresh.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from vigil import clock, db, overview
from vigil.graph.pathgraph import GRAPH
from vigil.realtime import HUB

log = logging.getLogger("vigil.copilot")
DEBOUNCE_S = 1.5
TRIGGERS = {"ledger.posted", "intel.account_status", "decision.created", "attack.run_updated", "taint.updated",
            "breaker.fired", "intent.updated", "account.opened", "demo.reset", "ringwatch.scan"}
STATE: dict[str, Any] = {"task": None, "dirty": True, "evaluations": 0, "last_eval_ms": 0.0, "errors": 0}

KIND_LABEL = {
    "ring_formed": "Ring formed", "account_flagged": "Account flagged", "cash_out_cluster": "Cash-out cluster",
    "impossible_travel": "Impossible travel", "payment_held_t3": "Payment held", "tier4_coercion": "Coercion alert",
    "fast_pass_through_new_account": "New account passing money through", "device_farm": "Device farm",
    "confirmed_scam_trace": "Confirmed scam money traced",
}
ENGINE = {
    "ring_formed": "Network watcher (RingWatch rules + detection stream)",
    "account_flagged": "Detection stream (live account status)",
    "cash_out_cluster": "Derived signal on simulated ATM locations (display only)",
    "impossible_travel": "Derived signal on simulated device locations (display only)",
    "payment_held_t3": "Payment gate (PRIMA pre-commit decision, Tier 3)",
    "tier4_coercion": "Payment gate (PRIMA pre-commit decision, Tier 4 + CircuitBreaker)",
    "fast_pass_through_new_account": "Mule pipeline heuristic (display only)",
    "device_farm": "Device graph (accounts bound to one device)",
    "confirmed_scam_trace": "TaintTrace (value traced from bank-confirmed scams)",
}


# ── severity rubric ──────────────────────────────────────────────────────
def _band_points(table: list[list[Any]], value: float) -> int:
    for upper, pts in table:
        if upper is None or value < upper:
            return int(pts)
    return int(table[-1][1])


def severity(kind: str, stake_paise: int, n_accounts: int, confirmed: bool, age_s: float, contained: bool) -> dict[str, Any]:
    cfg = overview.policy()["incidents"]
    parts = {"base": int(cfg["base"][kind]),
             "stake": _band_points(cfg["stake_bands_paise"], stake_paise),
             "accounts": _band_points([[u if u is None else u + 1, p] for u, p in cfg["entities_points"]], n_accounts),
             "confirmed": int(cfg["confirmed_points"]) if confirmed else 0,
             "recency": int(round(cfg["recency_points"] * (1.0 if age_s <= 300 else max(0.0, (3600 - age_s) / 3300)))),
             "contained": int(cfg["contained_points"]) if contained else 0}
    score = max(0, min(100, sum(parts.values())))
    b = cfg["bands"]
    level = "critical" if score >= b["critical"] else "high" if score >= b["high"] else "medium" if score >= b["medium"] else "low"
    return {"score": score, "level": level, "parts": parts}


# ── detectors → findings ─────────────────────────────────────────────────
def _age(ts: str | None) -> float:
    if not ts:
        return 99999.0
    return max(0.0, clock.now().timestamp() - clock.parse(ts).timestamp())


def _last_ts(accounts: list[str]) -> str | None:
    best = None
    for a in accounts:
        for lst in (GRAPH.out_edges.get(a, []), GRAPH.in_edges.get(a, [])):
            if lst and (best is None or lst[-1].ts > best):
                best = lst[-1].ts
    return best


ROLE_PHRASE = {"collector": "a mule collector (takes money in from many payers)",
               "distributor": "a mule distributor (spreads money out to many accounts)",
               "coordinator": "a coordinator inside a mule network", "entry": "the entry point of a mule chain",
               "exit": "a cash-out account at the end of a mule chain"}


def _flows_72h(aid: str) -> tuple[int, int]:
    since_t = clock.now().timestamp() - 72 * 3600
    return (sum(e.amount_paise for e in GRAPH.inflows(aid, since_t)),
            sum(e.amount_paise for e in GRAPH.outflows(aid, since_t)))


def findings() -> list[dict[str, Any]]:
    """Each finding carries `title` (short, for lists), `subject` (who / where, for the alert chip) and `situation`
    (one plain sentence with the numbers — what Vigilance says when it raises the alert)."""
    sts = overview.statuses()
    nm = overview.names()
    inr = overview._inr
    out: list[dict[str, Any]] = []
    since2h = clock.iso(clock.now() - timedelta(hours=2))
    ring_accounts: set[str] = set()

    for r in overview.rings():
        if r["size"] >= 3 and r["flagged"] >= 1:
            ring_accounts.update(r["members"])
            where = f" around {r['city']}" if r["city"] else ""
            out.append({"kind": "ring_formed", "entities": r["members"], "stake": r["value_paise"],
                        "title": f"{r['kind'].title()} of {r['size']} accounts{where}",
                        "subject": f"{r['size']} accounts{where}",
                        "situation": f"{r['size']} connected accounts{where} moved {inr(r['value_paise'])} between them in "
                                     f"the live window; {r['flagged']} of them are already flagged.",
                        "facts": [f"{r['flagged']} of {r['size']} accounts flagged",
                                  f"{inr(r['value_paise'])} moved between them in the live window",
                                  "Network rules: " + (", ".join(r["rules"][:5]) or "—")],
                        "confirmed": any(sts.get(a, {}).get("status") == "confirmed_fraud" for a in r["members"]),
                        "ts": _last_ts(r["members"]), "city": r["city"]})
    for aid, s in sts.items():
        if s["status"] == "flagged" and aid not in ring_accounts:
            stake = sum(e.amount_paise for e in GRAPH.in_edges.get(aid, [])[-20:])
            role = s.get("role")
            fam = int(s.get("families_flagging") or 0)
            tin, tout = _flows_72h(aid)
            moved = (f"received {inr(tin)} and passed {inr(tout)} ({round(100 * tout / tin)}%) on to other accounts in the last 72 hours"
                     if tin else f"received {inr(stake)} in its latest inflows")
            out.append({"kind": "account_flagged", "entities": [aid], "stake": stake,
                        "title": f"{nm.get(aid, aid)} flagged" + (f" as a {role}" if role and role != "unclassified" else "")
                                 + f" · {fam} detector families agree",
                        "subject": nm.get(aid, aid),
                        "situation": f"{nm.get(aid, aid)} {moved}; {fam} independent detector families agree it behaves "
                                     f"like {ROLE_PHRASE.get(role or '', 'a mule account')}.",
                        "facts": [s.get("reason") or "flagged by the detection stream",
                                  f"{inr(stake)} received in its latest inflows"],
                        "confirmed": False, "ts": s.get("since") or _last_ts([aid])})
    for c in overview.cash_out_clusters(since2h):
        out.append({"kind": "cash_out_cluster", "entities": c["accounts"], "stake": c["value_paise"], "tx_ids": c["tx_ids"],
                    "title": f"{len(c['tx_ids'])} risky ATM withdrawals in {c['city']}",
                    "subject": c["city"],
                    "situation": f"{len(c['tx_ids'])} ATM withdrawals by risky accounts in {c['city']}: "
                                 f"{inr(c['value_paise'])} taken out within {c['radius_km']} km between "
                                 f"{c['first_ts'][11:16]} and {c['last_ts'][11:16]} UTC (simulated ATM locations).",
                    "facts": [f"{inr(c['value_paise'])} withdrawn within {c['radius_km']} km",
                              f"between {c['first_ts'][11:16]} and {c['last_ts'][11:16]} UTC",
                              "Simulated ATM terminal locations (±25 m)",
                              f"{len(c['accounts'])} risky accounts · {c.get('atm_count', len(c['tx_ids']))} ATM terminal(s) · "
                              f"{c.get('minutes', 0):.0f}-minute window",
                              f"Rule: {c.get('rule', 'cash-out cluster')}"],
                    "confirmed": False, "ts": c["last_ts"], "city": c["city"]})
    for t in overview.impossible_travel(since2h):
        span = "under a minute" if t["minutes"] < 1 else f"{t['minutes']:.0f} min"
        limit = overview.policy()["signals"]["impossible_travel_kmh"]
        who = nm.get(t["account"], t["account"])
        out.append({"kind": "impossible_travel", "entities": [t["account"]], "stake": 0, "tx_ids": t["tx_ids"],
                    "title": f"{who}: {t['from_city']} → {t['to_city']} in {span}",
                    "subject": who,
                    "situation": f"{who}'s device paid from {t['from_city']} and then from {t['to_city']} ({t['km']} km "
                                 f"apart) within {span} — faster than any travel ({limit} km/h limit).",
                    "facts": [f"{t['km']} km apart, implied speed {t['kmh']} km/h (limit {limit} km/h)",
                              "Same account, consecutive presence fixes (device GPS / ATM terminal; simulated)",
                              f"Location quality: {' → '.join(p['label'].replace('Simulated location · ', '') for p in t.get('points', []))}"
                              f" · {t.get('effective_km', t['km'])} km after subtracting both accuracies · confidence {t.get('confidence', 'high')}",
                              "Location is corroborating evidence: it can support, never decide, an account's status"],
                    "confirmed": False, "ts": t["ts"], "city": t["to_city"]})
    for al in db.q("SELECT a.*, i.state FROM alerts a LEFT JOIN transaction_intents i ON i.id = a.intent_id "
                   "WHERE a.tier >= 3 AND a.status = 'open' ORDER BY a.ts DESC LIMIT 20"):
        kind = "tier4_coercion" if al["tier"] >= 4 else "payment_held_t3"
        snd, rcp = nm.get(al["account_id"], al["account_id"]), nm.get(al["recipient_id"], al["recipient_id"])
        situation = (f"{snd} is trying to send {inr(al['amount_paise'])} to {rcp} with signs of coercion; Vigil is holding "
                     f"the payment and has alerted the trusted contact (Tier 4)." if al["tier"] >= 4 else
                     f"Vigil held {snd}'s {inr(al['amount_paise'])} payment to {rcp} for review before any money moved "
                     f"(Tier 3).")
        out.append({"kind": kind, "entities": [al["account_id"], al["recipient_id"]], "stake": al["amount_paise"],
                    "title": f"{snd} → {rcp} {inr(al['amount_paise'])} held (Tier {al['tier']})",
                    "subject": f"{snd} → {rcp}", "situation": situation,
                    "facts": [al["headline"], f"intent {al['intent_id']} · state {al['state']}"],
                    "confirmed": False, "ts": al["ts"], "key_extra": al["intent_id"],
                    "contained": al["state"] in ("HELD", "ESCALATED", "REJECTED")})
    pipe = overview.pipeline()
    for a in pipe["accounts"]:
        if a["suspicious_path"] and a["id"] not in ring_accounts and sts.get(a["id"], {}).get("status") != "flagged":
            out.append({"kind": "fast_pass_through_new_account", "entities": [a["id"]], "stake": a["out_paise"],
                        "title": f"{a['name']} ({a['age_days']:.0f} d old) forwarded {a['forwarded_pct']:.0f}% of inflow",
                        "subject": a["name"],
                        "situation": f"{a['name']}, opened {a['age_days']:.0f} days ago, received {inr(a['in_paise'])} "
                                     f"and forwarded {a['forwarded_pct']:.0f}% of it.",
                        "facts": [pipe["rule"], f"in {inr(a['in_paise'])} · out {inr(a['out_paise'])}"],
                        "confirmed": False, "ts": a["first_debit_ts"]})
    for dev, accs in GRAPH.device_accounts.items():
        accs = sorted(a for a in accs if not a.startswith("ext:"))
        risky = [a for a in accs if sts.get(a, {}).get("status") in overview.RISKY | overview.WARN]
        if len(accs) >= 3 and risky:
            out.append({"kind": "device_farm", "entities": accs, "stake": sum(e.amount_paise for a in accs
                                                                              for e in GRAPH.in_edges.get(a, [])[-5:]),
                        "title": f"{len(accs)} accounts on one device", "subject": f"{len(accs)} accounts, one device",
                        "situation": f"{len(accs)} accounts are operated from the same device; {len(risky)} of them "
                                     f"are flagged or on early warning.",
                        "facts": [f"device {dev[:4]}… shared by {len(accs)} accounts",
                                  "at least one is under watch or flagged"],
                        "confirmed": False, "ts": _last_ts(accs), "key_extra": dev})
    try:
        from vigil.risk import taint
        exp = {a: v for a, v in taint.exposure().items() if v > 0 and not a.startswith("ext:")}
    except Exception:
        exp = {}
    if exp:
        accs = sorted(exp, key=lambda a: -exp[a])[:12]
        total = int(sum(exp.values()))
        out.append({"kind": "confirmed_scam_trace", "entities": accs, "stake": total,
                    "title": f"Scam money traced to {len(exp)} account(s)",
                    "subject": f"{len(exp)} account(s)",
                    "situation": f"{inr(total)} of money from bank-confirmed scams now sits in {len(exp)} account(s); "
                                 f"the largest holder is {nm.get(accs[0], accs[0])}.",
                    "facts": [f"{inr(total)} attributable (LIBR) from bank-confirmed scam reports",
                              "Largest holder: " + nm.get(accs[0], accs[0])],
                    "confirmed": True, "ts": clock.now_iso()})
    return out


# ── persistence ──────────────────────────────────────────────────────────
def _row_to(i: dict[str, Any]) -> dict[str, Any]:
    i = dict(i)
    i["entities"] = db.loads(i.pop("entity_ids"), [])
    i["tx_ids"] = db.loads(i["tx_ids"], [])
    i["summary"] = db.loads(i.pop("summary_json"), {})
    return i


def list_incidents(status: str = "open") -> list[dict[str, Any]]:
    rows = db.q("SELECT * FROM copilot_incidents" + (" WHERE status = ?" if status != "all" else "") +
                " ORDER BY score DESC, updated_ts DESC", (status,) if status != "all" else ())
    return [_row_to(r) for r in rows]


def get(incident_id: str) -> dict[str, Any] | None:
    r = db.q1("SELECT * FROM copilot_incidents WHERE id = ?", (incident_id,))
    return _row_to(r) if r else None


def public(i: dict[str, Any], brief: bool = True) -> dict[str, Any]:
    from vigil.copilot import playbooks
    s = i["summary"]
    label, typology = playbooks.CLASS.get(i["kind"], (KIND_LABEL.get(i["kind"], i["kind"]), ""))
    mins, within = playbooks.RESPOND.get(i["severity"], playbooks.RESPOND["medium"])
    try:
        pv = playbooks.view(i)
        progress = {"done": pv["done"], "total": pv["total"],
                    "next": next((st["title"] for st in pv["steps"] if not st["done"]), None)}
    except Exception:
        progress = None
    return {"id": i["id"], "kind": i["kind"], "kind_label": KIND_LABEL.get(i["kind"], i["kind"]), "severity": i["severity"],
            "classification": label, "typology": typology, "respond_within": within, "respond_minutes": mins,
            "procedure": progress, "subject": s.get("subject") or i["title"], "situation": s.get("situation") or i["title"],
            "contained": bool(s.get("contained")),
            "score": i["score"], "status": i["status"], "title": i["title"], "entities": i["entities"],
            "tx_ids": i["tx_ids"], "value_paise": s.get("stake"), "facts": s.get("facts", []),
            "score_parts": s.get("score_parts", {}), "engine": s.get("engine"), "city": s.get("city"),
            "created_ts": i["created_ts"], "updated_ts": i["updated_ts"], "version": s.get("version", 1),
            "llm_used": bool(i.get("llm_used")), **({"brief": s.get("brief")} if brief else {})}


def _upsert(f: dict[str, Any], open_rows: list[dict[str, Any]]) -> tuple[str, str] | None:
    cfg = overview.policy()["incidents"]
    sts = overview.statuses()
    ents = sorted(set(f["entities"]))
    contained = f.get("contained") or all(sts.get(a, {}).get("status") in ("held", "confirmed_fraud") for a in ents)
    sev = severity(f["kind"], int(f.get("stake") or 0), len(ents), bool(f.get("confirmed")), _age(f.get("ts")), contained)
    now = clock.now_iso()
    match = None
    for r in open_rows:
        if r["kind"] != f["kind"]:
            continue
        if f.get("key_extra") and r["summary"].get("key_extra") == f["key_extra"]:
            match = r
            break
        if not f.get("key_extra") and set(r["entities"]) & set(ents):
            match = r
            break
    summary = {"stake": int(f.get("stake") or 0), "facts": f["facts"], "score_parts": sev["parts"],
               "engine": ENGINE[f["kind"]], "city": f.get("city"), "key_extra": f.get("key_extra"),
               "contained": contained, "subject": f.get("subject"), "situation": f.get("situation")}
    if match:
        changed = (set(match["entities"]) != set(ents) or match["severity"] != sev["level"]
                   or match["summary"].get("stake") != summary["stake"])
        if not changed:
            old = match["summary"]
            if (old.get("situation"), old.get("subject"), old.get("city")) != (summary["situation"], summary["subject"], summary["city"]):
                fresh = {**old, "situation": summary["situation"], "subject": summary["subject"], "city": summary["city"],
                         "facts": summary["facts"]}       # wording refresh only: no new version, no announcement
                db.execute("UPDATE copilot_incidents SET summary_json = ?, title = ? WHERE id = ?",
                           (db.dumps(fresh), f["title"], match["id"]))
                match["summary"] = fresh
            return None
        summary["version"] = int(match["summary"].get("version", 1)) + 1
        summary["brief"] = None
        db.execute("UPDATE copilot_incidents SET severity = ?, score = ?, entity_ids = ?, tx_ids = ?, title = ?, "
                   "summary_json = ?, updated_ts = ? WHERE id = ?",
                   (sev["level"], sev["score"], db.dumps(ents), db.dumps(f.get("tx_ids", [])), f["title"],
                    db.dumps(summary), now, match["id"]))
        announce = (match["severity"] != sev["level"] or set(match["entities"]) != set(ents)
                    or _age(match["updated_ts"]) > float(cfg["cooldown_s"]))
        match.update(entities=ents, severity=sev["level"])
        return (match["id"], "updated") if announce else (match["id"], "quiet")
    bucket = int(clock.now().timestamp() // float(cfg["bucket_s"]))
    key = f"{f['kind']}|{'+'.join(ents[:12])}|{f.get('key_extra') or ''}|{bucket}"
    if db.q1("SELECT id FROM copilot_incidents WHERE dedupe_key = ?", (key,)):
        return None
    iid = db.next_id("INC")
    summary["version"] = 1
    db.insert("copilot_incidents", {"id": iid, "kind": f["kind"], "severity": sev["level"], "score": sev["score"],
                                    "status": "open", "entity_ids": db.dumps(ents), "tx_ids": db.dumps(f.get("tx_ids", [])),
                                    "title": f["title"], "summary_json": db.dumps(summary), "dedupe_key": key,
                                    "created_ts": now, "updated_ts": now, "opened_by": "engine", "llm_used": 0})
    open_rows.append({"id": iid, "kind": f["kind"], "entities": ents, "severity": sev["level"], "summary": summary,
                      "updated_ts": now})
    return iid, "created"


def evaluate() -> list[tuple[str, str]]:
    """One deterministic pass: findings → upserts → close incidents whose condition is gone."""
    import time
    t0 = time.perf_counter()
    overview.invalidate()
    changes: list[tuple[str, str]] = []
    open_rows = list_incidents("open")
    seen: set[str] = set()
    found = findings()
    with db.tx():
        for f in found:
            res = _upsert(f, open_rows)
            if res:
                seen.add(res[0])
                changes.append(res)
            else:
                for r in open_rows:     # unchanged match still counts as "still true"
                    if r["kind"] == f["kind"] and (set(r["entities"]) & set(f["entities"])):
                        seen.add(r["id"])
        for r in open_rows:
            if r["id"] not in seen and r["kind"] in ("account_flagged", "impossible_travel", "fast_pass_through_new_account"):
                if _age(r["updated_ts"]) > 600:          # condition gone for 10 min → resolve quietly
                    db.execute("UPDATE copilot_incidents SET status = 'resolved', updated_ts = ? WHERE id = ?",
                               (clock.now_iso(), r["id"]))
                    changes.append((r["id"], "resolved"))
    STATE["evaluations"] += 1
    STATE["last_eval_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    for iid, what in changes:
        if what in ("created", "updated", "resolved"):
            inc = get(iid)
            if inc:
                HUB.publish("console", "copilot.incident", {"change": what, "incident": public(inc, brief=False)})
    return changes


def set_status(incident_id: str, status: str) -> dict[str, Any] | None:
    if status not in ("acknowledged", "dismissed", "open"):
        return None
    inc = get(incident_id)
    if inc is None:
        return None
    db.execute("UPDATE copilot_incidents SET status = ?, updated_ts = ? WHERE id = ?", (status, clock.now_iso(), incident_id))
    inc = get(incident_id)
    HUB.publish("console", "copilot.incident", {"change": status, "incident": public(inc, brief=False)})
    return inc


# ── background task ──────────────────────────────────────────────────────
async def _run() -> None:
    queue = HUB.subscribe(["console"])
    try:
        while True:
            try:
                env = await asyncio.wait_for(queue.get(), timeout=10.0)
                if env.get("type") in TRIGGERS:
                    STATE["dirty"] = True
                if env.get("type") == "demo.reset":
                    overview.invalidate()
            except asyncio.TimeoutError:
                STATE["dirty"] = True          # periodic refresh (recency decays, conditions expire)
            if STATE["dirty"]:
                await asyncio.sleep(DEBOUNCE_S)
                while not queue.empty():       # coalesce the burst
                    queue.get_nowait()
                STATE["dirty"] = False
                try:
                    evaluate()
                except Exception:
                    STATE["errors"] += 1
                    log.exception("incident evaluation failed")
    finally:
        HUB.unsubscribe(queue)


def start() -> None:
    task = STATE.get("task")
    if task is None or task.done():
        STATE["task"] = asyncio.get_event_loop().create_task(_run())


def stop() -> None:
    task = STATE.get("task")
    if task is not None:
        task.cancel()
        STATE["task"] = None
