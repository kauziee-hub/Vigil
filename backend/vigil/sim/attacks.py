"""The ten attack patterns of the original money-mule project, as deterministic
Vigil scenarios (no randomness at run time).

Account pools are fixed, disjoint slices of the seeded ordinary population
(sorted ids), so every run touches the same accounts. Where an attack needs a
fresh mule account it is created with a fixed id. Every ledger posting is tagged
`seed_attack=<scenario id>` (ground truth for evaluation / replay only — no
scorer reads it). Money that "arrives from another bank" enters as an
external_credit so the ledger stays balanced.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from vigil import clock, db
from vigil.engine import ledger
from vigil.graph.pathgraph import GRAPH
from vigil.realtime import HUB
from vigil.sim import seed as seed_mod
from vigil.sim.scenarios import Scenario, Step, _ring_scan

ATTACK_ORDER = [
    "atk_fan_in", "atk_fan_out", "atk_circular", "atk_velocity_chain", "atk_cross_channel",
    "atk_shared_device", "atk_behavioural_drift", "atk_volume_spike", "atk_smurfing", "atk_dormant",
]
POOL_SIZE = 8

_EXCLUDE = set(seed_mod.VICTIMS + seed_mod.SMURF_TARGETS + seed_mod.EARLY_SENDERS + seed_mod.DOWNSTREAM)


def pool(scenario_id: str) -> list[str]:
    """Deterministic, disjoint slice of ordinary seeded customers for this attack."""
    rows = db.q("SELECT id FROM accounts WHERE kind = 'customer' AND is_demo_customer = 0 AND seed_role = 'legit' "
                "AND (persona IS NULL OR persona != 'merchant') ORDER BY id")
    from vigil.sim import cohort_v10
    v10 = set(cohort_v10.account_ids())        # v10 cohort never joins an attack: pools stay exactly as before v10
    ids = [r["id"] for r in rows if r["id"] not in _EXCLUDE and r["id"] != "dormant.savings@vigil" and r["id"] not in v10]
    i = ATTACK_ORDER.index(scenario_id)
    return ids[i * POOL_SIZE:(i + 1) * POOL_SIZE]


def _account(aid: str, name: str, days_old: int, device: str) -> None:
    if db.q1("SELECT id FROM accounts WHERE id = ?", (aid,)):
        return
    opened = clock.iso(clock.now() - timedelta(days=days_old))
    row = {"id": aid, "display_name": name, "kind": "customer", "bank_code": "VGL", "primary_device": device,
           "opened_at": opened, "balance_paise": 0, "daily_limit_paise": 10_000_000, "persona": None,
           "is_demo_customer": 0, "seed_role": "mule_attack"}
    with db.tx():
        db.insert("accounts", row)
        db.insert("account_devices", {"account_id": aid, "device_id": device, "first_seen": opened})
    GRAPH.add_account(row)
    GRAPH.add_device(aid, device)
    from vigil import geo
    geo.backfill_accounts()
    HUB.publish("console", "account.opened", {"account_id": aid, "label": name, "opened_at": opened})


def _tx(sid: str, sender: str, recipient: str, amount: int, *, channel: str = "upi", note: str = "",
        kind: str = "transfer") -> dict[str, Any]:
    if kind == "transfer" and ledger.available_paise(sender) < amount:
        top_up = amount - ledger.available_paise(sender) + 5_000_00
        ledger.post(sender_id="ext:other-bank", recipient_id=sender, amount_paise=top_up, kind="external_credit",
                    note="funds from another bank", source="scenario", seed_attack=sid, check_funds=False)
    tx = ledger.post(sender_id=sender, recipient_id=recipient, amount_paise=amount, kind=kind, note=note,
                     source="scenario", seed_attack=sid, channel=channel)
    HUB.publish("console", "ledger.posted", tx)
    return {"transaction_id": tx["id"], "source": sender, "target": recipient, "amount_paise": amount}


def _credit(sid: str, recipient: str, amount: int) -> dict[str, Any]:
    tx = ledger.post(sender_id="ext:other-bank", recipient_id=recipient, amount_paise=amount, kind="external_credit",
                     note="funds from another bank", source="scenario", seed_attack=sid, check_funds=False)
    HUB.publish("console", "ledger.posted", tx)
    return {"transaction_id": tx["id"], "source": "ext:other-bank", "target": recipient, "amount_paise": amount}


def _move(account: str, city: str) -> None:
    """SIMULATED: the account's phone is now in another city (display only — drives the impossible-travel story)."""
    from vigil import geo
    geo.HINTS[account] = city


def geo_story(scenario_id: str) -> dict[str, str]:
    """Where each attack's OWN injected postings happen (authored story, like the amounts — not ground truth).
    Mule cash-outs concentrate in one city so the Overview can show a cash-out cluster; the cross-channel hub starts
    in Delhi and is moved to Kolkata between steps (impossible travel). Locations are simulated and display-only."""
    if scenario_id not in ATTACK_ORDER:
        return {}
    p = pool(scenario_id)
    story = {
        "atk_fan_in": {"swift.collect@vigil": "Kolkata"},
        "atk_fan_out": {"bulk.payouts@vigil": "Hyderabad"},
        "atk_velocity_chain": {p[4]: "Mumbai"} if len(p) > 4 else {},
        "atk_cross_channel": {p[0]: "Delhi"} if p else {},
        "atk_shared_device": {a: "Mumbai" for a in ("dc.one@vigil", "dc.two@vigil", "dc.three@vigil", "dc.four@vigil",
                                                    "dc.hub@vigil")},
        "atk_volume_spike": {"fresh.wallet@vigil": "Surat"},
    }
    return story.get(scenario_id, {})


def _many(fns: list[Callable[[], Any]]) -> list[Any]:
    return [f() for f in fns]


def _h(aid: str) -> str:
    return aid.split("@")[0]


# ── the ten patterns ──────────────────────────────────────────────────────
def fan_in() -> list[Step]:
    sid, p, hub = "atk_fan_in", pool("atk_fan_in"), "swift.collect@vigil"
    amounts = [32_000_00, 41_000_00, 27_500_00, 45_000_00, 38_000_00, 29_000_00]
    steps = [Step("info", "New collector account appears", f"{_h(hub)} opened 3 days ago.",
                  lambda: _account(hub, "Swift Collect", 3, "dev-swift-01"))]
    for s, a in zip(p[:6], amounts):
        steps.append(Step("transaction", f"Fan-in: {_h(s)} → {_h(hub)} ₹{a // 100:,}", "First-time sender.",
                          lambda s=s, a=a: _tx(sid, s, hub, a, note="investment")))
    steps.append(Step("transaction", f"Collector forwards 90% → other bank", "Rapid pass-through out of the perimeter.",
                      lambda: _tx(sid, hub, "ext:other-bank", 1_92_000_00, kind="external_debit", note="transfer")))
    steps.append(Step("detect", "RingWatch scan", "Fan-in + pass-through + new-account inflow.", _ring_scan))
    return steps


def fan_out() -> list[Step]:
    sid, p, hub = "atk_fan_out", pool("atk_fan_out"), "bulk.payouts@vigil"
    steps = [Step("info", "Distributor account funded", f"{_h(hub)} receives ₹2,40,000 from another bank.",
                  lambda: (_account(hub, "Bulk Payouts", 6, "dev-bulk-02"), _credit(sid, hub, 2_40_000_00))[1])]
    targets = p[:6]
    for i in range(0, 6, 2):
        pair = targets[i:i + 2]
        steps.append(Step("transaction", "Fan-out: " + ", ".join(_h(t) for t in pair), "Rapid distribution.",
                          lambda pair=pair: _many([lambda t=t: _tx(sid, hub, t, 36_000_00, note="payout") for t in pair])))
    steps.append(Step("detect", "RingWatch scan", "Fan-out + rapid pass-through on the distributor.", _ring_scan))
    return steps


def circular() -> list[Step]:
    sid, p = "atk_circular", pool("atk_circular")
    ring = p[:4]
    amounts = [48_000_00, 47_000_00, 46_000_00, 45_000_00]
    steps = []
    for i in range(4):
        a, b = ring[i], ring[(i + 1) % 4]
        steps.append(Step("transaction", f"Ring: {_h(a)} → {_h(b)} ₹{amounts[i] // 100:,}", "Money moves round the loop.",
                          lambda a=a, b=b, amt=amounts[i]: _tx(sid, a, b, amt, note="loan repayment")))
    steps.append(Step("detect", "RingWatch scan", "Circular flow back to the origin within minutes.", _ring_scan))
    return steps


def velocity_chain() -> list[Step]:
    sid, p = "atk_velocity_chain", pool("atk_velocity_chain")
    chain = p[:5]
    steps = [Step("transaction", f"Funds land on {_h(chain[0])}", "₹80,000 from another bank.",
                  lambda: _credit(sid, chain[0], 80_000_00))]
    amt = 78_000_00
    for i in range(4):
        a, b = chain[i], chain[i + 1]
        steps.append(Step("transaction", f"Hop {i + 1}: {_h(a)} → {_h(b)} ₹{amt // 100:,}", "Forwarded within minutes.",
                          lambda a=a, b=b, amt=amt: _tx(sid, a, b, amt, note="transfer")))
        amt -= 2_000_00
    steps.append(Step("transaction", f"Exit: {_h(chain[4])} → ATM", "Cash-out at the end of the chain.",
                      lambda: _tx(sid, chain[4], "ext:atm", 70_000_00, kind="external_debit", note="cash")))
    steps.append(Step("detect", "RingWatch scan", "Velocity chain + pass-through.", _ring_scan))
    return steps


def cross_channel() -> list[Step]:
    sid, p = "atk_cross_channel", pool("atk_cross_channel")
    hub, feeders, outs = p[0], p[1:4], p[4:8]
    steps = []
    for f, ch in zip(feeders, ["upi", "imps", "neft"]):
        steps.append(Step("transaction", f"In via {ch.upper()}: {_h(f)} → {_h(hub)} ₹22,000", "Same hub, different rail.",
                          lambda f=f, ch=ch: _tx(sid, f, hub, 22_000_00, channel=ch, note="payment")))
    steps.append(Step("transaction", "Out across card / IMPS / UPI / NEFT", "Four rails within minutes.",
                      lambda: _many([lambda o=o, ch=ch: _tx(sid, hub, o, 15_500_00, channel=ch, note="transfer")
                                     for o, ch in zip(outs[:2], ["card", "imps"])]
                                    + [lambda: _move(hub, "Kolkata")]
                                    + [lambda o=o, ch=ch: _tx(sid, hub, o, 15_500_00, channel=ch, note="transfer")
                                       for o, ch in zip(outs[2:], ["upi", "neft"])])))
    steps.append(Step("detect", "Detector comparison", "Channel diversity is a rule-engine feature; RingWatch sees pass-through.",
                      _ring_scan))
    return steps


def shared_device() -> list[Step]:
    sid, p = "atk_shared_device", pool("atk_shared_device")
    members = ["dc.one@vigil", "dc.two@vigil", "dc.three@vigil", "dc.four@vigil"]
    hub = "dc.hub@vigil"
    steps = [Step("info", "Five accounts opened on one device", "All bound to dev-cluster-7x.",
                  lambda: [_account(a, a.split("@")[0].replace(".", " ").title(), 5, "dev-cluster-7x") for a in members + [hub]])]
    for m, s in zip(members, p[:4]):
        steps.append(Step("transaction", f"{_h(s)} → {_h(m)} → {_h(hub)}", "Each member collects then forwards to the hub.",
                          lambda m=m, s=s: [_tx(sid, s, m, 30_000_00, note="order"), _tx(sid, m, hub, 29_000_00, note="settle")]))
    steps.append(Step("transaction", f"{_h(hub)} → ATM ₹1,10,000", "Cash-out.",
                      lambda: _tx(sid, hub, "ext:atm", 1_10_000_00, kind="external_debit", note="cash")))
    steps.append(Step("detect", "RingWatch scan", "Shared-device cluster + pass-through.", _ring_scan))
    return steps


def behavioural_drift() -> list[Step]:
    sid, p = "atk_behavioural_drift", pool("atk_behavioural_drift")
    acct, others = p[0], p[1:8]
    steps = []
    for i in range(0, 7, 3):
        chunk = others[i:i + 3]
        steps.append(Step("transaction", f"{_h(acct)} pays " + ", ".join(_h(o) for o in chunk),
                          "Sudden burst to new counterparties.",
                          lambda chunk=chunk: _many([lambda o=o: _tx(sid, acct, o, 6_500_00, note="transfer") for o in chunk])))
    steps.append(Step("transaction", f"{_h(acct)} receives ₹90,000 then forwards", "Retention collapses.",
                      lambda: [_credit(sid, acct, 90_000_00), _tx(sid, acct, "ext:other-bank", 85_000_00, kind="external_debit")]))
    steps.append(Step("detect", "Detector comparison", "Behavioural drift is the main signal (baseline vs current).", _ring_scan))
    return steps


def volume_spike() -> list[Step]:
    sid, p, acct = "atk_volume_spike", pool("atk_volume_spike"), "fresh.wallet@vigil"
    steps = [Step("info", "Account opened yesterday", f"{_h(acct)}.", lambda: _account(acct, "Fresh Wallet", 1, "dev-fw-01"))]
    for i in range(0, 6, 2):
        pair = p[i:i + 2]
        steps.append(Step("transaction", "Inflows from " + ", ".join(_h(x) for x in pair), "High volume immediately.",
                          lambda pair=pair: _many([lambda x=x: _tx(sid, x, acct, 18_000_00, note="payment") for x in pair])))
    steps.append(Step("transaction", "Outflows to 4 accounts", "Volume in and straight out.",
                      lambda: _many([lambda x=x: _tx(sid, acct, x, 25_000_00, note="transfer") for x in p[6:8] + p[0:2]])))
    steps.append(Step("detect", "RingWatch scan", "New account + early volume spike.", _ring_scan))
    return steps


def smurfing() -> list[Step]:
    sid, p = "atk_smurfing", pool("atk_smurfing")
    acct, outs = p[0], p[1:8]
    steps = [Step("transaction", f"{_h(acct)} receives ₹80,000", "From another bank.", lambda: _credit(sid, acct, 80_000_00))]
    amounts = [9_900_00, 9_700_00, 9_800_00, 9_500_00, 9_600_00, 9_900_00, 9_400_00]
    for i in range(0, 7, 2):
        chunk = list(zip(outs[i:i + 2], amounts[i:i + 2]))
        steps.append(Step("transaction", "Structured transfers below ₹10,000: " + ", ".join(_h(o) for o, _ in chunk),
                          "Each just under the reporting-style threshold.",
                          lambda chunk=chunk: _many([lambda o=o, a=a: _tx(sid, acct, o, a, note="gift") for o, a in chunk])))
    steps.append(Step("detect", "RingWatch scan", "Smurfing + pass-through.", _ring_scan))
    return steps


def dormant() -> list[Step]:
    sid, p, acct = "atk_dormant", pool("atk_dormant"), "dormant.savings@vigil"
    steps = []
    for s, a in zip(p[:3], [55_000_00, 60_000_00, 48_000_00]):
        steps.append(Step("transaction", f"{_h(s)} → {_h(acct)} ₹{a // 100:,}", "Quiet for 76 days, now receiving.",
                          lambda s=s, a=a: _tx(sid, s, acct, a, note="deposit")))
    steps.append(Step("transaction", f"{_h(acct)} → other bank ₹1,50,000", "Woken up and emptied.",
                      lambda: _tx(sid, acct, "ext:other-bank", 1_50_000_00, kind="external_debit", note="transfer")))
    steps.append(Step("detect", "RingWatch scan", "Dormant activation + pass-through.", _ring_scan))
    return steps


# How many pool accounts each pattern actually uses (pool(sid)[:n]) — touched_accounts must list
# participants only, never bystanders from the pool (they would read as missed mules in COMPARE).
_POOL_USED = {
    "atk_fan_in": 6, "atk_fan_out": 6, "atk_circular": 4, "atk_velocity_chain": 5, "atk_cross_channel": 8,
    "atk_shared_device": 4, "atk_behavioural_drift": 8, "atk_volume_spike": 8, "atk_smurfing": 8, "atk_dormant": 3,
}

_FIXED_EXTRA = {
    "atk_fan_in": ["swift.collect@vigil"], "atk_fan_out": ["bulk.payouts@vigil"],
    "atk_shared_device": ["dc.one@vigil", "dc.two@vigil", "dc.three@vigil", "dc.four@vigil", "dc.hub@vigil"],
    "atk_volume_spike": ["fresh.wallet@vigil"], "atk_dormant": ["dormant.savings@vigil"],
}

_META = {
    "atk_fan_in": ("Fan-In", fan_in, "Six first-time senders pay a 3-day-old collector, which forwards 90% out."),
    "atk_fan_out": ("Fan-Out", fan_out, "A freshly funded distributor pays six accounts within minutes."),
    "atk_circular": ("Circular Ring", circular, "Four accounts pass money round a loop back to the origin."),
    "atk_velocity_chain": ("Velocity Chain", velocity_chain, "Funds hop through five accounts in minutes, then cash out."),
    "atk_cross_channel": ("Cross-Channel Burst", cross_channel, "One hub moves money across UPI, IMPS, NEFT and card within minutes."),
    "atk_shared_device": ("Shared Device Cluster", shared_device, "Five accounts on one device collect and consolidate."),
    "atk_behavioural_drift": ("Behavioural Drift", behavioural_drift, "A quiet account suddenly pays many new counterparties and stops retaining money."),
    "atk_volume_spike": ("Early Volume Spike", volume_spike, "A one-day-old account sees heavy volume in and out."),
    "atk_smurfing": ("Smurfing", smurfing, "Money split into many transfers just under ₹10,000."),
    "atk_dormant": ("Dormant Activation", dormant, "An account quiet for 76 days receives and empties ₹1.5 lakh."),
}


def build() -> dict[str, Scenario]:
    out: dict[str, Scenario] = {}
    for sid in ATTACK_ORDER:
        name, fn, summary = _META[sid]
        sc = Scenario(sid, name, "Attack", summary,
                      "Detectors flag the attack accounts; compare which families agree.",
                      [summary, "Injected as observed ledger postings (tagged with the scenario id for evaluation only).",
                       "Use COMPARE DETECTORS to see Rules / RF / GNN / drift / pattern memory side by side."],
                      fn, None)
        sc.category = "attack"
        sc.accounts_fn = (lambda sid=sid: pool(sid)[:_POOL_USED[sid]] + _FIXED_EXTRA.get(sid, []))
        out[sid] = sc
    return out
