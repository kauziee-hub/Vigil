"""TaintTrace — where did money from a confirmed scam go, and how much is still attributable?

Thin adapter over the vendored PRIMA lineage engine (`prima.attribution.trace`),
which is pure, deterministic and conservation-tested:

    claims + left_perimeter + retagged + extinguished == origin   (per incident, per rule)

We run two established tracing rules side by side and never collapse them:
  * LIBR  (Lowest Intermediate Balance Rule) — primary, used for policy floors
  * pro rata — shown for comparison
The amounts are "attributable under <rule>", never "the tainted money".

Runs only when a label is added (or on demand), then cached. RingWatch reads
`exposure()` from the cache; nothing re-traces per payment.
"""

from __future__ import annotations

import time
from collections import deque
from datetime import timezone
from typing import Any

from prima.attribution.rules import TracingRule
from prima.attribution.trace import Incident, ProvenanceGrade, trace_multi
from prima.ledger.models import Account, AccountKind, Journal, JournalKind, simple_transfer_entries

from vigil import clock, db

GENESIS = "0" * 64
RULES = (TracingRule.LIBR, TracingRule.PRO_RATA)
DE_MINIMIS_PAISE = 10_000  # ₹100: below this a split share is not tracked as its own parcel

_KIND = {
    "transfer": JournalKind.TRANSFER,
    "opening": JournalKind.EXTERNAL_CREDIT,
    "external_credit": JournalKind.EXTERNAL_CREDIT,
    "external_debit": JournalKind.EXTERNAL_DEBIT,
}

_cache: dict[str, Any] = {"key": None, "result": None}


def _labels() -> list[dict]:
    return db.q(
        "SELECT l.*, t.sender_id, t.recipient_id, t.amount_paise, t.ts AS tx_ts, t.seq "
        "FROM fraud_labels l JOIN transactions t ON t.id = l.transaction_id ORDER BY l.ts, l.id"
    )


def _cache_key() -> str:
    labels = db.scalar("SELECT COUNT(*) || ':' || COALESCE(MAX(id), '') FROM fraud_labels")
    seq = db.scalar("SELECT COALESCE(MAX(seq), -1) FROM transactions")
    return f"{labels}|{seq}"


def invalidate() -> None:
    _cache.clear()
    _cache.update(key=None, result=None)


def _labels_key() -> str:
    return str(db.scalar("SELECT COUNT(*) || ':' || COALESCE(MAX(id), '') FROM fraud_labels"))


def _closure(origin_ids: set[str]) -> tuple[set[str], int]:
    """Accounts that can hold value from the incidents: forward closure from the origin postings in seq order.

    Exact for attribution: traced value only ever moves along postings whose sender already holds it, so an
    account outside this closure never receives traced value and can be treated as outside the perimeter.
    """
    rows = db.q("SELECT id, seq, sender_id, recipient_id FROM transactions WHERE seq >= "
                "(SELECT MIN(seq) FROM transactions WHERE id IN (%s)) ORDER BY seq"
                % ",".join("?" * len(origin_ids)), tuple(origin_ids))
    reach: set[str] = set()
    for r in rows:
        if r["id"] in origin_ids or r["sender_id"] in reach:
            reach.add(r["recipient_id"])
    max_seq = int(db.scalar("SELECT COALESCE(MAX(seq), -1) FROM transactions"))
    return reach, max_seq


def run(force: bool = False) -> dict[str, Any]:
    key = _cache_key()
    if not force and _cache["key"] == key and _cache["result"] is not None:
        return _cache["result"]
    labels_key = _labels_key()
    cached = _cache.get("result")
    if not force and cached is not None and _cache.get("labels_key") == labels_key and _cache.get("reach") is not None:
        # incremental: new postings that touch no account in the closure cannot change any attribution
        reach = _cache["reach"]
        new_rows = db.q("SELECT sender_id, recipient_id FROM transactions WHERE seq > ?", (_cache["through_seq"],))
        if not any(r["sender_id"] in reach or r["recipient_id"] in reach for r in new_rows):
            _cache.update(key=key, through_seq=int(db.scalar("SELECT COALESCE(MAX(seq), -1) FROM transactions")))
            return cached
    started = time.perf_counter()
    labels = _labels()
    if not labels:
        result = {"incidents": [], "exposure": {}, "hops": {}, "computed_ms": 0.0, "through_seq": None}
        _cache.update(key=key, result=result, labels_key=labels_key, reach=None)
        return result

    origin_ids = {label["transaction_id"] for label in labels}
    reach, max_seq = _closure(origin_ids)
    # perimeter = the closure; everyone else is "external" (never holds traced value; see _closure)
    accounts = {
        row["id"]: Account(
            id=row["id"],
            kind=AccountKind.CUSTOMER if row["kind"] == "customer" and row["id"] in reach else AccountKind.EXTERNAL,
            display_name=row["display_name"],
        )
        for row in db.q("SELECT id, kind, display_name FROM accounts")
    }
    marks = ",".join("?" * len(reach))
    journal_rows = db.q(
        "SELECT id, seq, kind, sender_id, recipient_id, amount_paise, ts FROM transactions "
        f"WHERE sender_id IN ({marks}) OR recipient_id IN ({marks}) OR id IN ({','.join('?' * len(origin_ids))}) "
        "ORDER BY seq", (*reach, *reach, *origin_ids))
    journals: list[Journal] = []
    for row in journal_rows:
        journals.append(
            Journal(
                id=row["id"],
                kind=_KIND.get(row["kind"], JournalKind.TRANSFER),
                entries=simple_transfer_entries(row["sender_id"], row["recipient_id"], int(row["amount_paise"])),
                occurred_at=clock.parse(row["ts"]).astimezone(timezone.utc),
                seq=int(row["seq"]),
                prev_hash=GENESIS,
            )
        )
    incidents = [
        Incident(
            id=label["id"],
            origin_journal_ids=frozenset({label["transaction_id"]}),
            reported_at=clock.parse(label["ts"]),
            grade=ProvenanceGrade.BANK_CONFIRMED if label["grade"] == "bank_confirmed"
            else ProvenanceGrade.REPORTED_UNVERIFIED,
            reporter_ref=label["labelled_by"],
        )
        for label in labels
    ]
    by_rule = {
        rule: trace_multi(journals, incidents, rule, accounts, de_minimis_floor=DE_MINIMIS_PAISE)
        for rule in RULES
    }

    exposure: dict[str, int] = {}
    hops: dict[str, int] = {}
    incident_out: list[dict[str, Any]] = []
    for label in labels:
        per_rule: dict[str, Any] = {}
        for rule in RULES:
            d = by_rule[rule][label["id"]]
            payload = d.payload()
            per_rule[rule.value] = {
                "origin_paise": payload["origin_paise"],
                "attributable_total_paise": payload["attributable_total_paise"],
                "left_perimeter_paise": payload["left_perimeter_paise"],
                "spent_paise": payload["spent_paise"],
                "retagged_paise": payload["retagged_paise"],
                "extinguished_paise": payload["extinguished_paise"],
                "coverage": round(d.coverage, 4),
                "claims": [c for c in payload["claims"] if c["amount_paise"] > 0],
                "steps": payload["steps"],
                "digest": d.digest,
                # C1: still-attributable + left-perimeter never exceeds the origin;
                # "spent" is the remainder no longer attributable for any reason.
                "conserved": (
                    payload["attributable_total_paise"] + payload["left_perimeter_paise"]
                    + payload["spent_paise"]
                ) == payload["origin_paise"],
            }
        libr = per_rule[TracingRule.LIBR.value]
        for claim in libr["claims"]:
            exposure[claim["account_id"]] = exposure.get(claim["account_id"], 0) + int(claim["amount_paise"])
        label_hops = _hops(label["recipient_id"], libr["steps"])
        for account, hop in label_hops.items():
            hops[account] = min(hop, hops.get(account, hop))
        hops.setdefault(label["sender_id"], 0)
        incident_out.append({
            "label_id": label["id"],
            "transaction_id": label["transaction_id"],
            "source_account": label["sender_id"],
            "first_recipient": label["recipient_id"],
            "origin_paise": int(label["amount_paise"]),
            "grade": label["grade"],
            "labelled_at": label["ts"],
            "rules": per_rule,
            "hops": label_hops,
        })

    result = {
        "incidents": incident_out,
        "exposure": exposure,
        "hops": hops,
        "computed_ms": round((time.perf_counter() - started) * 1000, 2),
        "through_seq": max_seq,
        "journals_considered": len(journals),
        "perimeter_accounts": len(reach),
    }
    _cache.update(key=key, result=result, labels_key=labels_key, reach=reach, through_seq=max_seq)
    return result


def _hops(first_recipient: str, steps: list[dict]) -> dict[str, int]:
    """Hop number of each account reached by traced value (first recipient = hop 1)."""
    children: dict[str, set[str]] = {}
    for step in steps:
        if step["traced_paise"] > 0:
            children.setdefault(step["from_account"], set()).add(step["to_account"])
    hop = {first_recipient: 1}
    queue = deque([first_recipient])
    while queue:
        node = queue.popleft()
        for child in sorted(children.get(node, ())):
            if child not in hop:
                hop[child] = hop[node] + 1
                queue.append(child)
    return hop


def exposure() -> dict[str, int]:
    """LIBR-attributable paise per account from the latest run (cached)."""
    return run()["exposure"]


def summary_for(account_id: str) -> dict[str, Any] | None:
    result = run()
    amount = result["exposure"].get(account_id, 0)
    if not amount and account_id not in result["hops"]:
        return None
    return {"attributable_paise": amount, "hop": result["hops"].get(account_id)}
