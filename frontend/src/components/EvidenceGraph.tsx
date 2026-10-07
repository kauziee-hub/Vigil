// 2D evidence graph (Cytoscape): a capped subgraph, laid out once (dagre, left → right = direction of
// money), no physics, no per-frame work. Used inline in investigations and as the 2D fallback of the
// Network Intelligence page. Same visual grammar as the 3D view: colour = status, shape = role.
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import dagre from "cytoscape-dagre";
import { useEffect, useRef, useState } from "react";
import type { GraphEvidence } from "../api/types";
import { formatINR, handle } from "../lib/format";
import { ROLE_SHAPE, nodeStatus, roleKey } from "../lib/graphStyle";
import { STATUS_HEX, STATUS_LABEL, type Status } from "../lib/status";

cytoscape.use(dagre);

export function EvidenceGraph({
  evidence, onNodeClick, onEdgeClick, selected, height = "100%", compact = false, colorOf,
}: {
  evidence: GraphEvidence | null;
  onNodeClick?: (id: string) => void;
  onEdgeClick?: (edgeId: string) => void;
  selected?: string | null;
  height?: number | string;
  compact?: boolean;
  /** Optional override of node status (e.g. model-score modes on the Network page). */
  colorOf?: (id: string) => Status | null;
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
    const ink = getComputedStyle(document.documentElement).getPropertyValue("--ink-2").trim() || "#a2b2c5";
    const cy = cytoscape({
      container: box.current,
      wheelSensitivity: 0.25, minZoom: 0.2, maxZoom: 2.5, boxSelectionEnabled: false,
      style: [
        { selector: "node", style: {
          "background-color": "data(color)", shape: "data(shape)" as never, width: "data(size)", height: "data(size)",
          label: "data(short)", "font-size": compact ? 9 : 10, color: ink, "text-valign": "bottom", "text-margin-y": 4,
          "min-zoomed-font-size": 7, "font-family": "IBM Plex Mono, monospace", "border-width": 0,
          "text-max-width": "90px", "text-wrap": "ellipsis",
        } },
        { selector: "node[?ring]", style: { "border-width": 3, "border-color": "data(ring)" } },
        { selector: "node:selected", style: { "border-width": 3, "border-color": "#dce5ef" } },
        { selector: "edge", style: {
          width: "data(w)", "line-color": "#3a4f6b", "target-arrow-color": "#5a7393", "target-arrow-shape": "triangle",
          "curve-style": "bezier", "arrow-scale": 0.9, opacity: 0.85,
        } },
        { selector: "edge[?tainted]", style: { "line-color": STATUS_HEX.fraud, "target-arrow-color": STATUS_HEX.fraud, opacity: 1 } },
        { selector: "edge[?highlight]", style: { "line-color": "#8fb0dc", "target-arrow-color": "#8fb0dc" } },
        { selector: ".fresh", style: { "line-color": "#8fb0dc", "target-arrow-color": "#8fb0dc", width: 4 } },
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
    const ro = new ResizeObserver(() => {
      cy.resize();
      if (cy.elements().length) { cy.fit(undefined, 24); if (cy.zoom() > 1.25) { cy.zoom(1.25); cy.center(); } }
    });
    ro.observe(box.current);
    return () => { ro.disconnect(); cy.destroy(); cyRef.current = null; };
  }, [compact]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !evidence) return;
    const before = new Set(cy.edges().map((e) => e.id()));
    const maxAmt = Math.max(1, ...evidence.edges.map((e) => e.amount_paise));
    const els: ElementDefinition[] = [
      ...evidence.nodes.map((n) => {
        const st = colorOf?.(n.id) ?? nodeStatus({ risk: n.risk, labelled: n.labelled, kind: n.kind });
        const rk = roleKey(n.role, n.kind);
        return {
          data: {
            id: n.id, short: handle(n.label.length > 18 ? n.id : n.label), color: STATUS_HEX[st], shape: ROLE_SHAPE[rk].cy,
            size: 16 + Math.round(n.risk * 22), ring: n.attributable_paise > 0 && !n.labelled ? STATUS_HEX.fraud : evidence.focus === n.id ? "#8fb0dc" : "",
            tip: `${n.label} · ${STATUS_LABEL[st]}${n.role ? ` · ${n.role}` : ""}${n.risk ? ` · risk ${n.risk.toFixed(2)}` : ""}` +
                 `${n.attributable_paise ? ` · ${formatINR(n.attributable_paise)} traced` : ""}`,
          },
        };
      }),
      ...evidence.edges.map((e) => ({
        data: {
          id: e.id, source: e.source, target: e.target, highlight: e.highlight, tainted: e.tainted_paise > 0,
          w: 1 + 4.5 * Math.sqrt(e.amount_paise / maxAmt),
          tip: `${formatINR(e.amount_paise)} in ${e.count} payment${e.count > 1 ? "s" : ""}` +
               `${e.tainted_paise ? ` · ${formatINR(e.tainted_paise)} traced (LIBR)` : ""}`,
        },
      })),
    ];
    cy.resize();
    cy.batch(() => { cy.elements().remove(); cy.add(els); });
    cy.layout({ name: "dagre", rankDir: "LR", nodeSep: compact ? 18 : 28, rankSep: compact ? 60 : 90,
                animate: false, fit: true, padding: 24 } as cytoscape.LayoutOptions).run();
    if (cy.zoom() > 1.25) { cy.zoom(1.25); cy.center(); }
    if (before.size) {
      const fresh = cy.edges().filter((e) => !before.has(e.id()));
      fresh.addClass("fresh");
      window.setTimeout(() => fresh.removeClass("fresh"), 2500);
    }
  }, [evidence, compact, colorOf]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.$(":selected").unselect();
    if (selected) cy.$id(selected).select();
  }, [selected, evidence]);

  const statuses: Status[] = ["normal", "watch", "high", "critical", "fraud"];
  return (
    <div className="graph-box" style={{ height }}>
      <div ref={box} style={{ position: "absolute", inset: 0 }} />
      {tip && <div className="graph-tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
      {evidence && evidence.nodes.length === 0 && (
        <div className="graph-empty">No suspicious structure in this window.<br />Start a network scenario in the Scenario Lab to inject one.</div>
      )}
      {!compact && (
        <div className="graph-legend">
          {statuses.map((s) => <span key={s}><i style={{ background: STATUS_HEX[s] }} />{STATUS_LABEL[s]}</span>)}
          <span>shape = role</span>
          {evidence?.truncated && <span>showing {evidence.nodes.length} of {evidence.total_nodes}</span>}
        </div>
      )}
    </div>
  );
}
