# CHANGELOG

## v2 — platform build (in progress, 2026-10-06/07)

### Claude 1 (lead)
- Captured 19 screenshots of every v1 page/state (`docs/ui_current/`) and wrote `docs/UI_CURRENT_STATE.md`.
- Initialised git (baseline `6ea2941`), systematic `AGENT_HANDOFF/` (MASTER_PROMPT index, AGENT_LEDGER, runs/).
- Froze v2 contracts: provenance, detector results/consensus, SHAP, drift, pattern memory, roles, model registry, decision replay, counterfactuals, shadow-mode fields, 3D graph scene (`backend/vigil/contracts.py`, `frontend/src/api/types.ts`, `frontend/src/api/client.ts`).
- `docs/FINAL_PARALLEL_PLAN.md`: 9-item information architecture, status colour scale, ownership, interfaces, merge protocol.
- Optional vigil.intel router hook in app.py; scenarios.touched_accounts().
- Evidence provenance on every risk signal; SHADOW MODE with conventional bank baseline; corroborating model_evidence hook (never fused).
- Decision Replay, counterfactual ladder, decision record, risk evolution (engine/replay.py) — deterministic, same policy engine.
- 3D GraphScene with frozen layered layout and cache (graph/scene.py); v2 routes (api/routes_v2.py).
- Ten attack patterns from the original project as deterministic scenarios (sim/attacks.py); 15 scenarios total.
- Tests: backend/tests/test_vigil_v2.py (6).
- Session restart (~22:55 IST) killed the Claude 2/3 subagents; Claude 3's partial work preserved on `claude3/run1-wip`; both relaunched as run 2 (incremental commits now mandatory).
- Reset fix: `db.wipe()` now also clears SQLite AUTOINCREMENT counters, so a demo reset restores identical ids (previously `intent_transitions` ids kept climbing). New test `test_reset_restores_identical_world_after_every_scenario`: runs all 15 scenarios, toggles SHADOW, resets → every table identical (timestamps masked), mode back to ACTIVE, identical tiers on re-run. 218 tests pass.
- Counterfactuals: none for Tier 0 decisions (the s4 high-value control previously showed a no-op ladder).
- 3D scene scoping fix: `?scenario=` / `?focus=` now return only that scenario's accounts / that account plus 1–2 hops (previously the global suspicious set was mixed in, so every attack looked the same: ~60 nodes). `atk_circular` → 11 nodes / 12 edges, 3 ms; default scene unchanged (60 nodes, ≤ 12 ms, 45 KB). Unknown scenario → 404. 220 tests pass.
- `touched_accounts(atk_*)` now lists only the accounts each pattern actually uses (was the whole 8-account pool: e.g. `atk_circular` reported 8, uses 4), so scoped scenes and detector comparison no longer include bystanders. Test checks it against the `seed_attack` ground truth for all 10 attacks. 221 tests pass.
- Second session restart (~23:45 IST) killed the run-2 agents; milestone commits survived; remainder recovered to `claude2/run2-wip` / `claude3/run2-wip`; relaunched as run 3 (01:10 IST, 2026-10-07).
- Scenario determinism fix: the `BEH_ODD_HOUR` rule read the wall clock, so between 00:00 and 05:00 IST scenario s1 scored 0.45 and became Tier 3 (scoped hold) instead of Tier 2, and two lifecycle tests failed at night. Scripted scenarios now evaluate time-of-day rules at a pinned local hour (`clock.DEMO_LOCAL_HOUR_IST` = 14); live and ambient payments still use the real hour. Every decision's audit payload now carries `evaluation_context` (`local_hour_ist`, `local_hour_source`: "wall clock" or "pinned by scripted scenario"). Test runs s1 at 01:00 and 13:30 IST (both Tier 2) and checks a live payment at 01:00 still fires `BEH_ODD_HOUR`.
- `GraphScene.version` is now a hash of the scene content instead of the cache key, so a re-fetch after unrelated activity (ambient postings bump the graph counter every 3 s) returns the same version and the 3D view keeps its object and replay position. Intel warm-up hook: `app.py` calls `vigil.intel.warm()` at startup when the intel router is present (no-op until Claude 2 merges). 223 tests pass (run at 01:19 IST, inside the odd-hour window).

## v1 — MVP (2026-10-06)
See `AGENT_HANDOFF/runs/20261006-2112_claude1_v1-build.md`.
