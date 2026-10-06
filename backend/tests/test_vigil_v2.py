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
