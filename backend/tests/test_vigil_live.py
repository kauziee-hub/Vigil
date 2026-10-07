"""v3 live platform (lead-owned): world v3, universe, live stats, attack runs, posting hooks."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vigil import db
from vigil.engine import hooks, ledger
from vigil.sim import ambient, runs, scenarios


@pytest.fixture()
def client(world):
    from vigil.app import app

    with TestClient(app) as c:
        yield c


def test_world_v3_is_a_busy_everyday_economy(world):
    customers = db.scalar("SELECT COUNT(*) FROM accounts WHERE kind = 'customer' AND (persona IS NULL OR persona != 'merchant')")
    merchants = db.scalar("SELECT COUNT(*) FROM accounts WHERE persona = 'merchant'")
    txs = db.scalar("SELECT COUNT(*) FROM transactions WHERE kind != 'opening'")
    assert customers >= 450 and merchants >= 25 and txs >= 20_000
    assert ledger.system_total() == 0


def test_hooks_fire_for_live_postings_not_for_seeding(world):
    seen: list[str] = []
    fn = hooks.register(lambda tx: seen.append(tx["id"]))
    try:
        from vigil.sim import seed
        seed.seed()
        assert seen == []                                   # bulk history does not trigger live scoring
        for _ in range(5):
            ambient._tick()
        assert len(seen) >= 1
        bad = hooks.register(lambda tx: 1 / 0)              # a failing listener never breaks a posting
        ambient._tick()
        hooks.unregister(bad)
    finally:
        hooks.unregister(fn)


def test_universe_has_every_account_and_live_edges(client):
    for _ in range(20):
        ambient._tick()
    u = client.get("/api/live/universe").json()
    ids = {a["id"] for a in u["accounts"]}
    assert len(ids) == db.scalar("SELECT COUNT(*) FROM accounts")
    assert u["edges"] and all(e["origin"] in {"ambient", "scenario", "user"} for e in u["edges"])
    assert all(e["scenario"] is None for e in u["edges"] if e["origin"] != "scenario")
    assert 0 < len(u["history_edges"]) <= 600
    assert {a["group"] for a in u["accounts"]} >= {"customer", "merchant", "demo", "external"}
    assert "mule_attack" not in {a["group"] for a in u["accounts"]}   # no ground truth in the visual grouping


def test_attack_runs_are_evaluated_against_ground_truth(client):
    scenarios.run_sync("s2")
    scenarios.run_sync("atk_fan_in")
    rs = client.get("/api/attacks/runs").json()
    assert [r["scenario_id"] for r in rs] == ["atk_fan_in", "s2"]       # newest first
    s2 = rs[1]
    assert s2["status"] == "completed" and s2["injected"]
    assert "kiran.traders@vigil" in s2["detected"]
    assert s2["recall"] is not None and s2["recall"] >= 0.5
    assert s2["first_warning_ms"] is not None and s2["detection_ms"] is not None
    victims = {"anita.s@vigil", "vikram.p@vigil", "farah.k@vigil", "joseph.d@vigil", "lakshmi.n@vigil"}
    assert not (victims & set(s2["false_positives"]))
    assert client.get(f"/api/attacks/runs/{s2['run_id']}").json()["run_id"] == s2["run_id"]
    assert client.get("/api/attacks/runs/NOPE").status_code == 404


def test_live_stats_shapes(client):
    for _ in range(10):
        ambient._tick()
    scenarios.run_sync("atk_smurfing")
    s = client.get("/api/live/stats").json()
    assert len(s["volume"]) >= 60 and set(s["volume"][0]) == {"t", "normal", "attack"}
    assert sum(b["attack"] for b in s["volume"]) > 0 and sum(b["normal"] for b in s["volume"]) > 0
    assert s["channels"] and s["counts"]["accounts"] > 500
    assert s["runs_by_type"][0]["scenario_id"] == "atk_smurfing"


def test_reset_clears_runs(client):
    scenarios.run_sync("atk_fan_in")
    assert runs.all_runs()
    client.post("/api/demo/reset")
    assert runs.all_runs() == []
