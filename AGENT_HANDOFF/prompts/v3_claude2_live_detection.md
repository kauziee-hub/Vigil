You are CLAUDE 2 on the Vigil project (architecture: PRIMA). You own `backend/vigil/intel/**` (detection intelligence), which you built in earlier runs (see `AGENT_HANDOFF/runs/*claude2*` and `docs/ML_VALIDATION_REPORT.md`). This is v3: LIVE detection streaming, so the UI can show a living transaction universe the way the user's refined money-mule project does.

## Read first
1. `docs/V3_LIVE_PLATFORM_PLAN.md` — BINDING (interfaces, status semantics, ownership).
2. `AGENT_HANDOFF/prompts/04_USER_refined_mule_repo_2026-10-07.md` (user's direction) and the reference backend: `C:\Users\KausikGH\Documents\Projects\Indian Bank Project\money-mule-detection-refined\backend\` — `pipeline.py` (live per-transaction scoring, early warning, flags, attack-run evaluation, adaptive threshold — note its INTEGRATION_PROGRESS.md audit: the original adaptive threshold had its sign inverted), `early_warning.py`, `runtime.py`.
3. `backend/vigil/contracts.py` §v3 (`TxScored`, `AccountStatusChange`, `AttackRun`, `AccountStatus`) and `backend/vigil/engine/hooks.py` (post-posting hook: `hooks.register(fn)`; `fn(tx_row)` runs after every LIVE ledger posting, synchronously on the event-loop thread; suspended during seeding).
4. Your own `vigil/intel/live.py` (Snapshot, incremental `refresh()`), `service.py`, `consensus.py`.

## Environment
- Isolated git worktree. Python: `C:\Users\KausikGH\Documents\Projects\Fraud Detection\backend\.venv\Scripts\python.exe`, run from your worktree's `backend/`. **Commit after every milestone** ("intel3: …") — session restarts have killed agents twice.
- Windows; Bash heredocs containing backticks break the Bash tool — use Write/Edit for files.

## YOUR FILES
`backend/vigil/intel/**`, `backend/ml/**`, `backend/models/**`, `backend/tests/test_intel_*.py`, `docs/ML_VALIDATION_REPORT.md`, appended section of `docs/MODEL_CARD.md`.
## MUST NOT EDIT
`contracts.py`, `engine/**` (use `hooks.register` only), `api/**` (your router `intel/api.py` is yours), `sim/**`, `risk/**`, `app.py`, `config/**`, `frontend/**`. Need a change? `AGENT_HANDOFF/REQUESTS.md`.

## TASKS (milestones; commit each)
M1. `vigil/intel/stream.py` — register a hooks listener at import (make sure `vigil/intel/api.py` imports it so the app activates it). Per live posting: incremental intel refresh for the touched accounts (reuse `live.refresh` machinery), compute each touched account's live status, publish via `vigil.realtime.HUB.publish("console", ...)`:
   - `intel.tx_scored` → `TxScored` (sender/recipient status + strongest model-evidence value as risk, `scored_ms`);
   - `intel.account_status` → `AccountStatusChange` for every account whose status changed (including population effects of early warning) with a one-line `reason`.
   Budget: p95 < 30 ms per posting with ~350 accounts at 0.5 postings/s; never raise. Status semantics + precedence exactly as in the plan (`held` / `confirmed_fraud` read from Vigil tables `scoped_holds` (released_at IS NULL, as sender) and `fraud_labels` recipients — read-only; `new` = opened < 7 days; `idle` = no posting in the live window).
M2. Public functions: `status_map()`, `roles_flagged()`, `current_threshold()`, `threshold_history()`, `on_run_evaluated(run)` — signatures in the plan. `status_map()` must be fast (cached per graph state) because Claude 1's `/api/live/universe` and attack-run evaluation call it.
M3. **Adaptive model-evidence threshold** (the original project's feature, done correctly): the threshold that turns model evidence into the "flagged" status adapts after each evaluated attack run (from `on_run_evaluated`: recall vs false positives), bounded (e.g. 0.45–0.85), small steps, every change logged with reason in `threshold_history()`, deterministic, reset with the demo. It NEVER affects payment tiers. If you conclude it is not credible, implement it as a governed recommendation (logged, not applied) and say why.
M4. **Revalidate on world v3.** Claude 1 is replacing the seed with a denser, realistic everyday-UPI world (≈300+ accounts, daily small payments) and a routine-preserving ambient stream of ≈0.5 tx/s. When it lands on `main` (Claude 1 will message you; merge `main` into your branch), measure on the live world: ordinary (`seed_role='legit'`) accounts flagged / early-warned after 0, 600, 1800 ambient postings (must stay ~0), and per-attack live detection for all 10 attack scenarios + s2 (detected accounts, first-warning / detection latency). If the denser world shifts feature distributions enough to break your models, fix it with honest means (retrain on worlds generated to match, recalibrate) and document. Update `docs/ML_VALIDATION_REPORT.md` §10 and add tests.
M5. Tests `test_intel_stream*.py`: listener registered, events published with contract shapes, latency budget, status precedence, threshold bounds/logging/determinism across reset, no ordinary account flagged under ambient.

## Honesty rules (unchanged)
Model outputs are corroborating evidence only; never fused into tiers; metrics labelled SYNTHETIC VALIDATION; nothing in scoring reads `seed_role`, `seed_attack` or labels (evaluation code may, clearly separated).

## Return (saved verbatim into the run record)
1. Summary; 2. Files changed; 3. Commands + test results; 4. Latency numbers; 5. Live-world validation table (world v3); 6. Problems/decisions; 7. Remaining work; 8. Branch + commit hashes.
