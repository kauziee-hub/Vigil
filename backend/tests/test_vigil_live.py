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


def _full_trace() -> dict:
    """Reference: trace_multi over EVERY journal with real account kinds (the pre-v3 implementation)."""
    from datetime import timezone

    from prima.attribution.trace import Incident, ProvenanceGrade, trace_multi
    from prima.ledger.models import Account, AccountKind, Journal, JournalKind, simple_transfer_entries

    from vigil import clock
    from vigil.risk import taint

    accounts = {r["id"]: Account(id=r["id"], kind=AccountKind.CUSTOMER if r["kind"] == "customer" else AccountKind.EXTERNAL)
                for r in db.q("SELECT id, kind FROM accounts")}
    journals = [Journal(id=r["id"], kind=taint._KIND.get(r["kind"], JournalKind.TRANSFER),
                        entries=simple_transfer_entries(r["sender_id"], r["recipient_id"], int(r["amount_paise"])),
                        occurred_at=clock.parse(r["ts"]).astimezone(timezone.utc), seq=int(r["seq"]), prev_hash=taint.GENESIS)
                for r in db.q("SELECT * FROM transactions ORDER BY seq")]
    incidents = [Incident(id=l["id"], origin_journal_ids=frozenset({l["transaction_id"]}), reported_at=clock.parse(l["ts"]),
                          grade=ProvenanceGrade.BANK_CONFIRMED) for l in taint._labels()]
    out = {}
    for rule in taint.RULES:
        for inc_id, d in trace_multi(journals, incidents, rule, accounts, de_minimis_floor=taint.DE_MINIMIS_PAISE).items():
            p = d.payload()
            out[(inc_id, rule.value)] = (sorted((c["account_id"], c["amount_paise"]) for c in p["claims"] if c["amount_paise"] > 0),
                                         p["left_perimeter_paise"], p["spent_paise"], p["attributable_total_paise"])
    return out


def test_restricted_taint_trace_equals_full_trace(world):
    from vigil.risk import taint

    scenarios.run_sync("s2")
    scenarios.run_sync("atk_fan_in")
    for _ in range(30):
        ambient._tick()
    for sender, recipient in (("anita.s@vigil", "kiran.traders@vigil"),):
        tx = db.q1("SELECT id FROM transactions WHERE sender_id = ? AND recipient_id = ?", (sender, recipient))
        with db.tx():
            db.insert("fraud_labels", {"id": "LBL-EQ1", "transaction_id": tx["id"], "grade": "bank_confirmed",
                                       "label": "scam", "labelled_by": "test", "ts": "2026-10-07T00:00:00.000Z"})
    fan = db.q("SELECT id FROM transactions WHERE recipient_id = 'swift.collect@vigil' ORDER BY seq")[0]
    with db.tx():
        db.insert("fraud_labels", {"id": "LBL-EQ2", "transaction_id": fan["id"], "grade": "bank_confirmed",
                                   "label": "scam", "labelled_by": "test", "ts": "2026-10-07T00:00:01.000Z"})
    fast = taint.run(force=True)
    full = _full_trace()
    got = {}
    for inc in fast["incidents"]:
        for rule, r in inc["rules"].items():
            got[(inc["label_id"], rule)] = (sorted((c["account_id"], c["amount_paise"]) for c in r["claims"]),
                                            r["left_perimeter_paise"], r["spent_paise"], r["attributable_total_paise"])
    assert got == full
    assert fast["journals_considered"] < db.scalar("SELECT COUNT(*) FROM transactions") / 5   # it really is restricted


def test_taint_cache_survives_unrelated_postings(world):
    import time

    from vigil.risk import taint

    scenarios.run_sync("s2")
    tx = db.q1("SELECT id FROM transactions WHERE sender_id = 'anita.s@vigil' AND recipient_id = 'kiran.traders@vigil'")
    with db.tx():
        db.insert("fraud_labels", {"id": "LBL-C1", "transaction_id": tx["id"], "grade": "bank_confirmed",
                                   "label": "scam", "labelled_by": "test", "ts": "2026-10-07T00:00:00.000Z"})
    first = taint.run(force=True)
    for _ in range(10):
        ambient._tick()                       # person-to-merchant postings outside the closure
    t = time.perf_counter()
    again = taint.run()
    assert (time.perf_counter() - t) < 0.05
    assert again is first


def test_demo_reset_rewarms_detection_intelligence(client, monkeypatch):
    """The first payment after a reset must not pay the cold intel build (675 ms → 17 ms on world v3)."""
    intel = pytest.importorskip("vigil.intel")
    calls: list[int] = []
    monkeypatch.setattr(intel, "warm", lambda: calls.append(1))
    assert client.post("/api/demo/reset").status_code == 200
    assert calls == [1]


def test_pathgraph_windows_stay_exact_with_back_dated_postings(world):
    """Window queries bisect on t; per-account lists must stay chronological even for a back-dated posting."""
    from vigil import clock
    from vigil.graph.pathgraph import GRAPH

    acct = "kiran.traders@vigil"
    newest = GRAPH.in_edges[acct][-1]
    GRAPH.add_transaction({"id": "TX-BACKDATED", "seq": 10**9, "sender_id": "ramesh@vigil", "recipient_id": acct,
                           "amount_paise": 100, "ts": clock.iso(clock.parse(newest.ts) - __import__("datetime").timedelta(hours=1)),
                           "kind": "transfer"})
    for edges in (GRAPH.in_edges[acct], GRAPH.out_edges["ramesh@vigil"]):
        assert all(edges[i].t <= edges[i + 1].t for i in range(len(edges) - 1))
    for since in (newest.t - 7200, newest.t - 3600, newest.t, newest.t + 1):
        assert GRAPH.inflows(acct, since) == [e for e in GRAPH.in_edges[acct] if e.t >= since]
        assert GRAPH.inflows_before(acct, since) == [e for e in GRAPH.in_edges[acct] if e.t < since]
    GRAPH.load()
