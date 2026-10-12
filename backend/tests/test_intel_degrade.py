"""The platform must start and decide payments when the optional ML dependencies are missing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

SCRIPT = r"""
import json, sys
for name in ("numpy", "sklearn", "shap", "torch", "joblib", "scipy"):
    sys.modules[name] = None                      # any import of these now raises ImportError
from fastapi.testclient import TestClient
from vigil import app as app_module
out = {"intel_available": app_module.INTEL_AVAILABLE}
with TestClient(app_module.app) as c:
    models = c.get("/api/intel/models").json()
    out["models"] = {m["model_id"]: m["status"] for m in models}
    intel = c.get("/api/intel/accounts/kiran.traders@vigil").json()
    out["detectors"] = {d["family"]: d["status"] for d in intel["detectors"]}
    out["shap"] = intel["shap"]
    out["consensus"] = intel["consensus"]
    r = c.post("/api/intents", json={"sender_id": "ramesh@vigil", "recipient_id": "meena.grocer@vigil",
                                    "amount_paise": 50000})
    d = r.json()["decision"]
    out["payment"] = {"status": r.status_code, "tier": d["tier"],
                      "evidence": {m["family"]: m["status"] for m in d["model_evidence"]}}
    out["scores"] = c.get("/api/intel/scores").status_code
    out["overview"] = c.get("/api/intel/overview").status_code
print("RESULT" + json.dumps(out))
"""


def test_app_runs_without_ml_dependencies():
    tmp = tempfile.mkdtemp(prefix="vigil-nodeps-")
    env = {**os.environ, "VIGIL_DB_PATH": os.path.join(tmp, "t.db"), "VIGIL_AMBIENT": "0",
           "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, "-c", SCRIPT], cwd=str(BACKEND), env=env, capture_output=True, text=True,
                          timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT"))
    out = json.loads(line[len("RESULT"):])
    assert out["intel_available"] is True
    assert out["models"]["rf-v2"] == "unavailable" and out["models"]["gnn-gat-v2"] == "unavailable"
    assert out["models"]["rules-v2"] == "active"
    assert out["detectors"]["random_forest"] == "unavailable" and out["detectors"]["gnn"] == "unavailable"
    assert out["detectors"]["rules"] == "ok" and out["detectors"]["drift"] == "ok"
    assert out["shap"] is None
    assert out["consensus"]["families_evaluated"] >= 5            # the pure-python families still work
    assert out["payment"]["status"] == 200 and out["payment"]["tier"] == 0
    assert out["payment"]["evidence"]["random_forest"] == "unavailable"
    assert out["scores"] == 200 and out["overview"] == 200
