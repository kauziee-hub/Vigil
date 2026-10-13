# Overview v10 — P0 baseline (2026-10-13, branch `overview-v10`, on top of `278541c`)

Captured before any v10 behaviour change. Every later phase is compared with these numbers.

| Gate | Result |
|---|---|
| pytest (full suite) | **337 passed**, 0 failed (≈ 35 min on the dev laptop, server + browser running) |
| world digest (new `tests/test_world_digest.py`) | passes; 30,983 pre-existing postings, 553 accounts |
| tsc --noEmit + vite build | green; main `index` 460.03 kB (138.39 kB gzip), `OverviewPage` 17.41 kB |
| smoke (`scripts/smoke_demo.py`) | **8/8 PASS** |
| risk-policy version | `2026.10.07-v3.1+9ba3476c1d` |

## World digest (fixed anchor 2026-10-01T06:00:00Z)

- transactions `(id, ts, sender, recipient, amount, kind, channel, device_id)`: `698bb4f7ea9483957644bce16983282c56650f7b5fbbb445a5cb7297052135e4` (30,983 rows)
- accounts `(id, display_name, kind, primary_device, opened_at, persona, daily_limit, is_demo, seed_role)`: `736b33c44c7fde4fb972f387a2225ff9fc333777bcff2734b91bef8f359f4c0f` (553 rows)

v10 rows (`source='cohort_v10'`, cohort accounts, `ext:intl-wire`) are excluded by the test, so this digest must stay identical through every phase.

## 11-pattern attack check (live server, reset → inject → graded run)

| Pattern | Detected | Flagged / injected | False positives |
|---|---|---|---|
| Money-mule network (s2) | Y | 3 / 4 (rahul.m at early warning) | 0 |
| Fan-in | Y | 1 / 1 | 0 |
| Fan-out | Y | 1 / 1 | 0 |
| Circular ring | Y | 4 / 4 | 0 |
| Velocity chain | Y | 3 / 5 (head + tail at early warning) | 0 |
| Cross-channel burst | Y | 1 / 1 | 0 |
| Shared device cluster | Y | 5 / 5 | 0 |
| Behavioural drift | Y | 1 / 1 | 0 |
| Early volume spike | Y | 1 / 1 | 0 |
| Smurfing | Y | 1 / 1 | 0 |
| Dormant activation | Y | 1 / 1 | 0 |

**11/11 detected, 0 false positives.**

## Notes

- Screenshot: `docs/screenshots/pre_v10_overview.png` (1440 px wide).
- The Playwright profile had a saved 33 % zoom for `localhost`; screenshots from now on use `http://127.0.0.1:8000`.
- `data/` is git-ignored, so the plan's `data/geo/*.json` reference data lives in `backend/vigil/geo/cities.json` instead (recorded in the ledger).
