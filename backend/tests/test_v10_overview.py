"""overview-v10 P2: read APIs for the money map, tape, connections, pipeline, KPIs, brief + derived signals."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(world):
    from vigil import overview
    from vigil.app import app
    overview.invalidate()
    with TestClient(app) as c:
        yield c


def test_map_shape_caps_and_synthetic_label(client):
    m = client.get("/api/geo/map?window=7d").json()
    assert m["synthetic"] is True and m["totals"]["postings"] > 0
    assert len(m["flows"]) <= 200 and len(m["cities"]) <= 40
    assert {"city", "lat", "lng", "tx_count", "value_paise", "fraud_linked_paise"} <= set(m["cities"][0])
    assert all(f["risk"] in ("normal", "suspicious", "fraud") for f in m["flows"])
    assert client.get("/api/geo/map?window=2d").status_code == 422
    assert client.get("/api/geo/map?channel=swift").status_code == 400


def test_tape_paging_filters_and_location_label(client):
    t = client.get("/api/tx/tape?limit=20").json()["rows"]
    assert 0 < len(t) <= 20 and t[0]["seq"] > t[-1]["seq"]
    assert t[0]["geo"]["label"].startswith("Simulated location")
    newer = client.get(f"/api/tx/tape?since_id={t[5]['tx_id']}&limit=50").json()["rows"]
    assert {r["tx_id"] for r in newer} == {r["tx_id"] for r in t[:5]}
    only = client.get("/api/tx/tape?only=fraud&limit=30").json()["rows"]
    assert all(r["risk"] == "fraud" for r in only)
    acc = client.get("/api/tx/tape?accounts=kiran.traders@vigil&limit=10").json()["rows"]
    assert acc and all("kiran.traders@vigil" in (r["sender_id"], r["recipient_id"]) for r in acc)


def test_connections_caps_and_404(client):
    tx = client.get("/api/tx/tape?q=kiran.traders&limit=5").json()["rows"][0]["tx_id"]
    c = client.get(f"/api/tx/{tx}/connections").json()
    assert set(c) >= {"tx", "sender", "recipient", "upstream", "downstream", "shared_device", "linked_by", "geo_path"}
    for lst in (c["upstream"], c["downstream"]):
        assert len(lst) <= 36 and all(1 <= h["hops"] <= 3 for h in lst)
    assert client.get("/api/tx/TX-999999/connections").status_code == 404


def test_kpis_pipeline_brief_exits_channels_attention(client):
    k = client.get("/api/overview/kpis?window=24h").json()
    assert [t["key"] for t in k["tiles"]] == ["moved", "fraud", "at_risk", "stopped", "left", "new"]
    assert k["tiles"][0]["value"] > 0 and len(k["tiles"][0]["spark"]) == 12
    scoped = client.get("/api/overview/kpis?window=24h&accounts=kiran.traders@vigil").json()
    assert scoped["scope"] == ["kiran.traders@vigil"] and scoped["tiles"][0]["value"] <= k["tiles"][0]["value"]
    p = client.get("/api/overview/pipeline?days=60").json()
    counts = [s["count"] for s in p["stages"]]
    assert counts == sorted(counts, reverse=True) and counts[0] >= 40          # funnel never widens; cohort included
    cohort = {a["id"]: a for a in p["accounts"] if a["id"].count(".") == 2}
    assert cohort and not any(a["suspicious_path"] for a in cohort.values())  # ordinary new customers fall out early
    assert any(a["id"] == "kiran.traders@vigil" and a["suspicious_path"] for a in p["accounts"])
    b = client.get("/api/overview/brief").json()
    assert len(b["lines"]) == 3 and b["llm_used"] is False
    e = client.get("/api/overview/exits?window=7d").json()
    assert {s["sink"] for s in e["by_sink"]} <= {"ext:atm", "ext:other-bank", "ext:intl-wire"}
    ch = client.get("/api/overview/channels?window=7d").json()
    assert abs(sum(r["share_value"] for r in ch["rails"]) - 1) < 0.01
    att = client.get("/api/overview/attention").json()
    assert any(a["id"] == "kiran.traders@vigil" for a in att["accounts"])


def test_endpoint_latency_budget(client):
    paths = ["/api/geo/map?window=1h", "/api/tx/tape?limit=100", "/api/overview/kpis?window=1h",
             "/api/overview/pipeline", "/api/overview/brief", "/api/overview/exits", "/api/overview/channels"]
    from vigil import overview
    worst = {}
    for p in paths:
        times = []
        for _ in range(5):
            overview.invalidate()                     # cold every time: the worst case, not the cached one
            t0 = time.perf_counter()
            assert client.get(p).status_code == 200
            times.append((time.perf_counter() - t0) * 1000)
        worst[p] = max(times)
    print("v10 endpoint worst-of-5 ms:", {k.split("?")[0]: round(v) for k, v in worst.items()})
    assert max(worst.values()) < 1500                 # generous on a loaded laptop; typical figures are logged


def test_impossible_travel_and_cash_out_cluster(world, monkeypatch):
    from vigil import geo, overview
    from vigil.engine import ledger
    a = "kiran.traders@vigil"
    geo.HINTS[a] = "Delhi"
    ledger.post(sender_id=a, recipient_id="zenith.exports@vigil", amount_paise=1_000_00, source="scenario", check_funds=False)
    geo.HINTS[a] = "Kolkata"
    ledger.post(sender_id=a, recipient_id="zenith.exports@vigil", amount_paise=1_000_00, source="scenario", check_funds=False)
    since = "2000-01-01T00:00:00Z"
    trips = [t for t in overview.impossible_travel(since) if t["account"] == a]
    assert trips and trips[-1]["from_city"] == "Delhi" and trips[-1]["to_city"] == "Kolkata" and trips[-1]["kmh"] > 900
    # three risky ATM withdrawals in one city within minutes → one cash-out cluster
    ids = ["zenith.exports@vigil", "pooja.m@vigil", "rahul.m@vigil"]
    for x in ids:
        geo.HINTS[x] = "Mumbai"
        ledger.post(sender_id=x, recipient_id="ext:atm", amount_paise=20_000_00, kind="external_debit", source="scenario",
                    check_funds=False)
    overview.invalidate()
    monkeypatch.setattr(overview, "statuses", lambda: {x: {"status": "flagged"} for x in ids})
    monkeypatch.setattr(overview, "ring_members", lambda: set())
    clusters = overview.cash_out_clusters(since)
    assert any(set(ids) <= set(c["accounts"]) and c["city"] == "Mumbai" for c in clusters)
    geo.HINTS.clear()
