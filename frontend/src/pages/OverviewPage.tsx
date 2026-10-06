// OVERVIEW — what is happening now, what needs attention, what value is at risk, which networks are emerging,
// how the detectors agree, which interventions are active, and whether the platform is healthy.
// One metric strip, then three dense columns. Everything is pushed over the console bus; nothing is polled.
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { DecisionSummary, DetectorFamily, GraphScene, IntelOverview, RingRow, ScenarioEvent, ScenarioStatus } from "../api/types";
import { RoleIcon } from "../components/intel";
import { SceneThumb } from "../components/SceneThumb";
import { usePlatform, useConsoleEvents } from "../components/Shell";
import { Async, Bar, Glyph, KV, Metric, PageHead, Panel, Pill, Sim, StatePill, TierPill, Unavailable } from "../components/ui";
import { duration, formatINR, formatPaiseShort, formatTime, handle, pct } from "../lib/format";
import { useDebounced, useLoad, useNow } from "../lib/hooks";
import { rowAge, useInterventionQueue } from "../lib/queue";
import { FAMILY, ROLE_LABEL, scoreStatus, tierStatus } from "../lib/status";

export function OverviewPage() {
  const nav = useNavigate();
  const { metrics: m, system, conn, mode, intelAvailable } = usePlatform();
  const now = useNow(10000);
  const q = useInterventionQueue("open");
  const feed = useLoad<DecisionSummary[]>(() => api.decisions(0));
  const ring = useLoad<RingRow[]>(api.ringwatch);
  const scene = useLoad<GraphScene>(() => api.scene({ cap: 60 }));
  const intel = useLoad<IntelOverview>(api.intelOverview);
  const scen = useLoad<ScenarioStatus[]>(api.scenarios);
  const [stream, setStream] = useState<DecisionSummary[]>([]);
  const [showStream, setShowStream] = useState(false);
  const [fresh, setFresh] = useState<string | null>(null);
  const [events, setEvents] = useState<ScenarioEvent[]>([]);

  const refreshQueue = useDebounced(() => q.rows.reload(), 1200);
  const refreshNet = useDebounced(() => { ring.reload(); scene.reload(); }, 2500);
  const refreshScen = useDebounced(() => scen.reload(), 600);
  useConsoleEvents((e) => {
    if (e.type === "decision.created") {
      const d = e.data as DecisionSummary;
      setStream((s) => [d, ...s].slice(0, 30));
      if (d.source !== "ambient") feed.setData((f) => [d, ...(f ?? []).filter((x) => x.decision_id !== d.decision_id)].slice(0, 40));
      setFresh(d.decision_id);
      if (d.tier >= 2) refreshQueue();
    } else if (e.type === "intent.updated" || e.type.startsWith("breaker.")) refreshQueue();
    if (["ringwatch.scan", "taint.updated", "monitor.finding"].includes(e.type)) refreshNet();
    if (e.type.startsWith("scenario.")) {
      const ev = e.data as ScenarioEvent;
      if (ev?.scenario_id) setEvents((x) => [ev, ...x].slice(0, 30));
      refreshScen();
    }
    if (e.type === "intel.updated") intel.reload();
    if (e.type === "demo.reset") { setStream([]); setEvents([]); feed.reload(); q.rows.reload(); refreshNet(); scen.reload(); }
  });

  const attention = q.all.filter((r) => r.tier >= 2);
  const holds = attention.filter((r) => r.state === "HELD" || r.state === "ESCALATED");
  const feedRows = showStream ? stream : (feed.data ?? []);
  const ruleCounts = useMemo(() => {
    const c = new Map<string, number>();
    (ring.data ?? []).forEach((r) => r.labels.forEach((l) => c.set(l, (c.get(l) ?? 0) + 1)));
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  }, [ring.data]);
  const roleCounts = useMemo(() => {
    const c = new Map<string, number>();
    (ring.data ?? []).forEach((r) => { if (r.role) c.set(r.role, (c.get(r.role) ?? 0) + 1); });
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  }, [ring.data]);
  const tiers = m?.decisions_by_tier ?? {};
  const tierTotal = Object.values(tiers).reduce((a, b) => a + b, 0);
  const activeScen = (scen.data ?? []).filter((s) => s.state !== "idle");

  return (
    <>
      <PageHead crumb="01 · Operate" title="Overview"
        lede="Every payment intent is assessed before the provider is called; most pass silently. Money that does move is watched as a network, and value from confirmed scams is traced downstream." />

      <div className="mstrip" style={{ marginBottom: 12 }}>
        <Metric k="Payments 10m" v={m ? String(m.transactions_last_10m) : "—"} d={m ? `${m.transactions_total.toLocaleString("en-IN")} ledger postings total` : ""} />
        <Metric k="Zero-friction" v={m?.zero_friction_rate != null ? pct(m.zero_friction_rate) : "—"} d={m ? `of ${m.decisions_total.toLocaleString("en-IN")} decisions passed silently` : ""} />
        <Metric k="Attention" v={String(attention.length)} status={attention.length ? "high" : undefined} d={`${holds.length} on hold · tier ≥ 2 open`} />
        <Metric k="Held" v={m ? formatPaiseShort(m.held_paise) : "—"} status={m && m.held_paise ? "held" : undefined} d="scoped to single payments" />
        <Metric k="Suspicious" v={m ? formatPaiseShort(m.suspicious_value_paise) : "—"} status={m && m.suspicious_accounts ? "watch" : undefined} d={m ? `${m.suspicious_accounts} accounts · 72 h` : ""} />
        <Metric k="Traced" v={m ? formatPaiseShort(m.attributable_paise) : "—"} status={m && m.attributable_paise ? "fraud" : undefined} d="LIBR, still attributable" />
        <Metric k="Latency p95" v={m?.latency_p95_ms != null ? `${m.latency_p95_ms.toFixed(0)} ms` : "—"} d={m?.latency_p50_ms != null ? `p50 ${m.latency_p50_ms.toFixed(1)} ms` : ""} />
        <Metric k="Mode" v={mode ? mode.mode.toUpperCase() : "—"} status={mode?.mode === "shadow" ? "watch" : undefined} d={mode?.mode === "shadow" ? "evaluating, not intervening" : "interventions applied"} />
      </div>

      <div className="grid cols-ov align-start">
        {/* ── column A: attention + live decisions ── */}
        <div className="stack">
          <Panel kicker="Needs attention" title="Open interventions · tier ≥ 2" flush
                 actions={<Link className="btn xs ghost" to="/interventions">Queue →</Link>}>
            <Async load={q.rows} what="Intervention queue" endpoint="/api/interventions">
              {() => attention.length === 0 ? <div className="empty">Nothing needs attention. Holds and purpose confirmations appear here the moment they are decided.</div> : (
                <table className="dt compact">
                  <tbody>
                    {attention.slice(0, 8).map((r) => (
                      <tr key={r.decision_id} className="click" onClick={() => nav(`/investigations/decision/${r.decision_id}`)}>
                        <td style={{ width: 44 }}><TierPill tier={r.tier} /></td>
                        <td className="xs"><b>{handle(r.sender_id)}</b> → {handle(r.recipient_id)}<div className="dim ell" style={{ maxWidth: 260 }}>{r.headline}</div></td>
                        <td className="num">{formatINR(r.amount_paise)}</td>
                        <td><StatePill state={r.state} /></td>
                        <td className="mono xs dim nowrap">{duration(rowAge(r, now, q.fetchedAt))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Async>
          </Panel>

          <Panel kicker="Happening now" title="Live decisions" flush
                 actions={<label className="row tight xs muted"><input type="checkbox" checked={showStream} onChange={(e) => setShowStream(e.target.checked)} /> background stream</label>}
                 footer={showStream ? "Background (ambient) payments since this page opened — pushed over the realtime channel." : "Scenario and customer decisions. Tick ‘background stream’ to watch every evaluation."}>
            {feedRows.length === 0 ? <div className="empty">{showStream ? "Waiting for the next background payment…" : "No scenario or customer decisions yet. Start one in the Scenario Lab or pay in Transaction Guard."}</div> : (
              <div className="tscroll" style={{ maxHeight: 380 }}>
                <table className="dt compact">
                  <tbody>
                    {feedRows.slice(0, 30).map((d) => (
                      <tr key={d.decision_id} className={`click ${fresh === d.decision_id ? "flash" : ""}`} onClick={() => nav(`/investigations/decision/${d.decision_id}`)}>
                        <td className="mono xs dim" style={{ width: 62 }}>{formatTime(d.created_at)}</td>
                        <td style={{ width: 44 }}><TierPill tier={d.tier} /></td>
                        <td className="xs">{handle(d.sender_id)} → {handle(d.recipient_id)}<div className="dim ell" style={{ maxWidth: 280 }}>{d.tier === 0 ? "approved silently" : d.labels.join(" · ") || d.headline}</div></td>
                        <td className="num">{formatINR(d.amount_paise)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>

        {/* ── column B: emerging networks + value at risk ── */}
        <div className="stack">
          <Panel kicker="Emerging networks" title="Suspicious subgraph" flush
                 q={scene.data ? `${scene.data.nodes.length} accounts · ${scene.data.edges.length} flows${scene.data.truncated ? ` of ${scene.data.total_candidates}` : ""}` : undefined}
                 actions={<Link className="btn xs" to="/network">Open 3D ↗</Link>}>
            <Async load={scene} what="Graph scene" endpoint="/api/graph/scene">
              {(s) => <SceneThumb scene={s} height={230} onPick={(id) => nav(`/network?focus=${encodeURIComponent(id)}`)} />}
            </Async>
            <Async load={ring} what="RingWatch" endpoint="/api/ringwatch">
              {(list) => list.length === 0 ? <div className="empty">No account currently shows network evidence.</div> : (
                <table className="dt compact">
                  <thead><tr><th>Account</th><th>Role</th><th style={{ width: "32%" }}>Network score</th></tr></thead>
                  <tbody>
                    {list.slice(0, 6).map((r) => (
                      <tr key={r.account_id} className="click" title={r.labels.join(" · ")} onClick={() => nav(`/investigations/account/${encodeURIComponent(r.account_id)}`)}>
                        <td className="xs">{handle(r.account_id)} {r.labelled && <Pill status="fraud">confirmed</Pill>}</td>
                        <td className="xs"><span className="row tight"><RoleIcon role={r.role} />{r.role ? ROLE_LABEL[r.role] ?? r.role : "—"}</span></td>
                        <td><span className="row tight"><span className="grow"><Bar value={r.score} status={scoreStatus(r.score)} /></span><span className="mono xs">{r.score.toFixed(2)}</span></span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Async>
            <div className="panel-f">{ring.data ? `${ring.data.length} accounts with network evidence (score ≥ 0.30)` : ""} · <Link to="/investigations">all accounts →</Link></div>
          </Panel>

          <Panel kicker="Value at risk" title="Where the money is">
            <KV rows={[
              ["Held by Vigil", <span className="mono" style={{ color: m?.held_paise ? "var(--st-held)" : undefined }}>{m ? formatINR(m.held_paise) : "—"}</span>],
              ["Inflow to suspicious accounts (72 h)", <span className="mono">{m ? formatINR(m.suspicious_value_paise) : "—"}</span>],
              ["Traced from confirmed scams (LIBR)", <span className="mono" style={{ color: m?.attributable_paise ? "var(--st-fraud)" : undefined }}>{m ? formatINR(m.attributable_paise) : "—"}</span>],
              ["Challenges overturned", <span className="mono">{m ? `${m.challenges_overturned} of ${m.challenges}` : "—"}</span>],
              ["Ledger conservation", m ? (m.system_total_paise === 0 ? <span className="xs" style={{ color: "var(--st-normal)" }}>balanced · system total ₹0</span> : <span className="xs" style={{ color: "var(--st-critical)" }}>imbalance {formatINR(m.system_total_paise)}</span>) : "—"],
            ]} />
          </Panel>
        </div>

        {/* ── column C: detector agreement, attack feed, system ── */}
        <div className="stack ov-c">
          <Panel kicker="Detector agreement" title="What each detector family sees" flush>
            {intel.data ? (
              <div className="sect">
                {Object.entries(intel.data.detector_agreement).sort((a, b) => b[1] - a[1]).map(([fam, n]) => (
                  <div key={fam} className="barrow"><span className="lbl"><Glyph family={fam as DetectorFamily} /> {FAMILY[fam as DetectorFamily]?.label ?? fam}</span>
                    <Bar value={n} max={Math.max(1, ...Object.values(intel.data!.detector_agreement))} /><span className="val">{n}</span></div>
                ))}
                <div className="xs muted" style={{ marginTop: 4 }}>accounts flagged per family · model families are corroborating evidence (SYNTHETIC VALIDATION)</div>
              </div>
            ) : (
              <div className="sect">
                {intel.unavailable || intelAvailable === false
                  ? <Unavailable what="Model families (RF · GNN · drift · pattern memory)" endpoint="/api/intel/overview" />
                  : intel.loading ? null : intel.error && <div className="notice err sm">{intel.error.message}</div>}
              </div>
            )}
            <div className="sect">
              <div className="sect-t">Rule engine · RingWatch · on the authorisation path</div>
              {ruleCounts.length === 0 ? <div className="xs muted">No network rule fires on any account.</div> : ruleCounts.slice(0, 6).map(([l, n]) => (
                <div key={l} className="barrow"><span className="lbl">{l}</span><Bar value={n} max={Math.max(1, ruleCounts[0][1])} /><span className="val">{n}</span></div>
              ))}
              {roleCounts.length > 0 && <div className="row wrap tight" style={{ marginTop: 6 }}>{roleCounts.map(([r, n]) => <span key={r} className="tag"><RoleIcon role={r} size={11} />&nbsp;{ROLE_LABEL[r] ?? r} {n}</span>)}</div>}
            </div>
            <div className="sect">
              <div className="sect-t">Decisions by tier · since seed</div>
              <div className="dist">{Object.entries(tiers).map(([t, n]) => n > 0 && <span key={t} title={`T${t}: ${n}`} style={{ width: `${(n / Math.max(1, tierTotal)) * 100}%`, background: `var(--st-${tierStatus(Number(t))})` }} />)}</div>
              <div className="row wrap tight xs muted" style={{ marginTop: 4 }}>{Object.entries(tiers).map(([t, n]) => <span key={t}>T{t} <b className="mono ink2">{n}</b></span>)}</div>
            </div>
          </Panel>

          <Panel kicker="Attack & pattern feed" title="Scenarios and pattern alerts" flush actions={<Link className="btn xs ghost" to="/lab">Lab →</Link>}>
            {events.length === 0 && activeScen.length === 0 && !(intel.data?.pattern_alerts.length) ? (
              <div className="empty">No scenario has run since the last reset.</div>
            ) : (
              <div className="sect">
                <div className="tl">
                  {events.slice(0, 6).map((ev, i) => (
                    <div key={`${ev.run_id}-${ev.step}-${i}`} className={`tl-i ${ev.scenario_id.startsWith("atk_") || ev.scenario_id === "s2" ? "hot" : ""}`}>
                      <div className="t">{formatTime(ev.ts)} · {ev.scenario_id} · {ev.step}/{ev.total_steps}</div>
                      <div className="xs">{ev.title}</div>
                    </div>
                  ))}
                  {events.length === 0 && activeScen.map((s) => (
                    <div key={s.id} className={`tl-i ${s.category === "attack" ? "hot" : ""}`}>
                      <div className="t">{s.id} · {s.state} · {s.step}/{s.total_steps}</div>
                      <div className="xs"><Link to={`/lab?s=${s.id}`}>{s.name}</Link>{s.log.length > 0 && <span className="muted"> — {s.log[s.log.length - 1].title}</span>}</div>
                    </div>
                  ))}
                </div>
                {(intel.data?.pattern_alerts ?? []).slice(0, 4).map((p) => (
                  <div key={`${p.account_id}-${p.match.signature_id}`} className="barrow" title="structural similarity, not attribution">
                    <span className="lbl">{handle(p.account_id)} · {p.match.name}</span><Bar value={p.match.similarity} /><span className="val">{pct(p.match.similarity)}</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel kicker="System" title="Platform status" actions={<Link className="btn xs ghost" to="/health">Health →</Link>}>
            <KV rows={[
              ["Realtime", <span className="row tight"><span className={`dot ${conn === "open" ? "ok" : conn === "connecting" ? "warn" : "bad"}`} />{conn === "open" ? "live (push)" : conn}</span>],
              ["Payments", system ? <span>{system.payment_provider === "razorpay_test" ? "Razorpay TEST" : "Mock provider"}{system.gateway.status === "auth_failed" && <span className="xs" style={{ color: "var(--st-watch)" }}> · gateway keys rejected</span>}</span> : "—"],
              ["Intelligence", intelAvailable ? "available" : intelAvailable === false ? <span className="muted">not available</span> : "…"],
              ["External intel", <Sim />],
              ["Graph", system ? <span className="mono xs">{system.graph_nodes} accounts · {system.graph_edges.toLocaleString("en-IN")} edges · v{system.graph_version}</span> : "—"],
              ["ML on decision path", system ? (system.ml_on_decision_path ? "yes" : "no — transparent engine only") : "—"],
            ]} />
          </Panel>
        </div>
      </div>
    </>
  );
}
