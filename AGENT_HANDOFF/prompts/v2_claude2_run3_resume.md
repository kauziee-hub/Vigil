You are CLAUDE 2 on the Vigil project (architecture: PRIMA). This is RUN 3 of your task.

Your complete, binding instructions are in this file — read it in full first and follow it exactly:
`AGENT_HANDOFF/prompts/v2_claude2_ml_intelligence.md`
(then the files it tells you to read: the user's brief, `docs/FINAL_PARALLEL_PLAN.md` §4.2, `backend/vigil/contracts.py`, `docs/MODEL_CARD.md`, `frontend/src/api/types.ts`).

## What happened in run 2 (interrupted)
The lead's session restarted and killed you at ~23:43 IST. Your milestone commits survived; the lead committed the uncommitted remainder verbatim. Everything is on branch **`claude2/run2-wip`** (`871df51`), record: `AGENT_HANDOFF/runs/20261006-2303_claude2_ml-intelligence-run2.md`:
- `docs/ML_VALIDATION_REPORT.md` §1 Audit (A1–A16) — done.
- `vigil/intel/features.py` (shared train/live extractor), `ml/datagen.py` (150 deterministic worlds, 10 families) — done.
- `vigil/intel/{rules,early_warning,drift,pattern_memory,roles,models}.py`, `ml/{gnn_torch,metrics,train_all}.py`, and trained artefacts in `backend/models/` (`validation_v2.json` etc., trained_at 2026-10-06T18:13:17Z) — written but you never verified or committed them yourself, so review them before building on them.
- NOT written: `vigil/intel/consensus.py`, `vigil/intel/api.py`, `backend/tests/test_intel_*.py`, `backend/requirements-ml.txt`, ML_VALIDATION_REPORT metrics sections, MODEL_CARD appendix.

## FIRST STEPS
1. In your worktree: `git merge --no-edit claude2/run2-wip`. That branch already contains the latest backend on `main` (its merge-base is main `7222af6`); main has since changed only `AGENT_HANDOFF/**` — no conflicts expected.
2. Run the full suite: `cd backend; <venv python> -m pytest -q` (main has 221 tests; all must still pass).
3. ML deps are ALREADY installed in the main venv: scikit-learn 1.9.1, shap 0.51.0, torch 2.14.1+cpu. Write `backend/requirements-ml.txt` with these pins.

## Remaining work, in order (commit after EACH, prefix `intel:`)
(a) `vigil/intel/consensus.py` — `corroboration(account_id) -> list[DetectorResult]`: < 20 ms warm, NEVER raises (unknown/empty/external accounts → `[]` or honest "insufficient data" results), honest `kind` values. It is called synchronously inside the payment decision (`engine/decide.py::_model_evidence`, wrapped in try/except, first 8 results kept), so it must NOT import shap and must not do the heavy cold load on the payment path if avoidable. Also expose `vigil.intel.warm() -> None` (loads artefacts, builds the live feature cache; safe to call twice; never raises). The lead will call it once from app startup after merge — do not edit `app.py`.
(b) `vigil/intel/api.py` — `router = APIRouter(prefix="/api/intel")` with exactly the five routes in FINAL_PARALLEL_PLAN §4.2. JSON must match `frontend/src/api/types.ts` field for field (`AccountIntel`, `IntelScores`, `IntelOverview`, `ModelInfo`, `ScenarioCompare`, `DetectorResult`, `DetectorConsensus`); Claude 3 is building the UI against them right now. All routes `async def`. `/scores` cached per `GRAPH.version`. `ScenarioCompare`: `touched_accounts(sid)` are "involved accounts", not all mules (see the mid-run message in your run-2 record).
(c) Tests `backend/tests/test_intel_*.py` per the binding file (shapes validate against contracts, determinism, never-raise, consensus semantics, latency budget, live s2 → kiran.traders / zenith.exports flagged by ≥ 3 families while ordinary seeded accounts mostly are not). Full suite green.
(d) Training budget: the recovered run took 804 s (LOAO 690 s), over the 10-minute CPU budget. Make the default `train_all.py` finish < 10 min (e.g. fewer GNN epochs/early stop inside LOAO, or LOAO behind a flag with its results kept from the last full run) and SAY in the report which numbers came from which run. Re-run it once so committed artefacts match the committed code; record the exact command and wall time.
(e) `docs/ML_VALIDATION_REPORT.md` metrics sections (Rules / RF / GNN / drift / pattern memory / early warning / consensus; per-attack; leave-one-attack-out; calibration; roles; old protocol vs honest protocol) — all labelled SYNTHETIC VALIDATION, honest where models fail (e.g. GNN on unseen shared_device / smurfing / dormant) — plus the appended section in `docs/MODEL_CARD.md`.

## Rules (unchanged)
Edit only your files (binding file "YOUR FILES"). The live backend on :8000 is run by the lead from `main`; your router goes live only after the lead merges — test with the pytest client (isolated temp DB), do not start another server on :8000. Commit after every milestone so an interruption cannot lose work. Do not leave any server or long-running process running when you finish. End with the return format the binding file specifies (your final message is saved verbatim into the run record).
