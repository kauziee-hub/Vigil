# AGENT HANDOFF — current state (read this first)

Any agent (Claude / Cursor / Codex) resuming this project, read in order:
1. `AGENT_HANDOFF/MASTER_PROMPT.md` — index of the user's prompts (verbatim files in `prompts/`); the binding one is `prompts/01_MASTER_PROMPT_v2_platform.md`.
2. This file — what is done, what is running, how to run/verify, how to resume.
3. `docs/FINAL_PARALLEL_PLAN.md` — BINDING for v2: 9-area IA, status colours, file ownership, frozen interfaces, merge protocol.
4. `AGENT_HANDOFF/AGENT_LEDGER.md` — one row per agent run; each row links its run record in `runs/`.
5. Your role prompt in `prompts/` (v2: `v2_claude2_*`, `v2_claude3_*`, `v2_codex_engineering.md`, `v2_cursor_polish.md`).

Append to the **Log** at the bottom when you finish a unit of work. Contract/API change requests go in `REQUESTS.md`.

## Status: v2 platform build — in progress (updated 2026-10-07 08:15 IST)

| Area | Owner | Where | State |
|---|---|---|---|
| v1 MVP (lifecycle, risk engine, s0–s4, CircuitBreaker, 2D graph, docs) | Claude 1 | `main` | ✅ verified (see v1 log below) |
| UI audit of v1 (19 states) | Claude 1 | `docs/UI_CURRENT_STATE.md`, `docs/ui_current/` | ✅ |
| Frozen v2 contracts + plan | Claude 1 | `backend/vigil/contracts.py`, `frontend/src/api/*`, `docs/FINAL_PARALLEL_PLAN.md` | ✅ `595d4aa` |
| Provenance, shadow mode + bank baseline, Decision Replay, counterfactuals, decision record, risk timeline, governance, interventions, system health, 3D GraphScene, 10 attack scenarios (15 total) | Claude 1 | `main` (`057bb0b` …) | ✅ live on :8000, tested |
| Reset determinism across all 15 scenarios | Claude 1 | `main` `315ef07` | ✅ test enforces identical world |
| Ambient stream routine-preserving (was flagging ordinary customers within minutes); scenarios pin time-of-day rules | Claude 1 | `main` `0070ff4`, `23dcbbf` | ✅ tested |
| Scoped scenes (`?scenario=`, `?focus=`), touched_accounts = participants only, no Tier-0 counterfactuals | Claude 1 | `main` `0fb20ef`, `e2ea443`, `d2a880e` | ✅ tested |
| ML / detection intelligence (`/api/intel/*`, RF/GAT retrain, SHAP, drift, pattern memory, roles, consensus) | Claude 2 | `main` (merged `4fe0a17`; branch `claude2/run3`) | ✅ merged + live on :8000; 268 tests; report `docs/ML_VALIDATION_REPORT.md` (SYNTHETIC VALIDATION) |
| Frontend redesign (9 areas, 3D network, replay UI, governance) | Claude 3 | `main` (merged `88823fb`; branch `claude3/run3`) | ✅ merged; lead browser walkthrough Acts 1–5 + control + shadow + Guard pass; 3 UI fixes on main |
| Engineering tasks (benchmarks, reset/concurrency/realtime tests, Razorpay harness, fixtures) | Codex | `codex/<task>` | ⏳ prompt issued to operator |
| UI polish | Cursor | `cursor/<task>` | ⏳ unblocked (Claude 3 merged) — operator pastes `prompts/v2_cursor_polish.md`; known items: interventions table height at ~800 px, drift "CHANGE" column = capped z |
| Razorpay test path | — | `backend/vigil/payments/providers.py` | ⚠️ keys rejected (401) → mock fallback; fresh `rzp_test_` keys in `.env` re-enable it |

## How to run / verify

```powershell
powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Reset      # start fresh (builds UI, seeds, serves :8000)
cd backend; .venv\Scripts\python.exe -m pytest -q                 # 271 tests (211 v1 + 15 v2 + 45 intel)
backend\.venv\Scripts\python.exe scripts\smoke_demo.py             # 8 act checks
cd frontend; npm run build                                          # type-check + bundle
```

## How to resume after an interruption (learned 2026-10-06 22:55)
In-process subagents die when the lead's session restarts. On resume:
1. `git worktree list` and `git branch -a`; compare with ledger rows marked IN PROGRESS.
2. For each agent worktree: `git status`. Commit any uncommitted work verbatim as a WIP commit on its branch (say whether it builds), rename the branch (`<agent>/runN-wip`), then remove the worktree.
3. Mark the run INTERRUPTED in its record + ledger; save a resume prompt in `prompts/` BEFORE relaunching; relaunch with a new run record.
4. Every agent prompt now requires a commit after each milestone.

## Key facts an agent must not break
* Money = integer paise; time = ISO UTC `Z`; errors = `{"error":{code,message,details?}}`.
* All FastAPI routes are `async def` (single-thread DB access). Don't add sync `def` routes.
* Policy only in `config/risk_policy.yaml`; bump `version` on any change; frontend never hard-codes thresholds.
* `risk_decisions` is append-only (SQLite trigger).
* Payment authorisation uses only the transparent engine; RF/GNN/drift/pattern memory are **corroborating model evidence**, never fused into the tier. Every model metric is labelled **SYNTHETIC VALIDATION**.
* SHAP explains the MODEL; ReasonLine explains the OPERATIONAL DECISION — separate.
* No account-freeze function; inbound money never held; no RBI branding or text implying real RBI/NPCI/DPIP data.
* Customer text must never contain words in `reasonline.BANNED_CUSTOMER_WORDS`.
* Reset must restore an identical world (test: `test_reset_restores_identical_world_after_every_scenario`).
* Expected tiers (tests enforce): s0→0, s1→2, s4→0, s3→4 (+breaker), s2+label then s1→3 — at ANY hour: scripted scenarios run with `clock.pinned_local_hour()` (14:00 IST); never read `datetime.now()` hour directly, use `clock.local_hour_ist()`.
* `GraphScene.version` is a content hash; don't parse it.

## Next steps (lead)
1. On each agent return: save the verbatim report into its run record + ledger FIRST, then review the diff against the ownership table, merge, run pytest + smoke + `npm run build` + browser walkthrough of all acts.
2. Restart the backend after merges (the reset fix `315ef07` and Claude 2's router need a restart).
3. Docs after merge: `DEMO_SCRIPT.md` v2, `README.md`, `KNOWN_LIMITATIONS.md`, `MODEL_CARD.md` check, CHANGELOG.
4. Codex / Cursor outputs: the operator pastes them back; record before merging.

## Log (newest last)


- 2026-10-06 Claude 1 — audited ccmule-main, "Actual ML - Laggy", PRIMA → `docs/CURRENT_STATE_AUDIT.md`, `docs/TARGET_ARCHITECTURE.md`.
- 2026-10-06 Claude 1 — skeleton; vendored `PRIMA/prima` → `backend/prima` + 190 tests. `.env` copied from PRIMA (git-ignored; never print).
- 2026-10-06 Claude 1 — backend complete (`backend/vigil/**`), 210 tests.
- 2026-10-06 Claude 1 — frontend complete (`frontend/src/**`), builds clean; run scripts; walkthrough of Acts 1–5 in browser.
- 2026-10-06 Claude 1 — fixes from walkthrough: Razorpay startup probe + auto-mock on 401; fan-in counts first-time senders only; labelled-neighbour rule follows money downstream (victims no longer scored); graph re-fit on resize; panel/button layout. 211 tests + smoke pass.
- 2026-10-06 Claude 1 — docs: MODEL_CARD, REAL_WORLD_POSITIONING (web-verified), KNOWN_LIMITATIONS, DEMO_SCRIPT, README, BENCHMARK_RESULTS, PARALLEL_WORK_PLAN, AGENT_PROMPTS.
- 2026-10-06 22:10–22:52 Claude 1 — v2: UI audit (19 screenshots), git + systematic AGENT_HANDOFF, frozen v2 contracts + `FINAL_PARALLEL_PLAN.md` (`595d4aa`), agent prompts (`7fece12`), lead backend (provenance, shadow, replay, counterfactuals, record, governance, interventions, health, 3D scene, 10 attacks; `057bb0b`), docs (`70a0520`).
- 2026-10-06 22:43 Claude 1 — launched Claude 2 + Claude 3 (run 1) in worktrees; issued Codex/Cursor prompts.
- 2026-10-06 ~22:55 — session restart killed both subagents. 22:59 user: "continue from here". Claude 3 WIP recovered → `claude3/run1-wip` (`b18a203`, tsc 11 errors); Claude 2 had written nothing.
- 2026-10-06 23:05 Claude 1 — relaunched Claude 2 + Claude 3 as run 2 (`3e545c0` records + resume prompts).
- 2026-10-06 23:08 Claude 1 — reset fix: AUTOINCREMENT counters cleared on wipe + full-world reset test (`315ef07`); no counterfactuals for Tier 0 (`d2a880e`). 218 tests pass.
- 2026-10-06 23:11–23:15 Claude 1 — scoped scenes + 404 unknown scenario (`0fb20ef`); touched_accounts = participants only (`e2ea443`); backend restarted on :8000; mid-run notes to Claude 2/3 recorded. 221 tests pass.
- 2026-10-06 ~23:45 — second session restart killed both run-2 agents (last writes: Claude 3 23:31, Claude 2 23:43). Milestone commits survived this time.
- 2026-10-07 01:00 user: "CONTINUE IMPLEMENTATION" (`prompts/03_USER_resume_2026-10-07_0100.md`).
- 2026-10-07 01:02–01:10 Claude 1 — recovered uncommitted work verbatim: `claude2/run2-wip` (`871df51`: detectors, train_all, trained artefacts), `claude3/run2-wip` (`ba5f83d`: Replay.tsx; tsc clean); stopped orphaned Vite :5183; removed both worktrees; records + ledger updated; `*.tsbuildinfo` ignored; relaunched both as run 3 (`prompts/v2_claude{2,3}_run3_resume.md`).
- 2026-10-07 01:15–01:30 Claude 1 — found s1 → Tier 3 between 00:00–05:00 IST (BEH_ODD_HOUR read the wall clock; 2 lifecycle tests failed at night): scenarios now pin the local hour, audit records `evaluation_context`; scene version = content hash; `app.py` calls `vigil.intel.warm()` when present (`23dcbbf`). 223 tests + smoke 8/8 at 01:25 IST. Backend restarted under preview config `vigil` (:8000, DB kept). Mid-run notes: Claude 2 (wall-clock fix, warm(), scene version), Claude 3 (restart; final-score colour must follow tier, not network bands).
- 2026-10-07 ~01:53 — usage limit stopped the session and Claude 3 (HTTP 429). Claude 2 had returned at ~01:51 (report saved verbatim `e26122d`, merged `4fe0a17`, 268 pass).
- 2026-10-07 07:29 user: "continue from where you left off". Claude 1 — Claude 3 WIP committed (`24f14cf`, tsc clean); backend restarted with intel live (5 routes 6–131 ms); found 130/140 accounts flagged on the live world → ambient stream made routine-preserving + 20 s interval (`0070ff4`, 269 pass, smoke 8/8); live world reset (07:36) → only kiran.traders + zenith.exports flagged; Claude 3 resumed with context (`prompts/v2_claude3_run3_continue_after_limit.md`); payment path verified (model evidence present, kinds honest, never in tier).
- 2026-10-07 07:50–08:15 Claude 1 — Claude 3 returned (report saved `86da0b8`), merged `88823fb`; build green; implemented its `min_tier` request (`00f3920`); browser walkthrough of every act on the merged build → fixed cached v1 shell (`d6e83ae`), replay spark SVG (`4c5b750`), stale Lab panel (`a3b9ac9`); found an ordinary customer (ramesh) labelled "Distributor" by EW + drift alone → Claude 2 run 4 launched (`prompts/v2_claude2_run4_roles_consensus_followup.md`; resume of the run-3 agent failed because its worktree was removed). Demo world reset, ACTIVE.
