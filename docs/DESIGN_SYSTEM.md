# Vigil design system (v2)

Owner: Claude 3 (frontend). Applies to every bank-side screen; the customer device (`/pay`, the phone inside Transaction Guard) and the trusted-contact phone (`/contact/:token`) use a light consumer variant of the same tokens.

Goal: an institutional financial-intelligence console — authoritative, calm, precise, dense. It must read as an operations tool a fraud-intelligence or payment-risk team would sit in front of all day, not as a dashboard template.

Implementation: `frontend/src/styles/tokens.css` (tokens), `frontend/src/styles/app.css` (components), `frontend/src/components/ui.tsx` (React primitives), `frontend/src/lib/status.ts` (the status scale), `frontend/src/lib/graphStyle.ts` (network visual grammar).

---

## 1. Principles

1. **Colour encodes status, and only status.** Six hues, one scale (§2). Structure, detector families, navigation and interaction are neutral navy / steel. If something is coloured, it is telling you how worried to be.
2. **Hairlines, not cards.** Flat panels separated by 1 px rules; 2–5 px radii; no drop shadows, no gradients, no glass.
3. **Density with hierarchy.** 13 px base type, 28 px table rows, uppercase micro-labels ("kickers") above values, tabular numerals everywhere. One metric *strip* per page at most — never a wall of KPI tiles.
4. **Every number has a source.** Values come from the API; nothing is estimated client-side. Provenance (source · observed at · freshness · version · status) is printed next to the evidence it describes.
5. **Honest absence.** When an endpoint is not served (404 "No such route") the panel says *not yet available* with the endpoint name, in a hatched "unavailable" block. Nothing is mocked, interpolated or hard-coded.
6. **Honest value kinds.** A detector value is labelled with what it is (`score`, `uncalibrated probability`, `level`, `similarity`, `count`). Nothing is called a probability unless the API says it is calibrated.
7. **Simulated inputs are always marked.** A dashed `SIMULATED` stamp accompanies external intelligence, context signals, scenario-injected journey events and test payments.
8. **Model ≠ decision.** SHAP and detector panels are titled "explains the MODEL" and sit apart from ReasonLine ("explains the OPERATIONAL DECISION"). Model evidence is labelled *corroborating — not on the authorisation path*.
9. **Motion only when it carries information.** Replay playback, a camera focus tween, particles on the selected/replayed money path, a 1.8 s flash on a newly arrived row. No idle animation, no pulsing, no scroll effects.
10. **Push, never poll.** One console WebSocket (Shell) fans out to pages; pages debounce bursts into one refetch. The only timers are local clocks (age/SLA countdown) and replay playback.

## 2. Status scale (FINAL_PARALLEL_PLAN §2)

| Status | Token | Dark | Light | Used for |
|---|---|---|---|---|
| NORMAL | `--st-normal` | `#4e9c7c` | `#2f7a5a` | T0, score < 0.30, drift LOW |
| WATCH | `--st-watch` | `#c9a43b` | `#94700f` | T1, score 0.30–0.50, drift MEDIUM |
| HIGH RISK | `--st-high` | `#dc8642` | `#b8561f` | T2/T3 risk level, score 0.50–0.75, drift HIGH |
| CRITICAL | `--st-critical` | `#e15656` | `#b8282f` | T4, score ≥ 0.75, rejected |
| HELD | `--st-held` | `#9886e6` | `#5f47b8` | scoped hold active (state HELD / ESCALATED), held value |
| CONFIRMED FRAUD | `--st-fraud` | `#e2477c` | `#a8124f` | bank-confirmed scam source/recipient, traced value; rendered as a **solid** pill so it outranks everything |

Each has a 12–16 % alpha background (`--st-*-bg`). `--st-unknown` (`#5d6f86`) = not evaluated / not applicable. Mapping functions live in `lib/status.ts` (`tierStatus`, `scoreStatus`, `levelStatus`, `stateStatus`); WebGL uses the hex mirror `STATUS_HEX`.

Tier vs state: a tier is a *risk level* (T3 = HIGH); HELD is a *state* shown with its own pill. A T4 escalation therefore shows `CRITICAL` + `HELD`.

## 3. Tokens

**Surfaces (dark, default):** `--bg #0a111b` page · `--bg-side #0b1320` rail/strip · `--surface #0e1724` panel · `--surface-2 #121d2d` raised row / input · `--surface-3 #172438` bar track · `--surface-hi #1b2a40` hover. **Rules:** `--line #1d2a3d`, `--line-2 #283a53`, `--line-3 #36506f`.
**Ink:** `--ink #dce5ef` primary · `--ink-2 #a2b2c5` secondary · `--ink-3 #6f8298` labels · `--ink-4 #4b5c72` disabled.
**Accent (interaction only, deliberately not a status hue):** steel blue `--accent #8fb0dc` — selection, focus, active nav, primary button.
**Light theme** (`data-theme="light"`, toggle in the strip): same roles, paper surfaces; status hues darkened for contrast.

**Type:** IBM Plex Sans (UI) + IBM Plex Mono (data: ids, money, scores, timestamps). Scale `--fs-xs 10.5` · `--fs-sm 11.5` · `--fs-md 12.5` · `--fs-base 13` · `--fs-lg 15` · `--fs-xl 18` · `--fs-num 17` (metric strip values). Kickers: 10.5 px, 600, uppercase, +0.08em.
**Spacing:** 2 / 4 / 6 / 8 / 12 / 16 / 20 / 28 px (`--s1…--s8`). Page gutter 16–20 px; panel padding 10×12; grid gap 12.
**Density:** table row 28 px (24 compact); button 28 px (24 sm, 20 xs); pill 19 px.
**Radii:** 2 / 3 / 5 px. **Shadows:** none.

## 4. Components

| Component | Class / primitive | Notes |
|---|---|---|
| App shell | `.shell .side .strip` · `Shell.tsx` | Left rail with the 9 IA items (numbered 01–09, grouped Operate / Intelligence / Control), status strip on top: MODE (ACTIVE/SHADOW), PAYMENTS provider, REALTIME, POLICY version, INTEL availability, EXT. INTEL `SIMULATED`, STREAM, clock, theme. A full-width band appears in SHADOW mode. |
| Page head | `PageHead` | crumb kicker · title · one-line lede · right-aligned actions. |
| Panel | `Panel` / `.panel .panel-h .panel-b .panel-f` | Header row: kicker, title, question it answers (`q`), actions. Hairline body. Optional footer for provenance. |
| Section | `.sect .sect-t` | Ruled sub-sections inside a panel. |
| Metric strip | `.mstrip` + `Metric` | One row of hairline-separated readings with a one-line qualifier; value coloured only when it is a status. |
| Key-value grid | `KV` / `.kv` (`.c4` = 2 pairs per row) | Dense `dt/dd`, mono values. |
| Dense table | `table.dt` (`.compact`) | Sticky uppercase header, 28 px rows, `tr.click` hover, `tr.sel` accent bar, inline bars inside cells. |
| Status pill | `Pill`, `TierPill`, `StatePill`, `ScorePill` | Square dot + uppercase label; fraud pill is solid. |
| Detector glyph | `Glyph` / `.glyph` | Neutral 3-letter mono identifier per family (RUL, RF, GNN, DRF, EW, PM, RW, TS, CTX, EXT). Never a hue. |
| Simulated stamp | `Sim` / `.sim` | Dashed outline, mono uppercase. |
| Bars | `Bar`, `BarRow`, `.dist` | 6 px track, status-coloured fill, optional threshold ticks (policy ladder). |
| Timeline | `.tl .tl-i` (`.hot .crit .held .ok .sim-i .future .now`) | Square markers; replay dims future frames and highlights the current one. |
| Tabs / segmented | `Tabs`, `Seg` | Underline tabs; uppercase segmented control for modes. |
| Drawer | `.drawer` | Right slide-over inside the network stage; investigation of the selected node. |
| Notices | `.notice` (`.err .warn .info`) | Left-ruled callouts. |
| Unavailable | `Unavailable`, `Async` | Hatched block naming the missing endpoint. `Async` = loading → error → unavailable → data. |
| Assessment case table | `.assess` | Transaction Guard: one row per signal family (label · evidence · score), decision row shaded. |
| Counterfactual ladder | `.ladder .rung` | Current tier rung shaded; each rung = deterministic policy-engine counterfactual. |
| Replay | `.replay-ctl .subs` | Play / step / scrub; subscores animate width (0.35 s) as frames advance. |
| Charts | `.chart` (inline SVG) | Risk evolution: step line + threshold bands + numbered markers whose labels say *why* the score moved. No chart library. |
| Network stage | `.net .net-hud .net-legend .net-label .net-replay` | WebGL canvas with mono HUD, legend, LOD labels, replay bar. |
| Customer device | `.phone .tier-banner .q-block` | Light consumer variant; the four-question intervention (RISK LEVEL / WHAT CHANGED / WHY / ACTION) kept verbatim from v1. |
| Trusted-contact phone | `.contact-wrap .contact .alert-card .c-note` | Same light consumer palette as the customer device; 48 px response buttons; mobile-first. |
| Scene thumbnail | `SceneThumb` / `svg.thumb` | Static SVG of the server's frozen layered layout: x = money-flow depth, y = position around the layer ring. No WebGL, no physics — cheap enough for Overview and the account view. |
| Model card | `ModelCard`, `ModelComparison` (`components/ModelCard.tsx`) | Registry comparison table + one model's validation record: metric strip, confusion matrix, raw-vs-calibrated reliability diagram, per-attack + leave-one-attack-out table, leakage audit, global SHAP, rule table, FP by persona; unknown metric keys under "training details" (nothing hidden). `.stamp-sv` = SYNTHETIC VALIDATION. |
| Detector matrix | `table.matrix .cell` | Accounts × detector families (Scenario Lab COMPARE DETECTORS): flagged cells outlined in the family's status colour, unflagged grey; scripted role + consensus pill per row; row drill-down. |
| Next steps | `ol.steps` | Numbered investigator actions with inline release / reject. |

## 5. Network visual grammar (`lib/graphStyle.ts`)

* **Colour = status** under the active mode (RISK: score bands; TAINT: traced value; MULE ROLES: neutral steel with role shapes; GNN / RULE / ML: the detector's score through the same bands; MONEY FLOW: neutral nodes, edge weight = amount).
* **Shape = role** (identical in 2D and 3D): sphere = account, icosahedron = suspected mule, hex prism = pass-through, octahedron = collector, cone = distributor, dodecahedron = coordinator, cylinder = entry, tetrahedron = exit / cash-out, box = external account.
* **Rings = state:** white = victim, violet = held, magenta = confirmed fraud source/recipient, steel = selected.
* **Edges:** shaft width ∝ √amount, arrowhead at the receiving node (direction is never ambiguous), magenta when value is traced from a confirmed scam. Particles only on the selected node's edges or on transactions inside the replay window.
* **Labels:** level of detail — hovered, selected and the top high-risk / confirmed nodes only (≤ 22).

## 6. Inherited ideas from the old frontends

Inspected before designing: `Indian Bank Project - End half sim - half actual/frontend/` (index.html, app.js, styles.css), `ccmule-main/frontend/sentinel/` (+ 12 `stitch_designs`), `ccmule-main/frontend/threejs_graph.py`.

| Idea | Source | Where it lives now |
|---|---|---|
| Left rail with operator context; square hairline panels; uppercase mono micro-labels over values | stitch designs (Aegis 08/10/12) | Shell rail, `.panel-h .k`, `.mstrip .k` |
| Investigation slide-over with a header metric row (accounts involved · exposure · hops · score) and an operator briefing | stitch 12 "network investigation" | Network drawer (`.drawer`), Investigations case header |
| Inline risk bars inside table rows | stitch 08/12 | RingWatch / early-warning / consensus tables |
| Legend and coordinate/HUD readouts overlaid on the graph canvas | stitch 10, threejs_graph HUD | `.net-hud`, `.net-legend` |
| Panel kickers and mini-metric strips instead of hero tiles | End-half-sim `panel-kicker`, `mini-metric` | `.panel-h .k`, `.mstrip` |
| Full-bleed graph stage + separate attack-subgraph replay | End-half-sim "Attack Subgraph" stage | Network stage + TIME / ATTACK REPLAY bar (scenario-scoped) |
| Investigation order Role → SHAP breakdown → why flagged; drift; pattern memory; early-detection cross-check | End-half-sim post-detection panels | Investigations "Model evidence" block |
| Labels only when zoomed / important (LOD) | threejs_graph `zoom > 3` labels | LOD labels in Graph3D |
| Cubic-eased camera zoom to the fraud cluster | threejs_graph `zoomToFraudCluster` | Graph3D focus tween on selection |
| A single particle travelling along the attack edge during replay; normal edges hidden during attack phase | threejs_graph replay | Particles only for selected / replayed edges; non-active edges dimmed during replay |

## 7. Rejected ideas and why

| Rejected | Why |
|---|---|
| Neon cyan / green on black, glow (`shadowBlur`) passes | Reads as cyberpunk, not institutional; glow passes were a major source of the old graph's lag. |
| Particles permanently running on every edge; per-frame JS collision for all nodes; running force physics | The old 3D view's lag. Replaced by a frozen server layout, InstancedMesh, render-on-demand, particles only on the selected/replayed path. |
| Pulsing nodes, attack-flash red vignette, scroll-reveal blur transitions | Motion without information; distracting in an operations tool. |
| Sci-fi copy ("Neural map", "Deploy scan", "Sovereign data integrity") and decorative numbers (14,282 nodes) | Not credible to a bank audience; numbers must come from the API. |
| Radial-gradient backgrounds, 22–28 px rounded glass cards, Space Grotesk / Share Tech Mono | Generic SaaS / hackathon aesthetic the brief explicitly rejects. |
| v1 KPI tile wall (8 equal tiles, big numbers) | Oversized statistics; replaced by one metric strip + attention queues. |
| v1 five tier colours + five dimension colours + role colours | Colour stopped meaning anything; replaced by one status scale + neutral glyphs/shapes. |
| v1 raw `key=value` evidence and ISO timestamps | Developer output; replaced by humanised evidence chips + provenance lines. |
| v1 lifecycle diagram on the operational overview | Static explainer in prime space; the lifecycle now appears where it is used (Guard outcome, Governance positioning). |

## 8. Decisions on the run-1 work (run 2 review)

Run 1 (interrupted) produced the tokens, primitives, status scale, Graph3D and EvidenceGraph rewrite. Kept: token set, status scale, Plex type pairing, InstancedMesh/render-on-demand Graph3D, LOD labels, the 2D Cytoscape fallback. Changed in run 2:
* Added explicit `suspected` and `pass-through` role shapes and `victim` handling — the live `/api/graph/scene` emits `suspected`, `pass-through`, `cash-out`, `victim` roles that run 1 collapsed into "normal".
* Scene payloads are cached client-side per query (cap · focus · hops · scenario) and only re-fetched when a console event indicates structural change (ringwatch scan, taint, scenario, reset), debounced; ambient ledger traffic marks the scene *stale* (one-click update) instead of rebuilding geometry every transaction.
* The customer device was extracted into one component shared by `/guard` (with the bank assessment beside it) and the `/pay?as=` kiosk (customer only, no shell), so the v1 intervention copy and flows exist exactly once.
* Shell reads `/api/system/health` (superset of `/api/health`) and shows a SHADOW band when Vigil is not intervening.

## 9. Decisions in run 3

* **A payment's final score is coloured by its tier** (policy ladder), never by the 0.30 / 0.50 / 0.75 network bands — those bands apply only to RingWatch / network risk and model scores. Dimension subscore bars are neutral (families are identifiers, not statuses).
* **Value kinds are printed, not implied.** RF / GNN detector values are "calibrated probability (synthetic worlds)"; the SHAP prediction is the raw RF output, "uncalibrated probability"; the rule engine is a point score ("2/12 pts"); drift is a level; pattern memory is a similarity.
* **ReasonLine and model evidence never share a panel.** Case view: left = "Explains the OPERATIONAL DECISION", right = "Explains the MODEL" (authorisation-path families, model evidence recorded on the decision, then account intelligence with SHAP / drift / pattern / role).
* **Risk evolution labels say why on the chart.** Ordinal x-axis (events in order, clock under each marker); labels only where score or tier moved, packed greedily into up to four rows by measured width so they never overlap; the table underneath carries the full reason codes.
* **The intervention window gap is shown, not hidden.** `/api/interventions` returns the newest 100 alerts, which the background stream can fill with Tier 1 heads-ups. Investigations / Interventions / Overview merge scenario and customer decisions (tier ≥ 2) with their live intent state and label them "outside alert window" (request filed: `min_tier` param).
* **Bundle:** main 382 kB, 3D network 537 kB (lazy), Cytoscape 2D fallback 543 kB (lazy, loaded only on the 2D toggle). Graph3D declutters LOD labels in screen space (priority: selected, hovered, risk).
* **Screenshots** (`docs/ui_v2/`) are captured headless at 1440 × 900 (tall captures for long pages) and at exactly 390 × 844 via DevTools device metrics for the two phone pages.
