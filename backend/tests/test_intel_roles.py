"""Roles (roles-v2.1) and consensus agreement (consensus-v2.1): a change in behaviour is not a mule role.

Regression for the lead's browser walkthrough of the merged platform: after Act 1 (s0), Act 2 (s1, held)
and the false-positive control (s4, ₹1,20,000 rent), the ordinary payer `ramesh@vigil` was flagged by drift +
early warning only (salary in, rent out in the same 72 h) and read as role "distributor" with "moderate"
agreement. Roles and agreement above "weak" now need mule-structure evidence (SYNTHETIC; behavioural checks).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vigil.contracts import AccountIntel, DetectorResult

AGREE = ["none", "weak", "moderate", "strong"]


def _r(family: str, flagged: bool) -> DetectorResult:
    return DetectorResult(family=family, label=family, value=0.5, display="0.50", kind="score", flagged=flagged,
                          version="t", observed_at="2026-01-01T00:00:00.000Z")


# ── pure semantics ────────────────────────────────────────────────────────
@pytest.mark.parametrize("flagging,level", [
    ({"drift", "early_warning"}, "weak"),                              # the Ramesh case: change detectors only
    ({"rules", "early_warning"}, "weak"),                              # the busy-merchant case
    ({"rules", "early_warning", "drift", "trailscore", "context"}, "weak"),
    ({"drift", "early_warning", "random_forest"}, "moderate"),
    ({"drift", "pattern_memory"}, "moderate"),
    ({"drift", "early_warning", "external"}, "moderate"),             # registry listing is mule evidence
    ({"drift", "early_warning", "ringwatch", "rules"}, "strong"),
    ({"random_forest", "gnn", "drift", "early_warning", "ringwatch"}, "strong"),
    ({"gnn"}, "weak"),
    (set(), "none"),
])
def test_agreement_needs_mule_evidence_above_weak(flagging, level):
    from vigil.intel.consensus import agreement, summarise
    fams = ["rules", "random_forest", "gnn", "drift", "early_warning", "pattern_memory", "ringwatch", "external",
            "trailscore", "context"]
    c = summarise([_r(f, f in flagging) for f in fams])
    assert c.agreement == level == agreement(flagging)
    assert (c.families_flagging, c.families_evaluated) == (len(flagging), 10)   # the count itself is unchanged
    if len(flagging) >= 2 and level == "weak":
        assert "no structural or model family agrees" in c.summary


def test_role_gate():
    from vigil.intel.roles import gate
    ok, why = gate({"drift": True, "early_warning": True})
    assert not ok and "no mule-structure evidence" in why and why.startswith("Behaviour changed")
    assert not gate({"rules": True, "early_warning": True, "drift": True})[0]
    assert not gate({"random_forest": True})[0]                          # one family: uncorroborated
    assert not gate({"random_forest": True, "trailscore": True, "context": True})[0]   # journey families ignored
    for evidence in ("random_forest", "gnn", "pattern_memory", "ringwatch", "external"):
        assert gate({evidence: True, "drift": True})[0], evidence
    assert gate({"random_forest": True, "gnn": True})[0]


# ── live acceptance (fresh seed, scenarios as in the walkthrough) ─────────
@pytest.fixture()
def client(world):
    from vigil.app import app

    with TestClient(app) as c:
        yield c


def _intel(client, account_id: str) -> AccountIntel:
    resp = client.get(f"/api/intel/accounts/{account_id}")
    assert resp.status_code == 200, resp.text
    return AccountIntel.model_validate(resp.json())


def _no_role(client, scores: dict, account_id: str) -> AccountIntel:
    intel = _intel(client, account_id)
    assert intel.role.role == "unclassified", (account_id, intel.role)
    assert scores[account_id]["role"] is None, account_id
    assert AGREE.index(intel.consensus.agreement) <= AGREE.index("weak"), (account_id, intel.consensus)
    return intel


def test_ordinary_payer_after_acts_and_control_has_no_role_and_weak_agreement(client):
    from vigil.intel.consensus import CHANGE_FAMILIES, MULE_EVIDENCE_FAMILIES
    from vigil.sim import scenarios, seed
    for sid in ("s0", "s1", "s4"):
        scenarios.run_sync(sid)
    scores = client.get("/api/intel/scores").json()["scores"]
    ramesh = _no_role(client, scores, "ramesh@vigil")
    flagged = {d.family for d in ramesh.detectors if d.status == "ok" and d.flagged}
    # the walkthrough state this test pins: behaviour-change flags only (salary in + rent out in one 72 h window)
    assert flagged and flagged <= CHANGE_FAMILIES | {"rules"}, flagged
    assert not flagged & MULE_EVIDENCE_FAMILIES
    assert "no mule-structure evidence" in ramesh.role.reason
    assert ramesh.role.evidence["mule_evidence_families"] == []

    # Act 2's recipient keeps its structural evidence and its role
    kiran = _intel(client, "kiran.traders@vigil")
    assert kiran.role.role != "unclassified" and scores["kiran.traders@vigil"]["role"] == kiran.role.role
    assert kiran.consensus.agreement == "strong"

    # after the mule ring (s2): victims get no role, the ring keeps roles and strong agreement
    scenarios.run_sync("s2")
    scores = client.get("/api/intel/scores").json()["scores"]
    for v in seed.VICTIMS:
        _no_role(client, scores, v)
    for a in ("kiran.traders@vigil", "zenith.exports@vigil"):
        intel = _intel(client, a)
        assert intel.role.role != "unclassified", (a, intel.role)
        assert scores[a]["role"] == intel.role.role
        assert intel.consensus.agreement == "strong", (a, intel.consensus)
        assert intel.role.evidence["mule_evidence_families"], a
    assert _intel(client, "kiran.traders@vigil").role.role == "collector"
    _no_role(client, scores, "ramesh@vigil")

    # invariant over the whole scored population: a role only with >= 2 flags incl. mule evidence
    from vigil.intel import live
    snap = live.CACHE.current(allow_full=True)
    flags = live.role_flags(snap)
    for a, row in scores.items():
        if row["role"] is not None:
            on = {f for f, v in flags[a].items() if v}
            assert len(on) >= 2 and on & MULE_EVIDENCE_FAMILIES, (a, on)
    overview = client.get("/api/intel/overview").json()
    assert sum(overview["role_counts"].values()) == sum(1 for r in scores.values() if r["role"] is not None)


def test_scenario_compare_victims_are_not_corroborated(client):
    from vigil.sim import scenarios, seed
    scenarios.run_sync("s2")
    body = client.get("/api/intel/scenarios/s2/compare").json()
    rows = {r["account_id"]: r for r in body["accounts"]}
    for v in seed.VICTIMS:
        assert AGREE.index(rows[v]["consensus"]["agreement"]) <= AGREE.index("weak"), rows[v]["consensus"]
    assert rows["kiran.traders@vigil"]["consensus"]["agreement"] == "strong"
