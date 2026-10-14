"""HTTP + WebSocket routes. Thin: validation in, domain call, JSON out.

All errors: {"error": {"code", "message", "details?"}} (see app.py handlers).
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Query, WebSocket
from pydantic import BaseModel, Field

from vigil import clock, db
from vigil.api import views
from vigil.contracts import CreateIntentRequest
from vigil.engine import lifecycle
from vigil.engine.ledger import VigilError
from vigil.realtime import HUB, serve
from vigil.risk import external_intel, ringwatch, taint
from vigil.settings import get_policy, get_policy_version
from vigil.sim import ambient, scenarios
from vigil.sim import seed as seed_mod

router = APIRouter(prefix="/api")
ws_router = APIRouter()


# ── system ────────────────────────────────────────────────────────────────
@router.get("/health")
async def health():
    return views.health()


@router.get("/policy")
async def policy():
    p = get_policy()
    return {"version": get_policy_version(), "weights": p["fusion"]["weights"], "ladder": p["ladder"],
            "corroboration": p["fusion"]["corroboration"], "adjustments": p["adjustments"],
            "note": "Hand-set demo weights, versioned. Not fitted or validated on real fraud data."}


@router.get("/metrics")
async def metrics():
    return views.metrics()


@router.post("/demo/reset")
async def demo_reset():
    was_on = ambient.STATE["enabled"]
    ambient.set_enabled(False)
    scenarios.cancel_all()
    result = seed_mod.seed()
    # rebuild the detection-intelligence snapshot now (≈0.7 s on world v3), inside the reset request,
    # so the first payment after a reset is not the cold build (675 ms → 17 ms for s0)
    try:
        from vigil.intel import warm  # type: ignore[import-not-found]

        warm()
    except Exception:
        pass
    HUB.publish("console", "demo.reset", result)
    if was_on:
        ambient.set_enabled(True)
    return result


class AmbientBody(BaseModel):
    enabled: bool


@router.post("/ambient")
async def set_ambient(body: AmbientBody):
    return ambient.set_enabled(body.enabled)


# ── accounts ──────────────────────────────────────────────────────────────
@router.get("/accounts")
async def accounts(role: Optional[str] = None, q: Optional[str] = None, limit: int = Query(200, le=500)):
    sql = "SELECT id, display_name, kind, balance_paise, is_demo_customer, persona, opened_at FROM accounts WHERE 1=1"
    params: list = []
    if role == "demo":
        sql += " AND is_demo_customer = 1"
    elif role == "customer":
        sql += " AND kind = 'customer'"
    if q:
        sql += " AND (id LIKE ? OR display_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY is_demo_customer DESC, id LIMIT ?"
    params.append(limit)
    return db.q(sql, tuple(params))


@router.get("/accounts/{account_id}")
async def account(account_id: str):
    return views.account_summary(account_id)


@router.get("/accounts/{account_id}/timeline")
async def account_timeline(account_id: str, minutes: int = Query(90, le=1440)):
    return views.timeline(account_id, minutes)


@router.get("/accounts/{account_id}/network")
async def account_network(account_id: str):
    signals, feats = ringwatch.evaluate(account_id)
    return {"account_id": account_id, "score": ringwatch.score(signals),
            "signals": [s.model_dump() for s in signals], "features": feats,
            "external_intel": external_intel.provider().lookup(account_id)}


@router.get("/accounts/{account_id}/transactions")
async def account_transactions(account_id: str, limit: int = Query(30, le=200)):
    return db.q("SELECT * FROM transactions WHERE (sender_id = ? OR recipient_id = ?) AND kind != 'opening' "
                "ORDER BY seq DESC LIMIT ?", (account_id, account_id, limit))


# ── intents ───────────────────────────────────────────────────────────────
@router.post("/intents")
async def create_intent(body: CreateIntentRequest):
    intent, decision = lifecycle.create(body, auto_pay=False if body.source == "user" else None)
    return {"intent": intent.model_dump(mode="json"), "decision": decision.model_dump(mode="json")}


@router.get("/intents")
async def list_intents(limit: int = Query(40, le=200), sender_id: Optional[str] = None, include_ambient: bool = False):
    sql = "SELECT id FROM transaction_intents WHERE 1=1"
    params: list = []
    if sender_id:
        sql += " AND sender_id = ?"
        params.append(sender_id)
    if not include_ambient:
        sql += " AND source != 'ambient'"
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    return [lifecycle.get_intent(r["id"]).model_dump(mode="json") for r in db.q(sql, tuple(params))]


@router.get("/intents/{intent_id}")
async def get_intent(intent_id: str):
    intent = lifecycle.get_intent(intent_id)
    decision = lifecycle.get_decision(intent.decision_id) if intent.decision_id else None
    return {"intent": intent.model_dump(mode="json"), "decision": decision.model_dump(mode="json") if decision else None}


class AckBody(BaseModel):
    purpose: Optional[str] = None


@router.post("/intents/{intent_id}/acknowledge")
async def acknowledge(intent_id: str, body: AckBody):
    return lifecycle.acknowledge(intent_id, body.purpose).model_dump(mode="json")


@router.post("/intents/{intent_id}/cancel")
async def cancel(intent_id: str):
    return lifecycle.cancel(intent_id).model_dump(mode="json")


class BankBody(BaseModel):
    action: Literal["release", "reject"]
    note: Optional[str] = None


@router.post("/intents/{intent_id}/bank-action")
async def bank_action(intent_id: str, body: BankBody):
    return lifecycle.bank_action(intent_id, body.action, body.note).model_dump(mode="json")


@router.post("/intents/{intent_id}/pay")
async def pay(intent_id: str):
    return lifecycle.pay(intent_id).model_dump(mode="json")


# ── decisions / investigation ─────────────────────────────────────────────
@router.get("/decisions")
async def list_decisions(limit: int = Query(50, le=300), min_tier: int = 0, include_ambient: bool = False):
    sql = ("SELECT d.record, i.source FROM risk_decisions d JOIN transaction_intents i ON i.id = d.intent_id "
           "WHERE d.tier >= ?" + ("" if include_ambient else " AND i.source != 'ambient'") +
           " ORDER BY d.created_at DESC, d.id DESC LIMIT ?")
    from vigil.contracts import RiskDecision
    out = []
    for r in db.q(sql, (min_tier, limit)):
        d = RiskDecision.model_validate_json(r["record"])
        out.append({**lifecycle.decision_summary(d), "source": r["source"], **views.case_sources(d)})
    return out


@router.get("/decisions/{decision_id}")
async def get_decision(decision_id: str):
    return lifecycle.get_decision(decision_id).model_dump(mode="json")


@router.get("/alerts")
async def alerts(status: Optional[str] = None, limit: int = Query(50, le=300)):
    sql = "SELECT * FROM alerts" + (" WHERE status = ?" if status else "") + " ORDER BY ts DESC LIMIT ?"
    return db.q(sql, ((status, limit) if status else (limit,)))


@router.get("/investigate/{decision_id}")
async def investigate(decision_id: str):
    return views.investigate(decision_id)


# ── network / tracing ─────────────────────────────────────────────────────
@router.get("/graph/suspicious")
async def graph_suspicious():
    return views.suspicious_graph().model_dump(mode="json")


@router.get("/graph/neighborhood/{account_id}")
async def graph_neighbourhood(account_id: str, hops: int = Query(1, ge=1, le=2)):
    return views.neighbourhood(account_id, hops).model_dump(mode="json")


@router.get("/ringwatch")
async def ringwatch_scan(min_score: float = 0.3):
    return views.ring_rows_with_detection(ringwatch.scan(min_score))


class LabelBody(BaseModel):
    transaction_id: str
    grade: Literal["bank_confirmed", "reported_unverified"] = "bank_confirmed"
    label: str = Field(default="scam", max_length=60)


@router.post("/labels")
async def add_label(body: LabelBody):
    tx = db.q1("SELECT * FROM transactions WHERE id = ?", (body.transaction_id,))
    if tx is None:
        raise VigilError(404, "unknown_transaction", f"No transaction '{body.transaction_id}'.")
    if db.q1("SELECT id FROM fraud_labels WHERE transaction_id = ?", (body.transaction_id,)):
        raise VigilError(409, "already_labelled", "This transaction is already labelled.")
    with db.tx():
        label_id = db.next_id("LBL")
        db.insert("fraud_labels", {"id": label_id, "transaction_id": body.transaction_id, "grade": body.grade,
                                   "label": body.label, "labelled_by": "analyst (demo)", "ts": clock.now_iso()})
    result = taint.run(force=True)
    view = views.taint_view()
    HUB.publish("console", "taint.updated", {"label_id": label_id, "transaction_id": body.transaction_id,
                                             "computed_ms": result["computed_ms"],
                                             "exposure": view["exposure"][:12]})
    return {"label_id": label_id, "taint": view}


@router.get("/taint")
async def get_taint():
    return views.taint_view()


# ── scenarios ─────────────────────────────────────────────────────────────
@router.get("/scenarios")
async def list_scenarios():
    return scenarios.status()


@router.post("/scenarios/{scenario_id}/start")
async def scenario_start(scenario_id: str):
    return scenarios.start(scenario_id)


@router.post("/scenarios/{scenario_id}/pause")
async def scenario_pause(scenario_id: str):
    return scenarios.pause(scenario_id)


@router.post("/scenarios/{scenario_id}/resume")
async def scenario_resume(scenario_id: str):
    return scenarios.resume(scenario_id)


@router.post("/scenarios/{scenario_id}/reset")
async def scenario_reset(scenario_id: str):
    if scenario_id not in scenarios.SCENARIOS:
        raise VigilError(404, "unknown_scenario", f"No scenario '{scenario_id}'.")
    return {"scenario_id": scenario_id, "reset": await demo_reset()}


@router.get("/scenarios/{scenario_id}/explain")
async def scenario_explain(scenario_id: str):
    return scenarios.explain(scenario_id)


# ── trusted contact ───────────────────────────────────────────────────────
@router.get("/contact/{token}")
async def contact(token: str):
    return lifecycle.contact_view(token)


class ContactBody(BaseModel):
    breaker_id: str
    response: Literal["acknowledged", "calling_user", "marked_expected"]


@router.post("/contact/{token}/respond")
async def contact_respond(token: str, body: ContactBody):
    return lifecycle.contact_respond(token, body.breaker_id, body.response)


# ── realtime ──────────────────────────────────────────────────────────────
@ws_router.websocket("/ws")
async def websocket(ws: WebSocket, topics: str = "console"):
    wanted = [t for t in topics.split(",") if t][:6]
    await serve(ws, wanted)
