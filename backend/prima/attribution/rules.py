"""Tracing rules.

When money from a reported fraud is mixed with a person's own money, there is
no fact of the matter about which rupees left the account — only a *rule* for
deciding. Courts have several, they disagree, and which one applies is a legal
question, not an engineering one.

So PRIMA does not pick. It implements the established rules as different
consumption orders over the same parcels of value, runs them side by side, and
reports the range. The forum chooses the rule; the engine shows what each one
yields and how it got there.

Every rule here is a *consumption order* — given an outflow, which parcels of
the account's balance does it draw on?

``LIBR``
    Lowest Intermediate Balance Rule. Presumes the account holder spends their
    own money before the traced money, so untainted parcels are consumed first
    and the traced claim survives as long as the balance allows. When the
    balance falls below the traced amount, the shortfall is treated as spent
    and — importantly — later deposits do **not** replenish it. This is the
    most common rule in the tracing case law and the most favourable to a
    victim, so it is the default for reporting the upper bound.

``PRO_RATA``
    Every outflow draws on all parcels in proportion to their size. Favoured
    where many victims have equal claims on one commingled pool, which is why
    it is the usual rule in Ponzi-scheme distributions.

``FIFO``
    First in, first out. The rule in *Clayton's Case*; still applied in some
    jurisdictions, increasingly disfavoured because it is arbitrary about
    facts nobody observed.

``LIFO``
    Last in, first out. Included because some courts use it as an alternative
    to LIBR, and because reporting it costs nothing once the machinery exists.

None of this is novel and it should never be described as such. The rules are
centuries old. What is unbuilt is running them over live inter-bank payment
data and producing a per-account amount somebody can contest.
"""

from __future__ import annotations

from enum import Enum
from typing import Sequence

from prima.money import Paise, split_proportionally

__all__ = ["TracingRule", "consumption_plan", "DEFAULT_RULES"]


class TracingRule(str, Enum):
    LIBR = "libr"
    PRO_RATA = "pro_rata"
    FIFO = "fifo"
    LIFO = "lifo"

    @property
    def label(self) -> str:
        return {
            TracingRule.LIBR: "Lowest Intermediate Balance Rule",
            TracingRule.PRO_RATA: "Pro rata",
            TracingRule.FIFO: "First in, first out",
            TracingRule.LIFO: "Last in, first out",
        }[self]

    @property
    def plain_english(self) -> str:
        """One sentence a non-lawyer can check, for the customer notice."""
        return {
            TracingRule.LIBR: (
                "assumes you spent your own money first, so the reported money "
                "is treated as still in the account for as long as the balance allowed"
            ),
            TracingRule.PRO_RATA: (
                "treats every payment out as drawing on all the money in the "
                "account in proportion"
            ),
            TracingRule.FIFO: "assumes money is spent in the order it arrived",
            TracingRule.LIFO: "assumes the most recently arrived money is spent first",
        }[self]


DEFAULT_RULES: tuple[TracingRule, ...] = (
    TracingRule.LIBR,
    TracingRule.PRO_RATA,
    TracingRule.FIFO,
)


def consumption_plan(
    parcel_amounts: Sequence[int],
    parcel_is_traced: Sequence[bool],
    parcel_seq: Sequence[int],
    outflow: int,
    rule: TracingRule,
) -> list[int]:
    """Decide how much of ``outflow`` each parcel supplies, under ``rule``.

    Returns a list the same length as ``parcel_amounts``. The result always
    sums to exactly ``outflow`` (given sufficient parcels) and never takes more
    from a parcel than it holds — the two properties that make attribution
    conserve value no matter how the money is split or merged.
    """
    if outflow < 0:
        raise ValueError("outflow must not be negative")
    count = len(parcel_amounts)
    if not (count == len(parcel_is_traced) == len(parcel_seq)):
        raise ValueError("parcel arrays must be the same length")
    taken = [0] * count
    if outflow == 0 or count == 0:
        return taken

    available = sum(parcel_amounts)
    if outflow > available:
        raise ValueError(
            f"outflow {outflow} exceeds available parcels {available}"
        )

    if rule is TracingRule.PRO_RATA:
        # Every parcel contributes in proportion. split_proportionally
        # guarantees the shares sum exactly to the outflow.
        shares = split_proportionally(outflow, [int(a) for a in parcel_amounts])
        # A share can exceed its parcel only through rounding at the margin;
        # clamp and redistribute the excess to parcels with room.
        taken = [min(int(s), int(a)) for s, a in zip(shares, parcel_amounts)]
        shortfall = outflow - sum(taken)
        index = 0
        while shortfall > 0 and index < count:
            room = int(parcel_amounts[index]) - taken[index]
            if room > 0:
                give = min(room, shortfall)
                taken[index] += give
                shortfall -= give
            index += 1
        if shortfall > 0:  # pragma: no cover - unreachable given the check above
            raise AssertionError("pro rata could not place the whole outflow")
        return taken

    # The remaining rules are all "consume in some order".
    if rule is TracingRule.LIBR:
        # Untainted first (the account holder spends their own money first),
        # then traced parcels oldest-first so the answer is deterministic.
        order = sorted(
            range(count), key=lambda i: (parcel_is_traced[i], parcel_seq[i], i)
        )
    elif rule is TracingRule.FIFO:
        order = sorted(range(count), key=lambda i: (parcel_seq[i], i))
    elif rule is TracingRule.LIFO:
        order = sorted(range(count), key=lambda i: (-parcel_seq[i], i))
    else:  # pragma: no cover - exhaustive
        raise ValueError(f"unhandled rule: {rule}")

    remaining = outflow
    for index in order:
        if remaining <= 0:
            break
        give = min(int(parcel_amounts[index]), remaining)
        taken[index] = give
        remaining -= give
    if remaining != 0:  # pragma: no cover - unreachable given the check above
        raise AssertionError("consumption plan did not place the whole outflow")
    return taken
