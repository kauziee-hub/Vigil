# CHANGELOG

## v8 — operations center, close monitoring, explained Detection, functional guide (2026-10-13, Claude 1)

- **Overview = live activity only**, nothing duplicated elsewhere: KPI strip (postings, value moved, accounts at risk, open interventions, new accounts, last detection run: click to frame the attack in the network) → **full-width, taller live network** → Needs attention (each account with its reason, status-since time and how many families agree) beside **Close monitoring** → **Money moving now** (payments per 30 s by origin, value, risky postings, channels, largest payments) beside **New accounts** (opened in the last 30 days, inflow since opening, large-inflow and shared-device flags). SHAP and detector families moved to Detection; decisions by tier stay on Governance / Health.
- **Close monitoring (watchlist):** pin any account (Watch on the account page or the network drawer, optional note); live suggestions for early warning, uncorroborated model evidence and pattern matches; 72 h activity and "what would flag it next". `GET/POST/DELETE /api/watchlist`, cleared by a demo reset.
- **Detection explained:** four numbered sections, and every chart has a Shows / How to read / Right now caption with live takeaways. Duplicated charts removed (volume, channels, decisions by tier).
- **Backend (additive):** universe accounts carry `reason`, `families`, `families_flagging`, `status_since`; `LiveStats.traffic`; `GET /api/live/new-accounts`; `account.opened` and `watchlist.updated` events.
- **Fixes:** live status changes keep their reason on the Overview; positioning no longer says the model layer is "in progress"; recipient risk-evolution title; toast link to the attack history.
- **Functional guide** (beginner level, 67 screenshots, demo script, live attack-check table): a Claude Doc; screenshots in `docs/guide/img/`.

## v10 — Overview money map, live tape, mule pipeline, Copilot (2026-10-13, Claude 1, branch `overview-v10`)

Plan: `AGENT_HANDOFF/prompts/10_OVERVIEW_V10_MASTER_PLAN.md`. Baseline and regression numbers: `AGENT_HANDOFF/baseline_v10.md`, `regression_v10.md`.
- **Data (P1):** simulated locations on every posting (basis + accuracy), hash-derived homes in 22 cities, 172 generated ATM terminals, rails (UPI / IMPS / NEFT / RTGS / card / ATM / wallet / international wire; a rail selector on the phone), a 40-account legitimate onboarding cohort and an `ext:intl-wire` sink — all appended after the main seed (world digest unchanged; 0 status changes; 11/11 attacks, 0 FP).
- **APIs (P2):** money map, tape, connections, KPIs, rings, pipeline, exits, channels, brief, attention, signals; all read-only, worst cold call 21 ms.
- **Overview (P3–P6, P9):** money map (flat + lazy globe, India point-of-view Natural Earth boundary, bundled offline), virtualised live tape + connections drawer, shared selection, compact 3D network, KPI strip with deltas and sparklines, needs attention with ₹ in / out, situation brief, mule pipeline, money by channel, incident mode, collection points.
- **Copilot (P7–P8):** deterministic incident engine (9 kinds, hand-set severity rubric with its components), structured briefings (Gemini JSON when a key is set, validated; deterministic template otherwise), read-only tool chat over SSE, strip + dock UI, safe markdown, whitelisted UI actions, offline mode.
- **Tests:** world digest, geo / rails / cohort (12), overview APIs (6), Copilot (18), frontend checks (18, `node scripts/frontend_checks.mjs`).

## v7 — no Razorpay, focused Overview, verified attacks (2026-10-13, Claude 1)

- **Razorpay removed.** Payments settle on a simulated rail behind the provider port. Gone: gateway probe, keys, checkout, confirm/fallback routes, `-Mock` flag.
- **Overview focused** on what needs action and why: KPI strip, network + needs attention, SHAP drivers, detector families, last detection run, traffic. Account scoring moved to Detection; live activity moved to Network.
- **Attacks verified live.** All 11 patterns detected, 0 false positives, every injected mule surfaced. Circular-ring originator now flagged (closed loop through ≥ 2 accounts counts as structural evidence): 3/4 → 4/4.
- **Neater repository:** `docs/screenshots/` (current), `docs/archive/` (superseded plans, audits, old screenshots, references); README rewritten for the current product.

## v6 — identity, iPhone device, graph edge filter, overview architecture (2026-10-12, Claude 1)

- **Identity:** the "watchful V" mark and a **VIGIL** wordmark in Sora; the same mark is the favicon.
- **Customer device** drawn as an iPhone (bezel, Dynamic Island, live status bar, home indicator). The payment flow is unchanged.
- **Graph edge filter:** Recent / Window / Risk only / All / Off on the Overview and Network pages. Finished flows no longer pile up; Risk only fades ordinary accounts but keeps the counterparties of risky flows visible.
- **Overview** reordered: KPI strip → live network, accounts at risk, payments protected, detector families → needs attention, traffic → why accounts are flagged (SHAP, pattern memory, decisions) → **detection performance** (the mule-detection analytics: last attack result, runs by pattern, latency & recall, adaptive threshold, roles, channel mix, attack history) → live activity → **account scoring** (all 549 scored accounts, sortable and filterable; previously a short scroll box).
- **Payments:** the empty assessment explains the live policy (dimension weights + tier ladder from `/api/policy`).
- Published to `https://github.com/kauziee-hub/Vigil.git` (`main`).

## v5 — reference UI + final demo (2026-10-12, Claude 1)

- **Light operations-center design** modelled on `docs/reference_v5/*`: white 20 px soft cards, pill top navigation with a mint active state, near-black primary buttons, a dark highlight card for the live network, Inter + IBM Plex Mono. Dark theme kept as a toggle.
- **Test inputs** console (top bar or Alt+T), PRIMA `/ops` style: customer payment (opens the real device prefilled), inject a mule-network pattern, coerced journey, report a confirmed scam, traffic / mode / reset. The simulation command center and the demo panels are gone from product screens.
- **Operations center** ordered by priority: network, accounts at risk, payments protected, detector families, needs attention, traffic; then SHAP drivers, pattern memory / early warning, decisions by tier; live activity; scoring.
- Detection page: live detection runs. Alert stream: risk changes only. Demo script rewritten (`docs/DEMO_SCRIPT.md`), with every step verified live.

## v4 — professional UI + functional audit (2026-10-09, Claude 1)

User direction (`AGENT_HANDOFF/prompts/06_USER_professional_ui_2026-10-09.md`): not the green UI; professional, mature, neat; fully functional, nothing fake.

- **Recovery:** both v3 run-2 agents were stopped by the account usage limit. Their work was recovered (`claude2/v3-run2-wip`, `claude3/v3-run2-wip`) and merged (`a8be146`, `99c4955`).
- **Design system v4** (`8c10d32`): neutral graphite field, one steel-blue accent, IBM Plex Sans/Mono, flat hairline panels, 3–8 px radii, sentence case, icon navigation, a real light theme. No gradients, glow, blur, starfield or green. `docs/DESIGN_SYSTEM.md` §v4.
- **Overview restructured:** compact header instead of a hero; one 8-metric strip instead of 12 tiles plus a band; the live transaction network above the fold beside "Needs attention"; attack results grouped with the command center; exact tier-mix counts instead of a rounded "100% zero-friction".
- **Honesty fixes:** the SHAP category chart showed unsigned magnitudes as red "risk" bars, so a pensioner whose model score was pushed *down* read as "Value Risk". It now uses a signed `category_net` and a diverging chart (`85a6c73`). One heading per panel; no numbered crumbs.
- **Detection (consensus-v2.2, `d071d56`):** structural route to live "flagged" (RingWatch ≥ 0.40 plus ≥ 2 intel families); model evidence needs onward money flow (victims are never corroborated, given roles or flagged). Live Scenario-lab runs: circular ring 0/4 → 4/4, fan-in 1/1, behavioural drift 1/1, 0 false positives. `docs/ML_VALIDATION_REPORT.md` §10.x.
- **Performance** (`f230e09`): RingWatch population scan 228 → 44 ms on world v3, exact (equivalence over 561 accounts × 3 times). Demo reset re-warms intel, so the first payment after a reset takes 17 ms (was 675 ms).
- **Functional audit (Playwright, real backend):** 15 routes with 0 console errors, 0 API errors and 0 crashes. Every control exercised end to end: payments (Act 1/2), reset, release, reject, Lab start/pause/resume/replay/compare, trusted-contact response, shadow ↔ active, pause/resume traffic.

## v2 — platform build (in progress, 2026-10-06/07)

### Claude 1 (lead)
- Captured 19 screenshots of every v1 page/state (`docs/ui_current/`) and wrote `docs/UI_CURRENT_STATE.md`.
- Initialised git (baseline `6ea2941`), systematic `AGENT_HANDOFF/` (MASTER_PROMPT index, AGENT_LEDGER, runs/).
- Froze v2 contracts: provenance, detector results/consensus, SHAP, drift, pattern memory, roles, model registry, decision replay, counterfactuals, shadow-mode fields, 3D graph scene (`backend/vigil/contracts.py`, `frontend/src/api/types.ts`, `frontend/src/api/client.ts`).
- `docs/FINAL_PARALLEL_PLAN.md`: 9-item information architecture, status colour scale, ownership, interfaces, merge protocol.
- Optional vigil.intel router hook in app.py; scenarios.touched_accounts().
- Evidence provenance on every risk signal; SHADOW MODE with conventional bank baseline; corroborating model_evidence hook (never fused).
- Decision Replay, counterfactual ladder, decision record, risk evolution (engine/replay.py) — deterministic, same policy engine.
- 3D GraphScene with frozen layered layout and cache (graph/scene.py); v2 routes (api/routes_v2.py).
- Ten attack patterns from the original project as deterministic scenarios (sim/attacks.py); 15 scenarios total.
- Tests: backend/tests/test_vigil_v2.py (6).
- Session restart (~22:55 IST) killed the Claude 2/3 subagents; Claude 3's partial work preserved on `claude3/run1-wip`; both relaunched as run 2 (incremental commits now mandatory).
- Reset fix: `db.wipe()` now also clears SQLite AUTOINCREMENT counters, so a demo reset restores identical ids (previously `intent_transitions` ids kept climbing). New test `test_reset_restores_identical_world_after_every_scenario`: runs all 15 scenarios, toggles SHADOW, resets → every table identical (timestamps masked), mode back to ACTIVE, identical tiers on re-run. 218 tests pass.
- Counterfactuals: none for Tier 0 decisions (the s4 high-value control previously showed a no-op ladder).
- 3D scene scoping fix: `?scenario=` / `?focus=` now return only that scenario's accounts / that account plus 1–2 hops (previously the global suspicious set was mixed in, so every attack looked the same: ~60 nodes). `atk_circular` → 11 nodes / 12 edges, 3 ms; default scene unchanged (60 nodes, ≤ 12 ms, 45 KB). Unknown scenario → 404. 220 tests pass.
- `touched_accounts(atk_*)` now lists only the accounts each pattern actually uses (was the whole 8-account pool: e.g. `atk_circular` reported 8, uses 4), so scoped scenes and detector comparison no longer include bystanders. Test checks it against the `seed_attack` ground truth for all 10 attacks. 221 tests pass.
- Second session restart (~23:45 IST) killed the run-2 agents; milestone commits survived; remainder recovered to `claude2/run2-wip` / `claude3/run2-wip`; relaunched as run 3 (01:10 IST, 2026-10-07).
- Scenario determinism fix: the `BEH_ODD_HOUR` rule read the wall clock, so between 00:00 and 05:00 IST scenario s1 scored 0.45 and became Tier 3 (scoped hold) instead of Tier 2, and two lifecycle tests failed at night. Scripted scenarios now evaluate time-of-day rules at a pinned local hour (`clock.DEMO_LOCAL_HOUR_IST` = 14); live and ambient payments still use the real hour. Every decision's audit payload now carries `evaluation_context` (`local_hour_ist`, `local_hour_source`: "wall clock" or "pinned by scripted scenario"). Test runs s1 at 01:00 and 13:30 IST (both Tier 2) and checks a live payment at 01:00 still fires `BEH_ODD_HOUR`.
- `GraphScene.version` is now a hash of the scene content instead of the cache key, so a re-fetch after unrelated activity (ambient postings bump the graph counter every 3 s) returns the same version and the 3D view keeps its object and replay position. Intel warm-up hook: `app.py` calls `vigil.intel.warm()` at startup when the intel router is present (no-op until Claude 2 merges). 223 tests pass (run at 01:19 IST, inside the odd-hour window).
- Merged Claude 2 run 3 (`4fe0a17`): `/api/intel/*` (accounts, scores, models, overview, scenario compare), `consensus.corroboration` on the payment path (model evidence only, never in the tier), retrained RF + GAT with SYNTHETIC VALIDATION (split-by-world, leave-one-attack-out, calibration, old-vs-honest protocol), SHAP, drift, pattern memory, roles, early warning; `docs/ML_VALIDATION_REPORT.md`, MODEL_CARD appendix. 268 tests pass on main. Live: all five routes 6–30 ms (s2 compare 131 ms).
- Ambient stream fix (found on the live world after Claude 2's merge: 130 of 140 accounts flagged by some detector, ordinary customers labelled "coordinator" with GNN 0.93). Cause: the background stream made one payment every 3 s, ~100x each account's own history, which the drift/early-warning/GNN detectors correctly read as abnormal; measured from a clean world: 29 ordinary customers drift-HIGH after 10 min, 104 of 133 after 40 min. Fix: the stream is now routine-preserving — a payment is made only if both accounts stay at or below their busiest 72 h block of the previous 45 days, otherwise the tick is skipped (`STATE["skipped"]`); default interval 3 s → 20 s (the 133-account world supports ~70 such payments per 72 h). After 800 ticks: 0 ordinary customers flagged by any detector. New test enforces both the per-account invariant and "no ordinary customer flagged" after 400 ticks. 269 tests + smoke 8/8.
- Merged Claude 3 run 3 (`88823fb`): the institutional frontend — 9 areas (Overview, Transaction Guard, Network Intelligence 3D, Detection & Models, Investigations with Decision Replay / risk evolution / counterfactuals / provenance, Interventions, Governance & Audit, Scenario Lab, System Health), trusted-contact phone, design system (`docs/DESIGN_SYSTEM.md`), 20 screenshots (`docs/ui_v2/`). Build green (main 395 kB; 3D and 2D graph lazy-loaded).
- `GET /api/interventions?min_tier=` (Claude 3 request); the queue merges every Tier ≥ 2 alert with the newest 100 so holds never drop out of view (`00f3920`).
- Fixes from the lead's browser walkthrough of the merged build: browsers kept the cached v1 shell (index.html now `Cache-Control: no-cache`, `d6e83ae`); Decision Replay spark path invalid SVG (`4c5b750`); Scenario Lab "Decisions produced" stale after re-running a 1-step scenario (`a3b9ac9`). Walkthrough results: Acts 1–5, control, shadow mode, Transaction Guard live payment all pass (details in `AGENT_HANDOFF/runs/20261007-0110_claude3_frontend-redesign-run3.md`). 271 tests.
- Merged Claude 2 run 4 (`c029fb6`, roles-v2.1 / consensus-v2.1): found in the walkthrough — an ordinary customer (ramesh) was shown as a mule "Distributor" with "moderate" agreement after the control rent payment, from early warning + drift alone. Now agreement above "weak" and any mule role require a mule-evidence family (RF, GNN, pattern memory, RingWatch, registry listing). SYNTHETIC VALIDATION on 30 test worlds: "≥ moderate" precision 0.44 → 0.875 at recall 0.865 → 0.858; non-mules given a role 279 → 33 (merchants 153 → 0); no retraining (no fitted artefact changed). Live: ramesh weak / unclassified, kiran strong / collector. UI wording follows (`3e7984a`). 286 tests.

## v1 — MVP (2026-10-06)
See `AGENT_HANDOFF/runs/20261006-2112_claude1_v1-build.md`.
