"""World v3 — the everyday economy layered onto the demo cast.

A deterministic population of ordinary UPI users with realistic habits: each
person has a daily payment rate, a few favourite local merchants, a few friends,
category-typical amounts and a daytime rhythm. Every favourite relationship
starts weeks ago, so ordinary activity is never "first-time" in a 72 h window.
Merchants settle weekly in the small hours, long after the evening's inflows, so
they never look like pass-through accounts. All times are anchor-relative
(deterministic across resets); each simulated day keeps a daytime rhythm.

Why: a live 3D universe needs a visible transaction stream, and a stream is only
"ordinary" if each account's own history is equally busy. This module gives the
world that history (≈500 customers, ≈30 k postings over 35 days) so the ambient
stream can run at one payment every few seconds while every account stays inside
its own routine. Uses its own RNG — the demo cast and the scripted scenarios are
unaffected.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable

ECON_SEED = 20261006 + 303
EXTRA_POPULATION = 390
ECON_DAYS = 35

# (id, display name, category)
EVERYDAY_MERCHANTS = [
    ("kirana.patil@vigil", "Patil Kirana Stores", "kirana"),
    ("kirana.annapurna@vigil", "Annapurna Provision Store", "kirana"),
    ("tea.ramu@vigil", "Ramu Tea Stall", "tea"),
    ("tea.irani@vigil", "Irani Cafe", "tea"),
    ("fuel.hp.kothrud@vigil", "HP Fuel Station, Kothrud", "fuel"),
    ("fuel.io.baner@vigil", "Indian Oil, Baner", "fuel"),
    ("food.swiftbites@vigil", "SwiftBites Food Delivery", "food"),
    ("food.tiffin.anna@vigil", "Anna's Tiffin Service", "food"),
    ("metro.card@vigil", "Metro card recharge", "transit"),
    ("auto.rides@vigil", "City Auto Rides", "auto"),
    ("bakery.brownbread@vigil", "Brown Bread Bakery", "bakery"),
    ("veg.mandai@vigil", "Mandai Vegetable Vendors", "veg"),
    ("salon.style@vigil", "Style Salon", "salon"),
    ("pharma.wellness@vigil", "Wellness Pharmacy", "pharmacy"),
    ("restaurant.spice@vigil", "Spice Route Restaurant", "restaurant"),
    ("laundry.fresh@vigil", "Fresh Press Laundry", "laundry"),
    ("stationery.vidya@vigil", "Vidya Stationers", "stationery"),
    ("gym.fitzone@vigil", "FitZone Gym", "gym"),
    ("cinema.citypride@vigil", "City Pride Cinemas", "cinema"),
    ("mobile.point@vigil", "Mobile Point Recharge", "mobile"),
]
CATEGORY_RUPEES = {
    "kirana": (120, 1800), "tea": (15, 60), "fuel": (300, 2500), "food": (180, 900), "transit": (50, 300),
    "auto": (40, 300), "bakery": (40, 400), "veg": (40, 400), "salon": (150, 900), "pharmacy": (80, 1500),
    "restaurant": (300, 2500), "laundry": (100, 600), "stationery": (20, 300), "gym": (800, 2500),
    "cinema": (250, 900), "mobile": (199, 799), "p2p": (100, 3000),
}
CATEGORY_WEIGHT = {
    "kirana": 9, "tea": 10, "fuel": 4, "food": 6, "transit": 6, "auto": 6, "bakery": 4, "veg": 6, "salon": 1,
    "pharmacy": 2, "restaurant": 2, "laundry": 1, "stationery": 1, "gym": 0.5, "cinema": 1, "mobile": 1,
}
PERSONAS = [("light", 0.9, 0.30), ("regular", 1.8, 0.45), ("heavy", 3.2, 0.25)]   # name, payments/day, share
HOURS = [7, 8, 8, 9, 9, 10, 11, 12, 13, 13, 14, 16, 17, 18, 18, 19, 19, 20, 20, 21, 21, 22]


def _poisson(rng: random.Random, lam: float) -> int:
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _ist_ts(anchor: datetime, days_ago: int, hour: int, minute: int, iso: Callable[[datetime], str]) -> str | None:
    """Anchor-RELATIVE time (deterministic across resets): day `days_ago` is the 24 h span ending
    (days_ago - 1) days before the anchor; `hour` 6..23 maps to minutes after that span starts, so each
    "day" keeps a daytime rhythm (activity hours 7-22, settlement at 3 = the following small hours).
    No wall-clock dependence: two resets at different times of day produce the identical world."""
    if hour < 6:
        hour += 24                                           # 03:00 settlement = after the evening
    minute_of_span = (hour - 6) * 60 + minute
    ts = anchor - timedelta(days=days_ago) + timedelta(minutes=minute_of_span)
    if ts >= anchor - timedelta(minutes=30):
        return None
    return iso(ts)


def _amount(rng: random.Random, category: str, scale: float) -> int:
    lo, hi = CATEGORY_RUPEES[category]
    rupees = math.exp(rng.uniform(math.log(lo), math.log(hi))) * scale
    return max(10, int(round(rupees))) * 100


def build(*, anchor: datetime, used: set[str], first: list[str], last: list[str], existing_population: list[str],
          make_account: Callable[..., None], plan: Callable[..., None], iso: Callable[[datetime], str]) -> dict[str, Any]:
    """Create merchants + extra population and plan their history. Returns the new account ids."""
    rng = random.Random(ECON_SEED)
    for aid, name, _cat in EVERYDAY_MERCHANTS:
        make_account(aid, name, days_old=rng.randint(600, 3000), persona="merchant")
        plan("ext:opening", aid, rng.randint(50_000, 150_000) * 100, _ist_ts(anchor, ECON_DAYS + 8, 6, 0, iso),
             kind="opening", note="opening balance")

    people: list[str] = []
    attempts = 0
    while len(people) < EXTRA_POPULATION and attempts < 20_000:
        attempts += 1
        handle = f"{rng.choice(first)}.{rng.choice(last)}{rng.randint(1, 99)}@vigil"
        if handle in used:
            continue
        used.add(handle)
        people.append(handle)
        name = handle.split("@")[0].rstrip("0123456789").replace(".", " ").title()
        make_account(handle, name, days_old=rng.randint(120, 3500))

    everyone = existing_population + people
    merchants = [(aid, cat) for aid, _n, cat in EVERYDAY_MERCHANTS]
    weights = [CATEGORY_WEIGHT[c] for _a, c in merchants]
    merchant_in: dict[str, list[tuple[str, int]]] = defaultdict(list)

    for person in people:
        name, rate, _share = rng.choices(PERSONAS, weights=[p[2] for p in PERSONAS])[0]
        scale = {"light": 0.8, "regular": 1.0, "heavy": 1.3}[name]
        opening = rng.randint(30_000, 2_50_000) * 100
        plan("ext:opening", person, opening, _ist_ts(anchor, ECON_DAYS + 7, 6, 0, iso), kind="opening",
             note="opening balance")
        salary = rng.randint(25_000, 1_20_000) * 100
        pay_day = rng.randint(1, 5)
        for month_back in (0, 30):
            ts = _ist_ts(anchor, month_back + pay_day, 10, rng.randint(0, 59), iso)
            if ts:
                plan("ext:employer", person, salary, ts, kind="external_credit", note="salary")
        favs: list[tuple[str, str]] = []
        while len(favs) < rng.randint(3, 6):
            m = rng.choices(merchants, weights=weights)[0]
            if m not in favs:
                favs.append(m)
        friends = [f for f in rng.sample(everyone, 4) if f != person][: rng.randint(1, 3)]
        targets: list[tuple[str, str]] = favs + [(f, "p2p") for f in friends]
        t_weights = [CATEGORY_WEIGHT.get(c, 2.0) for _t, c in favs] + [1.5] * len(friends)
        # relationships start weeks ago (never "first-time" inside a 72 h window)
        for target, cat in targets:
            ts = _ist_ts(anchor, ECON_DAYS + rng.randint(1, 5), rng.choice(HOURS), rng.randint(0, 59), iso)
            amt = _amount(rng, cat, scale)
            plan(person, target, amt, ts, note=cat)
            if cat != "p2p":
                merchant_in[target].append((ts, amt))
        for days_ago in range(ECON_DAYS, 0, -1):
            for _ in range(_poisson(rng, rate)):
                target, cat = rng.choices(targets, weights=t_weights)[0]
                ts = _ist_ts(anchor, days_ago, rng.choice(HOURS), rng.randint(0, 59), iso)
                if ts is None:
                    continue
                amt = _amount(rng, cat, scale)
                plan(person, target, amt, ts, note=cat)
                if cat != "p2p":
                    merchant_in[target].append((ts, amt))

    # weekly merchant settlement in the small hours — 85% of the week's takings, hours after the last inflow
    for aid, _cat in merchants:
        offset = rng.randint(0, 6)
        rows = sorted(merchant_in.get(aid, []))
        for days_ago in range(ECON_DAYS, 0, -1):
            if (days_ago + offset) % 7:
                continue
            ts = _ist_ts(anchor, days_ago, 3, 0, iso)
            if ts is None:
                continue
            week = [a for t, a in rows if t < ts and t >= _ist_ts(anchor, days_ago + 7, 3, 0, iso)]
            if week:
                plan(aid, "ext:other-bank", int(sum(week) * 0.85) // 100 * 100, ts, kind="external_debit",
                     note="settlement")
    return {"merchants": [m for m, _c in merchants], "people": people}
