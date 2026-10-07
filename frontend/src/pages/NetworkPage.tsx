// NETWORK INTELLIGENCE — how is money moving, who plays which role.
// WebGL 3D view over the server's frozen layout (GraphScene) with a 2D fallback; graph modes; 1/2-hop
// expansion; scenario-scoped attack scenes; TIME / ATTACK REPLAY over SceneEdge.txs; investigation drawer.
// Scene payloads are cached per query and re-fetched only when console events indicate structural change.
import { lazy, memo, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type {
  GraphScene, IntelScores, LedgerTx, RiskSignal, RingRow, ScenarioReplay, ScenarioStatus, SceneEdge, SceneNode, TaintView, UniverseAccount,
} from "../api/types";
import { SignalRow } from "../components/Decision";
import { Graph3D, type Graph3DStyle } from "../components/Graph3D";
import { AccountIntelBlock, RoleIcon } from "../components/intel";
import { MoneyTrace } from "../components/MoneyTrace";
import { useConsoleEvents } from "../components/Shell";
import { KV, PageHead, Panel, Pill, Seg, Sim, Tabs } from "../components/ui";
import { LiveUniverse3D, UniverseLegend, type UniverseInfo, type UniverseMode } from "../components/LiveUniverse3D";
import { UniverseDrawer } from "../components/UniverseDrawer";
import { formatINR, formatStamp, formatTime, handle } from "../lib/format";
import { ROLE_SHAPE, SHAPE_ICON, evidenceFromScene, nodeStatus, roleKey, sceneFromEvidence } from "../lib/graphStyle";
import { useDebounced, useLoad } from "../lib/hooks";
import { ROLE_LABEL, STATUS_HEX, STATUS_LABEL, scoreStatus, type Status } from "../lib/status";

type Mode = "flow" | "risk" | "taint" | "roles" | "gnn" | "rules" | "ml";
const MODES: [Mode, string][] = [
  ["flow", "Money flow"], ["risk", "Risk"], ["taint", "Taint"], ["roles", "Mule roles"],
  ["gnn", "GNN score"], ["rules", "Rule score"], ["ml", "ML score"],
];
const MODEL_MODES = new Set<Mode>(["gnn", "rules", "ml"]);
// The 2D fallback (Cytoscape) is only fetched when someone switches to 2D — the 3D page stays lighter.
const EvidenceGraph = lazy(() => import("../components/EvidenceGraph").then((m) => ({ default: m.EvidenceGraph })));
const CAPS = [40, 60, 100, 200, 400];

// ── scene cache (module-level: survives navigation away and back) ─────────────
const sceneCache = new Map<string, GraphScene>();
interface Scope { cap: number; focus?: string; hops?: number; scenario?: string }
const scopeKey = (s: Scope) => `c${s.cap}|f${s.focus ?? ""}|h${s.hops ?? 1}|s${s.scenario ?? ""}`;

async function fetchScene(s: Scope): Promise<GraphScene> {
  try {
    return await api.scene({ cap: s.cap, focus: s.focus, hops: s.focus ? s.hops : undefined, scenario: s.scenario });
  } catch (e) {
    // Older backends without /api/graph/scene: honest client-side layered layout of the v1 subgraph.
    if (e instanceof ApiError && e.status === 404 && e.code === "not_found") {
      const ev = s.focus ? await api.graphNeighbourhood(s.focus, s.hops ?? 1) : await api.graphSuspicious();
      return sceneFromEvidence(ev);
    }
    throw e;
  }
}

const NEUTRAL = "#8fae9f";
const NEUTRAL_DIM = "#34493f";
const EDGE_BASE = "#2c6b57";

function useStyle(mode: Mode, scores: IntelScores | null): Graph3DStyle {
  return useMemo<Graph3DStyle>(() => {
    const modelScore = (n: SceneNode): number | null => {
      const s = scores?.scores[n.id];
      if (!s) return null;
      return mode === "gnn" ? s.gnn : mode === "rules" ? s.rules : s.rf;
    };
    const ring = (n: SceneNode) => (n.labelled ? STATUS_HEX.fraud : n.held ? STATUS_HEX.held : null);
    const base = {
      ringColor: ring,
      edgeColor: (e: SceneEdge) => (e.tainted_paise > 0 ? STATUS_HEX.fraud : EDGE_BASE),
    };
    switch (mode) {
      case "flow":
        return { ...base, nodeColor: (n) => (n.kind === "external" ? NEUTRAL_DIM : NEUTRAL), nodeDim: () => false,
                 edgeColor: (e) => (e.tainted_paise > 0 ? STATUS_HEX.fraud : "#3a8a70"),
                 label: (n) => (n.risk >= 0.75 || n.labelled ? n.label : null) };
      case "taint":
        return { ...base, nodeColor: (n) => (n.labelled || n.taint_paise > 0 ? STATUS_HEX.fraud : NEUTRAL),
                 nodeDim: (n) => !(n.labelled || n.taint_paise > 0),
                 label: (n) => (n.labelled ? `${n.label} · confirmed` : n.taint_paise > 0 ? `${n.label} · ${formatINR(n.taint_paise)}` : null) };
      case "roles":
        return { ...base, nodeColor: (n) => (roleKey(n.role, n.kind) === "normal" ? NEUTRAL_DIM : "#d6efe2"),
                 nodeDim: (n) => roleKey(n.role, n.kind) === "normal" && !n.victim,
                 label: (n) => (roleKey(n.role, n.kind) !== "normal" && n.kind !== "external" ? `${ROLE_LABEL[n.role ?? ""] ?? n.role} · ${n.label}` : null) };
      case "gnn": case "rules": case "ml":
        return { ...base, nodeColor: (n) => { const v = modelScore(n); return v === null ? NEUTRAL_DIM : STATUS_HEX[scoreStatus(v)]; },
                 nodeDim: (n) => modelScore(n) === null,
                 label: (n) => { const v = modelScore(n); return v !== null && v >= 0.75 ? `${n.label} · ${v.toFixed(2)}` : null; } };
      default:
        return { ...base, nodeColor: (n) => STATUS_HEX[nodeStatus(n)], nodeDim: () => false,
                 label: (n) => (n.labelled || n.held || n.risk >= 0.6 ? n.label : null) };
    }
  }, [mode, scores]);
}

type Tip = { x: number; y: number; text: string } | null;
/** Tooltip owns its own state so pointer movement never re-renders the page. */
const HoverTip = memo(function HoverTip({ bind }: { bind: (set: (t: Tip) => void) => void }) {
  const [tip, setTip] = useState<Tip>(null);
  useEffect(() => bind(setTip), [bind]);
  return tip ? <div className="net-tip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div> : null;
});

function EvidenceSceneView() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "2d" ? "2d" : "3d";
  const mode = (params.get("mode") as Mode) || "risk";
  const cap = Number(params.get("cap")) || 60;
  const focus = params.get("focus") || undefined;
  const hops = Number(params.get("hops")) || 1;
  const scenario = params.get("scenario") || undefined;
  const scope: Scope = useMemo(() => ({ cap, focus, hops, scenario: focus ? undefined : scenario }), [cap, focus, hops, scenario]);
  const key = scopeKey(scope);

  const setParam = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v === null ? next.delete(k) : next.set(k, v)));
    next.set("tab", "scene");
    setParams(next, { replace: true });
  };

  const [scene, setScene] = useState<GraphScene | null>(() => sceneCache.get(key) ?? null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [stale, setStale] = useState(false);
  const [fetchMs, setFetchMs] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(focus ?? null);
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [focusSeq, setFocusSeq] = useState(0);
  const [replayOn, setReplayOn] = useState(params.get("replay") === "1");
  const scores = useLoad<IntelScores>(api.intelScores);
  const scenarios = useLoad<ScenarioStatus[]>(api.scenarios);
  const taint = useLoad<TaintView>(api.taint);
  const ring = useLoad<RingRow[]>(api.ringwatch);
  const keyRef = useRef(key);
  keyRef.current = key;

  const load = useCallback(async (force = false) => {
    const k = scopeKey(scope);
    const cached = sceneCache.get(k);
    if (cached && !force) { setScene(cached); setLoadErr(null); return; }
    setLoading(true);
    const t0 = performance.now();
    try {
      const s = await fetchScene(scope);
      setFetchMs(Math.round(performance.now() - t0));
      sceneCache.set(k, s);
      if (keyRef.current === k) {
        // identical version → keep the same object so nothing downstream rebuilds
        setScene((prev) => (prev && prev.version === s.version ? prev : s));
        setLoadErr(null); setStale(false);
      }
    } catch (e) {
      if (keyRef.current === k) setLoadErr(e instanceof ApiError ? (e.code === "unknown_scenario" ? `Unknown scenario '${scope.scenario}'.` : e.message) : String(e));
    } finally { setLoading(false); }
  }, [scope]);
  useEffect(() => { load(false); }, [load]);
  useEffect(() => { if (focus) { setSelected(focus); setFocusSeq((n) => n + 1); } }, [focus]);

  const structural = useDebounced(() => { sceneCache.clear(); load(true); taint.reload(); ring.reload(); }, 1200);
  useConsoleEvents((e) => {
    if (["ringwatch.scan", "taint.updated", "demo.reset", "scenario.step", "monitor.finding"].includes(e.type)) structural();
    else if (e.type === "ledger.posted") setStale(true);
    if (e.type.startsWith("scenario.")) scenarios.reload();
    if (e.type === "intel.updated") scores.reload();
  });

  const intelOk = !!scores.data && !scores.error;
  const style = useStyle(mode, scores.data);

  const scenReplay = useLoad<ScenarioReplay | null>(() => (scope.scenario ? api.scenarioReplay(scope.scenario) : Promise.resolve(null)), [scope.scenario, scene?.version]);

  // ── replay timeline (txs in the scene, ordered by ts then tx id = posting order). For an attack scope the
  //    timeline starts at the attack's first transaction; earlier context edges are simply already present. ──
  const timeline = useMemo(() => {
    if (!scene) return [];
    const out: { t: number; id: string; e: SceneEdge; amount: number; channel: string }[] = [];
    scene.edges.forEach((e) => e.txs.forEach((tx) => {
      const t = Date.parse(tx.ts);
      if (!Number.isNaN(t)) out.push({ t, id: tx.id, e, amount: tx.amount_paise, channel: tx.channel });
    }));
    out.sort((a, b) => a.t - b.t || a.id.localeCompare(b.id));
    const firstAttack = (scenReplay.data?.events ?? []).filter((ev) => ev.tx_id).map((ev) => Date.parse(ev.ts)).sort((a, b) => a - b)[0];
    if (scope.scenario && firstAttack !== undefined) {
      const from = out.findIndex((x) => x.t >= firstAttack - 1);
      if (from > 0) return out.slice(from);
    }
    return out;
  }, [scene, scenReplay.data, scope.scenario]);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { setStep(0); setPlaying(false); }, [scene?.version]);
  useEffect(() => {
    if (!playing || !replayOn) return;
    if (step >= timeline.length - 1) { setPlaying(false); return; }
    const t = window.setTimeout(() => setStep((s) => Math.min(timeline.length - 1, s + 1)), 420);
    return () => window.clearTimeout(t);
  }, [playing, step, replayOn, timeline.length]);
  const safeStep = Math.min(step, Math.max(0, timeline.length - 1));
  const cur = replayOn && timeline.length ? timeline[safeStep] : null;
  const replayT = cur ? cur.t : null;
  const replayWindow = useMemo(() => {
    if (!cur) return 1000;
    let prev = cur.t;
    for (let i = safeStep - 1; i >= 0; i--) { if (timeline[i].t < cur.t) { prev = timeline[i].t; break; } }
    return Math.max(1, cur.t - prev);
  }, [cur, timeline, safeStep]);

  const tipSetter = useRef<((t: Tip) => void) | null>(null);
  const bindTip = useCallback((set: (t: Tip) => void) => { tipSetter.current = set; }, []);
  const onHover = useCallback((t: Tip) => tipSetter.current?.(t), []);
  const hoverText = useCallback((n: SceneNode) => {
    const st = nodeStatus(n);
    const s = scores.data?.scores[n.id];
    return `${n.label} · ${STATUS_LABEL[st]}${n.role && n.role !== "normal" ? ` · ${ROLE_LABEL[n.role] ?? n.role}` : ""}` +
      `${n.risk ? ` · risk ${n.risk.toFixed(2)}` : ""}${n.taint_paise ? ` · ${formatINR(n.taint_paise)} traced` : ""}` +
      `${s && MODEL_MODES.has(mode) ? ` · rules ${s.rules?.toFixed(2) ?? "—"} rf ${s.rf?.toFixed(2) ?? "—"} gnn ${s.gnn?.toFixed(2) ?? "—"}` : ""}`;
  }, [scores.data, mode]);
  const hoverEdgeText = useCallback((e: SceneEdge) =>
    `${handle(e.source)} → ${handle(e.target)} · ${formatINR(e.amount_paise)} in ${e.count} payment${e.count > 1 ? "s" : ""}` +
    `${e.channels.length ? ` · ${e.channels.join("/")}` : ""}${e.tainted_paise ? ` · ${formatINR(e.tainted_paise)} traced (LIBR)` : ""}`, []);
  const onSelect = useCallback((id: string | null) => { setSelected(id); setSelectedEdge(null); if (id) setFocusSeq((n) => n + 1); }, []);
  const onSelectEdge = useCallback((id: string | null) => { setSelectedEdge(id); if (id) setSelected(null); }, []);

  const evidence2d = useMemo(() => (scene ? evidenceFromScene(scene) : null), [scene]);
  const colorOf2d = useMemo(() => {
    if (!scene) return undefined;
    const byHex = new Map(Object.entries(STATUS_HEX).map(([k, h]) => [h, k as Status]));
    const map = new Map<string, Status>();
    scene.nodes.forEach((n) => map.set(n.id, style.nodeDim(n) ? "unknown" : byHex.get(style.nodeColor(n)) ?? "unknown"));
    return (id: string) => map.get(id) ?? null;
  }, [scene, style]);

  const node = scene?.nodes.find((n) => n.id === selected) ?? null;
  const edge = scene?.edges.find((e) => e.id === selectedEdge) ?? null;
  const attackScen = (scenarios.data ?? []).filter((s) => s.category === "attack" || s.id === "s2");
  const counts = useMemo(() => {
    if (!scene) return null;
    const c = { fraud: 0, held: 0, victim: 0, high: 0, roles: 0 };
    scene.nodes.forEach((n) => { if (n.labelled) c.fraud++; if (n.held) c.held++; if (n.victim) c.victim++; if (n.risk >= 0.5) c.high++; if (roleKey(n.role, n.kind) !== "normal") c.roles++; });
    return c;
  }, [scene]);

  return (
    <>
      <div className="notice sm" style={{ marginBottom: 12 }}>Evidence scene: the suspicious subgraph (accounts with network evidence plus counterparties), a focus neighbourhood or one attack. Layout is computed once on the server and frozen — no physics. Shape = role, colour = status, ring = held / confirmed / victim.</div>
      <div className="net-toolbar">
        <Seg options={[["3d", "3D"], ["2d", "2D"]]} value={view} onChange={(v) => setParam({ view: v === "3d" ? "scene" : v })} />
        <Seg options={MODES} value={mode} onChange={(m) => setParam({ mode: m === "risk" ? null : m })} />
        <label className="row tight xs muted">Scope
          <select className="select sm" style={{ width: 230 }} value={focus ? "__focus" : scenario ?? ""}
                  onChange={(e) => setParam({ scenario: e.target.value && e.target.value !== "__focus" ? e.target.value : null, focus: null, hops: null, replay: null })}>
            <option value="">Suspicious subgraph (default)</option>
            {focus && <option value="__focus">Focus: {handle(focus)} · {hops}-hop</option>}
            {attackScen.map((s) => <option key={s.id} value={s.id}>{s.act === "Attack" ? "Attack" : s.act} · {s.name}</option>)}
          </select>
        </label>
        <label className="row tight xs muted">Node cap
          <select className="select sm" style={{ width: 70 }} value={cap} onChange={(e) => setParam({ cap: e.target.value === "60" ? null : e.target.value })}>
            {CAPS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <button className={`btn sm ${replayOn ? "on" : ""}`} disabled={!timeline.length} onClick={() => { setReplayOn(!replayOn); setPlaying(false); setStep(0); }}
                title={timeline.length ? "Replay the transactions in this scene in posting order" : "No timestamped transactions in this scene"}>
          {replayOn ? "Exit replay" : scope.scenario ? "Attack replay" : "Time replay"}</button>
        <span className="grow" />
        {stale && <button className="btn sm" onClick={() => { sceneCache.clear(); load(true); }} title="New ledger activity since this scene was built">New activity · update scene</button>}
        <button className="btn sm ghost" onClick={() => { sceneCache.delete(key); load(true); }} disabled={loading}>{loading ? "Loading…" : "Reload"}</button>
      </div>
      {MODEL_MODES.has(mode) && !intelOk && (
        <div className="unavail" style={{ marginBottom: 8 }}><span className="ic">∅</span><div><b>{MODES.find((m) => m[0] === mode)?.[1]}: not yet available.</b> Per-account model scores come from <span className="mono">/api/intel/scores</span>, which this server does not serve yet. Nodes are shown unscored (dimmed) rather than estimated.</div></div>
      )}
      {loadErr && <div className="notice err" style={{ marginBottom: 8 }}>{loadErr}</div>}

      <div className={`net ${replayOn ? "has-replay" : ""} ${node || edge ? "has-drawer" : ""}`}>
        <div className="net-canvas">
          {scene && view === "3d" && (
            <Graph3D scene={scene} style={style} selected={selected} selectedEdge={selectedEdge} replayT={replayT}
                     replayWindowMs={replayWindow} focusSeq={focusSeq} onSelect={onSelect} onSelectEdge={onSelectEdge}
                     onHover={onHover} hoverText={hoverText} hoverEdgeText={hoverEdgeText} />
          )}
          {scene && view === "2d" && (
            <Suspense fallback={<div className="net-empty"><span className="spinner lg" /></div>}>
              <EvidenceGraph evidence={evidence2d} selected={selected} colorOf={colorOf2d} onNodeClick={(id) => onSelect(id)} onEdgeClick={(id) => onSelectEdge(id)} />
            </Suspense>
          )}
        </div>
        <HoverTip bind={bindTip} />
        {!scene && !loadErr && <div className="net-empty"><span className="spinner lg" /></div>}
        {scene && scene.nodes.length === 0 && (
          <div className="net-empty">No suspicious structure in this scope.<br />Run a network or attack scenario in the <Link to="/lab">Scenario Lab</Link> to inject one.</div>
        )}

        {scene && view === "3d" && (
          <div className="net-hud">
            <div className="hud">
              <div><b>{scene.nodes.length}</b> nodes · <b>{scene.edges.length}</b> aggregated edges{scene.truncated && <> · showing {scene.nodes.length} of {scene.total_candidates} candidates</>}</div>
              <div>scope <b>{focus ? `${handle(focus)} · ${hops}-hop` : scope.scenario ? `scenario ${scope.scenario}` : "suspicious subgraph"}</b> · cap {scene.cap}</div>
              <div>layout <b>{scene.layout}</b> · built {scene.built_ms.toFixed(1)} ms{scene.cached ? " (server cache)" : ""}{fetchMs !== null ? ` · fetched ${fetchMs} ms` : ""}</div>
              {scene.time_range && <div>window {formatStamp(scene.time_range[0])} → {formatStamp(scene.time_range[1])}</div>}
              {counts && <div>high-risk <b>{counts.high}</b> · role holders <b>{counts.roles}</b> · confirmed <b style={{ color: counts.fraud ? STATUS_HEX.fraud : undefined }}>{counts.fraud}</b> · held <b>{counts.held}</b> · victims <b>{counts.victim}</b></div>}
            </div>
          </div>
        )}

        {view === "3d" && <Legend mode={mode} />}

        {replayOn && scope.scenario && scenReplay.data && (
          <div className="net-steps">
            <div className="up" style={{ marginBottom: 4 }}>Attack timeline · {scope.scenario}</div>
            {scenReplay.data.events.length === 0 && <div className="xs muted">This scenario has not run since the last reset. Start it in the Scenario Lab.</div>}
            {scenReplay.data.events.map((ev, i) => {
              const done = cur ? Date.parse(ev.ts) <= cur.t : false;
              const now = !!cur && ev.tx_id === cur.id;
              return (
                <div key={i} className={`st ${done ? "done" : ""} ${now ? "now" : ""}`}>
                  <span className="mono dim">{formatTime(ev.ts)}</span> {ev.title}{ev.amount_paise ? <span className="mono"> {formatINR(ev.amount_paise)}</span> : null}
                </div>
              );
            })}
          </div>
        )}

        {replayOn && timeline.length > 0 && (
          <div className="net-replay">
            <button className="btn sm" onClick={() => { if (safeStep >= timeline.length - 1) setStep(0); setPlaying(!playing); }}>{playing ? "❚❚ Pause" : "▶ Play"}</button>
            <button className="btn sm ghost" onClick={() => { setPlaying(false); setStep(Math.max(0, safeStep - 1)); }} aria-label="Previous transaction">‹</button>
            <button className="btn sm ghost" onClick={() => { setPlaying(false); setStep(Math.min(timeline.length - 1, safeStep + 1)); }} aria-label="Next transaction">›</button>
            <input type="range" min={0} max={timeline.length - 1} value={safeStep} onChange={(e) => { setPlaying(false); setStep(Number(e.target.value)); }} aria-label="Replay position" />
            <span className="now">{safeStep + 1}/{timeline.length} · {cur && formatStamp(new Date(cur.t).toISOString())}</span>
            {cur && <span className="mono xs ell" style={{ maxWidth: 320 }}>{cur.id} · {handle(cur.e.source)} → {handle(cur.e.target)} · {formatINR(cur.amount)}</span>}
          </div>
        )}

        {(node || edge) && (
          <aside className="drawer" aria-label="Investigation drawer">
            {node && <NodeDrawer node={node} scene={scene!} intelScores={scores.data} taint={taint.data}
                                onClose={() => setSelected(null)} onFocus={() => setFocusSeq((n) => n + 1)}
                                onExpand={(h) => setParam({ focus: node.id, hops: String(h), scenario: null, replay: null })}
                                onLabelled={() => { taint.reload(); sceneCache.clear(); load(true); }} />}
            {edge && <EdgeDrawer edge={edge} onClose={() => setSelectedEdge(null)} onPick={(id) => onSelect(id)} />}
          </aside>
        )}
      </div>

      <div className="grid cols-ms align-start" style={{ marginTop: 12 }}>
        <Panel kicker="TaintTrace" title="Value traced from confirmed scams" q="LIBR and pro rata side by side"
               footer={taint.data && taint.data.incidents.length > 0 ? `${taint.data.computed_ms} ms over ${taint.data.journals_considered ?? "—"} journals · conservation checked per rule` : "Confirm a victim payment in the drawer (Recent postings) to start a trace."}>
          {taint.unavailable ? <div className="empty">TaintTrace endpoint not served.</div> : <MoneyTrace incidents={taint.data?.incidents ?? []} focus={selected ?? undefined} />}
        </Panel>
        <Panel kicker="RingWatch" title="Accounts with network evidence" flush>
          <table className="dt compact">
            <thead><tr><th>Account</th><th>Role</th><th style={{ width: "30%" }}>Score</th></tr></thead>
            <tbody>
              {(ring.data ?? []).slice(0, 12).map((r) => (
                <tr key={r.account_id} className={`click ${selected === r.account_id ? "sel" : ""}`}
                    onClick={() => (scene?.nodes.some((n) => n.id === r.account_id) ? onSelect(r.account_id) : setParam({ focus: r.account_id, hops: "1", scenario: null }))}>
                  <td>{handle(r.account_id)} {r.labelled && <Pill status="fraud">confirmed</Pill>}</td>
                  <td className="xs"><span className="row tight"><RoleIcon role={r.role} />{r.role ? ROLE_LABEL[r.role] ?? r.role : "—"}</span></td>
                  <td><span className="row tight"><span className="grow"><span className="bar" style={{ display: "block" }}><i style={{ width: `${r.score * 100}%`, background: STATUS_HEX[scoreStatus(r.score)] }} /></span></span><span className="mono xs">{r.score.toFixed(2)}</span></span></td>
                </tr>
              ))}
              {ring.data && ring.data.length === 0 && <tr><td colSpan={3} className="empty">No account currently shows network evidence.</td></tr>}
            </tbody>
          </table>
        </Panel>
      </div>
    </>
  );
}

function Legend({ mode }: { mode: Mode }) {
  const statuses: Status[] = mode === "taint" ? ["fraud"] : mode === "flow" || mode === "roles" ? [] : ["normal", "watch", "high", "critical"];
  const roles = ["normal", "suspected", "pass-through", "collector", "distributor", "coordinator", "entry", "exit", "external"];
  return (
    <div className="net-legend">
      {statuses.map((s) => <span key={s}><i className="sw" style={{ background: STATUS_HEX[s] }} />{STATUS_LABEL[s]}</span>)}
      {(mode === "flow" || mode === "roles") && <span><i className="sw" style={{ background: mode === "flow" ? NEUTRAL : "#d6efe2" }} />{mode === "flow" ? "Account (neutral)" : "Role holder"}</span>}
      <span><svg width="12" height="12" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="none" stroke={STATUS_HEX.fraud} strokeWidth="2" /></svg>Confirmed fraud</span>
      <span><svg width="12" height="12" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="none" stroke={STATUS_HEX.held} strokeWidth="2" /></svg>Held</span>
      <span><svg width="12" height="12" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="none" stroke="#edf7f1" strokeWidth="2" /></svg>Victim</span>
      <span><svg width="22" height="10" viewBox="0 0 22 10"><path d="M1 5h15" stroke="#3a8a70" strokeWidth="2" /><path d="M14 1l7 4-7 4z" fill="#3a8a70" /></svg>Direction · width ∝ √amount</span>
      {roles.map((r) => (
        <span key={r}><svg width="12" height="12" viewBox="0 0 16 16"><path d={SHAPE_ICON[ROLE_SHAPE[r].shape]} fill="none" stroke="#b9cfc3" strokeWidth="1.4" /></svg>{ROLE_SHAPE[r].label}</span>
      ))}
    </div>
  );
}

function NodeDrawer({ node, scene, intelScores, taint, onClose, onFocus, onExpand, onLabelled }: {
  node: SceneNode; scene: GraphScene; intelScores: IntelScores | null; taint: TaintView | null;
  onClose: () => void; onFocus: () => void; onExpand: (hops: number) => void; onLabelled: () => void;
}) {
  const ext = node.kind === "external" || node.id.startsWith("ext:");
  const net = useLoad(() => (ext ? Promise.resolve(null) : api.accountNetwork(node.id)), [node.id]);
  const txs = useLoad<LedgerTx[]>(() => (ext ? Promise.resolve([]) : api.accountTransactions(node.id)), [node.id]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const inE = scene.edges.filter((e) => e.target === node.id);
  const outE = scene.edges.filter((e) => e.source === node.id);
  const inSum = inE.reduce((s, e) => s + e.amount_paise, 0);
  const outSum = outE.reduce((s, e) => s + e.amount_paise, 0);
  const st = nodeStatus(node);
  const sc = intelScores?.scores[node.id];
  const labelledTx = new Set((taint?.incidents ?? []).map((i) => i.transaction_id));
  const signals = (net.data?.signals ?? []) as RiskSignal[];

  const confirm = async (txId: string) => {
    setBusy(txId); setErr(null);
    try { await api.label(txId); onLabelled(); txs.reload(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  return (
    <>
      <div className="drawer-h">
        <RoleIcon role={node.role} size={18} />
        <div className="grow">
          <div className="b">{node.label}</div>
          <div className="mono xs dim">{node.id}</div>
        </div>
        <button className="btn xs ghost" onClick={onClose} aria-label="Close drawer">✕</button>
      </div>
      <div className="drawer-b">
        <div className="sect">
          <div className="row wrap tight">
            <Pill status={st} />
            {node.role && node.role !== "normal" && <span className="tag">{ROLE_LABEL[node.role] ?? node.role}</span>}
            {node.held && <Pill status="held">held</Pill>}
            {node.victim && <span className="tag">victim</span>}
            {ext && <span className="tag">outside the bank's view</span>}
          </div>
          <div className="mstrip" style={{ marginTop: 8 }}>
            <div className="m"><div className="k">Network risk</div><div className="v" style={{ color: STATUS_HEX[scoreStatus(node.risk)] }}>{node.risk.toFixed(2)}</div><div className="d">RingWatch score</div></div>
            <div className="m"><div className="k">Traced</div><div className="v" style={{ color: node.taint_paise ? STATUS_HEX.fraud : undefined }}>{formatINR(node.taint_paise)}</div><div className="d">LIBR attributable</div></div>
            <div className="m"><div className="k">In / out</div><div className="v">{inE.length}/{outE.length}</div><div className="d">edges in scene</div></div>
          </div>
          <div style={{ marginTop: 8 }}>
            <KV c4 rows={[
              ["Inflow (scene)", <span className="mono">{formatINR(inSum)}</span>], ["Outflow (scene)", <span className="mono">{formatINR(outSum)}</span>],
              ["Balance", <span className="mono">{formatINR(node.balance_paise)}</span>], ["Layer", `${node.layer} (flow depth)`],
            ]} />
          </div>
          <div className="row wrap" style={{ marginTop: 8 }}>
            <button className="btn sm" onClick={onFocus}>Focus camera</button>
            {!ext && <button className="btn sm" onClick={() => onExpand(1)}>Expand 1-hop</button>}
            {!ext && <button className="btn sm" onClick={() => onExpand(2)}>Expand 2-hop</button>}
            {!ext && <Link className="btn sm primary" to={`/investigations/account/${encodeURIComponent(node.id)}`}>Investigate</Link>}
          </div>
        </div>
        {node.flags.length > 0 && (
          <div className="sect"><div className="sect-t">RingWatch flags · rule engine</div>
            <div className="row wrap tight">{node.flags.map((f) => <span key={f} className="tag">{f}</span>)}</div></div>
        )}
        {sc && (
          <div className="sect"><div className="sect-t">Model scores (corroborating)</div>
            <KV c4 rows={[["Rules", sc.rules?.toFixed(2) ?? "—"], ["Random Forest", sc.rf?.toFixed(2) ?? "—"], ["GNN", sc.gnn?.toFixed(2) ?? "—"], ["Drift", sc.drift_level ?? "—"],
                          ["Role", sc.role ?? "—"], ["Early warning", sc.early_warning ? "yes" : "no"]]} />
          </div>
        )}
        {!ext && <AccountIntelBlock accountId={node.id} compact />}
        {!ext && (
          <div className="sect">
            <div className="sect-t">Network evidence · RingWatch rules</div>
            {net.data && signals.length === 0 && <div className="xs muted">No network rule fires for this account.</div>}
            {signals.map((s) => <SignalRow key={s.rule_id} s={s} />)}
            {net.data && Boolean(net.data.external_intel) && (
              <div className="notice sm" style={{ marginTop: 6 }}><Sim text="SIMULATED EXTERNAL INTELLIGENCE" /> {String((net.data.external_intel as { status?: string }).status ?? "")}</div>
            )}
          </div>
        )}
        {!ext && (txs.data ?? []).length > 0 && (
          <div className="sect">
            <div className="sect-t">Recent postings · confirm a victim payment to trace it</div>
            {err && <div className="notice err sm">{err}</div>}
            <table className="dt compact">
              <tbody>
                {(txs.data ?? []).slice(0, 10).map((t) => {
                  const inbound = t.recipient_id === node.id;
                  return (
                    <tr key={t.id}>
                      <td className="mono xs">{formatTime(t.ts)}</td>
                      <td className="xs">{inbound ? `← ${handle(t.sender_id)}` : `→ ${handle(t.recipient_id)}`}</td>
                      <td className="num xs">{formatINR(t.amount_paise)}</td>
                      <td className="right">
                        {labelledTx.has(t.id) ? <Pill status="fraud">confirmed</Pill>
                          : inbound && t.kind === "transfer" && (t.source === "scenario" || node.risk >= 0.4) && (
                            <button className="btn xs danger" disabled={busy === t.id} onClick={() => confirm(t.id)}
                                    title="Simulates a verified victim report confirmed by the bank; starts TaintTrace">{busy === t.id ? "Tracing…" : "Confirm scam"}</button>)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="sect">
          <div className="sect-t">Counterparties in this scene</div>
          <table className="dt compact">
            <tbody>
              {[...inE.map((e) => ({ e, dir: "←", other: e.source })), ...outE.map((e) => ({ e, dir: "→", other: e.target }))]
                .sort((a, b) => b.e.amount_paise - a.e.amount_paise).slice(0, 10).map(({ e, dir, other }) => (
                  <tr key={e.id}><td className="xs">{dir} {handle(other)}</td><td className="num xs">{formatINR(e.amount_paise)}</td><td className="xs dim">{e.count}×</td>
                    <td>{e.tainted_paise > 0 && <Pill status="fraud">traced</Pill>}</td></tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function EdgeDrawer({ edge, onClose, onPick }: { edge: SceneEdge; onClose: () => void; onPick: (id: string) => void }) {
  return (
    <>
      <div className="drawer-h">
        <div className="grow"><div className="b">{handle(edge.source)} → {handle(edge.target)}</div><div className="mono xs dim">aggregated edge</div></div>
        <button className="btn xs ghost" onClick={onClose} aria-label="Close drawer">✕</button>
      </div>
      <div className="drawer-b">
        <div className="sect">
          <KV rows={[
            ["Amount", <b className="mono">{formatINR(edge.amount_paise)}</b>], ["Payments", edge.count], ["Channels", edge.channels.join(", ") || "—"],
            ["First", formatStamp(edge.first_ts)], ["Last", formatStamp(edge.last_ts)],
            ["Traced (LIBR)", edge.tainted_paise ? <span className="mono" style={{ color: STATUS_HEX.fraud }}>{formatINR(edge.tainted_paise)}</span> : "—"],
          ]} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn sm" onClick={() => onPick(edge.source)}>Open sender</button>
            <button className="btn sm" onClick={() => onPick(edge.target)}>Open recipient</button>
          </div>
        </div>
        <div className="sect"><div className="sect-t">Transactions</div>
          <table className="dt compact"><tbody>
            {edge.txs.map((t) => <tr key={t.id}><td className="mono xs">{t.id}</td><td className="mono xs">{formatStamp(t.ts)}</td><td className="xs">{t.channel}</td><td className="num xs">{formatINR(t.amount_paise)}</td></tr>)}
          </tbody></table>
        </div>
      </div>
    </>
  );
}

// ══ v3: Network Intelligence = full-screen live universe (lenses) + the scoped evidence scene as a second view ══
const UMODES: [UniverseMode, string][] = [["live", "Live status"], ["risk", "Risk"], ["model", "Model score"], ["roles", "Roles"], ["taint", "Taint"]];

function LiveUniverseView() {
  const [params, setParams] = useSearchParams();
  const mode = (params.get("lens") as UniverseMode) || "live";
  const taint = useLoad<TaintView>(api.taint);
  const refreshTaint = useDebounced(() => taint.reload(), 1500);
  useConsoleEvents((e) => { if (e.type === "taint.updated" || e.type === "demo.reset") refreshTaint(); });
  const taintMap = useMemo(() => new Map((taint.data?.exposure ?? []).map((x) => [x.account_id, x.attributable_paise])), [taint.data]);
  const accounts = useRef(new Map<string, UniverseAccount>());
  const [info, setInfo] = useState<UniverseInfo | null>(null);
  const onInfo = useCallback((i: UniverseInfo) => { accounts.current = i.accounts; setInfo(i); }, []);
  const [sel, setSel] = useState<{ id: string; acct: UniverseAccount | null } | null>(null);
  const [orbit, setOrbit] = useState(false);
  const [gt, setGt] = useState(false);
  const [focus, setFocus] = useState<{ ids: string[]; seq: number } | null>(null);
  const onSelect = useCallback((id: string | null, acct: UniverseAccount | null) => setSel(id ? { id, acct } : null), []);
  const setLens = (m: UniverseMode) => {
    const n = new URLSearchParams(params);
    if (m === "live") n.delete("lens"); else n.set("lens", m);
    setParams(n, { replace: true });
  };
  const [q, setQ] = useState("");
  const find = () => {
    const needle = q.trim().toLowerCase();
    if (!needle) return;
    const hit = [...accounts.current.values()].find((a) => a.id.toLowerCase().includes(needle) || a.label.toLowerCase().includes(needle));
    if (hit) { setSel({ id: hit.id, acct: hit }); setFocus({ ids: [hit.id], seq: Date.now() }); }
  };
  const alarm = useMemo(() => [...(info?.accounts.values() ?? [])]
    .filter((a) => a.status === "flagged" || a.status === "held" || a.status === "confirmed_fraud"), [info]);

  return (
    <>
      <div className="net-toolbar">
        <Seg options={UMODES} value={mode} onChange={setLens} />
        <button className={`btn sm ${orbit ? "on" : "ghost"}`} onClick={() => setOrbit(!orbit)}>Auto-orbit</button>
        <button className={`btn sm ${gt ? "on" : "ghost"}`} onClick={() => setGt(!gt)} title="Colour postings tagged by the simulator (evaluation only — never scored)">Simulator ground truth</button>
        <button className="btn sm ghost" onClick={() => setFocus({ ids: [...accounts.current.keys()], seq: Date.now() })}>Reset view</button>
        {alarm.length > 0 && <button className="btn sm danger" onClick={() => setFocus({ ids: alarm.map((a) => a.id), seq: Date.now() })}>Zoom to {alarm.length} flagged / held</button>}
        <span className="grow" />
        <input className="input sm" style={{ width: 220 }} placeholder="Find account (id or name)" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && find()} />
        <button className="btn sm" onClick={find}>Find</button>
      </div>
      {mode === "model" && <div className="notice sm" style={{ marginBottom: 10 }}>MODEL SCORE colours the strongest model evidence per account (RF / GNN, <span className="stamp-sv">SYNTHETIC VALIDATION</span>) — corroborating only, never used for authorisation.</div>}
      <section className="stage">
        <div className="stage-h">
          <div><div className="k">Network intelligence · {UMODES.find((m) => m[0] === mode)?.[1]}</div><div className="t">Live Transaction Universe</div></div>
          <UniverseLegend mode={mode} groundTruth={gt} />
        </div>
        <div style={{ position: "relative" }}>
          <LiveUniverse3D mode={mode} groundTruth={gt} autoRotate={orbit && !sel} size="full" selected={sel?.id ?? null} onSelect={onSelect}
                          onInfo={onInfo} taint={taintMap} focus={focus} />
          {sel && <UniverseDrawer id={sel.id} acct={accounts.current.get(sel.id) ?? sel.acct} taint={taint.data ? taintMap.get(sel.id) ?? 0 : undefined}
                                  onClose={() => setSel(null)} onFocus={() => setFocus({ ids: [sel.id], seq: Date.now() })} />}
        </div>
      </section>
    </>
  );
}

export function NetworkPage() {
  const [params, setParams] = useSearchParams();
  const explicit = params.get("tab");
  const v = params.get("view");
  const tab = explicit === "scene" || explicit === "live" ? explicit
    : params.get("focus") || params.get("scenario") || v === "2d" || v === "3d" || v === "scene" ? "scene" : "live";
  return (
    <>
      <PageHead compact crumb="03 · Intelligence" title="Network Intelligence"
        lede={tab === "live"
          ? "Every account and every live posting. Lenses: LIVE STATUS (detection intelligence), RISK (RingWatch network score — on the authorisation path), MODEL SCORE (corroborating), ROLES and TAINT (value traced from confirmed scams)."
          : "Scoped evidence scene with replay, role shapes and an investigation drawer — the suspicious subgraph, an account's neighbourhood or one attack."}
        actions={<Tabs tabs={[["live", "Live universe"], ["scene", "Evidence scene"]]} value={tab}
                       onChange={(t) => setParams(t === "live" ? new URLSearchParams() : new URLSearchParams({ tab: "scene" }), { replace: true })} />} />
      {tab === "live" ? <LiveUniverseView /> : <EvidenceSceneView />}
    </>
  );
}
