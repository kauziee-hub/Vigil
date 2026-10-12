# Run record — claude1 — v10: Overview money map, live tape, mule pipeline, Copilot (plan 10, P0–P10)

| Field | Value |
|---|---|
| Agent | Claude 1 (lead), working alone |
| Timestamp | 2026-10-13 03:30 → 06:30 IST (approx.) |
| Objective | User prompt v9 (`prompts/11_USER_implement_v10_plan_update_guide_2026-10-13.md`): implement `prompts/10_OVERVIEW_V10_MASTER_PLAN.md` fully, adequately tested, fintech-expert quality; then update the functional guide with every new feature and check nothing in the project is missing from it |
| Exact Prompt | `prompts/11_USER_implement_v10_plan_update_guide_2026-10-13.md` (verbatim) + the plan |
| Branch | `overview-v10` (base `278541c` = the v8 session's uncommitted work, committed first) |
| Status | DONE (see Deviations) |

## What shipped, by phase
- **P0** `cb4b7f5`: baseline — pytest 337 pass, smoke 8/8, 11/11 attacks 0 FP, world-digest test (30,983 postings / 553 accounts, fixed anchor), pre-v10 screenshot. `AGENT_HANDOFF/baseline_v10.md`.
- **P1** `68e1cc9`: simulated locations on every posting at `ledger.post` time (pure, never raises): basis + accuracy (ATM terminal ±25 m, device GPS ±30 m, merchant POS ±2 km, IP ±3–15 km, KYC home); hash-derived homes in 22 cities (persona cities kept: Ramesh Bengaluru, Sunita Pune); 172 generated ATM terminals; guarded additive migration + backfill for existing DBs; rails (rail selector on the phone; one hash-derived habitual rail per background customer; ATM / international sinks displayed without rewriting stored channels); 40-account legitimate onboarding cohort with its own RNG after the main seed; `ext:intl-wire`; scenario story cities (Mumbai cash-outs, Delhi → Kolkata impossible travel). Regression handled honestly: `AGENT_HANDOFF/regression_v10.md`.
- **P2** `815c0d4`: `vigil/overview` read models + `api/routes_overview.py`: money map, reference, tape (since_id paging, filters), connections (≤ 3 hops, ≤ 12 per level), KPIs (6 tiles, deltas, sparklines, incident scope), rings, pipeline, exits, channels, brief, attention, signals. Worst cold call 21 ms.
- **P3+P4+P5** `02eb358`: money map (d3-geo; SVG land + canvas arcs / particles / pulses; zoom / pan / keyboard; edge-clamped foreign arcs; city-level ATMs; accuracy circle for the selected posting; reduced-motion and hidden-tab pause), lazy three.js globe (texture drawn once from the same GeoJSON; dispose on unmount; IntersectionObserver pause), virtualised live tape, connections drawer, shared selection context. Map data: Natural Earth India point of view, simplified to 325 KB by `scripts/build_geo_assets.py`.
- **P7** `bb38066`: Copilot backend — deterministic incident engine (9 kinds, rubric from `config/copilot_policy.yaml`, dedupe by overlap, cooldown, auto-resolve), structured briefs (Gemini JSON schema validated, whitelist enforced, severity forced to the system's; deterministic template fallback), 17 read-only tools (seed_* stripped, untrusted text wrapped, size caps), SSE chat (Gemini stream + tool loop with budget; offline router), rate limit, secret redaction, `.env.example` placeholders.
- **P6+P8+P9** `8b832c6`: Overview v10 assembly (layout per plan §2), KPI strip v10, needs attention with ₹ in / out, situation brief, mule pipeline, money by channel, compact 3D, Copilot strip + dock (Briefing / Chat), safe markdown renderer, whitelisted UI actions (watch = confirmed proposal), incident mode, collection points.
- **P10**: final walkthrough polish — the cross-channel hub now sends from Delhi before moving to Kolkata so **impossible travel** is actually raised (geo only; still 1/1, 0 FP); ring location from the flagged members' own postings ("around Mumbai"); offline Copilot answers *trace the money* / *who else is linked* inside an incident; connections grouped per account per hop ("× n"); ATMs and clusters drawn above city dots, street-level fly-to for precise locations, zoom capped at the land data's detail; phone-width KPI text. Docs (README, DEMO_SCRIPT, KNOWN_LIMITATIONS, CHANGELOG, DESIGN_SYSTEM, THIRD_PARTY_DATA), screenshots (`docs/screenshots/v10_*`, `docs/guide/img/v10_*`), functional guide v10 (`docs/guide/VIGIL_FUNCTIONAL_GUIDE.md` + a copy beside the user's original in Downloads), records.

## Gates (final)
- pytest: **374 passed, 0 failed** (337 baseline + digest 1 + geo / rails / cohort 12 + overview 6 + Copilot 18); the last polish (P10) re-ran overview + Copilot (24) and the cross-channel / circular / digest tests (5) afterwards.
- tsc + vite build green; main `index` 458.6 kB (was 460.0 kB), `OverviewPage` chunk 413.9 kB incl. the 325 KB map file (was 17.4 kB), globe chunk 8.3 kB (lazy).
- Smoke 8/8. World digest identical to P0. Risk-policy version unchanged (`2026.10.07-v3.1+9ba3476c1d`, test).
- 11/11 attack patterns, 0 FP, identical to P0 (with the incident engine running).
- Frontend checks 18/18 (`node scripts/frontend_checks.mjs`: XSS fixtures, action whitelist, incident ordering, selection).
- Grep gate: no API key in the tree, no `dangerouslySetInnerHTML`, no `seed_*` read in `vigil/copilot` (test).
- E2E (Playwright, live server): attack → CRITICAL ring chip → briefing without typing → chat → tape row → drawer → globe; 0 console / API errors.

## Deviations (recorded, defaults from plan §14 where applicable)
- Reference data in `backend/vigil/geo/cities.json` (the plan's `data/geo/` is git-ignored); ATMs generated in code.
- `d3-zoom` / `topojson-client` not added (manual zoom; pre-simplified GeoJSON) — fewer downloads, same behaviour.
- Phases P3–P5 and P6/P8/P9 committed together (they share the page and the selection context); P7 before P6 so every commit runs.
- No frontend test runner was installed (no extra download): frontend checks run on Vite's bundled esbuild + react-dom/server.
- Optional P9 extras **Recovery clock** and **Customers protected** were not built (plan: only if time permits); case packet out of scope.
- The Gemini path is tested with a stub client (no key on this machine); live Gemini calls were not exercised.
- The two Claude artifact links to the v8 guide could not be opened from this session ("made by someone else"; the permission prompt cannot be shown here), so the guide was rebuilt from the user's Markdown export.

## Remaining work
- Optional: add `GEMINI_API_KEY` to `.env` to try AI briefings; build the recovery clock / customers-protected extras; merge `overview-v10` into `main` and push (not done without the user's go-ahead).
