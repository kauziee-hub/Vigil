# Prompt for CURSOR — polish only (v2). Copy everything below into Cursor.

Project: Vigil (PRIMA), `C:\Users\KausikGH\Documents\Projects\Fraud Detection` (git). Use branch `cursor/polish-<n>`.
WAIT until Claude 3's redesign is merged to `main` (check `AGENT_HANDOFF/AGENT_LEDGER.md` for a "claude3 … MERGED" row) — then polish what exists.

Read first: `docs/DESIGN_SYSTEM.md` (Claude 3), `docs/FINAL_PARALLEL_PLAN.md` §2 (status colour scale) and §3 (ownership).

## You may edit
`frontend/src/styles/polish.css` (create; imported last), `frontend/src/components/ui/**` (small presentational components), and purely presentational JSX attributes (aria-labels, titles, className) in `frontend/src/pages/**`.
## You must NOT touch
database, risk logic, model logic, transaction lifecycle, `frontend/src/api/**`, anything in `backend/` or `config/`, data flow in pages.

## Tasks
1. Responsive: 1280 / 1440 / 1920 widths; tables scroll horizontally inside panels, never the page; /contact and /pay at 360–390 px.
2. Alignment & spacing: consistent 4/8 px grid, numeric columns right-aligned with tabular figures, consistent panel header heights.
3. Labels & tooltips: every abbreviation (LIBR, T0–T4, PR-AUC, SHAP, GAT) has a tooltip; units on every number (₹, ms, %, h).
4. Icons: consistent single icon set (no emoji in the bank UI; the trusted-contact page may keep simple symbols).
5. Loading / empty / error states: skeleton rows for tables, explicit "not yet available" for 404 endpoints, ErrorBanner showing `{code, message}`.
6. Accessibility: aria-labels on icon buttons, visible focus ring, contrast ≥ 4.5:1 for text on the navy shell, `prefers-reduced-motion` honoured.
7. Formatting: Indian digit grouping (₹5,61,600), relative + absolute times, consistent date format.
8. Dead imports and unused components removal (frontend only); minor visual bugs.

## Test
`cd frontend; npm run build` must pass. Visually check /, /guard, /network, /investigations, /interventions, /governance, /lab, /health, /contact/arjun.

## Return format (paste back to the operator; saved verbatim to AGENT_HANDOFF/runs/)
Branch · Commit · Files changed · Before/after notes per page · Build output · Remaining issues.
