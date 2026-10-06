"""Small, controlled stream of ordinary payments (optional, toggleable).

Seeded RNG; ordinary customers pay one of their existing payees roughly their
usual amount. Every ambient payment goes through the full intent pipeline,
so the command center shows real decisions (overwhelmingly Tier 0).
Nothing in the demo depends on this stream.
"""

from __future__ import annotations

import asyncio
import random

from vigil import db
from vigil.contracts import CreateIntentRequest
from vigil.engine import lifecycle
from vigil.engine.ledger import VigilError
from vigil.realtime import HUB
from vigil.settings import get_settings

EXCLUDE_ROLES = ("mule_collector", "mule_layer", "mule_downstream", "coercion_beneficiary", "known_mule")
STATE = {"enabled": False, "task": None, "count": 0, "errors": 0}
_rng = random.Random(7)


def _tick() -> None:
    row = db.q1(
        "SELECT p.account_id, p.payee_id FROM payees p "
        "JOIN accounts s ON s.id = p.account_id JOIN accounts r ON r.id = p.payee_id "
        "WHERE s.is_demo_customer = 0 AND s.kind = 'customer' AND s.seed_role = 'legit' "
        f"AND r.seed_role NOT IN ({','.join('?' * len(EXCLUDE_ROLES))}) "
        "AND s.id NOT IN (SELECT id FROM accounts WHERE id LIKE 'anita%' OR id LIKE 'vikram%' OR id LIKE 'farah%' "
        "OR id LIKE 'joseph%' OR id LIKE 'lakshmi%') "
        "ORDER BY p.account_id, p.payee_id LIMIT 1 OFFSET ?",
        (*EXCLUDE_ROLES, _rng.randint(0, 400)),
    )
    if row is None:
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
