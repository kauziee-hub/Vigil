# Run record — claude2 — ML / detection intelligence (run 3, resume)

| Field | Value |
|---|---|
| Agent | Claude 2 (subagent launched by Claude 1, isolated git worktree) |
| Timestamp | launched 2026-10-07 ~01:10 IST; returned ~01:51 IST (duration 2430 s, 202 tool uses) |
| Objective | Finish detection intelligence from `claude2/run2-wip`: `consensus.corroboration` + `warm()`, `/api/intel/*` (5 routes), tests, requirements-ml.txt, train_all < 10 min + re-run, ML_VALIDATION_REPORT metrics + MODEL_CARD appendix |
| Exact Prompt | Full message sent: `AGENT_HANDOFF/prompts/v2_claude2_run3_resume.md` (verbatim; it points to the binding `AGENT_HANDOFF/prompts/v2_claude2_ml_intelligence.md`). |
| Previous run | `runs/20261006-2303_claude2_ml-intelligence-run2.md` — INTERRUPTED |
| Status | DONE — merged into main `4fe0a17` (report saved first, `e26122d`) |

## Agent Output / Summary (verbatim final report)

Run 3 is finished: all five remaining items are built, tested and committed, and the full suite passes (268 tests: your 223 plus 45 new intel tests). Retraining changed the generator and drift detector, so every metric was recomputed.

## 1. Summary
- **(a) Payment-path hook.** `corroboration(account_id)` in `vigil/intel/consensus.py` returns the six detector families (RF, GNN, rules, early warning, drift, pattern memory) with honest `kind` values. It never raises, returns `[]` for unknown, empty or external accounts, and never imports shap or sklearn.
  - Warm latency after a whole scenario's postings is 5–13 ms; median 5.5 ms over 10 single postings; cache hit 0.2 ms.
  - `vigil.intel.warm()` is in the package `__init__`. It is idempotent, never raises, loads the artefacts and builds the live snapshot. It also prepares the SHAP explainer on a short daemon thread that does no DB access.
  - Live results are cached per graph state and updated incrementally after new postings; a reset always forces a full rebuild.
- **(b) API.** `vigil/intel/api.py` has exactly the five routes from §4.2, all `async def`, returning JSON that matches `types.ts` field for field.
  - `ScenarioCompare.seed_role` is the seeded role plus how the account took part, e.g. `"legit · sent scenario funds"`. Involved accounts are not presented as missed mules.
  - `vigil/intel/registry.py::models()` also feeds your `/api/governance/summary`, which already imports it.
- **(c) Tests:** 45 new. Shapes are checked against `contracts.py` and against `types.ts` parsed directly. They also cover:
  - consensus semantics, never-raise, the 20 ms latency budget;
  - same score and tier with and without intel;
  - s2: kiran.traders 6/6 and zenith.exports 4/6 families, 0 ordinary accounts flagged;
  - all ten attacks flagged with no spill-over to uninvolved accounts;
  - determinism, numpy ports equal to sklearn/torch;
  - a static check that no detector reads ground truth;
  - the app runs with numpy/sklearn/shap/torch blocked.
- **(d) Training budget.** The default `ml/train_all.py` now takes **3 min 20 s wall (192 s internal)**, down from 804 s. The LOAO GNN runs at 20 epochs / patience 6, and validation is one batch.
  - `--full-loao` (60 epochs / patience 15, 7 min 15 s) writes only `validation_v2_full_loao.json`.
  - Training is deterministic; the committed artefacts match the committed code.
- **(e) Docs:** `docs/ML_VALIDATION_REPORT.md` §2–12, every section labelled SYNTHETIC VALIDATION, and an appended section at the end of `docs/MODEL_CARD.md`.

## 2. Files changed (all inside my ownership)
- `backend/vigil/intel/`: new `consensus.py`, `live.py`, `api.py`, `service.py`, `registry.py`; modified `__init__.py`, `models.py`, `drift.py`, `features.py`
- `backend/ml/datagen.py`, `backend/ml/train_all.py`
- `backend/models/*` (regenerated) plus `validation_v2_full_loao.json`
- `backend/requirements-ml.txt`
- `backend/tests/test_intel_{api,consensus,live,degrade}.py`
- `docs/ML_VALIDATION_REPORT.md`, `docs/MODEL_CARD.md` (appended section only)

## 3. Commands and test results
All run from `backend/`:
- `python -m pytest` → **268 passed**. Before your `23dcbbf` merge, the 2 odd-hour lifecycle tests failed, as you said they would.
- `python ml/train_all.py` → 192 s internal / 3 m 20 s wall; RF port check 2.2e-16, GNN 1.1e-7; trained_at 2026-10-06T20:11:11Z.
- `python ml/train_all.py --full-loao` → 426 s.
- `python ml/train_all.py --no-loao` was used once while iterating; it is superseded by the default run.

## 4. Metrics — SYNTHETIC VALIDATION
Measured on 30 held-out test worlds: 8,846 accounts, 310 mules.

| Detector | Precision | Recall | F1 | PR-AUC |
|---|---|---|---|---|
| Rules | 0.26 | 0.35 | 0.30 | 0.19 |
| Early warning | 0.29 | 0.63 | 0.40 | 0.28 |
| Drift | 0.57 | 0.76 | 0.65 | 0.66 |
| Pattern memory | 0.83 | 0.46 | 0.59 | 0.66 |
| RF (calibrated) | 0.93 | 0.85 | 0.88 | 0.92 |
| GNN (calibrated) | 0.98 | 0.91 | 0.94 | 0.95 |
| Consensus ≥ 3 of 6 | 0.85 | 0.78 | 0.81 | 0.82 |

**Per-attack recall, rules / RF / GNN:**

| Attack family | Rules | RF | GNN |
|---|---|---|---|
| fan_in | 0.70 | 0.80 | 0.70 |
| fan_out | 0.19 | 0.75 | 0.89 |
| circular | 0.09 | 1.00 | 0.98 |
| velocity_chain | 0.08 | 1.00 | 0.97 |
| cross_channel | 0.21 | 0.79 | 0.90 |
| shared_device | 0.92 | 0.96 | 1.00 |
| behavioural_drift | 1.00 | 0.86 | 1.00 |
| volume_spike | 0.86 | 1.00 | 0.86 |
| smurfing | 0.21 | 0.48 | 0.69 |
| dormant | 0.50 | 0.90 | 0.90 |

**Leave-one-attack-out, recall on the unseen family:**
- RF: 0.70 / 0.68 / 1.00 / 1.00 / 0.79 / 0.90 / 0.86 / 0.71 / **0.28** / **0.50**, in the same family order as above.
- GNN at 20 epochs: 0.30 / 0.57 / 0.96 / 0.94 / 0.76 / **0.17** / 0.43 / **0.00** / 0.34 / 0.30.
- GNN at 60 epochs: 0.40 / 0.68 / 0.98 / 0.94 / 0.76 / 0.21 / 0.57 / 0.00 / 0.38 / 0.50.
- The GNN does not generalise to unseen shared-device, volume-spike or behavioural-drift families, whatever the budget.

**Calibration (Brier):** RF 0.0121 raw → 0.0065 calibrated; GNN 0.0078 → 0.0033.

**Old protocol vs honest protocol:** the old setup scores F1 0.89 on these worlds. The same model on honest windowed features scores F1 0.11 and flags 57% of accounts.

## 5. Audit findings (short)
A1–A16 in report §1 are unchanged. The headline: the old models learned the attack-window shortcut and "touched by the injector", were tested on the same simulation they were trained on, and read labels at runtime (adaptive threshold, PatternMemory, the `is_attack` boost). §8 shows the leakage directly.

## 6. Problems and decisions
- **Distribution gap found when wiring the live world.** The run-2 models flagged 9 ordinary accounts by GNN and 18 by drift on the unattacked seeded world, because every live salary falls inside the 72 h window.
  - Fixes: a payday calendar in the generator (v2.1), plus a 45-day drift baseline with a per-feature cap of 4 and HIGH requiring at least 2 changed features. Everything was re-fitted on train/validation worlds only.
  - Result: 0 of 131 ordinary accounts flagged on the seeded world.
  - Report §2.1 states openly that this was motivated by looking at the demo world.
- **Collector role is weak** (10% correct; usually labelled "entry"). Roles are documented as descriptions, not validated classifications.
- **ScenarioCompare `seed_role` format** is `"&lt;db seed_role&gt; · &lt;involvement&gt;"`, so victims and smurfing recipients read as involved rather than missed.
- **`/api/intel/scores`** covers every scored account, a superset of the default scene. `role` is `null` unless at least 2 families flag the account.

## 7. Remaining work
- **For you:** merge, then check `/api/intel/*` live on :8000 and in the browser. `warm()` is already called from your startup code.
- **Unchanged limitations:** the RF leans on amount features; the live GNN scores the whole graph each time (fine at demo scale, would need sampling at bank scale).

## 8. Branch and commit
Branch `worktree-agent-a91d0e8bba17e1c06`, HEAD **`7a3f647`** (merges master `d63a901`). Milestone commits: `158f236` (a), `a179161` (b), `163a08c` (c), `747bdf2` (d), `b8b9441` (e). No servers or background processes are left running.

_(end of verbatim report)_

## Files Changed
Lead ownership check: 37 files, +8294, every path inside Claude 2's ownership (`backend/vigil/intel/**`, `backend/ml/**`, `backend/models/**`, `backend/requirements-ml.txt`, `backend/tests/test_intel_*.py`, `docs/ML_VALIDATION_REPORT.md`, `docs/MODEL_CARD.md`); MODEL_CARD append-only (0 lines removed). Worktree clean at return.

## Tests Run / Test Results
Lead, on main after merge (07:29 IST): `pytest` → **268 passed** (counted with `-rA`). After the lead's ambient fix: 269 passed; `scripts/smoke_demo.py` 8/8.
Live on :8000 after restart: `/api/intel/models` 200 7 ms · `/overview` 200 30 ms · `/scores` 200 6 ms · `/accounts/kiran.traders@vigil` 200 20 ms · `/accounts/nobody@vigil` 404 · `/scenarios/s2/compare` 200 131 ms · `/scenarios/atk_circular/compare` 200 76 ms · unknown scenario 404. `/api/system/health` → `intel_available: true`.
Payment path (temp DB, s2 then s1/s0/s3): every decision carries 5 model families with honest kinds (`probability_calibrated`, `score`, `level`, `similarity`); audit lists them under `model_evidence_not_used_for_tier`; `ml_models_used: []`; s1 after s2 → Tier 3 (as the feedback-loop test expects); s3 coercion recipient not flagged by any model (correct: coercion is caught by payment context, not mule structure). `warm()` 132 ms.
**Reproducibility check (lead):** re-ran `python ml/train_all.py` in a throwaway detached worktree of main `65a0706`: exit 0, 171 s wall (158.9 s internal). `gnn_v2.npz` and `rf_v2.joblib` byte-identical; `rf_v2.npz` model arrays identical (left/right/feature/threshold/p1/offsets/max_depth), only the stored port-check reference predictions differ by 2.2e-16; every metric in `validation_v2.json` identical — diffs are only `trained_at`, timings, the npz hash and the port-check value. Claim "committed artefacts match the committed code" verified to float precision.

## Screenshots / Artifacts
`backend/models/*` (v2.1 artefacts + `validation_v2.json`, `validation_v2_full_loao.json`), `docs/ML_VALIDATION_REPORT.md` §1–12, MODEL_CARD appendix.

## Problems Found
1. (lead, after merge) On the long-running live server 130/140 accounts were flagged by ≥ 1 family. Root cause was the lead's ambient stream (1 payment / 3 s ≈ 100× each account's history), not the models — fixed in `0070ff4` (routine-preserving stream, 20 s); live world reset; only kiran.traders + zenith.exports flagged afterwards. Lead note appended to report §10 (`ca195a0`).
2. `vigil.intel.warm()` docstring said it never imports shap; it warms SHAP on a daemon thread (no DB access) — docstring corrected by lead in `0070ff4`.
3. Roles remain weak (collector 10 % correct) — documented by the agent as descriptions, not validated classifications.

## Decisions Made
Merge as-is (no functional change needed). Keep the SHAP warm-up thread: it does no DB access, so the single-threaded DB invariant holds. Unknown account → 404 accepted (UI must show an honest empty state).

## Remaining Work
UI verification against live intel (Claude 3, resumed 07:40). DEMO_SCRIPT v2 / README after the UI merge.

## Git Commit / Diff Reference
Base: main @ `9351a91`; merged master `d63a901` during the run. Branch: `worktree-agent-a91d0e8bba17e1c06` @ `7a3f647` → renamed `claude2/run3` after merge; worktree removed. Merge commit on main: `4fe0a17`.

## Mid-run messages from Claude 1 (verbatim)
1. (~01:22 IST) "Lead update (main commit 23dcbbf; merge `master` into your branch before you rely on a full-suite run): if `test_vigil_lifecycle.py::test_s1_risky_recipient_intervenes_before_payment` and `::test_feedback_loop_mule_ring_raises_recipient_risk` fail for you, that is NOT your bug. The BEH_ODD_HOUR rule read the wall clock, so between 00:00 and 05:00 IST s1 scored 0.45 -> Tier 3 instead of Tier 2. Fixed on main: scripted scenarios (scenarios.run_sync and the async runner) now evaluate time-of-day rules at a pinned hour (`clock.DEMO_LOCAL_HOUR_IST` = 14, via `clock.pinned_local_hour()`); live/ambient payments keep the real hour. Two other main changes that touch you: (1) `app.py` now calls `vigil.intel.warm()` once at startup when your router imports, so implement `warm()` in `vigil/intel/__init__.py` exactly as your prompt says (never raises, idempotent); (2) `GraphScene.version` is now a content hash (`scene-<16 hex>`), not the graph-counter cache key, so do not parse it — use `GRAPH.version` for your own caching. Main: 223 tests pass at 01:19 IST. Do not edit clock.py / sim / engine."
