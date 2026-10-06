# FINAL PARALLEL PLAN (v2 — platform build)

Owner: **Claude 1 (lead)**. Frozen 2026-10-06 22:41 IST at commit `595d4aa`. Supersedes `PARALLEL_WORK_PLAN.md` for all v2 work.

Goal: one coherent financial operating system with three layers — **(1) pre-commitment payment protection, (2) money-mule / network intelligence, (3) model / investigation / governance intelligence** — that makes the original mule project and PRIMA read as prototypes of Vigil.

Rule for every visible component: it must answer one of — *what happened · why is it risky · what did each detector see · how is money moving · what action did Vigil take · why that action · what would make it safe · what would an investigator do next · how would a bank govern this.*

---

## 1. Information architecture (frozen)

| # | Nav item | Route(s) | Absorbs (brief items) | Primary question |
|---|---|---|---|---|
| 1 | **Overview** | `/` | Overview | What is happening, what needs attention, value at risk, emerging networks, detector agreement, active interventions, system status |
| 2 | **Transaction Guard** | `/guard` (bank view) · `/pay?as=` (customer-only kiosk, kept) | Transaction Guard | Pre-commit assessment of one payment: sender / recipient / amount / relationship / device / behaviour / network / external / journey / context / decision → provider & ledger outcome |
| 3 | **Network Intelligence** | `/network` | Network Intelligence, 3D graph, attack replay | How is money moving; who plays which role |
| 4 | **Detection & Models** | `/detection` | Detection Intelligence + Model & Explainability | What does each detector see; how good are the models (SYNTHETIC VALIDATION); SHAP global; early warning; pattern memory |
| 5 | **Investigations** | `/investigations`, `/investigations/decision/:id`, `/investigations/account/:id` | Investigations, Decision Replay, counterfactuals, risk evolution, account intel | Why was this risky, what would make it safe, what next |
| 6 | **Interventions** | `/interventions` | Interventions, ScopedHold, CircuitBreaker | What action is active, SLA, release/reject |
| 7 | **Governance & Audit** | `/governance`, `/governance/decision/:id` | Governance/Audit, Shadow Mode, policy, decision records, positioning | How a bank governs this: mode, policy versions, raw records, replay, deployment context |
| 8 | **Scenario Lab** | `/lab` | Scenario Lab (14 scenarios) | Reproducible demonstrations; compare detectors |
| 9 | **System Health** | `/health` (+ status in top bar) | System Health | Latency, provider, realtime, caches, intel availability |
| — | Trusted contact | `/contact/:token` | CircuitBreaker phone | (standalone, mobile) |

Old routes `/investigate/*`, `/decision/*`, `/about` must redirect to their new homes.

## 2. Status colour scale (frozen — colour encodes status only)

| Status | Meaning | Used for |
|---|---|---|
| NORMAL | nothing notable | T0, network score < 0.30 |
| WATCH | worth a look | T1, score 0.30–0.50, drift MEDIUM |
| HIGH RISK | likely problem | T2, score 0.50–0.75, drift HIGH |
| CRITICAL | act now | T4, score ≥ 0.75 |
| HELD | money paused by Vigil | T3/T4 scoped hold active |
| CONFIRMED FRAUD | bank-confirmed scam source/recipient | labelled tx/accounts, traced value |

Dimension/detector families get **neutral** identifiers (glyph + label), not competing hues. Simulated inputs carry a SIMULATED marker everywhere.

## 3. File ownership (non-overlapping) and branches

Git exists (baseline `6ea2941`). Claude 2 and Claude 3 work in **isolated git worktrees/branches**; Claude 1 reviews and merges. Codex and Cursor (external tools) must create branches `codex/<task>` / `cursor/<task>`.

| Owner | Branch | May edit | Must NOT edit |
|---|---|---|---|
| **Claude 1** (lead) | `main` | `backend/vigil/{contracts,db,settings,clock,app,realtime}.py`, `schema.sql`, `engine/**`, `payments/**`, `api/**`, `sim/**`, `graph/**`, `risk/**` (fusion/policy), `config/risk_policy.yaml`, `frontend/src/api/**`, `run_demo.*`, `docs/{FINAL_PARALLEL_PLAN,CHANGELOG,TARGET_ARCHITECTURE}.md`, `AGENT_HANDOFF/**` | — (reviews everything) |
| **Claude 2** (ML / intelligence) | worktree branch | `backend/vigil/intel/**` (new), `backend/ml/**` (training & evaluation, new), `backend/models/**` (artefacts + metadata JSON), `backend/requirements-ml.txt`, `backend/tests/test_intel_*.py`, `docs/ML_VALIDATION_REPORT.md`, append-only section in `docs/MODEL_CARD.md` | contracts, engine, api (except its own router), risk/fusion, payments, sim, frontend, schema |
| **Claude 3** (frontend redesign) | worktree branch | `frontend/src/{pages,components,styles,lib,App.tsx,main.tsx}`, `frontend/index.html`, `frontend/package.json` (new viz deps only, justified), `docs/DESIGN_SYSTEM.md`, `docs/ui_v2/*.png` | `frontend/src/api/**` (request changes via REQUESTS.md), anything in `backend/`, `config/` |
| **Codex** | `codex/<task>` | `scripts/**` (new files), `backend/tests/test_codex_*.py`, `backend/tests/fixtures/**` | `backend/vigil/**`, `frontend/**`, `config/**` |
| **Cursor** | `cursor/<task>` | CSS polish + presentational components only, after Claude 3 merges: `frontend/src/styles/polish.css`, `frontend/src/components/ui/**` | DB, risk logic, model logic, lifecycle, api, pages' data flow |

## 4. Frozen interfaces

### 4.1 Python contracts — `backend/vigil/contracts.py`
`Provenance`, `RiskSignal.provenance`, `DetectorResult`, `DetectorConsensus`, `ShapContribution`, `ShapExplanation`, `DriftFeature`, `DriftReport`, `PatternMatch`, `RoleAssessment`, `AccountIntel`, `ModelInfo`, `ReplayFrame`, `DecisionReplay`, `Counterfactual`, `BaselineDecision`, `RiskDecision.{mode, recommended_tier, applied_tier, baseline, model_evidence}`, `SceneNode`, `SceneTx`, `SceneEdge`, `GraphScene`. TS mirror: `frontend/src/api/types.ts`.

Value semantics: `DetectorResult.kind` must be honest — an RF `predict_proba` that is not calibrated is `probability_uncalibrated`; rule points are `score`; drift is `level`; pattern memory is `similarity`.

### 4.2 Claude 2 must provide (Python)
```
vigil/intel/api.py        router = APIRouter(prefix="/api/intel")
  GET /api/intel/accounts/{account_id}        -> AccountIntel
  GET /api/intel/scores                        -> {graph_version, scores:{id:{rules,rf,gnn,drift_level,role,early_warning}}}  (cached per graph version; all accounts in the default scene)
  GET /api/intel/models                        -> list[ModelInfo]
  GET /api/intel/overview                      -> IntelOverview (see types.ts)
  GET /api/intel/scenarios/{scenario_id}/compare -> ScenarioCompare
vigil/intel/consensus.py  corroboration(account_id: str) -> list[DetectorResult]
                          # called by engine/decide.py for model_evidence; must be < 20 ms warm, must never raise
```
Inputs Claude 2 may READ (not edit): `vigil.graph.pathgraph.GRAPH` (edges with ts, amount, channel via tx table), `vigil.db` (read-only SELECTs), `vigil.risk.{ringwatch,trailscore,contextflag,external_intel,taint}` evaluate functions, `vigil.sim.scenarios.touched_accounts(scenario_id)` and `SCENARIOS`.
The app imports `vigil.intel.api` optionally; if ML deps are missing the platform still runs (`intel_available=false`).

### 4.3 Claude 1 provides (REST, implemented on `main`)
| Endpoint | Returns |
|---|---|
| `GET /api/decisions/{id}/replay` | `DecisionReplay` — frames reconstruct journey events → evaluation → decision → actions → outcome, subscores evolving |
| `GET /api/decisions/{id}/counterfactuals` | `Counterfactual[]` from the policy engine (no LLM) |
| `GET /api/decisions/{id}/record` | `DecisionRecord` — provenance table, model versions, thresholds, reason codes, operator actions, payment result |
| `GET /api/accounts/{id}/risk-timeline` | `RiskPoint[]` with reasons |
| `GET/POST /api/mode` | `ModeView` — active / shadow |
| `GET /api/governance/summary` | `GovernanceSummary` |
| `GET /api/interventions?status=open|all` | `InterventionRow[]` |
| `GET /api/system/health` | `SystemHealth` |
| `GET /api/graph/scene?cap=&focus=&hops=&scenario=` | `GraphScene` — frozen 3D layout, cached by version |
| `GET /api/scenarios` (14 scenarios) · `POST …/start|pause|resume|reset` · `GET …/explain` · `GET …/replay` | scenario lab |
| existing v1 endpoints | unchanged |

### 4.4 Realtime (unchanged envelope `{type, topic, ts, data}`)
New event types: `mode.changed`, `scenario.*` for all 14 scenarios, `intel.updated` (Claude 2 may publish via `vigil.realtime.HUB.publish("console", "intel.updated", {...})`).

## 5. Decisions that are NOT negotiable
* Payment authorisation uses only the transparent engine (`risk/*` + `config/risk_policy.yaml`). RF/GNN/drift/pattern memory are **corroborating model evidence** shown beside the decision, never fused into the tier.
* Models are restored and re-validated, not deleted; every metric labelled **SYNTHETIC VALIDATION**.
* SHAP explains the model; ReasonLine explains the operational decision. Separate UI blocks.
* No RBI branding/logos; no text implying real RBI/NPCI/DPIP data.
* Deterministic scenarios; reset must restore identical state.

## 6. Priorities
* **P0:** unified institutional UI · Transaction Guard · 3D network investigation · mule intelligence visible (Rules/RF/GNN) · explainability · all core scenarios · Decision Replay · reliable reset · performance · trusted contact · governance/audit.
* **P1:** ML retraining with honest validation · SHAP · drift · pattern memory · roles · counterfactuals · shadow mode · risk evolution.
* **P2:** decorative visuals, advanced animation, extra modelling.

## 7. Run-record protocol (mandatory)
Every agent run gets `AGENT_HANDOFF/runs/<YYYYMMDD-HHMM>_<agent>_<task>.md` with: Agent · Timestamp · Objective · Exact Prompt · Agent Output/Summary · Files Changed · Tests Run · Test Results · Screenshots/Artifacts · Problems Found · Decisions Made · Remaining Work · Git Commit/Diff Reference · Status. One row per run in `AGENT_HANDOFF/AGENT_LEDGER.md`. **The result is saved before the next prompt is sent.** Claude 1 writes the record for Claude 2/3 subagent runs from their returned reports; Codex/Cursor outputs are pasted in by the operator.

## 8. Merge protocol
1. Agent finishes on its branch; tests/build pass in its worktree.
2. Claude 1 saves the run record, reviews the diff against the ownership table, merges into `main`.
3. Claude 1 runs: `pytest`, `scripts/smoke_demo.py`, `npm run build`, browser walkthrough; records results in the merge run record and `docs/CHANGELOG.md`.
