// INVESTIGATION CASE — one intervention, end to end:
// case header → DECISION REPLAY (playback; subscores and tier evolve per frame) → RISK EVOLUTION (markers say why)
// → WHAT WOULD MAKE IT SAFE (deterministic counterfactual ladder) → ReasonLine (explains the OPERATIONAL DECISION)
// beside detector consensus / SHAP (explains the MODEL) → evidence PROVENANCE → money trace → actions.
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type {
  AccountSummary, Counterfactual, DecisionRecord, DecisionReplay, Dimension, Investigation, RiskDecisionV2, RiskPoint,
} from "../api/types";
import { InterventionShown, Outcome } from "../components/Assessment";
import { ReasonLinePanel, SIMULATED_DIMS, Timeline } from "../components/Decision";
import { AccountIntelBlock, DetectorTable } from "../components/intel";
import { MoneyTrace } from "../components/MoneyTrace";
import { CounterfactualLadder, DecisionReplayView, ProvenanceTable, RiskEvolution } from "../components/Replay";
import { SceneThumb } from "../components/SceneThumb";
import { useConsoleEvents } from "../components/Shell";
import { AskVigilance } from "../components/vigilance/Vigilance";
import { Async, Bar, ErrorNote, Glyph, KV, Loading, Metric, PageHead, Panel, Pill, Seg, Sim, StatePill, Tabs, TierPill } from "../components/ui";
import { duration, formatDateTime, formatINR, formatStamp, formatTime, handle } from "../lib/format";
import { sceneFromEvidence } from "../lib/graphStyle";
import { useDebounced, useLoad } from "../lib/hooks";
import { DIM_GLYPH, tierStatus } from "../lib/status";

const DIM_FAMILY: Record<Dimension, string> = {
  network: "Rule engine · RingWatch (recipient network)",
  sequence: "TrailScore (sender journey)",
  behaviour: "Behaviour (sender history)",
  context: "Context (ContextFlag)",
  external: "External intelligence",
};

export function CasePage() {
  const { decisionId = "" } = useParams();
  const loc = useLocation();
  const nav = useNavigate();
  const inv = useLoad<Investigation>(() => api.investigate(decisionId), [decisionId]);
  const replay = useLoad<DecisionReplay>(() => api.replay(decisionId), [decisionId]);
  const cfs = useLoad<Counterfactual[]>(() => api.counterfactuals(decisionId), [decisionId]);
  const record = useLoad<DecisionRecord>(() => api.record(decisionId), [decisionId]);
  const [who, setWho] = useState<"sender" | "recipient">("sender");
  const [modelWho, setModelWho] = useState<"recipient" | "sender">("recipient");
  const [tab, setTab] = useState<"journey" | "intervention" | "parties">("journey");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const d = inv.data?.decision;
  const it = inv.data?.intent;
  const riskAcct = d ? (who === "sender" ? d.sender_id : d.recipient_id) : null;
  const timeline = useLoad<RiskPoint[] | null>(() => (riskAcct ? api.riskTimeline(riskAcct) : Promise.resolve(null)), [riskAcct]);

  const refresh = useDebounced(() => { inv.reload(); record.reload(); }, 500);
  useConsoleEvents((e) => {
    const data = e.data as { intent_id?: string } | null;
    if (e.type === "intent.updated" && it && data?.intent_id === it.intent_id) refresh();
    else if (["breaker.responded", "breaker.fired", "taint.updated"].includes(e.type)) refresh();
    else if (e.type === "demo.reset") { inv.reload(); replay.reload(); cfs.reload(); record.reload(); timeline.reload(); }
  });

  useEffect(() => {
    if (loc.hash === "#replay" && replay.data) document.getElementById("replay")?.scrollIntoView({ block: "start" });
  }, [loc.hash, replay.data]);

  const act = async (action: "release" | "reject") => {
    if (!it) return;
    setBusy(true); setErr(null);
    try { await api.bankAction(it.intent_id, action); inv.reload(); record.reload(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const netScene = useMemo(() => (inv.data ? sceneFromEvidence(inv.data.graph) : null), [inv.data]);

  if (inv.error && !inv.data) {
    return (
      <>
        <PageHead crumb={<Link to="/investigations">Investigations</Link>} title={`Case ${decisionId}`} />
        <ErrorNote error={inv.error} />
      </>
    );
  }
  if (!inv.data || !d || !it) return <Loading text="Loading case" />;
  const x = inv.data;
  const d2 = (record.data?.decision ?? d) as RiskDecisionV2;
  const held = it.state === "HELD" || it.state === "ESCALATED";
  const cb = x.circuit_breaker[0];
  const ladder = record.data?.thresholds;
  const signalCount = d.dimensions.reduce((s, k) => s + k.signals.length, 0);
  const famFired = d.dimensions.filter((k) => k.signals.length > 0).length;

  return (
    <>
      <PageHead crumb={<><Link to="/investigations">Investigations</Link> / case <span className="mono">{d.decision_id}</span></>}
        title={<span className="row wrap tight"><TierPill tier={d.tier} lg full /> <span>{handle(d.sender_id)} → {handle(d.recipient_id)} · <span className="mono">{formatINR(d.amount_paise)}</span></span></span>}
        lede={d.reasons.analyst.summary}
        actions={<>
          {held && <button className="btn sm ok" disabled={busy} onClick={() => act("release")}>Release hold</button>}
          {held && <button className="btn sm danger" disabled={busy} onClick={() => act("reject")}>Reject payment</button>}
          <AskVigilance entities={[d.sender_id, d.recipient_id]}
                        prompt={`Explain case ${d.decision_id}: ${handle(d.sender_id)} paying ${handle(d.recipient_id)} ${formatINR(d.amount_paise)}. Why this tier, who is the recipient, and what should I do next?`} />
          <Link className="btn sm" to={`/governance/decision/${d.decision_id}`}>Decision record</Link>
          <Link className="btn sm ghost" to={`/network?focus=${encodeURIComponent(d.recipient_id)}`}>Recipient network ↗</Link>
        </>} />
      {err && <div className="notice err" style={{ marginBottom: 10 }}>{err}</div>}

      <div className="mstrip inv-tiles case-tiles" style={{ marginBottom: 20 }}>
        <Metric k="Final score" v={d.final_score.toFixed(3)} d={`base ${d.base_score.toFixed(3)} · ${d.adjustments.length} adjustment${d.adjustments.length === 1 ? "" : "s"}`} status={tierStatus(d.tier)} />
        <Metric k="Intervention" v={<span style={{ fontSize: 13 }}>{d.intervention.title}</span>} d={d.intervention.kind.replace(/_/g, " ")} />
        <Metric k="State" v={<StatePill state={it.state} />} d={`${it.source} · ${formatTime(it.updated_at)}`} />
        <Metric k="Scoped hold" v={x.hold ? formatINR(x.hold.held_paise) : "—"} status={x.hold && !x.hold.outcome ? "held" : undefined}
                d={x.hold ? (x.hold.outcome ?? `review by ${formatTime(x.hold.review_by)}`) : "no hold"} />
        <Metric k="Trusted contact" v={cb ? (cb.response?.replace(/_/g, " ") ?? "awaiting") : "—"} d={cb ? `${String(cb.payload.contact_name ?? "contact")} · alerted ${formatTime(cb.fired_at)}` : "CircuitBreaker not used"} />
        <Metric k="Evidence" v={`${signalCount} signals`} d={`${famFired} of 5 families fired`} />
        <Metric k="Mode" v={(d2.mode ?? "active").toUpperCase()} status={d2.mode === "shadow" ? "watch" : undefined}
                d={d2.baseline ? `bank baseline: ${d2.baseline.decision.replace(/_/g, " ")}` : "no baseline recorded"} />
        <Metric k="Evaluated" v={`${d.latency_ms.toFixed(1)} ms`} d={`${formatDateTime(d.created_at)} · ${d.policy_version.split("+")[0]}`} />
      </div>

      <div className="stack loose">
        <Panel id="replay" kicker="Decision Replay" title="How the state built up to this intervention"
               q="play it: each frame re-scores the evidence known at that moment"
               actions={replay.data && <span className="xs dim mono">policy {replay.data.policy_version.split("+")[0]}</span>} flush>
          <Async load={replay} what="Decision Replay" endpoint="/api/decisions/{id}/replay">
            {(r) => <DecisionReplayView frames={r.frames} ladder={ladder} note={r.note} />}
          </Async>
        </Panel>

        <div className="grid cols-2 align-start">
          <Panel kicker="Risk evolution" title={`${handle(riskAcct ?? "")} · risk over time`} q="markers say why the score moved"
                 actions={<Seg options={[["sender", "Sender"], ["recipient", "Recipient"]]} value={who} onChange={setWho} />}>
            <Async load={timeline} what="Risk evolution" endpoint="/api/accounts/{id}/risk-timeline"
                   empty={<div className="empty">No evaluation events recorded for this account.</div>}>
              {(pts) => pts.length === 0
                ? <div className="empty">{who === "recipient" ? "This account has not initiated an evaluated payment; its risk appears on the sender's timeline and in network evidence." : "No evaluation events recorded for this account."}</div>
                : <RiskEvolution points={pts} ladder={ladder} decisionId={d.decision_id} onPickDecision={(id) => nav(`/investigations/decision/${id}`)} />}
            </Async>
          </Panel>
          <Panel kicker="Why · what would make it safe" title="Counterfactual ladder" q="deterministic re-runs of the policy engine">
            <Async load={cfs} what="Counterfactuals" endpoint="/api/decisions/{id}/counterfactuals">
              {(items) => <CounterfactualLadder items={items} tier={d.tier} score={d.final_score} />}
            </Async>
          </Panel>
        </div>

        <div className="grid cols-2 align-start">
          <Panel kicker="ReasonLine" title="Explains the OPERATIONAL DECISION" q="transparent policy engine — the only thing on the authorisation path">
            <ReasonLinePanel decision={d} />
          </Panel>
          <Panel kicker="Detector consensus · SHAP" title="Explains the MODEL" q="corroborating evidence — never sets the tier" flush
                 actions={<Seg options={[["recipient", "Recipient"], ["sender", "Sender"]]} value={modelWho} onChange={setModelWho} />}>
            <div className="sect">
              <div className="sect-t">Families on the authorisation path · this decision</div>
              <table className="dt compact">
                <thead><tr><th>Family</th><th style={{ width: "34%" }}>Value</th><th>Kind</th><th className="num">Signals</th></tr></thead>
                <tbody>
                  {d.dimensions.map((k) => (
                    <tr key={k.dimension}>
                      <td><span className="row tight"><Glyph code={DIM_GLYPH[k.dimension]} /><span>{DIM_FAMILY[k.dimension]}</span>{SIMULATED_DIMS.includes(k.dimension) && (k.dimension === "external" || k.signals.length > 0) && <Sim />}</span></td>
                      <td><span className="row tight"><span className="grow"><Bar value={k.score} /></span><span className="mono xs">{k.score.toFixed(2)}</span></span></td>
                      <td className="xs muted">score</td>
                      <td className="num">{k.signals.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="sect">
              <div className="sect-t">Model evidence recorded on the decision</div>
              {(d2.model_evidence ?? []).length
                ? <DetectorTable detectors={d2.model_evidence!} compact />
                : <div className="xs muted">None recorded: the decision was made by the transparent engine; model families (RF · GNN · drift · early warning · pattern memory) are attached only when the intelligence layer is available.</div>}
            </div>
            <div className="sect" style={{ paddingBottom: 2 }}>
              <div className="sect-t">{modelWho === "recipient" ? "Recipient" : "Sender"} · {handle(modelWho === "recipient" ? d.recipient_id : d.sender_id)} · account intelligence</div>
            </div>
            <AccountIntelBlock accountId={modelWho === "recipient" ? d.recipient_id : d.sender_id} compact />
          </Panel>
        </div>

        <Panel kicker="Evidence provenance" title="Every material signal: source · value · observed at · freshness · version · status"
               flush footer={record.data ? <span className="mono">model versions: {Object.entries(record.data.model_versions).map(([k, v]) => `${k} ${v}`).join(" · ")}</span> : undefined}>
          <Async load={record} what="Decision record" endpoint="/api/decisions/{id}/record">
            {(r) => <ProvenanceTable record={r} />}
          </Async>
        </Panel>

        <div className="grid cols-2 align-start">
          <Panel kicker="Money trace" title="Value traced from confirmed scams" q="LIBR and pro rata side by side">
            <MoneyTrace incidents={x.money_trace} focus={d.recipient_id} />
          </Panel>
          <Panel kicker="Recipient network" title={`${handle(d.recipient_id)} · last 72 h`} flush
                 q={`${x.graph.nodes.length} accounts · ${x.graph.edges.length} flows`}
                 actions={<>
                   <Link className="btn xs" to={`/network?focus=${encodeURIComponent(d.recipient_id)}&hops=1`}>3D · 1-hop</Link>
                   <Link className="btn xs" to={`/network?focus=${encodeURIComponent(d.recipient_id)}&hops=2`}>2-hop</Link>
                 </>}
                 footer="Static layered projection of the recipient's neighbourhood (money flows left → right). Colour = status; magenta = traced from a confirmed scam.">
            {netScene && <SceneThumb scene={netScene} height={230} focus={d.recipient_id}
                                     onPick={(id) => nav(`/investigations/account/${encodeURIComponent(id)}`)} />}
          </Panel>
        </div>

        <div className="grid cols-ms align-start">
          <section className="panel">
            <Tabs tabs={[["journey", "Sender journey"], ["intervention", "Intervention & lifecycle"], ["parties", "Parties"]]} value={tab} onChange={setTab} />
            <div className="panel-b">
              {tab === "journey" && <Timeline items={x.timeline} empty="No journey events in the 60-minute window before this payment." />}
              {tab === "intervention" && (
                <div className="grid cols-2 align-start"><InterventionShown decision={d} intent={it} /><Outcome intent={it} record={record.data} /></div>
              )}
              {tab === "parties" && (
                <div className="grid cols-2 align-start">
                  <Party title="Sender" a={x.sender} />
                  <Party title="Recipient" a={x.recipient} />
                  {x.external_intel && (
                    <div className="span-all">
                      <div className="up">External intelligence on the recipient <Sim /></div>
                      <div className="row wrap md" style={{ marginTop: 4 }}>
                        <Pill status={x.external_intel.status === "confirmed_mule" ? "fraud" : x.external_intel.status === "reported" ? "high" : x.external_intel.status === "watchlist" ? "watch" : "normal"}>{x.external_intel.status.replace("_", " ")}</Pill>
                        <span className="mono xs">risk {x.external_intel.risk_score.toFixed(2)}</span>
                        {x.external_intel.reason_codes.map((c) => <span key={c} className="tag mono">{c}</span>)}
                        <span className="xs muted">{x.external_intel.source} · {formatStamp(x.external_intel.last_updated)}</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
          <Panel kicker="Next steps" title="What an investigator does next">
            <ol className="steps">
              {held && (
                <li>
                  <b>Decide the hold.</b> {x.hold && <>{formatINR(x.hold.held_paise)} held · {x.hold.reference} · review by {formatTime(x.hold.review_by)}{cb && <> · contact said <b>{cb.response?.replace(/_/g, " ") ?? "nothing yet"}</b></>}.</>}
                  <div className="row tight" style={{ marginTop: 4 }}>
                    <button className="btn xs ok" disabled={busy} onClick={() => act("release")}>Release hold</button>
                    <button className="btn xs danger" disabled={busy} onClick={() => act("reject")}>Reject payment</button>
                  </div>
                </li>
              )}
              <li><b>Check the recipient.</b> Network evidence, detector consensus and risk history:{" "}
                <Link to={`/investigations/account/${encodeURIComponent(d.recipient_id)}`}>{handle(d.recipient_id)}</Link></li>
              <li><b>Check the sender.</b> Journey, drift and prior payments:{" "}
                <Link to={`/investigations/account/${encodeURIComponent(d.sender_id)}`}>{handle(d.sender_id)}</Link></li>
              <li><b>Follow the money.</b> Expand the recipient in 3D (<Link to={`/network?focus=${encodeURIComponent(d.recipient_id)}&hops=2`}>2-hop</Link>); a verified victim report can be confirmed from the account drawer to start TaintTrace.</li>
              <li><b>Record.</b> Audit-grade record with raw JSON: <Link to={`/governance/decision/${d.decision_id}`}>{d.decision_id}</Link>{it.transitions.length > 0 && <> · last transition {duration((Date.now() - Date.parse(it.transitions[it.transitions.length - 1].ts)) / 1000)} ago</>}</li>
            </ol>
          </Panel>
        </div>
      </div>
    </>
  );
}

function Party({ title, a }: { title: string; a: AccountSummary }) {
  return (
    <div>
      <div className="up" style={{ marginBottom: 4 }}>{title}</div>
      <KV rows={[
        ["Account", <><Link to={`/investigations/account/${encodeURIComponent(a.id)}`}><b>{a.display_name}</b></Link> <span className="mono xs dim">{a.id}</span></>],
        ["Profile", a.persona ?? a.kind],
        ["Opened", formatDateTime(a.opened_at)],
        ["Balance", <span className="mono">{formatINR(a.balance_paise)}{a.held_paise > 0 && <span style={{ color: "var(--st-held)" }}> · held {formatINR(a.held_paise)}</span>}</span>],
        ["Devices", <span className="mono xs">{a.devices.join(", ") || "—"}</span>],
        ["Trusted contact", a.trusted_contact ? `${a.trusted_contact.name} (${a.trusted_contact.relation}) ${a.trusted_contact.phone_masked}` : "none"],
      ]} />
    </div>
  );
}
