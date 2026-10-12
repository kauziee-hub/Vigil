# Prompt for CLAUDE 2 — Risk Engine (copy everything below)

You are Claude 2 on the Vigil project (PRIMA architecture). Repo: `C:\Users\KausikGH\Documents\Projects\Fraud Detection`.
Read first: `AGENT_HANDOFF/STATE.md`, `docs/TARGET_ARCHITECTURE.md` (§5 contracts, §7 dimensions, §8 fusion), `config/risk_policy.yaml`, `backend/vigil/contracts.py`.

The risk engine already works end to end (S0→T0, S1→T2, S3→T4, S4→T0, S2+label → S1→T3). Your job is to make it **more credible and better tested**, not bigger.

## FILES YOU MAY EDIT
- `backend/vigil/risk/**`
- `backend/tests/test_risk_*.py` (new)
- Values (not key names/structure) in `config/risk_policy.yaml` — bump `version` when you change any value.

## FILES YOU MUST NOT EDIT
`backend/vigil/contracts.py`, `backend/vigil/engine/**`, `backend/vigil/api/**`, `backend/vigil/sim/**`, `backend/vigil/db.py`, `backend/vigil/schema.sql`, anything in `frontend/`. Need a contract change? Append to `AGENT_HANDOFF/REQUESTS.md`.

## INPUT CONTRACT
Each dimension module returns `(list[RiskSignal], facts_dict)`; every `RiskSignal` has `rule_id`, `dimension`, `label`, `reason` (one sentence built only from evidence values), `evidence` (raw numbers), `contribution` (from policy). `fusion.fuse(signals_by_dim, facts)` returns `FusionResult`. `reasonline.build(...)` renders customer/analyst/audit text deterministically. No ML, no LLM.

## TASKS (in order)
1. Unit tests per rule (`tests/test_risk_rules.py`): construct tiny worlds via `vigil.engine.ledger.post` + `vigil.graph.pathgraph.GRAPH` (use the `world` fixture then add targeted transactions) and assert each `NET_*`, `SEQ_*`, `BEH_*`, `CTX_*` rule fires/doesn't fire at its threshold boundary.
2. Fusion tests: weights sum to 1; contributions sum to `base_score`; each named adjustment (`ADJ_CORROBORATION`, `FLOOR_*`, `CAP_FRICTION_GUARD`, `CAP_NO_SENDER_EVIDENCE`) triggered by a minimal case; counterfactual text correct.
3. RingWatch false-positive review: run `ringwatch.scan(0.3)` on a fresh seed; any ordinary (seed_role='legit') account scoring ≥ 0.4 is a false positive — tighten that rule (prefer windows/first-time-sender logic over raising thresholds) and record before/after counts in `docs/MODEL_CARD.md` §Rules (append a short section; do not rewrite the rest).
4. ContextFlag: add negation-safe phrasing tests ("this is not urgent" should still be fine to match — document the choice) and a test that benign notes ("rent for family", "groceries") match nothing.
5. ReasonLine: test that customer text never contains `BANNED_CUSTOMER_WORDS` for every rule combination you can generate (hypothesis is available).

## EXPECTED OUTPUT
New tests, small rule refinements, a short appended section in `docs/MODEL_CARD.md`, an entry in `AGENT_HANDOFF/STATE.md`.

## TEST COMMAND
`cd backend; .venv\Scripts\python.exe -m pytest -q`

## DEFINITION OF DONE
All tests pass (existing 210 + yours). The five scenario outcomes above are unchanged (`tests/test_vigil_lifecycle.py` passes). No new dependencies. Every rule still returns rule_id + reason + evidence + contribution.
