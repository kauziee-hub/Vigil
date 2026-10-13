"""The single-page-app fallback must never serve a file from outside frontend/dist (e.g. backend/.env or the README)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_spa_fallback_never_escapes_the_build_folder(world):
    from vigil import app as app_mod
    if not app_mod.FRONTEND_DIST.is_dir():
        pytest.skip("frontend/dist not built")
    with TestClient(app_mod.app) as c:
        for path in ("/%2e%2e/%2e%2e/README.md", "/..%2f..%2fREADME.md", "/%2e%2e/%2e%2e/backend/vigil/settings.py"):
            r = c.get(path)
            assert r.status_code == 200
            assert "<!doctype html" in r.text.lower() or "<html" in r.text.lower(), path   # index.html, not the file
            assert "PRIMA" not in r.text[:200] and "def " not in r.text, path
