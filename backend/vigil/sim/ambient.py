"""Live stream of ordinary everyday payments (optional, toggleable).

Seeded RNG; habit-driven: an ordinary customer pays one of their habitual
payees (weighted by how often they pay them) roughly their usual amount. Every ambient payment goes through the full intent pipeline,
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
from vigil.sim.seed import VICTIMS

EXCLUDE_ROLES = ("mule_collector", "mule_layer", "mule_downstream", "coercion_beneficiary", "known_mule")
STATE = {"enabled": False, "task": None, "count": 0, "errors": 0, "skipped": 0}
_rng = random.Random(7)
WINDOW_H = 72
BASELINE_DAYS = 45
CANDIDATES_PER_TICK = 8


MERCHANT_ALLOWANCE = 1.3   # a shop can have a few days up to 30% busier than its busiest recent stretch


def _within_routine(account_id: str, merchant: bool = False) -> bool:
    """True if one more posting keeps the account at or below its busiest baseline 72 h block
    (merchants: up to MERCHANT_ALLOWANCE x that block — ordinary trade varies more than a person's habits)."""
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
    busiest = max(blocks.values(), default=0)
    return current + 1 <= (busiest * MERCHANT_ALLOWANCE if merchant else busiest)


_PEOPLE: dict[str, list[str]] = {"ids": [], "epoch": None}


def _people() -> list[str]:
    """Ordinary customers eligible to pay (cached per seed)."""
    epoch = db.get_meta("seeded_at")
    if _PEOPLE["epoch"] != epoch:
        rows = db.q(
            "SELECT id FROM accounts WHERE kind = 'customer' AND is_demo_customer = 0 AND seed_role = 'legit' "
            "AND (persona IS NULL OR persona != 'merchant') ORDER BY id")
        excluded = set(VICTIMS) | {"dormant.savings@vigil"}
        _PEOPLE.update(ids=[r["id"] for r in rows if r["id"] not in excluded], epoch=epoch)
    return _PEOPLE["ids"]


def _candidate() -> dict | None:
    """A person and one of their habitual MERCHANTS, weighted by how often they pay them.

    Person-to-merchant only: in a time-compressed demo, person-to-person money would be re-spent within
    minutes and read as a (small) velocity chain; merchants never forward within the hour (weekly settlement).
    """
    people = _people()
    if not people:
        return None
    sender = people[_rng.randrange(len(people))]
    habits = db.q(
        "SELECT t.recipient_id AS payee, COUNT(*) AS n, CAST(AVG(t.amount_paise) AS INTEGER) AS typical "
        "FROM transactions t JOIN accounts r ON r.id = t.recipient_id "
        "WHERE t.sender_id = ? AND t.kind = 'transfer' AND t.source IN ('seed', 'ambient') AND r.persona = 'merchant' "
        f"AND r.seed_role NOT IN ({','.join('?' * len(EXCLUDE_ROLES))}) "
        "GROUP BY t.recipient_id ORDER BY t.recipient_id", (sender, *EXCLUDE_ROLES))
    if not habits:
        return None
    pick = _rng.choices(habits, weights=[h["n"] for h in habits])[0]
    return {"account_id": sender, "payee_id": pick["payee"], "typical": pick["typical"]}


def _tick() -> None:
    row = None
    for _ in range(CANDIDATES_PER_TICK):
        c = _candidate()
        if c is not None and _within_routine(c["account_id"]) and _within_routine(c["payee_id"], merchant=True):
            row = c
            break
    if row is None:
        STATE["skipped"] += 1
        return
    amount = max(1_000, int((row["typical"] or 50_000) * _rng.uniform(0.75, 1.25)) // 100 * 100)
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
