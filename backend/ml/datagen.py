"""Synthetic transaction worlds for SYNTHETIC VALIDATION of detection intelligence v2.

Repairs audit findings A1-A5, A14 (docs/ML_VALIDATION_REPORT.md §1):
  * many independent worlds, each fully determined by (seed, world index);
  * realistic background that keeps flowing through the evaluation window: salaries (external and
    internal payroll fan-out), recurring payees, merchants with many regular senders and daily
    settlement sweeps, bills, ATM, legitimate high-value payments, lump-sum pass-throughs, event
    collections from many first-time senders, family shared devices, dormant-but-legitimate
    reactivations, very new legitimate accounts;
  * the ten attack families of the original attacks.py, with variable sizes, amounts that overlap
    the background, recruited (old) as well as fresh mule accounts, and slow-mule variants;
  * the evaluation time (`now_t`) is fixed per world and every attack START is drawn at a random
    offset 15 min .. 72 h before it, so attacks may be in progress or partly outside the window:
    there is no attack-window shortcut;
  * labels are mule / not-mule. Victims and bystanders are NEGATIVES. Roles recorded where meaningful.

Edge attribute names match vigil.graph.pathgraph.Edge (src, dst, amount_paise, t) so that the SAME
feature function (vigil/intel/features.py) runs on these worlds and on the live graph.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

DAY = 86400.0
HOUR = 3600.0
MINUTE = 60.0
T0 = 1_800_000_000.0          # evaluation time of every world (absolute value is irrelevant)
HISTORY_DAYS = 60

FAMILIES: tuple[str, ...] = (
    "fan_in", "fan_out", "circular", "velocity_chain", "cross_channel",
    "shared_device", "behavioural_drift", "volume_spike", "smurfing", "dormant",
)
FAMILY_NAMES = {
    "fan_in": "Fan-In", "fan_out": "Fan-Out", "circular": "Circular Ring", "velocity_chain": "Velocity Chain",
    "cross_channel": "Cross-Channel Burst", "shared_device": "Shared Device Cluster",
    "behavioural_drift": "Behavioural Drift", "volume_spike": "Early Volume Spike", "smurfing": "Smurfing",
    "dormant": "Dormant Activation",
}
LIVE_SCENARIO = {f: f"atk_{f}" for f in FAMILIES}
LIVE_SCENARIO["volume_spike"] = "atk_volume_spike"
EXTERNALS = ("ext:employer", "ext:atm", "ext:other-bank")


@dataclass(frozen=True, slots=True)
class SimEdge:
    src: str
    dst: str
    amount_paise: int
    t: float
    channel: str
    tag: str | None = None      # attack instance id; ground truth for the old-protocol replication ONLY


class World:
    """One synthetic world. Implements vigil.intel.features.GraphSource."""

    def __init__(self, index: int, seed: int, now_t: float = T0) -> None:
        self.index = index
        self.seed = seed
        self.now_t = now_t
        self.accounts: dict[str, dict[str, Any]] = {}
        self.devices: dict[str, set[str]] = defaultdict(set)
        self.device_accounts: dict[str, set[str]] = defaultdict(set)
        self._in: dict[str, list[SimEdge]] = defaultdict(list)
        self._out: dict[str, list[SimEdge]] = defaultdict(list)
        self.labels: dict[str, int] = {}
        self.family: dict[str, str] = {}
        self.role: dict[str, str] = {}
        self.primary: set[str] = set()       # the account a pattern is named after (collector, hub, ...)
        self.attacks: list[dict[str, Any]] = []
        self.kind_hint: dict[str, str] = {}  # background persona (for error analysis only)
        self.n_edges = 0

    # ── GraphSource ────────────────────────────────────────────────────
    def inflows(self, account_id: str) -> list[SimEdge]:
        return self._in.get(account_id, [])

    def outflows(self, account_id: str) -> list[SimEdge]:
        return self._out.get(account_id, [])

    def channel(self, edge: SimEdge) -> str:
        return edge.channel

    def device_cluster_size(self, account_id: str) -> int:
        peers: set[str] = set()
        for d in self.devices.get(account_id, ()):
            peers |= self.device_accounts[d]
        return max(1, len(peers))

    def opened_t(self, account_id: str) -> float | None:
        a = self.accounts.get(account_id)
        return a["opened_t"] if a else None

    def is_external(self, account_id: str) -> bool:
        return account_id.startswith("ext:")

    # ── building ───────────────────────────────────────────────────────
    def add_account(self, aid: str, kind: str, age_days: float, device: str | None = None) -> str:
        self.accounts[aid] = {"opened_t": self.now_t - age_days * DAY, "kind": kind}
        self.labels.setdefault(aid, 0)
        self.kind_hint[aid] = kind
        if not aid.startswith("ext:"):
            self.bind(aid, device or f"dev-{aid}")
        return aid

    def bind(self, aid: str, device: str) -> None:
        self.devices[aid].add(device)
        self.device_accounts[device].add(aid)

    def tx(self, src: str, dst: str, rupees: float, t: float, channel: str = "upi", tag: str | None = None) -> None:
        if src == dst or t > self.now_t:
            return
        if t < self.accounts[src]["opened_t"] or t < self.accounts[dst]["opened_t"]:
            return
        paise = int(round(rupees)) * 100
        if paise <= 0:
            return
        e = SimEdge(src, dst, paise, t, channel, tag)
        self._out[src].append(e)
        self._in[dst].append(e)
        self.n_edges += 1

    def finalize(self) -> "World":
        for lst in list(self._in.values()) + list(self._out.values()):
            lst.sort(key=lambda e: (e.t, e.src, e.dst))
        return self

    def scored_accounts(self) -> list[str]:
        return sorted(a for a, v in self.accounts.items()
                      if not a.startswith("ext:") and v["opened_t"] <= self.now_t)

    def mark_mule(self, aid: str, family: str, role: str, primary: bool = False) -> None:
        self.labels[aid] = 1
        self.family.setdefault(aid, family)
        self.role.setdefault(aid, role)
        if primary:
            self.primary.add(aid)


class AttackOnlyView:
    """The ORIGINAL protocol's view (audit A1): only injected transactions are visible.
    Used solely to replicate the old leakage on the v2 generator for the report."""

    def __init__(self, w: World) -> None:
        self.w = w
        self._in = {a: [e for e in lst if e.tag] for a, lst in w._in.items()}
        self._out = {a: [e for e in lst if e.tag] for a, lst in w._out.items()}

    def inflows(self, a: str) -> list[SimEdge]:
        return self._in.get(a, [])

    def outflows(self, a: str) -> list[SimEdge]:
        return self._out.get(a, [])

    def channel(self, e: SimEdge) -> str:
        return e.channel

    def device_cluster_size(self, a: str) -> int:
        return self.w.device_cluster_size(a)

    def opened_t(self, a: str) -> float | None:
        return self.w.opened_t(a)

    def is_external(self, a: str) -> bool:
        return self.w.is_external(a)


# ── helpers ───────────────────────────────────────────────────────────────
def _lognormal_amount(r: random.Random, median: float, sigma: float, lo: float, hi: float) -> float:
    return float(min(hi, max(lo, median * math.exp(r.gauss(0.0, sigma)))))


def _poisson(r: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    n, p, limit = 0, 1.0, math.exp(-min(lam, 60.0))
    while True:
        p *= r.random()
        if p <= limit:
            return n
        n += 1


def _pick_channel(r: random.Random, prefs: list[str]) -> str:
    if len(prefs) == 1 or r.random() < 0.7:
        return prefs[0]
    return r.choice(prefs)


# ── background ────────────────────────────────────────────────────────────
def _background(w: World, r: random.Random) -> dict[str, Any]:
    now = w.now_t
    start = now - HISTORY_DAYS * DAY
    for e in EXTERNALS:
        w.add_account(e, "external", 5000)

    merchants = [w.add_account(f"w{w.index}.merchant{i}", "merchant", r.uniform(700, 4000))
                 for i in range(r.randint(8, 14))]
    utilities = merchants[:2]
    shops = merchants[2:]
    payroll = [w.add_account(f"w{w.index}.company{i}", "payroll", r.uniform(1500, 5000))
               for i in range(r.randint(2, 4))]

    n_cust = r.randint(220, 320)
    customers: list[str] = []
    for i in range(n_cust):
        u = r.random()
        age = r.uniform(200, 3500) if u < 0.85 else (r.uniform(20, 200) if u < 0.95 else r.uniform(1, 20))
        customers.append(w.add_account(f"w{w.index}.c{i:03d}", "customer", age))

    # households sharing one phone (legitimate shared devices: 2-3 accounts)
    pool = customers[:]
    r.shuffle(pool)
    n_house = int(len(pool) * 0.08 / 2.3)
    for h in range(n_house):
        size = 3 if r.random() < 0.25 else 2
        members = pool[h * 3:h * 3 + size]
        dev = f"dev-house-{w.index}-{h}"
        for m in members:
            w.bind(m, dev)

    # personas that change the history shape (disjoint)
    shuffled = customers[:]
    r.shuffle(shuffled)
    dormant_legit = set(shuffled[:int(0.04 * n_cust)])
    dormant_reserve = shuffled[int(0.04 * n_cust):int(0.04 * n_cust) + 6]   # may be activated by an attack
    reserved = set(dormant_reserve)
    # dormant accounts must really be quiet: nobody else pays them / buys from them either
    active = [c for c in customers if c not in dormant_legit and c not in reserved]
    traders = set(r.sample(active, int(0.06 * n_cust)))
    landlords = set(r.sample([c for c in active if c not in traders], int(0.02 * n_cust)))
    for c in traders:
        w.kind_hint[c] = "trader"
    for c in landlords:
        w.kind_hint[c] = "landlord"
    employer_of: dict[str, str] = {}
    for c in customers:
        if r.random() < 0.4:
            employer_of[c] = r.choice(payroll)

    payday = {p: r.uniform(0, 30) for p in payroll}
    payroll_due: dict[tuple[str, int], float] = defaultdict(float)

    for c in customers:
        opened = w.accounts[c]["opened_t"]
        act_start = max(start, opened)
        act_end = now
        if c in dormant_legit or c in reserved:
            act_end = now - r.uniform(40, 58) * DAY
        u = r.random()
        prefs = ["upi"] if u < 0.80 else (["upi", "imps"] if u < 0.95 else ["upi", "imps", "neft", "card"])
        level = r.random()
        per30 = r.uniform(2, 6) if level < 0.30 else (r.uniform(6, 15) if level < 0.80 else r.uniform(15, 40))

        # salary
        salary = _lognormal_amount(r, 45_000, 0.5, 12_000, 2_50_000)
        if (now - opened) > 40 * DAY:
            for month in range(2):
                if c in employer_of:
                    comp = employer_of[c]
                    t = start + payday[comp] * DAY + month * 30 * DAY + r.uniform(0, 2) * HOUR
                    if t <= act_end:
                        w.tx(comp, c, salary, t, "neft")
                        payroll_due[(comp, month)] += salary
                else:
                    t = start + r.uniform(0, 5) * DAY + month * 30 * DAY + r.uniform(0, 10) * HOUR
                    if t <= act_end:
                        w.tx("ext:employer", c, salary, t, "neft")

        # recurring payees
        payees = r.sample(shops, min(len(shops), r.randint(2, 3)))
        friends = r.sample([x for x in active if x != c], r.randint(0, 3))
        typical = {p: _lognormal_amount(r, 900, 0.8, 100, 8_000) for p in payees}
        typical.update({f: _lognormal_amount(r, 2_000, 0.9, 200, 15_000) for f in friends})
        targets = payees + friends
        weights = [3.0] * len(payees) + [1.0] * len(friends)
        span = max(0.0, act_end - act_start)
        n = _poisson(r, per30 * span / (30 * DAY))
        for _ in range(n):
            p = r.choices(targets, weights)[0]
            amt = typical[p] * r.uniform(0.6, 1.4)
            w.tx(c, p, amt, act_start + r.random() * span, _pick_channel(r, prefs))
            if p in friends and r.random() < 0.15:
                w.tx(p, c, amt * r.uniform(0.5, 1.2), act_start + r.random() * span, "upi")
        # bills
        for util in utilities:
            if r.random() < 0.7:
                amt = _lognormal_amount(r, 1_500, 0.4, 300, 6_000)
                for month in range(2):
                    t = start + r.uniform(5, 15) * DAY + month * 30 * DAY
                    if act_start <= t <= act_end:
                        w.tx(c, util, amt * r.uniform(0.8, 1.2), t, _pick_channel(r, prefs))
        # ATM
        if r.random() < 0.35:
            for _ in range(r.randint(1, 3)):
                w.tx(c, "ext:atm", r.randint(2, 15) * 1000, act_start + r.random() * span, "card")
        # one-off new payees
        if r.random() < 0.4:
            for _ in range(r.randint(1, 2)):
                other = r.choice(active)
                w.tx(c, other, _lognormal_amount(r, 2_500, 0.9, 300, 20_000), act_start + r.random() * span,
                     _pick_channel(r, prefs))
        # legitimate high-value payment to a new counterparty
        if r.random() < 0.06:
            dst = r.choice(["ext:other-bank", r.choice(active)])
            w.tx(c, dst, _lognormal_amount(r, 1_20_000, 0.6, 40_000, 4_00_000), act_start + r.random() * span,
                 r.choice(["neft", "imps", "upi"]))
        # legitimate lump sum in and (sometimes) straight out — a pass-through hard negative
        if r.random() < 0.03:
            t = act_start + r.random() * span
            lump = _lognormal_amount(r, 1_50_000, 0.6, 50_000, 6_00_000)
            w.tx("ext:other-bank", c, lump, t, "neft")
            if r.random() < 0.5:
                w.tx(c, "ext:other-bank", lump * r.uniform(0.7, 0.95), t + r.uniform(20, 600) * MINUTE, "neft")
        # dormant-but-legitimate reactivation inside the window
        if c in dormant_legit:
            for _ in range(r.randint(1, 3)):
                p = r.choice(targets) if targets else r.choice(shops)
                w.tx(c, p, typical.get(p, 800) * r.uniform(0.6, 1.4), now - r.uniform(0.1, 70) * HOUR, prefs[0])
        # a few fresh legit accounts receive money from family
        if (now - opened) < 30 * DAY and friends:
            w.tx(friends[0], c, _lognormal_amount(r, 5_000, 0.6, 500, 30_000), act_start + r.random() * span, "upi")
        # small trader: sales from regular and first-time buyers, takings swept to cash / supplier (hard negative)
        if c in traders:
            regulars = r.sample(active, r.randint(5, 15))
            per_day = r.uniform(1, 4)
            sales = sorted(act_start + r.random() * span for _ in range(_poisson(r, per_day * span / DAY)))
            takings, last_sweep = 0.0, act_start
            for t in sales:
                buyer = r.choice(regulars) if r.random() < 0.5 else r.choice(active)
                amt = _lognormal_amount(r, 1_500, 0.8, 200, 20_000)
                w.tx(buyer, c, amt, t, "upi")
                takings += amt
                if t - last_sweep > r.uniform(1, 3) * DAY and takings > 2_000:
                    dst = r.choice(["ext:atm", "ext:other-bank", r.choice(shops)])
                    w.tx(c, dst, takings * r.uniform(0.6, 0.95), t + r.uniform(10, 360) * MINUTE,
                         "card" if dst == "ext:atm" else "upi")
                    takings, last_sweep = 0.0, t
        # landlord: monthly rents from a few tenants, then the loan EMI goes out (fan-in-like, recurring)
        if c in landlords:
            tenants = r.sample(active, r.randint(3, 6))
            rent = _lognormal_amount(r, 15_000, 0.4, 5_000, 60_000)
            for month in range(2):
                due = start + r.uniform(0, 3) * DAY + month * 30 * DAY
                for tn in tenants:
                    w.tx(tn, c, rent * r.uniform(0.9, 1.1), due + r.uniform(0, 4) * DAY, "upi")
                w.tx(c, "ext:other-bank", rent * len(tenants) * r.uniform(0.5, 0.9), due + r.uniform(4, 6) * DAY, "neft")

    # payroll companies: client receipts, funding before payday, vendors
    for comp in payroll:
        for month in range(2):
            due = payroll_due.get((comp, month), 0.0)
            pay_t = start + payday[comp] * DAY + month * 30 * DAY
            if due > 0:
                w.tx("ext:other-bank", comp, due * r.uniform(1.05, 1.3), pay_t - r.uniform(2, 48) * HOUR, "neft")
            for _ in range(r.randint(3, 8)):
                w.tx("ext:other-bank", comp, _lognormal_amount(r, 1_50_000, 0.7, 20_000, 8_00_000),
                     start + month * 30 * DAY + r.uniform(0, 30) * DAY, "neft")
            for _ in range(r.randint(1, 4)):
                w.tx(comp, r.choice(merchants + ["ext:other-bank"]), _lognormal_amount(r, 40_000, 0.7, 5_000, 3_00_000),
                     start + month * 30 * DAY + r.uniform(0, 30) * DAY, "neft")

    # merchants: daily-ish settlement sweeps of accumulated takings (low retention, fast forwarding)
    for m in merchants:
        every = r.choice([1, 1, 2, 3])
        frac = r.uniform(0.7, 0.95)
        inflows = sorted(w.inflows(m), key=lambda e: e.t)
        acc, i = 0, 0
        day = 0
        while start + day * DAY <= now:
            sweep_t = start + day * DAY + r.uniform(18, 23) * HOUR
            while i < len(inflows) and inflows[i].t <= sweep_t:
                acc += inflows[i].amount_paise
                i += 1
            if acc > 0:
                w.tx(m, "ext:other-bank", acc * frac / 100.0, sweep_t, "neft")
                acc = 0
            day += every
        for _ in range(r.randint(1, 4)):
            w.tx(m, r.choice(merchants + ["ext:other-bank"]), _lognormal_amount(r, 20_000, 0.8, 3_000, 2_00_000),
                 start + r.random() * HISTORY_DAYS * DAY, "neft")

    # event organiser: many first-time senders in a short burst, then a vendor payment (ambiguous negative)
    organisers = []
    n_org = 0 if r.random() < 0.4 else (2 if r.random() < 0.25 else 1)
    for k in range(n_org):
        org = w.add_account(f"w{w.index}.organiser{k}", "organiser", r.uniform(30, 2500))
        organisers.append(org)
        ev_t = now - r.uniform(2, 70) * HOUR if r.random() < 0.7 else start + r.uniform(5, 50) * DAY
        collected = 0.0
        for buyer in r.sample(active, r.randint(8, 25)):
            amt = _lognormal_amount(r, 1_200, 0.5, 300, 4_000)
            t = ev_t - r.uniform(0, 30) * HOUR
            w.tx(buyer, org, amt, t, "upi")
            collected += amt
        w.tx(org, r.choice(merchants + ["ext:other-bank"]), collected * r.uniform(0.6, 0.95),
             ev_t + r.uniform(0.5, 24) * HOUR, r.choice(["upi", "neft"]))
        for _ in range(r.randint(2, 6)):
            w.tx(org, r.choice(shops), _lognormal_amount(r, 800, 0.6, 100, 5_000), start + r.random() * HISTORY_DAYS * DAY)

    return {"customers": customers, "merchants": merchants, "payroll": payroll, "organisers": organisers,
            "dormant_reserve": dormant_reserve, "dormant_legit": dormant_legit}


# ── attacks ───────────────────────────────────────────────────────────────
class _Attack:
    def __init__(self, w: World, r: random.Random, family: str, k: int, ctx: dict[str, Any], used: set[str]) -> None:
        self.w, self.r, self.family, self.ctx, self.used = w, r, family, ctx, used
        self.tag = f"{family}#{k}"
        self.start = w.now_t - r.uniform(0.25, 72) * HOUR
        self.slow = 8.0 if r.random() < 0.15 else 1.0
        self.members: list[str] = []
        self.n_new = 0

    def delay(self, lo_min: float, hi_min: float) -> float:
        return self.r.uniform(lo_min, hi_min) * MINUTE * self.slow

    def tx(self, src: str, dst: str, rupees: float, t: float, channel: str = "upi") -> None:
        self.w.tx(src, dst, rupees, t, channel, self.tag)

    def bystander(self) -> str:
        pool = [c for c in self.ctx["customers"] if c not in self.used and c not in self.ctx["dormant_reserve"]]
        c = self.r.choice(pool)
        self.used.add(c)
        return c

    def victims(self, n: int) -> list[str]:
        return [self.bystander() for _ in range(n)]

    def mule(self, role: str, *, fresh_p: float = 0.65, age: tuple[float, float] = (1, 40),
             device: str | None = None, primary: bool = False) -> str:
        if self.r.random() < fresh_p or device is not None:
            aid = f"w{self.w.index}.{self.tag.replace('#', '_')}.m{self.n_new}"
            self.n_new += 1
            # opened before the attack starts (plus 30 min .. 2 days), but otherwise as young as drawn
            min_age = (self.w.now_t - self.start) / DAY + self.r.uniform(0.02, 2.0)
            self.w.add_account(aid, "mule", max(min_age, self.r.uniform(*age)), device)
            # a little camouflage history before the attack
            if self.r.random() < 0.5:
                for _ in range(self.r.randint(1, 3)):
                    t = self.w.accounts[aid]["opened_t"] + self.r.random() * max(0.0, self.start - self.w.accounts[aid]["opened_t"])
                    self.w.tx(aid, self.r.choice(self.ctx["merchants"]), self.r.uniform(150, 2_000), t)
        else:
            aid = self.bystander()      # recruited / rented existing account with legitimate history
        self.w.mark_mule(aid, self.family, role, primary)
        self.members.append(aid)
        return aid

    def cash_out(self, aid: str, amount: float, t: float) -> None:
        dst = self.r.choice(["ext:atm", "ext:other-bank"])
        channel = "card" if dst == "ext:atm" and self.r.random() < 0.3 else ("imps" if self.r.random() < 0.25 else "upi")
        self.tx(aid, dst, amount, t, channel)


def _fan_in(a: _Attack) -> None:
    r, t = a.r, a.start
    col = a.mule("collector", age=(1, 30), primary=True)
    second = a.mule("exit") if r.random() < 0.4 else None
    batch = r.random() < 0.3
    held = 0.0
    spread = r.uniform(0.5, 36) * HOUR
    times = sorted(t + r.random() * spread for _ in range(r.randint(4, 9)))
    last = t
    for v, tv in zip(a.victims(len(times)), times):
        amt = _lognormal_amount(r, 25_000, 0.6, 5_000, 90_000)
        a.tx(v, col, amt, tv, "upi" if r.random() < 0.8 else "imps")
        last = tv
        if batch:
            held += amt
        else:
            out_t = tv + a.delay(5, 50)
            dst = second or "ext:other-bank"
            a.tx(col, dst, amt * r.uniform(0.85, 0.98), out_t, "imps" if dst.startswith("ext") else "upi")
            if second:
                a.cash_out(second, amt * r.uniform(0.8, 0.95), out_t + a.delay(10, 180))
    if batch and held:
        out_t = last + a.delay(10, 120)
        dst = second or "ext:other-bank"
        a.tx(col, dst, held * r.uniform(0.85, 0.98), out_t, "imps")
        if second:
            a.cash_out(second, held * 0.85, out_t + a.delay(10, 180))


def _fan_out(a: _Attack) -> None:
    r, t = a.r, a.start
    dist = a.mule("distributor", age=(2, 40), primary=True)
    total = _lognormal_amount(r, 1_60_000, 0.4, 60_000, 4_00_000)
    a.tx("ext:other-bank", dist, total, t, "neft")
    n = r.randint(4, 8)
    tt = t + a.delay(5, 90)
    for i in range(n):
        rec = a.mule("exit", fresh_p=0.5)
        amt = total / n * r.uniform(0.75, 0.98)
        tt += r.uniform(1, 25) * MINUTE * a.slow
        a.tx(dist, rec, amt, tt, "upi" if r.random() < 0.75 else "imps")
        if r.random() < 0.75:
            a.cash_out(rec, amt * r.uniform(0.7, 1.0), tt + r.uniform(10, 720) * MINUTE)


def _circular(a: _Attack) -> None:
    r, t = a.r, a.start
    ring = [a.mule("coordinator" if i == 0 else "ring", fresh_p=0.5, primary=True) for i in range(r.randint(3, 6))]
    amt = _lognormal_amount(r, 45_000, 0.4, 15_000, 1_20_000)
    a.tx("ext:other-bank", ring[0], amt * 1.05, t - r.uniform(5, 25) * MINUTE, "neft")
    tt = t
    for _loop in range(r.randint(1, 3)):
        for i in range(len(ring)):
            tt += a.delay(2, 60)
            a.tx(ring[i], ring[(i + 1) % len(ring)], amt, tt, "upi" if r.random() < 0.8 else "imps")
            amt *= r.uniform(0.97, 1.0)


def _velocity_chain(a: _Attack) -> None:
    r, t = a.r, a.start
    n = r.randint(4, 7)
    chain = [a.mule("entry" if i == 0 else ("exit" if i == n - 1 else "relay"), primary=0 < i < n - 1 or n <= 2)
             for i in range(n)]
    amt = _lognormal_amount(r, 90_000, 0.5, 30_000, 3_00_000)
    a.tx("ext:other-bank", chain[0], amt, t, "neft")
    tt = t
    for i in range(n - 1):
        tt += a.delay(1, 30)
        amt *= r.uniform(0.9, 0.98)
        a.tx(chain[i], chain[i + 1], amt, tt, "upi" if r.random() < 0.7 else "imps")
    a.cash_out(chain[-1], amt * r.uniform(0.85, 0.98), tt + a.delay(5, 60))


def _cross_channel(a: _Attack) -> None:
    r, t = a.r, a.start
    hub = a.mule("distributor", primary=True)
    rails = ["upi", "imps", "neft", "card"]
    in_rails = r.sample(rails, r.randint(2, 4))
    total = 0.0
    tt = t
    for v in a.victims(r.randint(3, 5)):
        amt = _lognormal_amount(r, 22_000, 0.5, 5_000, 70_000)
        tt += a.delay(1, 20)
        a.tx(v, hub, amt, tt, r.choice(in_rails))
        total += amt
    outs = r.randint(3, 5)
    out_rails = r.sample(rails, min(4, outs)) + r.sample(rails, max(0, outs - 4))
    for i in range(outs):
        rec = a.mule("exit", fresh_p=0.5)
        tt += a.delay(1, 15)
        amt = total / outs * r.uniform(0.8, 0.97)
        a.tx(hub, rec, amt, tt, out_rails[i])
        if r.random() < 0.6:
            a.cash_out(rec, amt * 0.9, tt + r.uniform(10, 600) * MINUTE)


def _shared_device(a: _Attack) -> None:
    r, t = a.r, a.start
    dev = f"dev-cluster-{a.w.index}-{a.tag}"
    members = [a.mule("collector", device=dev, age=(2, 25), primary=True) for _ in range(r.randint(3, 6))]
    hub = a.mule("exit", device=dev, age=(2, 25), primary=True)
    tt = t
    total = 0.0
    for m in members:
        for v in a.victims(r.randint(1, 2)):
            amt = _lognormal_amount(r, 25_000, 0.5, 6_000, 70_000)
            tt += a.delay(2, 40)
            a.tx(v, m, amt, tt, "upi")
            fwd_t = tt + a.delay(5, 60)
            a.tx(m, hub, amt * r.uniform(0.9, 0.98), fwd_t, "upi")
            total += amt
    a.cash_out(hub, total * r.uniform(0.8, 0.95), tt + a.delay(30, 240))


def _behavioural_drift(a: _Attack) -> None:
    r, t = a.r, a.start
    acct = a.mule("distributor", fresh_p=0.0, primary=True)       # established account suddenly changes
    tt = t
    for rec in [a.bystander() for _ in range(r.randint(6, 10))]:
        tt += r.uniform(5, 150) * MINUTE * a.slow
        a.tx(acct, rec, _lognormal_amount(r, 9_000, 0.5, 2_000, 30_000), tt, "upi")
    lump = _lognormal_amount(r, 90_000, 0.5, 30_000, 2_50_000)
    lt = t + r.uniform(0, 12) * HOUR
    a.tx("ext:other-bank" if r.random() < 0.6 else a.bystander(), acct, lump, lt, "imps")
    a.tx(acct, "ext:other-bank", lump * r.uniform(0.85, 0.97), lt + a.delay(5, 60), "imps")


def _volume_spike(a: _Attack) -> None:
    r, t = a.r, a.start
    acct = a.mule("collector", fresh_p=1.0, age=(0.05, 3), primary=True)
    spread = r.uniform(1, 24) * HOUR
    total = 0.0
    for v in a.victims(r.randint(4, 8)):
        amt = _lognormal_amount(r, 18_000, 0.5, 4_000, 60_000)
        a.tx(v, acct, amt, t + r.random() * spread, "upi")
        total += amt
    outs = [a.bystander() for _ in range(r.randint(3, 6))]
    for rec in outs:
        a.tx(acct, rec, total / len(outs) * r.uniform(0.7, 0.95), t + spread + r.uniform(5, 240) * MINUTE * a.slow, "upi")


def _smurfing(a: _Attack) -> None:
    r, t = a.r, a.start
    hub = a.mule("distributor", primary=True)
    lump = _lognormal_amount(r, 1_00_000, 0.4, 50_000, 2_50_000)
    a.tx("ext:other-bank", hub, lump, t, "neft")
    near = r.random() < 0.75
    recs = []
    for _ in range(r.randint(3, 8)):
        if r.random() < 0.5:
            recs.append(a.mule("exit", fresh_p=0.7))
        else:
            recs.append(a.bystander())
    tt = t
    for _ in range(r.randint(6, 15)):
        tt += r.uniform(2, 120) * MINUTE * a.slow
        amt = r.uniform(8_200, 9_990) if near else r.uniform(2_000, 5_000)
        rec = r.choice(recs)
        a.tx(hub, rec, amt, tt, "upi")
        if a.w.labels.get(rec) == 1 and r.random() < 0.3:
            a.cash_out(rec, amt * 0.95, tt + r.uniform(10, 300) * MINUTE)


def _dormant(a: _Attack) -> None:
    r, t = a.r, a.start
    reserve = [c for c in a.ctx["dormant_reserve"] if c not in a.used]
    if reserve:
        acct = reserve[0]
        a.used.add(acct)
        a.w.mark_mule(acct, a.family, "collector", True)
        a.members.append(acct)
    else:
        acct = a.mule("collector", fresh_p=0.0, primary=True)
    total = 0.0
    tt = t
    for v in a.victims(r.randint(2, 4)):
        amt = _lognormal_amount(r, 50_000, 0.4, 15_000, 1_20_000)
        tt += a.delay(5, 120)
        a.tx(v, acct, amt, tt, "upi" if r.random() < 0.7 else "neft")
        total += amt
    a.tx(acct, "ext:other-bank", total * r.uniform(0.9, 1.0), tt + a.delay(10, 360), "imps")


_ATTACK_FN = {
    "fan_in": _fan_in, "fan_out": _fan_out, "circular": _circular, "velocity_chain": _velocity_chain,
    "cross_channel": _cross_channel, "shared_device": _shared_device, "behavioural_drift": _behavioural_drift,
    "volume_spike": _volume_spike, "smurfing": _smurfing, "dormant": _dormant,
}


def make_world(index: int, seed: int = 20261006, families: list[str] | None = None) -> World:
    """Deterministic: identical (index, seed) -> identical world."""
    r = random.Random(seed * 10_007 + index)
    w = World(index, seed)
    ctx = _background(w, r)
    used: set[str] = set()
    fams = families if families is not None else r.sample(FAMILIES, r.choice([2, 3, 3, 4]))
    for k, fam in enumerate(fams):
        a = _Attack(w, r, fam, k, ctx, used)
        _ATTACK_FN[fam](a)
        w.attacks.append({"family": fam, "tag": a.tag, "start_t": a.start, "offset_h": round((w.now_t - a.start) / HOUR, 2),
                          "slow": a.slow > 1, "mules": [m for m in a.members if w.labels.get(m) == 1]})
    return w.finalize()


def generate(n_worlds: int, seed: int = 20261006) -> list[World]:
    return [make_world(i, seed) for i in range(n_worlds)]


if __name__ == "__main__":  # quick summary: python ml/datagen.py
    import time
    t0 = time.perf_counter()
    ws = generate(10)
    for w in ws:
        n = len(w.scored_accounts())
        pos = sum(w.labels[a] for a in w.scored_accounts())
        print(f"world {w.index}: accounts={n} mules={pos} ({pos / n:.1%}) edges={w.n_edges} "
              f"attacks={[x['family'] + '@' + str(x['offset_h']) + 'h' for x in w.attacks]}")
    print(f"{time.perf_counter() - t0:.2f}s")
