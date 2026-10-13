"""Vigilance routes (overview-v10 P7, renamed from Copilot in v11; the URL prefix stays /api/copilot). Read-only with
respect to the bank: nothing here can hold, release, freeze or approve. The only writes are Vigilance's own records
(incident status, procedure ticks, threads, messages)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Literal, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from vigil.copilot import brief, chat, config, incidents, playbooks
from vigil.engine.ledger import VigilError

router = APIRouter(prefix="/api/copilot")
_RATE: dict[str, deque] = defaultdict(deque)


def _rate_ok(key: str) -> bool:
    limit = int(config.policy()["rate_limit_per_min"])
    now = time.monotonic()
    q = _RATE[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


@router.get("/status")
async def copilot_status():
    return {**config.status(), "engine": {k: v for k, v in incidents.STATE.items() if k != "task"},
            "open_incidents": len(incidents.list_incidents("open"))}


@router.get("/incidents")
async def list_incidents(status: Literal["open", "acknowledged", "dismissed", "resolved", "all"] = "open"):
    return {"incidents": [incidents.public(i, brief=False) for i in incidents.list_incidents(status)],
            "max_visible": int(incidents.overview.policy()["incidents"]["max_visible"])}


@router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
    inc = incidents.get(incident_id)
    if inc is None:
        raise VigilError(404, "unknown_incident", f"No incident '{incident_id}'.")
    return incidents.public(inc)


class BriefBody(BaseModel):
    deep: bool = False
    fast: bool = False          # never call the model: cached narrative or the deterministic template, at once


@router.post("/incidents/{incident_id}/brief")
async def brief_incident(incident_id: str, body: Optional[BriefBody] = None):
    """The incident's assessment (classification, red flags, key facts, recommendation, next procedure step)."""
    out = await brief.build(incident_id, deep=bool(body and body.deep), fast=bool(body and body.fast))
    if out is None:
        raise VigilError(404, "unknown_incident", f"No incident '{incident_id}'.")
    thread = chat.thread_for_incident(incident_id)
    return {"brief": out, "thread_id": thread["id"], "incident": incidents.public(incidents.get(incident_id), brief=False)}


@router.get("/incidents/{incident_id}/procedure")
async def incident_procedure(incident_id: str):
    """Vigilance procedure for this incident: steps by phase, who / when / why, automatic and manual completion."""
    inc = incidents.get(incident_id)
    if inc is None:
        raise VigilError(404, "unknown_incident", f"No incident '{incident_id}'.")
    return playbooks.view(inc)


class StepBody(BaseModel):
    done: bool = True


@router.post("/incidents/{incident_id}/procedure/{step_id}")
async def incident_procedure_step(incident_id: str, step_id: str, body: Optional[StepBody] = None):
    """Tick (or untick) a step by hand. This records the analyst's own progress; it changes nothing in the bank."""
    inc = incidents.get(incident_id)
    if inc is None:
        raise VigilError(404, "unknown_incident", f"No incident '{incident_id}'.")
    out = playbooks.set_step(inc, step_id, body.done if body else True)
    if out is None:
        raise VigilError(404, "unknown_step", f"No step '{step_id}' in this procedure.")
    incidents.HUB.publish("console", "copilot.incident", {"change": "procedure", "incident": incidents.public(incidents.get(incident_id), brief=False)})
    return out


@router.post("/incidents/{incident_id}/{action}")
async def incident_action(incident_id: str, action: Literal["ack", "dismiss", "reopen"]):
    status = {"ack": "acknowledged", "dismiss": "dismissed", "reopen": "open"}[action]
    inc = incidents.set_status(incident_id, status)
    if inc is None:
        raise VigilError(404, "unknown_incident", f"No incident '{incident_id}'.")
    return incidents.public(inc, brief=False)


@router.post("/evaluate")
async def evaluate_now():
    """Run one deterministic incident pass now (the background task also does this on every relevant event)."""
    changes = incidents.evaluate()
    return {"changes": changes, "open": len(incidents.list_incidents("open"))}


class ThreadBody(BaseModel):
    incident_id: Optional[str] = None
    title: Optional[str] = Field(default=None, max_length=120)


@router.post("/threads")
async def create_thread(body: Optional[ThreadBody] = None):
    return chat.create_thread(body.incident_id if body else None, body.title if body else None)


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str):
    t = chat.get_thread(thread_id)
    if t is None:
        raise VigilError(404, "unknown_thread", f"No thread '{thread_id}'.")
    return t


class MessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


@router.post("/threads/{thread_id}/messages")
async def post_message(thread_id: str, body: MessageBody, request: Request):
    key = request.client.host if request.client else "local"
    if not _rate_ok(key):
        raise VigilError(429, "rate_limited", "Too many messages to Vigilance — wait a minute.")
    if chat.get_thread(thread_id) is None:
        raise VigilError(404, "unknown_thread", f"No thread '{thread_id}'.")
    return StreamingResponse(chat.turn(thread_id, body.content), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
