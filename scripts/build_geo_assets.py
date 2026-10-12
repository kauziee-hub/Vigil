"""Build the bundled map asset for the Overview money map (overview-v10 P3).

Input  (downloaded once into the git-ignored data/geo_raw/, public domain, Natural Earth v5.x):
  ne_10m_admin_0_countries_ind.geojson  — countries, India point of view (boundary as depicted by India)
  ne_50m_admin_1_states_provinces.geojson — first-order subdivisions (only India's are used)
Output (committed): frontend/src/assets/geo/india_pov.geo.json — simplified, quantised GeoJSON.

    python scripts/build_geo_assets.py

India and its neighbourhood keep ~3 km detail; distant countries are simplified harder (they are only
grey context for international flows). Deterministic: same input → byte-identical output.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "geo_raw"
OUT = ROOT / "frontend" / "src" / "assets" / "geo" / "india_pov.geo.json"

NEAR = (55.0, -2.0, 105.0, 42.0)          # lon/lat box: India, neighbours, Gulf edge, SE Asia edge
TOL_NEAR, TOL_FAR, TOL_STATE = 0.03, 0.4, 0.035
MIN_AREA_NEAR, MIN_AREA_FAR = 0.01, 2.5   # square degrees; drops specks


def _dp(points: list[list[float]], tol: float) -> list[list[float]]:
    """Douglas–Peucker (iterative) on one open polyline."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-12
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / norm
            if d > best:
                best, idx = d, i
        if best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def _area(ring: list[list[float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2


def _ring(ring: list[list[float]], tol: float, min_area: float) -> list[list[float]] | None:
    pts = _dp(ring[:-1], tol)
    if len(pts) < 3 and min_area == 0.0:          # tiny state / UT (Chandigarh): keep its own outline
        pts = _dp(ring[:-1], tol / 20)
    if len(pts) < 3:
        return None
    pts = [[round(x, 3), round(y, 3)] for x, y in pts]
    pts.append(pts[0])
    return pts if _area(pts) >= min_area else None


def _polys(geom: dict) -> list:
    return [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]


def _near(geom: dict) -> bool:
    x0, y0, x1, y1 = NEAR
    for poly in _polys(geom):
        for x, y in poly[0]:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return True
    return False


def _simplify(geom: dict, tol: float, min_area: float) -> dict | None:
    out = []
    for poly in _polys(geom):
        outer = _ring(poly[0], tol, min_area)
        if outer is None:
            continue
        holes = [h for h in (_ring(r, tol, min_area) for r in poly[1:]) if h]
        out.append([outer, *holes])
    if not out:
        return None
    return {"type": "MultiPolygon", "coordinates": out}


def main() -> None:
    countries = json.loads((RAW / "ne_10m_admin_0_countries_ind.geojson").read_text(encoding="utf-8"))
    states = json.loads((RAW / "ne_50m_admin_1_states_provinces.geojson").read_text(encoding="utf-8"))
    feats = []
    for f in sorted(countries["features"], key=lambda f: f["properties"]["ADM0_A3"]):
        p = f["properties"]
        iso = p["ADM0_A3"]
        near = iso == "IND" or _near(f["geometry"])
        g = _simplify(f["geometry"], TOL_NEAR if near else TOL_FAR, MIN_AREA_NEAR if near else MIN_AREA_FAR)
        if g:
            feats.append({"type": "Feature", "properties": {"layer": "country", "iso": iso, "name": p["NAME"],
                                                            "near": near}, "geometry": g})
    for f in sorted((f for f in states["features"] if f["properties"]["adm0_a3"] == "IND"),
                    key=lambda f: f["properties"]["name"]):
        g = _simplify(f["geometry"], TOL_STATE, 0.0)
        if g:
            feats.append({"type": "Feature", "properties": {"layer": "state", "name": f["properties"]["name"]},
                          "geometry": g})
    doc = {"type": "FeatureCollection",
           "source": "Natural Earth v5 (public domain): admin-0 countries, India point of view (10m); "
                     "admin-1 states (50m). Simplified by scripts/build_geo_assets.py.",
           "features": feats}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    n_c = sum(1 for f in feats if f["properties"]["layer"] == "country")
    print(f"wrote {OUT.relative_to(ROOT)}: {OUT.stat().st_size // 1024} KB, {n_c} countries, {len(feats) - n_c} states")


if __name__ == "__main__":
    main()
