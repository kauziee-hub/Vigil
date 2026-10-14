# CHANGELOG

## v12.3 — same-size network and map, aligned lower rows (2026-10-14, Claude 1)

- The live network and the money map now have the same width (rows 1 and 2 share 2 : 1 columns) and the same height (row 1 takes row 2's measured height); the tape and Needs attention match them.
- Situation brief | money by channel and close monitoring | mule pipeline stretch to one height each; long lists scroll inside their card (a class-name clash that shifted the monitoring card by 13 px is fixed).

## v12.2 — aligned Overview, state-to-state view, calm normal run made explicit (2026-10-14, Claude 1)

- **Aligned rows**: the network card and the tape card are both exactly 668 px; the map card and Needs attention share their height; the 3D view fills its card.
- **Nothing floats over the map**: the "Corridors to watch" overlay is gone; the rail has a **Between states** tab (`geo_map → state_flows`): state-to-state routes, risky first, fraud-linked / early-warning / ordinary split, risky accounts, main city pair, and where most fraud-linked money ends. Clearing a selection returns to the whole country.
- **Normal run vs test inputs**: measured — background traffic alone creates no fraud (12 minutes after a reset: 185 accounts active, 85 flows, 0 red; only the seeded Kiran Traders flagged and Zenith Exports at early warning). The Test inputs button now reads "Test inputs · N active" after any test input, because those accounts stay flagged until a reset.
- Docs updated in place (functional and technical guides, demo script, test book), screenshots replaced, unused images removed.

## v12.1 — location intelligence (2026-10-14, Claude 1)

- **Location becomes evidence, carefully** (`backend/vigil/geo/intel.py`, `config/location_policy.yaml`): impossible travel (precision-aware: effective distance after subtracting both points' accuracy, high / low confidence), coordinated cash-out clusters (now with ATM terminals, time window, withdrawals, rule), and location-behaviour anomalies (unusual region against the account's own 90-day geography, multi-city burst). Only presence bases count (device GPS, ATM terminal, branch; IP at low confidence); card-POS and KYC addresses never do; sender–recipient distance is never a signal.
- **Corroborating only**: a high-confidence location rule can stand in for the missing second voice in the live status rule (`intel/stream.classify(..., location=True)`), never create a status alone, never touch a payment tier or `risk_policy.yaml`. With location off the rule is byte-for-byte the old one (tested over every combination). When it changes a status, the reason names the rule, observed value, threshold and basis; `status_map()` carries `location`.
- **Incidents**: impossible travel feeds the existing possible-account-takeover alert, clusters the existing cash-out alert, both with location quality in their facts (titles unchanged).
- **API / live**: `GET /api/geo/intel` (signals, normal-geography picture, thresholds, selection context); WebSocket `geo.location_intel` when findings change.
- **Money Map**: a Location intelligence rail inside the card (no new section) reacting to the selection; violet impossible-travel routes, numbered account moves from home, cluster ATMs with a callout; "Corridors to watch" now say why; the city card became a purposeful city context in the rail. Overview orientation unchanged; network and map taller.
- **Tests**: `tests/test_location_intel.py` (16 with v12.2's state-flow test); demo test book Suite L (6 checks).

## v12 — demo test book (2026-10-13, Claude 1)

- **Demo test book** (`docs/DEMO_TEST_BOOK.md`, PDF `docs/Vigil_Demo_Test_Book.pdf`): every test input, the result it must give, where to look and what it proves, in seven suites — the PRIMA tier ladder (one payment per tier), policy behaviour (pressure words alone, corroboration, large-but-normal, velocity, the circuit-breaker cap), all 11 attack patterns with their detection result and Vigilance alert, the feedback loop (confirmed report → TaintTrace → the same payment held → incidents and the 12-step procedure → release), controls (false-positive control, shadow mode), all patterns back to back, and the cash-out cluster combination. A 15-minute demo order with checkpoints and a troubleshooting table.
- **`scripts/test_book_check.py`** replays every case through the HTTP API and checks it (117 checks).
- **Test inputs drawer (additive):** a "More tiers" row so every tier has a one-click input, and an **Expected:** line under the chosen preset and the selected pattern. The original presets are unchanged.

## v8 — operations center, close monitoring, explained Detection, functional guide (2026-10-13, Claude 1)

- **Overview = live activity only**, nothing duplicated elsewhere: KPI strip (postings, value moved, accounts at risk, open interventions, new accounts, last detection run: click to frame the attack in the network) → **full-width, taller live network** → Needs attention (each account with its reason, status-since time and how many families agree) beside **Close monitoring** → **Money moving now** (payments per 30 s by origin, value, risky postings, channels, largest payments) beside **New accounts** (opened in the last 30 days, inflow since opening, large-inflow and shared-device flags). SHAP and detector families moved to Detection; decisions by tier stay on Governance / Health.
- **Close monitoring (watchlist):** pin any account (Watch on the account page or the network drawer, optional note); live suggestions for early warning, uncorroborated model evidence and pattern matches; 72 h activity and "what would flag it next". `GET/POST/DELETE /api/watchlist`, cleared by a demo reset.
- **Detection explained:** four numbered sections, and every chart has a Shows / How to read / Right now caption with live takeaways. Duplicated charts removed (volume, channels, decisions by tier).
- **Backend (additive):** universe accounts carry `reason`, `families`, `families_flagging`, `status_since`; `LiveStats.traffic`; `GET /api/live/new-accounts`; `account.opened` and `watchlist.updated` events.
- **Fixes:** live status changes keep their reason on the Overview; positioning no longer says the model layer is "in progress"; recipient risk-evolution title; toast link to the attack history.
- **Functional guide** (beginner level, 67 screenshots, demo script, live attack-check table): a Claude Doc; screenshots in `docs/guide/img/`.

## v11 — Vigilance, the requested Overview orientation, a better map, two guides (2026-10-13, Claude 1, branch `overview-v10`)

- **Vigilance** (the v10 Copilot, renamed and rebuilt as a fraud-operations agent): every alert is classified (label, typology, severity, respond-within target) with a one-sentence situation in rupees; a ranked Vigilance bar on top of the Overview, toasts when an alert is raised or escalated, and one chat box whose alert cards open a **case** — an assessment (red flags from the detection rules or the payment decision's analyst reasons, key facts, risk if ignored, recommendation, confidence; Gemini only phrases the narrative and is validated) and the bank **procedure** in four phases (`copilot/playbooks.py`: contain → investigate → report → recover & close, citing PMLA STR / FIU-IND, RBI FMR, RBI 2017 customer liability, 1930 / CFCFRMS; steps tick themselves when Vigil sees the outcome or are ticked by the analyst). STR grounds draft. Global dock: it stays open on every page and carries map / network actions back to the Overview; "Ask Vigilance" on the account and case pages.
- **Gemini on a free key:** the key may be `GEMINI_API_KEY`, `GEMINI_API` or `GOOGLE_API_KEY`, in `.env` or `backend/.env`; Gemini 3.x thinking kept low so answers fit; few tool calls; offline fallback on rate limits.
- **Overview orientation:** Vigilance bar → KPI strip → live network | live transactions → money map | needs attention → situation brief | money by channel → close monitoring | mule pipeline.
- **Money map:** risky corridors glow with dashes moving in the money's direction, hover a corridor for its details, "Top corridors" panel, city card with Ask Vigilance, grid, glow, distance scale; corridor clicks frame both ends.
- **Fixes:** SPA path traversal (could have served `backend/.env`; now refused, with a test); the held-payment procedure opened the sender's page as "the recipient"; the coerced-payment assessment used the customer's message as a red flag; offline chat matched "str" inside other words.
- **Docs:** the functional guide (Claude Doc) gained the new Overview chapter and a Vigilance chapter; a full technical guide (`docs/TECHNICAL_GUIDE.md`, 23 sections + Appendix A, and a 13-tab Claude Doc with diagrams and screenshots).
- **Tests:** 381 backend tests (+6 procedures, +1 traversal), all pass; frontend checks 20/20.

## v10 — Overview money map, live tape, mule pipeline, Copilot (2026-10-13, Claude 1, branch `overview-v10`)

Baseline and regression numbers: `docs/verification/baseline_v10.md`, `regression_v10.md`.
- **Data (P1):** simulated locations on every posting (basis + accuracy), hash-derived homes in 22 cities, 172 generated ATM terminals, rails (UPI / IMPS / NEFT / RTGS / card / ATM / wallet / international wire; a rail selector on the phone), a 40-account legitimate onboarding cohort and an `ext:intl-wire` sink — all appended after the main seed (world digest unchanged; 0 status changes; 11/11 attacks, 0 FP).
- **APIs (P2):** money map, tape, connections, KPIs, rings, pipeline, exits, channels, brief, attention, signals; all read-only, worst cold call 21 ms.
- **Overview (P3–P6, P9):** money map (flat + lazy globe, India point-of-view Natural Earth boundary, bundled offline), virtualised live tape + connections drawer, shared selection, compact 3D network, KPI strip with deltas and sparklines, needs attention with ₹ in / out, situation brief, mule pipeline, money by channel, incident mode, collection points.
- **Copilot (P7–P8):** deterministic incident engine (9 kinds, hand-set severity rubric with its components), structured briefings (Gemini JSON when a key is set, validated; deterministic template otherwise), read-only tool chat over SSE, strip + dock UI, safe markdown, whitelisted UI actions, offline mode.
- **Tests:** world digest, geo / rails / cohort (12), overview APIs (6), Copilot (18), frontend checks (18, `node scripts/frontend_checks.mjs`).

## v7 — no Razorpay, focused Overview, verified attacks (2026-10-13, Claude 1)

- **Razorpay removed.** Payments settle on a simulated rail behind the provider port. Gone: gateway probe, keys, checkout, confirm/fallback routes, `-Mock` flag.
- **Overview focused** on what needs action and why: KPI strip, network + needs attention, SHAP drivers, detector families, last detection run, traffic. Account scoring moved to Detection; live activity moved to Network.
- **Attacks verified live.** All 11 patterns detected, 0 false positives, every injected mule surfaced. Circular-ring originator now flagged (closed loop through ≥ 2 accounts counts as structural evidence): 3/4 → 4/4.
- **Neater repository:** superseded plans, audits and old screenshots moved out of the published docs; README rewritten for the current product.

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

User direction: not the green UI; professional, mature, neat; fully functional, nothing fake.

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
- Initialised git (baseline `6ea2941`).
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
- Fixes from the lead's browser walkthrough of the merged build: browsers kept the cached v1 shell (index.html now `Cache-Control: no-cache`, `d6e83ae`); Decision Replay spark path invalid SVG (`4c5b750`); Scenario Lab "Decisions produced" stale after re-running a 1-step scenario (`a3b9ac9`). Walkthrough results: Acts 1–5, control, shadow mode, Transaction Guard live payment all pass. 271 tests.
- Merged Claude 2 run 4 (`c029fb6`, roles-v2.1 / consensus-v2.1): found in the walkthrough — an ordinary customer (ramesh) was shown as a mule "Distributor" with "moderate" agreement after the control rent payment, from early warning + drift alone. Now agreement above "weak" and any mule role require a mule-evidence family (RF, GNN, pattern memory, RingWatch, registry listing). SYNTHETIC VALIDATION on 30 test worlds: "≥ moderate" precision 0.44 → 0.875 at recall 0.865 → 0.858; non-mules given a role 279 → 33 (merchants 153 → 0); no retraining (no fitted artefact changed). Live: ramesh weak / unclassified, kiran strong / collector. UI wording follows (`3e7984a`). 286 tests.

## v1 — MVP (2026-10-06)
