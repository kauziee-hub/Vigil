# AGENT HANDOFF — current state (read this first)

Any agent (Claude / Cursor / Codex) resuming this project, read in order:
1. `AGENT_HANDOFF/MASTER_PROMPT.md` — index of the user's prompts (verbatim files in `prompts/`); the binding one is `prompts/01_MASTER_PROMPT_v2_platform.md`.
2. This file — what is done, what is running, how to run/verify, how to resume.
3. `docs/archive/plans/V3_LIVE_PLATFORM_PLAN.md` — BINDING for v3 (live platform: interfaces, status semantics, ownership); `docs/archive/plans/FINAL_PARALLEL_PLAN.md` — v2 base (9-area IA, status colours, merge protocol).
4. `AGENT_HANDOFF/AGENT_LEDGER.md` — one row per agent run; each row links its run record in `runs/`.
5. Your role prompt in `prompts/` (v2: `v2_claude2_*`, `v2_claude3_*`, `v2_codex_engineering.md`, `v2_cursor_polish.md`).

Append to the **Log** at the bottom when you finish a unit of work. Contract/API change requests go in `REQUESTS.md`.

## Status: v8 — operations center, close monitoring, explained Detection, functional guide (updated 2026-10-13 03:30 IST)

User direction (`prompts/10_USER_functional_guide_overview_watchlist_2026-10-13.md`).

* Overview = live activity only: KPI strip → full-width network → Needs attention (reasons) | Close monitoring (watchlist) → Money moving now | New accounts. SHAP / detector families on Detection; decisions by tier on Governance.
* Detection: four numbered sections; every chart captioned (Shows / How to read / Right now).
* New APIs (additive): `/api/watchlist` (GET/POST/DELETE), `/api/live/new-accounts`, `LiveStats.traffic`, universe `reason` / `families` / `status_since`.
* Functional guide (Claude Doc): https://claude.ai/code/artifact/bf16f71c-e278-4271-ac55-27e269ca9bac ; screenshots `docs/guide/img/`.
* Live attack check: 11/11 detected, 0 FP (s2 3/4, velocity 3/5, rest full; circular 4/4 in a fresh world).
* Next (user): the technical guide. Not committed yet.

## Status: v10 — Overview money map, live tape, mule pipeline, Copilot (updated 2026-10-13 ~06:30 IST)

Plan `prompts/10_OVERVIEW_V10_MASTER_PLAN.md`, implemented on branch **`overview-v10`** (not merged into `main`, not pushed). Baseline / regression: `AGENT_HANDOFF/baseline_v10.md`, `regression_v10.md`. Record: `runs/20261013-0330_claude1_v10-overview-money-map-copilot.md`.

* Overview = KPI strip → Copilot strip → money map (flat / globe, simulated locations, India point-of-view boundary) | live tape → compact 3D | needs attention | brief → close monitoring | mule pipeline → money by channel; Copilot dock.
* Copilot: deterministic incident engine + briefings + read-only chat; offline by default; `GEMINI_API_KEY` in `.env` enables Gemini (sends synthetic incident facts to Google).
* Key facts not to break: world digest (`tests/test_world_digest.py`); cohort excluded from attack pools and the background stream; locations never feed a score / tier; Copilot has no write tools and never reads `seed_*`.
* Gates: pytest 374/374, smoke 8/8, 11/11 attacks 0 FP, tsc + build green, frontend checks 18/18 (`node scripts/frontend_checks.mjs`).
* Functional guide v10: `docs/guide/VIGIL_FUNCTIONAL_GUIDE.md` (images in `docs/guide/img/v10_*`).
* Screenshots via Playwright: use `http://127.0.0.1:8000` (the profile has a saved 33 % zoom for `localhost`).

## Status: v7 — no Razorpay, focused Overview, attacks verified (updated 2026-10-13 00:40 IST)

User direction (`prompts/09_USER_fix_remove_razorpay_cleanup_overview_2026-10-12.md`).

* Payments: simulated rail only, behind the `PaymentProvider` port. No `.env` or keys are needed (Razorpay fully removed).
* Overview: KPI strip → network + needs attention → why flagged (SHAP, detector families, last run) → traffic. Full account scoring is on Detection; live streams are on Network.
* Attacks (live check): 11/11 patterns detected, 0 false positives, every injected mule surfaced. Partial by design: money-mule network 3/4 and velocity chain 3/5 (the extra accounts are at early warning). Circular ring fixed to 4/4.
* Docs: current docs in `docs/`, current screenshots in `docs/screenshots/`, superseded material in `docs/archive/`.
* Backend tests: 330/330 pass.

## Status: v6 — identity, iPhone device, graph edge filter, overview architecture; on GitHub (updated 2026-10-12 22:50 IST)

User direction (`prompts/08_USER_logo_iphone_graph_overview_push_2026-10-12.md`).

* Repository: `https://github.com/kauziee-hub/Vigil.git`, branch **`main`** (the local `master` was renamed by the user on publish). Push fast-forward only; never push `.env`.
* UI v6: logo + VIGIL wordmark, iPhone customer device, edge filter (Recent / Window / Risk only / All / Off), Overview KPI strip, detection performance, full account scoring (549). `docs/screenshots/*`.
* Before presenting: Test inputs → Reset demo world (or `run_demo.ps1 -Reset`). Backend unchanged (330/330).

## Status: v5 final-demo build — ready (updated 2026-10-12 22:15 IST)

User direction (`prompts/07_USER_reference_ui_final_demo_2026-10-12.md`): UI like `docs/archive/references/reference_v5/*`; all PRIMA + mule features ordered by priority; SHAP; minimal test inputs, not a simulation panel; demo tomorrow.

* UI v5: light soft-card design, pill top navigation, Operations center overview, Test inputs console (Alt+T). `docs/archive/screenshots/ui_v5/*`.
* Demo script: `docs/DEMO_SCRIPT.md` (8 steps, all verified live).
* Before presenting: `run_demo.ps1 -Reset`. Payments use the mock provider until valid `rzp_test_` keys are in `.env`.
* Backend unchanged since `64e2b30` (330/330).

## Status: v4 professional UI — done by Claude 1 alone (updated 2026-10-09 10:30 IST)

User direction 2026-10-09 (`prompts/06_USER_professional_ui_2026-10-09.md`): not the green UI; professional, mature, neat; fully functional, nothing fake.

| Area | Where | State |
|---|---|---|
| v3 agents (stopped by usage limit 10-07) recovered + merged | `claude3/v3-run2-wip` → `a8be146`; `claude2/v3-run2-wip` → `99c4955` | ✅ |
| Design system v4 (graphite, steel-blue accent, IBM Plex, flat hairline, sentence case, icon nav, light theme) | `8c10d32`, `docs/DESIGN_SYSTEM.md` §v4 | ✅ every area reviewed at 1600×1000 + contact at 390 px |
| Honesty: SHAP signed categories; exact tier mix; one heading per panel | `85a6c73`, `97437db` | ✅ |
| Detection consensus-v2.2 (structural flagged route; model evidence needs onward flow) | `d071d56`, `docs/ML_VALIDATION_REPORT.md` §10.x | ✅ live: circular 4/4, fan-in 1/1, drift 1/1, s2 3/4, 0 FP; victims weak/no role |
| Perf: RingWatch scan 228→44 ms; reset re-warms intel | `f230e09` | ✅ |
| Functional audit (Playwright on the real backend) | run record `runs/20261009-0013_claude1_v4-professional-ui.md` | ✅ 15 routes, 0 console/API errors; every control exercised |
| Razorpay | `.env` | ⚠️ keys rejected → mock provider (needs fresh `rzp_test_` keys) |

Demo note: payments made from Transaction Guard use the real clock, so after midnight Act 2 is Tier 3 (unusual-hour +0.05 crosses 0.42); during the day it is Tier 2. Scripted scenarios pin 14:00.

## Status: v3 live platform — superseded by v4 (updated 2026-10-07 09:45 IST)

User direction 2026-10-07 (`prompts/04_USER_refined_mule_repo_2026-10-07.md`): match/beat the refined money-mule repo's live 3D transaction universe, analytics and look, keeping every PRIMA feature.

| Area | Owner | Where | State |
|---|---|---|---|
| Frozen v3 contracts (LiveUniverse, TxScored, AccountStatusChange, AttackRun, LiveStats), posting hooks, plan | Claude 1 | `main` `9bbd08e` | ✅ |
| World v3: everyday economy (553 accounts, ~31k postings, anchor-relative, deterministic), habit-driven P2M ambient (3 s, routine-preserving), RingWatch fan-out/smurfing refinements (policy 2026.10.07-v3.1) | Claude 1 | `main` `d3bc3d3` | ✅ |
| Live backend: `/api/live/universe`, `/api/live/stats`, `/api/attacks/runs` (+ WS `attack.run_updated`), live status resolver, attack-run evaluation | Claude 1 | `main` `0f8976a` | ✅ live on :8000 |
| TaintTrace v3: exact forward-closure perimeter + incremental cache (2,026 ms → 13 ms on world v3) | Claude 1 | `main` `5acf440` | ✅ tested (matches full trace) |
| Live detection stream, adaptive threshold, world-v3 revalidation (13 intel tests fail on world v3 until M4) | Claude 2 | run 1 → `claude2/v3-run1-wip` (`fd612e5`); run 2 running since 09:42 | 🔄 |
| Live platform UI (design v3, LiveUniverse3D, Live Operations, Network, restyle all areas) | Claude 3 | run 1 → `claude3/v3-run1-wip` (`4f842af`, M1–M4); run 2 running since 09:42 | 🔄 |
| Engineering tasks / UI polish | Codex / Cursor | operator | ⏳ prompts issued |

Known red on `main` until Claude 2 v3 merges: 13 intel tests (world v3 shifted feature distributions — M4).

## Status: v2 platform build — complete (as of 2026-10-07 08:40 IST)

| Area | Owner | Where | State |
|---|---|---|---|
| v1 MVP (lifecycle, risk engine, s0–s4, CircuitBreaker, 2D graph, docs) | Claude 1 | `main` | ✅ verified (see v1 log below) |
| UI audit of v1 (19 states) | Claude 1 | `docs/archive/plans/UI_CURRENT_STATE.md`, `docs/archive/screenshots/ui_current/` | ✅ |
| Frozen v2 contracts + plan | Claude 1 | `backend/vigil/contracts.py`, `frontend/src/api/*`, `docs/archive/plans/FINAL_PARALLEL_PLAN.md` | ✅ `595d4aa` |
| Provenance, shadow mode + bank baseline, Decision Replay, counterfactuals, decision record, risk timeline, governance, interventions, system health, 3D GraphScene, 10 attack scenarios (15 total) | Claude 1 | `main` (`057bb0b` …) | ✅ live on :8000, tested |
| Reset determinism across all 15 scenarios | Claude 1 | `main` `315ef07` | ✅ test enforces identical world |
| Ambient stream routine-preserving (was flagging ordinary customers within minutes); scenarios pin time-of-day rules | Claude 1 | `main` `0070ff4`, `23dcbbf` | ✅ tested |
| Scoped scenes (`?scenario=`, `?focus=`), touched_accounts = participants only, no Tier-0 counterfactuals | Claude 1 | `main` `0fb20ef`, `e2ea443`, `d2a880e` | ✅ tested |
| ML / detection intelligence (`/api/intel/*`, RF/GAT retrain, SHAP, drift, pattern memory, roles, consensus) | Claude 2 | `main` (run 3 `4fe0a17`, run 4 `c029fb6`; branches `claude2/run3`, `claude2/run4`) | ✅ merged + live; roles/agreement need mule-structure evidence (run 4); report `docs/ML_VALIDATION_REPORT.md` (SYNTHETIC VALIDATION) |
| Frontend redesign (9 areas, 3D network, replay UI, governance) | Claude 3 | `main` (merged `88823fb`; branch `claude3/run3`) | ✅ merged; lead browser walkthrough Acts 1–5 + control + shadow + Guard pass; 3 UI fixes on main |
| Engineering tasks (benchmarks, reset/concurrency/realtime tests, Razorpay harness, fixtures) | Codex | `codex/<task>` | ⏳ prompt issued to operator |
| UI polish | Cursor | `cursor/<task>` | ⏳ unblocked (Claude 3 merged) — operator pastes `prompts/v2_cursor_polish.md`; known items: interventions table height at ~800 px, drift "CHANGE" column = capped z |
| Razorpay test path | — | `backend/vigil/payments/providers.py` | ⚠️ keys rejected (401) → mock fallback; fresh `rzp_test_` keys in `.env` re-enable it |

## How to run / verify

```powershell
powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Reset      # start fresh (builds UI, seeds, serves :8000)
cd backend; .venv\Scripts\python.exe -m pytest -q                 # 286 tests (211 v1 + 15 v2 + 60 intel)
backend\.venv\Scripts\python.exe scripts\smoke_demo.py             # 8 act checks
cd frontend; npm run build                                          # type-check + bundle
```

## How to resume after an interruption (learned 2026-10-06 22:55; used 3×)
In-process subagents die when the lead's session restarts. On resume (also: `ListAgents` to confirm they are dead; stop orphaned Vite servers they left; `cd` out of a worktree before removing it):
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


- 2026-10-06 Claude 1 — audited ccmule-main, "Actual ML - Laggy", PRIMA → `docs/archive/plans/CURRENT_STATE_AUDIT.md`, `docs/TARGET_ARCHITECTURE.md`.
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
- 2026-10-07 08:30–08:40 Claude 1 — Claude 2 run 4 returned (report saved `9ac5ebb`), merged `c029fb6`, 286 pass; live check: ramesh weak/unclassified, kiran strong/collector; UI wording (`3e7984a`); demo world reset, ACTIVE. Docs: DEMO_SCRIPT v2 (`96b1ce6`), README + startup banner (`24697bc`), Cursor prompt v2.1 (`9ab441e`).
- 2026-10-07 08:45–09:30 Claude 1 — v3: reviewed the refined repo (screenshots `docs/archive/references/reference_refined/`), froze v3 contracts + plan + prompts (`9bbd08e`), launched Claude 2/3 v3 (08:59), world v3 (`d3bc3d3`), live backend (`0f8976a`), TaintTrace v3 (`5acf440`, 2,026 → 13 ms); server restarted 09:29:59.
- 2026-10-07 ~09:30 — third session restart killed both v3 agents. 09:33 user: "continue" (`prompts/05_USER_continue_2026-10-07_0933.md`).
- 2026-10-07 09:35–09:42 Claude 1 — recovered: Claude 3 WIP committed (`4f842af`, tsc ok) → `claude3/v3-run1-wip`; Claude 2 had no uncommitted work → `claude2/v3-run1-wip`; orphaned Vite :5181 stopped; worktrees removed; run records closed as INTERRUPTED; resume prompts saved; both relaunched as v3 run 2 (`6fb1b51`).
- 2026-10-09 00:13–10:30 Claude 1 — v4 (alone; agents stopped by usage limit): recovered + merged v3 work, design system v4, Overview restructure, SHAP honesty fix, consensus-v2.2 detection fixes, RingWatch perf, Playwright functional audit. See `runs/20261009-0013_claude1_v4-professional-ui.md`.
- 2026-10-12 21:28–22:15 Claude 1 — v5: reference-style light UI, top pill nav, Operations center, Test inputs console, Detection runs section; full demo flow verified live; record `runs/20261012-2130_claude1_v5-final-demo.md`.
- 2026-10-12 22:21–22:50 Claude 1 — v6: logo/wordmark, iPhone device, graph edge filter, overview re-architecture (KPI strip, detection performance, full account scoring), Payments policy primer; user published the repo (`f3b6329`), Claude 1 pushed the rest fast-forward; record `runs/20261012-2221_claude1_v6-identity-device-graph-overview.md`.
- 2026-10-12 23:55 – 2026-10-13 00:40 Claude 1 — v7: Razorpay removed; Overview trimmed; all 11 attacks verified live; circular-ring originator fix; docs archived; record `runs/20261013-0000_claude1_v7-razorpay-removal-cleanup-overview-attacks.md`.
- 2026-10-13 00:50–03:30 Claude 1 — v8: Overview rebuilt around live activity (network full width, reasons in Needs attention, close monitoring, money moving now, new accounts); Detection captioned; watchlist / new-accounts / traffic APIs; functional guide (Claude Doc, 67 screenshots). Record `runs/20261013-0050_claude1_v8-operations-center-watchlist-guide.md`.
- 2026-10-13 03:30–06:30 Claude 1 — v10: plan 10 P0–P10 on `overview-v10` (v8 work committed as its base); P1 regression found (cohort leaked into attack pools) and fixed without tuning; guide v10. Record `runs/20261013-0330_claude1_v10-overview-money-map-copilot.md`.
