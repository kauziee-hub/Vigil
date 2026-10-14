"""Read models for the UI: graph evidence, investigation bundle, metrics, timelines.

Pure reads over SQLite + the in-memory PathGraph + cached RingWatch/TaintTrace.
"""

from __future__ import annotations

import statistics
from typing import Any

from vigil import clock, db
from vigil.contracts import GraphEdge, GraphEvidence, GraphNode
from vigil.engine import ledger, lifecycle
from vigil.graph.pathgraph import GRAPH
from vigil.realtime import HUB
from vigil.risk import external_intel, ringwatch, taint, trailscore
from vigil.settings import get_policy, get_policy_version

MAX_NODES = 60


def account_summary(account_id: str) -> dict[str, Any]:
    acc = ledger.account(account_id)
    contact = db.q1("SELECT name, relation, phone_masked, token FROM trusted_contacts WHERE account_id = ?", (account_id,))
    devices = [r["device_id"] for r in db.q("SELECT device_id FROM account_devices WHERE account_id = ? ORDER BY first_seen", (account_id,))]
    payees = db.q(
        "SELECT p.payee_id, a.display_name, COUNT(t.id) AS payments FROM payees p JOIN accounts a ON a.id = p.payee_id "
        "LEFT JOIN transactions t ON t.sender_id = p.account_id AND t.recipient_id = p.payee_id "
        "WHERE p.account_id = ? GROUP BY p.payee_id ORDER BY payments DESC LIMIT 8", (account_id,))
    return {
        "id": acc["id"], "display_name": acc["display_name"], "kind": acc["kind"], "persona": acc["persona"],
        "opened_at": acc["opened_at"], "balance_paise": acc["balance_paise"],
        "available_paise": ledger.available_paise(account_id) if acc["kind"] == "customer" else acc["balance_paise"],
        "held_paise": ledger.held_paise(account_id), "daily_limit_paise": acc["daily_limit_paise"],
        "primary_device": acc["primary_device"], "devices": devices, "payees": payees,
        "trusted_contact": {k: contact[k] for k in ("name", "relation", "phone_masked")} if contact else None,
        "is_demo_customer": bool(acc["is_demo_customer"]),
    }


def _labelled_sources() -> dict[str, str]:
    rows = db.q("SELECT t.sender_id, l.transaction_id FROM fraud_labels l JOIN transactions t ON t.id = l.transaction_id")
    return {r["sender_id"]: r["transaction_id"] for r in rows}


def _traced_edges() -> dict[tuple[str, str], int]:
    traced: dict[tuple[str, str], int] = {}
    for inc in taint.run()["incidents"]:
        for step in inc["rules"]["libr"]["steps"]:
            if step["traced_paise"] > 0:
                key = (step["from_account"], step["to_account"])
                traced[key] = traced.get(key, 0) + int(step["traced_paise"])
    return traced


def _evidence(node_ids: list[str], focus: str | None, since_t: float | None, flagged: dict[str, dict]) -> GraphEvidence:
    total = len(node_ids)
    keep = node_ids[:MAX_NODES]
    keep_set = set(keep)
    exposure = taint.exposure()
    labelled = ringwatch.labelled_accounts()
    sources = _labelled_sources()
    traced = _traced_edges()
    nodes: list[GraphNode] = []
    for nid in keep:
        meta = GRAPH.accounts.get(nid, {"display_name": nid, "kind": "customer"})
        row = flagged.get(nid)
        role = row["role"] if row else None
        if nid in sources:
            role = "source"
        if nid == "ext:atm":
            role = "cash-out"
        bal = db.scalar("SELECT balance_paise FROM accounts WHERE id = ?", (nid,)) or 0
        nodes.append(GraphNode(
            id=nid, label=meta["display_name"], kind="external" if meta.get("kind") == "external" else "customer",
            risk=row["score"] if row else 0.0, flags=row["labels"] if row else [], role=role,
            balance_paise=int(bal), labelled=nid in labelled, attributable_paise=exposure.get(nid, 0),
        ))
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in GRAPH.edges_between(keep):
        if since_t is not None and edge.t < since_t:
            continue
        a = agg.setdefault((edge.src, edge.dst), {"amount": 0, "count": 0, "first": edge.ts, "last": edge.ts, "tx": []})
        a["amount"] += edge.amount_paise
        a["count"] += 1
        a["first"] = min(a["first"], edge.ts)
        a["last"] = max(a["last"], edge.ts)
        if len(a["tx"]) < 5:
            a["tx"].append(edge.tx_id)
    edges = [
        GraphEdge(id=f"{s}->{d}", source=s, target=d, amount_paise=a["amount"], count=a["count"], first_ts=a["first"],
                  last_ts=a["last"], tainted_paise=traced.get((s, d), 0), tx_ids=a["tx"],
                  highlight=traced.get((s, d), 0) > 0 or (s in flagged and d in flagged))
        for (s, d), a in agg.items() if s in keep_set and d in keep_set
    ]
    return GraphEvidence(nodes=nodes, edges=edges, focus=focus, truncated=total > len(keep), total_nodes=total)


def suspicious_graph() -> GraphEvidence:
    window_t = clock.now().timestamp() - float(get_policy()["network"]["window_hours"]) * 3600
    rows = ringwatch.scan(min_score=0.4)
    flagged = {r["account_id"]: r for r in rows}
    core = list(flagged) + [a for a in taint.exposure() if a not in flagged]
    for acc in ringwatch.labelled_accounts():
        if acc not in core:
            core.append(acc)
    ordered = list(core)
    seen = set(core)
    # bring in the 1-hop counterparties that explain the flags (victims in, cash-out out), largest first
    neighbours: list[tuple[int, str]] = []
    for nid in core:
        for e in GRAPH.inflows(nid, window_t) + GRAPH.outflows(nid, window_t):
            other = e.src if e.dst == nid else e.dst
            if other not in seen:
                neighbours.append((-e.amount_paise, other))
    for _, other in sorted(neighbours):
        if other not in seen:
            seen.add(other)
            ordered.append(other)
    return _evidence(ordered, None, window_t, flagged)


def neighbourhood(account_id: str, hops: int = 1) -> GraphEvidence:
    ledger.account(account_id)
    flagged = {r["account_id"]: r for r in ringwatch.scan(min_score=0.0)}
    window_t = clock.now().timestamp() - float(get_policy()["network"]["window_hours"]) * 3600
    frontier = {account_id}
    ordered = [account_id]
    for _ in range(max(1, min(hops, 2))):
        nxt: list[tuple[float, str]] = []
        for nid in frontier:
            edges = GRAPH.inflows(nid) + GRAPH.outflows(nid)
            for e in sorted(edges, key=lambda e: -e.t)[:25]:
                other = e.src if e.dst == nid else e.dst
                nxt.append((-e.t, other))
        frontier = set()
        for _, other in sorted(nxt):
            if other not in ordered:
                ordered.append(other)
                frontier.add(other)
    recent = any(e.t >= window_t for e in GRAPH.inflows(account_id) + GRAPH.outflows(account_id))
    return _evidence(ordered, account_id, window_t if recent else None, flagged)


def timeline(account_id: str, minutes: int = 90) -> list[dict[str, Any]]:
    items = [{"kind": "event", **e} for e in trailscore.journey(account_id, window_minutes=minutes)]
    since = clock.ago_iso(minutes=minutes)
    for t in db.q("SELECT id, sender_id, recipient_id, amount_paise, ts, kind FROM transactions "
                  "WHERE (sender_id = ? OR recipient_id = ?) AND ts >= ? AND kind != 'opening' ORDER BY ts",
                  (account_id, account_id, since)):
        items.append({"kind": "payment", "event_type": "payment_out" if t["sender_id"] == account_id else "payment_in",
                      "label": f"{'Paid' if t['sender_id'] == account_id else 'Received'} ₹{t['amount_paise'] // 100:,}",
                      "payload": t, "ts": t["ts"], "minutes_ago": round(clock.minutes_between(t["ts"], clock.now_iso()), 1)})
    for i in db.q("SELECT id, recipient_id, amount_paise, state, tier, created_at FROM transaction_intents "
                  "WHERE sender_id = ? AND created_at >= ? ORDER BY created_at", (account_id, since)):
        items.append({"kind": "intent", "event_type": "payment_attempt",
                      "label": f"Payment attempt ₹{i['amount_paise'] // 100:,} → {i['recipient_id']} (Tier {i['tier']}, {i['state']})",
                      "payload": i, "ts": i["created_at"], "minutes_ago": round(clock.minutes_between(i["created_at"], clock.now_iso()), 1)})
    items.sort(key=lambda x: x["ts"])
    return items


def investigate(decision_id: str) -> dict[str, Any]:
    decision = lifecycle.get_decision(decision_id)
    intent = lifecycle.get_intent(decision.intent_id)
    hold = db.q1("SELECT * FROM scoped_holds WHERE intent_id = ?", (intent.intent_id,))
    breakers = [{**r, "payload": db.loads(r["payload"], {})} for r in
                db.q("SELECT * FROM circuit_breaker_events WHERE intent_id = ? ORDER BY fired_at", (intent.intent_id,))]
    trace = taint.run()
    relevant = [inc for inc in trace["incidents"]
                if decision.recipient_id in inc["hops"] or any(c["account_id"] == decision.recipient_id
                                                               for c in inc["rules"]["pro_rata"]["claims"])]
    return {
        "decision": decision.model_dump(mode="json"),
        "intent": intent.model_dump(mode="json"),
        "sender": account_summary(decision.sender_id),
        "recipient": account_summary(decision.recipient_id),
        "external_intel": (external_intel.provider().lookup(decision.recipient_id) or None),
        "graph": neighbourhood(decision.recipient_id).model_dump(mode="json"),
        "timeline": timeline(decision.sender_id, minutes=60),
        "money_trace": relevant,
        "hold": hold,
        "circuit_breaker": breakers,
    }


def taint_view() -> dict[str, Any]:
    result = taint.run()
    names = {a["id"]: a["display_name"] for a in db.q("SELECT id, display_name FROM accounts")}
    return {**{k: v for k, v in result.items() if k != "exposure"},
            "exposure": [{"account_id": a, "name": names.get(a, a), "attributable_paise": p, "hop": result["hops"].get(a)}
                         for a, p in sorted(result["exposure"].items(), key=lambda kv: -kv[1])]}


def metrics() -> dict[str, Any]:
    since10 = clock.ago_iso(minutes=10)
    tiers = {int(r["tier"]): int(r["n"]) for r in db.q("SELECT tier, COUNT(*) AS n FROM risk_decisions GROUP BY tier")}
    total = sum(tiers.values())
    lat = [float(r["latency_ms"]) for r in db.q("SELECT latency_ms FROM risk_decisions ORDER BY created_at DESC LIMIT 300")]
    lat_sorted = sorted(lat)
    flagged = ringwatch.scan(min_score=0.4)
    exposure = taint.exposure()
    challenges = int(db.scalar("SELECT COUNT(*) FROM alerts WHERE tier >= 2") or 0)
    overturned = int(db.scalar(
        "SELECT COUNT(*) FROM alerts WHERE tier >= 2 AND resolution IN ('bank_released','customer_continued')") or 0)
    expected = int(db.scalar("SELECT COUNT(*) FROM circuit_breaker_events WHERE response = 'marked_expected'") or 0)
    return {
        "transactions_last_10m": int(db.scalar("SELECT COUNT(*) FROM transactions WHERE ts >= ? AND source != 'seed'", (since10,)) or 0),
        "transactions_total": int(db.scalar("SELECT COUNT(*) FROM transactions WHERE kind != 'opening'") or 0),
        "decisions_total": total,
        "decisions_by_tier": {str(t): tiers.get(t, 0) for t in range(5)},
        "zero_friction_rate": round(tiers.get(0, 0) / total, 3) if total else None,
        "pending_intents": int(db.scalar("SELECT COUNT(*) FROM transaction_intents WHERE state IN "
                                         "('CREATED','RISK_EVALUATED','CHALLENGED','HELD','ESCALATED','APPROVED','PAYMENT_INITIATED')") or 0),
        "open_interventions": int(db.scalar("SELECT COUNT(*) FROM alerts WHERE status = 'open'") or 0),
        "held_paise": int(db.scalar("SELECT COALESCE(SUM(held_paise),0) FROM scoped_holds WHERE released_at IS NULL") or 0),
        "suspicious_accounts": len(flagged),
        "suspicious_value_paise": sum(r["total_in_paise"] for r in flagged),
        "attributable_paise": sum(exposure.values()),
        "challenges": challenges,
        "challenges_overturned": overturned + expected,
        "latency_p50_ms": round(statistics.median(lat_sorted), 2) if lat_sorted else None,
        "latency_p95_ms": round(lat_sorted[min(len(lat_sorted) - 1, int(0.95 * len(lat_sorted)))], 2) if lat_sorted else None,
        "system_total_paise": ledger.system_total(),
    }


def health() -> dict[str, Any]:
    from vigil.sim import ambient
    return {
        "status": "ok", "time": clock.now_iso(), "policy_version": get_policy_version(),
        "payment_provider": "mock",
        "payment_provider_label": "Simulated payment rail (no real money)",
        "external_intel_provider": external_intel.provider().name,
        "ambient": ambient.STATE["enabled"], "ws_clients": HUB.clients(),
        "seeded_at": db.get_meta("seeded_at"), "graph_version": GRAPH.version,
        "accounts": int(db.scalar("SELECT COUNT(*) FROM accounts") or 0),
        "transactions": int(db.scalar("SELECT COUNT(*) FROM transactions") or 0),
        "ml_on_decision_path": False,
    }


# ── Cases page: why a row is in the queue (read from stored data only, never guessed) ──────────────
# detection-layer families whose flag on the recipient counts as "mule detection" evidence; RingWatch and the
# registry have their own badges (they are rule sources on the payment), so they are not repeated here
MULE_FAMILIES = ("random_forest", "gnn", "rules", "drift", "early_warning", "pattern_memory")


def case_sources(d: Any) -> dict[str, Any]:
    """Engines behind a payment case, from its decision record: RingWatch / TaintTrace / registry rules that fired,
    and the detection families that flagged the recipient at decision time (corroborating evidence, never fused)."""
    fired = set(d.rules_fired)
    sources: list[str] = []
    if any(r.startswith("NET_") and r != "NET_TAINT_EXPOSURE" for r in fired):
        sources.append("ringwatch")
    if "NET_TAINT_EXPOSURE" in fired:
        sources.append("tainttrace")
    if any(r.startswith("EXT_") for r in fired):
        sources.append("registry")
    flagged_by = [m.family for m in d.model_evidence if m.flagged and m.status == "ok" and m.family in MULE_FAMILIES]
    if flagged_by:
        sources.append("mule_detection")
    return {"sources": sources, "flagged_by": flagged_by}


def ring_rows_with_detection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """RingWatch rows plus the live detector families flagging each account and its high-confidence location
    rules (from `intel.stream.status_map()`); copies, so the RingWatch scan cache is never modified."""
    try:
        from vigil.intel import stream  # type: ignore[import-not-found]
        sm = stream.status_map()
    except Exception:
        sm = {}
    out = []
    for r in rows:
        s = sm.get(r["account_id"]) or {}
        out.append({**r, "families": list(s.get("families") or []),
                    "location_rules": list((s.get("location") or {}).get("rules") or [])})
    return out
