"""v2 routes (Claude 1): Decision Replay, counterfactuals, records, risk evolution,
shadow mode, governance, interventions queue, system health, 3D graph scene.

All handlers are `async def` (single-threaded DB access invariant).
"""

from __future__ import annotations

import os
import time
from typing import Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from vigil import clock, db
from vigil.api import views
from vigil.contracts import RiskDecision
from vigil.engine import mode, replay
from vigil.engine.ledger import VigilError
from vigil.graph import scene
from vigil.graph.pathgraph import GRAPH
from vigil.settings import get_policy, get_policy_version, get_settings
from vigil.sim import scenarios

router = APIRouter(prefix="/api")
STARTED = time.time()


@router.get("/decisions/{decision_id}/replay")
async def decision_replay(decision_id: str):
    return replay.replay(decision_id).model_dump(mode="json")


@router.get("/decisions/{decision_id}/counterfactuals")
async def decision_counterfactuals(decision_id: str):
    return [c.model_dump() for c in replay.counterfactuals(decision_id)]


@router.get("/decisions/{decision_id}/record")
async def decision_record(decision_id: str):
    return replay.record(decision_id)


@router.get("/accounts/{account_id}/risk-timeline")
async def risk_timeline(account_id: str):
    return replay.risk_timeline(account_id)


# ── mode ──────────────────────────────────────────────────────────────────
@router.get("/mode")
async def get_mode():
    return mode.current()


class ModeBody(BaseModel):
    mode: Literal["active", "shadow"]


@router.post("/mode")
async def set_mode(body: ModeBody):
    return mode.set_mode(body.mode)


# ── interventions queue ───────────────────────────────────────────────────
@router.get("/interventions")
async def interventions(status: Literal["open", "all"] = "open", limit: int = Query(100, ge=1, le=500),
                        min_tier: int = Query(0, ge=0, le=4)):
    where = ["a.tier >= ?"] + (["a.status = 'open'"] if status == "open" else [])
    sql = ("SELECT a.*, i.state, i.hold_id FROM alerts a JOIN transaction_intents i ON i.id = a.intent_id"
           f" WHERE {' AND '.join(where)} ORDER BY a.ts DESC LIMIT ?")
    now_t = clock.now().timestamp()
    out = []
    for a in db.q(sql, (min_tier, limit)):
        hold = db.q1("SELECT id, held_paise, reference, outcome, review_by FROM scoped_holds WHERE intent_id = ?",
                     (a["intent_id"],))
        cb = db.q1("SELECT c.id, c.response, c.responded_at, t.name FROM circuit_breaker_events c "
                   "JOIN trusted_contacts t ON t.id = c.contact_id WHERE c.intent_id = ?", (a["intent_id"],))
        rec = db.q1("SELECT record FROM risk_decisions WHERE id = ?", (a["decision_id"],))
        d_mode = RiskDecision.model_validate_json(rec["record"]).mode if rec else "active"
        out.append({
            "intent_id": a["intent_id"], "decision_id": a["decision_id"], "sender_id": a["account_id"],
            "recipient_id": a["recipient_id"], "amount_paise": a["amount_paise"], "tier": a["tier"], "kind": a["kind"],
            "state": a["state"], "headline": a["headline"], "opened_at": a["ts"],
            "age_s": round(now_t - clock.parse(a["ts"]).timestamp(), 1),
            "sla_due": hold["review_by"] if hold else None,
            "hold": ({k: hold[k] for k in ("id", "held_paise", "reference", "outcome")} if hold else None),
            "circuit_breaker": ({"id": cb["id"], "contact": cb["name"], "response": cb["response"],
                                 "responded_at": cb["responded_at"]} if cb else None),
            "mode": d_mode,
        })
    return out


# ── governance ────────────────────────────────────────────────────────────
@router.get("/governance/summary")
async def governance_summary():
    policy = get_policy()
    models = []
    try:
        from vigil.intel.registry import models as intel_models  # type: ignore[import-not-found]
        models = [m.model_dump() for m in intel_models()]
    except Exception:
        models = []
    tiers = {str(r["tier"]): int(r["n"]) for r in db.q("SELECT tier, COUNT(*) AS n FROM risk_decisions GROUP BY tier")}
    shadow_rows = [RiskDecision.model_validate_json(r["record"]) for r in
                   db.q("SELECT record FROM risk_decisions WHERE record LIKE '%\"mode\":\"shadow\"%'")]
    would = sum(1 for d in shadow_rows if (d.recommended_tier or 0) >= 2)
    base_ch = sum(1 for d in shadow_rows if d.baseline and d.baseline.decision != "approve")
    agree = sum(1 for d in shadow_rows if ((d.recommended_tier or 0) >= 2) == bool(d.baseline and d.baseline.decision != "approve"))
    actions = db.q("SELECT intent_id, actor, to_state, detail, ts FROM intent_transitions "
                   "WHERE actor IN ('customer','bank','contact') ORDER BY id DESC LIMIT 15")
    return {
        "mode": mode.current(),
        "policy": {"version": get_policy_version(), "weights": policy["fusion"]["weights"], "ladder": policy["ladder"],
                   "corroboration": policy["fusion"]["corroboration"], "adjustments": policy["adjustments"],
                   "note": "Hand-set demo weights, versioned. Not fitted or validated on real fraud data."},
        "models": models,
        "decisions_by_tier": {str(t): tiers.get(str(t), 0) for t in range(5)},
        "shadow": {"evaluated": len(shadow_rows), "vigil_would_intervene": would, "baseline_would_challenge": base_ch,
                   "agreement_rate": round(agree / len(shadow_rows), 3) if shadow_rows else None},
        "recent_actions": actions,
    }


# ── system health ─────────────────────────────────────────────────────────
@router.get("/system/health")
async def system_health():
    base = views.health()
    m = views.metrics()
    db_path = get_settings().db_path
    size = sum(os.path.getsize(p) for p in (str(db_path), f"{db_path}-wal") if os.path.exists(p))
    from vigil import app as app_module
    return {
        **base,
        "uptime_s": round(time.time() - STARTED, 1),
        "db_size_bytes": size,
        "graph_nodes": len(GRAPH.accounts),
        "graph_edges": sum(len(v) for v in GRAPH.out_edges.values()),
        "cache": {"scene": scene.cache_stats()},
        "intel_available": bool(getattr(app_module, "INTEL_AVAILABLE", False)),
        "latency_p95_ms": m.get("latency_p95_ms"),
        "mode": mode.current()["mode"],
    }


# ── graph scene ───────────────────────────────────────────────────────────
@router.get("/graph/scene")
async def graph_scene(cap: int = Query(60, ge=10, le=400), focus: Optional[str] = None,
                      hops: int = Query(1, ge=1, le=2), scenario: Optional[str] = None):
    if focus and db.q1("SELECT id FROM accounts WHERE id = ?", (focus,)) is None:
        raise VigilError(404, "unknown_account", f"No account '{focus}'.")
    if scenario and scenario not in scenarios.SCENARIOS:
        raise VigilError(404, "unknown_scenario", f"No scenario '{scenario}'.")
    return scene.build(cap=cap, focus=focus, hops=hops, scenario=scenario).model_dump(mode="json")


# ── scenario replay ───────────────────────────────────────────────────────
@router.get("/scenarios/{scenario_id}/replay")
async def scenario_replay(scenario_id: str):
    if scenario_id not in scenarios.SCENARIOS:
        raise VigilError(404, "unknown_scenario", f"No scenario '{scenario_id}'.")
    return {"scenario_id": scenario_id, "events": scenarios.replay_events(scenario_id)}

