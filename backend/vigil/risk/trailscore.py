"""TrailScore — the sender's recent journey, not just this payment.

Each step alone is ordinary (people do get new phones, add payees, raise
limits). The ordered chain inside a short window, ending in a large transfer,
is what is abnormal — so the chain carries its own bonus.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from vigil import clock, db
from vigil.contracts import RiskSignal

from vigil.settings import get_policy

STEP_TEXT = {
    "login_new_device": ("New device sign-in", "signed in from a new device"),
    "credential_changed": ("Credentials changed", "changed login credentials"),
    "payee_added": ("New payee added", "added a new payee"),
    "limit_raised": ("Transfer limit raised", "raised the transfer limit"),
    "screen_share_active": ("Screen sharing on", "had screen sharing active"),
}

JOURNEY_TYPES = tuple(STEP_TEXT) + ("simulated_context", "payment_attempt", "note_entered")


def journey(account_id: str, window_minutes: int | None = None, until_iso: str | None = None) -> list[dict[str, Any]]:
    cfg = get_policy()["sequence"]
    minutes = window_minutes if window_minutes is not None else int(cfg["window_minutes"])
    until = until_iso or clock.now_iso()
    since = clock.iso(clock.parse(until) - timedelta(minutes=minutes))
    rows = db.q(
        "SELECT id, event_type, payload, ts, source FROM events "
        "WHERE account_id = ? AND ts >= ? AND ts <= ? ORDER BY ts",
        (account_id, since, until),
    )
    out = []
    for row in rows:
        payload = db.loads(row["payload"], {}) or {}
        out.append({
            "event_id": row["id"],
            "event_type": row["event_type"],
            "label": STEP_TEXT.get(row["event_type"], (row["event_type"].replace("_", " ").capitalize(),))[0],
            "payload": payload,
            "ts": row["ts"],
            "minutes_ago": round(clock.minutes_between(row["ts"], until), 1),
            "source": row["source"],
        })
    return out


def evaluate(sender_id: str, amount_paise: int, available_paise: int) -> tuple[list[RiskSignal], list[dict[str, Any]]]:
    cfg = get_policy()["sequence"]
    events = journey(sender_id)
    first_ts: dict[str, str] = {}
    for ev in events:
        first_ts.setdefault(ev["event_type"], ev["ts"])

    signals: list[RiskSignal] = []
    for step, weight in cfg["steps"].items():
        if step not in first_ts:
            continue
        label, verb = STEP_TEXT[step]
        mins = round(clock.minutes_between(first_ts[step], clock.now_iso()))
        signals.append(RiskSignal(
            rule_id=f"SEQ_{step.upper()}", dimension="sequence", label=label,
            reason=f"The account {verb} {mins} minute{'s' if mins != 1 else ''} ago.",
            evidence={"event_type": step, "ts": first_ts[step], "minutes_ago": mins},
            contribution=float(weight),
        ))

    chain_cfg = cfg["ordered_chain"]
    order = [s for s in chain_cfg["order"] if s in first_ts]
    in_order = len(order) >= int(chain_cfg["min_steps_in_order"]) and all(
        first_ts[order[i]] < first_ts[order[i + 1]] for i in range(len(order) - 1)
    )
    if in_order:
        span = round(clock.minutes_between(first_ts[order[0]], clock.now_iso()))
        signals.append(RiskSignal(
            rule_id="SEQ_ORDERED_CHAIN", dimension="sequence", label="Takeover-style sequence",
            reason=(f"In the last {span} minutes these happened in order: "
                    + " → ".join(STEP_TEXT[s][0].lower() for s in order)
                    + " → this payment. Each step is ordinary; the sequence together is not."),
            evidence={"order": order, "span_minutes": span, "first_ts": {s: first_ts[s] for s in order}},
            contribution=float(chain_cfg["bonus"]),
        ))
    large = cfg["large_transfer_after_chain"]
    fraction = amount_paise / available_paise if available_paise > 0 else 1.0
    if len([s for s in signals if s.rule_id != "SEQ_ORDERED_CHAIN"]) >= 2 and fraction >= large["min_balance_fraction"]:
        signals.append(RiskSignal(
            rule_id="SEQ_LARGE_AFTER_CHANGES", dimension="sequence", label="Large transfer right after changes",
            reason=f"This payment is {round(fraction * 100)}% of the available balance and comes right after account changes.",
            evidence={"balance_fraction": round(fraction, 3)}, contribution=float(large["bonus"]),
        ))
    return signals, events
