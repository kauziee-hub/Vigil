"""v8 operations center: close monitoring (watchlist), status reason / since on the universe, traffic, new accounts."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vigil import db
from vigil.sim import scenarios


@pytest.fixture()
def client(world):
    from vigil.app import app

    with TestClient(app) as c:
        yield c


def test_pin_list_and_unpin(client):
    r = client.post("/api/watchlist", json={"account_id": "ramesh@vigil", "note": "salary pattern changed"})
    assert r.status_code == 200 and r.json()["note"] == "salary pattern changed"
    w = client.get("/api/watchlist").json()
    assert w["pinned"] == 1
    e = w["entries"][0]
    assert e["account_id"] == "ramesh@vigil" and e["pinned"] and "pinned" in e["sources"]
    assert e["status"] and e["next_step"] and e["label"]
    assert e["activity"] is None or set(e["activity"]) >= {"in_paise", "out_paise", "forwarded_fraction", "counterparties"}
    # pinning twice updates the note, never duplicates
    client.post("/api/watchlist", json={"account_id": "ramesh@vigil", "note": "second note"})
    w = client.get("/api/watchlist").json()
    assert [x["account_id"] for x in w["entries"] if x["pinned"]] == ["ramesh@vigil"]
    assert w["entries"][0]["note"] == "second note"
    assert client.delete("/api/watchlist/ramesh@vigil").json()["removed"] is True
    assert client.delete("/api/watchlist/ramesh@vigil").json()["removed"] is False
    assert client.get("/api/watchlist").json()["pinned"] == 0


def test_pin_rejects_unknown_and_external_accounts(client):
    assert client.post("/api/watchlist", json={"account_id": "nobody@vigil"}).status_code == 404
    ext = db.scalar("SELECT id FROM accounts WHERE kind = 'external' LIMIT 1")
    r = client.post("/api/watchlist", json={"account_id": ext})
    assert r.status_code == 400 and r.json()["error"]["code"] == "external_account"


def test_suggestions_exclude_alarm_statuses_and_explain_themselves(client):
    scenarios.run_sync("s2")
    u = {a["id"]: a for a in client.get("/api/live/universe").json()["accounts"]}
    w = client.get("/api/watchlist").json()
    for e in w["entries"]:
        assert not e["pinned"]
        assert e["status"] not in {"flagged", "held", "confirmed_fraud"}     # those are in "Needs attention"
        assert set(e["sources"]) <= {"early_warning", "model_only", "pattern_memory"} and e["sources"]
        assert e["next_step"]
    # every early-warning customer is suggested (up to the cap)
    ew = [a for a, v in u.items() if v["status"] == "early_warning"]
    listed = {e["account_id"] for e in w["entries"]}
    assert set(ew[:12]) <= listed or len(listed) == 12


def test_universe_accounts_carry_reason_families_and_since(client):
    scenarios.run_sync("s2")
    u = {a["id"]: a for a in client.get("/api/live/universe").json()["accounts"]}
    kiran = u["kiran.traders@vigil"]
    assert kiran["status"] == "flagged"
    assert kiran["reason"] and kiran["families_flagging"] >= 2 and len(kiran["families"]) == kiran["families_flagging"]
    assert kiran["status_since"]
    assert all(a["reason"] for a in u.values() if a["status"] in {"flagged", "early_warning", "held", "confirmed_fraud"})


def test_reset_clears_the_watchlist(client):
    client.post("/api/watchlist", json={"account_id": "ramesh@vigil"})
    client.post("/api/demo/reset")
    assert db.scalar("SELECT COUNT(*) FROM watchlist") == 0
    assert client.get("/api/watchlist").json()["pinned"] == 0


def test_live_stats_traffic_splits_postings_by_origin(client):
    from vigil.sim import ambient
    for _ in range(10):
        ambient._tick()
    scenarios.run_sync("atk_fan_in")
    t = client.get("/api/live/stats").json()["traffic"]
    assert t["bucket_seconds"] == 30 and len(t["buckets"]) >= 20
    assert set(t["buckets"][0]) == {"t", "everyday", "customer", "injected", "value_paise"}
    assert sum(b["injected"] for b in t["buckets"]) > 0 and sum(b["everyday"] for b in t["buckets"]) > 0
    assert t["postings"] == sum(b["everyday"] + b["customer"] + b["injected"] for b in t["buckets"])
    assert t["value_paise"] > 0 and t["avg_paise"] > 0 and t["channels"]
    assert 0 < len(t["largest"]) <= 5
    amounts = [x["amount_paise"] for x in t["largest"]]
    assert amounts == sorted(amounts, reverse=True)
    assert t["risky_postings"] >= 1                      # the fan-in hub is at early warning or worse


def test_new_accounts_lists_recent_openings_with_their_flows(client):
    scenarios.run_sync("atk_volume_spike")               # opens "Fresh Wallet" a day ago, then floods it
    rows = client.get("/api/live/new-accounts?days=30").json()
    assert rows == sorted(rows, key=lambda r: r["opened_at"], reverse=True)
    fresh = [r for r in rows if r["label"] == "Fresh Wallet"]
    assert fresh and fresh[0]["age_days"] < 2 and fresh[0]["in_paise"] > 0 and fresh[0]["senders"] >= 1
    assert all(r["age_days"] <= 30 for r in rows)
    old = db.scalar("SELECT COUNT(*) FROM accounts WHERE kind = 'customer'")
    assert len(rows) < old
