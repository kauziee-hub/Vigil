# Prompt for CODEX — medium, isolated tasks (copy everything below)

Project: Vigil (PRIMA) at `C:\Users\KausikGH\Documents\Projects\Fraud Detection`. Read `AGENT_HANDOFF/STATE.md`, `docs/TARGET_ARCHITECTURE.md` first.
Python 3.11 venv at `backend/.venv`. Backend package `vigil` (import with `backend/` on `sys.path`).

## FILES YOU MAY EDIT
- `scripts/**` (except do not rewrite `scripts/benchmark_demo.py` wholesale — extend it)
- `backend/tests/test_contract_*.py`, `backend/tests/test_realtime_*.py`, `backend/tests/fixtures/**` (new files)

## FILES YOU MUST NOT EDIT
Anything under `backend/vigil/` (report bugs in `AGENT_HANDOFF/REQUESTS.md`), `frontend/`, `config/`.

## TASKS (independent)
1. **Contract sync test** `backend/tests/test_contract_types.py`: parse `frontend/src/api/types.ts` (regex over `interface X { field: … }`) and assert field names match the Pydantic models in `vigil/contracts.py` for `TransactionIntent, RiskSignal, DimensionScore, PolicyAdjustment, Intervention, RiskDecision, GraphNode, GraphEdge, GraphEvidence, ExternalIntel, ScenarioEvent`.
2. **Realtime test** `backend/tests/test_realtime_ws.py`: with `fastapi.testclient.TestClient`, open `/ws?topics=console,contact:arjun`, run scenario s3 via `POST /api/scenarios/s3/start` (or `vigil.sim.scenarios.run_sync('s3')` inside the app loop), assert a `breaker.fired` event arrives on `contact:arjun` within 5 s; reconnect and assert `hello` arrives again.
3. **Benchmark extension** `scripts/benchmark_demo.py`: add DB query timings for the 5 indexed queries and a `--json` output flag. Keep existing output format.
4. **Razorpay harness** `scripts/razorpay_check.py`: with keys from `.env`, create one test order (₹1) and print order id + mode; never print secrets; exit 0 with a clear "offline/unconfigured → mock fallback" message when unavailable.
5. **Reset determinism** `backend/tests/test_contract_reset.py`: two `POST /api/demo/reset` calls produce identical `(id, seq, sender_id, recipient_id, amount_paise)` ledger rows and identical `/api/graph/suspicious` node sets after running s2.

## INPUT CONTRACT
See `docs/TARGET_ARCHITECTURE.md` §5/§9. Test env: `tests/conftest.py` sets an isolated temp DB, mock payments, no ambient.

## TEST COMMAND
`cd backend; .venv\Scripts\python.exe -m pytest -q` and `backend\.venv\Scripts\python.exe scripts\benchmark_demo.py`

## DEFINITION OF DONE
All tests pass; scripts run offline; no secrets printed; STATE.md entry added.
