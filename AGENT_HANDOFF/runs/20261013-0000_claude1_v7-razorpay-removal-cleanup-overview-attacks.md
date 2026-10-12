# Run record — claude1 — v7: remove Razorpay, clean up, focused Overview, verify every attack

| Field | Value |
|---|---|
| Agent | Claude 1 (lead), working alone |
| Timestamp | 2026-10-12 23:55 → 2026-10-13 00:40 IST |
| Objective | User prompt v7 (`prompts/09_USER_fix_remove_razorpay_cleanup_overview_2026-10-12.md`): fix the issues; remove Razorpay; small clean-up and neater project files; trim the Overview to what matters; check that injected attacks do what they should |
| Exact Prompt | `prompts/09_USER_fix_remove_razorpay_cleanup_overview_2026-10-12.md` (verbatim) |
| Status | DONE |

## Agent Output / Summary
1. **Razorpay removed end to end.**
   - Backend: `payments/providers.py` keeps only the `PaymentProvider` port plus the simulated rail (`MockPaymentProvider`). Removed the gateway probe, key settings, the `/payment/confirm` and `/payment/fallback-mock` routes, `confirm_razorpay` / `fallback_mock`, and `PaymentInfo.key_id`. `/api/health` reports `payment_provider: "mock"`, "Simulated payment rail (no real money)".
   - Frontend: removed the Checkout script loader, gateway banners and retry flows, plus the Razorpay labels in Assessment, Shell, Health, Governance, Record and Pay.
   - Config and docs: `.env.example` now holds only Vigil settings. The `-Mock` / `--mock` flag was removed from the run scripts. README, KNOWN_LIMITATIONS, REAL_WORLD_POSITIONING, TARGET_ARCHITECTURE and DEMO_SCRIPT were updated.
   - The local, git-ignored `.env` (Razorpay keys only, copied from PRIMA, whose own `.env` is untouched) was deleted.
   - Test `test_razorpay_signature_verification` was replaced by `test_simulated_payment_rail_is_the_only_provider`.
2. **Attack verification.** All 11 injectable patterns were driven through the live API exactly as Test inputs does (reset → inject → evaluation). Script: scratchpad `attack_check.py`. Result: every pattern detected, **0 false positives in every run**, and **every injected mule account surfaced** (early warning or flagged).
   - Before the fix, fully flagged: fan-in, fan-out, cross-channel, shared device (5/5), behavioural drift, volume spike, smurfing, dormant.
   - Partial: money-mule network 3/4, circular ring 3/4, velocity chain 3/5.
3. **Fix — circular ring 3/4 → 4/4** (`intel/stream.py::_rw`). The ring's originator pays out first and is paid back last, so it shows only the circular rule (RingWatch 0.25), not pass-through or a fast chain, and never reached the structural route (≥ 0.40). A closed loop through ≥ 2 other accounts now counts as structural evidence on its own, still requiring ≥ 2 independent intel families. A refund (A → B → A) does not qualify. Verified live: 4/4, 0 false positives.
4. **Not changed, by design.** The head and tail of the velocity chain, and the downstream account in the money-mule network, stay at early warning. Their only network evidence is the fast-chain rule (0.15), which also matches a victim or ordinary customer who receives money and pays within 30 minutes. Promoting it would re-open the victim false positives consensus-v2.2 closed. Documented in DEMO_SCRIPT "Honesty points".
5. **Overview trimmed** from 7 sections / ~17 cards to 7 cards:
   - KPI strip: accounts at risk, open interventions, passed without friction, decision latency, last detection run (mules caught / injected), postings.
   - Network with edge filter, beside Needs attention.
   - Why accounts are flagged: SHAP drivers, detector families, compact last-run card with *Show in network* and *All runs*.
   - Transaction traffic.

   What moved: detection-performance charts (duplicates of LiveStatsCharts) and pattern memory → Detection; the full account scoring table → Detection (replacing the 60-row scroll box); live activity streams → Network. The accounts-at-risk, payments-protected and decisions-by-tier cards were folded into the KPI strip.
6. **Project files neater.**
   - `docs/` now holds only the current documents plus `docs/screenshots/` (current set).
   - Superseded plans, audits, early agent prompts, earlier screenshot generations and reference images moved to `docs/archive/` (`git mv`, with an index README).
   - Stale paths were updated in code comments and handoff files.
   - Removed CSS for the deleted cards.

## Files Changed
- Backend: `backend/vigil/{payments/providers.py,settings.py,app.py,contracts.py,api/routes.py,api/views.py,engine/lifecycle.py,intel/stream.py}`, `backend/tests/{conftest.py,test_vigil_api.py,test_intel_degrade.py}`.
- Frontend: `frontend/src/{api/client.ts,api/types.ts,components/{CustomerDevice,Assessment,Shell,OverviewAnalytics,live/AttackResults}.tsx,pages/{OverviewPage,DetectionPage,NetworkPage,HealthPage,GovernancePage,RecordPage,PayPage}.tsx,styles/v5.css}`.
- Root and docs: `.env.example`, `run_demo.{ps1,sh}`, `README.md`, `docs/**`, `AGENT_HANDOFF/**`.

## Tests Run / Test Results
- `tsc --noEmit` = 0; `vite build` green.
- Backend: full suite **330/330 pass** (includes the ambient "no ordinary customer flagged" invariant).
- Live attack check: 11/11 patterns detected, 0 false positives, 0 injected accounts unseen. Circular ring re-run after the fix: 4/4.
- Playwright route sweep at 1440×900: Overview, Payments, Network, Detection, Cases, Interventions, Governance, Health, trusted contact. 0 console errors, 0 API errors.

## Screenshots / Artifacts
`docs/screenshots/01…09_*.png`.

## Decisions Made
- Kept the provider port (the architecture point: Vigil decides before any rail is called) with only the simulated rail.
- Overview = "what needs action now, and why"; analysis lives on Detection and Network.

## Remaining Work
Before the demo: Test inputs → Reset demo world.

## Git Commit / Diff Reference
See the commit that adds this record.
