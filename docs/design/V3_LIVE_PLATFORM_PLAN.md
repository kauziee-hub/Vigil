# V3 — Vigil Live Platform plan (frozen 2026-10-07 by Claude 1)

User direction (2026-10-07): the refined money-mule repo
(https://github.com/Gowtham640/money-mule-detection, cloned to `Indian Bank Project/money-mule-detection-refined`,
screenshots in `docs/reference_refined/`) sets the bar — its live 3D transaction universe, analytics and look.
"It should be of this level. Not something else. Bring all this into one. The UI to be something that's actually good.
The graphs and neural network transaction everything real and nice."

## What the reference does that Vigil must match or beat
1. **Live 3D transaction universe** — every account as a glowing node (sphere layout by stable hash), each new transaction drawn live with a travelling particle, edges fading out of a time window, status colours (normal / early warning / flagged / new / banned), perspective grid floor, slow orbit, toasts. Three.js with instanced meshes; render pauses off-screen.
2. **Simulation Command Center** — choose one of ten attack patterns, spawn, watch steps, chips "warning +3 ms · detected +2.2 s · completed", attack subgraph with replay from DB, last-attack result (injected / detected / missed / first warning / detection / false positives), attack history table with precision / recall per run.
3. **Live streams** — transaction feed with per-transaction scores, risky-transaction feed, alert stream.
4. **Rule-based scoring table + hybrid ML score table** (Rules / RF / GNN / fused / status per account).
5. **Account investigation** — risk over time, SHAP breakdown, why flagged, rules fired, early-warning signals, window features, recent transactions, neighbours, alerts, simulator ground truth.
6. **Live statistics** (Chart.js) — volume per 10 s (normal vs injected), channel donut, attack runs by type (runs vs detected), threshold & recall per run, detection latency per run, roles of flagged mules.
7. **Look** — deep green-black, mint accent, Space Grotesk + JetBrains Mono, eyebrow labels, generous rounded panels, glow.

## What Vigil keeps (PRIMA layer — not in the reference)
Payment Intent Gateway, five-dimension pre-commit assessment, interrupt ladder T0–T4, scoped holds, CircuitBreaker + trusted contact, Decision Replay, counterfactuals, provenance, shadow mode, governance records, TaintTrace, honest SYNTHETIC VALIDATION model registry. These are restyled into the same visual system, never removed.

## Information architecture (unchanged 9 areas; Overview becomes "Live Operations")
Overview = the reference's single-page operations view (hero status, KPIs, live universe, command center + attack subgraph, streams, score tables, last attack + history, live statistics) **plus** a PRIMA strip (open interventions, held value, tier mix). The other eight areas keep their routes and are restyled.

## The liveliness constraint and its fix (Claude 1)
A visible live stream makes ordinary customers look anomalous unless the world's own history is equally busy (measured 2026-10-07: 29/133 ordinary customers drift-flagged after 10 min at 1 tx/3 s). Fix: **world v3** — denser, realistic everyday-UPI history (≈300+ accounts, daily small payments), so an ambient stream of ≈0.5 tx/s stays inside every account's own routine; ambient remains routine-preserving (never exceeds an account's busiest 72 h). Deterministic as before.

## Frozen interfaces (code: `backend/vigil/contracts.py` §v3, `frontend/src/api/types.ts` §v3, `frontend/src/api/client.ts`)
| Owner | Interface |
|---|---|
| Claude 1 | `GET /api/live/universe?window_minutes=&history=` → `LiveUniverse` · `GET /api/live/stats` → `LiveStats` · `GET /api/attacks/runs` → `AttackRun[]` · `GET /api/attacks/runs/{run_id}` · WS `attack.run_updated` (AttackRun) · existing `ledger.posted` |
| Claude 1 | `vigil.engine.hooks.register(fn)` — `fn(tx_row)` runs after every live posting (suspended during seeding); must be < 30 ms, must not raise |
| Claude 2 | `vigil/intel/stream.py`: registers a hook listener; per posting refreshes intel incrementally and publishes WS `intel.tx_scored` (TxScored) and `intel.account_status` (AccountStatusChange); `status_map() -> dict[account_id, {"status","risk","model_risk","role","families_flagging"}]`; `roles_flagged() -> dict[str,int]`; `current_threshold() -> float`; `threshold_history() -> list[{t,value,reason}]`; `on_run_evaluated(run: AttackRun) -> None` (adaptive model-evidence threshold, bounded, logged, never touches tiers) |
| Claude 3 | consumes the above; no backend edits |

Status semantics: `held` and `confirmed_fraud` come from Vigil state (active scoped hold as sender / labelled scam recipient); `new` = opened < 7 days; `early_warning` / `flagged` from detection intelligence; `idle` = no posting in the live window. Precedence: confirmed_fraud > held > flagged > early_warning > new > normal > idle.

## Ownership (non-overlapping)
| Owner | Files |
|---|---|
| Claude 1 | `backend/vigil/{contracts,app}.py`, `engine/**`, `sim/**` (seed v3, ambient v3, attack-run evaluation), `api/**` (live routes), `risk/taint.py` (scaling), `graph/**`, `frontend/src/api/**`, docs/handoff |
| Claude 2 | `backend/vigil/intel/**`, `backend/ml/**`, `backend/models/**`, `backend/tests/test_intel_*.py`, `docs/ML_VALIDATION_REPORT.md`, MODEL_CARD appendix |
| Claude 3 | `frontend/src/{pages,components,styles,lib}/**`, `frontend/src/{App,main}.tsx`, `frontend/index.html`, `frontend/package.json` (chart.js allowed), `docs/DESIGN_SYSTEM.md`, `docs/ui_v3/*.png` |

## Rules
Every agent commits after each milestone (session restarts kill agents). Honesty labels stay: SIMULATED, SYNTHETIC VALIDATION, SIMULATOR GROUND TRUTH. No polling — realtime push.
