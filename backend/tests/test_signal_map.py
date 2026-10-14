"""v12.4 signal map: the inside of the eight detector families, the supporting signals, honest validation labels."""

from __future__ import annotations

import pytest

from vigil import geo


@pytest.fixture()
def live_world(world):
    from vigil.geo import intel
    from vigil.intel import stream
    stream.register()
    intel.reset()
    return world


def _run_live(sid: str) -> None:
    from vigil.sim import scenarios  # noqa: F401  (imports attacks in the right order)
    from vigil.sim import attacks
    geo.HINTS.update(attacks.geo_story(sid) if sid in attacks.ATTACK_ORDER else
                     {a: "Mumbai" for a in ("kiran.traders@vigil", "zenith.exports@vigil", "pooja.m@vigil", "rahul.m@vigil")})
    scenarios.run_sync(sid)


def test_catalogue_keeps_the_eight_families_and_lists_their_inside(live_world):
    from vigil.intel import signals
    m = signals.signal_map()
    assert [f["id"] for f in m["families"]] == ["ringwatch", "random_forest", "gnn", "rules", "drift", "early_warning",
                                               "pattern_memory", "external"]
    count = {f["id"]: f["signal_count"] for f in m["families"]}
    assert count == {"ringwatch": 13, "random_forest": 1, "gnn": 1, "rules": 6, "drift": 8, "early_warning": 6,
                     "pattern_memory": 10, "external": 3}
    assert [s["id"] for s in m["supporting"]] == ["payment", "location"]
    assert {s["id"]: s["signal_count"] for s in m["supporting"]} == {"payment": 22, "location": 4}
    t = m["totals"]
    assert t["families"] == 8 and t["family_signals"] == 48 and t["supporting_signals"] == 26
    for g in m["families"] + m["supporting"]:
        assert g["purpose"] and g["role"] and g["feeds"]
        assert all(s["checks"] and s["label"] for s in g["signals"])


def test_validation_is_labelled_honestly(live_world):
    """Metrics only for families benchmarked on held-out worlds; never for RingWatch, the registry or sub-signals."""
    from vigil.intel import signals
    m = signals.signal_map()
    kind = {g["id"]: g["validation"]["kind"] for g in m["families"] + m["supporting"]}
    assert kind["ringwatch"] == "live_graded" and kind["external"] == "lookup"
    assert kind["payment"] == "supporting" and kind["location"] == "supporting"
    for fid in ("random_forest", "gnn", "rules", "drift", "pattern_memory", "early_warning"):
        g = next(f for f in m["families"] if f["id"] == fid)
        assert g["validation"]["kind"] == "benchmarked" and "PR-AUC" in g["validation"]["headline"]
    for g in m["families"] + m["supporting"]:
        if g["validation"]["kind"] != "benchmarked":
            assert "headline" not in g["validation"]
        for s in g["signals"]:                     # a single signal never carries a metric
            assert not {"roc_auc", "pr_auc", "precision", "recall", "f1"} & set(s)


def test_live_counts_account_focus_and_read_only(live_world):
    from vigil.intel import signals, stream
    _run_live("s2")
    before = {a: v["status"] for a, v in stream.status_map().items()}
    m = signals.signal_map()
    rw = next(f for f in m["families"] if f["id"] == "ringwatch")
    fired = {s["id"]: s["firing"] for s in rw["signals"]}
    assert fired["NET_PASS_THROUGH"] >= 1 and rw["firing_signals"] >= 3 and rw["flagged_now"] >= 1
    assert m["totals"]["firing_now"] >= rw["firing_signals"]
    assert any(a["id"] == "kiran.traders@vigil" for a in m["top_accounts"])
    k = signals.signal_map("kiran.traders@vigil")
    assert k["account"]["status"] == "flagged" and k["account"]["families_flagging"] >= 4
    krw = next(f for f in k["families"] if f["id"] == "ringwatch")
    assert krw["account_flagged"] is True
    assert any(s["hit"] and s["id"] == "NET_PASS_THROUGH" and "moved on" in (s["why"] or "") for s in krw["signals"])
    rules = next(f for f in k["families"] if f["id"] == "rules")
    assert any(s["hit"] and s["why"] for s in rules["signals"]) and "points" in rules["account_value"]
    ext = next(f for f in k["families"] if f["id"] == "external")
    assert ext["account_value"] == "reported" and ext["account_flagged"] is True
    after = {a: v["status"] for a, v in stream.status_map().items()}
    assert before == after                          # the signal map never changes a status


def test_payment_time_and_location_signals_are_counted(live_world):
    from vigil.intel import signals
    _run_live("s1")                                 # Ramesh → Kiran ₹45,000: registry reported + pass-through + behaviour
    _run_live("atk_cross_channel")                  # impossible travel Delhi → Kolkata
    m = signals.signal_map()
    pay = next(s for s in m["supporting"] if s["id"] == "payment")
    fired = {s["id"]: s["firing"] for s in pay["signals"]}
    assert fired["EXT_REPORTED"] >= 1 and fired["BEH_FIRST_TIME_PAYEE"] >= 1
    loc = next(s for s in m["supporting"] if s["id"] == "location")
    lf = {s["id"]: s for s in loc["signals"]}
    assert lf["LOC_IMPOSSIBLE_TRAVEL"]["firing"] >= 1 and "Possible-account-takeover" in lf["LOC_IMPOSSIBLE_TRAVEL"]["feeds"]
    hub = next(a for a, e in __import__("vigil.geo.intel", fromlist=["x"]).evidence_map().items()
               if any(r["rule"] == "LOC_IMPOSSIBLE_TRAVEL" for r in e["rules"]))
    h = signals.signal_map(hub)
    hl = next(s for s in h["supporting"] if s["id"] == "location")
    assert any(s["hit"] and s["id"] == "LOC_IMPOSSIBLE_TRAVEL" and "Delhi" in (s["why"] or "") for s in hl["signals"])
    hp = next(s for s in h["supporting"] if s["id"] == "payment")
    assert hp["account_decision"] is None or hp["account_decision"]["as"] in ("sender", "recipient")


def test_signal_map_api(live_world):
    from fastapi.testclient import TestClient
    from vigil.app import app
    with TestClient(app) as c:
        r = c.get("/api/intel/signals")
        assert r.status_code == 200 and r.json()["totals"]["families"] == 8
        a = c.get("/api/intel/signals?account=kiran.traders@vigil").json()
        assert a["account"]["id"] == "kiran.traders@vigil"
        x = c.get("/api/intel/signals?account=ext:atm").json()
        assert x["account"]["status"] is None and "Not a scored" in x["account"]["reason"]
        assert c.get("/api/intel/signals?window_min=1").status_code == 422
