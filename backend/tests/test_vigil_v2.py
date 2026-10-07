"""v2 lead-owned features: replay, counterfactuals, provenance, shadow mode, scene, attacks."""

from __future__ import annotations

from vigil import db
from vigil.engine import ledger, lifecycle, mode, replay
from vigil.graph import scene
from vigil.sim import scenarios


def _decision(sid: str):
    r = [x for x in scenarios.run_sync(sid) if isinstance(x, dict) and x.get("decision_id")][0]
    return lifecycle.get_decision(r["decision_id"]), r


def test_replay_reconstructs_coercion_and_ends_at_recorded_tier(world):
    d, _ = _decision("s3")
    rp = replay.replay(d.decision_id)
    kinds = [f.kind for f in rp.frames]
    assert kinds[0] == "event" and "decision" in kinds
    decision_frame = next(f for f in rp.frames if f.kind == "decision")
    assert decision_frame.tier == d.tier == 4
    pre = [f for f in rp.frames if f.kind in {"event", "evaluation"}]
    assert pre[0].final_score == 0.0
    assert [f.final_score for f in pre] == sorted(f.final_score for f in pre)   # risk only accumulates
    labels = " ".join(f.label for f in rp.frames)
    for phrase in ("new device", "Payee added", "limit", "transfer attempted", "Scoped hold", "Trusted-contact alert"):
        assert phrase.lower() in labels.lower(), phrase
    # recomputation from evidence matches the recorded decision score
    assert abs(decision_frame.final_score - pre[-1].final_score) < 1e-6


def test_counterfactuals_come_from_policy_engine(world):
    d, _ = _decision("s3")
    cfs = replay.counterfactuals(d.decision_id)
    assert cfs and all(c.tier <= d.tier for c in cfs)
    safest = min(cfs, key=lambda c: c.tier)
    assert safest.tier <= 1 and safest.tier_delta < 0
    for sid in ("s0", "s4"):  # Tier 0 (incl. the high-value legitimate control): nothing to make safer
        d0, _ = _decision(sid)
        assert d0.tier == 0 and replay.counterfactuals(d0.decision_id) == []


def test_every_signal_has_provenance(world):
    for sid in ("s1", "s3"):
        d, _ = _decision(sid)
        for dim in d.dimensions:
            for s in dim.signals:
                assert s.provenance is not None, s.rule_id
                assert s.provenance.status in {"observed", "computed", "simulated"}
                assert s.provenance.freshness_s >= 0
    ext = [s for dim in d.dimensions for s in dim.signals if s.dimension == "context"]
    assert all(s.provenance.status == "simulated" for s in ext)


def test_shadow_mode_records_but_does_not_intervene(world):
    mode.set_mode("shadow")
    try:
        d, r = _decision("s3")
        intent = lifecycle.get_intent(r["intent_id"])
        assert d.mode == "shadow" and d.recommended_tier == 4 and d.applied_tier == 0
        assert d.baseline is not None and d.baseline.decision == "otp_step_up"
        assert db.q1("SELECT id FROM scoped_holds WHERE intent_id = ?", (r["intent_id"],)) is None
        assert db.q1("SELECT id FROM circuit_breaker_events WHERE intent_id = ?", (r["intent_id"],)) is None
        assert intent.state.value == "MONITORED"   # the bank baseline let it through (scenario auto-pays)
    finally:
        mode.set_mode("active")
    d2, _ = _decision("s1")
    assert d2.mode == "active" and d2.applied_tier == d2.tier


def test_scene_is_capped_cached_and_layered(world):
    scenarios.run_sync("s2")
    a = scene.build(cap=40)
    b = scene.build(cap=40)
    assert not a.cached and b.cached and a.version == b.version
    assert 0 < len(a.nodes) <= 40
    ids = {n.id for n in a.nodes}
    assert {"kiran.traders@vigil", "zenith.exports@vigil"} <= ids
    layer = {n.id: n.layer for n in a.nodes}
    assert layer["zenith.exports@vigil"] > layer["kiran.traders@vigil"]   # money flows left → right
    assert all(e.source in ids and e.target in ids for e in a.edges)


def test_scene_version_tracks_content_not_graph_counter(world):
    from vigil.graph.pathgraph import GRAPH

    scenarios.run_sync("atk_circular")
    a = scene.build(scenario="atk_circular")
    GRAPH.version += 1                      # e.g. an ambient posting elsewhere: cache miss, same picture
    b = scene.build(scenario="atk_circular")
    assert not b.cached and b.version == a.version
    before = scene.build().version
    scenarios.run_sync("s2")                # the s2 mule ring moves money inside the default scene
    assert scene.build().version != before


def test_scenario_tiers_do_not_depend_on_time_of_day(world, monkeypatch):
    from datetime import datetime, timezone

    from vigil import clock
    from vigil.contracts import CreateIntentRequest
    from vigil.sim import seed

    real_now = clock.now
    for hour_utc, tier in ((19, 2), (8, 2)):           # 01:00 IST (odd-hour window) and 13:30 IST
        offset = datetime(2026, 10, 6, hour_utc, 30, tzinfo=timezone.utc) - real_now()
        monkeypatch.setattr(clock, "now", lambda offset=offset: real_now() + offset)
        seed.seed()
        d, _ = _decision("s1")
        assert d.tier == tier and "BEH_ODD_HOUR" not in d.rules_fired
        assert d.reasons.audit["evaluation_context"] == {"local_hour_ist": clock.DEMO_LOCAL_HOUR_IST,
                                                         "local_hour_source": "pinned by scripted scenario"}
    # a live payment at 01:00 IST still sees the real hour
    offset = datetime(2026, 10, 6, 19, 30, tzinfo=timezone.utc) - real_now()
    monkeypatch.setattr(clock, "now", lambda: real_now() + offset)
    seed.seed()
    _, live = lifecycle.create(CreateIntentRequest(sender_id="ramesh@vigil", recipient_id="meena.grocer@vigil",
                                                   amount_paise=50_000))
    assert "BEH_ODD_HOUR" in live.rules_fired


def test_ambient_stream_keeps_every_account_within_its_own_routine(world):
    import pytest

    from vigil.sim import ambient

    legit = [r["id"] for r in db.q("SELECT id FROM accounts WHERE seed_role = 'legit' AND kind = 'customer'")]
    for _ in range(400):
        ambient._tick()
    assert ambient.STATE["count"] > 20                      # it still produces a visible stream ...
    for a in legit:                                          # ... but never pushes an account past its own busiest 72 h
        ambient_rows = db.scalar("SELECT COUNT(*) FROM transactions WHERE source = 'ambient' "
                                 "AND (sender_id = ? OR recipient_id = ?)", (a, a))
        if ambient_rows:
            assert not _over_routine(a), a
    pytest.importorskip("numpy")
    from vigil.intel import service

    scores = service.scores()["scores"]
    flagged = [a for a in legit if a in scores and (scores[a]["drift_level"] == "HIGH" or scores[a]["early_warning"]
                                                    or (scores[a]["rf"] or 0) >= 0.5 or (scores[a]["gnn"] or 0) >= 0.5)]
    assert flagged == []                                     # ordinary customers do not look like mules


def _over_routine(account_id: str) -> bool:
    from datetime import timedelta

    from vigil import clock
    from vigil.sim import ambient

    window_start = clock.now() - timedelta(hours=ambient.WINDOW_H)
    rows = db.q("SELECT ts FROM transactions WHERE (sender_id = ? OR recipient_id = ?) AND ts >= ?",
                (account_id, account_id, clock.iso(window_start - timedelta(days=ambient.BASELINE_DAYS))))
    current, blocks = 0, {}
    for r in rows:
        t = clock.parse(r["ts"])
        if t >= window_start:
            current += 1
        else:
            k = int((window_start - t).total_seconds() // (ambient.WINDOW_H * 3600))
            blocks[k] = blocks.get(k, 0) + 1
    return current > max(blocks.values(), default=0)


def test_attack_scenarios_are_deterministic_and_balanced(world):
    first = {sid: scenarios.touched_accounts(sid) for sid in scenarios.SCENARIOS if sid.startswith("atk_")}
    assert len(first) == 10
    for sid in first:
        scenarios.run_sync(sid)
        assert scenarios.replay_events(sid)
    assert ledger.system_total() == 0
    from vigil.sim import seed
    seed.seed()
    assert first == {sid: scenarios.touched_accounts(sid) for sid in first}


def _world_snapshot() -> dict:
    """Every row of every table (timestamps masked: the seed is anchored to now) + AUTOINCREMENT counters."""
    import json
    import re

    ts = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")
    out = {}
    for t in db.ALL_TABLES:
        out[t] = sorted(json.dumps({k: ts.sub("<ts>", r[k]) if isinstance(r[k], str) else r[k] for k in r.keys()},
                                   sort_keys=True) for r in db.q(f"SELECT * FROM {t}"))
    out["sqlite_sequence"] = sorted(f"{r['name']}={r['seq']}" for r in db.q("SELECT name, seq FROM sqlite_sequence"))
    return out


def test_reset_restores_identical_world_after_every_scenario(world):
    from vigil.sim import seed

    before = _world_snapshot()
    first = {sid: [x.get("tier") for x in scenarios.run_sync(sid) if isinstance(x, dict) and "tier" in x]
             for sid in scenarios.SCENARIOS}
    mode.set_mode("shadow")  # an operator toggle must not survive a demo reset
    seed.seed()
    assert _world_snapshot() == before
    assert mode.current()["mode"] == "active"
    again = {sid: [x.get("tier") for x in scenarios.run_sync(sid) if isinstance(x, dict) and "tier" in x]
             for sid in scenarios.SCENARIOS}
    assert again == first
    assert first["s0"] == [0] and first["s3"] == [4]


def test_scenario_and_focus_scenes_are_scoped_not_global(world):
    for sid in ("s2", "atk_circular"):
        scenarios.run_sync(sid)
    full = scene.build()
    ring = scene.build(scenario="atk_circular")
    ids = {n.id for n in ring.nodes}
    assert set(scenarios.touched_accounts("atk_circular")) <= ids
    assert "kiran.traders@vigil" not in ids          # the s2 mule ring is not mixed into another attack's scene
    assert len(ring.nodes) < len(full.nodes)
    focus = scene.build(focus="zenith.exports@vigil", hops=1)
    fids = {n.id for n in focus.nodes}
    assert {"zenith.exports@vigil", "kiran.traders@vigil"} <= fids
    assert not (set(scenarios.touched_accounts("atk_circular")) & fids)


def test_scene_route_rejects_unknown_scenario(world):
    from fastapi.testclient import TestClient
    from vigil.app import app

    with TestClient(app) as c:
        r = c.get("/api/graph/scene?scenario=nope")
        assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_scenario"


def test_interventions_min_tier_keeps_holds_visible(world):
    from fastapi.testclient import TestClient
    from vigil.app import app

    scenarios.run_sync("s3")                                   # Tier 4 hold + CircuitBreaker
    with TestClient(app) as c:
        for _ in range(3):
            scenarios.run_sync("s0")                           # newer, lower-tier traffic
        allrows = c.get("/api/interventions?status=all").json()
        serious = c.get("/api/interventions?status=all&min_tier=2").json()
        assert serious and all(r["tier"] >= 2 for r in serious)
        assert any(r["tier"] == 4 and r["hold"] for r in serious)
        assert {r["decision_id"] for r in serious} <= {r["decision_id"] for r in allrows}
        assert c.get("/api/interventions?min_tier=5").status_code == 422
        assert len(c.get("/api/interventions?status=all&limit=1").json()) <= 1


def test_spa_shell_is_never_cached(world):
    import pytest
    from fastapi.testclient import TestClient
    from vigil.app import app
    from vigil.settings import FRONTEND_DIST

    if not (FRONTEND_DIST / "index.html").is_file():
        pytest.skip("frontend not built")
    with TestClient(app) as c:
        for path in ("/", "/network", "/investigations/decision/DEC-000001"):
            r = c.get(path)
            assert r.status_code == 200 and r.headers.get("cache-control") == "no-cache", path


def test_touched_accounts_are_exactly_the_attack_participants(world):
    for sid in scenarios.SCENARIOS:
        if not sid.startswith("atk_"):
            continue
        scenarios.run_sync(sid)
        rows = db.q("SELECT sender_id, recipient_id FROM transactions WHERE seed_attack = ?", (sid,))
        actual = {a for r in rows for a in (r["sender_id"], r["recipient_id"]) if not a.startswith("ext:")}
        assert set(scenarios.touched_accounts(sid)) == actual, sid
