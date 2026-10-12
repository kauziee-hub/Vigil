"""v8 close-monitoring routes (watchlist). All `async def` (single-threaded DB access invariant).

    GET    /api/watchlist                 -> Watchlist (pinned accounts + live suggestions, with insight)
    POST   /api/watchlist                 {account_id, note?} -> pin an account
    DELETE /api/watchlist/{account_id}    -> unpin

Changes are pushed as `watchlist.updated` on the console channel. Watching never changes a status or a tier.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from vigil.engine import watchlist

router = APIRouter(prefix="/api")


@router.get("/watchlist")
async def get_watchlist():
    return watchlist.view().model_dump(mode="json")


class WatchBody(BaseModel):
    account_id: str = Field(min_length=1, max_length=120)
    note: Optional[str] = Field(default=None, max_length=watchlist.NOTE_MAX)


@router.post("/watchlist")
async def add_to_watchlist(body: WatchBody):
    return watchlist.add(body.account_id, body.note)


@router.delete("/watchlist/{account_id}")
async def remove_from_watchlist(account_id: str):
    return {"account_id": account_id, "removed": watchlist.remove(account_id)}
