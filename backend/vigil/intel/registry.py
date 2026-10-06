"""Model registry: ModelInfo for every intel model, read from the versioned metadata in backend/models/.

Used by GET /api/intel/models, the overview, and (optionally) the lead's governance summary
(`vigil.api.routes_v2` imports `vigil.intel.registry.models`). Every metric is SYNTHETIC VALIDATION.
"""

from __future__ import annotations

import json
from typing import Any

from vigil.contracts import ModelInfo
from vigil.intel.models import MODELS_DIR, STORE

LABEL = "SYNTHETIC VALIDATION — computer-generated worlds; not real-bank accuracy."
_METRIC_KEYS = ("precision", "recall", "f1", "roc_auc", "pr_auc", "pr_auc_active_accounts", "confusion", "n",
                "positives", "prevalence", "flag_rate", "false_positives_by_persona")
_cache: list[ModelInfo] | None = None


def _load(name: str) -> dict[str, Any] | None:
    try:
        return json.loads((MODELS_DIR / name).read_text(encoding="utf-8"))
    except Exception:
        return None


def _metrics(m: dict[str, Any] | None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"label": LABEL, "evaluated_on": "held-out TEST worlds (split by world)"}
    for k in _METRIC_KEYS:
        if m and k in m:
            out[k] = m[k]
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _calib(c: dict[str, Any] | None, method: str | None) -> dict[str, Any]:
    if not c:
        return {}
    return {"method": method, "label": LABEL, **c}


def _build() -> list[ModelInfo]:
    STORE.load()
    val = _load("validation_v2.json") or {}
    out: list[ModelInfo] = []
    split = val.get("split") or "split-by-world"

    rf = _load("rf_v2.json")
    if rf:
        out.append(ModelInfo(
            model_id=rf.get("model_id", "rf-v2"), family="random_forest", version=rf["version"],
            trained_at=rf.get("trained_at"), seed=rf.get("seed"), split=rf.get("split", split),
            metrics=_metrics(rf.get("metrics"), threshold=rf.get("threshold"), threshold_rule=rf.get("threshold_rule"),
                             params=rf.get("params"), class_weight_reason=rf.get("class_weight_reason"),
                             leave_one_attack_out=rf.get("loao") or None, loao_config=val.get("loao_config"),
                             old_protocol=val.get("old_protocol"), shap_global=rf.get("shap_global"),
                             features=rf.get("features"), dataset=rf.get("dataset")),
            per_attack=rf.get("per_attack") or {},
            calibration=_calib(rf.get("calibration"), rf.get("calibration_method")),
            status="active" if STORE.rf is not None else "unavailable"))

    gnn = _load("gnn_v2.json")
    if gnn:
        out.append(ModelInfo(
            model_id=gnn.get("model_id", "gnn-gat-v2"), family="gnn", version=gnn["version"],
            trained_at=gnn.get("trained_at"), seed=gnn.get("seed"), split=gnn.get("split", split),
            metrics=_metrics(gnn.get("metrics"), threshold=gnn.get("threshold"), threshold_rule=gnn.get("threshold_rule"),
                             architecture=gnn.get("architecture"), params=gnn.get("params"), training=gnn.get("training"),
                             leave_one_attack_out=gnn.get("loao") or None, loao_config=val.get("loao_config")),
            per_attack=gnn.get("per_attack") or {},
            calibration=_calib(gnn.get("calibration"), gnn.get("calibration_method")),
            status="active" if STORE.gnn is not None else "unavailable"))

    rules = _load("rules_v2.json")
    if rules:
        ew = rules.get("early_warning") or {}
        out.append(ModelInfo(
            model_id=rules.get("model_id", "rules-v2"), family="rules", version=rules["version"],
            trained_at=rules.get("trained_at"), seed=rules.get("seed"), split=rules.get("split", split),
            metrics=_metrics(rules.get("metrics"), rules=rules.get("rules"), flag_points=rules.get("flag_points"),
                             note="Hand-set thresholds (not fitted). Value is a point score, not a probability.",
                             early_warning={"version": ew.get("version"), **_metrics(ew.get("metrics")),
                                            "per_attack": ew.get("per_attack")}),
            per_attack=rules.get("per_attack") or {}, calibration={}, status="active"))

    drift = _load("drift_meta_v2.json")
    if drift:
        out.append(ModelInfo(
            model_id=drift.get("model_id", "drift-v2"), family="drift", version=drift["version"],
            trained_at=drift.get("trained_at"), seed=drift.get("seed"), split=drift.get("split", split),
            metrics=_metrics(drift.get("metrics"), params=drift.get("params"),
                             note="Level (LOW / MEDIUM / HIGH) from per-feature change vs the account's own 45-day "
                                  "baseline; HIGH counts as a flag."),
            per_attack=drift.get("per_attack") or {}, calibration={}, status="active"))

    pm = _load("pattern_memory_meta_v2.json")
    if pm:
        out.append(ModelInfo(
            model_id=pm.get("model_id", "pattern-memory-v2"), family="pattern_memory", version=pm["version"],
            trained_at=pm.get("trained_at"), seed=pm.get("seed"), split=pm.get("split", split),
            metrics=_metrics(pm.get("metrics"), threshold=pm.get("threshold"),
                             note="Structural similarity to prototypes built offline from TRAINING worlds; "
                                  "never reads labels at runtime; not criminal attribution."),
            per_attack=pm.get("per_attack") or {}, calibration={}, status="active"))
    return out


def models() -> list[ModelInfo]:
    """ModelInfo list (built once per process; artefacts are immutable at runtime). Never raises."""
    global _cache
    if _cache is None:
        try:
            _cache = _build()
        except Exception:
            return []
    return [m.model_copy(deep=True) for m in _cache]


def reset_cache() -> None:
    global _cache
    _cache = None
