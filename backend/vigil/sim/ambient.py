"""Small, controlled stream of ordinary payments (optional, toggleable).

Seeded RNG; ordinary customers pay one of their existing payees roughly their
usual amount. Every ambient payment goes through the full intent pipeline,
so the command center shows real decisions (overwhelmingly Tier 0).
Nothing in the demo depends on this stream.

Routine-preserving: a payment is only made when BOTH accounts are still inside
their own normal range — fewer postings in the trailing 72 h than in their
busiest 72 h block of the previous 45 days. Otherwise the tick is skipped. An
unthrottled stream (one payment every 3 s) made every account ~100x busier than
its own history within minutes, which is not ordinary behaviour and correctly
read as behavioural drift by the detection layer.
"""

from __future__ import annotations

import asyncio
import random
from datetime import timedelta

from vigil import clock, db
from vigil.contracts import CreateIntentRequest
from vigil.engine import lifecycle
from vigil.engine.ledger import VigilError
from vigil.realtime import HUB
from vigil.settings import get_settings

EXCLUDE_ROLES = ("mule_collector", "mule_layer", "mule_downstream", "coercion_beneficiary", "known_mule")
STATE = {"enabled": False, "task": None, "count": 0, "errors": 0, "skipped": 0}
_rng = random.Random(7)
WINDOW_H = 72
BASELINE_DAYS = 45
CANDIDATES_PER_TICK = 8


def _within_routine(account_id: str) -> bool:
    """True if one more posting keeps the account at or below its busiest baseline 72 h block."""
    now = clock.now()
    window_start = now - timedelta(hours=WINDOW_H)
    base_start = window_start - timedelta(days=BASELINE_DAYS)
    rows = db.q("SELECT ts FROM transactions WHERE (sender_id = ? OR recipient_id = ?) AND ts >= ?",
                (account_id, account_id, clock.iso(base_start)))
    current = 0
    blocks: dict[int, int] = {}
    for r in rows:
        t = clock.parse(r["ts"])
        if t >= window_start:
            current += 1
        else:
            k = int((window_start - t).total_seconds() // (WINDOW_H * 3600))
            blocks[k] = blocks.get(k, 0) + 1
    return current < max(blocks.values(), default=0)


def _candidate() -> dict | None:
    return db.q1(
        "SELECT p.account_id, p.payee_id FROM payees p "
        "JOIN accounts s ON s.id = p.account_id JOIN accounts r ON r.id = p.payee_id "
        "WHERE s.is_demo_customer = 0 AND s.kind = 'customer' AND s.seed_role = 'legit' "
        f"AND r.seed_role NOT IN ({','.join('?' * len(EXCLUDE_ROLES))}) "
        "AND s.id NOT IN (SELECT id FROM accounts WHERE id LIKE 'anita%' OR id LIKE 'vikram%' OR id LIKE 'farah%' "
        "OR id LIKE 'joseph%' OR id LIKE 'lakshmi%') "
        "ORDER BY p.account_id, p.payee_id LIMIT 1 OFFSET ?",
        (*EXCLUDE_ROLES, _rng.randint(0, 400)),
    )


def _tick() -> None:
    row = None
    for _ in range(CANDIDATES_PER_TICK):
        c = _candidate()
        if c is not None and _within_routine(c["account_id"]) and _within_routine(c["payee_id"]):
            row = c
            break
    if row is None:
        STATE["skipped"] += 1
        return
    typical = db.scalar("SELECT CAST(AVG(amount_paise) AS INTEGER) FROM transactions WHERE sender_id=? AND recipient_id=?",
                        (row["account_id"], row["payee_id"])) or 50_000
    amount = max(10_000, int(typical * _rng.uniform(0.7, 1.2)) // 100 * 100)
    try:
        lifecycle.create(CreateIntentRequest(sender_id=row["account_id"], recipient_id=row["payee_id"],
                                             amount_paise=amount, source="ambient"))
        STATE["count"] += 1
    except VigilError:
        STATE["errors"] += 1


async def _loop() -> None:
    interval = get_settings().ambient_interval_s
    while STATE["enabled"]:
        try:
            _tick()
        except Exception:
            STATE["errors"] += 1
        await asyncio.sleep(interval)


def set_enabled(enabled: bool) -> dict:
    STATE["enabled"] = enabled
    task = STATE.get("task")
    if enabled and (task is None or task.done()):
        STATE["task"] = asyncio.get_event_loop().create_task(_loop())
    HUB.publish("console", "ambient.changed", {"enabled": enabled})
    return {"enabled": enabled, "count": STATE["count"]}
