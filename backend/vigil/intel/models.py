"""Runtime model store. Loaded ONCE (lazy, module-level, thread-safe), never per request.

* Random Forest: trained with scikit-learn (ml/train_all.py) and exported to plain arrays
  (models/rf_v2.npz); inference is a vectorised numpy tree walk (verified equal to sklearn
  predict_proba at training time and in tests). Calibration = isotonic map fitted on VALIDATION
  worlds, stored as knots in models/rf_v2.json.
* GNN (GAT): trained with plain torch (ml/gnn_torch.py), exported to numpy (models/gnn_v2.npz);
  inference re-implements the same edge-softmax attention in numpy (verified at training time and
  in tests). No torch import at serve time.
* SHAP: TreeExplainer over the sklearn forest (models/rf_v2.joblib), imported lazily on first use.

Missing numpy / artefacts -> the detector reports status="unavailable". Nothing here raises to callers.
"""

from __future__ import annotations

import bisect
import json
import logging
import math
import threading
from pathlib import Path
from typing import Any

from vigil.intel.features import FEATURES

log = logging.getLogger("vigil.intel")
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
LOG_FEATURES = {"in_degree", "out_degree", "total_in_amount", "total_out_amount", "unique_neighbors",
                "unique_channels", "device_cluster_size", "transaction_count", "account_age_days",
                "near_threshold_outflows", "dormancy_days", "baseline_tx_rate"}
SHAP_CATEGORIES = {
    "transaction_count": "Velocity Risk", "baseline_tx_rate": "Velocity Risk",
    "in_degree": "Ring Participation", "out_degree": "Ring Participation", "unique_neighbors": "Ring Participation",
    "retention_ratio": "Retention Risk", "forwarded_fraction": "Retention Risk",
    "device_cluster_size": "Shared Device Risk", "unique_channels": "Channel Risk",
    "account_age_days": "Account Newness", "dormancy_days": "Dormancy Risk",
    "new_counterparty_ratio": "Counterparty Novelty", "near_threshold_outflows": "Structuring Risk",
    "total_in_amount": "Value Risk", "total_out_amount": "Value Risk",
}


def gnn_input_row(f: dict[str, float] | None, is_external: bool) -> list[float]:
    """Raw GNN input (before train-fitted standardisation). Externals: zeros + indicator."""
    if is_external or f is None:
        return [0.0] * len(FEATURES) + [1.0]
    return [math.log1p(max(0.0, f[k])) if k in LOG_FEATURES else float(f[k]) for k in FEATURES] + [0.0]


# ── numpy kernels (shared with tests) ─────────────────────────────────────
def forest_predict(arr: dict[str, Any], X: Any) -> Any:
    import numpy as np
    X = np.asarray(X, dtype=np.float32).astype(np.float64)
    n = X.shape[0]
    left, right, feat, thr, p1, offs = arr["left"], arr["right"], arr["feature"], arr["threshold"], arr["p1"], arr["offsets"]
    rows = np.arange(n)
    total = np.zeros(n)
    depth = int(arr["max_depth"]) + 1
    for t in range(len(offs) - 1):
        off = int(offs[t])
        idx = np.zeros(n, dtype=np.int64)
        for _ in range(depth):
            g = off + idx
            lc = left[g]
            internal = lc != -1
            if not internal.any():
                break
            go_left = X[rows, np.maximum(feat[g], 0)] <= thr[g]
            idx = np.where(internal, np.where(go_left, lc, right[g]), idx)
        total += p1[off + idx]
    return total / (len(offs) - 1)


def gat_forward(W: dict[str, Any], x: Any, edges_in: tuple[Any, Any], edges_out: tuple[Any, Any]) -> Any:
    """2-layer relational GAT, numpy. edges_*: (j_src_idx, i_dst_idx) message j -> i, self-loops included."""
    import numpy as np
    h = np.asarray(x, dtype=np.float64)
    heads = int(W["heads"])
    for k in (1, 2):
        out = h @ W[f"l{k}_self_w"] + W[f"l{k}_self_b"]
        n = h.shape[0]
        for r, (j, i) in (("in", edges_in), ("out", edges_out)):
            z = (h @ W[f"l{k}_{r}_w"]).reshape(n, heads, -1)
            e = (z[i] * W[f"l{k}_{r}_adst"]).sum(-1) + (z[j] * W[f"l{k}_{r}_asrc"]).sum(-1)
            e = np.where(e > 0, e, 0.2 * e)
            emax = np.full((n, heads), -np.inf)
            np.maximum.at(emax, i, e)
            ex = np.exp(e - emax[i])
            den = np.zeros((n, heads))
            np.add.at(den, i, ex)
            alpha = ex / den[i]
            m = np.zeros_like(z)
            np.add.at(m, i, alpha[..., None] * z[j])
            out = out + m.reshape(n, -1)
        h = np.where(out > 0, out, np.expm1(np.minimum(out, 0)))
    logit = (h @ W["out_w"]).reshape(-1) + W["out_b"].reshape(-1)[0]
    return 1.0 / (1.0 + np.exp(-logit))


def build_edge_index(n: int, pairs: list[tuple[int, int]]) -> tuple[tuple[Any, Any], tuple[Any, Any]]:
    """pairs: (sender_idx, recipient_idx). 'in' relation: sender -> recipient; 'out': recipient -> sender."""
    import numpy as np
    loops = np.arange(n, dtype=np.int64)
    s = np.array([p[0] for p in pairs], dtype=np.int64)
    d = np.array([p[1] for p in pairs], dtype=np.int64)
    e_in = (np.concatenate([s, loops]), np.concatenate([d, loops]))
    e_out = (np.concatenate([d, loops]), np.concatenate([s, loops]))
    return e_in, e_out


# ── store ─────────────────────────────────────────────────────────────────
class ModelStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.loaded = False
        self.rf: dict[str, Any] | None = None
        self.rf_meta: dict[str, Any] = {}
        self.gnn: dict[str, Any] | None = None
        self.gnn_meta: dict[str, Any] = {}
        self.errors: dict[str, str] = {}
        self._explainer: Any = None
        self._shap_tried = False

    def load(self) -> "ModelStore":
        if self.loaded:
            return self
        with self._lock:
            if self.loaded:
                return self
            try:
                self.rf_meta = json.loads((MODELS_DIR / "rf_v2.json").read_text(encoding="utf-8"))
                self.gnn_meta = json.loads((MODELS_DIR / "gnn_v2.json").read_text(encoding="utf-8"))
            except Exception as exc:
                self.errors["metadata"] = f"{type(exc).__name__}: {exc}"
            try:
                import numpy as np
                with np.load(MODELS_DIR / "rf_v2.npz") as z:
                    self.rf = {k: z[k] for k in z.files}
            except Exception as exc:
                self.errors["random_forest"] = f"{type(exc).__name__}: {exc}"
                self.rf = None
            try:
                import numpy as np
                with np.load(MODELS_DIR / "gnn_v2.npz") as z:
                    self.gnn = {k: z[k] for k in z.files}
            except Exception as exc:
                self.errors["gnn"] = f"{type(exc).__name__}: {exc}"
                self.gnn = None
            self.loaded = True
            if self.errors:
                log.warning("intel models partially unavailable: %s", self.errors)
        return self

    # RF
    def rf_raw(self, rows: list[list[float]]) -> list[float] | None:
        self.load()
        if self.rf is None or not rows:
            return None if self.rf is None else []
        return [float(v) for v in forest_predict(self.rf, rows)]

    def calibrate(self, p: float, family: str) -> float:
        meta = self.rf_meta if family == "random_forest" else self.gnn_meta
        cal = meta.get("calibration_map")
        if not cal:
            return p
        xs, ys = cal["x"], cal["y"]
        if p <= xs[0]:
            return float(ys[0])
        if p >= xs[-1]:
            return float(ys[-1])
        i = bisect.bisect_right(xs, p)
        x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
        return float(y0 + (y1 - y0) * (p - x0) / (x1 - x0)) if x1 > x0 else float(y1)

    # GNN
    def gnn_scores(self, raw_rows: list[list[float]], pairs: list[tuple[int, int]]) -> list[float] | None:
        self.load()
        if self.gnn is None or not raw_rows:
            return None if self.gnn is None else []
        import numpy as np
        x = (np.asarray(raw_rows, dtype=np.float64) - self.gnn["mean"]) / self.gnn["std"]
        e_in, e_out = build_edge_index(len(raw_rows), pairs)
        return [float(v) for v in gat_forward(self.gnn, x, e_in, e_out)]

    # SHAP
    def explainer(self) -> Any:
        if self._shap_tried:
            return self._explainer
        with self._lock:
            if self._shap_tried:
                return self._explainer
            try:
                import joblib
                import shap
                model = joblib.load(MODELS_DIR / "rf_v2.joblib")
                self._explainer = shap.TreeExplainer(model)
            except Exception as exc:
                self.errors["shap"] = f"{type(exc).__name__}: {exc}"
                self._explainer = None
            self._shap_tried = True
        return self._explainer

    def shap_values(self, row: list[float]) -> tuple[float, list[float]] | None:
        ex = self.explainer()
        if ex is None:
            return None
        try:
            import numpy as np
            vals = ex.shap_values(np.asarray([row], dtype=np.float64), check_additivity=False)
            base = ex.expected_value
            arr = np.asarray(vals)
            if isinstance(vals, list):           # older shap: list per class
                contrib = np.asarray(vals[1])[0]
                b = float(np.asarray(base).reshape(-1)[1])
            elif arr.ndim == 3:                  # (n, features, classes)
                contrib = arr[0, :, 1]
                b = float(np.asarray(base).reshape(-1)[1])
            else:
                contrib = arr[0]
                b = float(np.asarray(base).reshape(-1)[-1])
            return b, [float(v) for v in contrib]
        except Exception as exc:
            self.errors["shap"] = f"{type(exc).__name__}: {exc}"
            return None


STORE = ModelStore()
