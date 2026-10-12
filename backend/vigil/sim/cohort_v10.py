"""Onboarding cohort (overview-v10 P1f): ~40 LEGITIMATE new accounts opened over the last 60 days.

Why: the Overview's mule pipeline (opened → funded → active → passing through → exited) is only informative if
ordinary new customers flow through its early stages and fall out, so "new" never reads as "mule".

Rules that keep the existing demo world intact:
* Runs AFTER the main seed with its own RNG (`random.Random(SEED ^ 0xC0DE10)`); the main RNG stream, the seeded
  rows and their ids are untouched (tests/test_world_digest.py).
* Every posting is tagged `source='cohort_v10'`; ids are allocated after the main seed's.
* Behaviour is ordinary: a first credit from outside the bank, then everyday merchant spending that keeps a
  healthy balance. Live-window (72 h) activity is light, so no network rule or early-warning signal is driven.
* Includes the hard negatives the plan asks for — a freelancer paid by many clients who keeps the money, a new
  shop with fast but legitimate turnover — placed well before the live window.
* Six benign shared-device pairs (family / shop): two accounts per device (the shared-device rule needs three).
Account ids look like `first.last.NN@vigil` — a shape the main seed and the economy never produce.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from vigil import clock, db

SEED = 20261006 ^ 0xC0DE10
N_ACCOUNTS = 40
EXTRA_ACCOUNTS = ("ext:intl-wire",)     # v10 external sink (international wires); appended, not in the main seed

FIRST = ["aarav", "vihaan", "aditi", "saanvi", "ishaan", "myra", "reyansh", "anika", "kiara", "advik", "zoya",
         "arnav", "tara", "veer", "nisha", "rudra", "pari", "dhruv", "mira", "kabir"]
LAST = ["sharma", "iyer", "nair", "reddy", "khan", "patel", "das", "menon", "gill", "bhat", "rao", "sen"]
# (kind, share, opened_via weights, persona)
KINDS = [
    ("student", 12, "Student. Pocket money / stipend from family at another bank; small everyday spends."),
    ("salaried", 12, "Salaried, first job. Monthly salary in; rent, food and bills out."),
    ("freelancer", 8, "Freelancer. Paid by clients, keeps most of it."),
    ("shop", 8, "New shop owner. Daily takings in, weekly supplier payment out."),
]
VIA = [("app", 55), ("branch", 25), ("agent", 12), ("kiosk", 8)]


@lru_cache(maxsize=1)
def _plan_accounts() -> tuple[dict[str, Any], ...]:
    """Pure (no DB): the cohort's accounts, in creation order."""
    rng = random.Random(SEED)
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for kind, n, persona in KINDS:
        for _ in range(n):
            while True:
                aid = f"{rng.choice(FIRST)}.{rng.choice(LAST)}.{rng.randint(10, 99)}@vigil"
                if aid not in used:
                    used.add(aid)
                    break
            via = rng.choices([v for v, _ in VIA], weights=[w for _, w in VIA])[0]
            out.append({"id": aid, "kind": kind, "persona": persona, "opened_via": via,
                        "days_old": rng.randint(1, 60), "hour": rng.randint(8, 19)})
    # three accounts opened in the last 3 days (pipeline: opened / funded only)
    for a in out[::13][:3]:
        a["days_old"] = 1 + out.index(a) % 3
    # six benign shared-device pairs: (student, salaried) family pairs and (shop, helper) pairs
    pairs = [(out[0], out[12]), (out[3], out[15]), (out[6], out[18]), (out[32], out[33]), (out[34], out[35]),
             (out[24], out[25])]
    for i, (a, b) in enumerate(pairs):
        dev = f"dev-{'shop' if a['kind'] == 'shop' else 'family'}-{i + 1:02d}"
        a["device"] = b["device"] = dev
        a["shared_note"] = b["shared_note"] = "shop counter phone" if a["kind"] == "shop" else "family phone"
    for a in out:
        a.setdefault("device", f"dev-{a['id'].split('@')[0].replace('.', '-')}")
    return tuple(out)


def account_ids() -> list[str]:
    """Every account v10 appends after the main seed (cohort + new external sinks)."""
    return [a["id"] for a in _plan_accounts()] + list(EXTRA_ACCOUNTS)


def ensure() -> bool:
    """Append the cohort to a database seeded before v10 (anchored at its seeding time). Returns True if added."""
    from vigil.engine import hooks
    from vigil.graph.pathgraph import GRAPH
    if db.q1("SELECT 1 FROM accounts WHERE id = ?", (_plan_accounts()[0]["id"],)):
        return False
    seeded = db.get_meta("seeded_at")
    if not seeded:
        return False
    with hooks.suspended():
        build(clock.parse(seeded))
    GRAPH.load()
    return True


def build(anchor: datetime) -> dict[str, Any]:
    """Create the cohort and post its history through the real ledger (hooks are suspended by the caller)."""
    from vigil import geo
    from vigil.engine import ledger
    from vigil.engine.ledger import VigilError

    rng = random.Random(SEED + 1)
    merchants = [r["id"] for r in db.q(
        "SELECT id FROM accounts WHERE persona = 'merchant' AND id NOT IN ('landlord.iyer@vigil') ORDER BY id")]
    clients = [r["id"] for r in db.q(
        "SELECT id FROM accounts WHERE kind = 'customer' AND seed_role = 'legit' AND is_demo_customer = 0 "
        "AND (persona IS NULL OR persona != 'merchant') ORDER BY id")][:60]
    with db.tx():
        if not db.q1("SELECT id FROM accounts WHERE id = 'ext:intl-wire'"):
            db.insert("accounts", {"id": "ext:intl-wire", "display_name": "International wire (leaves the country)",
                                   "kind": "external", "bank_code": "VGL", "primary_device": None,
                                   "opened_at": clock.iso(anchor - timedelta(days=900)), "balance_paise": 0,
                                   "daily_limit_paise": 10_000_000, "persona": None, "is_demo_customer": 0,
                                   "seed_role": "external"})
        for a in _plan_accounts():
            opened = anchor - timedelta(days=a["days_old"], hours=a["hour"])
            home = geo.home_for(a["id"])
            db.insert("accounts", {
                "id": a["id"], "display_name": a["id"].split("@")[0].rsplit(".", 1)[0].replace(".", " ").title(),
                "kind": "customer", "bank_code": "VGL", "primary_device": a["device"], "opened_at": clock.iso(opened),
                "balance_paise": 0, "daily_limit_paise": 10_000_000,
                "persona": a["persona"] + (f" Shares a {a['shared_note']}." if a.get("shared_note") else ""),
                "is_demo_customer": 0, "seed_role": "legit", "opened_via": a["opened_via"], "opened_city": home,
            })
            db.insert("account_devices", {"account_id": a["id"], "device_id": a["device"], "first_seen": clock.iso(opened)})

    planned: list[dict[str, Any]] = []

    bounds = {"lo": anchor}

    def plan(s: str, r: str, amt: int, t: datetime, kind: str = "transfer", note: str = "", channel: str = "upi",
             device: str | None = None) -> None:
        if t >= anchor or t < bounds["lo"]:           # never before the account opened, never in the future
            return
        planned.append({"sender_id": s, "recipient_id": r, "amount_paise": int(amt) // 100 * 100, "ts": clock.iso(t),
                        "kind": kind, "note": note, "channel": channel, "device_id": device})

    for i, a in enumerate(_plan_accounts()):
        aid, opened = a["id"], anchor - timedelta(days=a["days_old"], hours=a["hour"])
        bounds["lo"] = opened
        first_credit = opened + timedelta(hours=rng.randint(2, 60))
        spend_ch = rng.choice(["upi", "upi", "upi", "card"])
        live_cut = anchor - timedelta(hours=80)          # keep heavy activity out of the 72 h live window
        if a["kind"] == "student":
            amt = rng.randint(3_000, 8_000) * 100
            plan("ext:other-bank", aid, amt, first_credit, "external_credit", "from family")
            t = first_credit + timedelta(hours=rng.randint(6, 40))
            for _ in range(rng.randint(2, 5)):
                plan(aid, rng.choice(merchants), rng.randint(80, 600) * 100, min(t, live_cut), note="food",
                     channel=spend_ch, device=a["device"])
                t += timedelta(days=rng.uniform(1.5, 6))
        elif a["kind"] == "salaried":
            amt = rng.randint(30_000, 90_000) * 100
            plan("ext:employer", aid, amt, first_credit, "external_credit", "salary")
            t = first_credit + timedelta(hours=rng.randint(10, 72))
            for _ in range(rng.randint(3, 6)):
                plan(aid, rng.choice(merchants), rng.randint(300, 4_000) * 100, min(t, live_cut), note="bills",
                     channel=spend_ch, device=a["device"])
                t += timedelta(days=rng.uniform(2, 7))
        elif a["kind"] == "freelancer":
            n_clients = 6 if i == 24 else rng.randint(1, 3)        # account 24: hard negative — many clients
            t = first_credit
            for c in rng.sample(clients, n_clients):
                plan(c, aid, rng.randint(4_000, 15_000) * 100, min(t, live_cut), note="invoice")
                t += timedelta(hours=rng.randint(5, 30))
            plan(aid, rng.choice(merchants), rng.randint(500, 2_500) * 100, min(t + timedelta(days=2), live_cut),
                 note="supplies", channel=spend_ch, device=a["device"])
        else:  # shop: takings in from regulars, weekly supplier payment out (hard negative: account 32)
            t = first_credit
            regulars = rng.sample(clients, 8 if i == 32 else 4)
            for d in range(rng.randint(5, 12)):
                plan(rng.choice(regulars), aid, rng.randint(150, 900) * 100, min(t, live_cut), note="shop purchase")
                t += timedelta(hours=rng.randint(8, 30))
            plan("ext:opening", aid, 5_000_00, opened + timedelta(hours=1), "opening", "opening float")
            plan(aid, "ext:other-bank", rng.randint(2_000, 6_000) * 100, min(t, live_cut), "external_debit",
                 "supplier payment", device=a["device"])
        # most accounts made one small everyday payment recently (looks alive, drives nothing)
        if a["days_old"] > 3 and rng.random() < 0.6:
            plan(aid, rng.choice(merchants), rng.randint(60, 400) * 100,
                 anchor - timedelta(hours=rng.randint(6, 60)), note="tea", channel=spend_ch, device=a["device"])

    planned.sort(key=lambda p: (p["ts"], p["sender_id"], p["recipient_id"]))
    posted = skipped = 0
    with db.tx():
        for p in planned:
            try:
                ledger.post(sender_id=p["sender_id"], recipient_id=p["recipient_id"], amount_paise=p["amount_paise"],
                            kind=p["kind"], ts=p["ts"], note=p["note"], source="cohort_v10", channel=p["channel"],
                            device_id=p["device_id"], check_funds=p["kind"] not in {"opening", "external_credit"})
                posted += 1
            except VigilError:
                skipped += 1
    return {"accounts": len(_plan_accounts()), "transactions": posted, "skipped": skipped}
