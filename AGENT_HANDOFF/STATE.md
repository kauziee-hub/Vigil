# AGENT HANDOFF — current state (read this first)

Any agent (Claude / Cursor / Codex) resuming this project, read in order:
1. `AGENT_HANDOFF/prompts/00_MASTER_PROMPT.md` — the original brief (verbatim).
2. This file — what is done, how to run/verify, what is next.
3. `AGENT_HANDOFF/outputs/01_lead_report.md` — the lead's findings + decisions.
4. `docs/TARGET_ARCHITECTURE.md` (binding contracts/API) and `docs/PARALLEL_WORK_PLAN.md` (file ownership).
5. Your role prompt: `AGENT_HANDOFF/prompts/{claude2,claude3,cursor,codex}.md` (same as `docs/AGENT_PROMPTS/`).

Append to the **Log** at the bottom when you finish a unit of work (what changed, how verified). Requests for contract/API changes go in `AGENT_HANDOFF/REQUESTS.md`.

## Status: MVP complete and verified end to end (2026-10-06)

| Deliverable | Where | State |
|---|---|---|
| Unified repo | this folder | ✅ |
| Start command | `run_demo.ps1` / `run_demo.sh` (one port, :8000) | ✅ |
| Seed / reset | auto-seed on first run; `-Reset`/`--reset`; **Reset demo** button; `POST /api/demo/reset` | ✅ deterministic |
| Local DB | `data/vigil.db` (SQLite WAL), schema `backend/vigil/schema.sql` | ✅ |
| Normal payment / risky recipient / mule ring / coercion / FP control | scenarios s0–s4 | ✅ (smoke + tests) |
| Razorpay test path | `backend/vigil/payments/providers.py` | ⚠️ code works; **current keys rejected (HTTP 401)** → auto mock fallback. Put fresh `rzp_test_` keys in `.env`. |
| Fast 2D graph | Cytoscape + dagre, capped, static layout | ✅ |
| CircuitBreaker / trusted contact | `/contact/arjun`, WebSocket | ✅ verified live |
| Explainability / investigation | `/decision/:id`, `/investigate/:id` | ✅ |
| Benchmark | `scripts/benchmark_demo.py --write` → `docs/BENCHMARK_RESULTS.md` | ✅ p95 ≈ 1 ms |
| Tests | `backend/tests` (211) + `scripts/smoke_demo.py` | ✅ all pass |
| Docs | `docs/*.md`, README | ✅ |

## How to run / verify

```powershell
powershell -ExecutionPolicy Bypass -File run_demo.ps1 -Reset      # start fresh (builds UI, seeds, serves :8000)
cd backend; .venv\Scripts\python.exe -m pytest                     # 211 tests
backend\.venv\Scripts\python.exe scripts\smoke_demo.py             # 8 act checks
backend\.venv\Scripts\python.exe scripts\benchmark_demo.py         # latency
cd frontend; npm run build                                          # type-check + bundle
```

## Key facts an agent must not break

* Money = integer paise; time = ISO UTC `Z`; errors = `{"error":{code,message,details?}}`.
* All FastAPI routes are `async def` (single-thread DB access). Don't add sync `def` routes.
* Policy only in `config/risk_policy.yaml`; bump `version` on any change; frontend never hard-codes thresholds.
* `risk_decisions` is append-only (SQLite trigger).
* No ML model on the decision path; no account-freeze function; inbound money never held.
* Customer text must never contain words in `reasonline.BANNED_CUSTOMER_WORDS`.
* Expected tiers (tests enforce): s0→0, s1→2, s4→0, s3→4 (+breaker), s2+label then s1→3.

## Open items / next best steps

1. Fresh Razorpay **test** keys in `.env` (then restart; top bar shows "Razorpay TEST").
2. Rehearse `docs/DEMO_SCRIPT.md` twice with a phone on the LAN (allow Python through Windows firewall on private networks).
3. Parallel polish per `docs/PARALLEL_WORK_PLAN.md` (Claude 2 risk tests, Claude 3 UX, Cursor a11y, Codex contract/realtime tests).
4. Optional: code-split the frontend bundle (772 kB, mostly Cytoscape) with a lazy Network page.

## Log (newest last)

- 2026-10-06 Claude 1 — audited ccmule-main, "Actual ML - Laggy", PRIMA → `docs/CURRENT_STATE_AUDIT.md`, `docs/TARGET_ARCHITECTURE.md`.
- 2026-10-06 Claude 1 — skeleton; vendored `PRIMA/prima` → `backend/prima` + 190 tests. `.env` copied from PRIMA (git-ignored; never print).
- 2026-10-06 Claude 1 — backend complete (`backend/vigil/**`), 210 tests.
- 2026-10-06 Claude 1 — frontend complete (`frontend/src/**`), builds clean; run scripts; walkthrough of Acts 1–5 in browser.
- 2026-10-06 Claude 1 — fixes from walkthrough: Razorpay startup probe + auto-mock on 401; fan-in counts first-time senders only; labelled-neighbour rule follows money downstream (victims no longer scored); graph re-fit on resize; panel/button layout. 211 tests + smoke pass.
- 2026-10-06 Claude 1 — docs: MODEL_CARD, REAL_WORLD_POSITIONING (web-verified), KNOWN_LIMITATIONS, DEMO_SCRIPT, README, BENCHMARK_RESULTS, PARALLEL_WORK_PLAN, AGENT_PROMPTS.
