# Vigil design system

## v10 additions (2026-10-13) — Overview operations center
* **Layout** (≥ 1280 px): header (window 15m/1h/24h/7d · rail · incident mode · find) → KPI strip (6 clickable tiles,
  delta vs previous window, 12-bucket sparkline) → Copilot incident strip → **money map (2fr) | live tape (1fr)** →
  compact 3D network | needs attention | situation brief → close monitoring | mule pipeline → money by channel. Copilot
  dock bottom-right. Tablet / phone: one column.
* **Money map** (`components/map/*`): dark canvas card. Land from the bundled India point-of-view Natural Earth file
  (SVG); arcs, moving postings and pulses on canvas. Arc thickness = value; colour = risk (mint normal, amber early
  warning, red fraud-linked). City dot size = value. ATM = small square (red when a risky withdrawal used it); cash-out
  cluster = red ring with count; collection point = amber / red diamond. Foreign destinations clamp to the map edge
  with "→ City". Flat | Globe toggle (globe lazy-loaded, three.js, texture drawn from the same GeoJSON). Every location
  carries the dashed amber **Simulated locations** badge and "Simulated location · basis · ±accuracy".
* **Live tape** (`components/tape/LiveTape.tsx`): 60 px virtualised rows (≤ 300 in memory); red / amber left bar + tint
  for fraud-linked / early-warning; rail badge colours per rail; "N new" pill while paused on hover; fresh rows flash.
* **Connections drawer**: right slide-over (Esc closes): posting header with location label, From / To cards, Linked by
  chips, upstream / downstream grouped by hop, Show on map · Show in network · Open recipient · Ask Copilot.
* **Mule pipeline**: five-stage horizontal funnel (mint → amber for Passing through → red for Exited); suspicious-path
  rows tinted red; benign shared-device pairs tagged "family / shop pattern".
* **Money by channel**: per rail, a grey bar (share of value) over a red bar (share of fraud-linked value).
* **Copilot**: strip chips = severity dot + SEVERITY label + kind glyph + title + ₹ + age (colour is never the only
  signal); dock 360–760 px, resizable, focus-trapped; Briefing (severity "why?" breakdown, confidence, action cards with
  whitelisted buttons, evidence chips) and Chat (streaming, expandable tool-call chips, suggestion chips, Stop, copy,
  retry). Model text renders through `lib/safeMarkdown.tsx` only (no raw HTML).

## v6 additions (2026-10-12)
* **Identity:** `components/Logo.tsx`. The mark is a 32 px tile, gradient `#6eedd2 → #1aa585`, rx 9.5, with a dark-mint eyelid arc, a white V (3.1 stroke, round caps) and a pupil dot. The wordmark is **VIGIL** in Sora 700, 18 px, letter-spacing 0.16 em, with a small grey tagline. Use the mark alone where space is tight; never recolour it.
* **Customer device:** `.iphone` (60 px radius, titanium gradient bezel, side buttons) wraps `.phone` (47 px radius). It has an iOS status bar with the Dynamic Island and a home indicator. The device column is 396 px wide.
* **Edge filter:** a `seg seg-dark` segmented control on dark stages (`.stage-filter`) with Recent / Window / Risk only / All / Off. Defaults: Recent on the Overview, Window on Network.
* **KPI strip:** `.kpi-strip`, six hairline-divided figures under the page title, each with a value, label and sub-line. It replaces scattered tiles.
* **Score cells:** `.score-cell`, a 64 px bar plus a mono value coloured by band. Sortable headers use `th.sortable` with an arrow.

## v5 — operations center (current, 2026-10-12)
Supersedes v4's dark graphite as the default (v4 becomes the dark toggle). References: `docs/archive/references/reference_v5/*`. Implementation: `frontend/src/styles/tokens.css` (light tokens + `[data-theme="dark"]`) and `frontend/src/styles/v5.css` (loaded after `app.css`).
* Field `#eef1f3` with a soft mint radial glow; cards white, 20 px radius, two-layer soft shadow, no borders; tiles 18 px.
* Navigation: one pill bar in the top bar; the active item has a mint gradient (`#7cecd5 → #4fd6b8`) with dark mint ink. Buttons are pills; primary is near-black `#0f1419`.
* Status colours are unchanged in meaning (watch amber, high orange, critical red, held violet, confirmed fraud crimson), tuned for white.
* Dark highlight cards (`--canvas #0c1115`) only for live canvases (network / evidence scenes).
* Card header pattern: 30 px black icon tile + 15–16 px semibold title + right-aligned pill action. Big numbers: 40 px / 500 weight, with a delta pill.
* Demo-only inputs live in the Test inputs drawer, never on a product screen.


## v4 — institutional (current, 2026-10-09; supersedes the v3 visual language below)

User direction (`AGENT_HANDOFF/prompts/06_USER_professional_ui_2026-10-09.md`): "Not the green UI. Make it a professional, matured UI. Neat it up. Fully functional, no fake stuff." v3's *functionality* (live universe, command center, streams, score tables, attack runs, all nine areas) is kept; its *look* (green-black field, mint accent, glow, translucent glass, display hero, letter-spaced eyebrows) is replaced.

| Decision | v4 rule |
|---|---|
| Field | Neutral graphite (`#0d1015` page, `#141920` panels, `#222932` hairlines). Light theme is a real alternative (`data-theme="light"`), not an afterthought. |
| Accent | One steel blue (`#5b93f0`, strong `#3f7be0`) for interaction only: primary buttons, selection, focus, links. Never means "safe". |
| Status | Muted scales: normal slate `#8593a8`, watch amber `#d6a23f`, high `#dd7a3e`, critical `#e2564e`, held violet `#9283d6`, confirmed fraud crimson `#c8344d`. Live account status: normal steel `#5f86b8`, new sky `#5fb0d6`. No green anywhere except a muted `--ok` for "ledger balanced / approved". |
| Type | IBM Plex Sans for UI, IBM Plex Mono only for identifiers, amounts in tables and code. 13 px base; page title 20 px; panel title 14 px. Sentence case everywhere (proper names keep capitals: RingWatch, CircuitBreaker, Random Forest). |
| Shape | Flat surfaces, 1 px borders, radii 3–8 px, no gradients, glow, blur or translucency. Shadows only for floating layers (toasts, drawers). |
| Headings | One heading per panel (`Panel` drops the kicker when a title exists). No numbered crumbs or nav items; nav uses 16 px stroke icons. |
| Metrics | One hairline-divided metric strip (`.mstrip`), not a wall of tiles; status shown by a 2 px top rule and value colour. |
| Canvas | 3D / graph stages are always dark (`--canvas`) in both themes; no starfield; node glow 0.07; edges drawn with normal blending (additive blending turned blue into cyan). |
| Honesty | Charts must not imply direction they do not have (e.g. SHAP: signed `category_net` drawn red/blue; unsigned influence never shown with "+"). Exact counts beat rounded percentages that hide an intervention. |

---

# v3 — live platform (historical)

Owner: Claude 3 (frontend). Applies to every bank-side screen. The customer device (`/pay`, the phone inside Transaction Guard) is a light consumer card; the trusted-contact phone (`/contact/:token`) uses the v3 dark field with one large alert card.

Goal (user direction 2026-10-07, `AGENT_HANDOFF/prompts/04_USER_refined_mule_repo_2026-10-07.md`): reach the level of the refined money-mule reference — its live 3D transaction universe, analytics and look — and bring Vigil's PRIMA layer (pre-commit assessment, interventions, replay, counterfactuals, provenance, governance) into the same system. Calm and readable; no neon noise.

Implementation: `frontend/src/styles/tokens.css` (tokens), `frontend/src/styles/app.css` (components), `frontend/src/components/ui.tsx` (primitives), `frontend/src/lib/status.ts` (status scales), `frontend/src/lib/universe3d.ts` (live universe engine), `frontend/src/lib/graphStyle.ts` (evidence-scene grammar), `frontend/src/components/charts.tsx` (Chart.js wrapper).

---

## 1. Principles

1. **Hue encodes status; mint is the brand / interaction accent and never means "safe".** Two status scales (§2): the decision scale (tiers, scores) and the live account scale (universe, streams).
2. **Reference look, institutional content.** Deep green-black field, translucent panels with hairline mint borders, 18–28 px radii, soft glow, eyebrow labels (letter-spaced, mint, uppercase, mono), Space Grotesk for UI / display, JetBrains Mono for data.
3. **Every number has a source.** Values come from the API; nothing is estimated client-side. Where a chart samples live values (account risk over time), it says so.
4. **Honest absence.** An endpoint that is not served renders a hatched "not yet available" block naming the endpoint. Nothing is mocked.
5. **Honest value kinds.** `score`, `uncalibrated probability`, `calibrated probability (synthetic worlds)`, `level`, `similarity`, `count` are printed next to the value.
6. **Honesty labels.** `SIMULATED` on simulated inputs; `SYNTHETIC VALIDATION` on every model metric; `simulator ground truth` on anything derived from scenario tags (injected volume series, last-attack injected list, account ground truth); model evidence is "corroborating — not used for authorisation".
7. **Model ≠ decision.** SHAP panels are titled "explains the MODEL"; ReasonLine "explains the OPERATIONAL DECISION". They never share a panel.
8. **Push, never poll.** One console WebSocket (Shell) fans out; lists flush ≤ 2/s, charts ≤ 1/s, refetches are event-driven and throttled. The 3D canvas is imperative — no React render per event.
9. **Motion carries information.** Travelling particles = a posting that just happened; a ring = held / confirmed; the stage flashes red only while an attack runs. No idle decoration.

## 2. Status scales

**Decision scale** (tiers, network / model scores, drift) — `--st-*`, `lib/status.ts`:

| Status | Token | Hex | Used for |
|---|---|---|---|
| NORMAL | `--st-normal` | `#5b9bff` | T0, score < 0.30 |
| WATCH | `--st-watch` | `#ffbc4d` | T1, score 0.30–0.50, drift MEDIUM |
| HIGH | `--st-high` | `#ff9157` | T2 / T3 risk level, score 0.50–0.75 |
| CRITICAL | `--st-critical` | `#ff647f` | T4, score ≥ 0.75, rejected |
| HELD | `--st-held` | `#a68bff` | scoped hold (state HELD / ESCALATED) |
| CONFIRMED FRAUD | `--st-fraud` | `#e8264f` | solid pill — outranks everything |

A payment's final score is coloured by its **tier**, never by the network bands.

**Live account scale** (universe nodes, stream pills, account status) — `--as-*`, `ACCOUNT_STATUS_*` in `lib/status.ts`. Precedence (contract): confirmed_fraud > held > flagged > early_warning > new > normal > idle.

| Status | Hex | Node |
|---|---|---|
| normal | `#2f7dff` | blue |
| idle | `#1f4a8f` | dim blue (no posting in the live window) |
| new | `#22ff99` | mint (opened < 7 days) |
| early_warning | `#ffc34d` | amber, larger |
| flagged | `#ff3d63` | red, larger, LOD label |
| held | `#9b7bff` | violet + ring |
| confirmed_fraud | `#c8102e` | deep crimson + ring |
| external | `#7e8f8a` | grey, outer ring |

## 3. Tokens

**Field:** `--bg-0 #05110d`, `--bg-1 #081913`, `--bg-2 #0c2018`; body = two faint radial glows (mint top-left, amber top-right) over a vertical gradient + a 42 px grid at 7 % opacity.
**Surfaces:** `--surface rgba(8,24,18,.84)` panels (blur 18 px), `--surface-2/3` rows and inputs, `--surface-strong` table heads and chart shells. **Lines:** `--line` / `--line-2` hairlines, `--line-3` / `--accent-line` mint borders.
**Ink:** `--ink #edf7f1`, `--ink-2 #b9cfc3`, `--ink-3 #96b1a2`, `--ink-4 #5f7c6d`.
**Accent:** `--accent #47d38c` (primary buttons are a `#68f0af → #25c870` gradient with dark ink), `--warning #ffbc4d`, `--danger #ff647f`.
**Type:** Space Grotesk (UI) + JetBrains Mono (ids, money, scores, timestamps, eyebrows). Base 14 px; KPI values 24–30 px; hero titles `clamp(28px, 2.7vw, 42px)`, Overview hero up to 56 px.
**Radii:** 8 / 14 / 18 / 22 / 28 px. **Depth:** `--shadow 0 28px 80px rgba(0,0,0,.32)`; glow only on dots and selected states.
**Charts (Chart.js v4, loaded on demand):** teal `rgba(43,217,176,.78)` normal volume · magenta injected (simulator ground truth) · blue RF · magenta GNN · teal rules · amber early warning / threshold · red network score / detected; tiers T0–T4 = blue · amber · orange · violet · red.
A light theme exists (`data-theme="light"`) with the same roles.

## 4. Components

| Component | Class / primitive | Notes |
|---|---|---|
| Shell | `.shell .side .strip` · `Shell.tsx` | Grouped rail (Operate / Intelligence / Control, 01–09), status strip (mode, payments, realtime, policy, intel, ext. intel `SIMULATED`, stream, clock, theme), SHADOW band, toasts for status escalations and completed attack runs. |
| Page hero | `PageHead` / `.page-head` (`compact`) | The reference hero card on every page: eyebrow crumb, display title, lede, actions right. `compact` (Network) keeps the canvas in the viewport. Overview uses the larger `.hero` with LIVE / RF / GNN / SHAP / DB chips. |
| Panel | `Panel` / `.panel` | Eyebrow kicker, title, question (`q`), actions, optional footer for provenance and honesty notes. |
| KPI tiles | `.mstrip` + `Metric` (`.kpi-grid`, `.inv-tiles` 4×2, `.dense`) | Label 12 px, value 24–30 px, mono qualifier line; value coloured only when it is a status. |
| Profile line | `.profile-line` | Mono pill row under the account tiles (opened, devices, balance, held, postings, traced value, limit, contact). |
| Tokens | `.token-row .token` (`.danger .warn .ok`) | Rules fired, early-warning signals, detected / missed mules (links). |
| Why list | `.why-list` | Reference "Why flagged?" bullets: live reason, RingWatch reasons (operational), consensus, role, top SHAP features (model). |
| Streams | `.feed .feed-row` · `.alert-row .sev` | Live transactions, risky transactions, alert stream; fresh rows flash once. |
| Command center | `CommandCenter` · `.scn-grid .scn-btn .run-card .progress .run-chip` | Scenario grid grouped attack / payment / control; START / PAUSE / RESUME / RESET; chips `warning +x` · `detected +y` · `completed` from `AttackRun`. Shared by Overview and Scenario Lab (run chips, last result, history per pattern). |
| Attack results | `LastAttackResult`, `AttackHistory` | Injected / detected / missed / warned / false positives, latencies, precision / recall, model threshold — simulator ground truth. |
| Charts | `ChartCanvas` (`components/charts.tsx`), `.chart-shell .chart-h` | Dynamic `import("chart.js")`, in-place `update("none")` at most once a second; honest empty states. Shared: `TiersOverTimeChart`, `VolumeChart`, `LiveStatsCharts`, `DetectionCharts`. |
| Live universe | `LiveUniverse3D` (`lib/universe3d.ts`) · `.stage .uni .uni-label .uni-tip` | §5. |
| Evidence scene | `Graph3D`, `EvidenceGraph` (2D fallback), `.net .net-hud .net-replay .drawer` | Scoped scene (`?scenario=`, `?focus=`), modes, replay, drawer — kept from v2 as Network's second view. |
| Decision building blocks | `ReasonLinePanel`, `DecisionReplayView`, `CounterfactualLadder`, `ProvenanceTable`, `RiskEvolution` | Unchanged behaviour, restyled. |
| Model evidence | `AccountIntelView` (`grid`), `ModelCard`, `ModelComparison`, `table.matrix` | Consensus, SHAP, drift, pattern memory, role; registry with `SYNTHETIC VALIDATION`. |
| Customer device | `.phone .tier-banner .q-block` | Light card; four-question intervention copy from v1. |
| Trusted-contact phone | `.contact-wrap .contact .alert-card` | v3 dark field, 52 px response buttons, readable at 390 px. |
| Unavailable | `Unavailable`, `Async` | Hatched block naming the missing endpoint. |

## 5. Live universe grammar (`lib/universe3d.ts`)

* **Cost model (from the reference `graph3d.js`):** one `InstancedMesh` for node cores + one for additive glows (2 draw calls), one `LineSegments` buffer for live edges updated in place, one for the faint history constellation, an `InstancedMesh` of travellers for new postings, a perspective grid floor; raycast only after the pointer moves; render loop pauses when the canvas is off-screen; no per-frame allocation; LOD labels only for hovered, selected, flagged / held / confirmed nodes.
* **Layout:** deterministic sphere by stable hash; merchants on an inner shell, demo customers in their own shell, external counterparties on the outer ring; slow optional auto-orbit; OrbitControls.
* **Colour = live status** (§2) under LIVE STATUS; Network adds lenses RISK (RingWatch score — operational), MODEL SCORE (corroborating), ROLES, TAINT (traced value).
* **Edges:** ordinary flows are quiet teal (opacity by count, fading with age across the window) so alarm edges read first — red when either party is flagged / confirmed, violet when held, amber for early warning, magenta for simulator-ground-truth postings when that toggle is on. History edges are drawn very faint.
* **Data:** `api.universe()` on mount; WS `ledger.posted` (edge + traveller), `intel.tx_scored` / `intel.account_status` (recolour / rescale + toast), `demo.reset` (reload). Click a node → drawer (status, role, taint, recent postings, open account).

## 6. Page patterns (v3)

* **Live Operations:** hero → 12 KPI tiles → PRIMA strip → universe stage → command center + attack subgraph → streams → rule / hybrid score tables → last attack result + PRIMA attention + detector agreement → attack history → live statistics.
* **Account investigation (reference layout + PRIMA):** 4×2 score tiles (live status, RingWatch, consensus, role / RF, GNN, rules, early warning) → profile line → risk over time (live-sampled) + SHAP category chart → why flagged · rules fired · early-warning signals · RingWatch features · external intel + window features (now · baseline · change · SHAP) → ledger + neighbours + alerts + simulator ground truth → PRIMA risk evolution + intents → full model evidence grid → account record.
* **Case:** hero with tier pill and parties → 4×2 tiles → Decision Replay → risk evolution + counterfactual ladder → ReasonLine vs model → provenance → money trace + recipient network → journey / intervention / parties + next steps.
* **Detection & Models:** SYNTHETIC VALIDATION banner → KPI row (RF / GNN held-out ROC-AUC, rule recall, scored, RingWatch flags, early warnings) → charts (flagged per family, metrics by model, per-attack recall) → RingWatch rules, early warnings, roles → per-account scores, pattern memory → registry + model card.

## 7. Decisions

* **v3 reverses the v2 "no glass / no radial gradients / no Space Grotesk / no KPI wall" rules** because the user named the refined reference as the bar. Kept from v2: one status meaning per hue, honest value kinds, push-only data, model ≠ decision, provenance, LOD labels, motion only with meaning.
* **Still rejected:** sci-fi copy and decorative numbers; particles running on every edge permanently (travellers exist only for postings that just happened); pulsing everything (only the LIVE dot pulses); neon-bright ordinary edges (dimmed in the run-2 self-review so attack edges read first).
* **Risk over time on the account page** has no stored score history for model families, so it samples the backend's own values each time they are re-computed while the page is open, and says so.
* **Before `intel.tx_scored` is served,** the streams carry each party's *current* live status from the universe (RingWatch + Vigil state), are seeded with the newest postings of the live window and the newest PRIMA alerts, and say so in their footers.
* **Bundles:** three.js only in the Overview / Network chunks; Chart.js (208 kB) only when a chart mounts; Cytoscape only on the 2D fallback.
* **Screenshots** (`docs/archive/screenshots/ui_v3/`) are captured headless with an isolated Chromium at 1600 × 1000 (390 × 844 for the contact phone).

History: v2 decisions (run 2–3: role shapes, scene caching, shared customer device, tier-coloured final score, printed value kinds, risk-evolution labelling, alert-window gap) remain in force; see git history of this file (`3aaa7ae`) for the v2 text.
