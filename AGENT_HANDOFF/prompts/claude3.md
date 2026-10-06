# Prompt for CLAUDE 3 — Product / UX (copy everything below)

You are Claude 3 on the Vigil project (PRIMA architecture). Repo: `C:\Users\KausikGH\Documents\Projects\Fraud Detection`.
Read first: `AGENT_HANDOFF/STATE.md`, `docs/TARGET_ARCHITECTURE.md`, `docs/DEMO_SCRIPT.md`, `frontend/src/api/types.ts`, `frontend/src/api/client.ts`.

The frontend base (Vite + React + TS + Cytoscape/dagre) is built by Claude 1 and works end to end. Your job: make the five-act demo **instantly legible to a judge in under 60 seconds** — hierarchy, copy, spacing, states, mobile — without changing data flow.

## FILES YOU MAY EDIT
`frontend/src/pages/**`, `frontend/src/components/**`, `frontend/src/styles/**`.

## FILES YOU MUST NOT EDIT
`frontend/src/api/**` (client, types, realtime hook — ask Claude 1 via `AGENT_HANDOFF/REQUESTS.md`), `frontend/src/App.tsx` routes, anything in `backend/`, `config/`. Never hard-code risk thresholds or tier boundaries — read `/api/policy`.

## INPUT CONTRACT
REST + WebSocket as in `docs/TARGET_ARCHITECTURE.md` §9 and `frontend/src/api/client.ts`. Money is integer paise → format with `formatINR` from `frontend/src/lib/format.ts`. Times ISO `Z` → `formatTime`.

## TASKS
1. Pay page (`/pay`): phone-frame; states CHECKING → APPROVED / intervention panel with **RISK LEVEL / WHAT CHANGED / WHY WE ARE INTERRUPTING / WHAT ACTION IS BEING TAKEN**; Razorpay label must read "TEST MODE — no real money moved"; mock label "DEMO PAYMENT".
2. Investigation (`/investigate/:decisionId`): left account+intent details, middle contribution bars (from `decision.dimensions`), right small network, below timeline, money trace (LIBR vs pro-rata side by side), action history; three tabs Customer / Bank / Audit.
3. Network (`/network`): keep Cytoscape layout static (no physics); improve legend, node roles, edge labels on hover only, "Confirm source scam" affordance.
4. Trusted contact (`/contact/:token`): big type, one alert card, three buttons, works at 360 px wide.
5. Loading / empty / error states everywhere (API errors have `{error:{code,message}}`).

## EXPECTED OUTPUT
Polished pages; no new runtime deps unless essential (justify in STATE.md).

## TEST COMMAND
`cd frontend; npm run build` (type-check + bundle) then `cd ..; .\run_demo.ps1` and click through Acts 1–5 from `docs/DEMO_SCRIPT.md`.

## DEFINITION OF DONE
Build passes; every button does something real (no success animations without a backend call); no polling (use the realtime hook); dashboard meaningful render < 2 s; graph interaction smooth with default suspicious subgraph; STATE.md entry added.
