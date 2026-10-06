"""The single database layer. stdlib sqlite3, WAL, one connection.

The FastAPI app runs every handler on the event-loop thread, so this one
connection is only ever touched by one thread at a time. Do not create a
second connection layer anywhere else in the codebase.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from vigil.settings import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_conn: sqlite3.Connection | None = None


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def connect(path: Path | None = None) -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    db_path = path or get_settings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _conn = conn
    return conn


def conn() -> sqlite3.Connection:
    return _conn if _conn is not None else connect()


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def q(sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    return conn().execute(sql, params).fetchall()


def q1(sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    return conn().execute(sql, params).fetchone()


def scalar(sql: str, params: tuple | dict = ()) -> Any:
    row = conn().execute(sql, params).fetchone()
    if row is None:
        return None
    return next(iter(row.values()))


def execute(sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
    return conn().execute(sql, params)


def insert(table: str, row: dict[str, Any]) -> None:
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    conn().execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", row)


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """Atomic unit of work. Nested use joins the outer transaction."""
    c = conn()
    if c.in_transaction:
        yield c
        return
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
    except BaseException:
        c.execute("ROLLBACK")
        raise
    else:
        c.execute("COMMIT")


def next_id(prefix: str, width: int = 6) -> str:
    """Readable sequential ids: INT-000001, DEC-000001 … (reset with the demo)."""
    key = f"seq:{prefix}"
    row = q1("SELECT value FROM meta WHERE key = ?", (key,))
    value = int(row["value"]) + 1 if row else 1
    execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    return f"{prefix}-{value:0{width}d}"


def next_seq() -> int:
    value = scalar("SELECT COALESCE(MAX(seq), -1) FROM transactions")
    return int(value) + 1


def get_meta(key: str, default: str | None = None) -> str | None:
    row = q1("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


ALL_TABLES = (
    "intent_transitions", "circuit_breaker_events", "scoped_holds", "alerts",
    "risk_decisions", "payment_attempts", "transaction_intents", "fraud_labels",
    "taint_runs", "scenario_runs", "events", "payees", "account_devices",
    "trusted_contacts", "external_intel", "transactions", "accounts", "meta",
)


def wipe() -> None:
    with tx() as c:
        for table in ALL_TABLES:
            c.execute(f"DELETE FROM {table}")
        # AUTOINCREMENT counters survive DELETE; reset them so a demo reset restores identical ids.
        if c.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
            c.execute("DELETE FROM sqlite_sequence")


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, sort_keys=True, default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)
