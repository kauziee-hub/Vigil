"""Overview v10 read APIs (P2): money map, live tape, connections, rings, mule pipeline, exits, KPIs, brief.

All `async def`, all read-only. Logic lives in `vigil.overview` (shared with the Copilot's tools). Locations are
simulated and always carry basis + accuracy. Push: `overview.tick` on the console topic tells the page which
panels to refresh (no polling).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from vigil import geo, overview
from vigil.engine.ledger import VigilError

router = APIRouter(prefix="/api")

Window = Literal["15m", "1h", "24h", "7d"]


def _channel(channel: str) -> str:
    if channel != "all" and channel not in geo.CHANNELS:
        raise VigilError(400, "bad_channel", f"channel must be 'all' or one of {list(geo.CHANNELS)}.")
    return channel


@router.get("/geo/map")
async def geo_map(window: Window = "1h", channel: str = "all"):
    return overview.geo_map(window, _channel(channel))


@router.get("/geo/reference")
async def geo_reference():
    """Static reference: cities, ATM terminals, basis labels (simulated)."""
    return {"cities": geo.CITIES, "atms": list(geo.atm_terminals()), "basis": geo.BASIS_LABEL,
            "channels": [{"id": c, "label": overview.RAIL_LABEL[c]} for c in geo.CHANNELS], "synthetic": True}


@router.get("/geo/intel")
async def geo_intel(window: Window = "1h", account: str | None = Query(None, max_length=120),
                    city: str | None = Query(None, max_length=60), cluster: str | None = Query(None, max_length=80)):
    """Location intelligence for the Money Map (v12): impossible travel (high / low confidence), coordinated cash-out
    clusters, location-behaviour anomalies with rule / threshold / observed / basis / accuracy, the normal-geography
    picture, and context for the selected account / city / cluster. Simulated locations; corroborating evidence only."""
    from vigil.geo import intel as geo_intel_mod
    return geo_intel_mod.summary(overview.window_s(window), account=account, city=city, cluster=cluster)


@router.get("/tx/tape")
async def tx_tape(limit: int = Query(100, ge=1, le=300), since_id: str | None = None, channel: str = "all",
                  only: Literal["all", "suspicious", "fraud"] = "all", q: str | None = Query(None, max_length=60),
                  accounts: str | None = Query(None, max_length=2000)):
    acc = [a for a in (accounts or "").split(",") if a][:40] or None
    return overview.tape(limit, since_id, _channel(channel), only, q, acc)


@router.get("/tx/{tx_id}/connections")
async def tx_connections(tx_id: str):
    out = overview.connections(tx_id)
    if out is None:
        raise VigilError(404, "unknown_tx", f"No posting '{tx_id}'.")
    return out


@router.get("/overview/kpis")
async def overview_kpis(window: Window = "1h", channel: str = "all", accounts: str | None = Query(None, max_length=2000)):
    acc = {a for a in (accounts or "").split(",") if a} or None
    return overview.kpis(window, _channel(channel), acc)


@router.get("/overview/attention")
async def overview_attention():
    return overview.attention()


@router.get("/overview/rings")
async def overview_rings():
    return {"rings": overview.rings(), "collection_points": overview.collection_points()}


@router.get("/overview/pipeline")
async def overview_pipeline(days: int = Query(60, ge=1, le=180)):
    return overview.pipeline(days)


@router.get("/overview/exits")
async def overview_exits(window: Window = "24h"):
    return overview.exits(window)


@router.get("/overview/channels")
async def overview_channels(window: Window = "24h"):
    return overview.channel_mix(window)


@router.get("/overview/brief")
async def overview_brief(window: Window = "1h"):
    return overview.brief(window)


@router.get("/overview/signals")
async def overview_signals(window: Window = "24h"):
    from vigil import clock
    from datetime import timedelta
    since = clock.iso(clock.now() - timedelta(seconds=overview.window_s(window)))
    return {"cash_out_clusters": overview.cash_out_clusters(since), "impossible_travel": overview.impossible_travel(since),
            "collection_points": overview.collection_points()}
