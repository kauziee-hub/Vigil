"""Environment + policy loading. Read once, cached.

Secrets come only from the environment (or the git-ignored `.env` at the repo
root). Nothing secret is ever returned by an API.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
POLICY_PATH = REPO_ROOT / "config" / "risk_policy.yaml"
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader: KEY=VALUE lines, never overrides the real environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    db_path: Path
    host: str
    port: int
    payment_provider: str  # "mock" | "razorpay_test"
    razorpay_key_id: str
    razorpay_key_secret: str
    ambient_default: bool
    ambient_interval_s: float


def _resolve_provider() -> str:
    wanted = os.environ.get("VIGIL_PAYMENT_PROVIDER", "auto").strip().lower()
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    test_keys = key_id.startswith("rzp_test_") and bool(secret)
    if os.environ.get("VIGIL_DEMO_MODE", "").lower() in {"1", "true", "yes"}:
        return "mock"
    if wanted == "mock":
        return "mock"
    if wanted in {"auto", "razorpay_test"} and test_keys:
        return "razorpay_test"
    # Live keys are never used automatically. RazorpayLiveProvider is not built.
    return "mock"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    db = os.environ.get("VIGIL_DB_PATH") or str(REPO_ROOT / "data" / "vigil.db")
    return Settings(
        db_path=Path(db),
        host=os.environ.get("VIGIL_HOST", "0.0.0.0"),
        port=int(os.environ.get("VIGIL_PORT", "8000")),
        payment_provider=_resolve_provider(),
        razorpay_key_id=os.environ.get("RAZORPAY_KEY_ID", ""),
        razorpay_key_secret=os.environ.get("RAZORPAY_KEY_SECRET", ""),
        ambient_default=os.environ.get("VIGIL_AMBIENT", "1") not in {"0", "false", "no"},
        ambient_interval_s=float(os.environ.get("VIGIL_AMBIENT_INTERVAL", "20")),
    )


@lru_cache(maxsize=1)
def get_policy() -> dict[str, Any]:
    data = yaml.safe_load(POLICY_PATH.read_bytes())
    if not isinstance(data, dict):
        raise ValueError(f"policy is not a mapping: {POLICY_PATH}")
    weights = data["fusion"]["weights"]
    total = round(sum(float(v) for v in weights.values()), 6)
    if total != 1.0:
        raise ValueError(f"fusion weights must sum to 1.0, got {total}")
    return data


@lru_cache(maxsize=1)
def get_policy_version() -> str:
    raw = POLICY_PATH.read_bytes()
    version = str(get_policy().get("version", "0"))
    return f"{version}+{hashlib.sha256(raw).hexdigest()[:10]}"


def reload_policy() -> None:
    get_policy.cache_clear()
    get_policy_version.cache_clear()
