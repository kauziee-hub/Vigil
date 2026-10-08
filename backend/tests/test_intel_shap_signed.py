"""SHAP categories: unsigned influence plus signed net effect (what the account page draws as red/blue)."""

from __future__ import annotations

import pytest

pytest.importorskip("vigil.intel")


def test_category_net_is_signed_and_adds_up_to_the_prediction(world):
    from vigil.intel import service
    from vigil.sim import scenarios

    scenarios.run_sync("s2")
    for account in ("kiran.traders@vigil", "sunita@vigil"):
        intel = service.account_intel(account)
        shap = intel.shap
        if shap is None:
            pytest.skip("Random Forest / SHAP not available in this environment")
        assert set(shap.category_net) == set(shap.categories)
        for cat, net in shap.category_net.items():
            assert abs(net) <= shap.categories[cat] + 1e-6          # |sum| <= sum of |.|
        # SHAP additivity: base + Σ contributions = model output (rounding tolerance)
        assert abs(shap.base_value + sum(shap.category_net.values()) - shap.prediction) < 0.02, account
    # a quiet pensioner's model score sits below the base value, so the net effect is negative overall
    quiet = service.account_intel("sunita@vigil").shap
    assert quiet is not None and quiet.prediction < quiet.base_value and sum(quiet.category_net.values()) < 0
