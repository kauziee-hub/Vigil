# UI Current State (v1) — audit before the platform redesign

Captured 2026-10-06 22:35 IST from the running app (Playwright, 1440×900, dark theme, deterministic reset then Acts 1–5). Screenshots: `docs/ui_current/NN_*.png`. Nothing was changed before capture.

Overall verdict: **functionally correct, visually a well-behaved hackathon dashboard.** The data flows are real and should survive; the information architecture, density and visual language do not meet "institutional financial intelligence platform". The mule-detection layer (RF/GNN/SHAP/drift/roles/pattern memory/10 attacks) is absent from the UI entirely.

Cross-cutting problems (apply to every page):
* **Template look:** uniform rounded cards with equal padding, KPI tiles with big numbers, soft shadows — the generic SaaS/admin aesthetic the brief rejects.
* **Colour is decorative, not semantic:** five tier colours + five dimension colours + role colours compete. There is no single NORMAL / WATCH / HIGH RISK / CRITICAL / HELD / CONFIRMED FRAUD scale.
* **Raw developer output leaks into the UI:** `key=value` evidence strings, JSON-ish timestamps, a raw feature table (`window_hours 72`, `role null`, `labelled false`).
* **No provenance:** signals don't show source, observed-at, freshness, version, status.
* **Navigation is demo-shaped** (Command center / Pay / Investigate / Network / Where it sits), not operations-shaped.
* **Brand line** "PRIMA pre-commit engine" wraps at <1250 px; the top bar carries little operational status.

---

## 01 / 07 / 18 — Command center (fresh / after ring / after all acts) · `01_overview_fresh.png`, `07_…`, `18_…`

| | |
|---|---|
| Purpose | Demo control + headline metrics + live decision feed + RingWatch list. |
| What works | Event-driven refresh (no polling); deterministic scenarios with START/PAUSE/RESET/EXPLAIN; live feed links to investigations; ledger-total integrity line. |
| Confusing | Mixes three jobs (operations overview, demo control, architecture explainer). Lifecycle strip is a static diagram occupying prime space. "Challenges overturned 0/3" unexplained. KPI "Held ₹6.07L" without who/why. |
| Duplicated | Scenario controls duplicated on Network page; lifecycle explanation duplicated on About. |
| Generic / template-like | 8 identical KPI tiles with oversized numbers; equal-weight cards; bright blue primary buttons on every scenario. |
| Not institutional | Scenario cards dominate the operational view; feed rows have a **layout bug** (tier chip overlaps the sender/recipient text — 64 px column too narrow); no time-window context on KPIs. |
| Survive | Metric set (rate, intents, interventions by tier, held value, traced value, latency); live decision feed concept; RingWatch table; ledger-integrity line. |
| Redesign | Becomes **OVERVIEW**: dense status strip, "requires attention" queue, value-at-risk, emerging networks (with compact network thumbnail), detector agreement, active interventions. Scenario control moves to **SCENARIO LAB**; lifecycle diagram moves to Governance/About. |

## 02 / 03 / 04 / 05 / 10 / 12 — Pay (form, T0 receipt, T2, cancelled, T3, T4) · `02…05`, `10`, `12`

| | |
|---|---|
| Purpose | Customer-side pre-commit experience + bank side panel. |
| What works | The four-question intervention panel (RISK LEVEL / WHAT CHANGED / WHY / ACTION) reads well; T4 appears live when a scenario submits; scoped-hold balance shown; contact responses appear live; DEMO PAYMENT labelling honest; Razorpay fallback. |
| Confusing | The phone and the bank panel are equal weight — unclear who the audience is. "Quick fill (demo acts)" is demo scaffolding in the product surface. Intent lifecycle list is plain text. |
| Duplicated | Contribution panel is the same component as Investigation. |
| Generic | Phone frame with saturated blue header; large rounded inputs. |
| Not institutional | The bank side doesn't show the assessment the brief requires (sender / recipient / relationship / device / behaviour / network / external / journey / context / decision as a structured case header). |
| Survive | Customer intervention copy and four blocks; payment-provider fallback; live updates. |
| Redesign | Becomes **TRANSACTION GUARD**: left = customer device (kept simple); right = structured pre-commit assessment grid with one row per signal family + provenance, then decision, intervention, and after payment the provider/ledger/monitoring outcome. |

## 06 / 08 / 09 — Network (pre-ring, ring selected, after label) · `06…09`

| | |
|---|---|
| Purpose | RingWatch evidence + TaintTrace + mule-ring injection. |
| What works | Capped suspicious subgraph (17 nodes), dagre left→right story is clear; confirming a scam re-colours source and traced edges; LIBR vs pro-rata side by side with conservation check. |
| Confusing | Right panel is a long scroll: signals → postings → trace; "Confirm scam" buttons below the fold. Role legend colours vs risk colours ambiguous. |
| Generic | Grey default nodes, flat 2D — reads as a diagram, not an intelligence tool. |
| Not institutional | No graph modes (risk / taint / roles / model scores), no time replay, no detector view per node, no node cap control. |
| Survive | Backend suspicious-subgraph selection and aggregation; label → TaintTrace flow; MoneyTrace component data. |
| Redesign | **NETWORK INTELLIGENCE**: WebGL 3D with frozen precomputed layout + 2D fallback, modes (MONEY FLOW, RISK, TAINT, MULE ROLES, GNN, RULE, ML), time/attack replay, investigation drawer with detector consensus. |

## 11 / 13 — Trusted contact (idle, alert) · `11_contact_idle.png`, `13_contact_alert.png`

| | |
|---|---|
| Purpose | Arjun's phone: CircuitBreaker alert and response. |
| What works | Live push; facts not accusations; three large actions; correct mobile width. |
| Confusing | Nothing major. |
| Survive | Almost entirely. Light visual alignment with the new design system only. |

## 14 / 15 — Investigate (list, T4 detail) · `14…15`

| | |
|---|---|
| Purpose | Bank analyst case view. |
| What works | Intervention queue; release/reject; contribution by dimension with every rule; journey timeline; scoped hold + CircuitBreaker status; tabs for trace/actions/customer/audit. |
| Confusing | Contribution column is very tall (all signal cards expanded); evidence shown as raw `key=value` strings and ISO timestamps; recipient network panel nearly empty for new accounts; raw feature dump table. |
| Duplicated | Customer/Audit tabs duplicate the Decision page. |
| Not institutional | No case header (case id, status, owner, SLA), no provenance, no replay, no counterfactual table, no model evidence, no risk-over-time. |
| Survive | Data bundle (`/api/investigate`), queue, actions, timeline concept. |
| Redesign | **INVESTIGATIONS** (account/case deep dive incl. detectors, SHAP, drift, roles, pattern memory, risk evolution) + **INTERVENTIONS** (queue of challenges/holds/CircuitBreakers with SLAs and actions). |

## 16 — Decision three views · `16_decision_three_views.png`

| | |
|---|---|
| Purpose | Act 5: customer / analyst / audit renderings. |
| What works | Same record, three audiences, deterministic; integrity hash. |
| Not institutional | Raw JSON dump as the audit view; no "view raw record" vs structured record distinction; no replay. |
| Survive | Concept and data. |
| Redesign | Part of **GOVERNANCE / AUDIT**: structured decision record (inputs, provenance, model versions, policy version, thresholds, reason codes, action, operator action, payment result) + VIEW RAW RECORD + REPLAY DECISION. |

## 17 — Where it sits · `17_about.png`

| | |
|---|---|
| Purpose | Positioning vs RBI/RBIH/DPIP/NPCI/I4C. |
| What works | Honest, non-overclaiming copy. |
| Redesign | Fold into **GOVERNANCE** (deployment context, shadow-mode adoption story, policy versions) — not a top-level nav item. |

## 19 — Light theme · `19_overview_light_theme.png`

Works but has no distinct institutional character. Proposal: dark navy shell as default, light reading surfaces optional.

---

## What must survive the redesign (functional, do not rebuild)

Intent lifecycle + realtime push; four-question customer intervention; scoped hold & CircuitBreaker flow; trusted-contact page; deterministic scenarios + reset; label → TaintTrace with LIBR/pro-rata conservation; investigation data bundle; ReasonLine customer/analyst/audit; Razorpay fallback; ledger-integrity check.

## What is missing entirely (from the original mule project + v2 brief)

RF / GNN / rule-engine outputs per account, detector consensus, SHAP, behavioural drift, early warning, pattern-signature memory, role classification, 10 attack patterns, model metrics & validation, 3D graph with modes and replay, Decision Replay, counterfactual ladder, evidence provenance, shadow mode, risk-over-time, governance views, system health page.
