"""One time standard: UTC, ISO-8601, millisecond precision, trailing 'Z'.

Stored as TEXT in SQLite; lexicographic order == chronological order.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Iterator

IST = timezone(timedelta(hours=5, minutes=30))

# Scripted demo scenarios evaluate time-of-day rules at this local hour so their tiers do not
# depend on when the demo is run. Live and ambient payments always use the real hour.
DEMO_LOCAL_HOUR_IST = 14
_pinned_hour: ContextVar[int | None] = ContextVar("pinned_local_hour_ist", default=None)


def now() -> datetime:
    return datetime.now(timezone.utc)


def local_hour_ist() -> int:
    """Hour of day (IST) seen by time-of-day rules: the real hour, unless a scenario pinned it."""
    pinned = _pinned_hour.get()
    return pinned if pinned is not None else now().astimezone(IST).hour


def local_hour_pinned() -> bool:
    return _pinned_hour.get() is not None


@contextmanager
def pinned_local_hour(hour: int = DEMO_LOCAL_HOUR_IST) -> Iterator[None]:
    token = _pinned_hour.set(hour)
    try:
        yield
    finally:
        _pinned_hour.reset(token)


def iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_iso() -> str:
    return iso(now())


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def minutes_between(earlier: str, later: str) -> float:
    return (parse(later) - parse(earlier)).total_seconds() / 60.0


def ago_iso(**delta: float) -> str:
    return iso(now() - timedelta(**delta))
