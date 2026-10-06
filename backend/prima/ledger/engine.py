"""The ledger engine: the only thing allowed to move money.

Everything here is designed around one idea — *money is never mutated, only
posted*. There is no ``balance`` field to update and therefore no way for a
balance to disagree with its history. A balance is a fold over the journal.

The engine also owns the three properties a financial system is judged on:

* **Idempotency.** A journal carries an optional ``idempotency_key``. Posting
  the same key twice returns the first journal and writes nothing. This is what
  makes a retried webhook or a double-tapped button safe.
* **Atomicity.** A journal is accepted whole or not at all. A journal that
  would overdraw a customer account is rejected before anything is appended.
* **Auditability.** Every accepted journal is hash-linked to its predecessor.

Holds are modelled as claims against *availability*, never as movements of
money. A hold does not touch the ledger. This is deliberate: restraining value
is not the same act as spending it, and conflating the two is how systems end
up unable to explain where a customer's money went.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from prima.ledger.models import (
    GENESIS_HASH,
    Account,
    AccountKind,
    Entry,
    Journal,
    JournalKind,
    simple_transfer_entries,
    verify_chain,
)
from prima.money import Paise, require_positive

__all__ = ["Ledger", "LedgerError", "InsufficientFunds", "Hold"]


class LedgerError(Exception):
    """Base class for refusals from the ledger."""


class InsufficientFunds(LedgerError):
    def __init__(self, account_id: str, requested: Paise, available: Paise) -> None:
        super().__init__(
            f"account {account_id}: requested {requested} but only {available} is available"
        )
        self.account_id = account_id
        self.requested = requested
        self.available = available


class UnknownAccount(LedgerError):
    pass


@dataclass(frozen=True, slots=True)
class Hold:
    """An amount-scoped restraint on an account's available balance.

    A hold reduces what an account may *spend*. It never reduces the balance,
    never touches another account, and is always for a specific amount with a
    specific expiry. There is deliberately no way to construct a hold that
    covers an entire account: the amount is required and is validated positive.
    """

    id: str
    account_id: str
    amount_paise: Paise
    reason_ref: str
    opened_at: datetime
    expires_at: datetime
    incident_id: str | None = None
    released_at: datetime | None = None
    outcome: str | None = None

    @property
    def is_active(self) -> bool:
        return self.released_at is None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Ledger:
    """An in-memory, append-only double-entry ledger.

    This is the reference implementation and the one the tests run against. It
    is deliberately persistence-free: the domain rules live here, and a SQL
    adapter is expected to delegate to this logic rather than reimplement it.
    Any storage backend that preserves journal order and the hash chain will
    produce identical balances and identical attributions.
    """

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._journals: list[Journal] = []
        # Running position: the fold of every journal so far, maintained on
        # append. It is a cache of the fold, never a source of truth —
        # check_invariants() recomputes the fold and compares. Historical
        # (as_of) balances never read it; they still fold the journal.
        self._position: dict[str, int] = {}
        self._by_idempotency: dict[str, Journal] = {}
        self._holds: dict[str, Hold] = {}
        self._lock = threading.RLock()

    # ---------------------------------------------------------------- accounts

    def open_account(
        self,
        account_id: str,
        kind: AccountKind = AccountKind.CUSTOMER,
        display_name: str = "",
        institution: str = "",
        opened_at: datetime | None = None,
    ) -> Account:
        with self._lock:
            if account_id in self._accounts:
                return self._accounts[account_id]
            account = Account(
                id=account_id,
                kind=kind,
                display_name=display_name,
                institution=institution,
                opened_at=opened_at or _utc_now(),
            )
            self._accounts[account_id] = account
            return account

    def account(self, account_id: str) -> Account:
        try:
            return self._accounts[account_id]
        except KeyError:
            raise UnknownAccount(f"no such account: {account_id}") from None

    def accounts(self) -> tuple[Account, ...]:
        return tuple(self._accounts.values())

    # ---------------------------------------------------------------- posting

    def post(
        self,
        kind: JournalKind,
        entries: Sequence[Entry],
        *,
        occurred_at: datetime | None = None,
        idempotency_key: str | None = None,
        reference: str = "",
        metadata: Mapping[str, Any] | None = None,
        enforce_funds: bool = True,
    ) -> Journal:
        """Append one balanced journal, or return the existing one for this key.

        Raises before appending anything if the journal would overdraw a
        customer account. ``EXTERNAL`` accounts may go negative — that is what
        makes them the source of money entering the perimeter.
        """
        with self._lock:
            if idempotency_key is not None:
                existing = self._by_idempotency.get(idempotency_key)
                if existing is not None:
                    return existing

            if not entries:
                raise ValueError("a journal needs at least one entry")
            residual = sum(int(e.amount_paise) for e in entries)
            if residual != 0:
                # Checked before anything else: a journal that does not balance
                # is a programming error, and reporting it as "insufficient
                # funds" would send the reader hunting in the wrong place.
                raise ValueError(
                    "journal does not balance: entries must sum to zero "
                    f"(got {residual})"
                )

            for entry in entries:
                if entry.account_id not in self._accounts:
                    raise UnknownAccount(f"no such account: {entry.account_id}")

            if enforce_funds:
                self._check_funds(entries)

            journal = Journal(
                id="jnl_" + uuid.uuid4().hex,
                kind=kind,
                entries=tuple(entries),
                occurred_at=occurred_at or _utc_now(),
                seq=len(self._journals),
                prev_hash=self._journals[-1].hash if self._journals else GENESIS_HASH,
                idempotency_key=idempotency_key,
                reference=reference,
                metadata=dict(metadata or {}),
            )
            self._journals.append(journal)
            for entry in journal.entries:
                self._position[entry.account_id] = (
                    self._position.get(entry.account_id, 0) + int(entry.amount_paise)
                )
            if idempotency_key is not None:
                self._by_idempotency[idempotency_key] = journal
            return journal

    def _check_funds(self, entries: Iterable[Entry]) -> None:
        net: dict[str, int] = {}
        for entry in entries:
            net[entry.account_id] = net.get(entry.account_id, 0) + int(entry.amount_paise)
        for account_id, delta in net.items():
            if delta >= 0:
                continue
            account = self._accounts[account_id]
            if not account.is_customer:
                continue  # external accounts are the boundary; they may go negative
            available = self.available_balance(account_id)
            if -delta > int(available):
                raise InsufficientFunds(account_id, Paise(-delta), available)

    def transfer(
        self,
        sender_id: str,
        receiver_id: str,
        amount_paise: int,
        *,
        occurred_at: datetime | None = None,
        idempotency_key: str | None = None,
        reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> Journal:
        """Move value between two accounts inside the perimeter."""
        return self.post(
            JournalKind.TRANSFER,
            simple_transfer_entries(sender_id, receiver_id, amount_paise),
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            reference=reference,
            metadata=metadata,
        )

    def external_credit(
        self,
        account_id: str,
        amount_paise: int,
        *,
        source_account_id: str,
        occurred_at: datetime | None = None,
        idempotency_key: str | None = None,
        reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> Journal:
        """Bring value in from outside, debited from a named external account."""
        amount = require_positive(amount_paise, "credit amount")
        if self.account(source_account_id).is_customer:
            raise LedgerError("external credit must come from an EXTERNAL account")
        return self.post(
            JournalKind.EXTERNAL_CREDIT,
            (
                Entry(source_account_id, Paise(-int(amount))),
                Entry(account_id, amount),
            ),
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            reference=reference,
            metadata=metadata,
        )

    def external_debit(
        self,
        account_id: str,
        amount_paise: int,
        *,
        destination_account_id: str,
        occurred_at: datetime | None = None,
        idempotency_key: str | None = None,
        reference: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> Journal:
        """Send value out of the perimeter — a cash-out or a cross-bank hop."""
        amount = require_positive(amount_paise, "debit amount")
        if self.account(destination_account_id).is_customer:
            raise LedgerError("external debit must go to an EXTERNAL account")
        return self.post(
            JournalKind.EXTERNAL_DEBIT,
            (
                Entry(account_id, Paise(-int(amount))),
                Entry(destination_account_id, amount),
            ),
            occurred_at=occurred_at,
            idempotency_key=idempotency_key,
            reference=reference,
            metadata=metadata,
        )

    # --------------------------------------------------------------- balances

    def journals(self) -> tuple[Journal, ...]:
        return tuple(self._journals)

    def journals_for(self, account_id: str) -> tuple[Journal, ...]:
        return tuple(j for j in self._journals if account_id in j.accounts())

    def balance(self, account_id: str, as_of: datetime | None = None) -> Paise:
        """The fold of the journal for this account.

        The current balance comes from the running position, which is updated
        in the same locked step that appends the journal, so it is always the
        fold of exactly the journals appended so far. A historical balance
        (``as_of``) folds the journal directly and never touches the position.
        """
        self.account(account_id)
        if as_of is None:
            return Paise(self._position.get(account_id, 0))
        return self._fold(account_id, as_of)

    def _fold(self, account_id: str, as_of: datetime | None = None) -> Paise:
        total = 0
        for journal in self._journals:
            if as_of is not None and journal.occurred_at > as_of:
                continue
            total += int(journal.delta_for(account_id))
        return Paise(total)

    def available_balance(self, account_id: str) -> Paise:
        """Balance minus every active hold. This is what may be spent."""
        held = sum(
            int(h.amount_paise)
            for h in self._holds.values()
            if h.account_id == account_id and h.is_active
        )
        return Paise(int(self.balance(account_id)) - held)

    def total_in_system(self) -> Paise:
        """Sum of every account balance. Must always be exactly zero."""
        return Paise(sum(int(self.balance(a.id)) for a in self._accounts.values()))

    # ------------------------------------------------------------------ holds

    def open_hold(
        self,
        account_id: str,
        amount_paise: int,
        *,
        reason_ref: str,
        expires_at: datetime,
        incident_id: str | None = None,
        opened_at: datetime | None = None,
        hold_id: str | None = None,
    ) -> Hold:
        """Restrain a specific amount. Never an account.

        Refuses to restrain more than is available, so holds can never make a
        balance unexplainable, and refuses a hold with no expiry.
        """
        amount = require_positive(amount_paise, "hold amount")
        with self._lock:
            self.account(account_id)
            available = self.available_balance(account_id)
            if int(amount) > int(available):
                raise InsufficientFunds(account_id, amount, available)
            opened = opened_at or _utc_now()
            if expires_at <= opened:
                raise LedgerError("a hold must expire in the future")
            hold = Hold(
                id=hold_id or ("hld_" + uuid.uuid4().hex),
                account_id=account_id,
                amount_paise=amount,
                reason_ref=reason_ref,
                opened_at=opened,
                expires_at=expires_at,
                incident_id=incident_id,
            )
            self._holds[hold.id] = hold
            return hold

    def release_hold(self, hold_id: str, outcome: str, at: datetime | None = None) -> Hold:
        with self._lock:
            hold = self._holds.get(hold_id)
            if hold is None:
                raise LedgerError(f"no such hold: {hold_id}")
            if not hold.is_active:
                return hold
            released = Hold(
                id=hold.id,
                account_id=hold.account_id,
                amount_paise=hold.amount_paise,
                reason_ref=hold.reason_ref,
                opened_at=hold.opened_at,
                expires_at=hold.expires_at,
                incident_id=hold.incident_id,
                released_at=at or _utc_now(),
                outcome=outcome,
            )
            self._holds[hold.id] = released
            return released

    def expire_holds(self, now: datetime | None = None) -> tuple[Hold, ...]:
        """Release every hold whose expiry has passed.

        Called on a timer in production. A hold that outlives its expiry is the
        failure mode this whole design exists to prevent, so expiry is a
        property of the data, not of an operator remembering.
        """
        moment = now or _utc_now()
        expired: list[Hold] = []
        with self._lock:
            for hold in list(self._holds.values()):
                if hold.is_active and hold.expires_at <= moment:
                    expired.append(self.release_hold(hold.id, "expired", moment))
        return tuple(expired)

    def holds_for(self, account_id: str, active_only: bool = True) -> tuple[Hold, ...]:
        return tuple(
            h
            for h in self._holds.values()
            if h.account_id == account_id and (h.is_active or not active_only)
        )

    # ------------------------------------------------------------- invariants

    def check_invariants(self) -> None:
        """Assert every ledger-wide invariant. Cheap enough to run in tests
        after every operation, and in production on a schedule."""
        verify_chain(self._journals)
        folded: dict[str, int] = {}
        for journal in self._journals:
            for entry in journal.entries:
                folded[entry.account_id] = folded.get(entry.account_id, 0) + int(entry.amount_paise)
        for account in self._accounts.values():
            if folded.get(account.id, 0) != self._position.get(account.id, 0):
                raise AssertionError(
                    f"running position for {account.id} disagrees with the journal fold"
                )
        residual = self.total_in_system()
        if residual != 0:
            raise AssertionError(
                f"value was created or destroyed: system total is {residual}, expected 0"
            )
        for account in self._accounts.values():
            if not account.is_customer:
                continue
            if self.balance(account.id) < 0:
                raise AssertionError(f"customer account {account.id} has a negative balance")
            held = sum(
                int(h.amount_paise)
                for h in self._holds.values()
                if h.account_id == account.id and h.is_active
            )
            if held > int(self.balance(account.id)):
                raise AssertionError(
                    f"account {account.id} has more held than it holds"
                )
