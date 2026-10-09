"""Live behaviour of the detection intelligence on the seeded demo world (SYNTHETIC; behavioural checks)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

INTEL = Path(__file__).resolve().parents[1] / "vigil" / "intel"
INTEL_FAMILIES = ("rules", "random_forest", "gnn", "drift", "early_warning", "pattern_memory")


def _n(snap, a):
    return sum(snap.flags[a].values())


def _n8(snap, a):
    """Families agreeing in the platform's account consensus: the six intel families + RingWatch + registry."""
    from vigil.intel import consensus, live
    fl = live.role_flags(snap).get(a) or {}
    return sum(1 for f in consensus.ACCOUNT_FAMILIES if fl.get(f))


def _ordinary(db, exclude=()):
    rows = db.q("SELECT id FROM accounts WHERE kind = 'customer' AND seed_role = 'legit' AND is_demo_customer = 0")
    return [r["id"] for r in rows if r["id"] not in set(exclude)]


def test_seeded_world_is_quiet_except_the_act2_recipient(world):
    """Before any scenario: only the seeded pass-through pair is corroborated; ordinary accounts are quiet."""
    from vigil.intel import live
    snap = live.build()
    assert snap.status == {"random_forest": "ok", "gnn": "ok"}
    assert _n(snap, "kiran.traders@vigil") >= 3          # by design: already forwarding money fast (Act 2)
    ordinary = _ordinary(world)
    assert len(ordinary) > 100
    assert not [a for a in ordinary if _n(snap, a) >= 2]
    assert sum(1 for a in ordinary if _n(snap, a) >= 1) <= 0.05 * len(ordinary)


def test_s2_mule_ring_flagged_by_three_or_more_families(world):
    from vigil.intel import live
    from vigil.sim import scenarios, seed
    scenarios.run_sync("s2")
    snap = live.build()
    for a in ("kiran.traders@vigil", "zenith.exports@vigil"):
        assert _n(snap, a) >= 3, (a, snap.flags[a])
        assert live.role(snap, a)["role"] != "unclassified"
    assert live.role(snap, "kiran.traders@vigil")["role"] == "collector"
    ordinary = _ordinary(world, exclude=scenarios.touched_accounts("s2"))
    assert not [a for a in ordinary if _n(snap, a) >= 2]
    assert sum(1 for a in ordinary if _n(snap, a) >= 1) <= 0.05 * len(ordinary)
    # victims paid INTO the ring: they are never corroborated as mules (world v3: the RF may still raw-flag a
    # victim's large first-time outflow; consensus-v2.2 keeps it uncorroborated, role-less and never "flagged")
    from vigil.intel import service, stream
    sm = stream.status_map()
    for v in seed.VICTIMS:
        intel = service.account_intel(v)
        assert intel.consensus.agreement in ("none", "weak"), (v, intel.consensus.summary)
        assert intel.role.role == "unclassified", (v, intel.role.reason)
        assert (sm.get(v) or {}).get("status") != "flagged", v


@pytest.mark.parametrize("sid", ["atk_fan_in", "atk_fan_out", "atk_circular", "atk_velocity_chain",
                                 "atk_cross_channel", "atk_shared_device", "atk_behavioural_drift",
                                 "atk_volume_spike", "atk_smurfing", "atk_dormant"])
def test_each_attack_pattern_is_corroborated_without_spill_over(world, sid):
    from vigil.intel import live
    from vigil.sim import scenarios, seed
    scenarios.run_sync(sid)
    snap = live.build()
    touched = scenarios.touched_accounts(sid)
    # corroboration as the platform reports it (8 account families incl. RingWatch); spill-over check unchanged
    assert max(_n8(snap, a) for a in touched if a in snap.flags) >= 3
    cast = {"kiran.traders@vigil", "zenith.exports@vigil", *seed.DOWNSTREAM}
    spill = [a for a in snap.ids if a not in touched and a not in cast and _n(snap, a) >= 2]
    assert spill == []


def test_incremental_refresh_matches_full_rebuild(world):
    from vigil.intel import live
    from vigil.sim import scenarios
    before = live.build()
    scenarios.run_sync("s2")
    inc = live.refresh(before)
    full = live.build(now_t=inc.now_t)
    assert inc.mode == "incremental" and full.mode == "full"
    assert {a: inc.flags[a] for a in inc.ids} == {a: full.flags[a] for a in full.ids}
    for a in ("kiran.traders@vigil", "zenith.exports@vigil", "pooja.m@vigil"):
        assert inc.feats[a] == full.feats[a]
        assert abs(inc.rf[a][0] - full.rf[a][0]) < 1e-12
        assert abs(inc.gnn[a][0] - full.gnn[a][0]) < 1e-9


def test_deterministic_for_identical_worlds(monkeypatch):
    """Same seed + same (frozen) clock -> identical features, scores and flags after a reset."""
    from vigil import clock, db
    from vigil.intel import live
    from vigil.sim import scenarios, seed
    frozen = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, "now", lambda: frozen)
    db.connect()
    out = []
    for _ in range(2):
        seed.seed()
        scenarios.run_sync("atk_circular")
        snap = live.build()
        out.append((snap.feats, snap.rf, snap.gnn, {a: snap.drift[a]["drift_score"] for a in snap.ids}, snap.flags,
                    {a: snap.patterns[a] for a in snap.ids}))
    for x, y in zip(out[0], out[1]):
        assert x == y
    assert snap.now_t == (frozen + timedelta(0)).timestamp()


def test_numpy_ports_equal_the_trained_models():
    """Serving (numpy) == training (sklearn / torch) on the reference rows stored with the artefacts."""
    np = pytest.importorskip("numpy")
    from ml.datagen import EXTERNALS
    from vigil.intel.models import MODELS_DIR, build_edge_index, forest_predict, gat_forward
    with np.load(MODELS_DIR / "rf_v2.npz") as z:
        arr = {k: z[k] for k in z.files}
    assert np.abs(forest_predict(arr, arr["check_X"]) - arr["check_p"]).max() < 1e-9
    with np.load(MODELS_DIR / "gnn_v2.npz") as z:
        W = {k: z[k] for k in z.files}
    pairs = [tuple(p) for p in W["check_pairs"].tolist()]
    e_in, e_out = build_edge_index(len(W["check_x"]), pairs)
    out = gat_forward(W, W["check_x"], e_in, e_out)
    n_ext = len(EXTERNALS)                      # external indicator nodes come first and are not scored
    assert np.abs(out[n_ext:] - W["check_out"][n_ext:]).max() < 1e-4


def _code_tokens(node) -> list[str]:
    """String constants (minus docstrings) and identifiers used by the code under `node`."""
    import ast
    docs = set()
    for n in ast.walk(node):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            out.append(n.value)
        elif isinstance(n, ast.Name):
            out.append(n.id)
        elif isinstance(n, ast.Attribute):
            out.append(n.attr)
    return out


def test_no_runtime_component_reads_ground_truth():
    """seed_role / seed_attack / fraud labels are read ONLY by the scenario-compare read model
    (vigil/intel/service.py::_involvement / scenario_compare), never by a detector.

    v3 live stream (stream.py), each exception limited to one function and one token:
      * `_vigil_state` reads bank-confirmed `fraud_labels` -> the plan's `confirmed_fraud` STATUS (Vigil state,
        precedence above every detector status; never a detector input);
      * `on_posting` passes the posting's `seed_attack` tag through as `TxScored.scenario` (display only).
    """
    import ast
    bad_tokens = ("seed_role", "seed_attack", "fraud_labels", "is_fraud")
    allowed = {"service.py": {"_involvement": bad_tokens, "scenario_compare": bad_tokens},
               "stream.py": {"_vigil_state": ("fraud_labels",), "on_posting": ("seed_attack",)}}
    for path in INTEL.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nodes: list[tuple[ast.AST, tuple[str, ...]]] = [(tree, ())]
        if path.name in allowed:
            body = tree.body[1:] if ast.get_docstring(tree) is not None else tree.body
            nodes = [(n, allowed[path.name].get(getattr(n, "name", ""), ())) for n in body]
        for node, ok in nodes:
            for tok in _code_tokens(node):
                for bad in bad_tokens:
                    assert bad not in tok or bad in ok, (path.name, getattr(node, "name", ""), tok)


def test_feature_function_is_shared_by_training_and_live(world):
    """The training generator and the live adapter feed the SAME extractor (no train/serve skew)."""
    from ml import datagen
    from vigil.intel import features as F
    from vigil.intel import live
    w = datagen.make_world(0)
    a = w.scored_accounts()[0]
    assert set(F.extract(w, a, w.now_t)) == set(F.FEATURES)
    snap = live.build()
    assert set(snap.feats["ramesh@vigil"]) == set(F.FEATURES)
    assert F.extract(live.SRC, "ramesh@vigil", snap.now_t) == snap.feats["ramesh@vigil"]
