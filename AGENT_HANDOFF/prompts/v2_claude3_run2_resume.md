You are CLAUDE 3 on the Vigil project (architecture: PRIMA). This is RUN 2 of your task.

Your complete, binding instructions are in this file — read it in full first and follow it exactly:
`AGENT_HANDOFF/prompts/v2_claude3_frontend_redesign.md`
(then the files it tells you to read: the user's brief, `docs/FINAL_PARALLEL_PLAN.md`, `docs/UI_CURRENT_STATE.md` + `docs/ui_current/*.png`, `frontend/src/api/types.ts` + `client.ts`, and the user's old frontends).

## What changed since that file was written
1. RUN 1 WAS INTERRUPTED mid-refactor (the lead's session restarted ~12 minutes after launch). The lead recovered your uncommitted work verbatim onto branch `claude3/run1-wip` (commit b18a203, 13 files, +1944/−496):
   - new: `components/Graph3D.tsx` (raw three.js, InstancedMesh nodes/edges, 597 lines), `components/ui.tsx` (shared primitives), `lib/status.ts` (status scale), `lib/graphStyle.ts`;
   - rewritten: `styles/tokens.css`, `styles/app.css`, `components/{Shell,Decision,EvidenceGraph}.tsx`, `lib/{format,hooks}.ts`; `package.json` adds `three` + `@types/three`;
   - it does NOT type-check: pages still import exports removed from `Decision.tsx` (TierChip, SimChip, BankView, ContributionPanel, SignalCard — 11 errors);
   - `docs/DESIGN_SYSTEM.md` and all new pages were not started.
2. FIRST STEPS: in your worktree run `git merge --no-edit claude3/run1-wip` (no conflicts expected — `main` only changed `frontend/src/api/types.ts` since then, which that branch does not touch), then `cd frontend && npm install`. Review the run-1 work critically against the brief: keep what is good, replace what is not, finish the refactor. You are not bound by run-1 decisions, but justify changes in DESIGN_SYSTEM.md.
3. The backend is LIVE at http://127.0.0.1:8000 (run by the lead from the main repo, `main` commit 70a0520) with every Claude-1 endpoint: `/api/graph/scene`, `/api/decisions/{id}/replay|counterfactuals|record`, `/api/accounts/{id}/risk-timeline`, `GET/POST /api/mode`, `/api/governance/summary`, `/api/interventions`, `/api/system/health`, `/api/scenarios/{id}/replay`. `GET /api/scenarios` returns 15 scenarios with optional `category` (payment | attack | control). Decisions carry `mode`, `recommended_tier`, `applied_tier`, `baseline`, `model_evidence`; signals carry `provenance`. `/api/intel/*` returns 404 until Claude 2 merges — render honest "not yet available" states; never fabricate.

## New mandatory rule: commit incrementally
Commit on your worktree branch after EACH milestone (message prefix `ui:`), so an interruption can never lose your work again — e.g. (a) merge + refactor fixed + `npm run build` green; (b) shell/IA/redirects + DESIGN_SYSTEM.md; then every one or two pages. Keep `npm run build` green at each commit wherever feasible.

## Order (P0 first)
Shell + 9-item IA + redirects → Transaction Guard → Network Intelligence (3D, lazy-loaded) → Investigations (Decision Replay, risk evolution, counterfactuals, provenance, consensus/SHAP/drift/patterns/role panels with honest empty states) → Interventions → Governance & Audit → Scenario Lab → Overview → Detection & Models → System Health → trusted-contact alignment → screenshots.

Stop any dev server you started before you finish. End with the return format the binding file specifies (your final message is saved verbatim into the run record).
