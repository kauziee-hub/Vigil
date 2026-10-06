# Parallel Work Plan

Lead / integrator: **Claude 1**. Contracts are frozen in `backend/vigil/contracts.py` and `docs/TARGET_ARCHITECTURE.md` §5. Nobody invents a new score schema, a second DB layer, or frontend thresholds.

Status at hand-off: backend complete and tested (210 tests). Claude 1 is building the frontend base (all pages wired end-to-end). Other agents work on **disjoint files** below.

## File ownership (non-overlapping)

| Area | Owner | May edit | Must NOT edit |
|---|---|---|---|
| Contracts, schema, DB layer, lifecycle, payments, API routes, app, seed, scenarios, run scripts | **Claude 1** | `backend/vigil/{contracts,db,settings,clock,app,realtime}.py`, `backend/vigil/schema.sql`, `backend/vigil/{engine,payments,api,sim,graph}/**`, `run_demo.*`, `frontend/src/api/**`, `frontend/src/App.tsx`, `frontend/src/main.tsx` | — |
| Risk engine | **Claude 2** | `backend/vigil/risk/**`, `backend/tests/test_risk_*.py`, values (not keys) in `config/risk_policy.yaml` | contracts, engine, api, frontend, seed |
| Product / UX | **Claude 3** | `frontend/src/pages/**`, `frontend/src/components/**`, `frontend/src/styles/**` | `frontend/src/api/**` (ask Claude 1), anything in `backend/` |
| Small safe tasks | **Cursor** | `README.md`, `docs/DEMO_SCRIPT.md` wording, `frontend/src/components/ui/**` (new small presentational components), CSS in `frontend/src/styles/polish.css` | risk formulas, schema, contracts, API, lifecycle |
| Medium isolated tasks | **Codex** | `scripts/**`, `backend/tests/test_contract_*.py`, `backend/tests/test_realtime_*.py`, `backend/tests/fixtures/**` | anything under `backend/vigil/` (report bugs to Claude 1), frontend |

## Interfaces everyone codes against

* HTTP: `docs/TARGET_ARCHITECTURE.md` §9 (live list: `GET /openapi.json` while the app runs).
* Types: `backend/vigil/contracts.py` ⇄ mirror `frontend/src/api/types.ts`.
* Realtime: `WS /ws?topics=console,pay:<account>,contact:<token>`; envelope `{type, topic, ts, data}`. Event types: `intent.updated`, `decision.created`, `ledger.posted`, `monitor.finding`, `breaker.fired`, `breaker.responded`, `scenario.started|step|paused|resumed|error`, `ringwatch.scan`, `taint.updated`, `journey.event`, `demo.reset`, `ambient.changed`, `metrics.dirty`.
* Money: integer paise. Time: ISO-8601 UTC `Z`. Errors: `{"error":{"code","message","details?"}}`.

## Merge protocol

1. Work only in your files. If you need a contract/API change, write it in `AGENT_HANDOFF/REQUESTS.md` (append) and continue with a stub.
2. Before handing back: `cd backend; .venv\Scripts\python.exe -m pytest` must pass; `cd frontend; npm run build` must pass.
3. Append a 3–5 line entry to `AGENT_HANDOFF/STATE.md` (what changed, how verified).
4. Claude 1 runs the five-scenario smoke (`scripts/smoke_demo.py`) after every merge.

## Critical path (today)

1. ✅ Audit + architecture + contracts
2. ✅ Backend lifecycle, risk engine, ledger, TaintTrace, scenarios, tests
3. ⏳ Frontend base: Command Center, Pay, Investigation, Network, Contact (Claude 1)
4. ⏳ One-command start + reset; benchmark; docs (Claude 1 / Codex)
5. Polish & hardening in parallel (Claude 2, Claude 3, Cursor)
6. Full rehearsal: Acts 1–5 twice from reset, second phone on LAN
