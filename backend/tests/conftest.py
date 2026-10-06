import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# Isolated, offline test environment — never touches data/vigil.db or Razorpay.
_tmp = tempfile.mkdtemp(prefix="vigil-test-")
os.environ["VIGIL_DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["VIGIL_AMBIENT"] = "0"
os.environ["VIGIL_PAYMENT_PROVIDER"] = "mock"

import pytest  # noqa: E402


@pytest.fixture()
def world():
    """Fresh deterministic demo world."""
    from vigil import db
    from vigil.sim import seed

    db.connect()
    seed.seed()
    return db
