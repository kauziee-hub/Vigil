"""Reproducible demo scenarios. Nothing depends on random chance or timing.

Time-of-day rules see a pinned local hour (clock.DEMO_LOCAL_HOUR_IST) while a scenario step runs,
so a scenario gives the same tier at 01:00 as at 14:00; the decision record says so.

Every scenario uses the real pipeline: journey events go into `events`,
observed money movements go through `ledger.post`, and payment attempts go
through the Payment Intent Gateway (`lifecycle.create`) exactly like the Pay UI.

Scenario 3 is time-compressed: its journey events are back-dated (−8 … −1 min)
so the 8-minute story plays in seconds. The UI says so.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from vigil import clock, db
from vigil.contracts import CreateIntentRequest, ScenarioEvent
from vigil.engine import ledger, lifecycle
from vigil.graph.pathgraph import GRAPH
from vigil.realtime import HUB
from vigil.risk import ringwatch
from vigil.sim import runs as runs_mod
from vigil.sim import seed as seed_mod

COERCION_CONTEXT = (
    "SIMULATED CALL TRANSCRIPT — Caller: 'This is Inspector Sharma, Mumbai cyber police. A warrant has been issued "
    "in your name for money laundering. You are under digital arrest. Do not tell anyone, not even your family. "
    "Transfer your savings to the RBI verification account immediately or officers will arrest you today.'"
)


@dataclass
class Step:
    kind: str
    title: str
    detail: str
    action: Callable[[], Any] | None = None


@dataclass
class Scenario:
    id: str
    name: str
    act: str
    summary: str
    expected: str
    explain: list[str]
    steps: Callable[[], list[Step]]
    payer: str | None = None
    category: str = "payment"                       # payment | attack | control
    accounts_fn: Callable[[], list[str]] | None = None
    tag: str | None = None                          # seed_attack tag on its ledger postings


def _event(account_id: str, event_type: str, minutes_ago: float, payload: dict | None = None) -> None:
    ts = clock.iso(clock.now() - timedelta(minutes=minutes_ago))
    with db.tx():
        db.insert("events", {"id": db.next_id("EV"), "account_id": account_id, "event_type": event_type,
                             "payload": db.dumps(payload or {}), "ts": ts, "source": "scenario"})
        if event_type == "login_new_device" and payload and payload.get("device_id"):
            db.execute("INSERT OR IGNORE INTO account_devices(account_id, device_id, first_seen) VALUES (?,?,?)",
                       (account_id, payload["device_id"], ts))
            GRAPH.add_device(account_id, payload["device_id"])
        if event_type == "limit_raised" and payload:
            db.execute("UPDATE accounts SET daily_limit_paise = ? WHERE id = ?", (payload["new_limit_paise"], account_id))
        if event_type == "payee_added" and payload:
            db.execute("INSERT OR IGNORE INTO payees(account_id, payee_id, added_at) VALUES (?,?,?)",
                       (account_id, payload["payee_id"], ts))
    HUB.publish("console", "journey.event", {"account_id": account_id, "event_type": event_type, "ts": ts})


def _intent(sender: str, recipient: str, amount: int, note: str | None = None, context: str | None = None,
            device: str | None = None) -> dict[str, Any]:
    intent, decision = lifecycle.create(CreateIntentRequest(
        sender_id=sender, recipient_id=recipient, amount_paise=amount, note=note, context_text=context,
        device_id=device, source="scenario"))
    return {"intent_id": intent.intent_id, "decision_id": decision.decision_id, "tier": decision.tier,
            "state": intent.state.value, "final_score": decision.final_score}


def _observed(sender: str, recipient: str, amount: int, note: str, kind: str = "transfer") -> dict[str, Any]:
    tx = ledger.post(sender_id=sender, recipient_id=recipient, amount_paise=amount, kind=kind, note=note,
                     source="scenario", seed_attack="mule_ring")
    HUB.publish("console", "ledger.posted", tx)
    return {"transaction_id": tx["id"]}


def _ring_scan() -> dict[str, Any]:
    rows = ringwatch.scan(min_score=0.4)
    HUB.publish("console", "ringwatch.scan", {"flagged": rows[:12]})
    return {"flagged": [r["account_id"] for r in rows[:8]]}


# ── scenario definitions ──────────────────────────────────────────────────
def _s0() -> list[Step]:
    return [Step("intent", "Ramesh pays Meena General Stores ₹500",
                 "Known recipient (13 previous payments), usual amount, known device.",
                 lambda: _intent("ramesh@vigil", "meena.grocer@vigil", 500_00, note="groceries"))]


def _s1() -> list[Step]:
    return [Step("intent", "Ramesh tries to pay Kiran Traders ₹45,000",
                 "First payment to a 9-day-old account that already forwards money quickly and is reported in the (simulated) registry.",
                 lambda: _intent("ramesh@vigil", "kiran.traders@vigil", 45_000_00, note="advance for goods"))]


def _s2() -> list[Step]:
    victims = list(zip(seed_mod.VICTIMS, [48_000_00, 55_000_00, 38_000_00, 62_000_00, 45_000_00]))
    steps = [Step("info", "Background activity continues", "Ordinary customers keep paying their usual payees.")]
    for victim, amount in victims:
        steps.append(Step("transaction", f"Fan-in: {victim.split('@')[0]} → kiran.traders ₹{amount // 100:,}",
                          "Victim pays the collector after a fake 'investment' call (observed transfer).",
                          lambda v=victim, a=amount: _observed(v, "kiran.traders@vigil", a, "investment deposit")))
    steps += [
        Step("transaction", "Pass-through: kiran.traders → zenith.exports ₹2,30,000",
             "Collected money leaves within minutes.",
             lambda: _observed("kiran.traders@vigil", "zenith.exports@vigil", 2_30_000_00, "supplier payment")),
        Step("transaction", "Split: zenith.exports → pooja.m ₹60,000", "Layering.",
             lambda: _observed("zenith.exports@vigil", "pooja.m@vigil", 60_000_00, "consulting")),
        Step("transaction", "Split: zenith.exports → rahul.m ₹55,000", "Layering.",
             lambda: _observed("zenith.exports@vigil", "rahul.m@vigil", 55_000_00, "consulting")),
    ]
    for target in seed_mod.SMURF_TARGETS:
        steps.append(Step("transaction", f"Smurfing: zenith.exports → {target.split('@')[0]} ₹9,500",
                          "Many transfers just below ₹10,000.",
                          lambda t=target: _observed("zenith.exports@vigil", t, 9_500_00, "refund")))
    steps += [
        Step("transaction", "Cash-out: zenith.exports → ATM ₹70,000", "Value leaves the bank's view.",
             lambda: _observed("zenith.exports@vigil", "ext:atm", 70_000_00, "cash", kind="external_debit")),
        Step("transaction", "Cash-out: pooja.m → ATM ₹58,000", "Downstream mule withdraws.",
             lambda: _observed("pooja.m@vigil", "ext:atm", 58_000_00, "cash", kind="external_debit")),
        Step("detect", "RingWatch scans the touched accounts",
             "Fan-in, pass-through, smurfing and shared-device rules fire on the relevant accounts only.", _ring_scan),
        Step("info", "Next: confirm the source as a scam",
             "In the Network view, click 'Confirm source scam' on anita.s → kiran.traders (simulates a verified 1930/NCRP "
             "report). TaintTrace then shows where that money went."),
    ]
    return steps


def _s3() -> list[Step]:
    return [
        Step("event", "08 min ago — new device sign-in", "Sunita's account signs in on a phone it has never seen.",
             lambda: _event("sunita@vigil", "login_new_device", 8, {"device_id": "dev-unknown-oneplus", "city": "Pune"})),
        Step("event", "06 min ago — payee added", "RK Legal Services (opened 2 days ago) is added as a payee.",
             lambda: _event("sunita@vigil", "payee_added", 6, {"payee_id": "rk.legal.services@vigil"})),
        Step("event", "04 min ago — transfer limit raised", "Daily limit raised from ₹1,00,000 to ₹10,00,000.",
             lambda: _event("sunita@vigil", "limit_raised", 4, {"old_limit_paise": 10_000_000, "new_limit_paise": 100_000_000})),
        Step("event", "02 min ago — simulated call context", "SIMULATED: an 'Inspector Sharma' threatens 'digital arrest'.",
             lambda: _event("sunita@vigil", "simulated_context", 2, {"text": COERCION_CONTEXT, "channel": "simulated call",
                                                                     "simulated": True})),
        Step("intent", "Now — Sunita tries to send 95% of her savings",
             "Payment intent to RK Legal Services from the new device.",
             lambda: _intent("sunita@vigil", "rk.legal.services@vigil",
                             (ledger.available_paise("sunita@vigil") * 95 // 100) // 100_00 * 100_00,
                             note="RBI verification", device="dev-unknown-oneplus")),
    ]


def _s4() -> list[Step]:
    return [Step("intent", "Ramesh pays his landlord ₹1,20,000",
                 "Large and unusual amount — but known payee (3 rent payments), known device, clean registry, no journey changes.",
                 lambda: _intent("ramesh@vigil", "landlord.iyer@vigil", 1_20_000_00, note="deposit + October rent"))]


SCENARIOS: dict[str, Scenario] = {
    "s0": Scenario("s0", "Normal payment", "Act 1", "Known recipient, normal amount, known device.",
                   "Tier 0 — approved instantly, zero friction.",
                   ["Every payment is evaluated, but most pass silently.",
                    "No dimension fires: recipient is a long-standing payee, amount is typical, no journey changes.",
                    "Proves the system is not a nag: friction is reserved for evidence."], _s0, "ramesh@vigil"),
    "s1": Scenario("s1", "Risky recipient", "Act 2", "Sender behaves normally; the recipient carries the risk.",
                   "Tier 2 — customer must confirm purpose before anything is sent.",
                   ["External intelligence (SIMULATED registry) reports the recipient.",
                    "RingWatch: 9-day-old account, money forwarded within ~15 minutes (pass-through).",
                    "Behaviour: first payment to this recipient, far above Ramesh's usual amounts.",
                    "Intervention happens BEFORE the provider is called: nothing has moved."], _s1, "ramesh@vigil"),
    "s2": Scenario("s2", "Money-mule network", "Act 3",
                   "Fan-in → rapid pass-through → split/smurfing → cash-out, injected as observed transfers.",
                   "RingWatch flags only the ring; after a confirmed label, TaintTrace attributes value downstream "
                   "and Kiran Traders' risk rises for the next payment (Tier 2 → Tier 3).",
                   ["Five victims pay the collector (fan-in from first-time senders).",
                    "Collector forwards within minutes (pass-through) to a layering account.",
                    "Layering account splits, smurfs below ₹10,000 and cashes out.",
                    "Confirming one victim payment as a scam runs TaintTrace (LIBR + pro rata, conserving).",
                    "Post-payment learning: the next payment to any of these accounts sees the new evidence."], _s2, None),
    "s3": Scenario("s3", "Coerced / digital-arrest payment", "Act 4",
                   "new device → new payee → limit raised → simulated threat call → 95% of savings.",
                   "Tier 4 — scoped hold + CircuitBreaker alert to Arjun (son) live on his phone.",
                   ["None of these events alone proves anything.",
                    "TrailScore: the ordered chain within 8 minutes is the signal.",
                    "Behaviour: 95% of balance, first-time payee, far above her usual payments.",
                    "ContextFlag (SIMULATED context): fear/authority, secrecy, urgency, 'verification account'.",
                    "Only this amount is held; her account keeps working. Arjun receives facts, not accusations."],
                   _s3, "sunita@vigil"),
    "s4": Scenario("s4", "False-positive control", "Control",
                   "Big payment, but everything about the relationship is normal.",
                   "Tier 0 — approved. The amount anomaly is noted but does not create friction.",
                   ["Behaviour notes the amount is unusually large.",
                    "Known payee, known device, no journey changes, clean registry → friction guard applies.",
                    "This is the control that shows we care about customer friction."], _s4, "ramesh@vigil"),
}


# ── runner ────────────────────────────────────────────────────────────────
@dataclass
class Run:
    scenario_id: str
    run_id: str
    steps: list[Step]
    step: int = 0
    state: str = "running"
    log: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task | None = None
    resume: asyncio.Event = field(default_factory=asyncio.Event)


RUNS: dict[str, Run] = {}
STEP_DELAY_S = 1.1


def status() -> list[dict[str, Any]]:
    out = []
    for s in SCENARIOS.values():
        run = RUNS.get(s.id)
        out.append({"id": s.id, "name": s.name, "act": s.act, "summary": s.summary, "expected": s.expected,
                    "payer": s.payer, "category": s.category, "state": run.state if run else "idle",
                    "step": run.step if run else 0, "total_steps": len(run.steps) if run else len(s.steps()),
                    "log": run.log if run else []})
    return out


def _emit(run: Run, step: Step, result: Any) -> None:
    ev = ScenarioEvent(scenario_id=run.scenario_id, run_id=run.run_id, step=run.step, total_steps=len(run.steps),
                       kind=step.kind, title=step.title, detail=step.detail, ts=clock.now_iso(), state=run.state)
    entry = {**ev.model_dump(), "result": result}
    run.log.append(entry)
    HUB.publish("console", "scenario.step", entry)


async def _execute(run: Run) -> None:
    try:
        while run.step < len(run.steps):
            if run.state == "paused":
                await run.resume.wait()
            step = run.steps[run.step]
            run.step += 1
            with clock.pinned_local_hour():
                result = step.action() if step.action else None
            runs_mod.after_step(run.run_id, result)
            if run.step == len(run.steps):
                run.state = "done"
            _emit(run, step, result)
            if run.state != "done":
                await asyncio.sleep(STEP_DELAY_S)
        if run.run_id in runs_mod.RUNS:
            # detection keeps working after the last posting: watch for a short grace period
            runs_mod.mark_evaluating(run.run_id)
            for _ in range(int(runs_mod.GRACE_S / 0.5)):
                await asyncio.sleep(0.5)
                runs_mod.poll(run.run_id)
            runs_mod.finish(run.run_id)
    except Exception as exc:  # surface, never crash the server
        run.state = "done"
        HUB.publish("console", "scenario.error", {"scenario_id": run.scenario_id, "error": str(exc)})


def start(scenario_id: str) -> dict[str, Any]:
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ledger.VigilError(404, "unknown_scenario", f"No scenario '{scenario_id}'.")
    current = RUNS.get(scenario_id)
    if current and current.state in {"running", "paused"}:
        raise ledger.VigilError(409, "already_running", "This scenario is already running.")
    run = Run(scenario_id=scenario_id, run_id=db.next_id("RUN"), steps=scenario.steps())
    RUNS[scenario_id] = run
    runs_mod.begin(scenario_id, run.run_id, scenario.name, scenario.category, len(run.steps))
    HUB.publish("console", "scenario.started", {"scenario_id": scenario_id, "run_id": run.run_id,
                                                "total_steps": len(run.steps)})
    run.task = asyncio.get_event_loop().create_task(_execute(run))
    return {"scenario_id": scenario_id, "run_id": run.run_id, "state": run.state}


def pause(scenario_id: str) -> dict[str, Any]:
    run = RUNS.get(scenario_id)
    if not run or run.state != "running":
        raise ledger.VigilError(409, "not_running", "Scenario is not running.")
    run.state = "paused"
    run.resume.clear()
    runs_mod.set_paused(run.run_id, True)
    HUB.publish("console", "scenario.paused", {"scenario_id": scenario_id})
    return {"scenario_id": scenario_id, "state": run.state}


def resume(scenario_id: str) -> dict[str, Any]:
    run = RUNS.get(scenario_id)
    if not run or run.state != "paused":
        raise ledger.VigilError(409, "not_paused", "Scenario is not paused.")
    run.state = "running"
    run.resume.set()
    runs_mod.set_paused(run.run_id, False)
    HUB.publish("console", "scenario.resumed", {"scenario_id": scenario_id})
    return {"scenario_id": scenario_id, "state": run.state}


def cancel_all() -> None:
    for run in RUNS.values():
        if run.task and not run.task.done():
            run.task.cancel()
    RUNS.clear()
    runs_mod.clear()


def run_sync(scenario_id: str) -> list[Any]:
    """Execute all steps immediately (tests, benchmark, CLI). Attack scenarios are evaluated as a run."""
    sc = SCENARIOS[scenario_id]
    steps = sc.steps()
    run_id = f"SYNC-{scenario_id}-{len(runs_mod.ORDER) + 1}"
    runs_mod.begin(scenario_id, run_id, sc.name, sc.category, len(steps))
    results = []
    with clock.pinned_local_hour():
        for step in steps:
            result = step.action() if step.action else None
            runs_mod.after_step(run_id, result)
            results.append(result)
    runs_mod.finish(run_id)
    return results


def touched_accounts(scenario_id: str) -> list[str]:
    """Accounts a scenario involves (frozen interface for vigil.intel compare)."""
    static = {
        "s0": ["ramesh@vigil", "meena.grocer@vigil"],
        "s1": ["ramesh@vigil", "kiran.traders@vigil"],
        "s2": [*seed_mod.VICTIMS, "kiran.traders@vigil", "zenith.exports@vigil", *seed_mod.DOWNSTREAM,
               *seed_mod.SMURF_TARGETS],
        "s3": ["sunita@vigil", "rk.legal.services@vigil"],
        "s4": ["ramesh@vigil", "landlord.iyer@vigil"],
    }
    if scenario_id in static:
        return static[scenario_id]
    sc = SCENARIOS.get(scenario_id)
    if sc is not None and sc.accounts_fn is not None:
        return list(dict.fromkeys(sc.accounts_fn()))
    raise ledger.VigilError(404, "unknown_scenario", f"No scenario '{scenario_id}'.")


def explain(scenario_id: str) -> dict[str, Any]:
    s = SCENARIOS.get(scenario_id)
    if s is None:
        raise ledger.VigilError(404, "unknown_scenario", f"No scenario '{scenario_id}'.")
    run = RUNS.get(scenario_id)
    produced = [entry["result"] for entry in (run.log if run else []) if isinstance(entry.get("result"), dict)
                and entry["result"].get("decision_id")]
    return {"id": s.id, "name": s.name, "act": s.act, "summary": s.summary, "expected": s.expected,
            "explain": s.explain, "decisions": produced,
            "time_compressed": s.id == "s3", "simulated_inputs": s.id in {"s2", "s3"}}


def replay_events(scenario_id: str) -> list[dict[str, Any]]:
    """Ordered events of the scenario for graph/time replay: tagged ledger postings + journey events + intents."""
    sc = SCENARIOS[scenario_id]
    tag = sc.tag or scenario_id
    events: list[dict[str, Any]] = []
    for t in db.q("SELECT id, ts, sender_id, recipient_id, amount_paise, channel, kind FROM transactions "
                  "WHERE seed_attack = ? AND source = 'scenario' ORDER BY seq", (tag,)):
        events.append({"ts": t["ts"], "kind": "transaction", "title": f"{t['sender_id']} -> {t['recipient_id']}",
                       "tx_id": t["id"], "source": t["sender_id"], "target": t["recipient_id"],
                       "amount_paise": t["amount_paise"]})
    run = RUNS.get(scenario_id)
    for entry in (run.log if run else []):
        result = entry.get("result")
        if entry["kind"] in {"event", "intent", "info", "detect"}:
            events.append({"ts": entry["ts"], "kind": entry["kind"], "title": entry["title"], "tx_id": None,
                           "source": None, "target": None,
                           "amount_paise": None if not isinstance(result, dict) else result.get("amount_paise")})
    events.sort(key=lambda e: e["ts"])
    return events


# ── registry: payment scenarios first, then the ten attack patterns ──
SCENARIOS["s0"].category = "payment"
SCENARIOS["s1"].category = "payment"
SCENARIOS["s2"].category = "attack"
SCENARIOS["s2"].tag = "mule_ring"
SCENARIOS["s3"].category = "payment"
SCENARIOS["s4"].category = "control"

from vigil.sim import attacks as _attacks  # noqa: E402  (registers after base classes exist)

SCENARIOS.update(_attacks.build())
