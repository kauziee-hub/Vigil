# MASTER PROMPT (verbatim from user, 2026-10-06)

Source projects attached:
- C:\Users\KausikGH\Documents\Projects\Indian Bank Project\ccmule-main            (money-mule detector, "Sentinel" frontend)
- C:\Users\KausikGH\Documents\Projects\Indian Bank Project\Indian Bank Project - Actual ML - Laggy  (older ML variant of the same)
- C:\Users\KausikGH\Documents\Projects\PRIMA                                      (PRIMA / Vigil)
Target workspace: C:\Users\KausikGH\Documents\Projects\Fraud Detection

User addendum: "ALL THE PROJECT FOLDERS THAT ARE REQUIRED ARE ATTACHED. WHAT EVER PROMPT IS GIVEN TO YOU AND WHAT OUTPUT YOU ARE GIVING SAVE IT IN A FOLDER EXPLICITLY IN THE DIRECTORY SO THAT I CAN SHIFT BETWEEN AGENTS IT CAN CONTINUE"

---

You are the LEAD ARCHITECT AND IMPLEMENTATION OWNER for this project.
I am giving you everything I currently have from TWO previous hackathon projects:

1. A MONEY MULE / FRAUD NETWORK DETECTION PROJECT
   * synthetic/background banking transactions
   * accounts and transaction graph
   * attack injection
   * mule/ring/fan-in/fan-out/pass-through/shared-device/velocity/etc. detection
   * tainted-money tracing
   * ML/rules/risk scoring
   * graph visualization
   * risk memory/adaptive logic where available
2. PRIMA / VIGIL
   * pre-commitment risk assessment
   * warn a customer BEFORE transferring money to a risky recipient
   * sequence/context/network intelligence
   * graduated interventions instead of simply "fraud/not fraud"
   * ReasonLine
   * TrailScore
   * ContextFlag
   * CircuitBreaker
   * ScopedHold
   * Razorpay integration attempt
   * bank/admin/user views
   * regulatory / India fintech positioning

These were hackathon prototypes. DO NOT assume their present architecture, code quality, UX, ML validity, naming, database, or design is good.
You have permission to refactor, delete, merge, simplify or replace components where justified.
We have effectively ONE DAY.
The objective is NOT: "combine two repositories and make more features."
The objective is: BUILD ONE POLISHED, FAST, TECHNICALLY CREDIBLE FINTECH MVP IN WHICH EVERY MAJOR COMPONENT HAS AN OBVIOUS PURPOSE.

Architecture: PRIMA — Pre-commitment Risk Intelligence & Mitigation Architecture
Product: Vigil — A working implementation of PRIMA.

Core thesis: Traditional fraud systems can produce risk intelligence. Vigil answers the next question:
"Given everything we know at this exact moment, what should happen BEFORE this customer irreversibly commits this payment?"

Vigil must NOT be presented as replacing RBI, NPCI, MuleHunter.ai, DPIP, bank EFRMS or AML systems.
Real-world positioning:

```
BANK / PAYMENT APP
| transaction intent
↓
existing bank intelligence (MuleHunter / EFRMS / AML / DPIP-style intelligence)
+ Vigil's own network, sequence and behavioural signals
↓
VIGIL PRE-COMMIT DECISION ENGINE
↓
PASS / EXPLAIN / CHALLENGE / HOLD / ESCALATE
↓
PAYMENT PROVIDER / PAYMENT RAIL
↓
POST-TRANSACTION GRAPH MONITORING
```

MuleHunter.ai is already intended for mule detection. DPIP is already intended for shared fraud intelligence.
Therefore DO NOT build a project whose claim is "we use AI to detect mule accounts better than RBI."
Our novelty/value should instead be:
1. combining multiple intelligence dimensions at PAYMENT COMMIT TIME;
2. converting risk into proportionate intervention;
3. explaining exactly WHY intervention happened;
4. tracing suspicious movement after payment;
5. closing the loop between pre-payment prevention and post-payment network detection.

DO NOT immediately start rewriting. Read BOTH projects completely.
Inspect: README/docs, backend, frontend, database/schema, ML models, notebooks, graph logic, APIs, transaction simulator, attack injector, Razorpay code, WebSockets/SSE/realtime, Supabase/Firebase/Postgres/etc., config/env handling, visualization, build scripts, tests, dependencies, duplicated implementations, dead code, hardcoded data, fake/demo-only paths, APIs that never actually connect, buttons that merely animate success, expensive rendering, blocking backend work, graph reconstruction, polling, unnecessary AI/LLM calls.

Create docs/CURRENT_STATE_AUDIT.md. For every major component write:
EXISTS AND WORKS / EXISTS BUT BROKEN / EXISTS BUT POOR DESIGN / DUPLICATED / CAN BE REUSED / SHOULD BE DELETED / MISSING
Do NOT preserve weak architecture just because we already wrote it.
Then create docs/TARGET_ARCHITECTURE.md and only then implement.
Do not wait for me to approve the architecture unless there is a genuine blocker.

LIFECYCLE (heart of the product):
A user initiates: SEND ₹X FROM ACCOUNT A TO ACCOUNT B → creates a TRANSACTION INTENT. NO "success" should happen yet.
Vigil evaluates that intent using:
A. recipient / external intelligence
B. network intelligence
C. sender journey / sequence intelligence
D. behavioural anomaly
E. transaction characteristics
F. optional context signal
G. known-pattern similarity if already implemented well
Then: RISK FUSION → REASON GENERATION → INTERRUPT LADDER → USER/BANK ACTION
Only after the action permits payment should the payment provider be invoked.
If payment completes: transaction enters the ledger → graph updates → post-transaction RingWatch/TaintTrace continue monitoring → future payments inherit newly learned risk.
THIS is how the old money-mule project and PRIMA become one system. They are NOT two pages in one dashboard. They are two stages of one payment lifecycle.

1. Payment Intent Gateway
First-class TransactionIntent object. Lifecycle:
CREATED → RISK_EVALUATED → CHALLENGED / HELD / APPROVED → PAYMENT_INITIATED → PAYMENT_SUCCEEDED / FAILED → MONITORED
Risk evaluation must occur before payment creation/confirmation where practical. Persist every state transition.

2. PathGraph
Unified financial graph. Nodes: account, device, recipient/payee if useful. Edges: completed money movements.
Events should NOT all be rendered as graph nodes unless there is a strong reason. Keep graph logic lightweight.
DO NOT reconstruct the entire graph for every request. Maintain/update graph incrementally or use cached snapshots.

3. RingWatch
Reuse and clean the strongest parts of the original mule detector: fan-in, fan-out, rapid pass-through, circular movement, smurfing/splitting, velocity chain, shared device, dormant account activation, unusual counterparty concentration, rapid cash-out where represented.
Every fired rule MUST return: rule_id, human-readable reason, raw evidence, normalized contribution. Not merely fraud = 1.

4. TaintTrace
If the original implementation works, port it rather than rewriting. When a transaction is confirmed fraudulent or seeded as known fraudulent: trace the relevant money downstream. Show: source, hop, amount, dilution, amount attributable to suspicious source, current downstream exposure. Correctness and explainability > sophisticated algorithms.

5. TrailScore
Evaluate recent ACCOUNT JOURNEY: new device → new payee → limit increased → unusually large/full-balance payment. Ordered chain has stronger significance than isolated events. Persist events with timestamps. Show the judge the timeline: "Nothing here individually proves fraud. Together, within 8 minutes, the sequence is highly abnormal."

6. Behavioural Risk
Do not call something "AI" just because a threshold exists. Understandable features: amount vs user's historical distribution, first-time recipient, number of new payees recently, velocity, dormant-to-active jump, balance fraction, historical counterparty relationship, device change, time-of-day deviation if useful. A lightweight anomaly model may be retained if it genuinely improves results. Deterministic/rule evidence MUST remain available.

7. ContextFlag
SMALL. Deterministic category-based detection over DEMO-SUPPLIED context: urgency, secrecy, fear, greed, bypassing approval. Do NOT pretend Vigil reads calls/WhatsApp/Telegram. Explicit "Simulated call/message context" input, clearly marked simulated. Production: legitimate upstream channels with consent/institutional access. Do not overclaim.

8. External Intelligence Adapter
Abstraction ExternalFraudIntelProvider; local LocalRegistryProvider emulating an external fraud registry: identifier, status, risk score, reason codes, source, last updated. UI label: SIMULATED EXTERNAL INTELLIGENCE (NOT "Live RBI DPIP"). Clean enough that a future DPIP/bank integration could replace it.

9. Risk Fusion
Transparent: network_score, sequence_score, behaviour_score, external_intel_score, context_score → normalized final score. Weights in config, explainable, versioned; UI displays contribution; system shows which evidence changed the decision. Create config/risk_policy.yaml.
Decision record MUST contain: decision_id, intent_id, sender, recipient, amount, timestamp, subscores, rules fired, final score, risk tier, chosen intervention, reason, policy/config version, evaluation latency.

10. ReasonLine
Same decision in three representations:
CUSTOMER: "You're sending ₹45,000 to a recipient you've never paid before. This recipient is linked to a rapid pass-through network and this payment is 92% of your available balance."
BANK ANALYST: subscore contribution, evidence, network indicators, journey events, external intelligence, timeline.
AUDIT LOG: structured immutable-ish JSON with exact inputs, scores, policy version, timestamp, action.
No LLM for core explanations. Deterministic templates. No hallucinations.

11. Interrupt Ladder (not binary)
TIER 0 pass silently; TIER 1 informational warning; TIER 2 acknowledgement/purpose confirmation; TIER 3 temporary scoped transaction hold + bank review simulation; TIER 4 scoped hold + CircuitBreaker / high-risk escalation.
Never imply freezing an entire real bank account. ScopedHold applies to the transaction/demo amount. Inbound transactions not automatically blocked.

12. CircuitBreaker
For severe sender-compromise/coercion: notify a PRE-NOMINATED trusted contact. Facts, not accusations: "An unusually large payment to a newly-added recipient is awaiting confirmation." Trusted contact can: ACKNOWLEDGE / CALL USER / MARK AS EXPECTED. Prefer local FastAPI WebSocket/SSE + second browser/phone on LAN. Reliability > glamour.

13. Post-payment Feedback Loop
Approved transaction → ledger → graph updates → recipient/network risk may change → future intents use new intelligence immediately. MUST be visible.

Payments: PaymentProvider interface — MockPaymentProvider, RazorpayTestProvider, optional RazorpayLiveProvider ONLY if configured. Razorpay TEST MODE is enough; it does NOT prove money moved. Never claim otherwise. Not a single point of failure. DEMO_MODE where the full lifecycle works offline. No hardcoded secrets; .env.example. Verify Razorpay signatures correctly if callbacks are used.

Stack (prefer; don't rewrite stable stack just for this): Frontend existing React/Next/Vite; Backend FastAPI; DB SQLite WAL; Realtime WebSocket/SSE; Graph NetworkX/adjacency + lightweight browser viz; Config YAML/JSON + env. Simplify unnecessary cloud services.
ONE startup command (./run_demo.sh or npm run demo): start backend, init DB, seed if absent, start frontend, print URLs.

Persistence at minimum: accounts, transactions, transaction_intents, events, risk_decisions, alerts/interventions, trusted_contacts, circuit_breaker_events, external_intel, fraud_labels, taint/tracing output.
Indexes: transactions(sender, timestamp), transactions(recipient, timestamp), events(account, timestamp), risk_decisions(intent), alerts(account, timestamp).
Seed deterministically. RESET DEMO button or script to same starting state.

Background: hundreds of plausible historical transactions seeded; optional small controlled live stream. DO NOT make the judge wait for random chance.
SCENARIOS:
0 NORMAL PAYMENT — known device, known recipient, normal amount, low risk, instant approval.
1 RISKY RECIPIENT — sender normal, recipient has external/network risk; intervene BEFORE payment.
2 MONEY MULE NETWORK — fan-in → rapid pass-through → downstream layering; RingWatch detects topology; after source fraud label, TaintTrace propagates attribution.
3 COERCED / DIGITAL-ARREST — new device → new payee → limit change → near-full-balance transfer → simulated urgency/secrecy context. TrailScore + behaviour + ContextFlag spike. Tier 4. CircuitBreaker.
4 FALSE-POSITIVE CONTROL — large transaction but known recipient/device, plausible, clean intel. Must NOT scream fraud.
Every scenario: START / PAUSE / RESET / EXPLAIN.

UI around one story:
HOME / COMMAND CENTER: transactions now, pending intents, interventions, suspicious accounts, suspicious value, false-challenge/demo metrics, system status.
PAY EXPERIENCE: From / To / Amount / optional note/context / Pay → "Vigil is checking this payment" → APPROVED or intervention panel: RISK LEVEL, WHAT CHANGED, WHY WE ARE INTERRUPTING, WHAT ACTION IS BEING TAKEN. No SHAP/GNN jargon.
BANK INVESTIGATION VIEW: left details; middle reason/contribution; right small network; below event timeline, money trace, policy/action history.
TRUSTED CONTACT VIEW: very simple mobile page; alert appears without refresh.

Graph: old Three.js graph too laggy. Performant 2D (Cytoscape.js / Sigma.js). Never render whole universe; default suspicious subgraph; 1–2 hop; cap nodes; cluster; static layout; no continuous physics; no per-frame rebuild; no giant labels; lazy detail; click to expand; animate only newly affected path. GRAPH IS EVIDENCE.

Performance targets: risk eval p95 <150 ms (excl. provider); scenario visible ~1 s; dashboard <2 s; smooth graph. No model reload per request, no CSV re-read, no full NetworkX rebuild per call, no aggressive polling; realtime push. Create scripts/benchmark_demo.py (risk p50/p95, graph query time, scenario processing, DB timings).

Models: for each existing model identify data, target, features, split, leakage, imbalance, metrics, synthetic?, calibrated?, actually loaded in prod path? If weak: fix cheaply, downgrade to "supporting anomaly score", or remove from critical path. Create docs/MODEL_CARD.md (synthetic limitation, can/cannot establish, metrics, failure modes).

Research/verify Indian ecosystem: RBI, RBIH, MuleHunter.ai, DPIP, NPCI, bank EFRMS/AML, I4C/NCRP. Never claim "Nobody uses AI for mule detection", "DPIP cannot detect fraud", "We integrate directly into RBI", or private API access. Formulation: "Vigil consumes or could consume existing institutional intelligence and adds a pre-commitment decision/intervention orchestration layer." Create docs/REAL_WORLD_POSITIONING.md — per module: WHO HOSTS, WHAT DATA, WHEN RUNS, INTEGRATES WITH, DECISION PRODUCED, BUILT NOW OR SIMULATED, WHAT CHANGES FOR PRODUCTION.

Do NOT waste time on: blockchain, 3D graph, GNN for its own sake, LLM chatbot, multi-bank infra, telecom integration, microservices, Kubernetes, real RBI APIs, cloud deployment, facial recognition, voice deepfake, production KYC, dozens of scam detectors.
PatternMemory/AdaptCal: keep only if ~80% done & trivial. Mesh → lightweight external-intel demo or roadmap.

Team: CLAUDE 1 (you, lead integrator), CLAUDE 2, CLAUDE 3, CURSOR, CODEX.
Create docs/PARALLEL_WORK_PLAN.md with NON-OVERLAPPING file ownership.
CLAUDE 1 — LEAD: contracts, schema, intent lifecycle, risk orchestration, payment provider, migration, integration, merge, start/reset, e2e. Define typed contracts FIRST: TransactionIntent, RiskSignal, RiskDecision, Intervention, GraphEvidence, ExternalIntel, ScenarioEvent.
CLAUDE 2 — RISK ENGINE: RingWatch, TaintTrace, TrailScore, behaviour, ContextFlag, fusion, ReasonLine inputs; stable functions + unit tests; no frontend.
CLAUDE 3 — PRODUCT/UX: payment UI, command center, investigation, decision viz, timeline, trusted contact, graph UI, responsive, scenario controls; consumes contracts.
CURSOR — small safe tasks (CSS, spacing, renaming, dead imports, loading/error states, tooltips, formatting, README, small tests, icons, a11y). No architecture/formulas/schema.
CODEX — medium isolated tasks (seeding/reset utils, benchmark, indexes/migration helper, API contract tests, fixtures, graph-query perf, Razorpay harness, realtime reconnect tests).
Each task: FILES IT MAY EDIT / MUST NOT EDIT / INPUT CONTRACT / EXPECTED OUTPUT / TEST COMMAND / DEFINITION OF DONE.
Prompts in docs/AGENT_PROMPTS/{claude2,claude3,cursor,codex}.md.
No invented score schemas, no duplicate types, no duplicate DB layer, no scattered localhost URLs, no FE/BE threshold mismatch. Backend is source of truth. Risk policy in one config. Predictable error responses. One date standard. Money as integer paise. No float ledger balances.

MUST-HAVE checklist:
1 App starts reliably. 2 Local deterministic DB. 3 Background history. 4 Intent lifecycle. 5 Normal passes. 6 Suspicious recipient pre-commit intervention. 7 Ring/mule injection. 8 Graph identifies subnetwork. 9 TrailScore. 10 Behaviour. 11 Context demo. 12 Fusion. 13 ReasonLine explains every intervention. 14 Interrupt Ladder. 15 ScopedHold sim. 16 CircuitBreaker reaches second browser/phone. 17 Post-payment updates graph/risk. 18 Razorpay Test OR clean fallback. 19 Reset works. 20 No major lag. 21 No broken buttons. 22 E2E repeatable.
NICE-TO-HAVE: PatternMemory, AdaptCal, advanced charts, extra scenarios, polish, external intel comparison view, real DPIP/MuleHunter feeds, telecom/SIM-swap, AML case mgmt, NLP call context, large-scale graph infra, multi-bank federation.

DEMO (5 acts):
ACT 1 normal ₹500 to regular payee → Tier 0 → Razorpay test completes. "Most payments experience zero additional friction."
ACT 2 suspicious recipient → external + network evidence → exact why + contribution panel → no payment. "Intervention before irreversible commitment."
ACT 3 investigation view → inject mule scenario (background continues) → fan-in → pass-through → split → downstream → RingWatch highlights only relevant nodes → click node shows evidence → mark source confirmed scam → TaintTrace propagates → back to pay view: recipient risk changed because network learned.
ACT 4 coerced customer: new device, payee added, limit raised, large transfer, simulated urgency → "None alone proves fraud" → TrailScore → escalate → CircuitBreaker LIVE on second device. "Proportionate intervention."
ACT 5 explainability: CUSTOMER REASON / BANK EVIDENCE / AUDIT RECORD. Close: "We are not proposing another fraud classifier... Vigil is the layer that converts those signals—plus local journey and network evidence—into an explainable intervention at the last reversible moment."

Fallbacks: Razorpay down → Mock provider, "DEMO PAYMENT". Second phone fails → second browser tab. Generator fails → pre-seeded DB. Graph fails → evidence table/timeline. Internet fails → core pipeline local. Never depend on random timing.

DELIVERABLES: 1 unified repo 2 startup command 3 seed/reset 4 unified local DB 5 normal payment 6 Razorpay Test if creds allow 7 four primary scenarios 8 fast 2D graph 9 CircuitBreaker 10 explainability view 11 trusted-contact view 12 investigation view 13 benchmark results 14 tests for critical paths 15 README.md 16 docs/CURRENT_STATE_AUDIT.md 17 docs/TARGET_ARCHITECTURE.md 18 docs/REAL_WORLD_POSITIONING.md 19 docs/MODEL_CARD.md 20 docs/PARALLEL_WORK_PLAN.md 21 docs/AGENT_PROMPTS/* 22 docs/DEMO_SCRIPT.md 23 docs/KNOWN_LIMITATIONS.md (REAL / SIMULATED / SYNTHETIC / PRODUCTION ROADMAP).

Process: audit → decide → code. Run continuously; integrate continuously. After each milestone run: normal, risky, mule, coercion, reset. Profile before visual optimisation. Reliability over effects. Reuse good code; replace fragile code; simplify features that weaken the story.

Success criterion: a judge understands in under 60 seconds WHAT happened, WHY risky, WHAT evidence, WHY that intervention, WHAT happened to the money, WHERE this sits in Indian financial infrastructure. Demo feels FAST, intentional, credible.

BEGIN BY READING EVERY PROVIDED FILE AND BOTH CODEBASES. Then output:
1. CURRENT-STATE FINDINGS 2. WHAT YOU WILL KEEP 3. WHAT YOU WILL DELETE/REPLACE 4. FINAL ARCHITECTURE 5. PARALLEL TASK ALLOCATION 6. CRITICAL PATH FOR TODAY
Then immediately begin implementation.
