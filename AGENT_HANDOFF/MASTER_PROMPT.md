# MASTER PROMPT (index)

The user's prompts, verbatim, in order. Later prompts override earlier ones where they conflict.

| # | Date | File | Summary |
|---|---|---|---|
| v1 | 2026-10-06 | `prompts/00_MASTER_PROMPT_v1_build.md` | Build one Vigil MVP from the mule-detector + PRIMA prototypes (architecture, lifecycle, risk engine, scenarios, docs). |
| v2 | 2026-10-06 | `prompts/01_MASTER_PROMPT_v2_platform.md` | Institutional-grade redesign; restore mule intelligence (RF/GNN/SHAP/drift/pattern memory/roles, 10 attacks); 3D graph; Decision Replay, counterfactuals, provenance, shadow mode, governance; systematic agent ledger. |
| v2.r | 2026-10-06 22:59 | `prompts/02_USER_resume_2026-10-06_2259.md` | "continue from here" after a session restart — continue v2 unchanged; relaunch the killed agents. |
| v2.r2 | 2026-10-07 ~01:00 | `prompts/03_USER_resume_2026-10-07_0100.md` | "CONTINUE IMPLEMENTATION" after a second session restart — continue v2 unchanged; recover run-2 WIP, relaunch agents as run 3. |

Role prompts issued to agents are stored inside each run record in `runs/` (and the latest copies in `prompts/`).
