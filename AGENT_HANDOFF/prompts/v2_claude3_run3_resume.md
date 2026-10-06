You are CLAUDE 3 on the Vigil project (architecture: PRIMA). This is RUN 3 of your task.

Your complete, binding instructions are in this file — read it in full first and follow it exactly:
`AGENT_HANDOFF/prompts/v2_claude3_frontend_redesign.md`
(then the files it tells you to read: the user's brief, `docs/FINAL_PARALLEL_PLAN.md`, `docs/UI_CURRENT_STATE.md`, `frontend/src/api/types.ts` + `client.ts`). Also read your own `docs/DESIGN_SYSTEM.md` from the branch below — it is your design system; keep to it.

## What happened in run 2 (interrupted)
The lead's session restarted and killed you at ~23:31 IST. Your five milestone commits survived; the lead committed your one uncommitted file verbatim. Everything is on branch **`claude3/run2-wip`** (`ba5f83d`, `tsc -b --noEmit` clean), record: `AGENT_HANDOFF/runs/20261006-2303_claude3_frontend-redesign-run2.md`:
- DONE: run-1 merge + refactor; 9-item IA shell (grouped rail, status strip, shadow band), v1→v2 redirects, lazy network route, `docs/DESIGN_SYSTEM.md`; Transaction Guard (`/guard`, shared customer device + structured pre-commit assessment) and `/pay` kiosk; `components/intel.tsx` panels + role shapes + error boundary; Network Intelligence (`/network`: WebGL scene, modes, scoped attack scenes, time/attack replay, cached payloads, investigation drawer, TaintTrace + RingWatch).
- WRITTEN, NOT WIRED: `components/Replay.tsx` (DecisionReplayView playback, risk evolution, counterfactual ladder, provenance) — no page imports it yet.
- STILL v1 PAGES behind new routes: `/` (CommandCenter), `/investigations` (InvestigatePage), `/governance` (AboutPage), `/governance/decision/:id` (DecisionPage).
- PLACEHOLDERS (`<Pending>`): `/detection`, `/investigations/account/:id`, `/interventions`, `/lab`, `/health`.

## FIRST STEPS
1. In your worktree: `git merge --no-edit claude3/run2-wip`. Since that branch forked, `main` changed only backend files and `AGENT_HANDOFF/**` (none under `frontend/`) — no conflicts expected. Then `git rm --cached frontend/tsconfig.tsbuildinfo` and commit: it is a `tsc -b` build artefact that run 2 committed by accident; `main` now ignores `*.tsbuildinfo` in the root `.gitignore`.
2. `cd frontend && npm install`, then `npm run build` must be green before you start new work.
3. Dev server: `npm run dev -- --port 5183 --strictPort` (proxies `/api` and `/ws` to the lead's backend on http://127.0.0.1:8000, which runs `main` with every Claude-1 endpoint, scoped scenes, Tier-0 `[]` counterfactuals). Port 5183 avoids clashing with anything the lead runs.
4. `/api/intel/*` still returns 404: Claude 2 is finishing it in parallel (models are trained; API not merged). Keep honest "not yet available" states; never fabricate.

## Remaining work, in order (commit after EACH page, prefix `ui:`, keep `npm run build` green)
1. **Investigations**: wire `Replay.tsx` into `/investigations/decision/:id` (case header, Decision Replay playback, risk evolution with labelled WHY markers, counterfactual ladder — Tier 0 → "Already the lowest tier, nothing would need to change" —, provenance evidence table, detector consensus, SHAP "explains the MODEL" separate from ReasonLine "explains the OPERATIONAL DECISION", money trace, actions) and build `/investigations/account/:id` (risk timeline, AccountIntel panels, 1–2 hop scene focus link to `/network?focus=`). Replace the v1 InvestigatePage list with a dense case list.
2. **Interventions** (`/interventions`).
3. **Governance & Audit** (`/governance`, `/governance/decision/:id`): mode ACTIVE/SHADOW toggle + shadow comparison, policy version/weights/ladder, model versions, decision records → structured record with VIEW RAW RECORD + REPLAY DECISION, positioning (reuse AboutPage content).
4. **Scenario Lab** (`/lab`): 15 scenarios with `category` (payment | attack | control); START / PAUSE / RESET / REPLAY / COMPARE DETECTORS (honest 404 state until Claude 2 merges); live step log via the realtime bus; link to `/network?scenario=<id>` for the scoped attack scene.
5. **Overview** (`/`) rebuilt per the binding file (dense, no wall of KPI tiles).
6. **Detection & Models** (`/detection`) — renders from `/api/intel/models` + `/api/intel/overview`; until then an honest unavailable state; "Operational use: corroborating evidence only" visible.
7. **System Health** (`/health`).
8. Trusted-contact page visual alignment.
9. Screenshots to `docs/ui_v2/` if a browser tool is available to you; otherwise list what should be captured.

## Rules (unchanged)
Edit only your files (binding file "YOUR FILES"); request API changes in `AGENT_HANDOFF/REQUESTS.md`. Commit after every page so an interruption cannot lose work. Stop any dev server you started before you finish. End with the return format the binding file specifies (your final message is saved verbatim into the run record).
