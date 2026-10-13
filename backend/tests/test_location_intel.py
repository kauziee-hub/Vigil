"""v12 location intelligence: impossible travel, coordinated cash-out, location-behaviour anomalies, and location as
a CORROBORATING (never deciding) voice in the live account status. Locations are simulated; see vigil/geo/intel.py."""

from __future__ import annotations

import itertools

import pytest

from vigil import geo


def _p(city: str, t: float, basis: str = "device_gps", acc_m: int | None = None, account: str = "x@vigil",
       lat: float | None = None, lng: float | None = None, tx: str | None = None) -> dict:
    c = geo.city(city)
    return {"tx_id": tx or f"TX-{city}-{t}", "seq": int(t), "ts": f"2026-10-13T10:{int(t // 60) % 60:02d}:{int(t % 60):02d}Z",
            "t": t, "account": account, "city": city, "lat": lat if lat is not None else c["lat"],
            "lng": lng if lng is not None else c["lng"], "basis": basis,
            "acc_m": acc_m if acc_m is not None else geo.ACCURACY_M.get(basis, 5000), "amount_paise": 100_00,
            "label": geo.label(basis, acc_m if acc_m is not None else geo.ACCURACY_M.get(basis, 5000))}


# ── A. impossible travel (pure rule) ──────────────────────────────────────
def test_genuine_impossible_travel_is_high_confidence():
    from vigil.geo import intel
    f = intel.travel_findings([_p("Delhi", 0), _p("Kolkata", 120)])
    assert len(f) == 1
    t = f[0]
    assert t["confidence"] == "high" and t["from_city"] == "Delhi" and t["to_city"] == "Kolkata"
    assert 1200 < t["km"] < 1400 and t["kmh"] > t["threshold_kmh"] == 900
    assert "km/h" in t["reason"] and t["minutes"] == 2.0


def test_normal_travel_is_not_flagged():
    from vigil.geo import intel
    # Mumbai → Pune (~120 km) in three hours, Delhi → Mumbai (~1,150 km) in two and a half hours (a flight)
    assert intel.travel_findings([_p("Mumbai", 0), _p("Pune", 3 * 3600)]) == []
    assert intel.travel_findings([_p("Delhi", 0), _p("Mumbai", 2.5 * 3600)]) == []


def test_gps_jitter_is_not_flagged():
    from vigil.geo import intel
    c = geo.city("Bengaluru")
    a = _p("Bengaluru", 0, lat=c["lat"], lng=c["lng"])
    b = _p("Bengaluru", 1, lat=c["lat"] + 0.0004, lng=c["lng"] + 0.0003)        # ~50 m away, one second later
    assert intel.travel_findings([a, b]) == []
    assert intel.effective_km(a, b)[1] == 0.0                                  # below both ±30 m radii


def test_low_precision_ip_is_conservative():
    from vigil.geo import intel
    # IP estimate (±15 km) then a GPS fix 1,300 km away two minutes later: shown, LOW confidence, never evidence
    f = intel.travel_findings([_p("Delhi", 0, basis="ip", acc_m=15000), _p("Kolkata", 120)])
    assert len(f) == 1 and f[0]["confidence"] == "low" and "low precision" in f[0]["reason"]
    # borderline: 60 km apart with a ±15 km IP estimate is only 45 km after accuracy — below the 50 km minimum
    c = geo.city("Delhi")
    near = geo.offset(c["lat"], c["lng"], 60, 90)
    g = intel.travel_findings([_p("Delhi", 0, basis="ip", acc_m=15000), _p("Delhi", 30, lat=near[0], lng=near[1])])
    assert g == []
    # the same 60 km between two precise fixes in 30 s IS impossible travel
    h = intel.travel_findings([_p("Delhi", 0), _p("Delhi", 30, lat=near[0], lng=near[1])])
    assert len(h) == 1 and h[0]["confidence"] == "high"


def test_merchant_pos_and_kyc_home_are_never_presence():
    from vigil.geo import intel
    assert "merchant_pos" not in intel.presence_bases() and "kyc_home" not in intel.presence_bases()
    assert {"device_gps", "atm_terminal", "branch", "ip"} == set(intel.presence_bases())


# ── C. location-behaviour anomalies (pure rules) ──────────────────────────
def _baseline(cities: list[str], n: int, home: str):
    h = geo.city(home)
    return {"n": n, "cities": set(cities), "points": [_p(c, -86400) for c in cities],
            "home": {"lat": h["lat"], "lng": h["lng"], "acc_m": 5000, "basis": "kyc_home", "city": home}, "home_city": home}


def test_unusual_region_needs_a_baseline_and_a_real_displacement():
    from vigil.geo import intel
    base = _baseline(["Pune"], 12, "Pune")
    hit = intel.unusual_region_findings([_p("Kolkata", 0)], base)
    assert len(hit) == 1 and hit[0]["rule"] == "LOC_UNUSUAL_REGION" and hit[0]["confidence"] == "high"
    assert hit[0]["nearest_baseline_km"] >= 150 and "Pune" in hit[0]["reason"]
    # a nearby new city (Pune → Mumbai, ~120 km) is ordinary travel
    assert intel.unusual_region_findings([_p("Mumbai", 0)], base) == []
    # a usual city is never unusual; a new account (too little history) is never judged on geography
    assert intel.unusual_region_findings([_p("Pune", 0)], base) == []
    assert intel.unusual_region_findings([_p("Kolkata", 0)], _baseline(["Pune"], 2, "Pune")) == []


def test_multi_city_burst():
    from vigil.geo import intel
    pts = [_p("Delhi", 0), _p("Jaipur", 600), _p("Lucknow", 1200)]
    f = intel.multi_city_findings(pts)
    assert len(f) == 1 and f[0]["cities"] == ["Delhi", "Jaipur", "Lucknow"]
    # the same three cities over a day is just travel
    assert intel.multi_city_findings([_p("Delhi", 0), _p("Jaipur", 8 * 3600), _p("Lucknow", 20 * 3600)]) == []


# ── 2. location in detection: corroborating only ─────────────────────────
def _old_classify(risk, fam, flagging, threshold, structural=False, onward=True):
    """The pre-v12 live rule, copied verbatim, to prove location=False changes nothing."""
    flagging = list(flagging)
    above = risk is not None and risk >= threshold
    if above and onward and any(f != fam for f in flagging):
        return "flagged"
    if structural and len(flagging) >= 2:
        return "flagged"
    if "early_warning" in flagging or len(flagging) >= 2:
        return "early_warning"
    return None


def test_classify_without_location_is_exactly_the_old_rule():
    from vigil.intel import live
    from vigil.intel.stream import classify
    fams = live.INTEL_FAMILIES
    for risk, fam in [(None, None), (0.4, "random_forest"), (0.9, "random_forest"), (0.95, "gnn")]:
        for k in range(0, 4):
            for flagging in itertools.combinations(fams, k):
                for structural, onward in itertools.product([False, True], [False, True]):
                    assert classify(risk, fam, flagging, 0.85, structural, onward) == \
                        _old_classify(risk, fam, flagging, 0.85, structural, onward)


def test_location_never_decides_on_its_own():
    from vigil.intel.stream import classify
    assert classify(None, None, [], 0.85, location=True) is None
    assert classify(0.99, "random_forest", [], 0.85, location=True) is None        # model evidence alone + location
    # it can stand in for the missing second voice …
    assert classify(0.9, "random_forest", ["random_forest"], 0.85, location=True) == "flagged"
    assert classify(0.9, "random_forest", ["random_forest"], 0.85) is None
    assert classify(None, None, ["drift"], 0.85, location=True) == "early_warning"
    assert classify(None, None, ["drift"], 0.85) is None
    # … but model evidence that does not move money on stays unflagged
    assert classify(0.9, "random_forest", ["random_forest"], 0.85, onward=False, location=True) == "early_warning"


# ── B. coordinated cash-out (DB-backed) ───────────────────────────────────
def _withdraw(db, ledger, aid: str, terminal: dict, ts: str, amount: int = 40_000_00) -> str:
    from vigil.engine import ledger as L
    if L.available_paise(aid) < amount:
        ledger.post(sender_id="ext:other-bank", recipient_id=aid, amount_paise=amount, kind="external_credit",
                    check_funds=False)
    tx = ledger.post(sender_id=aid, recipient_id="ext:atm", amount_paise=amount, kind="external_debit", note="cash")
    with db.tx():
        db.execute("UPDATE transactions SET ts = ?, geo_basis = 'atm_terminal', geo_accuracy_m = 25, geo_city = ?, "
                   "geo_lat = ?, geo_lng = ? WHERE id = ?", (ts, terminal["city"], terminal["lat"], terminal["lng"], tx["id"]))
    return tx["id"]


def _risky(monkeypatch, accounts: set[str]):
    from vigil import overview
    real = overview.statuses
    monkeypatch.setattr(overview, "statuses", lambda: {**real(), **{a: {"status": "flagged"} for a in accounts}})
    monkeypatch.setattr(overview, "ring_members", lambda: set())


def _customers(db, n: int) -> list[str]:
    return [r["id"] for r in db.q("SELECT id FROM accounts WHERE kind = 'customer' AND seed_role = 'legit' "
                                  "AND persona IS NULL ORDER BY id LIMIT ?", (n,))]


def test_coordinated_atm_cash_out_cluster(world, monkeypatch):
    from vigil import clock, overview
    from vigil.engine import ledger
    accts = _customers(world, 4)
    mumbai = [t for t in geo.atm_terminals() if t["city"] == "Mumbai"]
    base = clock.now()
    ids = [_withdraw(world, ledger, a, mumbai[i % 3], clock.iso(base.replace(microsecond=0)).replace("Z", "Z"))
           for i, a in enumerate(accts)]
    # spread them over 18 minutes
    for i, tx in enumerate(ids):
        with world.tx():
            world.execute("UPDATE transactions SET ts = ? WHERE id = ?",
                          (clock.iso(base - __import__("datetime").timedelta(minutes=18 - 6 * i)), tx))
    _risky(monkeypatch, set(accts))
    since = clock.iso(base - __import__("datetime").timedelta(hours=1))
    cl = [c for c in overview.cash_out_clusters(since) if set(c["tx_ids"]) & set(ids)]
    assert len(cl) == 1
    c = cl[0]
    assert set(c["accounts"]) == set(accts) and c["city"] == "Mumbai"
    assert c["atm_count"] == 3 and len(c["atms"]) == 3 and c["radius_km"] <= 8
    assert c["value_paise"] == 4 * 40_000_00 and c["minutes"] == pytest.approx(18, abs=0.1)
    assert c["first_ts"] < c["last_ts"] and "risky ATM withdrawals" in c["rule"]


def test_unrelated_atm_withdrawals_are_not_clustered(world, monkeypatch):
    from datetime import timedelta
    from vigil import clock, overview
    from vigil.engine import ledger
    accts = _customers(world, 6)
    base = clock.now()
    terms = {c: [t for t in geo.atm_terminals() if t["city"] == c][0] for c in ("Mumbai", "Delhi", "Chennai")}
    # (1) risky accounts but three different cities; (2) same city but ordinary accounts; (3) same city, hours apart
    a = [_withdraw(world, ledger, accts[i], terms[c], clock.iso(base - timedelta(minutes=5 * i)))
         for i, c in enumerate(terms)]
    b = [_withdraw(world, ledger, accts[3 + i], terms["Mumbai"], clock.iso(base - timedelta(minutes=2 * i))) for i in range(3)]
    _risky(monkeypatch, set(accts[:3]))
    since = clock.iso(base - timedelta(hours=3))
    got = {t for c in overview.cash_out_clusters(since) for t in c["tx_ids"]}
    assert not got & set(a + b)
    with world.tx():
        for i, tx in enumerate(b):
            world.execute("UPDATE transactions SET ts = ? WHERE id = ?", (clock.iso(base - timedelta(hours=i)), tx))
    _risky(monkeypatch, set(accts[3:]))
    assert not {t for c in overview.cash_out_clusters(since) for t in c["tx_ids"]} & set(b)


# ── world-level: scenario postings, detection unchanged, API, WebSocket, incidents ──
def _run_live(sid: str) -> None:
    """Run a scenario the way `scenarios.start` does (with its simulated geo story), synchronously."""
    from vigil.sim import scenarios  # noqa: F401  (imports attacks in the right order)
    from vigil.sim import attacks
    geo.HINTS.update(attacks.geo_story(sid) if sid in attacks.ATTACK_ORDER else
                     {a: "Mumbai" for a in ("kiran.traders@vigil", "zenith.exports@vigil", "pooja.m@vigil", "rahul.m@vigil")})
    scenarios.run_sync(sid)


@pytest.fixture()
def live_world(world):
    from vigil.geo import intel
    from vigil.intel import stream
    stream.register()
    intel.reset()
    return world


def test_seeded_world_and_ordinary_activity_raise_no_location_evidence(live_world):
    from vigil.geo import intel
    from vigil.sim import ambient
    assert intel.evidence_map() == {}
    for _ in range(40):                                   # ordinary customers paying their usual merchants
        ambient._tick()
    assert intel.evidence_map() == {}
    s = intel.summary(3600)
    assert s["impossible_travel"] == [] and s["anomalies"] == [] and s["normal"]["accounts_with_signals"] == 0
    assert s["normal"]["located_postings"] > 0


def test_existing_detection_unchanged_when_no_geo_anomaly(live_world):
    """Fan-in uses a brand-new collector (no geographic baseline) and ordinary senders at home: no location rule fires,
    so every live status is identical with location corroboration switched on or off."""
    from vigil.geo import intel
    from vigil.intel import stream
    _run_live("atk_fan_in")
    assert intel.evidence_map() == {}
    on = {a: v["status"] for a, v in stream.status_map().items()}
    pol = intel.policy()
    try:
        pol["corroboration"]["enabled"] = False
        intel.reset()
        stream.STATE.view_key = None
        off = {a: v["status"] for a, v in stream.status_map().items()}
    finally:
        pol["corroboration"]["enabled"] = True
        intel.reset()
    assert on == off


def test_cross_channel_scenario_triggers_impossible_travel_end_to_end(live_world):
    from fastapi.testclient import TestClient
    from vigil.app import app
    from vigil.copilot import incidents
    from vigil.geo import intel
    from vigil.realtime import HUB
    q = HUB.subscribe(["console"])
    _run_live("atk_cross_channel")
    hub = next(a for a, e in intel.evidence_map().items() if any(r["rule"] == "LOC_IMPOSSIBLE_TRAVEL" for r in e["rules"]))
    ev = intel.evidence_map()[hub]
    t = next(r for r in ev["rules"] if r["rule"] == "LOC_IMPOSSIBLE_TRAVEL")
    assert (t["from_city"], t["to_city"], t["confidence"]) == ("Delhi", "Kolkata", "high") and t["km"] > 1200
    assert ev["corroborates"] and ev["score"] > 0
    # WebSocket: the change was pushed
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    HUB.unsubscribe(q)
    pushed = [e for e in events if e["type"] == "geo.location_intel"]
    assert pushed and pushed[-1]["data"]["accounts"] >= 1 and "LOC_IMPOSSIBLE_TRAVEL" in pushed[-1]["data"]["rules"]
    # incident (existing possible-account-takeover type), with location quality in its facts
    incidents.evaluate()
    it = [incidents.public(i, brief=False) for i in incidents.list_incidents("open") if i["kind"] == "impossible_travel"]
    assert it and "Delhi → Kolkata" in it[0]["title"]
    assert any("Location quality" in f for f in it[0]["facts"])
    # live API payload for the Money Map
    with TestClient(app) as c:
        s = c.get("/api/geo/intel?window=1h").json()
        assert s["impossible_travel"][0]["from_city"] == "Delhi" and s["impossible_travel"][0]["points"][0]["label"]
        assert s["thresholds"]["impossible_travel_kmh"] == 900 and s["corroboration_enabled"] is True
        assert any(a["account"] == hub for a in s["anomalies"])
        sel = c.get(f"/api/geo/intel?window=1h&account={hub}").json()["selected"]
        assert sel["kind"] == "account" and sel["verdict"] == "suspicious" and sel["route"] and sel["usual_cities"]
        city = c.get("/api/geo/intel?window=1h&city=Kolkata").json()["selected"]
        assert city["kind"] == "city" and city["travel"]
    from vigil.intel import stream
    stream_status = stream.status_map()[hub]
    assert stream_status["location"]["rules"] and "changed_status" in stream_status["location"]


def test_cash_out_cluster_from_scenarios_feeds_the_existing_incident(live_world):
    from vigil.copilot import incidents
    from vigil.geo import intel
    for sid in ("s2", "atk_velocity_chain", "atk_shared_device"):
        _run_live(sid)
    s = intel.summary(3600)
    mumbai = [c for c in s["cash_out"] if c["city"] == "Mumbai"]
    assert mumbai and mumbai[0]["atm_count"] >= 2 and len(mumbai[0]["accounts"]) >= 3 and mumbai[0]["atms"]
    incidents.evaluate()
    inc = [incidents.public(i, brief=False) for i in incidents.list_incidents("open") if i["kind"] == "cash_out_cluster"]
    assert inc and inc[0]["subject"] == "Mumbai" and any("ATM terminal(s)" in f for f in inc[0]["facts"])


def test_state_flows_aggregate_city_corridors_by_state(live_world):
    """The map's corridors, summed state to state (inter-state only), risky first, with the main city pair."""
    from vigil import overview
    _run_live("s2")
    m = overview.geo_map("1h")
    sf = m["state_flows"]
    assert sf and all(x["from_state"] != x["to_state"] for x in sf)
    order = [(-x["fraud_linked_paise"], -x["suspicious_paise"], -x["value_paise"]) for x in sf]
    assert order == sorted(order)
    top = sf[0]
    assert top["to_state"] == "Maharashtra" and top["fraud_linked_paise"] > 0 and top["risk"] == "fraud"
    assert top["top_pair"]["to_city"] == "Mumbai" and top["accounts"] >= 2 and top["risky_accounts"] >= 1
    # every state flow is backed by city flows between those states
    city_state = {c["city"]: c.get("state") for c in m["cities"]}
    assert any(city_state.get(f["from_city"]) == top["from_state"] and city_state.get(f["to_city"]) == "Maharashtra"
               for f in m["flows"])
