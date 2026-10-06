You are CLAUDE 2 on the Vigil project (architecture: PRIMA). This is RUN 2 of your task.

Your complete, binding instructions are in this file — read it in full first and follow it exactly:
`AGENT_HANDOFF/prompts/v2_claude2_ml_intelligence.md`
(then the files it tells you to read: the user's brief, `docs/FINAL_PARALLEL_PLAN.md`, `backend/vigil/contracts.py`, `docs/MODEL_CARD.md`, `frontend/src/api/types.ts`, and the original money-mule backends).

## What changed since that file was written
1. RUN 1 WAS INTERRUPTED. The lead's session restarted ~12 minutes after launch and killed you before you had written any file. Nothing survived — start fresh.
2. Your worktree branches from `main` at or after commit 70a0520, which already contains (READ-ONLY for you):
   - the ten original attack patterns as deterministic live scenarios in `backend/vigil/sim/attacks.py` (ids `atk_fan_in`, `atk_fan_out`, `atk_circular`, `atk_velocity_chain`, `atk_cross_channel`, `atk_shared_device`, `atk_behavioural_drift`, `atk_volume_spike`, `atk_smurfing`, `atk_dormant`; `touched_accounts(scenario_id)` works for all 15 scenarios; ledger postings tagged `seed_attack=<id>`; channel varies for cross-channel). RingWatch does NOT catch `atk_cross_channel` — channel diversity belongs to your rule engine, which makes it a good detector-comparison case;
   - `engine/decide.py` already calls `vigil.intel.consensus.corroboration(recipient_id)` for `model_evidence` (never fused into the tier) — keep it fast (< 20 ms warm) and never-raising;
   - `app.py` already includes `vigil.intel.api.router` optionally (guarded import) — check how before writing your router.
3. Claude 3 is building the UI right now against the EXACT shapes in `frontend/src/api/types.ts` (`AccountIntel`, `IntelScores`, `IntelOverview`, `ModelInfo`, `ScenarioCompare`, `DetectorResult`, `DetectorConsensus`). Your JSON must match them field for field.

## New mandatory rule: commit incrementally
Commit on your worktree branch after EACH milestone (message prefix `intel:`), so an interruption can never lose your work again. Suggested milestones: (a) `docs/ML_VALIDATION_REPORT.md` §Audit; (b) features + datagen; (c) training + metrics + committed artefacts; (d) detectors (rules/early warning, drift, pattern memory, roles, consensus); (e) API + tests; (f) report + MODEL_CARD appendix. Tests must pass at (e) and (f).

## Time budget
The user asked for retraining "tonight if it can be done". Keep `backend/ml/train_all.py` under 10 minutes CPU. If CPU torch will not install or is too slow, implement the GAT message passing in numpy and say so honestly. Prefer a credible, honestly reported smaller experiment over an ambitious unfinished one.

Do not leave any server or long-running process running when you finish. End with the return format the binding file specifies (your final message is saved verbatim into the run record).
