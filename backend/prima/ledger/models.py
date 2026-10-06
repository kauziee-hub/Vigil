"""Ledger domain types.

The ledger is an append-only, hash-chained journal of double-entry postings.
It is the only source of truth about money in PRIMA. Balances, provenance,
attribution and every risk signal are *derived* from it and can be rebuilt
from it. Nothing else is authoritative, and nothing is ever updated in place.

Two invariants hold at all times, and are enforced rather than documented:

* **Balance.** Every journal's entries sum to exactly zero.
* **Continuity.** Every journal's ``prev_hash`` is the hash of the journal
  before it, so the log cannot be reordered or silently edited.

Money entering from outside the observed perimeter is not created out of
nothing: it is debited from an ``EXTERNAL`` account representing the
counterparty institution. The sum of *all* account balances is therefore
always zero, which is what makes "value was conserved" a checkable statement
rather than an aspiration.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from prima.money import Paise, require_positive

__all__ = [
    "AccountKind",
    "Account",
    "Entry",
    "Journal",
    "JournalKind",
    "GENESIS_HASH",
    "canonical_json",
]

GENESIS_HASH = "0" * 64


class AccountKind(str, Enum):
    """What sort of thing an account is.

    ``CUSTOMER`` accounts are inside the perimeter: we see their postings and
    can attribute value held in them. ``EXTERNAL`` accounts stand in for
    everything outside it — another bank, a card network, cash. Value that
    crosses into an ``EXTERNAL`` account has left our sight; attribution
    reports that as an opaque hop rather than pretending to follow it.
    """

    CUSTOMER = "customer"
    EXTERNAL = "external"


class JournalKind(str, Enum):
    TRANSFER = "transfer"                # customer -> customer, inside the perimeter
    EXTERNAL_CREDIT = "external_credit"  # money arriving from outside
    EXTERNAL_DEBIT = "external_debit"    # money leaving the perimeter
    ADJUSTMENT = "adjustment"            # operational correction, always attributed


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    kind: AccountKind
    display_name: str = ""
    institution: str = ""
    opened_at: datetime | None = None

    @property
    def is_customer(self) -> bool:
        return self.kind is AccountKind.CUSTOMER


@dataclass(frozen=True, slots=True)
class Entry:
    """One side of a posting: a signed change to one account.

    ``amount_paise`` is signed from the account's point of view — negative is
    money leaving it, positive is money arriving. A transfer is two entries
    that sum to zero.
    """

    account_id: str
    amount_paise: Paise

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount_paise", Paise(self.amount_paise))
        if self.amount_paise == 0:
            raise ValueError("an entry of zero paise carries no information")

    @property
    def is_debit(self) -> bool:
        return self.amount_paise < 0

    @property
    def is_credit(self) -> bool:
        return self.amount_paise > 0

    def as_dict(self) -> dict[str, Any]:
        return {"account_id": self.account_id, "amount_paise": int(self.amount_paise)}


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Deterministic JSON for hashing.

    Sorted keys, no insignificant whitespace, UTF-8 preserved. Two processes
    on two machines must produce byte-identical output for the same payload,
    or the hash chain is worthless.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class Journal:
    """An atomic, balanced set of entries, linked to the one before it."""

    id: str
    kind: JournalKind
    entries: tuple[Entry, ...]
    occurred_at: datetime
    seq: int
    prev_hash: str
    idempotency_key: str | None = None
    reference: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.entries:
            raise ValueError("a journal needs at least one entry")
        if len(self.entries) < 2:
            raise ValueError("double-entry: a journal needs at least two entries")
        if sum(int(e.amount_paise) for e in self.entries) != 0:
            raise ValueError(
                "journal does not balance: entries must sum to zero "
                f"(got {sum(int(e.amount_paise) for e in self.entries)})"
            )
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.seq < 0:
            raise ValueError("seq must not be negative")

    @property
    def total_moved(self) -> Paise:
        """The magnitude of value moved — the sum of the positive side."""
        return Paise(sum(int(e.amount_paise) for e in self.entries if e.amount_paise > 0))

    def hashable_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "seq": self.seq,
            "prev_hash": self.prev_hash,
            "occurred_at": self.occurred_at.astimezone(timezone.utc).isoformat(),
            "idempotency_key": self.idempotency_key,
            "reference": self.reference,
            "entries": [e.as_dict() for e in self.entries],
            "metadata": dict(sorted(self.metadata.items())),
        }

    @property
    def hash(self) -> str:
        return hashlib.sha256(
            canonical_json(self.hashable_payload()).encode("utf-8")
        ).hexdigest()

    def delta_for(self, account_id: str) -> Paise:
        return Paise(
            sum(int(e.amount_paise) for e in self.entries if e.account_id == account_id)
        )

    def accounts(self) -> tuple[str, ...]:
        seen: list[str] = []
        for entry in self.entries:
            if entry.account_id not in seen:
                seen.append(entry.account_id)
        return tuple(seen)


def simple_transfer_entries(
    sender_id: str, receiver_id: str, amount_paise: int
) -> tuple[Entry, ...]:
    """The two entries of an ordinary one-to-one transfer."""
    amount = require_positive(amount_paise, "transfer amount")
    if sender_id == receiver_id:
        raise ValueError("cannot transfer to the same account")
    return (
        Entry(account_id=sender_id, amount_paise=Paise(-int(amount))),
        Entry(account_id=receiver_id, amount_paise=amount),
    )


def verify_chain(journals: Sequence[Journal]) -> None:
    """Raise if the journal sequence is not a valid hash chain.

    Checks sequence numbering, link continuity and per-journal balance. This is
    the function an auditor runs; it must not depend on any stored derived
    state.
    """
    expected_prev = GENESIS_HASH
    for index, journal in enumerate(journals):
        if journal.seq != index:
            raise ValueError(f"journal {journal.id}: seq {journal.seq} != position {index}")
        if journal.prev_hash != expected_prev:
            raise ValueError(
                f"journal {journal.id}: prev_hash does not match the previous journal"
            )
        if sum(int(e.amount_paise) for e in journal.entries) != 0:
            raise ValueError(f"journal {journal.id}: does not balance")
        expected_prev = journal.hash
