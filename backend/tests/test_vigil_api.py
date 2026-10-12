"""API contract tests: shapes, error format, simulated payment rail."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(world):
    from vigil.app import app

    with TestClient(app) as c:
        yield c


def test_health_and_policy(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["ml_on_decision_path"] is False
    p = client.get("/api/policy").json()
    assert round(sum(p["weights"].values()), 6) == 1.0


def test_intent_roundtrip_user_path(client):
    res = client.post("/api/intents", json={"sender_id": "ramesh@vigil", "recipient_id": "meena.grocer@vigil",
                                            "amount_paise": 50000})
    assert res.status_code == 200
    body = res.json()
    assert body["intent"]["state"] == "APPROVED"          # user path waits for an explicit pay call
    assert body["decision"]["tier"] == 0
    paid = client.post(f"/api/intents/{body['intent']['intent_id']}/pay", json={"provider": "mock"}).json()
    assert paid["state"] == "MONITORED"
    assert paid["payment"]["provider"] == "mock"
    inv = client.get(f"/api/investigate/{body['decision']['decision_id']}").json()
    assert {"decision", "intent", "sender", "recipient", "graph", "timeline", "money_trace"} <= set(inv)


@pytest.mark.parametrize("path,payload,status,code", [
    ("/api/intents", {"sender_id": "nobody@vigil", "recipient_id": "meena.grocer@vigil", "amount_paise": 100}, 404, "unknown_account"),
    ("/api/intents", {"sender_id": "ramesh@vigil", "recipient_id": "meena.grocer@vigil", "amount_paise": -5}, 422, "validation_error"),
    ("/api/intents/INT-999999/pay", {}, 404, "unknown_intent"),
    ("/api/labels", {"transaction_id": "TX-999999"}, 404, "unknown_transaction"),
])
def test_error_shape(client, path, payload, status, code):
    res = client.post(path, json=payload)
    assert res.status_code == status
    assert res.json()["error"]["code"] == code
    assert isinstance(res.json()["error"]["message"], str)


def test_graph_endpoints_are_capped(client):
    client.post("/api/scenarios/s2/reset")
    from vigil.sim import scenarios
    scenarios.run_sync("s2")
    g = client.get("/api/graph/suspicious").json()
    assert 0 < len(g["nodes"]) <= 60
    ids = {n["id"] for n in g["nodes"]}
    assert "kiran.traders@vigil" in ids and "zenith.exports@vigil" in ids
    n = client.get("/api/graph/neighborhood/kiran.traders@vigil").json()
    assert n["focus"] == "kiran.traders@vigil"


def test_simulated_payment_rail_is_the_only_provider(client):
    from vigil.payments import providers

    assert isinstance(providers.get_provider(), providers.MockPaymentProvider)
    h = client.get("/api/health").json()
    assert h["payment_provider"] == "mock" and "no real money" in h["payment_provider_label"]
    assert not any("razorpay" in k for k in h)
    assert client.post("/api/intents/INT-x/payment/confirm", json={}).status_code in {404, 405}


def test_contact_page_and_unknown_token(client):
    assert client.get("/api/contact/arjun").json()["contact_name"] == "Arjun Rao"
    res = client.get("/api/contact/nope")
    assert res.status_code == 404 and res.json()["error"]["code"] == "unknown_token"
