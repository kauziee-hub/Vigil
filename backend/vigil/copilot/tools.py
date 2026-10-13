"""Vigilance's READ-ONLY tools (function declarations for Gemini + Python implementations).

Rules enforced here, not in the prompt:
* no write tool exists — nothing here can hold, release, freeze, approve, label or watch;
* every result is small JSON `{ok, data, truncated}` capped at MAX_CHARS;
* any key starting with `seed_` is stripped recursively (ground truth never reaches the model);
* free text written by other parties (ledger notes, personas) is returned only as `{"untrusted_text": ...}`.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any, Callable

from vigil import clock, db, geo, overview
from vigil.engine import livestatus
from vigil.graph.pathgraph import GRAPH

MAX_CHARS = 6000
MAX_ROWS = 15
UNTRUSTED_KEYS = {"note", "persona", "reason_text", "untrusted"}


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).startswith("seed_"):
                continue
            if k in UNTRUSTED_KEYS and isinstance(v, str):
                out[k] = {"untrusted_text": v[:300]}
            else:
                out[k] = _clean(v)
            if str(k).endswith("_paise") and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[str(k)[:-6] + "_inr"] = overview._inr(int(v))      # the model prints rupees, never paise
        return out
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _cap(data: Any) -> tuple[Any, bool]:
    truncated = False
    data = _clean(data)
    text = json.dumps(data, default=str)
    if len(text) <= MAX_CHARS:
        return data, False
    if isinstance(data, dict):
        for k, v in list(data.items()):
            if isinstance(v, list) and len(v) > MAX_ROWS:
                data[k] = v[:MAX_ROWS]
                truncated = True
    elif isinstance(data, list):
        data = data[:MAX_ROWS]
        truncated = True
    text = json.dumps(data, default=str)
    while len(text) > MAX_CHARS and isinstance(data, dict):
        lists = [k for k, v in data.items() if isinstance(v, list) and len(v) > 3]
        if not lists:
            break
        for k in lists:
            data[k] = data[k][: max(3, len(data[k]) // 2)]
        truncated = True
        text = json.dumps(data, default=str)
    if len(text) > MAX_CHARS:
        return {"summary": text[:MAX_CHARS - 200] + "…"}, True
    return data, truncated


def _ok(data: Any) -> dict[str, Any]:
    d, t = _cap(data)
    return {"ok": True, "data": d, "truncated": t}


def _err(msg: str) -> dict[str, Any]:
    return {"ok": False, "error": msg}


# ── implementations ──────────────────────────────────────────────────────
def get_overview_kpis(window: str = "1h") -> dict:
    k = overview.kpis(window if window in overview.policy()["windows"] else "1h")
    return _ok({"window": k["window"], "tiles": [{x: t[x] for x in ("key", "label", "value", "delta", "unit", "how")}
                                                for t in k["tiles"]]})


def list_open_incidents() -> dict:
    from vigil.copilot import incidents
    return _ok([incidents.public(i, brief=False) for i in incidents.list_incidents("open")][:MAX_ROWS])


def get_incident(incident_id: str) -> dict:
    from vigil.copilot import incidents
    inc = incidents.get(incident_id)
    return _ok(incidents.public(inc, brief=False)) if inc else _err("unknown incident")


def get_procedure(incident_id: str) -> dict:
    """The bank procedure (playbook) for an incident: steps by phase, owner, deadline, done or not."""
    from vigil.copilot import incidents, playbooks
    inc = incidents.get(incident_id)
    if not inc:
        return _err("unknown incident")
    v = playbooks.view(inc)
    return _ok({k: v[k] for k in ("classification", "typology", "severity", "respond_within", "done", "total")} |
               {"steps": [{x: s[x] for x in ("phase", "title", "owner", "when", "done", "outside")} for s in v["steps"]]})


def get_str_draft(incident_id: str) -> dict:
    """A DRAFT of the STR grounds of suspicion for an incident (for the Principal Officer; Vigil never files)."""
    from vigil.copilot import brief, incidents
    inc = incidents.get(incident_id)
    return _ok({"draft_markdown": brief.str_draft(inc)}) if inc else _err("unknown incident")


def get_account(account_id: str) -> dict:
    s = overview.account_summary(account_id)
    if s is None:
        return _err("unknown account")
    from vigil.copilot import incidents
    s["open_incidents"] = [i["id"] for i in incidents.list_incidents("open") if account_id in i["entities"]]
    return _ok(s)


def get_transaction(tx_id: str) -> dict:
    r = db.q1("SELECT id, ts, kind, sender_id, recipient_id, amount_paise, channel, note, source, intent_id, "
              "geo_city, geo_basis, geo_accuracy_m, peer_geo_city FROM transactions WHERE id = ?", (tx_id.upper(),))
    if r is None:
        return _err("unknown transaction")
    r["rail"] = geo.rail(r["channel"], r["recipient_id"])
    r["location"] = geo.label(r["geo_basis"], r["geo_accuracy_m"])
    sts = overview.statuses()
    r["sender_status"] = sts.get(r["sender_id"], {}).get("status")
    r["recipient_status"] = sts.get(r["recipient_id"], {}).get("status")
    if r["intent_id"]:
        d = db.q1("SELECT tier, final_score, intervention FROM risk_decisions WHERE intent_id = ?", (r["intent_id"],))
        r["payment_decision"] = d
    return _ok(r)


def get_connections(tx_id: str) -> dict:
    c = overview.connections(tx_id.upper())
    if c is None:
        return _err("unknown transaction")
    c.pop("geo_path", None)
    return _ok(c)


def trace_funds(account_id: str, direction: str = "downstream", hops: int = 2) -> dict:
    if account_id not in GRAPH.accounts:
        return _err("unknown account")
    hops = max(1, min(4, int(hops)))
    since = clock.now().timestamp() - 7 * 86400
    trail = overview._trace(account_id, since if direction == "downstream" else clock.now().timestamp(),
                            "down" if direction == "downstream" else "up", depth=hops, breadth=8)
    sts = overview.statuses()
    nodes = {}
    for e in trail:
        nodes[e["account"]] = {"id": e["account"], "status": sts.get(e["account"], {}).get("status"),
                               "hops": e["hops"]}
    out: dict[str, Any] = {"start": account_id, "direction": direction, "hops": hops,
                           "edges": [{k: e[k] for k in ("from", "to", "amount_paise", "ts", "tx_id")} for e in trail],
                           "nodes": list(nodes.values())}
    try:
        from vigil.risk import taint
        held = taint.exposure()
        if held.get(account_id):
            out["traced_from_confirmed_scams_paise"] = held[account_id]
    except Exception:
        pass
    return _ok(out)


def find_rings() -> dict:
    return _ok({"rings": overview.rings()[:8], "collection_points": overview.collection_points()[:8]})


def list_new_accounts(days: int = 30) -> dict:
    p = overview.pipeline(max(1, min(180, int(days))))
    accts = sorted(p["accounts"], key=lambda a: (not a["suspicious_path"], -a["in_paise"]))
    return _ok({"stages": p["stages"], "rule": p["rule"],
                "accounts": [{k: a[k] for k in ("id", "age_days", "stage", "suspicious_path", "in_paise", "out_paise",
                                                "retention_pct", "status", "opened_via", "opened_city")} for a in accts]})


def get_pipeline_stage(stage: str) -> dict:
    p = overview.pipeline()
    if stage not in overview.STAGES:
        return _err(f"stage must be one of {list(overview.STAGES)}")
    idx = overview.STAGES.index(stage)
    accts = [a for a in p["accounts"] if overview.STAGES.index(a["stage"]) >= idx]
    return _ok({"stage": stage, "count": len(accts), "accounts": accts})


def get_geo_activity(city: str) -> dict:
    m = overview.geo_map("24h")
    c = next((x for x in m["cities"] if x["city"].lower() == city.lower()), None)
    if c is None:
        return _err("no activity for that city in the last 24 h (locations are simulated)")
    flows = [f for f in m["flows"] if city.lower() in (f["from_city"].lower(), f["to_city"].lower())][:10]
    atms = [a for a in m["atm"] if a["city"].lower() == city.lower()][:10]
    clusters = [k for k in m["clusters"] if (k.get("city") or "").lower() == city.lower()]
    return _ok({"city": c, "flows": flows, "atms": atms, "clusters": clusters, "note": "Simulated locations."})


def get_channel_mix(window: str = "24h") -> dict:
    return _ok(overview.channel_mix(window if window in overview.policy()["windows"] else "24h"))


def get_exit_points(window: str = "24h") -> dict:
    return _ok(overview.exits(window if window in overview.policy()["windows"] else "24h"))


def get_collection_points() -> dict:
    return _ok(overview.collection_points())


def get_recent_alerts(n: int = 10) -> dict:
    rows = db.q("SELECT id, tier, kind, status, headline, amount_paise, account_id, recipient_id, ts FROM alerts "
                "ORDER BY ts DESC LIMIT ?", (max(1, min(30, int(n))),))
    return _ok(rows)


def search_accounts(query: str) -> dict:
    q = (query or "").strip().lower()[:40]
    if len(q) < 2:
        return _err("query too short")
    rows = db.q("SELECT id, display_name FROM accounts WHERE lower(id) LIKE ? OR lower(display_name) LIKE ? "
                "ORDER BY id LIMIT 12", (f"%{q}%", f"%{q}%"))
    sts = overview.statuses()
    return _ok([{"id": r["id"], "name": r["display_name"], "status": sts.get(r["id"], {}).get("status")} for r in rows])


def get_situation_brief(window: str = "1h") -> dict:
    return _ok(overview.brief(window if window in overview.policy()["windows"] else "1h"))


# ── declarations ─────────────────────────────────────────────────────────
def _p(props: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props or {}, **({"required": required} if required else {})}


S = {"type": "string"}
WIN = {"type": "string", "enum": ["15m", "1h", "24h", "7d"]}

REGISTRY: dict[str, tuple[Callable[..., dict], str, dict]] = {
    "get_overview_kpis": (get_overview_kpis, "Money moved, fraud-linked value, accounts at risk, stopped, left the bank, "
                          "new accounts for a time window.", _p({"window": WIN})),
    "get_situation_brief": (get_situation_brief, "Deterministic three-line summary of the current situation.", _p({"window": WIN})),
    "list_open_incidents": (list_open_incidents, "Open incidents raised by the deterministic incident engine.", _p()),
    "get_incident": (get_incident, "One incident with facts, severity breakdown and entities.",
                     _p({"incident_id": S}, ["incident_id"])),
    "get_procedure": (get_procedure, "The bank's step-by-step procedure for an incident (contain, investigate, report, "
                      "recover), with owner, deadline and which steps are done.", _p({"incident_id": S}, ["incident_id"])),
    "get_str_draft": (get_str_draft, "A draft of the Suspicious Transaction Report's grounds of suspicion for an incident "
                      "(subjects, period, largest transfers, red flags, typology, actions so far). A draft for the "
                      "Principal Officer; nothing is filed.", _p({"incident_id": S}, ["incident_id"])),
    "get_account": (get_account, "Status, reason, role, age, devices, 24 h in/out, watchlist state of an account.",
                    _p({"account_id": S}, ["account_id"])),
    "get_transaction": (get_transaction, "One posting: parties, amount, rail, simulated location, statuses, payment decision.",
                        _p({"tx_id": S}, ["tx_id"])),
    "get_connections": (get_connections, "Who funded the sender (upstream), where the money went next (downstream), "
                        "shared devices, ring membership, link types for a posting.", _p({"tx_id": S}, ["tx_id"])),
    "trace_funds": (trace_funds, "Follow money from an account up to 4 hops upstream or downstream (last 7 days).",
                    _p({"account_id": S, "direction": {"type": "string", "enum": ["upstream", "downstream"]},
                        "hops": {"type": "integer"}}, ["account_id"])),
    "find_rings": (find_rings, "Connected clusters of risky accounts (rings, chains, collection points).", _p()),
    "list_new_accounts": (list_new_accounts, "Accounts opened in the last N days with their mule-pipeline stage.",
                          _p({"days": {"type": "integer"}})),
    "get_pipeline_stage": (get_pipeline_stage, "Accounts that reached a mule-pipeline stage.",
                           _p({"stage": {"type": "string", "enum": list(overview.STAGES)}}, ["stage"])),
    "get_geo_activity": (get_geo_activity, "Activity, flows, ATMs and clusters for one (simulated) city, last 24 h.",
                         _p({"city": S}, ["city"])),
    "get_channel_mix": (get_channel_mix, "Share of value vs share of fraud-linked value per payment rail.", _p({"window": WIN})),
    "get_exit_points": (get_exit_points, "Where money leaves the bank: ATM cash, other banks, international wires.",
                        _p({"window": WIN})),
    "get_collection_points": (get_collection_points, "Accounts at or over the risk policy's fan-in threshold.", _p()),
    "get_recent_alerts": (get_recent_alerts, "Latest payment-gate alerts (tier ≥ 2 decisions).", _p({"n": {"type": "integer"}})),
    "search_accounts": (search_accounts, "Find accounts by id or name fragment.", _p({"query": S}, ["query"])),
}

WRITE_VERBS = ("hold", "release", "freeze", "approve", "reject", "label", "watch", "delete", "update", "create", "set")


def declarations() -> list[dict[str, Any]]:
    return [{"name": n, "description": d, "parameters": p} for n, (_f, d, p) in REGISTRY.items()]


def run(name: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """Execute one whitelisted tool. Unknown names are refused; arguments are type-checked by the callee."""
    entry = REGISTRY.get(name)
    if entry is None:
        return _err(f"unknown tool '{name}'")
    fn, _d, params = entry
    allowed = set(params.get("properties", {}))
    clean = {k: v for k, v in (args or {}).items() if k in allowed}
    try:
        return fn(**clean)
    except TypeError:
        return _err("missing or invalid arguments")
    except Exception as exc:                       # a tool must never crash the chat
        return _err(f"tool failed: {type(exc).__name__}")


def summarize(name: str, result: dict[str, Any]) -> str:
    """One line for the UI's tool-call chip."""
    if not result.get("ok"):
        return f"{name}: {result.get('error', 'failed')}"
    d = result.get("data")
    if isinstance(d, list):
        return f"{name}: {len(d)} row(s)" + (" (truncated)" if result.get("truncated") else "")
    if isinstance(d, dict):
        keys = ", ".join(list(d)[:5])
        return f"{name}: {keys}" + (" (truncated)" if result.get("truncated") else "")
    return name
