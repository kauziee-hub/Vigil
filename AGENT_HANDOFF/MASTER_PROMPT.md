# MASTER PROMPT (index)

The user's prompts, verbatim, in order. Later prompts override earlier ones where they conflict.

| # | Date | File | Summary |
|---|---|---|---|
| v1 | 2026-10-06 | `prompts/00_MASTER_PROMPT_v1_build.md` | Build one Vigil MVP from the mule-detector + PRIMA prototypes (architecture, lifecycle, risk engine, scenarios, docs). |
| v2 | 2026-10-06 | `prompts/01_MASTER_PROMPT_v2_platform.md` | Institutional-grade redesign; restore mule intelligence (RF/GNN/SHAP/drift/pattern memory/roles, 10 attacks); 3D graph; Decision Replay, counterfactuals, provenance, shadow mode, governance; systematic agent ledger. |
| v2.r | 2026-10-06 22:59 | `prompts/02_USER_resume_2026-10-06_2259.md` | "continue from here" after a session restart — continue v2 unchanged; relaunch the killed agents. |
| v2.r2 | 2026-10-07 ~01:00 | `prompts/03_USER_resume_2026-10-07_0100.md` | "CONTINUE IMPLEMENTATION" after a second session restart — continue v2 unchanged; recover run-2 WIP, relaunch agents as run 3. |
| v3 | 2026-10-07 | `prompts/04_USER_refined_mule_repo_2026-10-07.md` | Refined money-mule repo (Gowtham640/money-mule-detection) sets the UI/3D/analytics bar: live 3D transaction universe, command center, live analytics — bring all into one Vigil. Plan: `docs/archive/plans/V3_LIVE_PLATFORM_PLAN.md`. |
| v3.r | 2026-10-07 09:33 | `prompts/05_USER_continue_2026-10-07_0933.md` | "continue" after the 3rd session restart — continue v3 unchanged; relaunch the killed v3 agents. |
| v4 | 2026-10-09 00:13 | `prompts/06_USER_professional_ui_2026-10-09.md` | Not the green UI — professional, mature, neat; fully functional, nothing fake. |
| v5 | 2026-10-12 21:28 | `prompts/07_USER_reference_ui_final_demo_2026-10-12.md` | UI like two reference images (light, soft cards); all PRIMA + mule features ordered by priority; SHAP; minimal test inputs instead of a simulation panel; end-to-end for tomorrow's final demo. |
| v6 | 2026-10-12 | `prompts/08_USER_logo_iphone_graph_overview_push_2026-10-12.md` | Logo + wordmark; iPhone-style payment device; graph edge filters / scale; re-architect Overview with everything (validated); push to github.com/kauziee-hub/Vigil. |
| v7 | 2026-10-12 | `prompts/09_USER_fix_remove_razorpay_cleanup_overview_2026-10-12.md` | Fix the attack-detection miss; remove Razorpay entirely; small clean-up / neater project files; trim Overview to what matters; verify injected attacks do what they should. |
| v8 | 2026-10-13 00:50 | `prompts/10_USER_functional_guide_overview_watchlist_2026-10-13.md` | Learn every screen; Overview = live activity only, much bigger network, transactions + account creations + close monitoring; self-explanatory Detection charts; beginner functional guide with screenshots. |
| plan 10 | 2026-10-13 | `prompts/10_OVERVIEW_V10_MASTER_PLAN.md` | Overview v10 master plan (P0–P10): geo + channels + onboarding cohort, money map (flat + globe), live tape + connections, mule pipeline, channel chart, Gemini Copilot (incidents, briefs, chat), extras. Written by the user. |
| v9 | 2026-10-13 | `prompts/11_USER_implement_v10_plan_update_guide_2026-10-13.md` | Implement plan 10 fully, adequately tested, fintech-expert quality; then update the functional guide with every new feature and check nothing in the project is missing from it. |
| v11 | 2026-10-13 | `prompts/12_USER_vigilance_map_guides_gemini_2026-10-13.md` | Rename Copilot to Vigilance: a chat-box assistant that classifies what is happening ("HIGH · …"), coins alerts itself and leads to the bank's next-step procedures; better India map; refine the functional guide in the Claude-doc style with every new feature; a full beginner-to-expert technical guide in parallel; make the free Gemini key (`GEMINI_API` in `.env`) work and test it. |
| v11.r | 2026-10-13 | `prompts/13_USER_continue_vigilance_layout_fintech_agent_2026-10-13.md` | Continue v11 here; Overview orientation: Vigilance on top of everything, then live network (left) beside live transactions (right), then map (left) beside needs attention (right); the briefing must read like a fintech agent, not "open questions". |
| v11.r2 | 2026-10-13 | `prompts/14_USER_continue_guides_2026-10-13.md` | Continue: finish the functional guide (Claude Doc) and the technical guide (complete, then as a Claude Doc) as planned. |

Role prompts issued to agents are stored inside each run record in `runs/` (and the latest copies in `prompts/`).
