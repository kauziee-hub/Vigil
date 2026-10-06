# Prompt for CODEX — isolated engineering tasks (v2). Copy everything below into Codex.

You are CODEX on the Vigil project (architecture: PRIMA). Repo: `C:\Users\KausikGH\Documents\Projects\Fraud Detection` (git). Create a branch per task: `codex/<task-name>`. Do NOT redesign shared architecture.

Read first: `AGENT_HANDOFF/STATE.md`, `docs/FINAL_PARALLEL_PLAN.md` (§3 ownership, §4 interfaces), `backend/vigil/contracts.py`.
Python: `backend\.venv\Scripts\python.exe` (run from `backend/`; `tests/conftest.py` sets an isolated temp DB, mock payments, no ambient).

## FILES YOU MAY EDIT
New files only: `scripts/**`, `backend/tests/test_codex_*.py`, `backend/tests/fixtures/**`.
## MUST NOT EDIT
`backend/vigil/**`, `frontend/**`, `config/**`, docs other than appending your own run notes. Found a bug in `backend/vigil`? Write it to `AGENT_HANDOFF/REQUESTS.md` with a failing test.

## TASKS (independent; each its own branch + commit)
1. **Graph scene benchmark** `scripts/bench_graph_scene.py`: time `GET /api/graph/scene` (cap 60/150/300, cold vs cached) via `fastapi.testclient`, payload bytes, node/edge counts, after running scenario s2 and 3 attack scenarios. Output a table + `--json`.
2. **Scenario reset tests** `backend/tests/test_codex_reset.py`: for every scenario in `GET /api/scenarios`: reset → run (`vigil.sim.scenarios.run_sync(id)`) → snapshot `(id, seq, sender_id, recipient_id, amount_paise)` of non-seed ledger rows + decision tiers → reset → run → identical.
3. **Concurrency tests** `backend/tests/test_codex_concurrency.py`: fire 50 concurrent `POST /api/intents` (httpx AsyncClient against the ASGI app) across 5 senders; assert no 500s, ledger system total == 0, no customer negative balance, every intent has a decision and a consistent transition chain.
4. **Risk-decision integration tests** `backend/tests/test_codex_decisions.py`: for each scenario, assert decision record completeness (provenance on every signal once Claude 1 lands it, policy_version, latency, payload_sha256 matches recomputation of the audit payload), and that `GET /api/decisions/{id}/replay` final frame tier == decision tier, and counterfactual tiers ≤ actual tier.
5. **Realtime reliability** `backend/tests/test_codex_realtime.py`: WS `/ws?topics=console,contact:arjun,pay:sunita@vigil`; run s3; assert `breaker.fired` on contact topic and `intent.updated` on pay topic within 5 s; disconnect/reconnect receives `hello`; 20 clients connected simultaneously all receive the event.
6. **Razorpay test harness** `scripts/razorpay_check.py`: with keys from `.env`, create a ₹1 TEST order, print order id + mode; NEVER print secrets; on 401/offline exit 0 with "mock fallback active" message. Also unit-test signature verification with a known HMAC vector.
7. **ML inference timing** `scripts/bench_intel.py` (after Claude 2 merges `vigil/intel`): time `GET /api/intel/accounts/{id}` cold/warm, `/api/intel/scores`, `corroboration()`; report p50/p95.
8. **Decision Replay fixtures** `backend/tests/fixtures/replay/*.json`: golden replay outputs for s1, s3 and s1-after-label produced by the API; a test that compares structure (frame kinds/labels/tiers) to the golden files.

## Definition of done (per task)
Tests pass: `cd backend; .venv\Scripts\python.exe -m pytest -q`. Scripts run offline. No secrets printed.

## Return format (paste your final answer back to the operator; it is saved verbatim into AGENT_HANDOFF/runs/)
Task · Branch · Commit · Files changed · Commands + results · Problems found (with file:line) · Remaining work.
