"""The trace engine.

A pure function from (journal log, incident, rule) to a derivation. No I/O, no
clock, no randomness, no database. Given the same inputs it produces
byte-identical output on any machine, this year or in four years when somebody
asks how a number was arrived at. That property is not a nicety — the output of
this function is intended to end up in front of a person disputing a restraint
on their own money, and possibly in front of a court.

The model is parcels. Every account's balance is a list of parcels of value,
each tagged with where it came from. An outflow consumes parcels according to
the tracing rule and re-creates them on the receiving account. Value is never
duplicated, only split and moved, so the conservation property

    sum of every traced parcel still inside the perimeter
      + traced value that has left the perimeter
      = the origin amount

holds by construction rather than by careful arithmetic. That is the whole
reason for choosing parcels over a per-transaction "taint ratio": a ratio has
to be *kept* consistent, a parcel *is* consistent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable, Mapping, Sequence

from prima.attribution.rules import TracingRule, consumption_plan
from prima.ledger.models import Account, AccountKind, Journal, canonical_json
from prima.money import Paise, split_proportionally

__all__ = [
    "ProvenanceGrade",
    "Incident",
    "Claim",
    "Derivation",
    "TraceStep",
    "trace",
    "trace_multi",
    "trace_envelope",
    "allocate_across_credits",
    "incident_rank_map",
    "UNTAGGED_RANK",
]

# Rank 0 is the account holder's own money. Tagged parcels take ranks 1..n in
# the global incident order. LIBR consumes in ascending rank: own money first,
# then the oldest incident, then the next. See 04-VALUE-LINEAGE-SPEC.md §5.3.
UNTAGGED_RANK = 0


class ProvenanceGrade(str, Enum):
    """How much is actually known about the origin report.

    This never changes the computed amount. It governs what may be *done* with
    it — an unverified report can justify a notice and a small ceiling; it must
    not justify restraining someone's rent money. Keeping the grade out of the
    arithmetic is deliberate: multiplying a traced amount by a confidence
    number produces a figure that is neither the traced amount nor a
    probability, and is useless in both a bank's workflow and a courtroom.
    """

    REPORTED_UNVERIFIED = "reported_unverified"
    BANK_CONFIRMED = "bank_confirmed"
    ADJUDICATED = "adjudicated"


@dataclass(frozen=True, slots=True)
class Incident:
    """A reported fraud, anchored to the journals where the value moved."""

    id: str
    origin_journal_ids: frozenset[str]
    reported_at: datetime
    grade: ProvenanceGrade = ProvenanceGrade.REPORTED_UNVERIFIED
    reporter_ref: str = ""

    def __post_init__(self) -> None:
        if not self.origin_journal_ids:
            raise ValueError("an incident must name at least one origin journal")
        object.__setattr__(self, "origin_journal_ids", frozenset(self.origin_journal_ids))


@dataclass(frozen=True, slots=True)
class TraceStep:
    """One movement of traced value, for the derivation a person can read."""

    journal_id: str
    journal_seq: int
    occurred_at: str
    from_account: str
    to_account: str
    moved_paise: int
    traced_paise: int
    left_perimeter: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "journal_id": self.journal_id,
            "journal_seq": self.journal_seq,
            "occurred_at": self.occurred_at,
            "from_account": self.from_account,
            "to_account": self.to_account,
            "moved_paise": self.moved_paise,
            "traced_paise": self.traced_paise,
            "left_perimeter": self.left_perimeter,
        }


@dataclass(frozen=True, slots=True)
class Claim:
    """How much of one account's balance is attributable to one incident."""

    account_id: str
    amount_paise: Paise
    rule: TracingRule
    incident_id: str

    def as_dict(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "amount_paise": int(self.amount_paise),
            "rule": self.rule.value,
            "incident_id": self.incident_id,
        }


@dataclass(frozen=True, slots=True)
class Derivation:
    """The complete, reproducible record of one trace."""

    incident_id: str
    rule: TracingRule
    origin_paise: Paise
    claims: tuple[Claim, ...]
    steps: tuple[TraceStep, ...]
    left_perimeter_paise: Paise
    spent_paise: Paise
    journals_considered: int
    position_through_seq: int
    # Value of *this* incident that a later incident's origin journal claimed
    # as its own (spec §5.3 rule 3). It is not attributable to this incident any
    # more, but it did not vanish either, and saying so is the difference
    # between an explainable number and a hole in one.
    retagged_paise: Paise = Paise(0)
    # Value of *this* incident that a split drove below the de-minimis floor
    # (spec §6.2). It is still traced value — it is not the account holder's
    # own money and must never be folded into "clean" — but it is below the
    # amount worth tracking as its own parcel, so it is counted here and not
    # followed further. This is what bounds the trace's cardinality against an
    # adversary who picks the split depth. Zero unless a floor was supplied.
    extinguished_paise: Paise = Paise(0)

    @property
    def attributable_total(self) -> Paise:
        return Paise(sum(int(c.amount_paise) for c in self.claims))

    def claim_for(self, account_id: str) -> Paise:
        for claim in self.claims:
            if claim.account_id == account_id:
                return claim.amount_paise
        return Paise(0)

    @property
    def coverage(self) -> float:
        """Fraction of the origin amount still inside the observed perimeter.

        Reported with every derivation. A number without its coverage invites
        the reader to assume the trace saw everything, which it usually did not.
        """
        if int(self.origin_paise) == 0:
            return 0.0
        return int(self.attributable_total) / int(self.origin_paise)

    def payload(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "rule": self.rule.value,
            "origin_paise": int(self.origin_paise),
            "attributable_total_paise": int(self.attributable_total),
            "left_perimeter_paise": int(self.left_perimeter_paise),
            "spent_paise": int(self.spent_paise),
            "retagged_paise": int(self.retagged_paise),
            "extinguished_paise": int(self.extinguished_paise),
            "claims": [c.as_dict() for c in sorted(self.claims, key=lambda c: c.account_id)],
            "steps": [s.as_dict() for s in self.steps],
            "journals_considered": self.journals_considered,
            "position_through_seq": self.position_through_seq,
        }

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical payload.

        This is an integrity check, not a signature. It proves the derivation
        has not been altered since it was computed by someone who also has the
        payload; it proves nothing about who computed it. Do not describe it as
        a signature anywhere.
        """
        return hashlib.sha256(canonical_json(self.payload()).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class _Parcel:
    """A parcel of value sitting in an account.

    ``incident_id`` is the single tag it carries — ``None`` for the account
    holder's own money. A parcel never carries two tags: value is created by one
    inflow and has one origin (spec §5.3 rule 1).
    """

    amount: int
    incident_id: str | None
    seq: int  # journal seq at which this parcel arrived, for FIFO/LIFO ordering


def incident_rank_map(
    journals: Sequence[Journal], incidents: Sequence[Incident]
) -> dict[str, int]:
    """The global consumption order over incidents (spec §5.3 rule 2).

    Rank 1 is the oldest incident — the one whose earliest origin journal has
    the lowest sequence number. Ties break on the incident id, so the order is
    total and reproducible whatever order the caller happened to pass them in.
    Rank 0 is reserved for untagged value and is not handed out here.

    An incident whose origin journals all fall outside the window sorts last. It
    can hold no parcels there, so its position cannot change any arithmetic, but
    it still needs a defined one.
    """
    seq_by_journal = {j.id: j.seq for j in journals}
    unseen = max((j.seq for j in journals), default=-1) + 1

    def first_seen(incident: Incident) -> int:
        seen = [
            seq_by_journal[journal_id]
            for journal_id in incident.origin_journal_ids
            if journal_id in seq_by_journal
        ]
        return min(seen) if seen else unseen

    ordered = sorted(incidents, key=lambda i: (first_seen(i), i.id))
    return {incident.id: rank for rank, incident in enumerate(ordered, start=1)}


def _consumption_plan_multi(
    bucket: Sequence[_Parcel],
    outflow: int,
    rule: TracingRule,
    rank_of: Mapping[str, int],
) -> list[int]:
    """How much of ``outflow`` each parcel supplies, with any number of tags.

    Only LIBR reads the tags at all. Pro rata, FIFO and LIFO order by size or by
    arrival and are unchanged by how many incidents are live, so they delegate
    straight to :func:`consumption_plan` — there stays exactly one
    implementation of each rule.

    For LIBR the order *generalises* the single-incident one rather than
    replacing it. With one incident the key ``(rank, seq, index)`` takes the
    values ``(0 or 1, seq, index)``, which is precisely the
    ``(is_traced, seq, index)`` the single-incident engine used, because
    ``False == 0`` and ``True == 1``. One incident therefore yields
    byte-identical output before and after this change.
    """
    amounts = [p.amount for p in bucket]
    seqs = [p.seq for p in bucket]
    if rule is not TracingRule.LIBR:
        tagged = [p.incident_id is not None for p in bucket]
        return consumption_plan(amounts, tagged, seqs, outflow, rule)

    count = len(bucket)
    taken = [0] * count
    if outflow == 0 or count == 0:
        return taken
    available = sum(amounts)
    if outflow > available:
        raise ValueError(f"outflow {outflow} exceeds available parcels {available}")

    def rank(index: int) -> int:
        tag = bucket[index].incident_id
        return UNTAGGED_RANK if tag is None else rank_of[tag]

    remaining = outflow
    for index in sorted(range(count), key=lambda i: (rank(i), seqs[i], i)):
        if remaining <= 0:
            break
        give = min(amounts[index], remaining)
        taken[index] = give
        remaining -= give
    if remaining != 0:  # pragma: no cover - unreachable given the check above
        raise AssertionError("consumption plan did not place the whole outflow")
    return taken


def allocate_across_credits(
    released: Mapping[str | None, int],
    credit_weights: Sequence[int],
    order: Sequence[str | None],
) -> dict[str | None, list[int]]:
    """Spread a released composition over the credited entries.

    Two margins have to come out exact, and they pull against each other:

    * every tag's shares must sum to the amount released of that tag, or value
      is created or destroyed;
    * every credit's shares must sum to the amount actually credited, or an
      account ends up holding parcels that do not add up to its balance.

    Splitting each tag independently over the credit amounts — which is what the
    single-incident engine did — gets the first right and the second wrong. Two
    largest-remainder splits over the same weights can both hand their leftover
    paise to the same credit, so that credit receives one paisa more than it was
    actually paid and another receives one less. With a single incident only the
    tagged parcels are claimable, so the discrepancy sat harmlessly in the clean
    parcels and never surfaced. With two, both are claimable, and the account is
    claimed for a paisa more than it holds. That is C4, failing by one.

    So each tag is split over the *remaining capacity* of each credit rather
    than over its full amount. The first tag in ``order`` is still split over the
    credit amounts exactly as before; later tags fill what is left. Both margins
    close, and no share can exceed the capacity it was drawn from because the
    amounts and the capacities always have the same total.
    """
    capacity = [int(w) for w in credit_weights]
    shares: dict[str | None, list[int]] = {}
    for tag in order:
        amount = int(released.get(tag, 0))
        if amount <= 0:
            continue
        allocation = [int(s) for s in split_proportionally(amount, capacity)]
        shares[tag] = allocation
        capacity = [c - a for c, a in zip(capacity, allocation)]
    return shares


def trace_multi(
    journals: Sequence[Journal],
    incidents: Sequence[Incident],
    rule: TracingRule,
    accounts: Mapping[str, Account] | None = None,
    through_seq: int | None = None,
    *,
    de_minimis_floor: int | None = None,
) -> dict[str, Derivation]:
    """Trace every live incident in one pass, keyed by incident id.

    Running one trace per incident and merging the results does not work, and
    the failure is not subtle: each single-incident trace sees the other
    incident's value as the account holder's own money, and under LIBR presumes
    it was spent first. Both traces then claim the same rupees. One pass over
    one pool of parcels, with one tag each and one global consumption order, is
    what makes C4 (``Σ over incidents claim ≤ balance``) true by construction
    rather than by hoping.

    ``accounts`` tells the engine which accounts are inside the perimeter;
    anything unknown is treated as external, which is the safe default — it
    means the trace reports the value as having left rather than silently
    following it somewhere it cannot see.

    ``de_minimis_floor`` (spec §6.2) bounds the trace's *cardinality*. Without
    it an adversary who chooses the split depth grows the parcel list without
    bound — 2^depth leaves at branching factor 2. With a floor F, any share a
    split would credit to a customer account that comes out below F is not
    tracked as its own parcel; its value is added to that incident's
    ``extinguished_paise`` instead. An origin of value V can then produce at
    most ``V // F`` tracked parcels, whatever depth the adversary picks,
    because splitting divides value. Left unset, no parcel is ever extinguished
    and every existing result is reproduced byte for byte.
    """
    accounts = accounts or {}
    incident_list = list(incidents)
    if not incident_list:
        return {}
    ids = [incident.id for incident in incident_list]
    if len(set(ids)) != len(ids):
        raise ValueError("incident ids must be unique within one trace")
    if de_minimis_floor is not None:
        if isinstance(de_minimis_floor, bool) or not isinstance(de_minimis_floor, int):
            raise TypeError(
                "de_minimis_floor must be a positive int or None, got "
                f"{type(de_minimis_floor).__name__}"
            )
        if de_minimis_floor < 1:
            raise ValueError(
                f"de_minimis_floor must be >= 1, got {de_minimis_floor}"
            )

    ordered = sorted(journals, key=lambda j: j.seq)
    if through_seq is not None:
        ordered = [j for j in ordered if j.seq <= through_seq]

    rank_of = incident_rank_map(ordered, incident_list)
    # Parcels are appended traced-first, own-money-last, matching the order the
    # single-incident engine used. It matters: FIFO and LIFO break ties on the
    # position in the bucket, so reversing this would silently change them.
    append_order: list[str | None] = sorted(rank_of, key=lambda i: rank_of[i]) + [None]

    origin_of: dict[str, str] = {}
    for incident in incident_list:
        for journal_id in incident.origin_journal_ids:
            claimed_by = origin_of.get(journal_id)
            if claimed_by is not None and claimed_by != incident.id:
                # Two reports naming the same movement as their own origin is a
                # contradiction in the input, not a case with a right answer.
                # Refuse rather than invent one. See the report's assumptions.
                raise ValueError(
                    f"journal {journal_id} is named as the origin of both "
                    f"{claimed_by} and {incident.id}; an origin belongs to one incident"
                )
            origin_of[journal_id] = incident.id

    parcels: dict[str, list[_Parcel]] = {}
    steps: dict[str, list[TraceStep]] = {i: [] for i in ids}
    origin_total: dict[str, int] = {i: 0 for i in ids}
    left_perimeter: dict[str, int] = {i: 0 for i in ids}
    retagged: dict[str, int] = {i: 0 for i in ids}
    extinguished: dict[str, int] = {i: 0 for i in ids}

    def is_customer(account_id: str) -> bool:
        account = accounts.get(account_id)
        return account is not None and account.kind is AccountKind.CUSTOMER

    for journal in ordered:
        debits = [e for e in journal.entries if e.amount_paise < 0]
        credits = [e for e in journal.entries if e.amount_paise > 0]
        origin_incident = origin_of.get(journal.id)

        # ---- what composition of value does each debit release? -------------
        released: dict[str | None, int] = {}
        for entry in debits:
            outflow = -int(entry.amount_paise)
            account_id = entry.account_id
            bucket = parcels.setdefault(account_id, [])
            held = sum(p.amount for p in bucket)

            if held < outflow:
                # Either an external account (an unbounded source of
                # unattributed money) or a stretch of history we did not
                # observe. Either way the shortfall is clean by definition.
                bucket.append(_Parcel(amount=outflow - held, incident_id=None, seq=journal.seq))

            plan = _consumption_plan_multi(bucket, outflow, rule, rank_of)
            for parcel, take in zip(bucket, plan):
                if take == 0:
                    continue
                parcel.amount -= take
                released[parcel.incident_id] = released.get(parcel.incident_id, 0) + take
            parcels[account_id] = [p for p in bucket if p.amount > 0]

        released_total = sum(released.values())

        # ---- an origin journal *creates* its incident's value ---------------
        if origin_incident is not None:
            credited = sum(int(e.amount_paise) for e in credits)
            origin_total[origin_incident] += credited
            # Rule 3: the later report asserts this movement was fraudulent and
            # that assertion governs. Whatever the outflow was carrying for an
            # earlier incident is displaced — and is said so, not dropped.
            for tag, amount in released.items():
                if tag is not None and tag != origin_incident:
                    retagged[tag] += amount
            released = {origin_incident: credited}
            released_total = credited

        # ---- distribute what was released across the credited accounts ------
        if released_total > 0 and credits:
            credit_weights = [int(e.amount_paise) for e in credits]
            shares_by_tag = allocate_across_credits(
                released, credit_weights, append_order
            )

            for position, entry in enumerate(credits):
                target = entry.account_id
                bucket = parcels.setdefault(target, [])
                inside = is_customer(target)

                for tag in append_order:
                    shares = shares_by_tag.get(tag)
                    if shares is None:
                        continue
                    share = int(shares[position])
                    if share <= 0:
                        continue

                    if tag is None:
                        if inside:
                            bucket.append(
                                _Parcel(amount=share, incident_id=None, seq=journal.seq)
                            )
                        continue

                    if inside:
                        if de_minimis_floor is not None and share < de_minimis_floor:
                            # Below the reporting floor: still this incident's
                            # traced value (never folded into own money), just
                            # not worth a parcel. Count it and stop following
                            # it — this is what bounds the cardinality.
                            extinguished[tag] += share
                            continue
                        bucket.append(
                            _Parcel(amount=share, incident_id=tag, seq=journal.seq)
                        )
                    else:
                        # Value crossed out of the perimeter. Record it and stop
                        # following it rather than inventing a path.
                        left_perimeter[tag] += share

                    source = debits[0].account_id if debits else ""
                    steps[tag].append(
                        TraceStep(
                            journal_id=journal.id,
                            journal_seq=journal.seq,
                            occurred_at=journal.occurred_at.isoformat(),
                            from_account=source,
                            to_account=target,
                            moved_paise=int(entry.amount_paise),
                            traced_paise=share,
                            left_perimeter=not inside,
                        )
                    )

    derivations: dict[str, Derivation] = {}
    for incident in incident_list:
        incident_id = incident.id
        claims: list[Claim] = []
        for account_id, bucket in sorted(parcels.items()):
            if not is_customer(account_id):
                continue
            held = sum(p.amount for p in bucket if p.incident_id == incident_id)
            if held > 0:
                claims.append(
                    Claim(
                        account_id=account_id,
                        amount_paise=Paise(held),
                        rule=rule,
                        incident_id=incident_id,
                    )
                )
        attributable = sum(int(c.amount_paise) for c in claims)
        # spent_paise keeps its existing meaning and its existing formula:
        # "no longer attributable to this incident, for any reason". Extinguished
        # value is no longer attributable and did not leave the perimeter, so it
        # lands in spent — exactly as retagged value does (spec §5.3.3).
        # extinguished_paise is reported alongside so a reader can tell the two
        # apart. When no floor is given, extinguished is 0 and spent is
        # byte-identical to today.
        spent = (
            origin_total[incident_id] - attributable - left_perimeter[incident_id]
        )
        derivations[incident_id] = Derivation(
            incident_id=incident_id,
            rule=rule,
            origin_paise=Paise(origin_total[incident_id]),
            claims=tuple(claims),
            steps=tuple(steps[incident_id]),
            left_perimeter_paise=Paise(left_perimeter[incident_id]),
            spent_paise=Paise(max(0, spent)),
            journals_considered=len(ordered),
            position_through_seq=ordered[-1].seq if ordered else -1,
            retagged_paise=Paise(retagged[incident_id]),
            extinguished_paise=Paise(extinguished[incident_id]),
        )
    return derivations


def trace(
    journals: Sequence[Journal],
    incidents: Incident | Sequence[Incident],
    rule: TracingRule,
    accounts: Mapping[str, Account] | None = None,
    through_seq: int | None = None,
    *,
    other_live_incidents: Sequence[Incident] = (),
    de_minimis_floor: int | None = None,
) -> Derivation | dict[str, Derivation]:
    """Compute where reported value ended up, under one tracing rule.

    Pass a sequence of incidents to get ``{incident_id: Derivation}``; pass one
    ``Incident`` to get its ``Derivation`` directly. The single-incident call is
    the one-element case of the same engine, not a separate code path, so the
    two can never drift apart.

    ``other_live_incidents`` is how a caller asking about one incident names the
    others that are also live. It matters more than it looks. From inside
    :func:`trace_multi` a list of one incident is indistinguishable from "this is
    the only incident there is", so any other live incident sharing an account
    would be treated as the account holder's own clean money — and under LIBR
    presumed spent first. Two such calls then claim the same rupees, which is
    precisely the defect the one-pass engine exists to prevent, reintroduced at
    the call site. Naming the others routes the call through the same one pass
    with the complete set, and C4 holds again.

    Leaving it empty is the old behaviour exactly: the call becomes
    ``trace_multi(journals, [incidents], ...)``, byte for byte. That is correct
    when the incident really is the only live one, and wrong — silently — when it
    is not. The engine cannot tell the difference; only the caller can.

    ``de_minimis_floor`` is threaded straight through to :func:`trace_multi` —
    see its docstring.

    ``journals`` must be the ordered log.
    """
    if isinstance(incidents, Incident):
        return trace_multi(
            journals,
            [incidents, *other_live_incidents],
            rule,
            accounts,
            through_seq,
            de_minimis_floor=de_minimis_floor,
        )[incidents.id]
    if other_live_incidents:
        # A sequence is already the complete set. Merging the two lists would
        # guess at what the caller meant, and ignoring one of them would answer
        # a different question than the one asked. Neither is safe here.
        raise ValueError(
            "other_live_incidents applies only when tracing a single Incident; "
            "when passing a sequence, include every live incident in it"
        )
    return trace_multi(
        journals, incidents, rule, accounts, through_seq,
        de_minimis_floor=de_minimis_floor,
    )


def trace_envelope(
    journals: Sequence[Journal],
    incident: Incident,
    rules: Iterable[TracingRule],
    accounts: Mapping[str, Account] | None = None,
    through_seq: int | None = None,
    *,
    other_live_incidents: Sequence[Incident] = (),
    de_minimis_floor: int | None = None,
) -> dict[TracingRule, Derivation]:
    """Run several rules over the same facts.

    This is the output the product actually reports. A single number would be
    an assertion about which legal rule governs — a question the engine has no
    standing to answer. The range, with each rule named, lets the bank apply
    its own policy and lets a forum apply its own law.

    ``other_live_incidents`` carries the same meaning and the same warning as in
    :func:`trace`: name every other incident that is live over these accounts, or
    the envelope is computed as though this were the only one and can overclaim.
    """
    return {
        rule: trace(
            journals,
            incident,
            rule,
            accounts,
            through_seq,
            other_live_incidents=other_live_incidents,
            de_minimis_floor=de_minimis_floor,
        )
        for rule in rules
    }
