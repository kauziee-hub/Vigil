"""Ledger operations. Integer paise. Every posting debits one account and
credits another in the same SQLite transaction (the old PRIMA bug — debit
without credit — cannot happen here). Customer balances never go negative.
"""

from __future__ import annotations

from typing import Any

from vigil import clock, db
from vigil.engine import hooks
from vigil.graph.pathgraph import GRAPH


class VigilError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def account(account_id: str) -> dict[str, Any]:
    row = db.q1("SELECT * FROM accounts WHERE id = ?", (account_id,))
    if row is None:
        raise VigilError(404, "unknown_account", f"No account '{account_id}' in the demo ledger.")
    return row


def held_paise(account_id: str) -> int:
    return int(db.scalar(
        "SELECT COALESCE(SUM(held_paise), 0) FROM scoped_holds WHERE account_id = ? AND released_at IS NULL",
        (account_id,)) or 0)


def available_paise(account_id: str, exclude_intent: str | None = None) -> int:
    acc = account(account_id)
    held = held_paise(account_id)
    if exclude_intent:
        held -= int(db.scalar(
            "SELECT COALESCE(SUM(held_paise), 0) FROM scoped_holds WHERE intent_id = ? AND released_at IS NULL",
            (exclude_intent,)) or 0)
    return int(acc["balance_paise"]) - held


def post(
    *, sender_id: str, recipient_id: str, amount_paise: int, kind: str = "transfer",
    ts: str | None = None, note: str | None = None, intent_id: str | None = None,
    source: str = "user", device_id: str | None = None, channel: str = "upi",
    seed_attack: str | None = None, check_funds: bool = True,
) -> dict[str, Any]:
    if isinstance(amount_paise, bool) or not isinstance(amount_paise, int) or amount_paise <= 0:
        raise VigilError(400, "bad_amount", "amount_paise must be a positive integer.")
    if sender_id == recipient_id:
        raise VigilError(400, "same_account", "Sender and recipient must differ.")
    with db.tx():
        sender = account(sender_id)
        account(recipient_id)
        if check_funds and sender["kind"] == "customer":
            if available_paise(sender_id, exclude_intent=intent_id) < amount_paise:
                raise VigilError(400, "insufficient_funds", "Not enough available balance.")
        row = {
            "id": db.next_id("TX"),
            "seq": db.next_seq(),
            "kind": kind,
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "amount_paise": amount_paise,
            "channel": channel,
            "device_id": device_id,
            "note": note,
            "ts": ts or clock.now_iso(),
            "intent_id": intent_id,
            "source": source,
            "seed_attack": seed_attack,
        }
        db.insert("transactions", row)
        db.execute("UPDATE accounts SET balance_paise = balance_paise - ? WHERE id = ?", (amount_paise, sender_id))
        db.execute("UPDATE accounts SET balance_paise = balance_paise + ? WHERE id = ?", (amount_paise, recipient_id))
        if kind == "transfer":
            db.execute(
                "INSERT OR IGNORE INTO payees(account_id, payee_id, added_at) VALUES (?, ?, ?)",
                (sender_id, recipient_id, row["ts"]),
            )
    GRAPH.add_transaction(row)
    hooks.emit(row)
    return row


def system_total() -> int:
    return int(db.scalar("SELECT COALESCE(SUM(balance_paise), 0) FROM accounts") or 0)
