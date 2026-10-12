# Prompt for CURSOR — small, safe tasks (copy everything below)

Project: Vigil (PRIMA) at `C:\Users\KausikGH\Documents\Projects\Fraud Detection`. Read `AGENT_HANDOFF/STATE.md` first.
You do **small, bounded, low-risk** work only. No architecture, no risk formulas, no schema, no API changes.

## FILES YOU MAY EDIT
- `README.md` (wording, formatting only — keep every command accurate)
- `frontend/src/components/ui/**` (create small presentational components: Badge, Tooltip, Spinner, EmptyState, ErrorBanner)
- `frontend/src/styles/polish.css` (create; imported last)
- `frontend/src/lib/format.ts` (formatting helpers only, keep existing exports' behaviour)

## FILES YOU MUST NOT EDIT
Everything in `backend/`, `config/`, `frontend/src/api/**`, `frontend/src/App.tsx`, page logic in `frontend/src/pages/**` (Claude 3 owns pages).

## TASKS (each independent; do any subset)
1. Accessible labels: every icon-only button gets `aria-label`; focus-visible ring in `polish.css`.
2. `formatINR` Indian grouping check (₹1,20,000 / ₹5,61,600); add `formatPaiseShort` (₹1.2L, ₹45K) if absent.
3. `Spinner`, `EmptyState`, `ErrorBanner({code,message})` components.
4. README: fix typos, ensure Quick Start matches `run_demo.ps1` output.
5. Reduce-motion: `@media (prefers-reduced-motion: reduce)` disables transitions in `polish.css`.

## INPUT CONTRACT
Money integer paise; dates ISO `Z`. Existing CSS tokens in `frontend/src/styles/tokens.css` (use `var(--…)`, no raw hex).

## TEST COMMAND
`cd frontend; npm run build`

## DEFINITION OF DONE
Build passes; no visual regressions on `/`, `/pay`, `/network`, `/contact/arjun`; short entry in `AGENT_HANDOFF/STATE.md`.
