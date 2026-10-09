"""Detection intelligence: consensus semantics, the payment-path hook, latency, never-raise, never-fused."""

from __future__ import annotations

import statistics
import time

import pytest

from vigil.contracts import DetectorConsensus, DetectorResult


def _r(family: str, flagged: bool, status: str = "ok") -> DetectorResult:
    return DetectorResult(family=family, label=family, value=0.5, display="0.50", kind="score", flagged=flagged,
                          status=status, version="t", observed_at="2026-01-01T00:00:00.000Z")


# ── consensus semantics (pure) ────────────────────────────────────────────
@pytest.mark.parametrize("n_flag,level", [(0, "none"), (1, "weak"), (2, "moderate"), (3, "moderate"), (4, "strong"),
                                          (8, "strong")])
def test_agreement_levels(n_flag, level):
    from vigil.intel.consensus import summarise
    fams = ["rules", "random_forest", "gnn", "drift", "early_warning", "pattern_memory", "ringwatch", "external"]
    res = [_r(f, i < n_flag) for i, f in enumerate(fams)]
    c = summarise(res)
    assert isinstance(c, DetectorConsensus)
    assert c.families_flagging == n_flag and c.families_evaluated == 8 and c.agreement == level
    assert f"{n_flag} of 8" in c.summary or (n_flag == 0 and "No signal family" in c.summary)


def test_consensus_counts_only_ok_results():
    from vigil.intel.consensus import summarise
    res = [_r("rules", True), _r("random_forest", True, "unavailable"), _r("gnn", True, "not_applicable"),
           _r("drift", False)]
    c = summarise(res)
    assert (c.families_flagging, c.families_evaluated, c.agreement) == (1, 2, "weak")
    assert "uncorroborated" in c.summary
    empty = summarise([])
    assert (empty.families_flagging, empty.families_evaluated, empty.agreement) == (0, 0, "none")
    # agreement is monotone in the number of flagging families
    order = ["none", "weak", "moderate", "strong"]
    levels = [summarise([_r(f"rules", i < k) for i in range(6)]).agreement for k in range(7)]
    assert [order.index(x) for x in levels] == sorted(order.index(x) for x in levels)


# ── corroboration: payment-path contract ──────────────────────────────────
@pytest.mark.parametrize("bad", ["", "nobody@vigil", "ext:atm", "ext:other-bank", None, 42, "x" * 5000])
def test_corroboration_never_raises_and_is_empty_for_unknown_or_external(world, bad):
    from vigil.intel.consensus import corroboration
    assert corroboration(bad) == []


def test_corroboration_shape_and_honest_kinds(world):
    from vigil.intel import warm
    from vigil.intel.consensus import corroboration
    warm()
    res = corroboration("kiran.traders@vigil")
    assert [r.family for r in res] == ["random_forest", "gnn", "rules", "early_warning", "drift", "pattern_memory"]
    kinds = {r.family: r.kind for r in res}
    assert kinds["random_forest"] in {"probability_calibrated", "probability_uncalibrated"}
    assert kinds["gnn"] in {"probability_calibrated", "probability_uncalibrated"}
    assert kinds["rules"] == "score" and kinds["early_warning"] == "score"
    assert kinds["drift"] == "level" and kinds["pattern_memory"] == "similarity"
    for r in res:
        DetectorResult.model_validate(r.model_dump())
        assert r.status == "ok"
        if r.kind == "probability_calibrated":
            assert "synthetic" in r.detail["calibration"].lower()
    # an ordinary account with no window activity still gets honest (unflagged) results
    quiet = corroboration("dormant.savings@vigil")
    assert len(quiet) == 6 and not any(r.flagged for r in quiet)


def test_corroboration_survives_internal_failure(world, monkeypatch):
    from vigil.intel import consensus, live

    def boom(*_a, **_k):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(live.CACHE, "current", boom)
    assert consensus.corroboration("kiran.traders@vigil") == []


def test_warm_is_idempotent_and_never_raises(world, monkeypatch):
    from vigil.intel import live, warm
    from vigil.intel.models import STORE
    warm()
    snap = live.CACHE.snap
    warm()                                   # same graph state -> same cached snapshot
    assert live.CACHE.snap is snap
    monkeypatch.setattr(STORE, "load", lambda: (_ for _ in ()).throw(RuntimeError("disk gone")))
    warm()                                   # must not raise


def test_corroboration_does_not_need_shap(world, monkeypatch):
    from vigil.intel import consensus
    from vigil.intel.models import STORE

    def no_shap():
        raise AssertionError("SHAP must never be touched on the payment path")

    monkeypatch.setattr(STORE, "explainer", no_shap)
    monkeypatch.setattr(STORE, "shap_values", no_shap)
    consensus.warm(shap_in_background=False)
    assert len(consensus.corroboration("zenith.exports@vigil")) == 6


def test_corroboration_latency_budget(world):
    """< 20 ms once warm, including the incremental refresh after new postings (median of 5)."""
    from vigil.engine import ledger
    from vigil.intel import consensus
    from vigil.sim import scenarios
    consensus.warm(shap_in_background=False)
    scenarios.run_sync("s2")                 # many new postings since the warm snapshot
    timings = []
    for i in range(5):
        if i:
            ledger.post(sender_id="ramesh@vigil", recipient_id="meena.grocer@vigil", amount_paise=100_00 + i,
                        kind="transfer", note="latency probe", source="user")
        t0 = time.perf_counter()
        res = consensus.corroboration("kiran.traders@vigil")
        timings.append((time.perf_counter() - t0) * 1000)
        assert len(res) == 6
    assert statistics.median(timings) < 20.0, timings
    t0 = time.perf_counter()
    consensus.corroboration("kiran.traders@vigil")
    assert (time.perf_counter() - t0) * 1000 < 5.0      # same graph state: cache hit


def test_model_evidence_is_never_fused_into_the_tier(world, monkeypatch):
    """Same payment, with and without intel: identical score and tier; evidence only attached."""
    from vigil.engine import decide
    from vigil.intel import consensus
    from vigil.sim import scenarios
    scenarios.run_sync("s2")
    intent = {"id": "INT-INTELTEST", "sender_id": "ramesh@vigil", "recipient_id": "kiran.traders@vigil",
              "amount_paise": 45_000_00, "note": "advance for goods", "channel": "upi"}
    with_intel = decide.evaluate(dict(intent))
    assert {m.family for m in with_intel.model_evidence} >= {"random_forest", "gnn", "rules"}
    assert all(m.flagged for m in with_intel.model_evidence if m.family in {"random_forest", "gnn"})
    monkeypatch.setattr(consensus, "corroboration", lambda _a: [])
    without = decide.evaluate(dict(intent))
    assert without.model_evidence == []
    assert (with_intel.final_score, with_intel.tier) == (without.final_score, without.tier)


# ── consensus-v2.2: model evidence needs onward money flow ───────────────
@pytest.mark.parametrize("detail,level", [
    ({"forwarded_fraction": 0.0, "role": None, "rules": []}, "weak"),                 # victim: pays out of own balance
    ({"forwarded_fraction": 0.82, "role": None, "rules": []}, "moderate"),            # receives and moves money on
    ({"forwarded_fraction": 0.0, "role": "collector", "rules": []}, "moderate"),      # RingWatch flow role
    ({"forwarded_fraction": 0.0, "role": None, "rules": ["NET_CIRCULAR"]}, "moderate"),  # part of a closed loop
    ({}, "moderate"),                                                                 # flow not measured: no downgrade
])
def test_model_evidence_needs_onward_flow(detail, level):
    from vigil.intel.consensus import summarise
    rw = DetectorResult(family="ringwatch", label="ringwatch", value=0.1, display="0.10", kind="score", flagged=False,
                        status="ok", version="t", observed_at="2026-01-01T00:00:00.000Z", detail=detail)
    res = [_r("random_forest", True), _r("drift", True), _r("gnn", False), rw]
    c = summarise(res)
    assert c.families_flagging == 2 and c.agreement == level, (detail, c.summary)
    if level == "weak":
        assert "no onward money flow" in c.summary
