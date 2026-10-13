"""Async Gemini client (REST, `httpx`) — `models.generateContent` and `models.streamGenerateContent?alt=sse`.

Verified against ai.google.dev (2026-10-13): endpoint `v1beta/models/{model}:generateContent`, header
`x-goog-api-key`, `systemInstruction`, `contents[{role: user|model, parts}]`, `tools[{functionDeclarations}]`,
`generationConfig.responseMimeType/responseSchema`. Model parts are echoed back verbatim in later turns so any
extra fields the model attaches to a function call (e.g. thought signatures) survive.

Any failure — no key, disabled, cap reached, timeout, HTTP error, malformed reply — raises `CopilotUnavailable`;
every caller catches it and falls back to deterministic templates. The key is sent only in the request header and
is never logged.
"""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, AsyncIterator, Protocol

from vigil.copilot import config

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class CopilotUnavailable(Exception):
    pass


class LLM(Protocol):
    async def generate(self, *, system: str, contents: list[dict], tools: list[dict] | None = None,
                       schema: dict | None = None, model: str | None = None, max_tokens: int = 1500) -> dict: ...

    def stream(self, *, system: str, contents: list[dict], tools: list[dict] | None = None,
               model: str | None = None, max_tokens: int = 1500) -> AsyncIterator[dict]: ...


def _body(system: str, contents: list[dict], tools: list[dict] | None, schema: dict | None, max_tokens: int,
          model: str = "") -> dict:
    body: dict[str, Any] = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens}}
    thinking = config.thinking_config(model)
    if thinking:
        body["generationConfig"]["thinkingConfig"] = thinking
    if tools:
        body["tools"] = [{"functionDeclarations": tools}]
    if schema:
        body["generationConfig"]["responseMimeType"] = "application/json"
        body["generationConfig"]["responseSchema"] = schema
    return body


def _check() -> tuple[str, float]:
    if not config.enabled():
        raise CopilotUnavailable("copilot disabled")
    key = config.api_key()
    if not key:
        raise CopilotUnavailable("no GEMINI_API_KEY configured")
    if config.tokens_left() <= 0:
        raise CopilotUnavailable("daily token cap reached")
    return key, config.timeout_s()


def _usage(payload: dict) -> int:
    u = payload.get("usageMetadata") or {}
    return int(u.get("totalTokenCount") or 0)


class GeminiClient:
    async def generate(self, *, system: str, contents: list[dict], tools: list[dict] | None = None,
                       schema: dict | None = None, model: str | None = None, max_tokens: int = 1500) -> dict:
        import httpx
        key, timeout = _check()
        model = model or config.model_fast()
        url = f"{BASE}/{model}:generateContent"
        body = _body(system, contents, tools, schema, max_tokens, model)
        last: Exception | None = None
        for attempt in range(3):                       # 1 try + max 2 jittered retries
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.post(url, json=body, headers={"x-goog-api-key": key})
                if res.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    await asyncio.sleep(0.6 * (attempt + 1) + random.random() * 0.4)
                    continue
                if res.status_code != 200:
                    raise CopilotUnavailable(f"Gemini HTTP {res.status_code}")
                payload = res.json()
                config.record_usage(_usage(payload))
                cands = payload.get("candidates") or []
                if not cands:
                    raise CopilotUnavailable("Gemini returned no candidates")
                return {"parts": (cands[0].get("content") or {}).get("parts") or [], "usage": payload.get("usageMetadata")}
            except CopilotUnavailable as exc:
                last = exc
                break
            except Exception as exc:                   # network / timeout / bad JSON
                last = exc
                if attempt < 2:
                    await asyncio.sleep(0.6 * (attempt + 1) + random.random() * 0.4)
        config.USAGE["errors"] += 1
        config.USAGE["last_error"] = type(last).__name__ if last else "unknown"
        raise CopilotUnavailable(str(last) if isinstance(last, CopilotUnavailable) else "Gemini request failed")

    async def stream(self, *, system: str, contents: list[dict], tools: list[dict] | None = None,
                     model: str | None = None, max_tokens: int = 1500) -> AsyncIterator[dict]:
        """Yields {'text': str} chunks and {'function_call': part} items, then {'usage': n}."""
        import httpx
        key, timeout = _check()
        model = model or config.model_fast()
        url = f"{BASE}/{model}:streamGenerateContent?alt=sse"
        body = _body(system, contents, tools, None, max_tokens, model)
        tokens = 0
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=body, headers={"x-goog-api-key": key}) as res:
                    if res.status_code != 200:
                        raise CopilotUnavailable(f"Gemini HTTP {res.status_code}")
                    async for line in res.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            chunk = json.loads(line[5:].strip())
                        except ValueError:
                            continue
                        tokens = max(tokens, _usage(chunk))
                        for cand in chunk.get("candidates") or []:
                            for part in (cand.get("content") or {}).get("parts") or []:
                                if "functionCall" in part:
                                    yield {"function_call": part}
                                elif part.get("text") and not part.get("thought"):
                                    yield {"text": part["text"]}
        except CopilotUnavailable:
            config.USAGE["errors"] += 1
            raise
        except Exception as exc:
            config.USAGE["errors"] += 1
            config.USAGE["last_error"] = type(exc).__name__
            raise CopilotUnavailable("Gemini stream failed") from None
        config.record_usage(tokens)
        yield {"usage": tokens}


_CLIENT: dict[str, Any] = {"client": None}


def client() -> LLM:
    return _CLIENT["client"] or GeminiClient()


def set_client(c: LLM | None) -> None:
    """Tests inject a stub here (no network)."""
    _CLIENT["client"] = c
