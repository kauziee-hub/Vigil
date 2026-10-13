# Run record — v11: Vigilance, Overview orientation, money map, functional + technical guides

- **Agent:** Claude 1 (lead), with one continuation session and background copy agents for the Claude Doc.
- **Prompts:** v11 `prompts/12_USER_vigilance_map_guides_gemini_2026-10-13.md`, v11.r `13_USER_continue_vigilance_layout_fintech_agent_2026-10-13.md`, v11.r2 `14_USER_continue_guides_2026-10-13.md`.
- **Branch:** `overview-v10` (not merged into `main`, not pushed).
- **Date:** 2026-10-13.

## What was asked
Rename the Copilot to **Vigilance** and make it a fintech agent: a chat box that classifies what is happening ("High …"),
raises alerts itself and leads to the bank's next steps; Overview orientation: Vigilance on top, live network | live
transactions, then map | needs attention; a better India map; refine the functional guide in the Claude-doc style with
every new feature and check nothing is missing; a full, teachable technical guide; make the free Gemini key
(`GEMINI_API` in `backend/.env`) work and test it.

## What was done
- **Backend (Vigilance):** `copilot/playbooks.py` (classification, typology, respond-within, four-phase procedures with
  automatic and manual completion; Indian rules cited as illustrative), procedure routes, `get_procedure` /
  `get_str_draft` tools; findings carry `subject` + `situation` (plain sentence in rupees); assessment rewritten
  (`brief.py`: headline, summary, red flags, risk if ignored, recommendation, confidence by model or template; key facts,
  next step, severity by code; ids not in the facts reject a model reply; paise converted; `fast` mode); chat persona as
  a senior fraud / AML analyst ("verdict → Assessment → Do now"); `*_inr` strings in tool results; key names
  `GEMINI_API_KEY` / `GEMINI_API` / `GOOGLE_API_KEY` from `.env` or `backend/.env` (tests set `VIGIL_NO_DOTENV=1`);
  Gemini 3.x `thinkingLevel: low`; 4 tool calls per turn; 429 → offline answer with a note.
- **Fixes:** held-payment recipient read from the bank alert (was the alphabetically last account); coerced-payment red
  flags from the decision's analyst reasons (was the customer's message); **SPA path traversal** fixed (could have served
  `backend/.env`) + `tests/test_spa_path_traversal.py`; offline router matches `str` / `fiu` as whole words.
- **Frontend:** `components/vigilance/Vigilance.tsx` (ranked bar, toasts, one-chat-box dock with alert cards, case view =
  assessment + procedure, Draft STR note, Ask Vigilance buttons), global provider in the Shell (`consoleBus.ts`,
  `lib/vigilance.tsx` page bridge: actions carried to the Overview), `lib/vigilanceActions.ts` (case links whitelisted),
  safer mixed-content `SafeMarkdown`, Overview orientation as requested, money-map overlays (corridors, city card, risky
  arcs with moving dashes, hover, grid, glow, scale), `styles/v11.css`.
- **Docs:** functional guide Claude Doc updated in the continuation session (Overview chapter, new chapter 5 Vigilance,
  renumbering, glossary, honest answers, demo step 9, Pay via; 24 screenshots `docs/guide/img/v11_*`) — only that session
  can open it (`https://claude.ai/code/artifact/bf16f71c-e278-4271-ac55-27e269ca9bac`); technical guide
  `docs/TECHNICAL_GUIDE.md` (23 sections + Appendix A: 37 doc-vs-code differences, 32 possible bugs, 47 Q&As) and its
  Claude Doc `https://claude.ai/code/artifact/046e4edd-7138-4920-bafa-51b816c28a44` (overview tab + 12 tabs, 8 diagrams,
  22 screenshots); README, `.env.example`, DEMO_SCRIPT step 1 + 4, CHANGELOG v11, KNOWN_LIMITATIONS v11.

## Gates
- pytest **381 / 381** (374 + 6 procedures + 1 traversal), full suite on the final backend.
- Frontend checks **20 / 20**; `tsc --noEmit` clean; build green (continuation session).
- Live Gemini (free key) tested end to end: assessments written and validated, chat with tools, STR draft.
- Attack detection unchanged: no detector, threshold, policy or seed file touched in v11 (the backend suite includes the
  live attack runs and the world digest test).

## Honest notes
- The functional-guide Claude Doc cannot be opened from this session; the repo Markdown copy carries a note pointing to it.
- Held-payment / coercion incidents still stay open after the bank decides (Appendix A.2 #5).
- Procedures are illustrative, not legal advice.
