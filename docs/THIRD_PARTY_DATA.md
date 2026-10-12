# Third-party data and libraries added in overview-v10

## Map boundaries — Natural Earth (public domain)

| File in the repo | Source | Licence |
|---|---|---|
| `frontend/src/assets/geo/india_pov.geo.json` (325 KB) | Natural Earth v5 vector data, from `github.com/nvkelso/natural-earth-vector` (`geojson/`): **`ne_10m_admin_0_countries_ind.geojson`** (admin-0 countries, **India point of view**) and `ne_50m_admin_1_states_provinces.geojson` (India's 36 states and union territories only) | Public domain ("Natural Earth is in the public domain"; no permission needed, attribution appreciated) |

**India's boundary.** Natural Earth publishes "point of view" editions of its admin-0 layer that depict boundaries as a given country's government does. The Overview map uses the **India point-of-view** edition, so India's international boundary (Jammu & Kashmir, Ladakh, Arunachal Pradesh) is drawn as depicted by India. The State layer is drawn only inside that outline. This is a prototype on synthetic data; a production deployment should use a Survey of India–approved boundary dataset and follow the Geospatial Information Regulation requirements in force.

**How the bundled file is made.** `python scripts/build_geo_assets.py` reads the two raw downloads from the git-ignored `data/geo_raw/`, keeps India and its neighbourhood at about 3 km detail, simplifies distant countries harder (they are only grey context for international flows), quantises coordinates to 3 decimals and writes the bundled file. The script is deterministic: same input, byte-identical output. The raw downloads (13.2 MB and 2.3 MB) are not committed.

**Runtime.** The map data is bundled into the Overview chunk: no tile server, no CDN, works offline.

## City and ATM reference points (synthetic)

`backend/vigil/geo/cities.json`: 22 Indian city centres and 4 neutral foreign destinations (Dubai, Singapore, London, Hong Kong) as approximate WGS-84 city-centre coordinates. ATM terminals are **generated** (6–10 per city, deterministic from a hash of city and index, within 6 km of the centre and inside a land sector for coastal cities). All account homes, device positions and ATM uses are SIMULATED and labelled with their basis and accuracy in the UI.

## npm packages

| Package | Version | Licence | Used for |
|---|---|---|---|
| `d3-geo` | 3.1.1 | ISC | Mercator / equirectangular projections and path generation for the money map and the globe texture |
| `d3-array` | (dependency of d3-geo) | ISC | — |
| `@types/d3-geo` | 3.1.1 (dev) | MIT | TypeScript types |

The plan suggested `d3-zoom` and `topojson-client` as well. They were not needed: zoom / pan is a few lines of pointer handling, and the bundled file is already simplified GeoJSON. This kept the download to what was approved.

## Gemini API (optional, off by default)

The Copilot can call Google's Gemini API (`generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` / `:streamGenerateContent`) over HTTPS with `httpx` (already a pinned dependency). It is used only when `GEMINI_API_KEY` is set in `.env`. Defaults (verified on ai.google.dev on 2026-10-13): `gemini-3.8-flash` (briefings and chat), `gemini-3.1-pro-preview` ("Deep dive"). Use is subject to Google's terms. With no key, nothing leaves the machine.
