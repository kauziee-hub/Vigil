import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Isolated, offline test environment — never touches data/vigil.db.
_tmp = tempfile.mkdtemp(prefix="vigil-test-")
os.environ["VIGIL_DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["VIGIL_AMBIENT"] = "0"
os.environ["VIGIL_NO_DOTENV"] = "1"            # never load a developer's real API keys during tests
for _k in ("GEMINI_API_KEY", "GEMINI_API", "GOOGLE_API_KEY"):
    os.environ.pop(_k, None)

import pytest  # noqa: E402


@pytest.fixture()
def world():
    """Fresh deterministic demo world."""
    from vigil import db
    from vigil.sim import seed

    db.connect()
    seed.seed()
    return db
