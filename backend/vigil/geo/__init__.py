"""SIMULATED locations for the Overview money map (overview-v10 P1).

Every location here is synthetic and derived deterministically from hashes of account / transaction ids — never
from ground-truth labels (`seed_role`, `seed_attack`). Locations are display and investigation context ONLY: no
detector, score or payment tier reads them.

Each stamped posting carries a *basis* (how a real bank would know the place) and an *accuracy* (how precise that
basis is), so the UI can always say "Simulated location · ATM terminal · ±25 m" instead of pretending to be exact.

    basis          when                               accuracy
    atm_terminal   cash withdrawal (→ ext:atm)        ±25 m
    device_gps     app payment with a known device     ±30 m   (account anchor + bounded daily wander)
    merchant_pos   card / POS payment                 ±2 km   (the merchant's city)
    ip             web / no device (historical rows)  ±3–15 km
    kyc_home       credits from outside the bank       city-level (±5 km)
    branch         assisted account opening            ±100 m
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = json.loads((Path(__file__).with_name("cities.json")).read_text(encoding="utf-8"))
CITIES: list[dict[str, Any]] = _DATA["cities"]
BY_NAME: dict[str, dict[str, Any]] = {c["city"]: c for c in CITIES}
DOMESTIC = [c for c in CITIES if c["kind"] == "domestic"]
FOREIGN = [c for c in CITIES if c["kind"] == "foreign"]

ACCURACY_M = {"atm_terminal": 25, "device_gps": 30, "merchant_pos": 2000, "kyc_home": 5000, "branch": 100}
BASIS_LABEL = {"atm_terminal": "ATM terminal", "device_gps": "Device GPS", "merchant_pos": "Merchant POS",
               "ip": "IP address", "kyc_home": "KYC home address", "branch": "Branch"}
TIER_WEIGHT = {1: 0.55, 2: 0.30, 3: 0.15}            # share of accounts per city tier (Appendix A)
WANDER_KM = 8.0
ATM_RADIUS_KM = 6.0
ATMS_PER_TIER = {1: 10, 2: 8, 3: 6}
BANKS = ["VGL Bank", "State Bank", "City Union", "Metro Co-op", "Coastal Bank"]
SITES = ["Railway station", "Bus stand", "Main market", "Hospital", "Tech park", "Mall", "College", "Old town",
         "Highway plaza", "Temple road"]
SINKS = {"ext:atm": "atm", "ext:intl-wire": "intl_wire"}
CHANNELS = ("upi", "imps", "neft", "rtgs", "card", "atm", "wallet", "intl_wire")

# The demo cast's personas name their city; keep the map consistent with what the screens say.
HOME_OVERRIDE = {
    "ramesh@vigil": "Bengaluru", "meena.grocer@vigil": "Bengaluru", "bescom.power@vigil": "Bengaluru",
    "landlord.iyer@vigil": "Bengaluru", "jio.recharge@vigil": "Bengaluru", "chai.point@vigil": "Bengaluru",
    "sunita@vigil": "Pune", "medplus.pharma@vigil": "Pune", "fresh.dairy@vigil": "Pune",
    "sharma.tuitions@vigil": "Pune", "fuel.hp.kothrud@vigil": "Pune", "fuel.io.baner@vigil": "Pune",
}

# Optional per-account city hints set by a SIMULATED attack scenario for its own injected postings
# (e.g. every cash-out of a ring at ATMs in one city). Cleared on reset. Display only.
HINTS: dict[str, str] = {}


def _h(*parts: Any) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "big")


def _u(*parts: Any) -> float:
    return _h(*parts) / 2 ** 64


def offset(lat: float, lng: float, km: float, bearing_deg: float) -> tuple[float, float]:
    """Point `km` away from (lat, lng) along `bearing_deg` (small-distance approximation, < 0.1 % error at 10 km)."""
    b = math.radians(bearing_deg)
    dlat = (km / 111.32) * math.cos(b)
    dlng = (km / (111.32 * max(math.cos(math.radians(lat)), 0.01))) * math.sin(b)
    return round(lat + dlat, 6), round(lng + dlng, 6)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def _point_in_city(city: dict[str, Any], max_km: float, *key: Any) -> tuple[float, float]:
    """A point inside the city: bounded radius, and inside the land sector for coastal cities."""
    radius = min(max_km, city.get("radius_km", max_km))
    lo, hi = city.get("land_bearing", [0, 360])
    bearing = lo + (hi - lo) * _u("b", *key)
    km = radius * math.sqrt(_u("r", *key))             # uniform over the disc sector
    return offset(city["lat"], city["lng"], km, bearing)


def city(name: str | None) -> dict[str, Any] | None:
    return BY_NAME.get(name or "")


@lru_cache(maxsize=4096)
def home_for(account_id: str) -> str | None:
    """Home city of an account: a pure function of sha256(account_id), weighted toward Tier-1 metros.
    External bookkeeping accounts (ext:*) have no home."""
    if not account_id or account_id.startswith("ext:"):
        return None
    if account_id in HOME_OVERRIDE:
        return HOME_OVERRIDE[account_id]
    x = _u("home", account_id)
    acc = 0.0
    for tier in (1, 2, 3):
        group = [c for c in DOMESTIC if c["tier"] == tier]
        share = TIER_WEIGHT[tier]
        if x < acc + share:
            return group[min(len(group) - 1, int((x - acc) / share * len(group)))]["city"]
        acc += share
    return DOMESTIC[-1]["city"]


@lru_cache(maxsize=4096)
def home_point(account_id: str) -> tuple[float, float] | None:
    c = city(home_for(account_id))
    return _point_in_city(c, WANDER_KM, "home", account_id) if c else None


def anchor(account_id: str, day: int) -> tuple[float, float] | None:
    """Where the account's phone is on a given day: home + a bounded daily wander (≤ 8 km)."""
    c = city(HINTS.get(account_id) or home_for(account_id))
    if c is None:
        return None
    if HINTS.get(account_id):
        return _point_in_city(c, WANDER_KM, "hint", account_id, day)
    hp = home_point(account_id)
    lo, hi = c.get("land_bearing", [0, 360])
    km = min(WANDER_KM, c.get("radius_km", WANDER_KM)) * _u("w", account_id, day) * 0.5
    return offset(hp[0], hp[1], km, lo + (hi - lo) * _u("wb", account_id, day)) if hp else None


@lru_cache(maxsize=1)
def atm_terminals() -> tuple[dict[str, Any], ...]:
    out = []
    for c in DOMESTIC:
        code = c["city"][:3].upper()
        for i in range(ATMS_PER_TIER[c["tier"]]):
            lat, lng = _point_in_city(c, ATM_RADIUS_KM, "atm", c["city"], i)
            out.append({"terminal_id": f"ATM-{code}-{i + 1:02d}", "city": c["city"], "lat": lat, "lng": lng,
                        "bank": BANKS[_h("bank", c["city"], i) % len(BANKS)],
                        "site": SITES[_h("site", c["city"], i) % len(SITES)]})
    return tuple(out)


def nearest_atm(city_name: str, key: Any) -> dict[str, Any] | None:
    """The terminal an account used in a city (stable per key, e.g. account + 30-minute bucket)."""
    terms = [t for t in atm_terminals() if t["city"] == city_name]
    return terms[_h("atm-pick", key) % len(terms)] if terms else None


def foreign_for(key: Any) -> dict[str, Any]:
    return FOREIGN[_h("intl", key) % len(FOREIGN)]


def rail(channel: str | None, recipient_id: str | None) -> str:
    """The payment rail to DISPLAY. Historical seed rows store 'upi' for ATM / external debits; the sink they hit
    tells the real rail. The stored channel (an ML input) is never rewritten."""
    ch = channel or "upi"
    if ch == "upi" and recipient_id in SINKS:
        return SINKS[recipient_id]
    return ch


def _epoch_day(ts: str | None) -> int:
    try:
        return int(datetime.fromisoformat((ts or "").replace("Z", "+00:00")).timestamp() // 86400)
    except ValueError:
        return 0


def stamp(row: dict[str, Any]) -> dict[str, Any]:
    """Geo fields for one posting (pure, O(1), never raises). See the module docstring for the rules."""
    empty = {"geo_city": None, "geo_lat": None, "geo_lng": None, "geo_basis": None, "geo_accuracy_m": None,
             "peer_geo_city": None, "peer_geo_lat": None, "peer_geo_lng": None}
    try:
        s, r, tx_id = row["sender_id"], row["recipient_id"], row.get("id") or row.get("seq")
        ch = rail(row.get("channel"), r)
        out = dict(empty)
        if s.startswith("ext:"):                       # credit from outside the bank lands at the customer's home
            c = city(HINTS.get(r) or home_for(r))
            if c is None:
                return empty
            hp = home_point(r) if not HINTS.get(r) else _point_in_city(c, WANDER_KM, "hint", r)
            out.update(geo_city=c["city"], geo_lat=hp[0], geo_lng=hp[1], geo_basis="kyc_home",
                       geo_accuracy_m=ACCURACY_M["kyc_home"])
            return out
        sc = city(HINTS.get(s) or home_for(s))
        if sc is None:
            return empty
        if ch == "atm":
            ts = row.get("ts") or ""
            bucket = ts[:15]                            # yyyy-mm-ddThh:m → 10-minute bucket
            t = nearest_atm(sc["city"], (s, bucket)) or {}
            out.update(geo_city=sc["city"], geo_lat=t.get("lat"), geo_lng=t.get("lng"), geo_basis="atm_terminal",
                       geo_accuracy_m=ACCURACY_M["atm_terminal"], peer_geo_city=sc["city"],
                       peer_geo_lat=t.get("lat"), peer_geo_lng=t.get("lng"))
            return out
        if ch == "card":
            rc = city(home_for(r)) or sc
            lat, lng = _point_in_city(rc, 2.0, "pos", r)
            out.update(geo_city=rc["city"], geo_lat=lat, geo_lng=lng, geo_basis="merchant_pos",
                       geo_accuracy_m=ACCURACY_M["merchant_pos"])
        elif row.get("device_id") or s in HINTS:         # hinted = a scenario's mule phone
            p = anchor(s, _epoch_day(row.get("ts")))
            j = _point_in_city({"lat": p[0], "lng": p[1]}, 0.03, "gps", tx_id)   # ±30 m fix jitter
            out.update(geo_city=sc["city"], geo_lat=j[0], geo_lng=j[1], geo_basis="device_gps",
                       geo_accuracy_m=ACCURACY_M["device_gps"])
        else:
            acc_km = 3 + 12 * _u("ipacc", s)
            lat, lng = _point_in_city(sc, acc_km, "ip", s, tx_id)
            out.update(geo_city=sc["city"], geo_lat=lat, geo_lng=lng, geo_basis="ip",
                       geo_accuracy_m=int(acc_km * 1000))
        if ch == "intl_wire" or r == "ext:intl-wire":
            f = foreign_for((s, tx_id))
            out.update(peer_geo_city=f["city"], peer_geo_lat=f["lat"], peer_geo_lng=f["lng"])
        elif not r.startswith("ext:"):
            rc = city(HINTS.get(r) or home_for(r))
            rp = home_point(r) if rc and not HINTS.get(r) else (_point_in_city(rc, WANDER_KM, "hint", r) if rc else None)
            if rc and rp:
                out.update(peer_geo_city=rc["city"], peer_geo_lat=rp[0], peer_geo_lng=rp[1])
        return out
    except Exception:                                   # display context must never break a posting
        return empty


def label(basis: str | None, accuracy_m: int | None) -> str:
    if not basis:
        return "Location unknown"
    acc = "city-level" if basis == "kyc_home" else (f"±{accuracy_m / 1000:.0f} km" if (accuracy_m or 0) >= 1000
                                                     else f"±{accuracy_m} m")
    return f"Simulated location · {BASIS_LABEL.get(basis, basis)} · {acc}"


# ── persistence (reference tables + idempotent backfills) ───────────────────
def load_reference() -> None:
    from vigil import db
    with db.tx():
        for c in CITIES:
            db.execute("INSERT OR REPLACE INTO geo_cities(city, state, country, lat, lng, tier, kind) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (c["city"], c["state"], c["country"], c["lat"], c["lng"], c["tier"], c["kind"]))
        for t in atm_terminals():
            db.execute("INSERT OR REPLACE INTO atm_terminals(terminal_id, city, lat, lng, bank, site) "
                       "VALUES (?, ?, ?, ?, ?, ?)", (t["terminal_id"], t["city"], t["lat"], t["lng"], t["bank"], t["site"]))


def backfill_accounts() -> int:
    """Set home_* for every customer account that has none (idempotent)."""
    from vigil import db
    rows = db.q("SELECT id FROM accounts WHERE home_city IS NULL AND kind = 'customer'")
    vals = []
    for r in rows:
        hp = home_point(r["id"])
        if hp:
            vals.append((home_for(r["id"]), hp[0], hp[1], r["id"]))
    if vals:
        with db.tx() as c:
            c.executemany("UPDATE accounts SET home_city = ?, home_lat = ?, home_lng = ? WHERE id = ?", vals)
    return len(vals)


def backfill_transactions() -> int:
    """Stamp geo on rows posted before v10 (same pure function → same answer as stamping at post time)."""
    from vigil import db
    rows = db.q("SELECT id, seq, sender_id, recipient_id, channel, device_id, ts FROM transactions WHERE geo_basis IS NULL")
    vals = []
    for r in rows:
        g = stamp(r)
        if g["geo_basis"]:
            vals.append((g["geo_city"], g["geo_lat"], g["geo_lng"], g["geo_basis"], g["geo_accuracy_m"],
                         g["peer_geo_city"], g["peer_geo_lat"], g["peer_geo_lng"], r["id"]))
    if vals:
        with db.tx() as c:
            c.executemany("UPDATE transactions SET geo_city = ?, geo_lat = ?, geo_lng = ?, geo_basis = ?, "
                          "geo_accuracy_m = ?, peer_geo_city = ?, peer_geo_lat = ?, peer_geo_lng = ? WHERE id = ?", vals)
    return len(vals)
