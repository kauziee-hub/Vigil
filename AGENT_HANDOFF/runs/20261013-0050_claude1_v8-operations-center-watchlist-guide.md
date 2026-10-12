# Run record — claude1 — v8: operations center (live activity only), close monitoring, explained Detection, functional guide

| Field | Value |
|---|---|
| Agent | Claude 1 (lead), working alone |
| Timestamp | 2026-10-13 00:50 → 03:30 IST |
| Objective | User prompt v8 (`prompts/10_USER_functional_guide_overview_watchlist_2026-10-13.md`): run the app and learn every screen; fix the Overview (important things must not be lost, no duplication, a much bigger network, transactions + account creations + close monitoring); make every Detection chart self-explanatory; then deliver a beginner-level functional guide with screenshots. The technical guide comes next. |
| Exact Prompt | `prompts/10_USER_functional_guide_overview_watchlist_2026-10-13.md` (verbatim, two messages) |
| Status | DONE |

## Agent Output / Summary

1. **Overview v9 (operations center = live activity only, nothing duplicated from other pages).**
   - KPI strip: postings · 10 min, value moved · 10 min, accounts at risk, open interventions, new accounts · 30 days, last detection run (click → network switches to Risk only and frames the injected accounts).
   - Live transaction network full width and taller (`clamp(560px, 76vh, 900px)`), with a plain-language caption, an explanation of the current edge filter, and "Zoom to N at risk".
   - Needs attention: each account shows the detectors' one-line **reason**, the status **since** time and how many families **agree**.
   - **Close monitoring** (new): analyst-pinned accounts (Watch button on the account page and in the network drawer, optional note) plus live suggestions (early warning, model evidence above the threshold without corroboration, pattern match). Each shows 72 h activity (in, out, forwarded share, counterparties, new share) and **NEXT**: what would move it to "flagged".
   - **Money moving now** (replaces the old traffic line chart): payments per 30 s stacked by origin (everyday / customer / injected), value moved, average payment, payments touching risky accounts, channel mix, largest payments with recipient status, and a "how to read" caption.
   - **New accounts** (new): accounts opened in the last 30 days, inflow since opening and from how many senders, outflow, first money received, "large inflow while new" (policy `network.new_account_inflow`) and "device shared with N accounts".
   - Moved off the Overview because they live elsewhere: SHAP drivers and detector families (Detection §1), last attack result (Detection §2), payment decisions by tier (Governance, Health). A brief v8 attempt that put compact account scoring and a payment-tier card on the Overview was reverted after the user's second message.
2. **Detection v9**: four numbered sections (right now → did we catch the attacks → every account → model quality). Every chart has a Shows / How to read / Right now caption (`Explain` in `ui.tsx`), with live takeaways. New explained charts: model drivers (SHAP, moved from the Overview, with category meanings), runs by pattern, time-to-flag + recall per run, threshold history. Removed duplicates: transaction volume, channel doughnut, decisions by tier, threshold & recall per run.
3. **Backend (additive contracts)**:
   - `UniverseAccount` + `reason`, `families_flagging`, `families`, `status_since`; the detection stream tracks when each status was first seen (`stream.STATE.since`) and `status_map()` returns `families` and `since`; `livestatus.statuses()` passes reasons through (with fallbacks when Vigil's own state overrides).
   - `GET /api/watchlist`, `POST /api/watchlist`, `DELETE /api/watchlist/{id}` (`engine/watchlist.py`, `api/routes_watch.py`), table `watchlist` (cleared by a demo reset), WS `watchlist.updated`.
   - `LiveStats.traffic` (30 s buckets by origin, value, average, risky postings, channels, largest five).
   - `GET /api/live/new-accounts?days=30`; attacks publish `account.opened`.
4. **Fixes found while walking the app**: live status changes now carry their reason / families / since into the Overview (Pooja M showed a stale "no posting" reason); toast link to the attack history pointed at the Overview; Governance positioning still said the model layer was "in progress"; the account page's risk-evolution title said "as sender" for a recipient; run-chart labels skipped patterns; scroll offset under the sticky top bar.
5. **Tried and reverted**: a "closed loop + one non-rule family" route to flagged (to make the circular-ring originator robust after several un-reset attacks). It flagged an ordinary recipient who sat on an everyday 4-account cycle (test `test_attack_run_is_detected_live_without_false_positives[atk_fan_out]`), so it was removed; the guide documents the case honestly.
6. **Functional guide** (Claude Doc): https://claude.ai/code/artifact/bf16f71c-e278-4271-ac55-27e269ca9bac — 17 sections, 67 screenshots from a full live demo run (`docs/guide/img/`), every screen and chart explained for a beginner, worked score examples with real numbers, a 12-minute demo script, the live attack-check table and honest answers.

## Files Changed
- Backend: `vigil/{contracts.py,db.py,schema.sql,app.py,engine/livestatus.py,engine/watchlist.py (new),api/routes_live.py,api/routes_watch.py (new),intel/stream.py,sim/attacks.py}`, `tests/test_vigil_operations.py` (new, 7 tests).
- Frontend: `src/pages/{OverviewPage,DetectionPage,AccountPage,GovernancePage}.tsx`, `src/components/{Watchlist.tsx (new),OverviewAnalytics.tsx,DetectionCharts.tsx,LiveUniverse3D.tsx,UniverseDrawer.tsx,Shell.tsx,ui.tsx,live/LiveStatsCharts.tsx}`, `src/api/{client,types}.ts`, `src/styles/v5.css`.
- Docs: `docs/guide/img/*` (67 screenshots), README, DEMO_SCRIPT, CHANGELOG, AGENT_HANDOFF.

## Tests Run / Test Results
- `tsc --noEmit` clean; `vite build` green.
- Backend: new operations tests 7/7; attack, stream, operations and live suites 45/45 after the revert; full suite — see the ledger row.
- Live attack check (reset → inject → graded run, all 11 patterns): every pattern detected, 0 false positives; Money-mule network 3/4 and Velocity Chain 3/5 with the rest at early warning; Circular Ring 4/4 in a fresh world.
- Note: `test_latency_budget_under_ambient` fails when the machine is loaded (server + browser + build running) with or without these changes; it passed when re-run quietly.

## Decisions Made
- The Overview shows live activity and the action lists only; analysis stays on Detection, decisions by tier on Governance.
- Watchlist entries are operator state about the current world: a demo reset clears them.
- The guide is a Claude Doc (exportable to Word / PDF) rather than a repo Markdown copy; screenshots are kept in `docs/guide/img/`.

## Remaining Work
- Technical guide (how it is built, stack, storage, data flow) — the user's next step.
- Before presenting: Test inputs → Reset demo world.

## Git Commit / Diff Reference
Not committed yet (the user did not ask for a commit in this prompt).
