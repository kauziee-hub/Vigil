"""Incremental LIBR.

The batch engine answers "where did this money go" by replaying the whole
journal. That is the right thing for a derivation somebody will contest, and the
wrong thing for a decision that has to be made in the seconds before a payment
is confirmed. This module keeps the same answer up to date as postings arrive,
so at decision time the system looks up a number it already has.

It works because coalescing is exact *for LIBR specifically*. LIBR consumes in
rank order — the account holder's own money, then the oldest incident, then the
next — so how much each rank contributes to an outflow depends only on the total
held at each rank, never on which individual parcels those totals are made of.
An account's state therefore collapses from a list of parcels to a small map::

    account -> {None: own_paise, incident_1: paise, incident_2: paise, ...}

and a posting costs O(incidents touching the affected accounts), independent of
how long the history is.

This does not generalise. FIFO and LIFO break ties on parcel arrival order and
pro rata divides across every parcel, so both need the parcels themselves. Those
stay batch-only, and this module refuses any rule but LIBR rather than quietly
returning a number that is not the one the batch engine would give.

The batch engine is the reference. Everything here exists to reproduce it
exactly, posting by posting — not approximately, and not eventually.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from prima.attribution.rules import TracingRule
from prima.attribution.trace import (
    Incident,
    allocate_across_credits,
    trace_multi,
)
from prima.ledger.models import Account, Journal

__all__ = ["LineageState", "IncrementalLineage", "OutOfOrderJournal"]

# account id -> {incident id or None for own money: paise}
LineageState = dict[str, dict[str | None, int]]


class OutOfOrderJournal(ValueError):
    """Raised when :meth:`IncrementalLineage.apply` is handed a journal that is
    not the immediate successor of the last one it folded in.

    The class reproduces the batch engine one posting at a time, and the batch
    engine consumes the journal in strict ``seq`` order. A repeat, a gap, or a
    step backwards all mean the incremental state would diverge from what
    ``trace_multi`` says on the same journals — a repeat double-counts, a gap
    silently omits a posting the batch engine would have seen. Neither is
    something this class can paper over, so it refuses and lets the caller
    decide. It is a ``ValueError`` to match the other misuse guards in this
    codebase (``trace()``'s rejection of a bad ``other_live_incidents``, the
    duplicate-id check in ``trace_multi``).
    """


class IncrementalLineage:
    """A running LIBR position, maintained one posting at a time.

    Construct it with the live incidents and the accounts inside the perimeter,
    then either feed it the journal from the beginning or :meth:`seed_from` a
    batch trace and carry on. Incidents are reported after the money has already
    moved, so the seeding seam is not an optimisation — it is the normal case.
    """

    rule = TracingRule.LIBR

    def __init__(
        self,
        incidents: Sequence[Incident],
        customer_ids: Iterable[str],
    ) -> None:
        incident_list = list(incidents)
        ids = [incident.id for incident in incident_list]
        if len(set(ids)) != len(ids):
            raise ValueError("incident ids must be unique")

        self._incidents = incident_list
        self._incident_ids = ids
        self._customers: set[str] = set(customer_ids)

        self._origin_of: dict[str, str] = {}
        for incident in incident_list:
            for journal_id in incident.origin_journal_ids:
                claimed_by = self._origin_of.get(journal_id)
                if claimed_by is not None and claimed_by != incident.id:
                    # Same refusal the batch engine makes, for the same reason:
                    # one movement cannot be two separate frauds' origin.
                    raise ValueError(
                        f"journal {journal_id} is named as the origin of both "
                        f"{claimed_by} and {incident.id}; an origin belongs to "
                        "one incident"
                    )
                self._origin_of[journal_id] = incident.id

        self._state: LineageState = {}
        self._left: dict[str, int] = {i: 0 for i in ids}
        self._retagged: dict[str, int] = {i: 0 for i in ids}
        self._first_seen: dict[str, int] = {}
        self._max_seq_seen = -1
        # Value an account spent that the observed history cannot account for.
        # Counted, never raised on: a trace that starts mid-history is the
        # normal case, and refusing to score it would be worse than saying so.
        self.coverage_gap = 0

    # ------------------------------------------------------------- ordering

    def _ordered_incident_ids(self) -> list[str]:
        """Incidents oldest-first, exactly as the batch engine ranks them.

        An incident whose origin has not been seen yet sorts last. It can hold
        nothing, so its position cannot affect any arithmetic — but the order
        still has to be total, or two runs could disagree.
        """
        unseen = self._max_seq_seen + 1
        return sorted(
            self._incident_ids,
            key=lambda i: (self._first_seen.get(i, unseen), i),
        )

    def _consume_order(self) -> list[str | None]:
        """Own money first, then the oldest incident. This is LIBR."""
        return [None, *self._ordered_incident_ids()]

    def _append_order(self) -> list[str | None]:
        """Tagged first, own money last — the order the batch appends parcels.

        It looks arbitrary and is not: :func:`allocate_across_credits` fills each
        credit's capacity in this order, so reversing it would move a rounding
        paisa from one tag to another.
        """
        return [*self._ordered_incident_ids(), None]

    # -------------------------------------------------------------- seeding

    def seed_from(
        self,
        ledger,
        accounts: Mapping[str, Account],
        customer_ids: Iterable[str] | None = None,
        *,
        through_seq: int | None = None,
    ) -> None:
        """Initialise from a batch trace taken at report time.

        The batch trace is computed here, from ``self._incidents`` and
        ``self.rule``, in one combined :func:`trace_multi` pass. It is not
        accepted from the caller. A caller assembling it another way — the
        obvious mistake being one ``trace()`` call per incident, forgetting the
        rest are live — reintroduces the multi-incident composability defect the
        one-pass engine exists to prevent, and the assertion below only catches
        the subset of those that happen to push an account's own money negative.
        Removing the seam removes the mistake.

        ``through_seq`` names the last journal seq this seed accounts for, so
        the next :meth:`apply` must be handed ``through_seq + 1``. Left unset,
        that boundary is inferred as ``max(seq)`` over ``ledger.journals()`` —
        ``-1`` for an empty view, which is what makes the first ``apply`` on a
        never-seeded object expect seq 0. Pass it explicitly when the view you
        hand in may not literally contain every seq up to the boundary: a
        deliberately unobserved prefix, or a truncated view that is missing its
        own last journal. It must be an ``int`` and ``>= -1``; ``-1`` means
        there is no observed history before the first journal and the next
        ``apply`` accepts seq 0. Anything else — a value below ``-1``, a float,
        a bool, a string — raises before any state is touched, rather than
        silently corrupting the position.

        An account's own money is whatever its balance is not accounted for by
        some incident's claim. Reading the ledger here is deliberate and is the
        only place this class does it — :meth:`apply` must work from the journal
        it is handed and nothing else.
        """
        if through_seq is not None:
            # Validated before any mutation -- a bad through_seq must not leave
            # the object half-seeded with a corrupt _max_seq_seen.
            if isinstance(through_seq, bool) or not isinstance(through_seq, int):
                raise TypeError(
                    "through_seq must be an int or None, got "
                    f"{type(through_seq).__name__}"
                )
            if through_seq < -1:
                raise ValueError(f"through_seq must be >= -1, got {through_seq}")

        if customer_ids is not None:
            self._customers = set(customer_ids)

        journals = ledger.journals()
        derivations = trace_multi(
            journals, self._incidents, self.rule, accounts, through_seq=through_seq
        )
        if through_seq is not None:
            self._max_seq_seen = through_seq
        else:
            self._max_seq_seen = max((j.seq for j in journals), default=-1)
        self._first_seen = {}
        # Sort before ranking, exactly as trace_multi does. Without this,
        # _first_seen for a multi-origin incident would record the seq of
        # whichever origin journal ledger.journals() happened to return first,
        # not the true minimum -- inverting LIBR's oldest-first rank against
        # another incident. incident_rank_map takes the minimum; so must this.
        # Journals past through_seq are the streaming path's job, not the seed's.
        for journal in sorted(journals, key=lambda j: j.seq):
            if through_seq is not None and journal.seq > through_seq:
                break
            incident_id = self._origin_of.get(journal.id)
            if incident_id is not None and incident_id not in self._first_seen:
                self._first_seen[incident_id] = journal.seq

        self._state = {}
        self._left = {i: 0 for i in self._incident_ids}
        self._retagged = {i: 0 for i in self._incident_ids}
        self.coverage_gap = 0

        # through_seq defines ONE historical boundary for all seed state, not
        # just the trace: own-money must come from the same seq<=through_seq
        # view, never from ledger.balance()'s present-day answer.
        if through_seq is not None:
            scoped_balance: dict[str, int] = {}
            for journal in journals:
                if journal.seq > through_seq:
                    continue
                for entry in journal.entries:
                    scoped_balance[entry.account_id] = (
                        scoped_balance.get(entry.account_id, 0) + int(entry.amount_paise)
                    )

        for account_id in sorted(self._customers):
            buckets: dict[str | None, int] = {}
            tagged = 0
            for incident_id in self._ordered_incident_ids():
                derivation = derivations.get(incident_id)
                if derivation is None:
                    continue
                amount = int(derivation.claim_for(account_id))
                if amount > 0:
                    buckets[incident_id] = amount
                    tagged += amount
            if through_seq is not None:
                balance = scoped_balance.get(account_id, 0)
            else:
                balance = int(ledger.balance(account_id))
            own = balance - tagged
            if own > 0:
                buckets[None] = own
            elif own < 0:
                # Claims exceeding the balance would be C4 already broken. Do
                # not paper over it by clamping silently.
                raise AssertionError(
                    f"account {account_id}: claims total {tagged} against a "
                    f"balance of {tagged + own}"
                )
            if buckets:
                self._state[account_id] = buckets

        for incident_id, derivation in derivations.items():
            if incident_id in self._left:
                self._left[incident_id] = int(derivation.left_perimeter_paise)
                self._retagged[incident_id] = int(derivation.retagged_paise)

    # --------------------------------------------------------------- update

    def apply(self, journal: Journal) -> None:
        """Fold one posting into the state.

        Costs O(incidents on the touched accounts). Reads nothing but the
        journal it is given.

        The journal must be the immediate successor of the last one applied:
        ``seq`` exactly one greater. A fresh object expects ``seq == 0``; one
        seeded at cut ``N`` expects ``seq == N + 1``. Anything else -- a repeat,
        a gap, a step back -- raises :class:`OutOfOrderJournal` before any state
        is touched, because it would put this class out of step with the batch
        engine it exists to mirror.
        """
        expected = self._max_seq_seen + 1
        if journal.seq != expected:
            raise OutOfOrderJournal(
                f"expected journal seq {expected}, got {journal.seq}"
            )
        self._max_seq_seen = max(self._max_seq_seen, journal.seq)
        origin_incident = self._origin_of.get(journal.id)
        if origin_incident is not None and origin_incident not in self._first_seen:
            self._first_seen[origin_incident] = journal.seq

        debits = [e for e in journal.entries if e.amount_paise < 0]
        credits = [e for e in journal.entries if e.amount_paise > 0]

        # ---- what composition does each debit release? ----------------------
        released: dict[str | None, int] = {}
        for entry in debits:
            outflow = -int(entry.amount_paise)
            account_id = entry.account_id

            if account_id not in self._customers:
                # Outside the perimeter: an unbounded source of value we know
                # nothing about, so what it pays out is untagged by definition.
                released[None] = released.get(None, 0) + outflow
                continue

            buckets = self._state.setdefault(account_id, {})
            remaining = outflow
            for tag in self._consume_order():
                if remaining <= 0:
                    break
                held = buckets.get(tag, 0)
                if held <= 0:
                    continue
                take = held if held < remaining else remaining
                buckets[tag] = held - take
                if buckets[tag] == 0:
                    del buckets[tag]
                released[tag] = released.get(tag, 0) + take
                remaining -= take
            if remaining > 0:
                # The account spent more than the observed history gave it. The
                # batch engine calls this clean and so do we; the difference is
                # that here it is also counted, so nobody has to guess whether a
                # low number means "clean" or "we came in halfway".
                self.coverage_gap += remaining
                released[None] = released.get(None, 0) + remaining
            if not buckets:
                self._state.pop(account_id, None)

        released_total = sum(released.values())

        # ---- an origin journal creates its incident's value -----------------
        if origin_incident is not None:
            credited = sum(int(e.amount_paise) for e in credits)
            for tag, amount in released.items():
                if tag is not None and tag != origin_incident:
                    self._retagged[tag] += amount
            released = {origin_incident: credited}
            released_total = credited

        if released_total <= 0 or not credits:
            return

        # ---- distribute across the credited accounts ------------------------
        weights = [int(e.amount_paise) for e in credits]
        append_order = self._append_order()
        shares_by_tag = allocate_across_credits(released, weights, append_order)

        for position, entry in enumerate(credits):
            target = entry.account_id
            inside = target in self._customers
            for tag in append_order:
                shares = shares_by_tag.get(tag)
                if shares is None:
                    continue
                share = shares[position]
                if share <= 0:
                    continue
                if not inside:
                    if tag is not None:
                        # Left the perimeter. Record it and stop following it
                        # rather than inventing a path.
                        self._left[tag] += share
                    continue
                buckets = self._state.setdefault(target, {})
                buckets[tag] = buckets.get(tag, 0) + share

    def apply_all(self, journals: Iterable[Journal]) -> None:
        for journal in journals:
            self.apply(journal)

    # ---------------------------------------------------------------- reads

    def claim(self, account_id: str, incident_id: str) -> int:
        """How much of this account's balance is attributable to this incident."""
        return self._state.get(account_id, {}).get(incident_id, 0)

    def left_perimeter(self, incident_id: str) -> int:
        return self._left.get(incident_id, 0)

    def retagged(self, incident_id: str) -> int:
        return self._retagged.get(incident_id, 0)

    def own_money(self, account_id: str) -> int:
        return self._state.get(account_id, {}).get(None, 0)

    def total_claimed(self, account_id: str) -> int:
        """Every incident's claim on one account — the left side of C4."""
        return sum(
            amount
            for tag, amount in self._state.get(account_id, {}).items()
            if tag is not None
        )

    @property
    def state(self) -> LineageState:
        """The live state. Returned as-is; treat it as read-only."""
        return self._state

    def state_size(self) -> int:
        """Total entries held, for the cost numbers in the spec."""
        return sum(len(buckets) for buckets in self._state.values())
