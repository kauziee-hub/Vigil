# Target Architecture — PRIMA / Vigil

**PRIMA** (Pre-commitment Risk Intelligence & Mitigation Architecture) is the architecture.
**Vigil** is this working implementation.

> Given everything we know at this exact moment, what should happen **before** this customer irreversibly commits this payment?

Vigil is not a fraud classifier and does not replace RBI/RBIH (MuleHunter.AI, DPIP), NPCI, I4C or bank EFRMS/AML. It **consumes** that kind of intelligence (simulated here), adds its own network, journey, behaviour and context evidence, and turns the result into a **proportionate, explained intervention at the last reversible moment** — then watches where the money goes afterwards and feeds that back into the next decision.

---

## 1. One lifecycle, two stages

```
 PAY UI / scenario / ambient stream
            │  POST /api/intents          (no money moves)
            ▼
 ┌─────────────────────── PRE-COMMIT (Vigil decision engine) ───────────────────────┐
 │ TransactionIntent CREATED                                                          │
 │   ├─ A  ExternalIntel   (ExternalFraudIntelProvider → LocalRegistryProvider)       │
 │   ├─ B  RingWatch       (recipient network: PathGraph, fraud labels, TaintTrace)   │
 │   ├─ C  TrailScore      (sender journey: ordered events in window)                 │
 │   ├─ D  Behaviour       (sender history: amount z, new payee, velocity, balance %) │
 │   ├─ E  (transaction characteristics fold into D)                                  │
 │   └─ F  ContextFlag     (SIMULATED call/message context + payment note)            │
 │ → RiskFusion (config/risk_policy.yaml, versioned) → ReasonLine (3 audiences)       │
 │ → InterruptLadder T0..T4 → RISK_EVALUATED → APPROVED | CHALLENGED | HELD | ESCALATED│
 └──────────────────────────────────────────────────────────────────────────────────┘
            │ user acknowledges (T1/T2) · bank releases (T3/T4) · contact responds (T4)
            ▼
 PaymentProvider (simulated rail)  PAYMENT_INITIATED → PAYMENT_SUCCEEDED/FAILED
            │
            ▼
 ┌──────────────────────── POST-COMMIT (monitoring) ─────────────────────────────────┐
 │ ledger posting (integer paise, debit+credit) → PathGraph.add_edge (incremental)    │
 │ → RingWatch re-evaluates touched accounts → TaintTrace re-runs if labels exist     │
 │ → MONITORED. Next intent to any touched account sees the new evidence instantly.   │
 └──────────────────────────────────────────────────────────────────────────────────┘
```

### Intent state machine (persisted, every transition is a row in `intent_transitions`)

```
CREATED → RISK_EVALUATED → APPROVED ───────────────┐
                         → CHALLENGED → APPROVED ──┤  (user acknowledged / confirmed purpose)
                         │            → CANCELLED  │
                         → HELD       → APPROVED ──┤  (bank released)
                         │            → REJECTED   │  (bank rejected)  /  CANCELLED (user)
                         → ESCALATED  → APPROVED ──┤  (bank released after contact response)
                                      → REJECTED / CANCELLED
APPROVED → PAYMENT_INITIATED → PAYMENT_SUCCEEDED → MONITORED
                             → PAYMENT_FAILED  (retry → PAYMENT_INITIATED)
```

Tier → initial state: T0 → APPROVED (auto-pays), T1 → CHALLENGED(kind=inform), T2 → CHALLENGED(kind=confirm_purpose), T3 → HELD, T4 → ESCALATED.
A ScopedHold applies **only to this intent's amount**. Inbound money is never held. There is no account-freeze function anywhere.

## 2. Repository layout and ownership

```
Fraud Detection/
├─ AGENT_HANDOFF/           prompts, outputs, STATE.md (resume point for any agent)
├─ config/risk_policy.yaml  THE policy: weights, thresholds, windows, ladder (versioned)
├─ backend/
│  ├─ prima/                vendored lineage library (unchanged) — TaintTrace math
│  ├─ vigil/
│  │  ├─ contracts.py       Pydantic contracts (single source of truth)        [Claude 1]
│  │  ├─ settings.py        env + policy loader, policy version hash           [Claude 1]
│  │  ├─ db.py, schema.sql  sqlite3 WAL, schema, indexes, helpers              [Claude 1]
│  │  ├─ clock.py, ids.py   UTC ISO-8601 'Z' time, readable sequential ids     [Claude 1]
│  │  ├─ graph/pathgraph.py incremental in-memory adjacency                    [Claude 1]
│  │  ├─ risk/              ringwatch, trailscore, behaviour, contextflag,      [Claude 2]
│  │  │                     external_intel, fusion, reasonline, taint
│  │  ├─ engine/            intents (orchestrator), ladder, holds, breaker     [Claude 1]
│  │  ├─ payments/          PaymentProvider port + simulated rail          [Claude 1]
│  │  ├─ sim/               seed (deterministic), scenarios, ambient           [Claude 1 / Codex]
│  │  ├─ realtime.py        WebSocket topic hub                                [Claude 1]
│  │  └─ api/               FastAPI routers                                    [Claude 1]
│  └─ tests/                lineage (ported 200+), risk, lifecycle, scenarios, api
├─ frontend/                Vite + React + TS + Cytoscape(dagre)               [Claude 3]
├─ scripts/                 benchmark_demo.py, reset_demo.py                   [Codex]
├─ run_demo.ps1 / run_demo.sh                                                  [Claude 1]
└─ docs/
```

## 3. Stack (chosen for reliability on one laptop, offline)

| Concern | Choice | Why |
|---|---|---|
| Backend | FastAPI, single process, async handlers doing short synchronous SQLite work | One thread owns the DB → no locking bugs; every request is < 50 ms |
| DB | SQLite (WAL), stdlib `sqlite3`, `data/vigil.db` | No ORM: fewer moving parts, explicit SQL, fast |
| Graph | `PathGraph` — in-memory adjacency dicts loaded once at startup, appended on every settle | No per-request rebuild, no NetworkX |
| Lineage | `prima.attribution.trace_multi` (LIBR + pro-rata) | Conserving, deterministic, already tested |
| Realtime | One WebSocket `/ws?topics=…` with topic hub | Push only; no polling |
| Frontend | Vite + React 18 + TS, built and **served by FastAPI on the same port** | One URL, works from a phone on the LAN, no CORS, no scattered localhost URLs |
| Graph UI | Cytoscape.js + dagre (left→right money flow), layout computed once | No physics loop; evidence, not decoration |
| Payments | `PaymentProvider` port → `MockPaymentProvider` (simulated rail, offline, labelled) | The provider is called only after approval; a bank plugs its own rail into the port |
| ML | **None on the decision path.** Behaviour uses robust statistics (median/MAD z-score) | See `MODEL_CARD.md` |

## 4. Conventions (non-negotiable)

* Money: **integer paise** everywhere (`*_paise`). Never floats for balances.
* Time: UTC, ISO-8601 with milliseconds and `Z` (`2026-10-06T10:15:30.123Z`). Stored as TEXT; sortable.
* IDs: readable sequential — `ACC-…` handles for accounts use the UPI-style handle as id (`ramesh@vigil`), `INT-000001`, `DEC-000001`, `TX-000001`, `EV-…`, `ALR-…`, `CB-…`, `LBL-…`.
* Scores: floats in [0,1], rounded to 3 dp in API output. Contributions sum exactly to `base_score`.
* Errors: every non-2xx is `{"error": {"code": "snake_case", "message": "human text", "details": {...}?}}`.
* Policy lives only in `config/risk_policy.yaml`. The frontend never hard-codes thresholds; it reads `/api/policy`.
* Backend is the source of truth. Frontend types in `frontend/src/api/types.ts` mirror `contracts.py` and nothing else.

## 5. Contracts (`backend/vigil/contracts.py`)

```python
TransactionIntent { intent_id, sender_id, recipient_id, amount_paise, note?, context_text?,
                    channel, device_id, source: "user"|"scenario"|"ambient",
                    state: IntentState, tier?, decision_id?, payment?: PaymentInfo,
                    created_at, updated_at }
RiskSignal        { rule_id, dimension: external|network|sequence|behaviour|context,
                    label (short), reason (human sentence), evidence: {raw values},
                    contribution: float 0..1 (to its dimension score) }
DimensionScore    { dimension, score 0..1, weight, contribution (=weight*score), signals: [RiskSignal] }
RiskDecision      { decision_id, intent_id, sender_id, recipient_id, amount_paise, created_at,
                    dimensions: [DimensionScore], base_score, adjustments: [PolicyAdjustment],
                    final_score, tier 0..4, intervention: Intervention, rules_fired: [rule_id],
                    reasons: ReasonLine, policy_version, latency_ms, payload_sha256 }
PolicyAdjustment  { rule_id, kind: "corroboration"|"floor"|"cap", effect, reason }
Intervention      { tier, kind: pass|inform|confirm_purpose|scoped_hold|hold_and_circuit_breaker,
                    title, customer_action, bank_action, hold_paise, circuit_breaker: bool }
ReasonLine        { customer: {headline, facts[], what_happens_next},
                    analyst: {summary, top_dimensions[], signals[], journey[], external[], network[]},
                    audit: {…exact inputs, scores, policy_version, ts, action…} }
GraphEvidence     { nodes: [{id,label,kind,risk,flags[],role?,balance_paise,labelled,attributable_paise}],
                    edges: [{id,source,target,amount_paise,count,first_ts,last_ts,tainted_paise,highlight}],
                    focus?, truncated: bool, total_nodes }
ExternalIntel     { identifier, status: clean|reported|confirmed_mule|watchlist, risk_score 0..1,
                    reason_codes[], source, last_updated, simulated: true }
ScenarioEvent     { scenario_id, run_id, step, total_steps, kind, title, detail, ts, state: running|paused|done }
```

## 6. Database (SQLite, `backend/vigil/schema.sql`)

`accounts`, `devices` (via `accounts.primary_device` + `account_devices`), `payees`, `transactions` (ledger: seq, debit+credit in one row, `kind`=transfer|external_credit|external_debit), `transaction_intents`, `intent_transitions`, `events` (journey), `risk_decisions` (append-only, full JSON), `alerts` (interventions T≥1), `scoped_holds`, `trusted_contacts`, `circuit_breaker_events`, `external_intel`, `fraud_labels`, `taint_runs`, `scenario_runs`, `payment_attempts`, `meta`.
Indexes: `transactions(sender_id,ts)`, `transactions(recipient_id,ts)`, `events(account_id,ts)`, `risk_decisions(intent_id)`, `alerts(account_id,ts)`, `transaction_intents(sender_id,created_at)`.

## 7. Risk dimensions (owner: Claude 2)

| Dimension | Inputs | Example rules (each returns rule_id, reason, evidence, contribution) |
|---|---|---|
| external | `external_intel` row for recipient via provider | `EXT_CONFIRMED`, `EXT_REPORTED`, `EXT_WATCHLIST` |
| network | PathGraph windows on the **recipient**, fraud labels, taint claims | `NET_FAN_IN`, `NET_PASS_THROUGH`, `NET_FAN_OUT`, `NET_CIRCULAR`, `NET_SMURFING`, `NET_VELOCITY_CHAIN`, `NET_SHARED_DEVICE`, `NET_DORMANT_WAKE`, `NET_NEW_ACCOUNT_INFLOW`, `NET_LABELLED_NEIGHBOUR`, `NET_TAINT_EXPOSURE` |
| sequence | sender `events` in window, ordered chain | `SEQ_NEW_DEVICE`, `SEQ_PAYEE_ADDED`, `SEQ_LIMIT_RAISED`, `SEQ_CREDENTIAL_CHANGE`, `SEQ_SCREEN_SHARE`, `SEQ_ORDERED_CHAIN` |
| behaviour | sender settled history | `BEH_AMOUNT_OUTLIER`, `BEH_FIRST_TIME_PAYEE`, `BEH_BALANCE_DRAIN`, `BEH_NEW_PAYEE_BURST`, `BEH_VELOCITY`, `BEH_DORMANT_SENDER`, `BEH_ODD_HOUR` |
| context | simulated context events in window + note | `CTX_URGENCY`, `CTX_SECRECY`, `CTX_FEAR_AUTHORITY`, `CTX_GREED`, `CTX_BYPASS` |

Dimension score = `min(1, Σ signal.contribution)`. Contributions are set in the policy file.

## 8. Fusion and ladder (`config/risk_policy.yaml`)

```
base   = Σ weight_d × score_d                         (weights sum to 1, shown as contributions)
adjust = corroboration bonus when ≥2 dimensions ≥ 0.5 (+0.08 per extra dimension)
floors = EXT confirmed_mule → ≥T3 ;  NET_TAINT_EXPOSURE ≥ threshold → ≥T3
caps   = friction guard: established payee (≥3 prior payments) AND sequence < 0.3 AND context < 0.3
         AND external clean → tier ≤ 1
         T4 requires sender-side evidence (sequence ≥ 0.5 or context ≥ 0.5); otherwise cap at T3
tier   = ladder thresholds on final score
```

Every adjustment is a named `PolicyAdjustment` in the decision record so an analyst can see exactly which evidence changed the outcome. The decision also reports a **counterfactual**: the tier that would result if the strongest dimension were removed.

## 9. API surface (all JSON, prefix `/api`)

| Method & path | Purpose |
|---|---|
| `GET /health` | status, provider mode, policy version, counts |
| `GET /policy` | policy (weights, ladder) for UI legends |
| `GET /accounts?role=customer` · `GET /accounts/{id}` | accounts, balances, payees, trusted contact |
| `POST /intents` | create + evaluate (returns intent + decision) |
| `GET /intents/{id}` · `GET /intents?limit=` | intent with transitions |
| `POST /intents/{id}/acknowledge` | T1/T2 (`purpose` required at T2) |
| `POST /intents/{id}/cancel` | customer cancels |
| `POST /intents/{id}/bank-action` | `release` / `reject` (analyst) |
| `GET /decisions/{id}` | full decision (3 representations) |
| `GET /alerts` | interventions queue |
| `GET /investigate/{decision_id}` | everything the investigation view needs |
| `GET /graph/suspicious` · `GET /graph/neighborhood/{account}` | GraphEvidence, capped |
| `GET /accounts/{id}/timeline` | journey events + payments |
| `POST /labels` | mark a transaction confirmed fraud → TaintTrace |
| `GET /taint` | latest TaintTrace result (claims, hops, conservation) |
| `GET /metrics` | command-center numbers |
| `GET /scenarios` · `POST /scenarios/{id}/start|pause|resume|reset` · `GET /scenarios/{id}/explain` | scenario control |
| `POST /demo/reset` | deterministic reset to baseline |
| `POST /ambient` `{enabled}` | background stream toggle |
| `GET /contact/{token}` · `POST /contact/{token}/respond` | trusted-contact page |
| `WS /ws?topics=console,pay:<acct>,contact:<token>` | realtime push |

## 10. Performance design

* PathGraph loaded once; settle appends an edge (O(1)); RingWatch reads only the recipient's adjacency in a time window (bounded).
* Risk evaluation touches ~6 indexed queries; target p95 < 50 ms (budget 150 ms).
* TaintTrace (`trace_multi` over all journals) runs only when a label is added, then cached; claims are read from the cache by RingWatch.
* Graph endpoints return ≤ 60 nodes, aggregated edges; frontend lays out once (dagre), never animates physics.
* `scripts/benchmark_demo.py` reports p50/p95 risk latency, graph query time, scenario processing time.

## 11. Explicitly out of scope

Blockchain, 3D graphs, GNN, LLM explanations or chat, multi-bank federation, telecom integration, real RBI/NPCI APIs, microservices, cloud deployment, KYC, biometrics, voice analysis.
