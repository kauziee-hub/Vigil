# Claude 1 (lead) — session report, 2026-10-06

This is the output requested by the master prompt (sections 1–6), plus what was built and verified.

## 1. Current-state findings (full detail: docs/CURRENT_STATE_AUDIT.md)

* **ccmule-main / "Actual ML - Laggy"** — two forks of one mule detector (9 of 12 backend files identical). Best asset: the attack-pattern catalogue. Rules were windowless (`in_degree >= 2` = fan-in), unseeded random generator, RF + GAT trained on the injector's own labels with features measured only on the attack window (label leakage), adaptive threshold read ground truth at runtime, suspicion scoring was O(accounts × transactions) per request with 1 s client polling → the lag. Three.js / D3 / vis-network graphs rendered the whole universe with physics.
* **PRIMA** — two unrelated halves. `prima/` is a rigorous, pure, property-tested ledger + value-lineage library (190 tests port cleanly) — the strongest code anywhere. The hackathon app (`backend/`, `web/`) had: no TransactionIntent (a "quoted" ledger row played the role), two duplicate decision paths (one fabricated tier 4 for long notes), a known-payee override that forced tier 0 (coercion to a previously paid payee would pass), a commit path that **debited without crediting** (money destroyed), no graph update after payment (no feedback loop), a GNN given 45 % of network weight and run per request, a ContextFlag lexicon that only matched the demo script, a non-conserving taint ratio, and a frontend calling `/api/ops/*` routes that **did not exist**. Razorpay was a webhook top-up that cannot reach localhost; its keys are now rejected by Razorpay (HTTP 401).

## 2. Kept

`prima/` lineage engine (vendored unchanged → TaintTrace); attack-pattern ideas (re-implemented deterministically); TrailScore shape (window + ordered chain); ReasonLine three-audience idea + banned-word guard; WebSocket topic hub; amount-scoped hold principle (no account freeze); Razorpay HMAC knowledge; PRIMA design tokens (IBM Plex, tier palette).

## 3. Deleted / replaced

RF, GAT, SHAP, adaptive threshold, PatternMemory (off the decision path; see MODEL_CARD); windowless rules → windowed RingWatch with evidence; taint_ratio → `prima.trace_multi` (LIBR + pro rata); both decision paths → one orchestrator; SQLModel → stdlib sqlite3 (one DB layer); Razorpay webhook top-up → Checkout + server-side payment-signature verification inside the payment step, with startup key probe and automatic mock fallback; Streamlit/Three.js/D3/vis-network/force-graph → Cytoscape + dagre suspicious subgraph; missing ops routes → real scenario/reset/label APIs.

## 4. Final architecture (full: docs/TARGET_ARCHITECTURE.md)

One FastAPI process on one port serving API + built React UI; SQLite WAL; in-memory incremental PathGraph; one WebSocket with topics. Lifecycle: `CREATED → RISK_EVALUATED → APPROVED | CHALLENGED | HELD | ESCALATED → PAYMENT_INITIATED → PAYMENT_SUCCEEDED → MONITORED` (+ CANCELLED / REJECTED / PAYMENT_FAILED), every transition persisted and pushed. Five dimensions (external [simulated], network, sequence, behaviour, context [simulated]) → versioned fusion with named adjustments → ladder T0–T4 → provider only after approval → ledger + graph → RingWatch/TaintTrace → next decision.

## 5. Parallel task allocation (full: docs/PARALLEL_WORK_PLAN.md, prompts in docs/AGENT_PROMPTS/)

* Claude 1 — contracts, schema, lifecycle, payments, API, seed/scenarios, run scripts, integration (done).
* Claude 2 — risk-rule unit tests, fusion tests, false-positive review (`backend/vigil/risk/**`).
* Claude 3 — UX polish of pages/components only.
* Cursor — a11y, small UI components, formatting, README wording.
* Codex — contract-sync test, realtime WS test, benchmark extension, Razorpay check script, reset-determinism test.

## 6. Critical path — status

1. ✅ Audit + architecture + contracts
2. ✅ Backend lifecycle, risk engine, ledger, TaintTrace, scenarios — 211 tests pass
3. ✅ Frontend: Command center, Pay, Investigate, Network, Decision (3 views), Trusted contact, Where-it-sits
4. ✅ One-command start (`run_demo.ps1` / `run_demo.sh`), reset (button + flag), benchmark, smoke test
5. ✅ Docs: audit, architecture, positioning, model card, demo script, limitations, work plan, agent prompts, README
6. ⏳ Human: put valid **Razorpay test keys** in `.env` (current ones are rejected) if the Razorpay leg should run live; rehearse Acts 1–5 twice with a phone on the LAN.

## Verified in the running app (browser)

Act 1 T0 paid → Act 2 T2 with four-question panel → Act 3 ring injection renders 17-node evidence graph, Confirm scam → TaintTrace (conserved) → same recipient now T3 → Act 4 scenario payment appears live on Sunita's screen (T4) and alert arrives live on Arjun's phone page; his response appears live on Sunita's screen → Act 5 three-view decision page.

## Numbers

Risk evaluation p50 0.68 ms / p95 1.09 ms; persisted intent creation p95 1.9 ms; graph queries < 0.5 ms; TaintTrace 78 ms over 2,068 journals; seed 0.15 s.
