"""overview-v10 P1: simulated locations, rails and the onboarding cohort."""

from __future__ import annotations

import pytest


def test_geo_stamp_is_deterministic_and_never_raises():
    from vigil import geo
    row = {"id": "TX-000123", "sender_id": "ramesh@vigil", "recipient_id": "meena.grocer@vigil", "channel": "upi",
           "device_id": "dev-ramesh-pixel7", "ts": "2026-10-12T10:00:00.000Z"}
    assert geo.stamp(row) == geo.stamp(dict(row))
    assert geo.stamp(row)["geo_basis"] == "device_gps" and geo.stamp(row)["geo_city"] == "Bengaluru"
    for bad in ({}, {"sender_id": None}, {"sender_id": "x", "recipient_id": None}, {"sender_id": "ghost@vigil",
                                                                                     "recipient_id": "ext:atm"}):
        out = geo.stamp(bad)                     # must not raise
        assert set(out) >= {"geo_city", "geo_basis", "geo_accuracy_m"}


@pytest.mark.parametrize("row, basis, acc", [
    ({"sender_id": "ramesh@vigil", "recipient_id": "ext:atm", "channel": "upi", "ts": "2026-10-12T10:00:00Z"}, "atm_terminal", 25),
    ({"sender_id": "ramesh@vigil", "recipient_id": "meena.grocer@vigil", "channel": "card"}, "merchant_pos", 2000),
    ({"sender_id": "ext:employer", "recipient_id": "ramesh@vigil", "channel": "upi"}, "kyc_home", 5000),
    ({"sender_id": "ramesh@vigil", "recipient_id": "meena.grocer@vigil", "channel": "upi", "device_id": "d"}, "device_gps", 30),
])
def test_basis_and_accuracy_rules(row, basis, acc):
    from vigil import geo
    g = geo.stamp({"id": "TX-1", **row})
    assert g["geo_basis"] == basis and g["geo_accuracy_m"] == acc
    assert geo.label(basis, acc).startswith("Simulated location · ")


def test_ip_basis_accuracy_band_and_intl_peer():
    from vigil import geo
    g = geo.stamp({"id": "TX-9", "sender_id": "ramesh@vigil", "recipient_id": "ext:intl-wire", "channel": "intl_wire"})
    assert g["geo_basis"] == "ip" and 3000 <= g["geo_accuracy_m"] <= 15000
    assert g["peer_geo_city"] in {c["city"] for c in geo.FOREIGN}


def test_home_cities_cover_every_city_and_atms_stay_near_centre():
    from vigil import geo
    ids = [f"user{i}@vigil" for i in range(800)]
    homes = {geo.home_for(i) for i in ids}
    assert homes == {c["city"] for c in geo.DOMESTIC}
    for t in geo.atm_terminals():
        c = geo.city(t["city"])
        assert geo.haversine_km((c["lat"], c["lng"]), (t["lat"], t["lng"])) <= geo.ATM_RADIUS_KM + 0.01


def test_rail_display_mapping_keeps_stored_channel():
    from vigil import geo
    assert geo.rail("upi", "ext:atm") == "atm" and geo.rail("upi", "ext:intl-wire") == "intl_wire"
    assert geo.rail("imps", "ext:atm") == "imps" and geo.rail(None, "meena.grocer@vigil") == "upi"


def test_ambient_rail_is_hash_derived_and_at_most_two_rails():
    from vigil.sim import ambient
    rails = {ambient.rail_for(f"p{i}@vigil") for i in range(300)}
    assert rails == {"upi", "card"}
    assert ambient.rail_for("p1@vigil") == ambient.rail_for("p1@vigil")


def test_intent_channel_is_validated_and_posted(world):
    from pydantic import ValidationError
    from vigil.contracts import CreateIntentRequest
    from vigil.engine import lifecycle
    with pytest.raises(ValidationError):
        CreateIntentRequest(sender_id="ramesh@vigil", recipient_id="meena.grocer@vigil", amount_paise=100_00, channel="swift")
    intent, decision = lifecycle.create(CreateIntentRequest(sender_id="ramesh@vigil", recipient_id="meena.grocer@vigil",
                                                            amount_paise=450_00, channel="imps"))
    if not world.q1("SELECT 1 FROM transactions WHERE intent_id = ?", (intent.intent_id,)):
        lifecycle.pay(intent.intent_id)
    tx = world.q1("SELECT channel, geo_basis FROM transactions WHERE intent_id = ?", (intent.intent_id,))
    assert decision.tier == 0 and tx["channel"] == "imps" and tx["geo_basis"] == "device_gps"


def test_cohort_is_deterministic_tagged_and_collision_free(world):
    from vigil.sim import cohort_v10
    ids = cohort_v10.account_ids()
    assert len(ids) == len(set(ids)) == cohort_v10.N_ACCOUNTS + 1
    rows = world.q("SELECT id FROM accounts WHERE id IN ({})".format(",".join("?" * len(ids))), tuple(ids))
    assert len(rows) == len(ids)
    n = world.scalar("SELECT COUNT(*) FROM transactions WHERE source = 'cohort_v10'")
    assert n > 150
    # every cohort posting comes after the main seed's postings (no id shifted)
    first_cohort = world.scalar("SELECT MIN(seq) FROM transactions WHERE source = 'cohort_v10'")
    last_seed = world.scalar("SELECT MAX(seq) FROM transactions WHERE source = 'seed'")
    assert first_cohort > last_seed
    assert world.scalar("SELECT COUNT(*) FROM accounts WHERE kind = 'customer' AND home_city IS NULL") == 0
    assert set(cohort_v10.account_ids()) == set(ids)                   # pure, repeatable


def test_cohort_accounts_are_not_flagged(world):
    from vigil.engine import livestatus
    from vigil.sim import cohort_v10
    sts = livestatus.statuses(cohort_v10.account_ids())
    assert not [a for a, s in sts.items() if s["status"] in ("flagged", "early_warning", "held", "confirmed_fraud")]
