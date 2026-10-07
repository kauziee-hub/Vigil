You are CLAUDE 3 on the Vigil project (architecture: PRIMA). This is v3 RUN 2 of your live-platform UI task.

Your complete, binding instructions are in this file — read it in full first and follow it exactly:
`AGENT_HANDOFF/prompts/v3_claude3_live_ui.md`
(then what it tells you to read: `docs/V3_LIVE_PLATFORM_PLAN.md`, the user's direction, the reference frontend source + `docs/reference_refined/*.png`, the current Vigil frontend, `frontend/src/api/types.ts` §v3 + `client.ts`).

## What happened
v3 RUN 1 WAS INTERRUPTED (the lead's session restarted at ~09:30 IST — the third restart). Your milestone commits survived on branch `claude3/v3-run1-wip` (head `4f842af`):
- `523dc7a` M1 design system v3 · `0a6cb20` M2 LiveUniverse3D (`lib/universe3d.ts`) · `ff6f1a0` M3 Live Operations overview · `63d4775` M4 Network Intelligence (lenses, find/zoom, drawer) · `a7414fc` universe layout (merchants on an inner shell, history constellation)
- `4f842af` WIP commit made by the lead on recovery: `components/live/AccountLivePanel.tsx` (new) mounted on `AccountPage` — M5 had just started. It type-checks.
- The lead stopped the orphaned Vite server you had left on :5181.

## First steps
1. In your new worktree (created from current `main`): `git merge --no-edit claude3/v3-run1-wip` (no conflicts expected — `main` changed no frontend file since your last merge), then `cd frontend && npm install`.
2. The backend on http://127.0.0.1:8000 is live on `main` (world v3, `/api/live/universe`, `/api/live/stats`, `/api/attacks/runs`, WS `attack.run_updated`, `ledger.posted`). Claude 2's `intel.tx_scored` / `intel.account_status` are NOT merged yet (Claude 2 is relaunched in parallel) — until then statuses come from RingWatch + Vigil state; keep honest states, never fabricate.
3. The reference app is no longer running at :3010 — use its source and `docs/reference_refined/*.png`.

## Remaining work (in order; commit after each, prefix `ui3:`)
M5 — restyle every remaining area in the v3 system WITHOUT dropping features: finish the account page you started (reference investigation style + Vigil's risk timeline / intel / neighbourhood), then Investigations case page (Decision Replay, counterfactuals, provenance), Transaction Guard, Detection & Models (model cards, SYNTHETIC VALIDATION), Interventions, Governance & Audit, Scenario Lab (may share the Command Center), System Health, trusted-contact page.
Then a quick self-review of Overview + Network against the reference screenshots at 1600×1000 (readability, density, no neon noise) and fix what is weak.
M6 — screenshots to `docs/ui_v3/` (Playwright MCP if available) as the binding file lists. `npm run build` must pass at each commit.

Stop any dev server you started before you finish. End with the return format of the binding file (your final message is saved verbatim into the run record).
