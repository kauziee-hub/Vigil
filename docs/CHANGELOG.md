# CHANGELOG

## v2 — platform build (in progress, 2026-10-06/07)

### Claude 1 (lead)
- Captured 19 screenshots of every v1 page/state (`docs/ui_current/`) and wrote `docs/UI_CURRENT_STATE.md`.
- Initialised git (baseline `6ea2941`), systematic `AGENT_HANDOFF/` (MASTER_PROMPT index, AGENT_LEDGER, runs/).
- Froze v2 contracts: provenance, detector results/consensus, SHAP, drift, pattern memory, roles, model registry, decision replay, counterfactuals, shadow-mode fields, 3D graph scene (`backend/vigil/contracts.py`, `frontend/src/api/types.ts`, `frontend/src/api/client.ts`).
- `docs/FINAL_PARALLEL_PLAN.md`: 9-item information architecture, status colour scale, ownership, interfaces, merge protocol.
- Optional `vigil.intel` router hook in `app.py`; `scenarios.touched_accounts()`.

## v1 — MVP (2026-10-06)
See `AGENT_HANDOFF/runs/20261006-2112_claude1_v1-build.md`.
