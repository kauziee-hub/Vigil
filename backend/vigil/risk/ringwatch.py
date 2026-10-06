"""RingWatch — network evidence about an account (usually the payment recipient).

Cleaned-up successor of the ccmule rule set. Differences that matter:
  * every rule is time-windowed (no more "in_degree >= 2 ever");
  * every rule returns rule_id, a plain reason, raw evidence and a contribution;
  * it reads the incremental PathGraph — no per-request graph rebuild;
  * it reads confirmed fraud labels and TaintTrace exposure, which is how
    post-payment learning flows back into the next pre-payment decision.
No ML model is consulted (see docs/MODEL_CARD.md).
"""

from __future__ import annotations

from typing import Any

from vigil import clock, db
from vigil.contracts import RiskSignal
from vigil.graph.pathgraph import GRAPH
from vigil.risk import taint
from vigil.settings import get_policy

DAY = 86400.0


def _rupees(paise: int) -> str:
    rupees = paise // 100
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"₹{s}"


def labelled_accounts() -> dict[str, str]:
    """First recipients of confirmed/reported scam transactions → label id."""
    rows = db.q(
        "SELECT l.id, t.recipient_id FROM fraud_labels l JOIN transactions t ON t.id = l.transaction_id"
    )
    return {row["recipient_id"]: row["id"] for row in rows}


def _sig(rule_id: str, label: str, reason: str, evidence: dict[str, Any], contribution: float) -> RiskSignal:
    return RiskSignal(rule_id=rule_id, dimension="network", label=label, reason=reason,
                      evidence=evidence, contribution=float(contribution))


def features(account_id: str, now_t: float | None = None) -> dict[str, Any]:
    cfg = get_policy()["network"]
    now_t = now_t if now_t is not None else clock.now().timestamp()
    since = now_t - float(cfg["window_hours"]) * 3600
    inflows = GRAPH.inflows(account_id, since)
    outflows = GRAPH.outflows(account_id, since)
    total_in = sum(e.amount_paise for e in inflows)
    total_out = sum(e.amount_paise for e in outflows)

    # forwarded quickly: outflow value leaving within N minutes after an inflow
    pt_window = float(cfg["pass_through"]["max_minutes"]) * 60
    in_times = sorted(e.t for e in inflows)
    quick_out = 0
    quick_minutes: list[float] = []
    for out in outflows:
        prior = [t for t in in_times if t <= out.t]
        if prior and out.t - prior[-1] <= pt_window:
            quick_out += out.amount_paise
            quick_minutes.append((out.t - prior[-1]) / 60)
    forwarded_fraction = min(1.0, quick_out / total_in) if total_in else 0.0

    # first-time senders: paid this account inside the window but never before it
    earlier_senders = {e.src for e in GRAPH.inflows(account_id) if e.t < since}
    new_senders = {e.src for e in inflows} - earlier_senders

    account = GRAPH.accounts.get(account_id) or {}
    opened = account.get("opened_at")
    age_days = int((now_t - clock.parse(opened).timestamp()) / DAY) if opened else None
    return {
        "window_hours": cfg["window_hours"],
        "inflow_count": len(inflows),
        "outflow_count": len(outflows),
        "distinct_senders": len({e.src for e in inflows}),
        "first_time_senders": len(new_senders),
        "distinct_recipients": len({e.dst for e in outflows}),
        "total_in_paise": total_in,
        "total_out_paise": total_out,
        "forwarded_fraction": round(forwarded_fraction, 3),
        "median_forward_minutes": round(sorted(quick_minutes)[len(quick_minutes) // 2], 1) if quick_minutes else None,
        "small_outflows": sum(1 for e in outflows if e.amount_paise < int(cfg["smurfing"]["below_paise"])),
        "age_days": age_days,
        "device_peers": len(GRAPH.device_peers(account_id)),
        "inflows": inflows,
        "outflows": outflows,
        "since_t": since,
        "now_t": now_t,
    }


def evaluate(account_id: str, now_t: float | None = None) -> tuple[list[RiskSignal], dict[str, Any]]:
    cfg = get_policy()["network"]
    f = features(account_id, now_t)
    signals: list[RiskSignal] = []
    hours = f["window_hours"]

    if f["first_time_senders"] >= cfg["fan_in"]["min_distinct_senders"]:
        signals.append(_sig(
            "NET_FAN_IN", "Many first-time senders",
            f"Received money from {f['first_time_senders']} accounts that had never paid it before, in the last "
            f"{hours} hours ({_rupees(f['total_in_paise'])} in total).",
            {"first_time_senders": f["first_time_senders"], "distinct_senders": f["distinct_senders"],
             "total_in_paise": f["total_in_paise"], "window_hours": hours},
            cfg["fan_in"]["contribution"],
        ))
    if f["distinct_recipients"] >= cfg["fan_out"]["min_distinct_recipients"]:
        signals.append(_sig(
            "NET_FAN_OUT", "Splits money out",
            f"Sent money on to {f['distinct_recipients']} different accounts in the last {hours} hours.",
            {"distinct_recipients": f["distinct_recipients"], "total_out_paise": f["total_out_paise"]},
            cfg["fan_out"]["contribution"],
        ))
    pt = cfg["pass_through"]
    if f["total_in_paise"] >= pt["min_inflow_paise"] and f["forwarded_fraction"] >= pt["min_forwarded_fraction"]:
        signals.append(_sig(
            "NET_PASS_THROUGH", "Rapid pass-through",
            f"{round(f['forwarded_fraction'] * 100)}% of the money it received was moved on within "
            f"{pt['max_minutes']} minutes (typically after {f['median_forward_minutes']} min).",
            {"forwarded_fraction": f["forwarded_fraction"], "median_forward_minutes": f["median_forward_minutes"],
             "total_in_paise": f["total_in_paise"], "total_out_paise": f["total_out_paise"]},
            pt["contribution"],
        ))
    cycle = GRAPH.has_cycle_through(account_id, f["since_t"], int(cfg["circular"]["max_hops"]))
    if cycle:
        signals.append(_sig(
            "NET_CIRCULAR", "Circular flow",
            f"Money left this account and came back to it through {len(cycle) - 2} other account(s).",
            {"cycle": cycle}, cfg["circular"]["contribution"],
        ))
    sm = cfg["smurfing"]
    if f["small_outflows"] >= sm["min_count"]:
        signals.append(_sig(
            "NET_SMURFING", "Many small transfers",
            f"Made {f['small_outflows']} outgoing transfers below {_rupees(sm['below_paise'])} in {hours} hours.",
            {"small_outflows": f["small_outflows"], "below_paise": sm["below_paise"]}, sm["contribution"],
        ))
    chain = _velocity_chain(account_id, f, float(cfg["velocity_chain"]["max_minutes_per_hop"]) * 60)
    if chain >= cfg["velocity_chain"]["min_hops"]:
        signals.append(_sig(
            "NET_VELOCITY_CHAIN", "Part of a fast chain",
            f"Sits in a chain of {chain} quick hops, each forwarded within "
            f"{cfg['velocity_chain']['max_minutes_per_hop']} minutes.",
            {"hops": chain}, cfg["velocity_chain"]["contribution"],
        ))
    if f["device_peers"] >= cfg["shared_device"]["min_accounts"]:
        signals.append(_sig(
            "NET_SHARED_DEVICE", "Shared device",
            f"Its device is shared with {f['device_peers'] - 1} other account(s).",
            {"accounts_on_device": f["device_peers"]}, cfg["shared_device"]["contribution"],
        ))
    dw = cfg["dormant_wake"]
    activity = f["inflows"] + f["outflows"]
    if activity:
        first_recent = min(e.t for e in activity)
        last_before = GRAPH.last_activity_before(account_id, f["since_t"])
        opened_t = clock.parse(GRAPH.accounts[account_id]["opened_at"]).timestamp() if account_id in GRAPH.accounts else None
        quiet_from = last_before if last_before is not None else opened_t
        if quiet_from is not None and (first_recent - quiet_from) / DAY >= dw["min_quiet_days"]:
            quiet_days = int((first_recent - quiet_from) / DAY)
            signals.append(_sig(
                "NET_DORMANT_WAKE", "Dormant account woke up",
                f"Was inactive for {quiet_days} days, then became active in the last {hours} hours.",
                {"quiet_days": quiet_days}, dw["contribution"],
            ))
    na = cfg["new_account_inflow"]
    if f["age_days"] is not None and f["age_days"] <= na["max_age_days"] and f["total_in_paise"] >= na["min_inflow_paise"]:
        signals.append(_sig(
            "NET_NEW_ACCOUNT_INFLOW", "New account, large inflow",
            f"Opened {f['age_days']} days ago and has already received {_rupees(f['total_in_paise'])}.",
            {"age_days": f["age_days"], "total_in_paise": f["total_in_paise"]}, na["contribution"],
        ))

    labelled = labelled_accounts()
    ln = cfg["labelled_neighbour"]
    if account_id in labelled:
        signals.append(_sig(
            "NET_LABELLED_ACCOUNT", "Received a confirmed scam payment",
            "This account directly received a payment the bank has confirmed as a scam.",
            {"label_id": labelled[account_id]}, ln["contribution_1hop"] + ln["contribution_2hop"],
        ))
    else:
        # Follow the money downstream only: paying INTO a scam account (a victim) is not evidence against you.
        senders = {e.src for e in GRAPH.inflows(account_id)}
        one_hop = senders & set(labelled)
        if one_hop:
            signals.append(_sig(
                "NET_LABELLED_NEIGHBOUR", "Received money from a confirmed scam account",
                f"Received money directly from {len(one_hop)} account(s) that received confirmed scam payments.",
                {"from_accounts": sorted(one_hop)}, ln["contribution_1hop"],
            ))
        else:
            two_hop = {e.src for s in senders for e in GRAPH.inflows(s)} & set(labelled)
            if two_hop:
                signals.append(_sig(
                    "NET_LABELLED_NEIGHBOUR_2HOP", "Two hops downstream of a scam account",
                    "Received money from an account that was itself paid by a confirmed scam account.",
                    {"accounts": sorted(two_hop)}, ln["contribution_2hop"],
                ))

    te = cfg["taint_exposure"]
    exposure = taint.exposure().get(account_id, 0)
    if exposure >= te["min_paise"]:
        signals.append(_sig(
            "NET_TAINT_EXPOSURE", "Holds money traced to a scam",
            f"{_rupees(exposure)} of its current balance is attributable to a confirmed scam "
            f"(Lowest Intermediate Balance Rule).",
            {"attributable_paise": exposure, "rule": "libr"}, te["contribution"],
        ))

    f_public = {k: v for k, v in f.items() if k not in {"inflows", "outflows", "since_t", "now_t"}}
    f_public["role"] = role_of(f)
    f_public["attributable_paise"] = exposure
    f_public["labelled"] = account_id in labelled
    return signals, f_public


def _velocity_chain(account_id: str, f: dict[str, Any], hop_window: float) -> int:
    """Length of the fastest in→out chain through this account (hops)."""
    def forwards_quickly(node: str, after_t: float) -> bool:
        return any(0 <= e.t - after_t <= hop_window for e in GRAPH.outflows(node, after_t))

    best = 0
    for inflow in f["inflows"]:
        if not forwards_quickly(account_id, inflow.t):
            continue
        hops = 1
        upstream = GRAPH.inflows(inflow.src, inflow.t - hop_window)
        if any(e.t <= inflow.t for e in upstream):
            hops += 1
        nxt = [e for e in GRAPH.outflows(account_id, inflow.t) if e.t - inflow.t <= hop_window]
        if any(forwards_quickly(e.dst, e.t) for e in nxt):
            hops += 1
        best = max(best, hops)
    return best


def role_of(f: dict[str, Any]) -> str | None:
    if f["total_in_paise"] == 0 and f["total_out_paise"] == 0:
        return None
    if f["first_time_senders"] >= 3 and f["forwarded_fraction"] >= 0.6:
        return "collector"
    if f["forwarded_fraction"] >= 0.7:
        return "pass-through"
    if f["distinct_recipients"] >= 3 and f["total_out_paise"] >= f["total_in_paise"] * 0.6:
        return "distributor"
    return None


def score(signals: list[RiskSignal]) -> float:
    return round(min(1.0, sum(s.contribution for s in signals)), 4)


# ── population scan for the command center / graph (cached by graph version) ──
_scan_cache: dict[str, Any] = {"key": None, "rows": []}


def scan(min_score: float = 0.3) -> list[dict[str, Any]]:
    key = f"{GRAPH.version}|{taint._cache_key()}"
    if _scan_cache["key"] == key:
        return [r for r in _scan_cache["rows"] if r["score"] >= min_score]
    now_t = clock.now().timestamp()
    since = now_t - float(get_policy()["network"]["window_hours"]) * 3600
    active = {e.dst for edges in GRAPH.in_edges.values() for e in edges if e.t >= since}
    active |= set(labelled_accounts())
    active |= set(taint.exposure())
    rows = []
    for account_id in active:
        if (GRAPH.accounts.get(account_id) or {}).get("kind") == "external":
            continue
        signals, feats = evaluate(account_id, now_t)
        s = score(signals)
        if s > 0:
            rows.append({
                "account_id": account_id,
                "score": s,
                "rules": [x.rule_id for x in signals],
                "labels": [x.label for x in signals],
                "role": feats["role"],
                "attributable_paise": feats["attributable_paise"],
                "total_in_paise": feats["total_in_paise"],
                "labelled": feats["labelled"],
            })
    rows.sort(key=lambda r: (-r["score"], r["account_id"]))
    _scan_cache.update(key=key, rows=rows)
    return [r for r in rows if r["score"] >= min_score]
