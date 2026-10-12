"""Copilot runtime configuration. Secrets come ONLY from the environment (.env, git-ignored); nothing here is ever
returned by an API, logged or sent to the browser except booleans and model names."""

from __future__ import annotations

import os
import time
from typing import Any

from vigil import overview


def policy() -> dict[str, Any]:
    return overview.policy()["copilot"]


def api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    return key or None


def enabled() -> bool:
    raw = os.environ.get("COPILOT_ENABLED", "")
    if raw.strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool(policy().get("enabled_default", True))


def llm_available() -> bool:
    return enabled() and api_key() is not None


def model_fast() -> str:
    return os.environ.get("COPILOT_MODEL_FAST", "").strip() or policy()["default_model_fast"]


def model_deep() -> str:
    return os.environ.get("COPILOT_MODEL_DEEP", "").strip() or policy()["default_model_deep"]


def daily_cap() -> int:
    try:
        return int(os.environ.get("COPILOT_DAILY_TOKEN_CAP") or policy()["daily_token_cap"])
    except ValueError:
        return int(policy()["daily_token_cap"])


def timeout_s() -> float:
    try:
        return float(os.environ.get("COPILOT_TIMEOUT_S") or policy()["timeout_s"])
    except ValueError:
        return float(policy()["timeout_s"])


# usage accounting (process-local; resets daily)
USAGE: dict[str, Any] = {"day": time.strftime("%Y-%m-%d"), "tokens": 0, "calls": 0, "errors": 0, "last_error": None}


def record_usage(tokens: int) -> None:
    today = time.strftime("%Y-%m-%d")
    if USAGE["day"] != today:
        USAGE.update(day=today, tokens=0, calls=0, errors=0)
    USAGE["tokens"] += int(tokens or 0)
    USAGE["calls"] += 1


def tokens_left() -> int:
    if USAGE["day"] != time.strftime("%Y-%m-%d"):
        return daily_cap()
    return max(0, daily_cap() - int(USAGE["tokens"]))


def status() -> dict[str, Any]:
    return {"enabled": enabled(), "llm_available": llm_available(), "configured": api_key() is not None,
            "model_fast": model_fast(), "model_deep": model_deep(), "tokens_left_today": tokens_left(),
            "daily_token_cap": daily_cap(), "calls_today": USAGE["calls"], "errors_today": USAGE["errors"],
            "mode": "gemini" if llm_available() else "offline (deterministic templates)",
            "note": "Enabling the Copilot sends incident facts (synthetic data) to Google's Gemini API."
            if llm_available() else "No key configured or Copilot disabled: everything stays on this machine."}
