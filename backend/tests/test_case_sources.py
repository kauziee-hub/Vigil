"""v12.5 Cases clarity: why a row is in the Cases queue comes only from stored data (the decision record, the
intent's origin, RingWatch rows, the live detector status); every existing field stays as it was."""

from __future__ import annotations

from vigil import db
from vigil.engine import lifecycle
from vigil.risk import taint
from vigil.sim import scenarios

OLD_INTERVENTION_KEYS = {"intent_id", "decision_id", "sender_id", "recipient_id", "amount_paise", "tier", "kind", "state",
                         "headline", "opened_at", "age_s", "sla_due", "hold", "circuit_breaker", "mode"}


def run(sid):
    return [r for r in scenarios.run_sync(sid) if isinstance(r, dict) and r.get("decision_id")]


def _confirm_kiran_inflow():
    tx = db.q1("SELECT id FROM transactions WHERE sender_id='anita.s@vigil' AND recipient_id='kiran.traders@vigil'")
    with db.tx():
        db.insert("fraud_labels", {"id": "LBL-T1", "transaction_id": tx["id"], "grade": "bank_confirmed",
                                   "label": "scam", "labelled_by": "test", "ts": "2026-10-06T00:00:00.000Z"})
    taint.run(force=True)


def test_payment_case_sources_come_from_the_decision_record(world):
    from vigil.api import views
    [before] = run("s1")                      # EXT_REPORTED, NET_PASS_THROUGH, BEH_FIRST_TIME_PAYEE
    d = lifecycle.get_decision(before["decision_id"])
    cs = views.case_sources(d)
    assert "ringwatch" in cs["sources"] and "registry" in cs["sources"] and "tainttrace" not in cs["sources"]
    assert set(cs["flagged_by"]) <= set(views.MULE_FAMILIES)
    assert ("mule_detection" in cs["sources"]) == bool(cs["flagged_by"])
    # after a confirmed report the same payment carries NET_TAINT_EXPOSURE: TaintTrace joins the sources
    lifecycle.cancel(before["intent_id"])
    run("s2")
    _confirm_kiran_inflow()
    [after] = run("s1")
    d2 = lifecycle.get_decision(after["decision_id"])
    assert "NET_TAINT_EXPOSURE" in d2.rules_fired and "tainttrace" in views.case_sources(d2)["sources"]
    # a calm payment names no engine at all
    [calm] = run("s0")
    assert views.case_sources(lifecycle.get_decision(calm["decision_id"])) == {"sources": [], "flagged_by": []}


def test_cases_endpoints_add_origin_and_sources_without_changing_existing_fields(world):
    from fastapi.testclient import TestClient

    from vigil.app import app
    from vigil.copilot import incidents
    from vigil.risk import ringwatch
    with TestClient(app) as c:
        c.portal.call(incidents.stop)         # scenarios run on this thread; keep the background pass out of the way
        run("s1")
        run("s3")
        rows = c.get("/api/interventions?status=all&min_tier=2").json()
        assert rows and all(OLD_INTERVENTION_KEYS <= set(r) for r in rows)
        assert all(r["origin"] == "scenario" for r in rows)
        assert any("registry" in r["sources"] for r in rows)
        known = {"ringwatch", "tainttrace", "registry", "mule_detection"}
        assert all(set(r["sources"]) <= known and isinstance(r["flagged_by"], list) for r in rows)
        feed = c.get("/api/decisions?min_tier=1").json()
        assert feed and all(f["source"] == "scenario" and "sources" in f and f["labels"] for f in feed)
        ring = c.get("/api/ringwatch").json()
        assert ring and all(isinstance(r["families"], list) and isinstance(r["location_rules"], list) for r in ring)
        assert all("families" not in r for r in ringwatch.scan(0.3))       # the scan cache itself is untouched
