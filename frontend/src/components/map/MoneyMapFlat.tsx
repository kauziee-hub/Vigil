// MONEY MAP (flat) — where money moves, where it turns risky, where it leaves the bank. SIMULATED locations.
// Land: Natural Earth (public domain), India point of view, bundled offline (src/assets/geo, built by
// scripts/build_geo_assets.py). SVG for land / dots / labels, canvas for arcs + moving postings (performance).
// Arc thickness = value, colour = risk of the accounts involved (red = an account is flagged / held / confirmed /
// in a detected ring, amber = early warning); risky arcs glow and carry dashes moving in the direction of the money.
// A particle = one real new posting arriving over the WebSocket. Hovering an arc shows its corridor.
import { geoGraticule, geoMercator, geoPath } from "d3-geo";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import world from "../../assets/geo/india_pov.geo.json";
import type { GeoMap, MapCity, MapCluster } from "../../api/v10";
import { RAIL_LABEL, type Rail } from "../../api/v10";
import { formatPaiseShort } from "../../lib/format";
import type { Selection } from "../../lib/selection";
import type { GeoReference, LivePosting } from "./useMapData";

type Feat = { type: "Feature"; properties: { layer: "country" | "state"; iso?: string; name: string; near?: boolean }; geometry: unknown };
const FEATURES = (world as unknown as { features: Feat[] }).features;
const INDIA = FEATURES.find((f) => f.properties.iso === "IND") as Feat;
const COUNTRIES = FEATURES.filter((f) => f.properties.layer === "country" && f.properties.iso !== "IND");
const STATES = FEATURES.filter((f) => f.properties.layer === "state");

export interface MapLayers { flows: boolean; fraud: boolean; atm: boolean; collection: boolean; labels: boolean }
export const DEFAULT_LAYERS: MapLayers = { flows: true, fraud: true, atm: true, collection: true, labels: true };

const RISK_COLOR = { normal: "rgba(79,214,184,", suspicious: "rgba(240,176,64,", fraud: "rgba(240,82,82," } as const;
const MAX_PARTICLES = 150;

interface T { k: number; x: number; y: number }
interface Particle { from: [number, number]; to: [number, number] | null; t0: number; dur: number; risky: boolean; atm: boolean }
interface ArcGeo { f: GeoMap["flows"][number]; a: [number, number]; c: [number, number]; b: [number, number]; w: number }
const GRATICULE = geoGraticule().step([5, 5]).extent([[55, 0], [105, 42]])();
const RISK_WORD = { normal: "normal", suspicious: "early warning", fraud: "fraud-linked" } as const;

function useSize(ref: React.RefObject<HTMLDivElement>) {
  const [w, setW] = useState(800);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(320, Math.round(el.clientWidth))));
    ro.observe(el);
    setW(Math.max(320, Math.round(el.clientWidth)));
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

const reduceMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function MoneyMapFlat({ data, reference, layers, selected, onSelect, onPosting, height = 470 }: {
  data: GeoMap | null; reference: GeoReference | null; layers: MapLayers; selected: Selection | null;
  onSelect: (s: Selection | null) => void; onPosting: (fn: (p: LivePosting) => void) => () => void; height?: number;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const w = useSize(wrap);
  const h = height;
  const [t, setT] = useState<T>({ k: 1, x: 0, y: 0 });
  const tRef = useRef(t);
  tRef.current = t;
  const [hover, setHover] = useState<{ x: number; y: number; html: React.ReactNode } | null>(null);
  const particles = useRef<Particle[]>([]);
  const arcs = useRef<ArcGeo[]>([]);
  const dirty = useRef(true);

  const proj = useMemo(() => geoMercator().fitExtent([[28, 18], [w - 28, h - 18]], INDIA as never), [w, h]);
  const path = useMemo(() => geoPath(proj), [proj]);
  const land = useMemo(() => ({
    countries: COUNTRIES.map((f) => ({ d: path(f as never) ?? "", near: !!f.properties.near, name: f.properties.name })),
    india: path(INDIA as never) ?? "",
    states: STATES.map((f) => path(f as never) ?? "").join(" "),
    grid: path(GRATICULE as never) ?? "",
  }), [path]);

  const P = useCallback((lng: number, lat: number): [number, number] => {
    const p = proj([lng, lat]) ?? [0, 0];
    const { k, x, y } = tRef.current;
    return [x + k * p[0], y + k * p[1]];
  }, [proj]);
  const pxPerKm = useCallback((lat: number, lng: number) => {
    const a = P(lng, lat), b = P(lng + 0.05, lat);
    return Math.hypot(b[0] - a[0], b[1] - a[1]) / (0.05 * 111.32 * Math.cos((lat * Math.PI) / 180));
  }, [P]);

  // live postings → particles
  useEffect(() => onPosting((p) => {
    if (!p.from || reduceMotion() || document.visibilityState === "hidden") return;
    if (particles.current.length >= MAX_PARTICLES) particles.current.shift();
    particles.current.push({ from: p.from, to: p.to, t0: performance.now(), dur: 1700, risky: p.risky, atm: p.atm });
    dirty.current = true;
  }), [onPosting]);

  useEffect(() => { dirty.current = true; }, [data, layers, selected, t, w]);

  // canvas render loop (arcs, particles, pulses); idles when nothing moves; paused while the tab is hidden
  useEffect(() => {
    let raf = 0;
    const cv = canvas.current;
    if (!cv) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    cv.width = w * dpr; cv.height = h * dpr;
    const ctx = cv.getContext("2d")!;
    const motion = !reduceMotion();
    const maxV = Math.max(1, ...(data?.flows ?? []).map((f) => f.value_paise));
    const edge = (a: [number, number], b: [number, number]): { pt: [number, number]; clipped: boolean } => {
      const m = 16;
      if (b[0] >= m && b[0] <= w - m && b[1] >= m && b[1] <= h - m) return { pt: b, clipped: false };
      let tt = 1;
      const dx = b[0] - a[0], dy = b[1] - a[1];
      if (dx) tt = Math.min(tt, dx > 0 ? (w - m - a[0]) / dx : (m - a[0]) / dx);
      if (dy) tt = Math.min(tt, dy > 0 ? (h - m - a[1]) / dy : (m - a[1]) / dy);
      tt = Math.max(0, tt);
      return { pt: [a[0] + dx * tt, a[1] + dy * tt], clipped: true };
    };
    const ctrl = (a: [number, number], b: [number, number]): [number, number] => {
      const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2, dx = b[0] - a[0], dy = b[1] - a[1];
      return [mx - dy * 0.22, my + dx * 0.22];
    };
    const bez = (a: [number, number], c: [number, number], b: [number, number], s: number): [number, number] =>
      [(1 - s) ** 2 * a[0] + 2 * (1 - s) * s * c[0] + s * s * b[0], (1 - s) ** 2 * a[1] + 2 * (1 - s) * s * c[1] + s * s * b[1]];

    const draw = (now: number) => {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const geo: ArcGeo[] = [];
      let risky = false;
      if (data && layers.flows) {
        // normal flows first (quiet, fading in towards the destination), risky flows on top (glow + moving dashes)
        const ordered = [...data.flows].sort((x, y) => (x.risk === "normal" ? 0 : 1) - (y.risk === "normal" ? 0 : 1));
        for (const f of ordered) {
          if (f.from_lat == null || f.to_lat == null || f.from_city === f.to_city) continue;
          const a = P(f.from_lng, f.from_lat), b0 = P(f.to_lng, f.to_lat);
          const { pt: b, clipped } = edge(a, b0);
          const c = ctrl(a, b);
          const lw = 0.7 + 4.4 * Math.sqrt(f.value_paise / maxV);
          geo.push({ f, a, c, b, w: lw });
          if (f.risk === "normal") {
            const g = ctx.createLinearGradient(a[0], a[1], b[0], b[1]);
            g.addColorStop(0, RISK_COLOR.normal + "0.10)");
            g.addColorStop(1, RISK_COLOR.normal + "0.55)");
            ctx.strokeStyle = g;
            ctx.lineWidth = lw;
            ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.quadraticCurveTo(c[0], c[1], b[0], b[1]); ctx.stroke();
          } else {
            risky = true;
            ctx.save();
            ctx.shadowColor = RISK_COLOR[f.risk] + "0.9)"; ctx.shadowBlur = 10;
            ctx.strokeStyle = RISK_COLOR[f.risk] + "0.55)"; ctx.lineWidth = lw + 1;
            ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.quadraticCurveTo(c[0], c[1], b[0], b[1]); ctx.stroke();
            ctx.restore();
            if (motion) {
              ctx.save();
              ctx.setLineDash([3, 11]); ctx.lineDashOffset = -(now / 45) % 14; ctx.lineCap = "round";
              ctx.strokeStyle = "rgba(255,236,236,0.9)"; ctx.lineWidth = Math.max(1.2, lw * 0.55);
              ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.quadraticCurveTo(c[0], c[1], b[0], b[1]); ctx.stroke();
              ctx.restore();
            }
          }
          if (clipped) {
            ctx.fillStyle = "#c9d2dc"; ctx.font = "600 10.5px Inter, sans-serif";
            ctx.textAlign = b[0] > w / 2 ? "right" : "left";
            ctx.fillText(`→ ${f.to_city}`, b[0] + (b[0] > w / 2 ? -6 : 6), b[1] - 4);
            ctx.beginPath(); ctx.arc(b[0], b[1], 3, 0, Math.PI * 2); ctx.fill();
          }
        }
      }
      // selected posting: highlighted arc + accuracy circles
      if (selected?.kind === "tx" && selected.lat != null && selected.lng != null) {
        const a = P(selected.lng, selected.lat);
        if (selected.peer?.lat != null && selected.peer?.lng != null) {
          const { pt: b } = edge(a, P(selected.peer.lng, selected.peer.lat));
          const c = ctrl(a, b);
          ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 2.6; ctx.setLineDash([6, 4]);
          ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.quadraticCurveTo(c[0], c[1], b[0], b[1]); ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = "#ffffff"; ctx.beginPath(); ctx.arc(b[0], b[1], 4, 0, Math.PI * 2); ctx.fill();
        }
      }
      arcs.current = geo;
      let alive = motion && risky;
      if (motion) {
        if (data && layers.fraud) {
          const phase = (now % 2200) / 2200;
          for (const c of data.cities) {
            if (!c.fraud_linked_paise || c.lat == null) continue;
            const p = P(c.lng, c.lat);
            ctx.strokeStyle = `rgba(240,82,82,${0.7 * (1 - phase)})`; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(p[0], p[1], 6 + 18 * phase, 0, Math.PI * 2); ctx.stroke();
          }
          alive = alive || data.cities.some((c) => c.fraud_linked_paise > 0);
        }
        const keep: Particle[] = [];
        for (const pt of particles.current) {
          const s = (now - pt.t0) / pt.dur;
          if (s >= 1) continue;
          keep.push(pt);
          const a = P(pt.from[0], pt.from[1]);
          ctx.fillStyle = pt.risky ? "#ff6b6b" : "#9ff5e1";
          if (pt.to && !pt.atm) {
            const { pt: b } = edge(a, P(pt.to[0], pt.to[1]));
            const q = bez(a, ctrl(a, b), b, s);
            ctx.beginPath(); ctx.arc(q[0], q[1], pt.risky ? 3.2 : 2.2, 0, Math.PI * 2); ctx.fill();
          } else {
            ctx.strokeStyle = pt.risky ? `rgba(255,107,107,${1 - s})` : `rgba(240,176,64,${1 - s})`; ctx.lineWidth = 1.6;
            ctx.beginPath(); ctx.arc(a[0], a[1], 3 + 12 * s, 0, Math.PI * 2); ctx.stroke();
          }
        }
        particles.current = keep;
        alive = alive || keep.length > 0;
      }
      return alive;
    };
    const loop = (now: number) => {
      const alive = draw(now);
      dirty.current = false;
      if ((alive || dirty.current) && document.visibilityState !== "hidden") raf = requestAnimationFrame(loop);
      else raf = 0;
    };
    const kick = () => { if (!raf && document.visibilityState !== "hidden") raf = requestAnimationFrame(loop); };
    kick();
    const iv = window.setInterval(() => { if (dirty.current || particles.current.length) kick(); }, 250);
    const vis = () => kick();
    document.addEventListener("visibilitychange", vis);
    return () => { cancelAnimationFrame(raf); window.clearInterval(iv); document.removeEventListener("visibilitychange", vis); };
  }, [data, layers, selected, w, h, P, t]);

  // zoom / pan
  const zoomAt = useCallback((factor: number, mx: number, my: number) => {
    setT((o) => {
      const k = Math.min(24, Math.max(1, o.k * factor));   // land data is simplified to ~3 km: no deeper zoom
      const r = k / o.k;
      return { k, x: mx - (mx - o.x) * r, y: my - (my - o.y) * r };
    });
  }, []);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(Math.exp(-e.deltaY * 0.0016), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [zoomAt]);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number; moved: boolean } | null>(null);
  const reset = () => setT({ k: 1, x: 0, y: 0 });

  // fly to a selection that has coordinates
  useEffect(() => {
    if (!selected || selected.lat == null || selected.lng == null) return;
    const p = proj([selected.lng, selected.lat]);
    if (!p) return;
    const q = selected.kind === "city" && selected.peer?.lat != null && selected.peer?.lng != null
      ? proj([selected.peer.lng, selected.peer.lat]) : null;
    if (q) {                                                     // a corridor: frame both cities
      // keep it between the corridors panel (left) and the city card (right): ~250 px each side
      const k = Math.min(6, Math.max(1, Math.min(Math.max(220, w - 520) / (Math.abs(p[0] - q[0]) + 40), (h - 60) / (Math.abs(p[1] - q[1]) + 60))));
      const cx = (p[0] + q[0]) / 2, cy = (p[1] + q[1]) / 2;
      setT({ k, x: w / 2 - k * cx, y: h / 2 - k * cy });
      return;
    }
    const precise = /±\d+ m\b/.test(selected.label ?? "");      // ATM / device GPS: show street level
    // a city is shown at region level (zooming OUT of a street-level view if needed); points keep a deeper zoom
    const target = selected.kind === "city" ? 3.2 : selected.kind === "cluster" ? 12 : precise ? 14 : 2.4;
    const k = selected.kind === "city" ? target : Math.max(tRef.current.k, target);
    setT({ k, x: w / 2 - k * p[0], y: h / 2 - k * p[1] });
  }, [selected?.kind, selected?.id, selected?.lat, selected?.lng, selected?.peer?.lat, proj, w, h]); // eslint-disable-line react-hooks/exhaustive-deps

  const cities = data?.cities ?? [];
  const maxCity = Math.max(1, ...cities.map((c) => c.value_paise));
  const screen = cities.filter((c) => c.lat != null).map((c) => {
    const [x, y] = P(c.lng, c.lat);
    const r = c.kind === "foreign" ? 3 : 2.6 + 7.5 * Math.sqrt(c.value_paise / maxCity);
    const color = c.kind === "foreign" ? "#7d8794" : c.fraud_linked_paise ? "#f05252" : c.suspicious_count ? "#f0b040" : "#4fd6b8";
    return { c, x, y, r, color, on: x > -10 && x < w + 10 && y > -10 && y < h + 10 };
  });
  // labels: top by value + every risky city + the selected one; simple collision avoidance
  const labelled = useMemo(() => {
    if (!layers.labels) return new Set<string>();
    const order = [...screen].filter((s) => s.on).sort((a, b) =>
      (b.c.fraud_linked_paise > 0 ? 1e15 : 0) + b.c.value_paise - ((a.c.fraud_linked_paise > 0 ? 1e15 : 0) + a.c.value_paise));
    const boxes: number[][] = [];
    const keep = new Set<string>();
    for (const s of order.slice(0, t.k > 3 ? 40 : 14)) {
      const wd = s.c.city.length * 6.4 + 8, x0 = s.x + s.r + 3, y0 = s.y - 7;
      if (boxes.some(([a, b, c2, d]) => x0 < c2 && x0 + wd > a && y0 < d && y0 + 14 > b)) continue;
      boxes.push([x0, y0, x0 + wd, y0 + 14]);
      keep.add(s.c.city);
    }
    if (selected?.kind === "city") keep.add(selected.id);
    return keep;
  }, [screen, layers.labels, t.k, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const clusters: (MapCluster & { sx: number; sy: number; rpx: number })[] = (data?.clusters ?? [])
    .filter((c) => c.center && ((c.kind === "cash_out" && layers.atm) || (c.kind === "collection" && layers.collection)))
    .map((c) => {
      const [sx, sy] = P(c.center!.lng, c.center!.lat);
      return { ...c, sx, sy, rpx: Math.max(8, c.radius_km * pxPerKm(c.center!.lat, c.center!.lng)) };
    });
  const atms = layers.atm ? (t.k >= 4 && reference ? reference.atms : data?.atm ?? []) : [];
  const used = new Map((data?.atm ?? []).map((a) => [a.terminal_id, a]));
  const selPins: { x: number; y: number; rpx: number; label: string }[] = [];
  if (selected?.kind === "tx" && selected.lat != null && selected.lng != null) {
    const m = selected.label?.match(/±(\d+(?:\.\d+)?)\s*(m|km)/);
    const meters = m ? Number(m[1]) * (m[2] === "km" ? 1000 : 1) : 5000;
    const [x, y] = P(selected.lng, selected.lat);
    selPins.push({ x, y, rpx: Math.max(4, (meters / 1000) * pxPerKm(selected.lat, selected.lng)), label: selected.label ?? "" });
  }

  // nearest arc within a few pixels (sampled along each quadratic curve)
  const hitArc = (mx: number, my: number): ArcGeo | null => {
    let best: ArcGeo | null = null, bd = 7;
    for (const g of arcs.current) {
      for (let i = 0; i <= 20; i++) {
        const s = i / 20;
        const x = (1 - s) ** 2 * g.a[0] + 2 * (1 - s) * s * g.c[0] + s * s * g.b[0];
        const y = (1 - s) ** 2 * g.a[1] + 2 * (1 - s) * s * g.c[1] + s * s * g.b[1];
        const d = Math.hypot(x - mx, y - my) - g.w / 2;
        if (d < bd) { bd = d; best = g; }
      }
    }
    return best;
  };
  // scale bar: a round distance about 90 px long at the map centre
  const scale = useMemo(() => {
    const c = proj.invert?.([w / 2, h / 2]);
    if (!c) return null;
    const ppk = pxPerKm(c[1], c[0]);
    if (!ppk || !Number.isFinite(ppk)) return null;
    const target = 90 / ppk;
    const steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
    const km = steps.reduce((p, s) => (Math.abs(s - target) < Math.abs(p - target) ? s : p), steps[0]);
    return { px: km * ppk, label: km < 1 ? `${km * 1000} m` : `${km} km` };
  }, [proj, w, h, pxPerKm, t]); // eslint-disable-line react-hooks/exhaustive-deps

  const tip = (e: React.MouseEvent) => {
    if (drag.current?.moved) return;
    const r = wrap.current!.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const hit = screen.find((s) => s.on && Math.hypot(s.x - mx, s.y - my) <= Math.max(8, s.r + 3));
    if (hit) {
      const c = hit.c;
      setHover({ x: mx, y: my, html: <CityTip c={c} /> });
      return;
    }
    const cl = clusters.find((c) => Math.hypot(c.sx - mx, c.sy - my) <= c.rpx);
    const arc = !cl && layers.flows ? hitArc(mx, my) : null;
    if (arc) {
      const f = arc.f;
      setHover({ x: mx, y: my, html: <><b>{f.from_city} → {f.to_city}</b>
        <div>{f.tx_count} posting{f.tx_count > 1 ? "s" : ""} · {formatPaiseShort(f.value_paise)}</div>
        <div className={f.risk === "fraud" ? "bad" : f.risk === "suspicious" ? "warn" : "dim"}>{RISK_WORD[f.risk]}</div>
        <div className="dim">{Object.entries(f.rails).sort((x, y) => y[1] - x[1]).slice(0, 3).map(([r, n]) => `${RAIL_LABEL[r as Rail] ?? r} ${n}`).join(" · ")}</div>
        <div className="dim">Simulated locations · city to city</div></> });
      return;
    }
    if (cl) {
      setHover({ x: mx, y: my, html: <><b>{cl.kind === "cash_out" ? "Cash-out cluster" : "Collection point"}</b>
        <div>{cl.kind === "cash_out" ? `${cl.tx_ids?.length ?? 0} risky ATM withdrawals · ${formatPaiseShort(cl.value_paise)}`
          : `${cl.senders} distinct senders · ${formatPaiseShort(cl.value_paise)}`}</div>
        <div className="dim">{cl.kind === "cash_out" ? `within ${cl.radius_km} km · ${cl.city}` : cl.rule}</div>
        <div className="dim">Simulated location</div></> });
      return;
    }
    setHover(null);
  };
  const click = (e: React.MouseEvent) => {
    if (drag.current?.moved) return;
    const r = wrap.current!.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const hit = screen.find((s) => s.on && Math.hypot(s.x - mx, s.y - my) <= Math.max(8, s.r + 3));
    if (hit) { onSelect({ kind: "city", id: hit.c.city, lat: hit.c.lat, lng: hit.c.lng, label: hit.c.city }); return; }
    const cl = clusters.find((c) => Math.hypot(c.sx - mx, c.sy - my) <= c.rpx);
    if (cl) { onSelect({ kind: "cluster", id: cl.id, accounts: cl.accounts, lat: cl.center?.lat, lng: cl.center?.lng, label: cl.city ?? cl.id }); return; }
  };

  return (
    <div className="mmap" ref={wrap} style={{ height: h }} tabIndex={0} role="application"
         aria-label={`Money map (simulated locations). ${data ? `${data.totals.postings} postings, ${data.flows.length} city-to-city flows, ${data.clusters.length} clusters in the window.` : "Loading."} Use + and − to zoom, arrow keys to pan, 0 to reset.`}
         onKeyDown={(e) => {
           if (e.key === "+" || e.key === "=") zoomAt(1.4, w / 2, h / 2);
           else if (e.key === "-") zoomAt(1 / 1.4, w / 2, h / 2);
           else if (e.key === "0") reset();
           else if (e.key.startsWith("Arrow")) {
             const d = 40;
             setT((o) => ({ ...o, x: o.x + (e.key === "ArrowLeft" ? d : e.key === "ArrowRight" ? -d : 0), y: o.y + (e.key === "ArrowUp" ? d : e.key === "ArrowDown" ? -d : 0) }));
           } else return;
           e.preventDefault();
         }}
         onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, ox: t.x, oy: t.y, moved: false }; (e.target as Element).setPointerCapture?.(e.pointerId); }}
         onPointerMove={(e) => {
           const d = drag.current;
           if (d && e.buttons) {
             const dx = e.clientX - d.x, dy = e.clientY - d.y;
             if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
             if (d.moved) setT((o) => ({ ...o, x: d.ox + dx, y: d.oy + dy }));
           } else tip(e);
         }}
         onPointerUp={(e) => { click(e); window.setTimeout(() => { drag.current = null; }, 0); }}
         onPointerLeave={() => setHover(null)}
         onDoubleClick={reset}>
      <svg width={w} height={h} className="mmap-land" aria-hidden="true">
        <defs>
          <radialGradient id="mm-india-fill" cx="50%" cy="45%" r="65%">
            <stop offset="0%" stopColor="#1a3a43" /><stop offset="100%" stopColor="#0f2329" />
          </radialGradient>
          <filter id="mm-glow" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="3.2" /></filter>
        </defs>
        <g transform={`translate(${t.x},${t.y}) scale(${t.k})`}>
          <path d={land.grid} className="grid" vectorEffect="non-scaling-stroke" />
          {land.countries.map((c, i) => <path key={i} d={c.d} className={c.near ? "near" : "far"} vectorEffect="non-scaling-stroke" />)}
          <path d={land.india} className="india-glow" vectorEffect="non-scaling-stroke" filter="url(#mm-glow)" />
          <path d={land.india} className="india" fill="url(#mm-india-fill)" vectorEffect="non-scaling-stroke" />
          <path d={land.states} className="states" vectorEffect="non-scaling-stroke" />
        </g>
      </svg>
      <canvas ref={canvas} className="mmap-canvas" style={{ width: w, height: h }} />
      <svg width={w} height={h} className="mmap-top" aria-hidden="true">
        {screen.filter((s) => s.on).map((s) => (
          <g key={s.c.city}>
            {s.c.fraud_linked_paise > 0 && t.k < 6 && <circle cx={s.x} cy={s.y} r={s.r + 5} className="city-halo" />}
            <circle cx={s.x} cy={s.y} r={t.k >= 6 ? Math.min(s.r, 5) : s.r} fill={s.color} className={`city ${selected?.kind === "city" && selected.id === s.c.city ? "sel" : ""}`} opacity={t.k >= 6 ? 0.55 : 1} />
            {labelled.has(s.c.city) && <text x={s.x + s.r + 3} y={s.y + 4} className={`city-label ${s.c.kind === "foreign" ? "foreign" : ""} ${s.c.fraud_linked_paise > 0 ? "risky" : ""}`}>{s.c.city}</text>}
          </g>
        ))}
        {atms.map((a) => {
          const [x, y] = P(a.lng, a.lat);
          const u = used.get(a.terminal_id);
          if (x < -4 || x > w + 4 || y < -4 || y > h + 4) return null;
          return <rect key={a.terminal_id} x={x - 2.5} y={y - 2.5} width={5} height={5}
                       className={`atm ${u ? (u.risk_value_paise ? "risky" : "used") : "idle"}`} />;
        })}
        {clusters.map((c) => c.kind === "cash_out"
          ? <g key={c.id}><circle cx={c.sx} cy={c.sy} r={c.rpx} className="cluster cash" /><text x={c.sx} y={c.sy + 3} className="cluster-n">{c.tx_ids?.length ?? ""}</text></g>
          : <path key={c.id} d={`M${c.sx} ${c.sy - 7}L${c.sx + 7} ${c.sy}L${c.sx} ${c.sy + 7}L${c.sx - 7} ${c.sy}Z`} className={`coll ${c.status === "flagged" || c.status === "held" || c.status === "confirmed_fraud" ? "risky" : ""}`} />)}
        {selPins.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r={p.rpx} className="acc-circle" />
            <circle cx={p.x} cy={p.y} r={4} className="pin" />
          </g>
        ))}
      </svg>
      <div className="mmap-ctrl" onPointerDown={(e) => e.stopPropagation()}>
        <button onClick={() => zoomAt(1.5, w / 2, h / 2)} aria-label="Zoom in">+</button>
        <button onClick={() => zoomAt(1 / 1.5, w / 2, h / 2)} aria-label="Zoom out">−</button>
        <button onClick={reset} aria-label="Reset view" title="Reset view (double-click the map)">⟲</button>
      </div>
      <div className="mmap-vignette" aria-hidden="true" />
      {scale && <div className="mmap-scale" aria-hidden="true"><i style={{ width: scale.px }} /><span>{scale.label}</span></div>}
      {selPins[0] && <div className="mmap-pinlabel">{selPins[0].label}</div>}
      {hover && <div className="mmap-tip" style={{ left: Math.min(hover.x + 12, w - 230), top: Math.max(6, hover.y - 10) }}>{hover.html}</div>}
      {!data && <div className="mmap-empty">Loading money map…</div>}
      {data && data.totals.postings === 0 && <div className="mmap-empty">No postings in this window yet.</div>}
    </div>
  );
}

function CityTip({ c }: { c: MapCity }) {
  return (
    <>
      <b>{c.city}</b>{c.state && c.kind !== "foreign" ? <span className="dim"> · {c.state}</span> : null}
      <div>{c.tx_count} postings · {formatPaiseShort(c.value_paise)}</div>
      {c.fraud_linked_paise > 0 && <div className="bad">{formatPaiseShort(c.fraud_linked_paise)} fraud-linked</div>}
      {c.suspicious_count > 0 && <div className="warn">{c.suspicious_count} touching early-warning accounts</div>}
      {c.at_risk_accounts > 0 && <div>{c.at_risk_accounts} at-risk account(s) live here</div>}
      <div className="dim">{c.kind === "foreign" ? "International destination (simulated)" : "Simulated location · city centre"}</div>
    </>
  );
}
