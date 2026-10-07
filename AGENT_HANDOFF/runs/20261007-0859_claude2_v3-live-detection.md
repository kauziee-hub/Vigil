# Run record — claude2 — v3 live-detection

| Field | Value |
|---|---|
| Agent | claude2 (subagent launched by Claude 1, isolated git worktree) |
| Timestamp | launched 2026-10-07 08:59 IST |
| Objective | Live detection streaming (per-posting scoring, status events, adaptive model-evidence threshold, world-v3 revalidation) |
| Exact Prompt | Message sent: "Your complete, binding instructions are in this file — read it in full first and follow it exactly: AGENT_HANDOFF/prompts/v3_claude2_live_detection.md … baseline commit 9bbd08e. Work only in your git worktree, commit after every milestone, and end with the return format the file specifies." Full prompt: prompts/v3_claude2_live_detection.md (commit 9bbd08e). |
| Status | INTERRUPTED — Claude 1 session restart ~09:30 IST (3rd restart); no final report. All work was committed (milestone rule held); nothing uncommitted. |

## Agent Output / Summary
No final report (killed by the session restart). Recovered from git by Claude 1 on resume (09:35):
- `dc5f093` 09:08 intel3: live detection stream (hook listener, TxScored / AccountStatusChange, status_map, adaptive threshold skeleton); faster numpy GAT segment reductions
- `cf801bb` 09:12 intel3: live status rule + adaptive threshold step as pure functions; `ml/eval_live_status.py` picks the initial threshold on validation worlds (0.85)
- `83f85c5` 09:18 intel3: tests for the live stream (contract shapes, latency, precedence, adaptive threshold, ambient); early warning needs the EW detector or ≥ 2 families
- `fd612e5` 09:18 merge of main (world v3, `d3bc3d3`) — M4 had just started; no M4 fix was committed and no file was written after 09:18.

## Files Changed
`backend/vigil/intel/**` (stream.py et al.), `backend/ml/eval_live_status.py`, `backend/tests/test_intel_stream*.py` (see commits above).

## Tests Run / Test Results
Not reported. Known from the lead (09:17): 13 intel tests fail on world v3 (M4 scope).

## Screenshots / Artifacts
None returned.

## Problems Found
World v3 shifts feature distributions; 13 intel tests fail on it (seeded-world quiet test, s2 ≥3 families, 10 per-attack corroboration, roles ordinary-payer, intel half of ambient routine test).

## Decisions Made
Initial adaptive model-evidence threshold 0.85 chosen on validation worlds (per commit message).

## Remaining Work
M4 (revalidate + fix on world v3) entirely; confirm M1–M3/M5 budgets on world v3; final report → v3 run 2.

## Git Commit / Diff Reference
Base: 9bbd08e. Branch: `claude2/v3-run1-wip` @ `fd612e5` (renamed from the worktree branch by Claude 1 on recovery).

## Mid-run messages from Claude 1
1. (2026-10-07 09:17) "Lead: world v3 is on main (commit d3bc3d3) — start your M4 … 553 accounts, ~31k postings, anchor-relative; ambient person-to-merchant only, 3 s, routine-preserving (merchants up to 1.3x); RingWatch fan-out = first-time recipients, smurfing = ₹8,000–₹9,999 band (policy 2026.10.07-v3.1). Your intel tests currently FAIL on world v3 (13): seeded-world quiet test (fuel.io.baner, bakery.brownbread), s2 ≥3 families, all 10 per-attack corroboration tests, roles ordinary-payer test, intel half of the ambient routine test (kirana.patil + 6 people). Fixing these honestly is part of M4 … Do not edit sim/ or tests/test_vigil_*.py."
