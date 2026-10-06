"""Detection intelligence (Claude 2): windowed features, retrained RF / GAT, rules, early warning,
behavioural drift, pattern memory, roles and detector consensus.

Everything in this package is CORROBORATING MODEL EVIDENCE. Nothing here is fused into the payment
tier (see docs/FINAL_PARALLEL_PLAN.md §5). Pure-python modules (features, rules, drift, pattern memory,
roles) work without numpy; RF/GNN inference needs numpy, SHAP needs scikit-learn + shap. Missing
dependencies degrade a detector to status="unavailable", never to an exception.
"""

INTEL_VERSION = "intel-v2.1"


def warm() -> None:
    """Load model artefacts and build the live feature snapshot once (called by app startup).

    Idempotent, never raises, never imports shap / scikit-learn / torch.
    """
    try:
        from vigil.intel.consensus import warm as _warm

        _warm()
    except Exception:  # pragma: no cover - consensus.warm already swallows; this guards the import
        pass
