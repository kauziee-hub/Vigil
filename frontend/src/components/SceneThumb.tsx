// Compact network thumbnail: a static SVG projection of the server's FROZEN scene layout (GraphScene x/y/z).
// No physics, no WebGL, no re-layout — it draws exactly the positions /api/graph/scene returned, so it is
// cheap enough for the Overview and the account view. Colour = status, ring = held / confirmed / victim.
import { memo, useMemo } from "react";
import type { GraphScene } from "../api/types";
import { handle } from "../lib/format";
import { nodeStatus } from "../lib/graphStyle";

export const SceneThumb = memo(function SceneThumb({ scene, height = 200, focus, onPick, label = true }: {
  scene: GraphScene; height?: number; focus?: string | null; onPick?: (id: string) => void; label?: boolean;
}) {
  const W = 640, H = height, P = 16;
  // The server layout is layered: x = money-flow depth, each layer a ring in the y/z plane. A flat thumbnail reads
  // best as x = depth, y = the node's angle around its ring (ring centre → middle), axes scaled to fill the box.
  const geo = useMemo(() => {
    const pts = scene.nodes.map((n) => {
      const r = Math.hypot(n.y, n.z);
      return { n, px: n.x, py: r < 1e-6 ? 0 : Math.atan2(n.z, n.y) };
    });
    const xs = pts.map((p) => p.px), ys = pts.map((p) => p.py);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const fx = (v: number) => (maxX - minX < 1e-6 ? W / 2 : P + 24 + ((v - minX) / (maxX - minX)) * (W - 2 * P - 48));
    const fy = (v: number) => (maxY - minY < 1e-6 ? H / 2 : P + ((v - minY) / (maxY - minY)) * (H - 2 * P));
    const pos = new Map<string, [number, number]>();
    pts.forEach((p) => pos.set(p.n.id, [fx(p.px), fy(p.py)]));
    const maxAmt = Math.max(1, ...scene.edges.map((e) => e.amount_paise));
    return { pos, maxAmt };
  }, [scene, W, H]);

  if (!scene.nodes.length) return <div className="thumb-empty">No suspicious structure in this scope.</div>;
  const top = new Set([...scene.nodes].filter((n) => n.labelled || n.held || n.risk >= 0.75).sort((a, b) => b.risk - a.risk).slice(0, 5).map((n) => n.id));
  return (
    <svg className="thumb" viewBox={`0 0 ${W} ${H}`} style={{ height: H }} role="img"
         aria-label={`Network thumbnail: ${scene.nodes.length} accounts, ${scene.edges.length} aggregated money flows`}>
      <defs>
        <marker id="th-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0 0 8 4 0 8z" fill="#3a8a70" />
        </marker>
        <marker id="th-arrow-f" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0 0 8 4 0 8z" fill="var(--st-fraud)" />
        </marker>
      </defs>
      {scene.edges.map((e) => {
        const a = geo.pos.get(e.source), b = geo.pos.get(e.target);
        if (!a || !b) return null;
        const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1;
        const r = 5.5;
        const tainted = e.tainted_paise > 0;
        return (
          <line key={e.id} x1={a[0] + (dx / L) * r} y1={a[1] + (dy / L) * r} x2={b[0] - (dx / L) * (r + 1)} y2={b[1] - (dy / L) * (r + 1)}
                stroke={tainted ? "var(--st-fraud)" : "#2c6b57"} strokeOpacity={tainted ? 0.9 : 0.55}
                strokeWidth={0.6 + 2.2 * Math.sqrt(e.amount_paise / geo.maxAmt)} markerEnd={`url(#${tainted ? "th-arrow-f" : "th-arrow"})`} />
        );
      })}
      {scene.nodes.map((n) => {
        const p = geo.pos.get(n.id)!;
        const st = nodeStatus(n);
        const isFocus = focus === n.id;
        const ring = n.labelled ? "var(--st-fraud)" : n.held ? "var(--st-held)" : n.victim ? "#edf7f1" : isFocus ? "#68f0af" : null;
        return (
          <g key={n.id} transform={`translate(${p[0]},${p[1]})`} onClick={onPick ? () => onPick(n.id) : undefined}
             style={{ cursor: onPick ? "pointer" : undefined }}>
            <title>{`${n.label} · risk ${n.risk.toFixed(2)}${n.role ? ` · ${n.role}` : ""}`}</title>
            {ring && <circle r={isFocus ? 8.5 : 7} fill="none" stroke={ring} strokeWidth={1.6} />}
            <circle r={isFocus ? 5.5 : n.kind === "external" ? 3 : 4} fill={n.kind === "external" && st === "unknown" ? "#34493f" : `var(--st-${st})`} />
            {label && (top.has(n.id) || isFocus) && (
              <text x={8} y={-7} className="thumb-l">{handle(n.id)}</text>
            )}
          </g>
        );
      })}
    </svg>
  );
});
