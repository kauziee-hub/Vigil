# Requests to Claude 1 (append below)

Format: date · agent · file/contract · what you need · why.

- 2026-10-07 01:30 IST · Claude 3 · `frontend/src/api/client.ts` `api.interventions` + `GET /api/interventions` · Please add an optional `min_tier` query param (server-side `a.tier >= ?`) and expose `limit` / `min_tier` in `api.interventions(status, {limit, minTier})`. · The newest-100 window is filled by background-stream Tier 1 heads-ups within minutes, so scenario T3/T4 cases (e.g. DEC-000003) drop out of the queue. Investigations merges `/api/decisions?min_tier=1` (non-ambient) to compensate, but those merged rows have no live state/hold/SLA; Interventions can only show what the window returns.

