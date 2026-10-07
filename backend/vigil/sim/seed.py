"""Deterministic demo world. Same RNG seed + same relative timeline every reset.

Timestamps are anchored to the moment of seeding (so "last 72 hours" windows
are meaningful) but every offset, amount, id and edge is identical across
resets. Ground truth (`seed_role`, `seed_attack`) is stored for metrics only;
no scorer reads it.

The cast:
  ramesh@vigil   — demo payer, Acts 1–3 and 5 (pays grocer weekly, landlord monthly)
  sunita@vigil   — 67-year-old retired teacher, Act 4 (coercion); trusted contact: son Arjun
  kiran.traders  — Act 2 recipient: 9-day-old account already forwarding money fast
  zenith.exports — layering account downstream of kiran.traders
  ~120 ordinary customers + merchants generating background history
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from vigil import clock, db
from vigil.engine import ledger
from vigil.engine.ledger import VigilError
from vigil.graph.pathgraph import GRAPH
from vigil.risk import taint

SEED = 20261006
HISTORY_DAYS = 95

EXTERNAL = [
    ("ext:opening", "Opening balances (bookkeeping)"),
    ("ext:employer", "Salary & pension credits (other banks)"),
    ("ext:atm", "ATM / cash withdrawal (leaves our view)"),
    ("ext:other-bank", "Other banks (outside our perimeter)"),
]

MERCHANTS = [
    ("meena.grocer@vigil", "Meena General Stores"),
    ("medplus.pharma@vigil", "MedPlus Pharmacy, Kothrud"),
    ("bescom.power@vigil", "Electricity board (BESCOM)"),
    ("jio.recharge@vigil", "Jio recharge"),
    ("chai.point@vigil", "Chai Point"),
    ("sharma.tuitions@vigil", "Sharma Tuitions"),
    ("landlord.iyer@vigil", "R. Iyer (landlord)"),
    ("fresh.dairy@vigil", "Fresh Dairy"),
]

FIRST = ["arjun", "diya", "kabir", "isha", "rohan", "ananya", "vikas", "naina", "harsh", "kavya", "sameer",
         "riya", "yash", "pooja", "nikhil", "tanvi", "aditya", "shruti", "manav", "aisha", "kunal", "meera",
         "varun", "sana", "ravi", "lina", "gopal", "nina", "farhan", "leela", "siddharth", "ira", "dev",
         "maya", "arun", "kiran", "neha", "amit", "sonia", "vijay"]
LAST = ["sharma", "patel", "nair", "iyer", "khan", "das", "reddy", "gupta", "joshi", "menon", "rao", "singh",
        "verma", "kaur", "mishra", "pillai", "bose", "mehta", "desai", "naik"]

VICTIMS = ["anita.s@vigil", "vikram.p@vigil", "farah.k@vigil", "joseph.d@vigil", "lakshmi.n@vigil"]
DOWNSTREAM = ["pooja.m@vigil", "rahul.m@vigil"]
SMURF_TARGETS = ["amit.k@vigil", "neha.b@vigil", "sanjay.t@vigil", "ritu.v@vigil"]
EARLY_SENDERS = ["deepak.r@vigil", "sneha.j@vigil", "imran.q@vigil"]


def _acct(anchor: datetime, aid: str, name: str, *, kind: str = "customer", days_old: int = 900,
          device: str | None = None, persona: str | None = None, demo: bool = False,
          role: str = "legit", limit_paise: int = 10_000_000) -> None:
    device = device or (f"dev-{aid.split('@')[0]}" if kind == "customer" else None)
    opened = clock.iso(anchor - timedelta(days=days_old))
    db.insert("accounts", {
        "id": aid, "display_name": name, "kind": kind, "bank_code": "VGL", "primary_device": device,
        "opened_at": opened, "balance_paise": 0, "daily_limit_paise": limit_paise, "persona": persona,
        "is_demo_customer": 1 if demo else 0, "seed_role": role,
    })
    if device:
        db.insert("account_devices", {"account_id": aid, "device_id": device, "first_seen": opened})


def seed(anchor: datetime | None = None) -> dict[str, Any]:
    from vigil.engine import hooks

    with hooks.suspended():
        return _seed(anchor)


def _seed(anchor: datetime | None = None) -> dict[str, Any]:
    rng = random.Random(SEED)
    anchor = anchor or clock.now()
    db.wipe()
    taint.invalidate()

    def at(**delta: float) -> str:
        return clock.iso(anchor - timedelta(**delta))

    planned: list[dict[str, Any]] = []

    def plan(sender: str, recipient: str, amount: int, ts: str, kind: str = "transfer", note: str | None = None,
             attack: str | None = None) -> None:
        planned.append({"sender_id": sender, "recipient_id": recipient, "amount_paise": int(amount), "ts": ts,
                        "kind": kind, "note": note, "seed_attack": attack})

    with db.tx():
        for aid, name in EXTERNAL:
            _acct(anchor, aid, name, kind="external", role="external")
        for aid, name in MERCHANTS:
            _acct(anchor, aid, name, days_old=rng.randint(700, 3000), persona="merchant")

        # ── demo cast ──
        _acct(anchor, "ramesh@vigil", "Ramesh Kumar", days_old=2200, device="dev-ramesh-pixel7", demo=True,
              persona="Salaried engineer, Bengaluru. Pays his grocer weekly and rent monthly.")
        _acct(anchor, "sunita@vigil", "Sunita Rao", days_old=4100, device="dev-sunita-galaxy-a12", demo=True,
              persona="67, retired teacher, Pune. Pension in, small payments out. Son Arjun is her trusted contact.",
              limit_paise=10_000_000)
        _acct(anchor, "kiran.traders@vigil", "Kiran Traders", days_old=9, device="dev-kt-redmi",
              persona="Opened 9 days ago.", role="mule_collector")
        _acct(anchor, "zenith.exports@vigil", "Zenith Exports", days_old=40, device="dev-zx-01", role="mule_layer")
        _acct(anchor, "rk.legal.services@vigil", "RK Legal Services", days_old=2, device="dev-rkl-01",
              role="coercion_beneficiary")
        _acct(anchor, "quickloan.agent@vigil", "QuickLoan Agent", days_old=20, device="dev-ql-1", role="known_mule")
        for aid in DOWNSTREAM:
            _acct(anchor, aid, aid.split("@")[0].replace(".", " ").title(), days_old=rng.randint(15, 60),
                  device="dev-shared-z9", role="mule_downstream")
        for aid in VICTIMS + SMURF_TARGETS + EARLY_SENDERS:
            _acct(anchor, aid, aid.split("@")[0].replace(".", " ").title(), days_old=rng.randint(400, 3000))

        # ── ordinary population ──
        population: list[str] = []
        used = {a for a, _ in MERCHANTS} | {"ramesh@vigil", "sunita@vigil"} | set(VICTIMS + SMURF_TARGETS + EARLY_SENDERS)
        while len(population) < 110:
            handle = f"{rng.choice(FIRST)}.{rng.choice(LAST)}@vigil"
            if handle in used:
                continue
            used.add(handle)
            population.append(handle)
            _acct(anchor, handle, handle.split("@")[0].replace(".", " ").title(), days_old=rng.randint(200, 3500))

        customers = population + VICTIMS + SMURF_TARGETS + EARLY_SENDERS

        # opening balances (bookkeeping journal from outside the perimeter)
        opening = {aid: rng.randint(40_000, 300_000) * 100 for aid in customers}
        opening.update({"ramesh@vigil": 90_000_00, "sunita@vigil": 4_80_000_00, "kiran.traders@vigil": 2_000_00,
                        "zenith.exports@vigil": 35_000_00, "rk.legal.services@vigil": 1_000_00,
                        "quickloan.agent@vigil": 5_000_00, "pooja.m@vigil": 3_000_00, "rahul.m@vigil": 2_500_00})
        for v in VICTIMS:
            opening[v] = max(opening[v], 2_00_000_00)
        for aid, _ in MERCHANTS:
            opening[aid] = rng.randint(50_000, 200_000) * 100
        for aid, amount in sorted(opening.items()):
            days = min(HISTORY_DAYS + 5, int(db.scalar("SELECT julianday(?) - julianday(opened_at) FROM accounts WHERE id=?",
                                                        (clock.iso(anchor), aid))) )
            plan("ext:opening", aid, amount, at(days=max(days, 0), hours=1), kind="opening", note="opening balance")

        # ── ordinary behaviour ──
        merchant_ids = [a for a, _ in MERCHANTS if a != "landlord.iyer@vigil"]
        for aid in customers:
            salary = rng.randint(35_000, 140_000) * 100
            payees = rng.sample(merchant_ids, 2) + rng.sample(population, 2)
            typical = {p: rng.randint(200, 6_000) * 100 for p in payees}
            for month in range(3):
                plan("ext:employer", aid, salary, at(days=month * 30 + rng.randint(1, 3), hours=rng.randint(1, 10)),
                     kind="external_credit", note="salary")
            for _ in range(rng.randint(8, 16)):
                p = rng.choice(payees)
                amount = max(100, int(typical[p] * rng.uniform(0.6, 1.4)) // 100 * 100)
                plan(aid, p, amount, at(days=rng.uniform(0.5, HISTORY_DAYS - 2), minutes=rng.randint(0, 600)))
            if rng.random() < 0.25:
                plan(aid, "ext:atm", rng.randint(2, 10) * 1000_00, at(days=rng.uniform(3, 80)), kind="external_debit")
        # merchants settle to other banks occasionally
        for aid in merchant_ids:
            plan(aid, "ext:other-bank", 40_000_00, at(days=rng.uniform(10, 60)), kind="external_debit", note="settlement")

        # ── Ramesh: weekly grocer, monthly rent, salary ──
        for week in range(13):
            plan("ramesh@vigil", "meena.grocer@vigil", rng.randint(4, 9) * 100_00 // 1, at(days=week * 7 + 2, hours=rng.randint(9, 12)),
                 note="groceries")
        for month in range(3):
            plan("ext:employer", "ramesh@vigil", 1_10_000_00, at(days=month * 30 + 1, hours=3), kind="external_credit", note="salary")
            plan("ramesh@vigil", "landlord.iyer@vigil", 38_000_00, at(days=month * 30 + 3, hours=2), note="rent")
            plan("ramesh@vigil", "jio.recharge@vigil", 799_00, at(days=month * 30 + 10), note="recharge")
            plan("ramesh@vigil", "bescom.power@vigil", rng.randint(1_400, 2_600) * 100, at(days=month * 30 + 12), note="electricity")
        for other in rng.sample(population, 3):
            plan(other, "landlord.iyer@vigil", 26_000_00, at(days=rng.randint(2, 6)), note="rent")
            plan(other, "landlord.iyer@vigil", 26_000_00, at(days=rng.randint(32, 36)), note="rent")

        # ── Sunita: pension in, small payments out ──
        for month in range(3):
            plan("ext:employer", "sunita@vigil", 42_000_00, at(days=month * 30 + 2, hours=4), kind="external_credit", note="pension")
            plan("sunita@vigil", "medplus.pharma@vigil", rng.randint(1_200, 3_000) * 100, at(days=month * 30 + 6), note="medicines")
            plan("sunita@vigil", "bescom.power@vigil", rng.randint(900, 1_800) * 100, at(days=month * 30 + 9), note="electricity")
            plan("sunita@vigil", "fresh.dairy@vigil", 1_850_00, at(days=month * 30 + 15), note="milk")

        # ── Act 2 recipient already behaving like a pass-through (last ~2 days) ──
        for i, (sender, amount, hours_ago) in enumerate(zip(EARLY_SENDERS, [21_500_00, 24_000_00, 19_000_00], [52, 37, 21])):
            plan(sender, "kiran.traders@vigil", amount, at(hours=hours_ago), note="order payment", attack="early_inflow")
            plan("kiran.traders@vigil", "zenith.exports@vigil", amount - 500_00, at(hours=hours_ago, minutes=-14 - i * 3),
                 note="supplier", attack="early_forward")
        # dormant savings account for the dormant-activation attack (fixed values; no shared RNG)
        _acct(anchor, "dormant.savings@vigil", "Dormant Savings (R. Menon)", days_old=1100, device="dev-dormant-old")
        plan("ext:opening", "dormant.savings@vigil", 60_000_00, at(days=100, hours=1), kind="opening", note="opening balance")
        plan("dormant.savings@vigil", "bescom.power@vigil", 1_450_00, at(days=90), note="electricity")
        plan("dormant.savings@vigil", "meena.grocer@vigil", 2_100_00, at(days=82), note="groceries")
        plan("dormant.savings@vigil", "jio.recharge@vigil", 399_00, at(days=76), note="recharge")
        # zenith has a little legitimate-looking history
        plan("zenith.exports@vigil", "ext:other-bank", 20_000_00, at(days=12), kind="external_debit")
        plan("quickloan.agent@vigil", "ext:atm", 3_000_00, at(days=3), kind="external_debit")
        plan(rng.choice(population), "rk.legal.services@vigil", 500_00, at(days=1, hours=2), note="consultation")

    # post everything in time order through the real ledger (debit + credit, integer paise)
    planned.sort(key=lambda p: (p["ts"], p["sender_id"], p["recipient_id"]))
    posted = skipped = 0
    with db.tx():
        for p in planned:
            try:
                ledger.post(sender_id=p["sender_id"], recipient_id=p["recipient_id"], amount_paise=p["amount_paise"],
                            kind=p["kind"], ts=p["ts"], note=p["note"], source="seed", seed_attack=p["seed_attack"],
                            check_funds=p["kind"] not in {"opening", "external_credit"})
                posted += 1
            except VigilError:
                skipped += 1

    with db.tx():
        # simulated external registry (what a bank might receive from a shared-intelligence feed)
        registry = [
            ("kiran.traders@vigil", "reported", 0.62, ["VICTIM_REPORT", "RAPID_PASS_THROUGH"],
             "Simulated shared fraud registry", at(hours=20)),
            ("quickloan.agent@vigil", "confirmed_mule", 0.95, ["CONFIRMED_MULE", "MULTIPLE_VICTIM_REPORTS"],
             "Simulated shared fraud registry", at(days=2)),
            ("lucky.prize@vigil", "watchlist", 0.40, ["LINKED_TO_REPORTED_DEVICE"], "Simulated telecom-linked risk list",
             at(days=5)),
        ]
        for ident, status, score, codes, source, ts in registry:
            db.insert("external_intel", {"identifier": ident, "status": status, "risk_score": score,
                                         "reason_codes": db.dumps(codes), "source": source, "last_updated": ts})
        for aid in [a for a, _ in MERCHANTS] + ["ramesh@vigil", "sunita@vigil"]:
            db.insert("external_intel", {"identifier": aid, "status": "clean", "risk_score": 0.02,
                                         "reason_codes": "[]", "source": "Simulated shared fraud registry",
                                         "last_updated": at(days=1)})
        db.insert("trusted_contacts", {"id": "TC-000001", "account_id": "sunita@vigil", "name": "Arjun Rao",
                                       "relation": "son", "phone_masked": "+91 98xxxxxx21", "token": "arjun",
                                       "nominated_at": at(days=200)})
        db.insert("trusted_contacts", {"id": "TC-000002", "account_id": "ramesh@vigil", "name": "Priya Kumar",
                                       "relation": "spouse", "phone_masked": "+91 99xxxxxx07", "token": "priya",
                                       "nominated_at": at(days=400)})
        db.set_meta("seeded_at", clock.iso(anchor))
        db.set_meta("seed", str(SEED))

    GRAPH.load()
    taint.invalidate()
    return {"accounts": int(db.scalar("SELECT COUNT(*) FROM accounts")), "transactions": posted,
            "skipped": skipped, "anchor": clock.iso(anchor), "system_total_paise": ledger.system_total()}


def ensure_seeded() -> dict[str, Any] | None:
    if db.scalar("SELECT COUNT(*) FROM accounts"):
        GRAPH.load()
        return None
    return seed()
