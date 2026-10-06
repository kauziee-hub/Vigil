# Run record — claude2 — ML / detection intelligence (run 2, resume)

| Field | Value |
|---|---|
| Agent | Claude 2 (subagent launched by Claude 1, isolated git worktree) |
| Timestamp | launched 2026-10-06 23:05 IST |
| Objective | Same as run 1 (started fresh): audit + repair + retrain RF/GAT with honest SYNTHETIC VALIDATION; SHAP; drift; pattern memory; roles; rules/early warning; detector consensus API `/api/intel/*` |
| Exact Prompt | Full message sent: `AGENT_HANDOFF/prompts/v2_claude2_run2_resume.md` (verbatim; it points to the binding `AGENT_HANDOFF/prompts/v2_claude2_ml_intelligence.md`). |
| Previous run | `runs/20261006-2243_claude2_ml-intelligence.md` — INTERRUPTED |
| Status | INTERRUPTED — the Claude 1 session restarted again (agent's last file write 23:43 IST; found dead at 01:02 IST on 2026-10-07). Committed milestones survived; the uncommitted remainder was recovered verbatim. |

## Agent Output / Summary
No final report (killed by the session restart). The incremental-commit rule worked: three milestone commits survived. Claude 1 committed the uncommitted remainder verbatim as `871df51` and renamed the worktree branch to **`claude2/run2-wip`**.

What exists on `claude2/run2-wip` (6077 insertions, 25 files, all inside Claude 2's ownership):
* `abde2fc` — `docs/ML_VALIDATION_REPORT.md` §1 Audit of the original RF/GAT (findings A1–A16, "what survives").
* `4d57ea6` — merged master (touched_accounts = participants only; scoped scene).
* `eb5dff2` — `vigil/intel/features.py` (windowed per-account extractor shared by training and live inference) + `ml/datagen.py` (deterministic multi-world generator, 10 attack families, hard negatives).
* `871df51` (recovered WIP) — `vigil/intel/{rules,early_warning,drift,pattern_memory,roles,models}.py` (models.py: numpy forest + GAT forward pass, lazy SHAP TreeExplainer, `ModelStore`), `ml/{gnn_torch,metrics,train_all}.py`, and the trained artefacts in `backend/models/` (1.2 MB: `rf_v2.{joblib,npz,json}`, `gnn_v2.{npz,json}`, `rules_v2.json`, `drift{,_meta}_v2.json`, `pattern_memory{,_meta}_v2.json`, `validation_v2.json`) from a completed `train_all.py` run (trained_at 2026-10-06T18:13:17Z).

NOT yet written: `vigil/intel/consensus.py`, `vigil/intel/api.py`, `backend/tests/test_intel_*.py`, `backend/requirements-ml.txt`, the rest of `docs/ML_VALIDATION_REPORT.md` (metrics sections), the `docs/MODEL_CARD.md` appendix.

## Files Changed
See summary. Ownership check by Claude 1: every path is inside `backend/vigil/intel/**`, `backend/ml/**`, `backend/models/**`, `docs/ML_VALIDATION_REPORT.md` — no out-of-scope edits.

## Tests Run / Test Results
Agent: unknown (no report). Claude 1 on recovery: no `test_intel_*` exist yet; existing suite unaffected (branch only adds files under Claude 2's paths).

## Screenshots / Artifacts
`backend/models/validation_v2.json` (read by Claude 1 on recovery) — all metrics labelled "SYNTHETIC VALIDATION — computer-generated worlds; not real-bank accuracy." Split-by-world 90/30/30 (150 worlds, seed 20261006), attack start 0.25–72 h before evaluation time. Test worlds (8841 accounts, 334 mules):

| detector | precision | recall | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|
| rules | 0.27 | 0.35 | 0.31 | 0.82 | 0.19 |
| early warning | 0.29 | 0.58 | 0.38 | 0.88 | 0.30 |
| drift | 0.57 | 0.68 | 0.62 | 0.94 | 0.64 |
| pattern memory | 0.58 | 0.63 | 0.61 | 0.93 | 0.64 |
| random forest | 0.93 | 0.81 | 0.87 | 0.99 | 0.91 |
| GNN (GAT, torch) | 0.98 | 0.88 | 0.93 | 0.99 | 0.96 |
| consensus 3-of-6 | 0.79 | 0.74 | 0.76 | 0.96 | 0.79 |

Leave-one-attack-family-out shows real generalisation gaps (e.g. GNN recall on unseen shared_device 0.00, smurfing 0.13, dormant 0.14; RF holds up better). Old protocol (random row split, attack-window graph) on the same worlds: the old model gets precision 0.12 at recall 0.97 on honest test worlds (flags 31 % of accounts). Training time 804 s total, of which LOAO 690 s — over the 10-minute budget.

## Problems Found
1. Session restart killed the agent a second time (cause outside the project).
2. `train_all.py` total 804 s > 600 s budget (LOAO dominates).
3. `requirements-ml.txt` missing although sklearn 1.9.1 / shap 0.51.0 / torch 2.14.1+cpu are installed in the main venv.

## Decisions Made
(By Claude 1 on recovery) Commit the recovered artefacts as the prompt requires ("Commit the trained artefacts (they are small)" — 1.2 MB). Relaunch as run 3 resuming from `claude2/run2-wip`.

## Remaining Work
consensus.py (`corroboration()` < 20 ms warm, never raises) · api.py (5 routes per FINAL_PARALLEL_PLAN §4.2, matching `frontend/src/api/types.ts`) · tests · requirements-ml.txt · bring train_all under 10 min (or make LOAO a flag and say so) · ML_VALIDATION_REPORT metrics sections · MODEL_CARD appendix.

## Git Commit / Diff Reference
Base: main @ `3e545c0`. Branch: `claude2/run2-wip` @ `871df51` (worktree `agent-a40b2441401d71e94` removed after recovery).

## Mid-run messages from Claude 1 (verbatim)
1. (~23:22 IST) "Lead update (read-only interface change on main, commit e2ea443; merge or cherry-pick main if your compare/tests depend on it): vigil.sim.scenarios.touched_accounts("atk_*") now returns ONLY the accounts each attack actually transacts with. Before, it returned the whole 8-account pool, so e.g. atk_circular listed 8 accounts but its ring uses 4, and atk_dormant listed 8 + dormant but uses 3 + dormant. A test now asserts touched_accounts(sid) == the non-"ext:" accounts on transactions WHERE seed_attack = sid, for all 10 attacks. For ScenarioCompare, treat touched_accounts as "involved accounts", not "mules": fan-in senders, smurfing recipients etc. are involved but are not necessarily mule-role accounts, so do not report them as missed detections without saying so. Also on main: GET /api/graph/scene?scenario=<id> is now scoped to the scenario's accounts plus hops (commit 0fb20ef). Do not edit sim/."
