// ATTACK SUBGRAPH — the scenario-scoped evidence scene (/api/graph/scene?scenario=) in 3D, coloured by the detector's
// live status, with "Replay from DB": the attack's stored postings (/api/scenarios/{id}/replay) re-played in order.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../api/client";
import type { AccountStatus, GraphScene, ScenarioReplay, ScenarioStatus, SceneEdge, SceneNode } from "../../api/types";
import { formatINR, formatTime, handle } from "../../lib/format";
import { nodeStatus } from "../../lib/graphStyle";
import { useDebounced } from "../../lib/hooks";
import { ACCOUNT_STATUS_HEX, ACCOUNT_STATUS_LABEL, STATUS_HEX, STATUS_LABEL } from "../../lib/status";
import { Graph3D, type Graph3DStyle } from "../Graph3D";
import { useConsoleEvents } from "../Shell";
import { Panel } from "../ui";

export function AttackSubgraph({ scenario, statusOf }: {
  scenario: ScenarioStatus | null; statusOf: (id: string) => AccountStatus | null;
}) {
  const id = scenario?.id ?? null;
  const [scene, setScene] = useState<GraphScene | null>(null);
  const [replay, setReplay] = useState<ScenarioReplay | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const [statusSeq, setStatusSeq] = useState(0);
  const timer = useRef<number | undefined>(undefined);

  const load = useCallback(async () => {
    if (!id) { setScene(null); setReplay(null); return; }
    try {
      const [s, r] = await Promise.all([api.scene({ scenario: id, cap: 80 }), api.scenarioReplay(id).catch(() => null)]);
      setScene((prev) => (prev && prev.version === s.version ? prev : s));
      setReplay(r);
      setErr(null);
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  }, [id]);
  useEffect(() => { setScene(null); setStep(null); load(); }, [load]);
  const refresh = useDebounced(load, 1200);
  const recolour = useDebounced(() => setStatusSeq((n) => n + 1), 800);
  useConsoleEvents((e) => {
    if ((e.type === "scenario.step" || e.type === "scenario.done" || e.type.startsWith("scenario.")) && (e.data as { scenario_id?: string })?.scenario_id === id) refresh();
    if (e.type === "demo.reset") refresh();
    if (e.type === "intel.account_status" || e.type === "intel.tx_scored") recolour();
  });

  // attack postings in stored order (from the DB replay); fall back to the scene's own transactions
  const timeline = useMemo(() => {
    const evs = (replay?.events ?? []).filter((x) => x.tx_id && x.source && x.target);
    if (evs.length) return evs.map((x) => ({ t: Date.parse(x.ts), id: x.tx_id!, source: x.source!, target: x.target!, amount: x.amount_paise ?? 0, title: x.title }));
    const out: { t: number; id: string; source: string; target: string; amount: number; title: string }[] = [];
    (scene?.edges ?? []).forEach((e) => e.txs.forEach((t) => out.push({ t: Date.parse(t.ts), id: t.id, source: e.source, target: e.target, amount: t.amount_paise, title: "" })));
    return out.sort((a, b) => a.t - b.t || a.id.localeCompare(b.id));
  }, [replay, scene]);

  useEffect(() => {
    if (step === null) return;
    if (step >= timeline.length - 1) { timer.current = window.setTimeout(() => setStep(null), 2200); return () => window.clearTimeout(timer.current); }
    timer.current = window.setTimeout(() => setStep((s) => (s === null ? null : s + 1)), 650);
    return () => window.clearTimeout(timer.current);
  }, [step, timeline.length]);

  const attackTx = useMemo(() => new Set((replay?.events ?? []).map((x) => x.tx_id).filter(Boolean) as string[]), [replay]);
  const style = useMemo<Graph3DStyle>(() => {
    void statusSeq;
    const colour = (n: SceneNode) => {
      const st = statusOf(n.id);
      if (st && st !== "normal" && st !== "idle" && st !== "external") return ACCOUNT_STATUS_HEX[st];
      if (n.labelled || n.held) return STATUS_HEX[nodeStatus(n)];
      return n.kind === "external" ? "#4a5260" : ACCOUNT_STATUS_HEX.normal;
    };
    return {
      nodeColor: colour,
      nodeDim: () => false,
      edgeColor: (e: SceneEdge) => (e.tainted_paise > 0 ? STATUS_HEX.fraud : e.txs.some((t) => attackTx.has(t.id)) ? "#e2564e" : "#3b4f6b"),
      ringColor: (n: SceneNode) => (n.labelled ? STATUS_HEX.fraud : n.held ? STATUS_HEX.held : null),
      label: (n: SceneNode) => { const st = statusOf(n.id); return st === "flagged" || st === "held" || st === "confirmed_fraud" ? n.label : null; },
    };
  }, [statusOf, statusSeq, attackTx]);

  const cur = step !== null ? timeline[Math.min(step, timeline.length - 1)] : null;
  const hoverText = useCallback((n: SceneNode) => {
    const st = statusOf(n.id);
    return `${n.label} · ${st ? ACCOUNT_STATUS_LABEL[st] : STATUS_LABEL[nodeStatus(n)]}${n.role && n.role !== "normal" ? ` · ${n.role}` : ""}`;
  }, [statusOf]);
  const hoverEdgeText = useCallback((e: SceneEdge) => `${handle(e.source)} → ${handle(e.target)} · ${formatINR(e.amount_paise)} · ${e.count}×`, []);
  const noop = useCallback(() => undefined, []);
  const txCount = timeline.length;

  return (
    <Panel kicker="Attack subgraph" title={scenario ? `${scenario.id} · ${scenario.name}` : "No attack selected"} flush
           actions={<>
             {scene && <span className="chip mute">{scenario?.step ?? 0}/{scenario?.total_steps ?? 0} steps · {scene.nodes.length} accounts</span>}
             <button className="btn sm" disabled={!txCount} onClick={() => setStep(step === null ? 0 : null)}>{step === null ? "Replay from DB" : "Stop replay"}</button>
             {id && <Link className="btn sm ghost" to={`/network?view=scene&scenario=${id}`}>Open ↗</Link>}
           </>}
           footer={<>Edges are the attack's stored postings; node colours are the detector's live status (amber = early warning, red = flagged, violet = held). Replay plays the postings in ledger order from the database.</>}>
      <div className="net" style={{ height: 520, minHeight: 0, margin: "0 16px", borderRadius: 18 }}>
        <div className="net-canvas">
          {scene && scene.nodes.length > 0 && (
            <Graph3D scene={scene} style={style} selected={null} selectedEdge={null} replayT={cur ? cur.t : null} replayWindowMs={700}
                     focusSeq={0} onSelect={noop} onSelectEdge={noop} hoverText={hoverText} hoverEdgeText={hoverEdgeText} />
          )}
        </div>
        {!scenario && <div className="net-empty">Select an attack pattern in the Command Center.</div>}
        {scenario && scene && scene.nodes.length === 0 && <div className="net-empty">This pattern has not run since the last reset.<br />Spawn it to see its subgraph form here.</div>}
        {scenario && !scene && !err && <div className="net-empty"><span className="spinner lg" /></div>}
        {err && <div className="net-empty">{err}</div>}
        {cur && (
          <div className="net-replay">
            <span className="mono">{(step ?? 0) + 1}/{timeline.length}</span>
            <span className="now">{formatTime(new Date(cur.t).toISOString())}</span>
            <span className="mono xs ell">{cur.id} · {handle(cur.source)} → {handle(cur.target)} · {formatINR(cur.amount)}</span>
          </div>
        )}
      </div>
    </Panel>
  );
}
