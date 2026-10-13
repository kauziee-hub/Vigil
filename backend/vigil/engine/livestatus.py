"""Live account status — ONE resolver used by the universe, live stats and attack-run evaluation.

Detection status (normal / early_warning / flagged) comes from `vigil.intel.stream.status_map()`
(Claude 2) when the intelligence layer is installed; otherwise from RingWatch scores
(≥ 0.60 flagged, ≥ 0.30 early warning). Vigil's own state is overlaid:
  confirmed_fraud  — received a payment the bank confirmed as a scam (fraud_labels)
  held             — has an active scoped hold as sender
  new              — opened < 7 days ago
  idle             — no posting inside the live window
Precedence: confirmed_fraud > held > flagged > early_warning > new > normal > idle.
Never reads seed_role / seed_attack.
"""

from __future__ import annotations

from typing import Any, Iterable

from vigil import clock, db
from vigil.graph.pathgraph import GRAPH
from vigil.risk import ringwatch

PRECEDENCE = ["idle", "normal", "new", "early_warning", "flagged", "held", "confirmed_fraud"]
RANK = {s: i for i, s in enumerate(PRECEDENCE)}
NEW_DAYS = 7
LIVE_WINDOW_MIN = 10
# reasons when the intelligence layer is absent or Vigil's own state overrides its status
REASON = {
    "confirmed_fraud": "Recipient of a bank-confirmed fraud label",
    "held": "Active scoped hold on an outgoing payment",
    "new": f"Account opened less than {NEW_DAYS} days ago",
    "idle": f"No posting in the last {LIVE_WINDOW_MIN} min",
}


def _intel_map() -> dict[str, dict[str, Any]] | None:
    try:
        from vigil.intel import stream  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return stream.status_map()
    except Exception:
        return None


def _stronger(a: str, b: str) -> str:
    return a if RANK.get(a, 0) >= RANK.get(b, 0) else b


def statuses(ids: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
    now = clock.now()
    now_t = now.timestamp()
    accounts = GRAPH.accounts
    wanted = list(ids) if ids is not None else list(accounts)
    intel = _intel_map()
    scan = {r["account_id"]: r for r in ringwatch.scan(min_score=0.0)}
    labelled = set(ringwatch.labelled_accounts())
    held = {r["account_id"] for r in db.q("SELECT account_id FROM scoped_holds WHERE released_at IS NULL")}
    live_since = now_t - LIVE_WINDOW_MIN * 60
    out: dict[str, dict[str, Any]] = {}
    for aid in wanted:
        meta = accounts.get(aid) or {}
        if meta.get("kind") == "external":
            out[aid] = {"status": "external", "risk": 0.0, "model_risk": None, "role": None, "families_flagging": 0,
                        "reason": "External counterparty outside the bank's perimeter", "families": [], "since": None}
            continue
        row = scan.get(aid)
        risk = row["score"] if row else 0.0
        im = (intel or {}).get(aid) or {}
        if intel is not None:
            status = im.get("status") or "normal"
            if status not in RANK:
                status = "normal"
        else:
            status = "flagged" if risk >= 0.6 else "early_warning" if risk >= 0.3 else "normal"
        if status == "normal":
            opened = meta.get("opened_at")
            if opened and (now_t - clock.parse(opened).timestamp()) < NEW_DAYS * 86400:
                status = "new"
            else:
                active = any(e.t >= live_since for e in GRAPH.out_edges.get(aid, ())[-5:]) or \
                    any(e.t >= live_since for e in GRAPH.in_edges.get(aid, ())[-5:])
                if not active:
                    status = "idle"
        if aid in held:
            status = _stronger("held", status)
        if aid in labelled:
            status = "confirmed_fraud"
        reason = im.get("reason") if im.get("status") == status else None
        if not reason:
            reason = REASON.get(status) or (", ".join(row["labels"]) if row and row.get("labels") else None)
        out[aid] = {"status": status, "risk": risk, "model_risk": im.get("model_risk"),
                    "role": im.get("role") or (row["role"] if row else None),
                    "families_flagging": int(im.get("families_flagging") or 0),
                    "reason": reason, "families": list(im.get("families") or []),
                    "since": im.get("since") if im.get("status") == status else None,
                    "location": im.get("location")}           # v12: corroborating location evidence (or None)
    return out


def is_warned(status: str) -> bool:
    return status in {"early_warning", "flagged", "confirmed_fraud"}


def is_detected(status: str) -> bool:
    return status in {"flagged", "confirmed_fraud"}
