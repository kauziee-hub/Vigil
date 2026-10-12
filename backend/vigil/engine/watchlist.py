"""Close monitoring (watchlist): accounts an analyst pinned, plus accounts the detectors suggest watching.

Pinned entries persist in the `watchlist` table (a demo reset clears them, like every other table).
Suggestions are computed live and never stored:
  * early_warning   — the live status is early warning (behaviour change or uncorroborated detector signals);
  * model_only      — model evidence is at or above the live threshold but nothing corroborates it yet;
  * pattern_memory  — structurally similar to a stored mule signature (similarity, not attribution).
Accounts that are already flagged / held / confirmed are not suggested: they are in "Needs attention".

Every entry carries the live status and its reason, the 72 h activity the detectors measure (money in / out,
forwarded share, counterparties) and `next_step`: what would move it to "flagged", or what to do now.
Read-only with respect to decisions: watching an account never changes a status or a payment tier.
"""

from __future__ import annotations

from typing import Any

from vigil import clock, db
from vigil.contracts import WatchActivity, WatchEntry, Watchlist
from vigil.engine import livestatus
from vigil.engine.ledger import VigilError

ALARM = {"flagged", "held", "confirmed_fraud"}
SHORT = {"rules": "rules", "random_forest": "RF", "gnn": "GNN", "drift": "drift", "early_warning": "early warning",
         "pattern_memory": "pattern memory"}
MAX_SUGGESTED = 12
NOTE_MAX = 200


# ── pinned (persisted) ────────────────────────────────────────────────────
def pinned() -> dict[str, dict[str, Any]]:
    return {r["account_id"]: r for r in db.q("SELECT account_id, note, added_by, added_at FROM watchlist ORDER BY added_at DESC")}


def add(account_id: str, note: str | None = None) -> dict[str, Any]:
    row = db.q1("SELECT id, kind FROM accounts WHERE id = ?", (account_id,))
    if row is None:
        raise VigilError(404, "unknown_account", f"No account '{account_id}'.")
    if row["kind"] == "external":
        raise VigilError(400, "external_account", "External counterparties are outside the bank's view and cannot be watched.")
    note = (note or "").strip()[:NOTE_MAX] or None
    at = clock.now_iso()
    db.execute("INSERT INTO watchlist(account_id, note, added_by, added_at) VALUES(?, ?, 'operator', ?) "
               "ON CONFLICT(account_id) DO UPDATE SET note = excluded.note", (account_id, note, at))
    _publish(account_id, True)
    return pinned()[account_id]


def remove(account_id: str) -> bool:
    removed = db.execute("DELETE FROM watchlist WHERE account_id = ?", (account_id,)).rowcount > 0
    if removed:
        _publish(account_id, False)
    return removed


def _publish(account_id: str, on: bool) -> None:
    from vigil.realtime import HUB
    HUB.publish("console", "watchlist.updated", {"account_id": account_id, "pinned": on})


# ── live view ─────────────────────────────────────────────────────────────
def _intel() -> tuple[Any, Any, float | None, float | None]:
    """(live snapshot, stream module, live model threshold, pattern-memory threshold) — Nones without intel."""
    try:
        from vigil.intel import live, stream
        snap = live.CACHE.current(allow_full=True)
        return snap, stream, float(stream.current_threshold()), float(live.thresholds()["pattern_memory"])
    except Exception:
        return None, None, None, None


def _model(snap: Any, a: str) -> float | None:
    if snap is None:
        return None
    best = None
    for store in (snap.rf, snap.gnn):
        v = store.get(a)
        if v is not None and (best is None or v[1] > best):
            best = float(v[1])
    return best


def _next_step(a: str, status: str, families: list[str], risk: float | None, thr: float | None,
               network: float, stream: Any) -> str:
    if status == "confirmed_fraud":
        return "Confirmed by the bank. Payments to it are held (Tier 3 floor) and TaintTrace follows the money it forwards."
    if status == "held":
        return "A payment from this account is on a scoped hold: release or reject it in Interventions."
    if status == "flagged":
        return "Flagged on corroborated mule evidence. Open the account; confirming a scam on a payment to it starts TaintTrace."
    if stream is None:
        return (f"Network score {network:.2f}: flagged at 0.60 by the rule engine alone (detection intelligence is off)."
                if network else "No detector signal yet; status changes appear here live.")
    others = [f for f in families if f not in ("early_warning", "drift")]
    structural = False
    onward = True
    try:
        if len(families) >= 2:
            structural = bool(stream.structural(a))
        if risk is not None and thr is not None and risk >= thr:
            onward = bool(stream.onward(a))
    except Exception:
        pass
    if risk is not None and thr is not None and risk >= thr:
        if any(f not in ("random_forest", "gnn") for f in families) and not onward:
            return (f"Model evidence {risk:.2f} is above the live threshold {thr:.2f}, but the account keeps what it receives. "
                    "It is flagged the moment it starts forwarding inflows.")
        if not [f for f in families if f not in ("random_forest", "gnn")]:
            return f"Model evidence {risk:.2f} is above the live threshold {thr:.2f}; flagged once one more independent family agrees."
    if len(families) >= 2 and not structural:
        return (f"{len(families)} families already agree ({', '.join(SHORT.get(f, f) for f in families)}). "
                "Flagged if a network rule fires (fan-in, pass-through, fast chain, circular flow …) "
                f"or model evidence reaches {thr:.2f} with onward money flow." if thr is not None else
                "Flagged if a network rule fires.")
    if families and not others:
        return ("Behaviour change only (" + ", ".join(SHORT.get(f, f) for f in families) + "). Not mule evidence on its own; "
                "flagged only if network structure or model evidence joins it.")
    if risk is not None and thr is not None:
        return f"Model evidence {risk:.2f} is below the live threshold {thr:.2f}; no structural rule has fired."
    return "No corroborated signal yet; status changes appear here live."


def _activity(snap: Any, a: str) -> WatchActivity | None:
    f = snap.feats.get(a) if snap is not None else None
    if not f:
        return None
    return WatchActivity(in_paise=int(round(float(f.get("total_in_amount", 0.0)) * 100)),
                         out_paise=int(round(float(f.get("total_out_amount", 0.0)) * 100)),
                         forwarded_fraction=round(float(f.get("forwarded_fraction", 0.0)), 4),
                         counterparties=int(f.get("unique_neighbors", 0)),
                         new_counterparty_ratio=round(float(f.get("new_counterparty_ratio", 0.0)), 4),
                         tx_count=int(f.get("transaction_count", 0)))


def view() -> Watchlist:
    pins = pinned()
    sts = livestatus.statuses()
    snap, stream, thr, pm_thr = _intel()
    meta = {r["id"]: r for r in db.q("SELECT id, display_name, kind FROM accounts")}
    last_active = {r["a"]: r["ts"] for r in db.q(
        "SELECT sender_id AS a, MAX(ts) AS ts FROM transactions WHERE kind != 'opening' GROUP BY sender_id")}

    sources: dict[str, list[str]] = {a: ["pinned"] for a in pins if a in meta}
    rank: dict[str, tuple] = {}
    for a, st in sts.items():
        m = meta.get(a)
        if m is None or m["kind"] == "external" or st["status"] in ALARM:
            continue
        risk = _model(snap, a)
        tags = []
        if st["status"] == "early_warning":
            tags.append("early_warning")
        if risk is not None and thr is not None and risk >= thr:
            tags.append("model_only")
        top = (snap.patterns.get(a) or [None])[0] if snap is not None else None
        if top and pm_thr is not None and top["similarity"] >= pm_thr:
            tags.append("pattern_memory")
        if tags:
            sources.setdefault(a, []).extend(tags)
            rank[a] = (0 if "early_warning" in tags else 1, -len(st.get("families") or []), -(risk or 0.0), a)
    suggested = sorted((a for a in rank if a not in pins), key=lambda a: rank[a])[:MAX_SUGGESTED]
    order = [a for a in pins if a in meta] + suggested

    entries: list[WatchEntry] = []
    for a in order:
        st = sts.get(a) or {"status": "normal", "risk": 0.0}
        p = pins.get(a)
        risk = _model(snap, a)
        fams = list(st.get("families") or [])
        top = (snap.patterns.get(a) or [None])[0] if snap is not None else None
        ew = (snap.ew.get(a) or {}).get("signals") or [] if snap is not None else []
        entries.append(WatchEntry(
            account_id=a, label=meta[a]["display_name"] or a, pinned=p is not None, sources=sources.get(a, []),
            note=p["note"] if p else None, added_at=p["added_at"] if p else None,
            status=st["status"], status_since=st.get("since"), reason=st.get("reason"),
            families_flagging=int(st.get("families_flagging") or 0), families=fams,
            network_risk=round(float(st.get("risk") or 0.0), 4), model_risk=None if risk is None else round(risk, 4),
            model_threshold=thr, role=st.get("role"), early_warning_signals=list(ew),
            pattern={"name": top["name"], "similarity": round(float(top["similarity"]), 4)} if top and top["similarity"] >= 0.5 else None,
            activity=_activity(snap, a), last_active=last_active.get(a),
            next_step=_next_step(a, st["status"], fams, risk, thr, float(st.get("risk") or 0.0), stream)))
    return Watchlist(as_of=clock.now_iso(), model_threshold=thr, pinned=sum(1 for e in entries if e.pinned),
                     suggested=sum(1 for e in entries if not e.pinned), entries=entries)
