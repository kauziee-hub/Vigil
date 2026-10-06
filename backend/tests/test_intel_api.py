"""/api/intel/* — shapes validate against vigil/contracts.py and match frontend/src/api/types.ts."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vigil.contracts import AccountIntel, DetectorConsensus, DetectorResult, ModelInfo, PatternMatch

TYPES_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "types.ts"
MULE_ROLES = {"coordinator", "collector", "distributor", "entry", "exit", "unclassified"}


@pytest.fixture()
def client(world):
    from vigil.app import app

    with TestClient(app) as c:
        yield c


def _ts_fields(interface: str) -> set[str] | None:
    """Top-level field names of a TS interface in types.ts (None if the frontend tree is absent)."""
    if not TYPES_TS.exists():
        return None
    text = TYPES_TS.read_text(encoding="utf-8")
    m = re.search(r"export interface " + interface + r"\s*\{", text)
    assert m, interface
    i, depth, body = m.end(), 1, []
    while depth:
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif depth == 1:
            body.append(ch)                      # keep only the interface's own level
        i += 1
    lines = [re.sub(r"//.*", "", ln) for ln in "".join(body).splitlines()]
    pieces = [p.strip() for ln in lines for p in ln.split(";")]
    return {mm.group(1) for p in pieces if (mm := re.match(r"(\w+)\??\s*:", p))}


def test_router_mounted_and_intel_available(client):
    from vigil import app as app_module
    assert app_module.INTEL_AVAILABLE is True
    assert client.get("/api/system/health").json()["intel_available"] is True


def test_account_intel_validates_against_contract(client):
    from vigil.sim import scenarios
    scenarios.run_sync("s2")
    body = client.get("/api/intel/accounts/kiran.traders@vigil").json()
    intel = AccountIntel.model_validate(body)
    assert set(body) == set(AccountIntel.model_fields)
    ts = _ts_fields("AccountIntel")
    assert ts is None or ts == set(body)
    fams = [d.family for d in intel.detectors]
    assert fams[:8] == ["random_forest", "gnn", "rules", "early_warning", "drift", "pattern_memory", "ringwatch",
                        "external"]
    assert intel.consensus.families_flagging >= 3 and intel.consensus.agreement in {"moderate", "strong"}
    assert intel.role.role in MULE_ROLES and intel.role.role != "unclassified"
    assert intel.drift is not None and intel.drift.level == "HIGH" and intel.drift.features
    assert intel.patterns and all(0.0 <= p.similarity <= 1.0 for p in intel.patterns)
    assert "not criminal attribution" in intel.patterns[0].note
    assert set(intel.features) >= {"in_degree", "retention_ratio", "device_cluster_size", "account_age_days"}
    if intel.shap is not None:                         # shap installed (it is in requirements-ml.txt)
        s = intel.shap
        assert s.prediction_kind == "probability_uncalibrated"
        total = s.base_value + sum(c.contribution for c in s.top_positive + s.top_negative)
        assert s.top_positive and all(c.contribution > 0 for c in s.top_positive)
        assert all(c.contribution < 0 for c in s.top_negative)
        assert total <= 1.0 + 1e-6 and s.categories
        assert {c.category for c in s.top_positive} <= set(s.categories)
    for d in body["detectors"]:
        DetectorResult.model_validate(d)
        ts = _ts_fields("DetectorResult")
        assert ts is None or ts == set(d)


def test_account_intel_unknown_external_and_quiet(client):
    r = client.get("/api/intel/accounts/nobody@vigil")
    assert r.status_code == 404 and r.json()["error"]["code"] == "unknown_account"
    ext = AccountIntel.model_validate(client.get("/api/intel/accounts/ext:atm").json())
    assert ext.consensus.families_flagging == 0 and ext.consensus.agreement == "none"
    assert ext.consensus.families_evaluated <= 1                     # at most the registry lookup
    assert all(d.status == "not_applicable" for d in ext.detectors if d.family != "external")
    assert ext.shap is None and ext.drift is None and ext.features == {}
    quiet = AccountIntel.model_validate(client.get("/api/intel/accounts/sunita@vigil").json())
    assert quiet.consensus.families_flagging == 0 and quiet.role.role == "unclassified"


def test_scores_shape_and_cache_per_graph_version(client):
    from vigil.engine import ledger
    from vigil.graph.pathgraph import GRAPH
    a = client.get("/api/intel/scores").json()
    ts = _ts_fields("IntelScores")
    assert ts is None or ts == set(a)
    assert set(a) == {"graph_version", "scores"} and a["graph_version"] == GRAPH.version
    row_keys = {"rules", "rf", "gnn", "drift_level", "role", "early_warning"}
    assert "kiran.traders@vigil" in a["scores"] and "ramesh@vigil" in a["scores"]
    assert not any(k.startswith("ext:") for k in a["scores"])
    for row in a["scores"].values():
        assert set(row) == row_keys
        assert row["drift_level"] in {"LOW", "MEDIUM", "HIGH"} and isinstance(row["early_warning"], bool)
        assert row["role"] is None or row["role"] in MULE_ROLES
        for k in ("rules", "rf", "gnn"):
            assert row[k] is None or 0.0 <= row[k] <= 1.0
    from vigil.intel import live
    snap = live.CACHE.snap
    assert client.get("/api/intel/scores").json() == a and live.CACHE.snap is snap      # same version: cached
    ledger.post(sender_id="ramesh@vigil", recipient_id="meena.grocer@vigil", amount_paise=250_00, source="user")
    b = client.get("/api/intel/scores").json()
    assert b["graph_version"] == GRAPH.version > a["graph_version"]


def test_models_are_synthetic_and_honest(client):
    body = client.get("/api/intel/models").json()
    models = [ModelInfo.model_validate(m) for m in body]
    ts = _ts_fields("ModelInfo")
    assert ts is None or all(ts == set(m) for m in body)
    by_id = {m.model_id: m for m in models}
    assert {"rf-v2", "gnn-gat-v2", "rules-v2", "drift-v2", "pattern-memory-v2"} <= set(by_id)
    for m in models:
        assert m.data == "SYNTHETIC" and "SYNTHETIC VALIDATION" in m.metrics["label"]
        assert "not used for payment authorisation" in m.operational_use
        assert m.status == "active" and m.trained_at and m.seed == 20261006
        assert "split-by-world" in m.split
    for mid in ("rf-v2", "gnn-gat-v2"):
        m = by_id[mid]
        assert 0.0 <= m.metrics["precision"] <= 1.0 and m.metrics["pr_auc"] is not None
        assert m.per_attack and "brier" in m.calibration["calibrated"]
        assert "synthetic" in m.calibration["method"]
    gov = client.get("/api/governance/summary").json()
    assert {m["model_id"] for m in gov["models"]} == set(by_id)


def test_overview_shape(client):
    from vigil.sim import scenarios
    scenarios.run_sync("s2")
    body = client.get("/api/intel/overview").json()
    ts = _ts_fields("IntelOverview")
    assert ts is None or ts == set(body)
    assert set(body["detector_agreement"]) >= {"rules", "random_forest", "gnn", "drift", "early_warning",
                                               "pattern_memory", "ringwatch", "external"}
    assert all(isinstance(v, int) and v >= 0 for v in body["detector_agreement"].values())
    assert any(e["account_id"] == "kiran.traders@vigil" for e in body["early_warnings"])
    for e in body["early_warnings"]:
        assert set(e) == {"account_id", "score", "signals"} and len(e["signals"]) >= 2
    for p in body["pattern_alerts"]:
        assert set(p) == {"account_id", "match"}
        PatternMatch.model_validate(p["match"])
    assert set(body["role_counts"]) == MULE_ROLES and sum(body["role_counts"].values()) >= 3
    assert [ModelInfo.model_validate(m) for m in body["models"]]


def test_scenario_compare_shape_and_involvement(client):
    from vigil.sim import scenarios
    scenarios.run_sync("s2")
    body = client.get("/api/intel/scenarios/s2/compare").json()
    ts = _ts_fields("ScenarioCompare")
    assert ts is None or ts == set(body)
    assert body["scenario_id"] == "s2"
    assert [a["account_id"] for a in body["accounts"]] == scenarios.touched_accounts("s2")
    rows = {a["account_id"]: a for a in body["accounts"]}
    for a in body["accounts"]:
        assert set(a) == {"account_id", "seed_role", "detectors", "consensus"}
        DetectorConsensus.model_validate(a["consensus"])
        for d in a["detectors"]:
            DetectorResult.model_validate(d)
    assert rows["kiran.traders@vigil"]["seed_role"].startswith("mule_collector")
    assert "sent scenario funds" in rows["anita.s@vigil"]["seed_role"]      # a victim: involved, not a mule
    assert rows["kiran.traders@vigil"]["consensus"]["families_flagging"] >= 3
    assert client.get("/api/intel/scenarios/nope/compare").status_code == 404
    # attack scenario not yet run: its new accounts do not exist -> empty detectors, never an error
    fresh = client.get("/api/intel/scenarios/atk_fan_in/compare").json()
    hub = next(a for a in fresh["accounts"] if a["account_id"] == "swift.collect@vigil")
    assert hub["detectors"] == [] and hub["consensus"]["families_evaluated"] == 0
