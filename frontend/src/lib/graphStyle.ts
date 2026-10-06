// Shared visual grammar for 2D and 3D network views.
// Colour = status (risk / held / confirmed fraud). Shape = role. Ring = victim / held / confirmed source.
import type { GraphEvidence, GraphScene, SceneNode } from "../api/types";
import { scoreStatus, type Status } from "./status";

export type ShapeKey = "sphere" | "octa" | "cone" | "dodeca" | "cyl" | "tetra" | "ico" | "hex" | "box";

export const ROLE_SHAPE: Record<string, { shape: ShapeKey; cy: string; label: string }> = {
  normal: { shape: "sphere", cy: "ellipse", label: "Account" },
  victim: { shape: "sphere", cy: "ellipse", label: "Victim (white ring)" },
  suspected: { shape: "ico", cy: "pentagon", label: "Suspected mule" },
  "pass-through": { shape: "hex", cy: "hexagon", label: "Pass-through mule" },
  collector: { shape: "octa", cy: "diamond", label: "Collector" },
  distributor: { shape: "cone", cy: "triangle", label: "Distributor" },
  coordinator: { shape: "dodeca", cy: "star", label: "Coordinator" },
  entry: { shape: "cyl", cy: "round-tag", label: "Entry" },
  exit: { shape: "tetra", cy: "vee", label: "Exit / cash-out" },
  external: { shape: "box", cy: "round-rectangle", label: "External account" },
};

const ROLE_ALIAS: Record<string, string> = { source: "entry", "cash-out": "exit", cashout: "exit", unclassified: "normal", mule: "suspected" };

export function roleKey(role: string | null | undefined, kind?: string): string {
  if (kind === "external") return "external";
  if (!role) return "normal";
  const r = ROLE_ALIAS[role] ?? role;
  return ROLE_SHAPE[r] ? r : "normal";
}

/** Node status under the RISK view: confirmed fraud > held > risk score. */
export function nodeStatus(n: { risk: number; labelled: boolean; held?: boolean; kind?: string }): Status {
  if (n.labelled) return "fraud";
  if (n.held) return "held";
  if (n.kind === "external" && !n.risk) return "unknown";
  return n.risk > 0 ? scoreStatus(n.risk) : "normal";
}

/** SVG path data for legend icons (16×16 box). */
export const SHAPE_ICON: Record<ShapeKey, string> = {
  sphere: "M8 2a6 6 0 1 0 0.001 0z",
  octa: "M8 1 15 8 8 15 1 8z",
  cone: "M8 2 14 14H2z",
  dodeca: "M8 1l2 4.6 5 .4-3.8 3.3 1.2 4.9L8 11.6 3.6 14.2l1.2-4.9L1 6l5-.4z",
  cyl: "M3 4h10v8H3z",
  tetra: "M2 3h12L8 14z",
  ico: "M8 1.5l6.2 4.5-2.4 7.5H4.2L1.8 6z",
  hex: "M8 1l6 3.5v7L8 15l-6-3.5v-7z",
  box: "M2 5h12v6H2z",
};

/**
 * Fallback when GET /api/graph/scene is not served: convert the v1 suspicious subgraph into a scene with a
 * deterministic LAYERED layout computed once (BFS depth along money direction → x, stable hash → y/z).
 * No physics. Per-transaction timestamps are not available in this payload, so replay is edge-level.
 */
export function sceneFromEvidence(ev: GraphEvidence): GraphScene {
  const ids = ev.nodes.map((n) => n.id);
  const incoming = new Map<string, number>();
  const out = new Map<string, string[]>();
  ev.edges.forEach((e) => {
    incoming.set(e.target, (incoming.get(e.target) ?? 0) + 1);
    out.set(e.source, [...(out.get(e.source) ?? []), e.target]);
  });
  const depth = new Map<string, number>();
  const roots = ids.filter((id) => !incoming.get(id));
  const queue = (roots.length ? roots : ids.slice(0, 1)).map((id) => { depth.set(id, 0); return id; });
  while (queue.length) {
    const id = queue.shift()!;
    for (const t of out.get(id) ?? []) {
      if (!depth.has(t)) { depth.set(t, (depth.get(id) ?? 0) + 1); queue.push(t); }
    }
  }
  ids.forEach((id) => { if (!depth.has(id)) depth.set(id, 0); });
  const layers = new Map<number, string[]>();
  ids.forEach((id) => { const d = depth.get(id)!; layers.set(d, [...(layers.get(d) ?? []), id]); });
  const maxD = Math.max(0, ...layers.keys());
  const pos = new Map<string, [number, number, number]>();
  layers.forEach((members, d) => {
    members.sort();
    const n = members.length;
    members.forEach((id, i) => {
      const a = (i / Math.max(1, n)) * Math.PI * 2 + hash(id) * 0.6;
      const r = n === 1 ? 0 : 28 + n * 4.5;
      pos.set(id, [(d - maxD / 2) * 70, Math.cos(a) * r, Math.sin(a) * r]);
    });
  });
  const tainted = new Set(ev.nodes.filter((n) => n.attributable_paise > 0).map((n) => n.id));
  return {
    version: `client-${ev.nodes.length}-${ev.edges.length}-${ev.edges.reduce((s, e) => s + e.count, 0)}`,
    layout: "client-layered (fallback)",
    nodes: ev.nodes.map<SceneNode>((n) => {
      const [x, y, z] = pos.get(n.id)!;
      return {
        id: n.id, label: n.label, kind: n.kind === "external" ? "external" : "customer", x, y, z, layer: depth.get(n.id) ?? 0,
        role: n.role, risk: n.risk, taint_paise: tainted.has(n.id) ? n.attributable_paise : 0, labelled: n.labelled,
        victim: false, held: false, balance_paise: n.balance_paise, flags: n.flags,
      };
    }),
    edges: ev.edges.map((e) => ({
      id: e.id, source: e.source, target: e.target, amount_paise: e.amount_paise, count: e.count,
      first_ts: e.first_ts, last_ts: e.last_ts, tainted_paise: e.tainted_paise, channels: [], txs: [],
    })),
    focus: ev.focus, cap: ev.nodes.length, truncated: ev.truncated, total_candidates: ev.total_nodes,
    time_range: null, built_ms: 0, cached: false,
  };
}

/** Scene → GraphEvidence for the 2D (Cytoscape) fallback view. */
export function evidenceFromScene(s: GraphScene): GraphEvidence {
  return {
    nodes: s.nodes.map((n) => ({
      id: n.id, label: n.label, kind: n.kind, risk: n.risk, flags: n.flags, role: n.role, balance_paise: n.balance_paise,
      labelled: n.labelled, attributable_paise: n.taint_paise,
    })),
    edges: s.edges.map((e) => ({
      id: e.id, source: e.source, target: e.target, amount_paise: e.amount_paise, count: e.count, first_ts: e.first_ts,
      last_ts: e.last_ts, tainted_paise: e.tainted_paise, tx_ids: e.txs.map((t) => t.id), highlight: false,
    })),
    focus: s.focus, truncated: s.truncated, total_nodes: s.total_candidates,
  };
}

export function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return ((h >>> 0) % 10000) / 10000;
}
