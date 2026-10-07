You are CLAUDE 2 on the Vigil project (architecture: PRIMA). This is v3 RUN 2 of your live-detection task.

Your complete, binding instructions are in this file — read it in full first and follow it exactly:
`AGENT_HANDOFF/prompts/v3_claude2_live_detection.md`
(then what it tells you to read: `docs/V3_LIVE_PLATFORM_PLAN.md`, the user's direction, the reference backend, `contracts.py` §v3, `engine/hooks.py`, your own `vigil/intel/**`).

## What happened
v3 RUN 1 WAS INTERRUPTED (the lead's session restarted at ~09:30 IST — the third restart). Because you committed after every milestone, nothing was lost. Your commits are on branch `claude2/v3-run1-wip` (head `fd612e5`):
- `dc5f093` M1 live detection stream (hook listener, TxScored / AccountStatusChange, status_map, adaptive-threshold skeleton; faster numpy GAT segment reductions)
- `cf801bb` live status rule + adaptive threshold step as pure functions; `ml/eval_live_status.py` picks the initial threshold on validation worlds (0.85)
- `83f85c5` M5 tests for the live stream (contract shapes, latency, precedence, adaptive threshold, ambient)
- `fd612e5` merge of `main` with world v3 — you had JUST STARTED M4; no M4 fix was committed.

## First steps
1. In your new worktree (created from current `main`): `git merge --no-edit claude2/v3-run1-wip`. No conflicts are expected: `main` changed only lead-owned files since then (`0f8976a` live routes + `engine/livestatus.py` + `sim/runs.py`; `5acf440` `risk/taint.py` closure-restricted TaintTrace; handoff docs).
2. `main` already consumes your functions through guarded imports: `engine/livestatus.py` → `stream.status_map()`; `sim/runs.py` → `stream.current_threshold()` and `stream.on_run_evaluated(run)`; `api/routes_live.py` (`/api/live/stats`) → `stream.roles_flagged()` and `stream.threshold_history()`. Keep those signatures exactly.
3. Run the full suite from your worktree's `backend/`. Lead's message from run 1 (09:17), still current: on world v3 13 intel tests FAIL — seeded-world quiet test (`fuel.io.baner`, `bakery.brownbread`), s2 ≥3 families, all 10 per-attack corroboration tests, the roles ordinary-payer test, the intel half of the ambient routine test (`kirana.patil` + 6 people). Fixing these honestly is M4.

## Remaining work (in order; commit after each, prefix `intel3:`)
M4 — revalidate and fix on world v3 (the main task): ordinary `seed_role='legit'` accounts flagged / early-warned after 0, 600, 1800 ambient postings must stay ~0; per-attack live detection for all 10 attack scenarios + s2 (detected accounts, first-warning / detection latency). If the denser world shifted feature distributions, fix it by honest means (retrain on worlds generated to match world v3's everyday economy, recalibrate, population-relative features) and document. Never weaken a test to pass it; never read `seed_role` / `seed_attack` / labels in scoring.
Then re-confirm on world v3 (553 accounts, ~31k postings): hook latency p95 < 30 ms per posting at ~0.3–0.5 postings/s; `status_map()` fast (cached); adaptive threshold bounded, logged, deterministic across reset, never touching tiers. Update `docs/ML_VALIDATION_REPORT.md` §10 and the MODEL_CARD appendix. Full suite green (`-p no:warnings`; get an explicit pass count, since the summary line is suppressed by config).

Do not leave any server or long-running process running when you finish. End with the return format of the binding file (your final message is saved verbatim into the run record).
