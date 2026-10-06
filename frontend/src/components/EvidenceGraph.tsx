// The graph is evidence, not decoration: a capped subgraph, laid out once
// (dagre, left → right = direction of money), no physics, no per-frame work.
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import dagre from "cytoscape-dagre";
import { useEffect, useRef, useState } from "react";
import type { GraphEvidence, GraphNode } from "../api/types";
import { formatINR, handle } from "../lib/format";

cytoscape.use(dagre);

const ROLE_COLOR: Record<string, string> = {
  source: "#2471a3",
  collector: "#c0392b",
  "pass-through": "#d35400",
  distributor: "#b9770e",
  "cash-out": "#6c7a89",
};

function css(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function nodeColor(n: GraphNode): string {
  if (n.kind === "external") return "#8795a6";
  if (n.role && ROLE_COLOR[n.role]) return ROLE_COLOR[n.role];
  if (n.risk >= 0.6) return "#c0392b";
  if (n.risk >= 0.4) return "#d35400";
  return "#7f8fa3";
}

export function EvidenceGraph({
  evidence, onNodeClick, onEdgeClick, selected, height = "100%", compact = false,
}: {
  evidence: GraphEvidence | null;
  onNodeClick?: (id: string) => void;
  onEdgeClick?: (edgeId: string) => void;
  selected?: string | null;
  height?: number | string;
  compact?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const clickRef = useRef(onNodeClick);
  const edgeRef = useRef(onEdgeClick);
  clickRef.current = onNodeClick;
  edgeRef.current = onEdgeClick;

  useEffect(() => {
    if (!box.current) return;
    const ink = css("--ink", "#142030");
    const cy = cytoscape({
      container: box.current,
      wheelSensitivity: 0.25,
      minZoom: 0.2,
      maxZoom: 2.5,
      boxSelectionEnabled: false,
      style: [
        { selector: "node", style: {
          "background-color": "data(color)", width: "data(size)", height: "data(size)",
          label: "data(short)", "font-size": compact ? 9 : 10, color: ink, "text-valign": "bottom",
          "text-margin-y": 4, "min-zoomed-font-size": 7, "font-family": "IBM Plex Sans, sans-serif",
          "border-width": 0, "text-max-width": "90px", "text-wrap": "ellipsis",
        } },
        { selector: "node[kind = 'external']", style: { shape: "round-rectangle" } },
        { selector: "node[?labelled]", style: { "border-width": 4, "border-color": "#7b1e1e" } },
        { selector: "node[?tainted]", style: { "border-width": 3, "border-color": "#e74c3c", "border-style": "double" } },
        { selector: "node[?focus]", style: { "border-width": 4, "border-color": css("--brand", "#1d4f91") } },
        { selector: "node:selected", style: { "border-width": 4, "border-color": css("--focus", "#2f6fd1") } },
        { selector: "edge", style: {
          width: "data(w)", "line-color": "#aab4c1", "target-arrow-color": "#aab4c1", "target-arrow-shape": "triangle",
          "curve-style": "bezier", "arrow-scale": 0.8, opacity: 0.75,
        } },
        { selector: "edge[?highlight]", style: { "line-color": "#d35400", "target-arrow-color": "#d35400", opacity: 0.95 } },
        { selector: "edge[?tainted]", style: { "line-color": "#c0392b", "target-arrow-color": "#c0392b", "line-style": "solid", opacity: 1 } },
        { selector: ".fresh", style: { "line-color": css("--brand", "#1d4f91"), "target-arrow-color": css("--brand", "#1d4f91"), width: 5 } },
      ],
    });
    cy.on("tap", "node", (e) => clickRef.current?.(e.target.id()));
    cy.on("tap", "edge", (e) => edgeRef.current?.(e.target.id()));
    cy.on("mouseover", "node, edge", (e) => {
      const p = e.renderedPosition ?? e.target.renderedMidpoint?.() ?? { x: 0, y: 0 };
      setTip({ x: p.x, y: p.y, text: e.target.data("tip") });
    });
    cy.on("mouseout", "node, edge", () => setTip(null));
    cy.on("viewport", () => setTip(null));
    cyRef.current = cy;
    // Re-fit (never re-layout) when the container changes size, e.g. grid settling or window resize.
    const ro = new ResizeObserver(() => {
      cy.resize();
      if (cy.elements().length) {
        cy.fit(undefined, 24);
        if (cy.zoom() > 1.25) { cy.zoom(1.25); cy.center(); }
      }
    });
    ro.observe(box.current);
    return () => { ro.disconnect(); cy.destroy(); cyRef.current = null; };
  }, [compact]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !evidence) return;
    const before = new Set(cy.edges().map((e) => e.id()));
    const maxAmt = Math.max(1, ...evidence.edges.map((e) => e.amount_paise));
    const tainted = new Set(evidence.nodes.filter((n) => n.attributable_paise > 0).map((n) => n.id));
    const els: ElementDefinition[] = [
      ...evidence.nodes.map((n) => ({
        data: {
          id: n.id, short: handle(n.label.length > 18 ? n.id : n.label), kind: n.kind,
          color: nodeColor(n), size: 18 + Math.round(n.risk * 26), labelled: n.labelled, tainted: tainted.has(n.id),
          focus: evidence.focus === n.id,
          tip: `${n.label}${n.role ? ` · ${n.role}` : ""}${n.risk ? ` · risk ${n.risk.toFixed(2)}` : ""}` +
               `${n.attributable_paise ? ` · ${formatINR(n.attributable_paise)} traced` : ""}`,
        },
      })),
      ...evidence.edges.map((e) => ({
        data: {
          id: e.id, source: e.source, target: e.target, highlight: e.highlight, tainted: e.tainted_paise > 0,
          w: 1.2 + 5 * Math.sqrt(e.amount_paise / maxAmt),
          tip: `${formatINR(e.amount_paise)} in ${e.count} payment${e.count > 1 ? "s" : ""}` +
               `${e.tainted_paise ? ` · ${formatINR(e.tainted_paise)} traced (LIBR)` : ""}`,
        },
      })),
    ];
    cy.resize();
    cy.batch(() => {
      cy.elements().remove();
      cy.add(els);
    });
    cy.layout({ name: "dagre", rankDir: "LR", nodeSep: compact ? 18 : 28, rankSep: compact ? 60 : 90,
                animate: false, fit: true, padding: 24 } as cytoscape.LayoutOptions).run();
    if (cy.zoom() > 1.25) { cy.zoom(1.25); cy.center(); }  // small graphs: don't blow labels up
    if (before.size) {
      const fresh = cy.edges().filter((e) => !before.has(e.id()));
      fresh.addClass("fresh");
      window.setTimeout(() => fresh.removeClass("fresh"), 2500);
    }
  }, [evidence, compact]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.$(":selected").unselect();
    if (selected) cy.$id(selected).select();
  }, [selected, evidence]);

  return (
    <div className="graph-box" style={{ height }}>
      <div ref={box} style={{ position: "absolute", inset: 0 }} />
      {tip && <div className="graph-tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
      {evidence && evidence.nodes.length === 0 && (
        <div className="graph-empty">No suspicious structure right now.<br />Run Scenario 2 to inject a mule ring.</div>
      )}
      {!compact && (
        <div className="graph-legend">
          {Object.entries(ROLE_COLOR).map(([k, c]) => <span key={k}><i style={{ background: c }} />{k}</span>)}
          <span><i style={{ background: "#c0392b", borderRadius: 2 }} />traced edge</span>
          <span><i style={{ border: "3px solid #7b1e1e", background: "transparent" }} />confirmed scam recipient</span>
          {evidence?.truncated && <span className="muted">showing {evidence.nodes.length} of {evidence.total_nodes}</span>}
        </div>
      )}
    </div>
  );
}
