"""World v3 revalidation (v3 run 2, M4): early warning v3.0, training generator v3.0, incremental refresh on a
dense world, and per-attack LIVE detection through the stream (SYNTHETIC; behavioural checks, not metrics)."""

from __future__ import annotations

import pytest


def _f(**kw) -> dict[str, float]:
    from vigil.intel import features as F
    f = F.zero_features()
    f.update(kw)
    return f


STATS = {"age_p30": 1000.0, "mean_tx": 8.0, "std_tx": 20.0, "n": 500.0}


# ── early warning v3.0 (pure) ─────────────────────────────────────────────
def test_high_velocity_needs_the_account_to_be_busier_than_its_own_baseline():
    from vigil.intel import early_warning as EW
    shop = _f(transaction_count=224, baseline_tx_rate=242.0, account_age_days=2000)     # a busy shop at its routine
    assert "High Velocity" not in EW.raw(shop, STATS)[1]
    burst = _f(transaction_count=224, baseline_tx_rate=40.0, account_age_days=2000)     # 5x its own rate
    assert "High Velocity" in EW.raw(burst, STATS)[1]
    fresh = _f(transaction_count=60, baseline_tx_rate=0.0, account_age_days=3)          # no baseline: population only
    assert "High Velocity" in EW.raw(fresh, STATS)[1]


def test_high_fan_out_counts_first_time_recipients():
    from vigil.intel import early_warning as EW
    habitual = _f(out_degree=4, unique_neighbors=5, new_counterparty_ratio=0.0, account_age_days=150, transaction_count=7)
    assert "High Fan-Out" not in EW.raw(habitual, STATS)[1]          # pays four usual shops: not a fan-out
    distributor = _f(out_degree=6, unique_neighbors=7, new_counterparty_ratio=1.0, transaction_count=7)
    assert "High Fan-Out" in EW.raw(distributor, STATS)[1]
    collector = _f(in_degree=6, out_degree=1, unique_neighbors=7, new_counterparty_ratio=1.0, transaction_count=7)
    assert "High Fan-Out" not in EW.raw(collector, STATS)[1]         # new SENDERS are not fan-out


def test_early_warning_population_cache_is_exact():
    from ml import datagen
    from vigil.intel import early_warning as EW
    from vigil.intel import features as F
    w = datagen.make_world(8)                                        # a dense (everyday-economy) world
    feats = {a: F.extract(w, a, w.now_t) for a in w.scored_accounts()}
    out, stats = EW.evaluate_population(feats)
    for a, f in feats.items():
        s, sig = EW.raw(f, stats)
        assert (out[a]["score"], out[a]["signals"]) == (s, sig)
        assert out[a]["flagged"] == EW.evaluate(f, stats)["flagged"]
    o1, _, cache = EW.evaluate_population_cached(feats, None)
    o2, _, _ = EW.evaluate_population_cached(feats, cache)
    assert o1 == o2 == out


# ── training generator v3.0 ───────────────────────────────────────────────
def test_generator_v3_adds_only_the_everyday_layer():
    """The everyday layer has its own random stream: background, attacks and labels are those of v2.1."""
    from ml import datagen
    from vigil.intel import features as F
    dense = [i for i in range(12) if datagen.make_world(i).everyday]
    assert 4 <= len(dense) <= 11                                     # about two worlds in three
    i = dense[0]
    w3, w2 = datagen.make_world(i), datagen.make_world(i, everyday=False)
    assert not w2.everyday and w3.everyday["payers"] > 50
    assert w3.attacks == w2.attacks
    assert {a: y for a, y in w3.labels.items() if a in w2.labels} == w2.labels
    assert all(w3.labels[a] == 0 for a in set(w3.labels) - set(w2.labels))        # shops are never mules
    assert w3.n_edges > 2 * w2.n_edges
    shops = [a for a in w3.accounts if ".shop" in a]
    f = F.extract(w3, max(shops, key=lambda a: len(w3.inflows(a))), w3.now_t)
    assert f["in_degree"] >= 20 and f["forwarded_fraction"] == 0.0               # busy, but never a fast pass-through


# ── incremental refresh on world v3 ───────────────────────────────────────
def test_habitual_payment_re_measures_only_its_two_parties(world):
    from vigil.engine import ledger
    from vigil.intel import features as F
    from vigil.intel import live
    before = live.build()
    assert len(before.ids) > 500                                     # world v3 scale
    shop = "kirana.patil@vigil"
    payer = next(e.src for e in reversed(live.GRAPH.in_edges[shop]) if not live.SRC.is_external(e.src))
    ledger.post(sender_id=payer, recipient_id=shop, amount_paise=24_000, source="user")
    inc = live.refresh(before)
    assert inc.recomputed == sorted({payer, shop})
    assert len(inc.ctx_refreshed) <= 5                               # not the shop's ~100 window counterparties
    nodes = live.external_ids() + inc.ids
    assert set(inc.pairs_t) == F.window_pairs(live.SRC, nodes, inc.now_t)
    full = live.build(now_t=inc.now_t)
    for a in (payer, shop):
        assert inc.feats[a] == full.feats[a] and inc.flags[a] == full.flags[a]
        assert abs(inc.gnn[a][0] - full.gnn[a][0]) < 1e-9


def test_closing_a_loop_refreshes_the_cycle_context_of_the_whole_ring(world):
    from vigil.intel import live
    from vigil.sim import scenarios                                  # (imports attacks; attacks first is circular)
    from vigil.sim import attacks
    ring = attacks.pool("atk_circular")[:4]
    steps = scenarios.SCENARIOS["atk_circular"].steps()
    for step in steps[:3]:                                           # three hops: no loop yet
        step.action()
    before = live.build()
    assert not any(before.ctx[a]["in_cycle"] for a in ring)
    steps[3].action()                                                # the hop back to the origin closes the loop
    inc = live.refresh(before)
    assert set(ring) - set(inc.recomputed) <= set(inc.ctx_refreshed)
    assert all(inc.ctx[a]["in_cycle"] for a in ring)
    full = live.build(now_t=inc.now_t)
    assert {a: inc.ctx[a]["in_cycle"] for a in ring} == {a: full.ctx[a]["in_cycle"] for a in ring}
    assert {a: inc.flags[a] for a in ring} == {a: full.flags[a] for a in ring}


# ── per-attack live detection (the stream's statuses, evaluated as an AttackRun) ──
ATTACKS = ["s2", "atk_fan_in", "atk_fan_out", "atk_circular", "atk_velocity_chain", "atk_cross_channel",
           "atk_shared_device", "atk_behavioural_drift", "atk_volume_spike", "atk_smurfing", "atk_dormant"]


@pytest.fixture()
def live_stream(world):
    from vigil.graph.pathgraph import GRAPH
    from vigil.intel import live
    from vigil.intel import stream as S
    GRAPH.load()
    live.CACHE.clear()
    S.status_map()
    return S


@pytest.mark.parametrize("sid", ATTACKS)
def test_attack_run_is_detected_live_without_false_positives(live_stream, sid):
    """Every attack: at least one injected mule reaches the live 'flagged' status during the run (warned no
    later than detected), and no participant outside the injected mules is flagged."""
    from vigil.sim import runs, scenarios
    scenarios.run_sync(sid)
    run = runs.all_runs()[0]
    assert run.status == "completed" and run.injected
    assert run.detected and set(run.detected) <= set(run.injected), (run.detected, run.injected)
    assert run.false_positives == []
    assert run.first_warning_ms is not None and run.detection_ms is not None
    assert run.first_warning_ms <= run.detection_ms
    assert set(run.detected) <= set(run.warned)
