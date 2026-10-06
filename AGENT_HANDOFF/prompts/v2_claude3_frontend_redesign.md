You are CLAUDE 3 on the Vigil project (architecture: PRIMA). You own the FRONTEND VISUAL REDESIGN. Claude 1 (lead) owns contracts/backend/API and is implementing the new endpoints in parallel; Claude 2 is rebuilding the ML/detection-intelligence layer in parallel.

## Read first, in full
- `AGENT_HANDOFF/prompts/01_MASTER_PROMPT_v2_platform.md` — the user's brief (tone, what they hate, every feature).
- `docs/FINAL_PARALLEL_PLAN.md` — BINDING: 9-item information architecture (§1), status colour scale (§2), file ownership (§3), interfaces (§4).
- `docs/UI_CURRENT_STATE.md` + screenshots `docs/ui_current/*.png` — audit of the current UI (what survives, what is template-like).
- `frontend/src/api/types.ts` and `frontend/src/api/client.ts` — the FROZEN data contract. Every screen must be fed by these. Do not edit them; request changes in `AGENT_HANDOFF/REQUESTS.md`.
- The user's OLD frontends — inspect BEFORE designing and list which visual ideas are strong enough to keep:
  `C:\Users\KausikGH\Documents\Projects\Indian Bank Project\Indian Bank Project - End half sim - half actual\frontend\` (index.html, app.js, styles.css; Three.js graph via lib/three),
  `C:\Users\KausikGH\Documents\Projects\Indian Bank Project\ccmule-main\ccmule-main\frontend\sentinel\` (app.js, styles.css, and `stitch_designs/` — 12 HTML designs + screenshots),
  `...\ccmule-main\ccmule-main\frontend\threejs_graph.py` (the old 3D graph the user liked visually but was laggy).

## Environment
- You are in an isolated git worktree of `C:\Users\KausikGH\Documents\Projects\Fraud Detection`. Work and commit ONLY there.
- `cd frontend; npm install` (first time), then `npm run dev` (Vite on :5173, proxies `/api` and `/ws` to the backend on http://127.0.0.1:8000 which Claude 1 keeps running from the main repo; set `VIGIL_BACKEND` if needed). `npm run build` must pass (tsc strict + vite).
- New endpoints come online progressively while you work: `/api/graph/scene`, `/api/decisions/{id}/replay|counterfactuals|record`, `/api/accounts/{id}/risk-timeline`, `/api/mode`, `/api/governance/summary`, `/api/interventions`, `/api/system/health`, `/api/scenarios/{id}/replay`, and Claude 2's `/api/intel/*`. Build against the TYPES; render explicit "not yet available" states on 404 — NEVER fabricate data or hard-code numbers.
- Windows. Bash heredocs containing backticks break the Bash tool — create/edit files with Write/Edit.

## YOUR FILES
`frontend/src/{pages,components,styles,lib}/**`, `frontend/src/App.tsx`, `frontend/src/main.tsx`, `frontend/index.html`, `frontend/package.json` (+lock) for justified visualisation deps only, `docs/DESIGN_SYSTEM.md`, `docs/ui_v2/*.png`.
## MUST NOT EDIT
`frontend/src/api/**`, anything under `backend/`, `config/`, `scripts/`, other docs.

## WHAT TO BUILD
Visual target: institutional financial-intelligence platform — authoritative, calm, precise, high information density, premium, technical. Dark navy institutional shell is fine. NOT: neon cyberpunk, generic SaaS, giant gradient cards, glassmorphism, oversized stats, empty whitespace, random animation, "AI-generated dashboard", hackathon UI. Colour encodes STATUS only (NORMAL / WATCH / HIGH RISK / CRITICAL / HELD / CONFIRMED FRAUD — §2 of the plan). Detector families get neutral glyph + label identifiers. Simulated inputs always carry a SIMULATED marker. No RBI branding/logo; no text implying real RBI/NPCI/DPIP data.

1. `docs/DESIGN_SYSTEM.md`: tokens (colour, type scale, spacing, density), components (panels with hairline rules, dense tables, status pills, key-value grids, metric strips, timelines, drawers, tabs), "inherited ideas from the old frontends", "rejected ideas and why".
2. App shell: left or top navigation with exactly the 9 items of §1 (Overview, Transaction Guard, Network Intelligence, Detection & Models, Investigations, Interventions, Governance & Audit, Scenario Lab, System Health); top status strip (mode ACTIVE/SHADOW, payment provider, realtime, policy version, intel availability). Redirect old routes (`/investigate/*`, `/decision/*`, `/about`).
3. **Overview**: what is happening now / what needs attention / value at risk / emerging networks (compact network thumbnail) / detector agreement / active interventions / system status. Dense; no wall of KPI tiles.
4. **Transaction Guard** (`/guard`): customer device on one side (keep the existing simple four-question intervention copy and flows from PayPage — it works), and the bank-side pre-commit ASSESSMENT as a structured case: sender, recipient, amount, relationship, device, behaviour, network intel, external intel (SIMULATED), journey signals, context (SIMULATED), final decision + intervention, then provider/ledger/monitoring outcome after payment. Keep `/pay?as=` customer-only kiosk.
5. **Network Intelligence** (`/network`): HIGH-QUALITY WebGL 3D view, engineered correctly: use node positions from `GraphScene` (frozen, precomputed — NO running force physics; with 3d-force-graph set fx/fy/fz and cooldownTicks 0, or raw three.js with instanced meshes), suspicious subgraph default, configurable node cap, 1/2-hop expansion, cached payload (re-fetch only on scene version change), no rebuild on unrelated UI state, LOD labels (only hovered/selected/high-risk), obvious direction (arrows), edge particles ONLY for selected/replayed movement, node-selection investigation drawer (AccountIntel detectors + consensus + role + taint), smooth camera focus, 2D fallback toggle (reuse/upgrade the existing Cytoscape EvidenceGraph). Modes: MONEY FLOW, RISK, TAINT, MULE ROLES, GNN SCORE, RULE SCORE, ML SCORE (scores from `/api/intel/scores`). Visual distinction for victim, normal, suspected mule, collector, distributor, coordinator, entry, exit, confirmed fraud source, held. TIME / ATTACK REPLAY: scrub/play through `SceneEdge.txs` by timestamp. Lazy-load this page (code-split) so other pages stay light.
6. **Detection & Models** (`/detection`): detector agreement across accounts, early warnings, pattern alerts, role counts, model registry with SYNTHETIC VALIDATION metrics (precision/recall/F1/ROC-AUC/PR-AUC, confusion matrix, calibration, per-attack + leave-one-attack-out) from `/api/intel/models` and `/api/intel/overview`. "Operational use: corroborating evidence only" must be visible.
7. **Investigations** (`/investigations`, `/investigations/decision/:id`, `/investigations/account/:id`): case header; DECISION REPLAY with playback (frames from `/replay`; subscores and tier visibly evolve per frame); RISK EVOLUTION chart (SVG, markers labelled with WHY it changed — not a meaningless line); WHY / WHAT WOULD MAKE IT SAFE counterfactual ladder (`/counterfactuals`); evidence table with PROVENANCE (source, value, observed at, freshness, version, status); DETECTOR CONSENSUS (Rules, RF, GNN, drift, early warning, pattern memory, TrailScore, context, external — honest value kinds: never label a non-probability as a probability); SHAP panel (raw prediction, top +/- contributors, categories) clearly titled "explains the MODEL" and kept separate from ReasonLine "explains the OPERATIONAL DECISION"; drift baseline → current; pattern similarity bars ("structural similarity, not attribution"); role; money trace (keep MoneyTrace LIBR vs pro-rata); actions.
8. **Interventions** (`/interventions`): queue from `/api/interventions` — tier, state, age, SLA, hold, CircuitBreaker response, release/reject actions (existing `api.bankAction`).
9. **Governance & Audit** (`/governance`, `/governance/decision/:id`): mode ACTIVE/SHADOW toggle + shadow comparison (bank baseline vs Vigil recommendation), policy version/weights/ladder, model versions, decision records list → structured record (`/record`) with VIEW RAW RECORD and REPLAY DECISION, positioning (who hosts what; reuse AboutPage content).
10. **Scenario Lab** (`/lab`): all scenarios from `/api/scenarios` (14 incl. 10 attack patterns) with START / PAUSE / RESET / REPLAY / COMPARE DETECTORS (`/api/intel/scenarios/{id}/compare`), live step log.
11. **System Health** (`/health`): `/api/system/health`.
12. Trusted-contact page: keep (it works), align visually.
13. Realtime: keep push-only (`useRealtime` / Shell console bus); no polling.
14. Screenshots: if the Playwright MCP tools are available, save screenshots of every page to `docs/ui_v2/` (1440×900, plus a 390-wide mobile shot of /contact/arjun and /pay).

## Definition of done
`npm run build` passes; every button performs a real backend call (no fake success animation); unavailable endpoints show honest empty states; no polling; the 3D page sustains smooth interaction with the default scene; commit on your worktree branch with message "ui: <summary>".

## Return (your final message is saved verbatim into the run record)
1. Summary + the inherited/rejected visual ideas; 2. Files changed; 3. Build/test output; 4. Screenshot list; 5. Endpoints you found missing/incomplete; 6. Problems/decisions; 7. Remaining work; 8. Branch name + commit hash.
