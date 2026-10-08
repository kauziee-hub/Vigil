"""Live detection stream (v3): hook listener, WS event shapes, latency, status precedence, adaptive threshold.

Behavioural checks on the seeded demo world (SYNTHETIC). Status semantics: docs/V3_LIVE_PLATFORM_PLAN.md.
"""

from __future__ import annotations

import statistics
from datetime import timedelta

import pytest


def _drain(q) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _ordinary(db):
    rows = db.q("SELECT id FROM accounts WHERE kind = 'customer' AND seed_role = 'legit' AND is_demo_customer = 0")
    return {r["id"] for r in rows}


@pytest.fixture()
def stream(world):
    from vigil.graph.pathgraph import GRAPH
    from vigil.intel import live
    from vigil.intel import stream as S
    GRAPH.load()
    live.CACHE.clear()
    S.status_map()                   # baseline for this world (new epoch -> state reset)
    return S


def test_listener_registered_by_the_intel_router():
    import vigil.intel.api  # noqa: F401  (the app includes this router)
    from vigil.engine import hooks
    from vigil.intel import stream as S
    assert S.on_posting in hooks._listeners
    assert any("on_posting" in name for name in hooks.stats()["listeners"])


def test_seeding_does_not_trigger_live_scoring(world):
    from vigil.intel import stream as S
    from vigil.realtime import HUB
    from vigil.sim import seed
    q = HUB.subscribe(["console"])
    try:
        before = S.STATE.counters["postings"]
        seed.seed()
        assert S.STATE.counters["postings"] == before
        assert not [e for e in _drain(q) if e["type"].startswith("intel.")]
    finally:
        HUB.unsubscribe(q)


def test_events_have_contract_shapes(stream):
    from vigil.contracts import AccountStatusChange, TxScored
    from vigil.engine import ledger
    from vigil.realtime import HUB
    q = HUB.subscribe(["console"])
    try:
        tx = ledger.post(sender_id="ramesh@vigil", recipient_id="sunita@vigil", amount_paise=12_300, source="user")
        events = _drain(q)
    finally:
        HUB.unsubscribe(q)
    scored = [e for e in events if e["type"] == "intel.tx_scored"]
    assert len(scored) == 1
    ev = TxScored.model_validate(scored[0]["data"])
    assert ev.tx_id == tx["id"] and ev.sender_id == "ramesh@vigil" and ev.origin == "user"
    assert ev.scored_ms > 0 and ev.sender_status != "idle" and ev.recipient_status != "idle"
    changes = [AccountStatusChange.model_validate(e["data"]) for e in events if e["type"] == "intel.account_status"]
    by_id = {c.account_id: c for c in changes}
    # both parties were idle in the freshly seeded world; the posting makes them active
    for a, status in (("ramesh@vigil", ev.sender_status), ("sunita@vigil", ev.recipient_status)):
        assert a in by_id, by_id
        assert by_id[a].previous == "idle" and by_id[a].status == status and by_id[a].reason
    assert stream.status_map()["ramesh@vigil"]["status"] == ev.sender_status


def test_latency_budget_under_ambient(stream):
    """p95 < 30 ms per posting (hook runs synchronously on the event-loop thread)."""
    from vigil.sim import ambient
    stream.STATE.latencies.clear()
    for _ in range(150):
        ambient._tick()
    lat = sorted(stream.STATE.latencies)
    assert len(lat) >= 30
    p95 = lat[int(0.95 * (len(lat) - 1))]
    assert statistics.median(lat) < 20, lat
    assert p95 < 30, (p95, lat[-5:])
    assert stream.STATE.counters["errors"] == 0


def test_no_ordinary_account_flagged_or_warned_under_ambient(stream, world):
    from vigil.sim import ambient
    for _ in range(300):
        ambient._tick()
    assert ambient.STATE["count"] >= 50
    sm = stream.status_map()
    ordinary = _ordinary(world)
    bad = {a: (sm[a]["status"], sm[a]["reason"]) for a in ordinary if sm[a]["status"] in ("flagged", "early_warning")}
    assert not bad, bad
    assert {"normal", "idle"} <= {sm[a]["status"] for a in ordinary}


def test_status_precedence_with_vigil_state(stream, world):
    from vigil import clock
    S = stream
    a = "kiran.traders@vigil"
    sm = S.status_map()
    assert sm[a]["status"] == "flagged" and sm[a]["role"] and sm[a]["model_risk"] >= S.current_threshold()
    now = clock.now()
    world.insert("scoped_holds", {"id": "HOLD-T1", "intent_id": "INT-T1", "account_id": a, "held_paise": 100_000,
                                  "reference": "t", "opened_at": clock.iso(now), "review_by": clock.iso(now + timedelta(hours=1))})
    assert S.status_map()[a]["status"] == "held"                 # held > flagged
    tx = world.q1("SELECT id FROM transactions WHERE recipient_id = ? ORDER BY seq DESC LIMIT 1", (a,))
    world.insert("fraud_labels", {"id": "LBL-T1", "transaction_id": tx["id"], "grade": "reported_unverified",
                                  "label": "scam", "labelled_by": "test", "ts": clock.iso(now)})
    assert S.status_map()[a]["status"] == "held"                 # an unverified report is not "confirmed"
    world.insert("fraud_labels", {"id": "LBL-T2", "transaction_id": tx["id"], "grade": "bank_confirmed",
                                  "label": "scam", "labelled_by": "test", "ts": clock.iso(now)})
    sm = S.status_map()
    assert sm[a]["status"] == "confirmed_fraud"                  # confirmed_fraud > held
    world.execute("UPDATE scoped_holds SET released_at = ?, outcome = 'released' WHERE id = 'HOLD-T1'", (clock.iso(now),))
    assert S.status_map()[a]["status"] == "confirmed_fraud"
    # every status is one of the contract values; externals are "external"
    from vigil.intel import live
    for acc, v in sm.items():
        assert v["status"] in ("normal", "idle", "new", "early_warning", "flagged", "held", "confirmed_fraud", "external")
        assert (v["status"] == "external") == live.SRC.is_external(acc)


def test_new_idle_normal_semantics(stream):
    from vigil import clock
    from vigil.intel import live
    S = stream
    now_t = clock.now().timestamp()
    for a, v in S.status_map().items():
        if v["status"] == "new":
            assert (now_t - live.SRC.opened_t(a)) / 86400 < S.NEW_ACCOUNT_DAYS
        if v["status"] in ("normal", "idle"):
            last = S.STATE.last_t.get(a)
            active = last is not None and last >= now_t - S.LIVE_WINDOW_MINUTES * 60
            assert active == (v["status"] == "normal"), (a, v)


def test_classify_rule():
    from vigil.intel.stream import classify
    assert classify(0.95, "random_forest", ["random_forest", "gnn"], 0.85) == "flagged"
    assert classify(0.95, "random_forest", ["random_forest"], 0.85) is None              # uncorroborated: weak only
    assert classify(0.93, "gnn", ["gnn"], 0.85) is None
    assert classify(0.80, "random_forest", ["random_forest", "gnn"], 0.85) == "early_warning"  # 2 families, below T
    assert classify(0.20, "random_forest", ["drift"], 0.85) is None                      # drift alone (victim shape)
    assert classify(0.20, "random_forest", ["rules"], 0.85) is None                      # rules alone (busy merchant)
    assert classify(0.20, "random_forest", ["early_warning"], 0.85) == "early_warning"
    assert classify(None, None, [], 0.85) is None


def test_threshold_step_rule_is_bounded_and_explained():
    from vigil.intel.stream import T_MAX, T_MIN, T_STEP, threshold_step
    never = lambda t: 0  # noqa: E731
    t, why = threshold_step(0.60, [0.9], [], 3, never)
    assert t == pytest.approx(0.60 + T_STEP) and "raise" in why
    t, why = threshold_step(T_MAX, [0.95], [], 3, never)
    assert t == T_MAX and "upper bound" in why
    t, why = threshold_step(0.60, [0.30], [], 3, never)                  # FP not caused by model evidence
    assert t == 0.60
    t, why = threshold_step(0.60, [], [(0.59, True)], 3, never)          # corroborated near miss
    assert t == pytest.approx(0.60 - T_STEP) and "lower" in why
    t, why = threshold_step(0.60, [], [(0.59, True)], 3, lambda lowered: 2)
    assert t == 0.60 and "outside this attack" in why                   # collateral -> hold
    t, why = threshold_step(0.60, [], [(0.59, False)], 3, never)         # uncorroborated near miss -> hold
    assert t == 0.60
    t, why = threshold_step(0.60, [], [(0.10, True)], 3, never)          # far below -> hold
    assert t == 0.60 and "would not catch" in why
    t, why = threshold_step(T_MIN, [], [(T_MIN - 0.01, True)], 3, never)
    assert t == T_MIN and "lower bound" in why
    t, why = threshold_step(0.60, [], [], 3, never)
    assert t == 0.60 and "all injected" in why


def test_adaptive_threshold_logged_idempotent_and_reset_with_demo(stream, world):
    from vigil.intel import consensus as C
    from vigil.sim import seed
    S = stream
    T0 = S.current_threshold()
    assert S.T_MIN <= T0 <= S.T_MAX
    h0 = S.threshold_history()
    assert len(h0) == 1 and "initial" in h0[0]["reason"] and h0[0]["value"] == T0
    before = [r.model_dump() for r in C.corroboration("kiran.traders@vigil")]
    # pretend the threshold had drifted down, then a run reports a model-driven false positive
    S.STATE.threshold = 0.61
    run = {"run_id": "RUN-T1", "scenario_id": "atk_fan_in", "injected": ["swift.collect@vigil"], "detected": [],
           "missed": [], "false_positives": ["kiran.traders@vigil"], "recall": 0.0}
    S.on_run_evaluated(run)
    hist = S.threshold_history()
    assert hist[-1]["changed"] and hist[-1]["value"] == pytest.approx(0.63) and hist[-1]["previous"] == 0.61
    assert "false positive" in hist[-1]["reason"] and hist[-1]["run_id"] == "RUN-T1"
    S.on_run_evaluated(run)                                                # idempotent per run
    assert len(S.threshold_history()) == len(hist)
    # never touches the payment path: corroboration() (model evidence for decisions) is unchanged
    assert [r.model_dump() for r in C.corroboration("kiran.traders@vigil")] == before
    # reset with the demo restores the initial threshold and history
    seed.seed()
    S.status_map()
    assert S.current_threshold() == T0 and len(S.threshold_history()) == 1
    # determinism: the same run sequence gives the same thresholds
    seq = []
    for _ in range(2):
        seed.seed()
        S.status_map()
        S.STATE.threshold = 0.61
        S.on_run_evaluated(dict(run, run_id="RUN-A"))
        S.on_run_evaluated(dict(run, run_id="RUN-B", false_positives=[], missed=["swift.collect@vigil"]))
        seq.append([h["value"] for h in S.threshold_history()])
    assert seq[0] == seq[1]


def test_attack_scenario_streams_scenario_origin_and_flags_the_mule(stream):
    from vigil.contracts import TxScored
    from vigil.realtime import HUB
    from vigil.sim import scenarios
    q = HUB.subscribe(["console"])
    try:
        scenarios.run_sync("atk_fan_in")
        events = _drain(q)
    finally:
        HUB.unsubscribe(q)
    scored = [TxScored.model_validate(e["data"]) for e in events if e["type"] == "intel.tx_scored"]
    assert scored and all(s.origin == "scenario" for s in scored)
    last = [s for s in scored if s.recipient_id == "swift.collect@vigil"][-1]
    assert last.recipient_status == "flagged" and last.recipient_risk >= stream.current_threshold()
    changes = [e["data"] for e in events if e["type"] == "intel.account_status"
               and e["data"]["account_id"] == "swift.collect@vigil"]
    assert changes and changes[-1]["status"] == "flagged" and changes[-1]["previous"] in ("new", "early_warning")
    # the role is assessed on the flagged network as it grows; at the end of the attack it is a collector
    assert stream.status_map()["swift.collect@vigil"]["role"] == "collector"
    assert stream.roles_flagged().get("collector", 0) >= 1
