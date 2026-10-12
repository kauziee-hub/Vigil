"""Detection-intelligence REST API (docs/archive/plans/FINAL_PARALLEL_PLAN.md §4.2). Included optionally by vigil/app.py.

    GET /api/intel/accounts/{account_id}              -> AccountIntel
    GET /api/intel/scores                             -> IntelScores   (cached per graph version)
    GET /api/intel/models                             -> ModelInfo[]
    GET /api/intel/overview                           -> IntelOverview
    GET /api/intel/scenarios/{scenario_id}/compare    -> ScenarioCompare

All handlers are `async def` (single-threaded DB access is a project invariant). Importing this module
needs only the platform's own dependencies; numpy / scikit-learn / shap are optional and degrade a
model to status "unavailable". Every metric is SYNTHETIC VALIDATION; every output is corroborating
evidence only and never changes a payment decision.
"""

from __future__ import annotations

from fastapi import APIRouter

from vigil.engine.ledger import VigilError
from vigil.intel import live, service
from vigil.intel import stream  # noqa: F401  (registers the live-posting hook listener at import)
from vigil.intel.registry import models as _models

router = APIRouter(prefix="/api/intel", tags=["intel"])


@router.get("/stream")
async def intel_stream():
    """Live detection stream diagnostics: latency, status counts, live model-evidence threshold + history."""
    return {**stream.stats(), "threshold_history": stream.threshold_history()}


@router.get("/accounts/{account_id}")
async def account_intel(account_id: str):
    if not live.known(account_id):
        raise VigilError(404, "unknown_account", f"No account '{account_id}'.")
    return service.account_intel(account_id).model_dump(mode="json")


@router.get("/scores")
async def intel_scores():
    return service.scores()


@router.get("/models")
async def intel_models():
    return [m.model_dump(mode="json") for m in _models()]


@router.get("/overview")
async def intel_overview():
    return service.overview()


@router.get("/scenarios/{scenario_id}/compare")
async def scenario_compare(scenario_id: str):
    return service.scenario_compare(scenario_id)
