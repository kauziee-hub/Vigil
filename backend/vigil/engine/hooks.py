"""Post-commit hooks on ledger postings (v3 live platform).

`ledger.post` calls `emit(tx_row)` after a posting is committed and appended to
the PathGraph. Listeners (e.g. `vigil.intel.stream`, owned by Claude 2) register
with `register(fn)`; they run synchronously on the event-loop thread and MUST be
fast (< 30 ms) and MUST NOT raise — any exception is caught and counted so the
payment path can never fail because of a listener.

Bulk work (seeding, resets) wraps itself in `suspended()` so tens of thousands
of historical postings do not trigger live scoring.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Callable, Iterator

log = logging.getLogger("vigil.hooks")

Listener = Callable[[dict[str, Any]], None]
_listeners: list[Listener] = []
_state = {"suspended": 0, "errors": 0, "emitted": 0}


def register(fn: Listener) -> Listener:
    if fn not in _listeners:
        _listeners.append(fn)
    return fn


def unregister(fn: Listener) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


@contextmanager
def suspended() -> Iterator[None]:
    _state["suspended"] += 1
    try:
        yield
    finally:
        _state["suspended"] -= 1


def emit(tx: dict[str, Any]) -> None:
    if _state["suspended"]:
        return
    _state["emitted"] += 1
    for fn in list(_listeners):
        try:
            fn(tx)
        except Exception:  # a listener must never break a posting
            _state["errors"] += 1
            log.exception("posting listener failed")


def stats() -> dict[str, Any]:
    return {**_state, "listeners": [getattr(f, "__qualname__", repr(f)) for f in _listeners]}
