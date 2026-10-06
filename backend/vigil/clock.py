"""One time standard: UTC, ISO-8601, millisecond precision, trailing 'Z'.

Stored as TEXT in SQLite; lexicographic order == chronological order.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now() -> datetime:
    return datetime.now(timezone.utc)


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
