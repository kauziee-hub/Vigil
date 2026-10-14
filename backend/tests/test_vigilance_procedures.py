"""v11 Vigilance: every alert is classified (label, typology, respond-within) and carries a bank procedure whose steps
complete automatically from Vigil's own data or by the analyst's tick. Nothing here changes the bank's state."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(world, monkeypatch):
    from vigil import overview
    from vigil.api import routes_copilot
    from vigil.app import app
    from vigil.copilot import gemini, incidents
    overview.invalidate()
    routes_copilot._RATE.clear()
    gemini.set_client(None)
    with TestClient(app) as c:
        # these tests drive incidents.evaluate() themselves from this thread; the app's background pass runs on
        # the client's loop thread over the same SQLite connection, so pause it to keep the two from interleaving
        c.portal.call(incidents.stop)
        yield c


def test_every_incident_kind_has_a_classified_procedure_with_all_four_phases_covered():
    from vigil.copilot import incidents, playbooks
    for kind in incidents.KIND_LABEL:
        assert kind in playbooks.CLASS and kind in playbooks.PLAYBOOKS, kind
        steps = playbooks.PLAYBOOKS[kind]
        ids = [s["id"] for s in steps]
        assert len(ids) == len(set(ids)), f"duplicate step ids in {kind}"
        assert steps[-1]["id"] == "close"
        for s in steps:
            assert s["phase"] in {p for p, _l, _g in playbooks.PHASES}
            assert s["owner"] and s["when"] and s["title"]
            assert bool(s.get("ui") or s.get("auto")) != bool(s.get("outside")) or s["id"] == "close", (kind, s["id"])
    assert set(playbooks.RESPOND) == {"critical", "high", "medium", "low"}


def test_ring_incident_is_classified_and_its_procedure_auto_completes(client, world):
    from vigil.copilot import incidents
    from vigil.sim import scenarios
    scenarios.run_sync("s2")
    incidents.evaluate()
    rows = client.get("/api/copilot/incidents").json()["incidents"]
    ring = next((i for i in rows if i["kind"] == "ring_formed"), None) or next(i for i in rows if i["kind"] == "account_flagged")
    assert ring["classification"] and ring["typology"] and ring["respond_within"]
    assert ring["procedure"]["total"] >= 5 and ring["procedure"]["done"] == 0
    proc = client.get(f"/api/copilot/incidents/{ring['id']}/procedure").json()
    assert [p["id"] for p in proc["phases"]] == ["contain", "investigate", "report", "close"]
    assert any(s["kind"] == "outside" for s in proc["steps"]) and any(s["ui_action"] for s in proc["steps"])
    watch = next((s for s in proc["steps"] if s["auto_rule"] == "watched"), None)
    if watch:                                     # watching one member completes the step automatically
        client.post("/api/watchlist", json={"account_id": ring["entities"][0]})
        proc = client.get(f"/api/copilot/incidents/{ring['id']}/procedure").json()
        w = next(s for s in proc["steps"] if s["id"] == watch["id"])
        assert w["done"] and w["done_by"] == "vigil" and w["evidence"]
    # a manual tick is recorded and reversible; unknown steps are refused
    outside = next(s for s in proc["steps"] if s["kind"] == "outside")
    r = client.post(f"/api/copilot/incidents/{ring['id']}/procedure/{outside['id']}", json={"done": True}).json()
    assert next(s for s in r["steps"] if s["id"] == outside["id"])["done"]
    r = client.post(f"/api/copilot/incidents/{ring['id']}/procedure/{outside['id']}", json={"done": False}).json()
    assert not next(s for s in r["steps"] if s["id"] == outside["id"])["done"]
    assert client.post(f"/api/copilot/incidents/{ring['id']}/procedure/nope", json={"done": True}).status_code == 404


def test_held_payment_procedure_completes_when_the_bank_decides(client, world):
    from vigil.copilot import incidents
    from vigil.sim import scenarios
    scenarios.run_sync("s3")                     # coerced payment: Tier 4, held + trusted contact
    incidents.evaluate()
    rows = client.get("/api/copilot/incidents").json()["incidents"]
    t4 = next(i for i in rows if i["kind"] == "tier4_coercion")
    assert t4["classification"] == "Customer under coercion" and t4["severity"] in ("critical", "high")
    proc = client.get(f"/api/copilot/incidents/{t4['id']}/procedure").json()
    hold = next(s for s in proc["steps"] if s["auto_rule"] == "hold_decided")
    assert not hold["done"]
    case = next(s for s in proc["steps"] if s["id"] == "contact")
    assert case["ui_action"]["type"] == "open_page" and case["ui_action"]["target"].startswith("/investigations/decision/")
    rcp = next((s for s in proc["steps"] if (s["ui_action"] or {}).get("target", "").startswith("/investigations/account/")), None)
    assert rcp and "sunita" not in rcp["ui_action"]["target"]   # "check the recipient" opens the PAYEE, not the customer
    intent = client.get("/api/interventions?status=open").json()
    iid = next(r["intent_id"] for r in intent if r["tier"] >= 4)
    client.post(f"/api/intents/{iid}/bank-action", json={"action": "reject"})
    proc = client.get(f"/api/copilot/incidents/{t4['id']}/procedure").json()
    assert next(s for s in proc["steps"] if s["id"] == hold["id"])["done"]


def test_reset_clears_procedure_ticks(client, world):
    from vigil import db
    from vigil.copilot import incidents
    from vigil.sim import scenarios
    scenarios.run_sync("s2")
    incidents.evaluate()
    inc = client.get("/api/copilot/incidents").json()["incidents"][0]
    step = client.get(f"/api/copilot/incidents/{inc['id']}/procedure").json()["steps"][0]
    client.post(f"/api/copilot/incidents/{inc['id']}/procedure/{step['id']}", json={"done": True})
    assert db.scalar("SELECT COUNT(*) FROM copilot_playbook_steps") == 1
    client.post("/api/demo/reset")
    assert db.scalar("SELECT COUNT(*) FROM copilot_playbook_steps") == 0


def test_offline_chat_answers_next_steps_from_the_procedure(client, world):
    from vigil.copilot import incidents
    from vigil.sim import scenarios
    scenarios.run_sync("s3")
    incidents.evaluate()
    inc = next(i for i in client.get("/api/copilot/incidents").json()["incidents"] if i["kind"] == "tier4_coercion")
    tid = client.post("/api/copilot/threads", json={"incident_id": inc["id"]}).json()["id"]
    body = client.post(f"/api/copilot/threads/{tid}/messages", json={"content": "What should I do first?"}).text
    assert "Customer under coercion" in body and "respond within" in body and "outside Vigil" in body


def test_new_key_format_is_redacted():
    from vigil.copilot.chat import scrub
    assert "AQ.Ab" not in scrub("the key is AQ.Ab12345678901234567890xyz and more")
