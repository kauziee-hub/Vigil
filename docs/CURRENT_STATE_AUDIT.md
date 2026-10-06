# Current-State Audit

Audited 2026-10-06 by Claude 1 (lead integrator). Three source trees were read:

| Tree | What it is |
|---|---|
| `Indian Bank Project/ccmule-main` ("Vectraze"/"Sentinel") | Money-mule detector: pandas simulator, 10 attack injectors, rules + RandomForest + GAT, FastAPI + vanilla-JS/D3 dashboard, Streamlit + Three.js legacy UI |
| `Indian Bank Project/Indian Bank Project - Actual ML - Laggy` | Older fork of the same detector. Same `attacks/detection/features/gnn/training` files byte-for-byte; bigger `api.py`/`realtime_engine.py`, vis-network UI, a web worker |
| `PRIMA` | Two unrelated halves: (a) `prima/` — a rigorous, pure, property-tested ledger + value-lineage library (204 tests); (b) `backend/` + `web/` — the hackathon "Vigil" app (FastAPI + SQLModel + React) with RingWatch/TrailScore/ContextFlag/ReasonLine/ScopedHold/CircuitBreaker/Razorpay |

Legend: **WORKS** = exists and works · **BROKEN** = exists but broken · **POOR** = exists but poor design · **DUP** = duplicated · **REUSE** = can be reused · **DELETE** = should be deleted · **MISSING**.

---

## 1. Money-mule detector (ccmule + Laggy fork)

| Component | Verdict | Evidence |
|---|---|---|
| Attack injectors `attacks.py` (fan-in, fan-out, circular ring, velocity chain, cross-channel burst, shared-device cluster, behavioural drift, volume spike, smurfing, dormant activation) | **REUSE (idea) / POOR (code)** | The *pattern catalogue* is the best asset. Code is unseeded `random`/`np.random`, uses `datetime.now()` (naive), mutates pandas frames row-by-row, prints to stdout. Not reproducible: a judge could not see the same attack twice. |
| Normal-traffic generator `generator.py` | **POOR** | Random pairs inside random clusters; no notion of a regular payee, so "first-time recipient" is meaningless; float/int rupees; unseeded. |
| Structural rules `detection.rule_based_detection` | **POOR** | `in_degree >= 2` fires "fan-in", `transaction_count >= 3` fires "velocity" — with no time window these fire on almost every normal account. Returns `reasons: [str]` but no evidence, no normalised contribution. |
| `early_stage_detection`, `behavioral_drift_detection` | **REUSE (ideas)** | Relative (population-percentile) thresholds and "min 2 signals" dampening are sensible. Implemented with `iterrows` over all accounts. |
| `classify_fraud_roles` | **REUSE (idea)** | Collector / distributor / pass-through role labels are good explanation vocabulary. |
| RandomForest `fraud_model.pkl` (`training.py`) | **DELETE from decision path** | Labels are *which accounts the injector touched*; features are computed only over the attack window (`timestamp >= attack_time`) so the model learns the generator, not fraud. Random (not temporal) split across runs of the same generator, accuracy is therefore near-perfect and meaningless. Not calibrated. See `MODEL_CARD.md`. |
| GAT `gnn.py`/`gnn_model.pth` | **DELETE** | Same label leakage; PRIMA's RingWatch loaded it per request with torch on CPU (heavy import, ~seconds cold). Contributes nothing a judge can verify. |
| SHAP explainer | **DELETE** | Explains a meaningless model; heavy dependency. |
| `risk_memory.py` (PatternMemory) | **POOR / roadmap** | Global list in process memory; signature built from ground-truth `is_fraud` flags (leak). Not 80% done → roadmap. |
| Adaptive threshold | **DELETE** | Adjusts threshold from precision/recall measured on ground truth at runtime — impossible in production. |
| `RealTimeEngine.compute_suspicion_scores` | **POOR — root cause of lag** | Every call copies the full DataFrame and does `iterrows` × boolean mask per account (O(accounts × transactions)), called on every API request. |
| FastAPI `api.py` | **POOR** | 1 s client polling (`setInterval(update, 1000)`), whole-state JSON each time, ban/unban "freeze" endpoints (contradicts the no-account-freeze principle). |
| Frontends: Streamlit, `threejs_graph.py` (1,257 lines), Sentinel `app.js` (1,666 lines, D3), Laggy `app.js` (3,434 lines, vis-network physics) | **DELETE** | Whole-universe rendering, continuous physics, polling. This is the "laggy graph" the brief refers to. |
| `Initially used/`, `fix_app.py`, `launch.command`, `puppeteer-test/`, stitch HTML mockups, PNG concepts | **DELETE** | Dead code / design scratch. |
| The two forks | **DUP** | 9 of 12 backend modules identical. Neither is canonical. |

## 2. PRIMA `prima/` library (ledger + value lineage)

| Component | Verdict | Evidence |
|---|---|---|
| `prima/money.py` — integer paise, `bool` rejected, conserving split | **WORKS / REUSE** | Property-tested. |
| `prima/ledger/models.py` — Journal/Entry, balance-to-zero, hash chain | **WORKS / REUSE** | Used to feed the trace. |
| `prima/ledger/engine.py` — in-memory double-entry ledger | **WORKS** | Not needed at runtime (SQLite is the ledger) but kept because the vendored tests use it. |
| `prima/attribution/trace.py` — `trace_multi` (LIBR / pro-rata / FIFO / LIFO), conservation, de-minimis floor, digest | **WORKS / REUSE as TaintTrace** | Pure, deterministic, 204 tests incl. hypothesis conservation. Strongest code in all three trees. Ported unchanged to `backend/prima/`. |
| `prima/attribution/incremental.py` — hot LIBR | **WORKS** | Not required at demo scale (batch trace of ~2k journals is ~tens of ms). Kept, unused. |
| `prima/decision.py` (R1–R4 policy, no score) | **POOR fit** | Coherent for the lineage thesis but has no sender/journey/context dimension. Superseded by Vigil's fusion. Not ported. |
| `scripts/demo.py` (static HTML report) | **DELETE (for this product)** | Console demo; replaced by the live app. |

## 3. PRIMA hackathon app (`backend/`, `web/`)

| Component | Verdict | Evidence |
|---|---|---|
| SQLite + WAL, SQLModel tables, append-only `RiskDecision` guard | **REUSE (design) / POOR (shape)** | Good: integer paise, append-only listener, indexes on tx(sender,ts)/(receiver,ts), events(account,ts). Missing: no `transaction_intents` table — a "quoted" `Transaction` row plays the intent, so ledger rows and intents are conflated; no `external_intel`, `fraud_labels`, `taint_results`. |
| `core/decision.py::evaluate_quote` **and** `action/decision_stub.py::evaluate` | **DUP** | Two decision paths; the stub contains a fixture fallback that fabricates tier 4 for any note ≥ 20 chars and fixture "model digests". |
| Known-payee override (`if prior_payments >= 1: tier = 0`) | **BROKEN (logic)** | Any prior payment to the recipient forces tier 0 — a coerced customer paying a payee they added and paid ₹1 to yesterday would pass silently. Replaced by an explicit, scoped "friction guard". |
| `payer.py` commit tiers 0–2 | **BROKEN** | Debits the sender, never credits the receiver (money destroyed). Graph not updated after settle, so post-payment learning never happens. |
| Fusion (0.40/0.35/0.25 + cross-term) in `prima_config.yaml` | **REUSE (idea)** | Config-held weights + version hash is right. Only three dimensions; no external-intel or behaviour dimension. |
| RingWatch (`scoring/ringwatch.py`) | **POOR** | Same windowless rules as ccmule; 45 % weight on a GAT loaded per request; whole score multiplied by 0.35 unless the account has tainted inflow (so structure alone is suppressed); `two_hop_money_subgraph` rebuilds an undirected copy of the whole graph per call. |
| PathGraph (`graph/pathgraph.py`) | **POOR** | `rebuild_from_db` (full rebuild) is called by taint after every label; upserts exist but are never called on commit. |
| Taint (`graph/taint.py`) | **POOR** | A per-transaction `taint_ratio = parent * child/parent_amount`, max-propagated — not conserving, double counts across branches. `prima/attribution` already does this correctly. |
| TrailScore | **REUSE** | Window + weighted steps + ordered-sequence bonus is the right shape. Reads every event of the account then filters in Python. |
| ContextFlag + lexicon | **POOR** | Matches only 15 long verbatim sentences + 5 regexes, i.e. only the demo script. Rebuilt as a category keyword lexicon over explicitly simulated context. |
| ReasonLine (user/bank/regulator, banned-word guard, SHA-256 payload) | **REUSE** | Best explanation code. Customer facts come partly from a fixture; regulator record embeds fake model digests. Rebuilt deterministically from evidence. |
| ScopedHold (`action/scoped_hold.py`) | **DUP / POOR** | In-memory isolation copy *and* SQL copy. "₹1 immediate send" is confusing. Principle (amount-scoped, never inbound, no account freeze) is kept. |
| CircuitBreaker + `/ws/watch/{token}` | **REUSE (idea) / DUP** | Works over WebSocket; duplicated in-memory session map + SQL log. Actions limited to approve/hold. |
| TopicHub WebSocket | **WORKS / REUSE** | Diff push, no 1 s timer. Ported. |
| `/api/ops/*` (seed, guest, inject_sequence, context, reset, report_fraud…) | **BROKEN** | `web/src/lib/api.ts` calls them; **`backend/routes/ops.py` does not exist**. Every Ops-page button 404s. |
| Razorpay (`razorpay_client.py`, topup + webhook) | **WORKS (narrowly) / POOR fit** | Raw-body webhook HMAC is correct. But funding is via webhook, which never reaches `localhost` without a tunnel, so the path cannot complete in a local demo. Replaced with Checkout + server-side **payment-signature** verification (`order_id|payment_id`, HMAC-SHA256, key secret) — works on localhost. |
| `.env` | **SECURITY** | Contains Razorpay **test** keys; PRIMA's own notes say treat as exposed. Copied (not printed) into the new repo's git-ignored `.env`; rotate when convenient. |
| `web/` React app (PayPage, ConsolePage, OpsPage, WatchPage, TopupPage) | **REUSE (tokens, copy, flows) / POOR (graph)** | Design tokens (IBM Plex, tier palette, dark mode) are good and are reused. `RiskGraph` uses `react-force-graph-2d` (continuous force simulation). Pages assume the missing ops routes. |
| `ComprehensionProbe` | **POOR** | Fixed question unrelated to the actual reasons. Replaced by purpose confirmation at tier 2. |
| `BankMeshSignal`, `PatternSignature`, AdaptCal config | **MISSING (empty tables / disabled)** | Mesh → replaced by the External Intelligence adapter. AdaptCal/PatternMemory → roadmap. |
| `metrics/ps3` prevented-loss | **POOR** | Reads the `is_seeded_attack` ground-truth column to compute "prevented loss". Kept only as clearly labelled demo metrics. |
| Tests for the app | **MISSING** | Only the `prima/` library is tested. |
| One-command start | **MISSING** | `run-demo.ps1` only runs the static report. |

## 4. Cross-cutting findings

| Finding | Verdict |
|---|---|
| No first-class TransactionIntent / lifecycle | **MISSING** — the core of the brief. |
| No external-intelligence abstraction | **MISSING** |
| No behavioural (sender-history) dimension | **MISSING** |
| No closed loop: completed payments never update the graph used by the next decision | **MISSING** |
| Three graph front-ends (Three.js, D3, vis-network, force-graph), all whole-universe + physics | **DUP / DELETE** |
| Naive vs aware datetimes mixed; floats for rupees in ccmule | **POOR** |
| Scattered `localhost` URLs (CORS lists in YAML, Streamlit, launch scripts) | **POOR** |
| Torch / torch-geometric / shap / scikit-learn in requirements | **DELETE** — none survive on the decision path. |

## 5. Decision summary

**Keep:** `prima/` lineage library (as TaintTrace engine, unchanged, tests ported); the attack-pattern catalogue (re-implemented as deterministic scenarios); TrailScore shape; ReasonLine three-audience structure and banned-word guard; WebSocket TopicHub; Razorpay HMAC knowledge; amount-scoped hold principle; design tokens.

**Replace:** ccmule rules (windowless) → windowed RingWatch with evidence; GNN/RF → removed from decision path; taint_ratio → `prima.trace_multi`; ContextFlag lexicon; both decision paths → one orchestrator; Razorpay webhook top-up → Checkout + signature verify inside the payment step; every graph UI → Cytoscape + dagre, suspicious subgraph only.

**Delete (not ported):** Streamlit, Three.js, D3, vis-network UIs; RF/GNN/SHAP; adaptive threshold; risk_memory; ban endpoints; `Initially used/`; fixtures with fabricated model digests.
