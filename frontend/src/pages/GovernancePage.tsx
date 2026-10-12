// GOVERNANCE & AUDIT — how a bank governs Vigil: operating mode (ACTIVE / SHADOW) with the bank-baseline vs
// Vigil comparison, the versioned policy (weights, ladder, named adjustments), registered models, operator
// actions, decision records (→ structured record, raw JSON, replay) and deployment positioning.
import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { DecisionRecord, DecisionSummary, GovernanceSummary, InterventionRow, PolicyView } from "../api/types";
import { TiersOverTimeChart } from "../components/live/LiveStatsCharts";
import { usePlatform, useConsoleEvents } from "../components/Shell";
import { Async, Bar, Glyph, KV, Metric, PageHead, Panel, Pill, Sim, Tabs, TierPill } from "../components/ui";
import { DIM_LABEL, formatINR, formatStamp, humanKey, pct } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";
import { useLiveStats } from "../lib/live";
import { DIM_GLYPH, STATUS_LABEL, TIER_SHORT, tierStatus } from "../lib/status";

type Tab = "oversight" | "records" | "positioning";
type PolicyExtra = PolicyView & { corroboration?: Record<string, unknown>; adjustments?: Record<string, unknown> };

export function GovernancePage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "oversight";
  return (
    <>
      <PageHead crumb="Control" title="Governance & audit"
        lede="How a bank would govern Vigil: start in SHADOW (evaluate, record, never intervene), compare against the bank's baseline, then enable the intervention ladder. Every decision is an append-only, versioned record that can be inspected raw and replayed." />
      <div style={{ marginBottom: 12 }}>
        <Tabs tabs={[["oversight", "Mode · policy · models"], ["records", "Decision records"], ["positioning", "Deployment positioning"]]}
              value={tab} onChange={(t) => setParams(t === "oversight" ? {} : { tab: t }, { replace: true })} />
      </div>
      {tab === "oversight" && <Oversight />}
      {tab === "records" && <Records />}
      {tab === "positioning" && <Positioning />}
    </>
  );
}

// ── mode, shadow comparison, policy, models ──────────────────────────────────
function Oversight() {
  const { refreshMode } = usePlatform();
  const sum = useLoad<GovernanceSummary>(api.governance);
  const recent = useLoad<DecisionSummary[]>(() => api.decisions(0));
  const shadowRows = useLoad<InterventionRow[]>(() => api.interventions("all"));
  const live = useLiveStats(5000);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const refresh = useDebounced(() => { sum.reload(); recent.reload(); shadowRows.reload(); }, 1500);
  useConsoleEvents((e) => {
    if (["mode.changed", "demo.reset", "intent.updated"].includes(e.type)) refresh();
    else if (e.type === "decision.created" && ((e.data as { source?: string })?.source ?? "ambient") !== "ambient") refresh();
  });

  const setMode = async (m: "active" | "shadow") => {
    const text = m === "shadow"
      ? "Switch Vigil to SHADOW mode? New payments are still evaluated and recorded, but Vigil will not intervene — the bank's baseline decision is applied."
      : "Switch Vigil to ACTIVE mode? New payments receive Vigil's intervention ladder.";
    if (!window.confirm(text)) return;
    setBusy(true); setErr(null);
    try { await api.setMode(m); refreshMode(); sum.reload(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  // Baseline vs Vigil, per decision: scenario/customer decisions + any shadow-mode alerts, newest 12.
  const ids = useMemo(() => {
    const out: { id: string; ts: string }[] = [];
    (recent.data ?? []).forEach((d) => out.push({ id: d.decision_id, ts: d.created_at }));
    (shadowRows.data ?? []).filter((r) => r.mode === "shadow").forEach((r) => out.push({ id: r.decision_id, ts: r.opened_at }));
    const seen = new Set<string>();
    return out.sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts)).filter((x) => (seen.has(x.id) ? false : (seen.add(x.id), true))).slice(0, 12).map((x) => x.id);
  }, [recent.data, shadowRows.data]);
  const records = useLoad<DecisionRecord[]>(async () => {
    const rs = await Promise.all(ids.map((id) => api.record(id).catch(() => null)));
    return rs.filter((r): r is DecisionRecord => !!r);
  }, [ids.join(",")]);

  return (
    <Async load={sum} what="Governance summary" endpoint="/api/governance/summary">
      {(s) => {
        const pol = s.policy as PolicyExtra;
        const total = Object.values(s.decisions_by_tier).reduce((a, b) => a + b, 0);
        const shadow = s.mode.mode === "shadow";
        return (
          <div className="stack loose">
            {err && <div className="notice err">{err}</div>}
            <div className="grid cols-2 align-start">
              <Panel kicker="Operating mode" title={shadow ? "SHADOW — evaluating, not intervening" : "ACTIVE — interventions applied before payment"}
                     actions={<div className="seg" role="radiogroup" aria-label="Operating mode">
                       <button role="radio" aria-checked={!shadow} className={!shadow ? "on" : ""} disabled={busy || !shadow} onClick={() => setMode("active")}>Active</button>
                       <button role="radio" aria-checked={shadow} className={shadow ? "on" : ""} disabled={busy || shadow} onClick={() => setMode("shadow")}>Shadow</button>
                     </div>}>
                <div className="stack">
                  <KV c4 rows={[
                    ["Mode", <Pill status={shadow ? "watch" : "normal"}>{s.mode.mode}</Pill>], ["Since", s.mode.since ? formatStamp(s.mode.since) : "start of run"],
                  ]} />
                  <div className="md ink2">{s.mode.note}</div>
                  <ol className="steps">
                    <li><b>Shadow.</b> Vigil evaluates every payment and records its recommendation beside the bank's baseline (approve / OTP step-up / decline). No customer sees a Vigil intervention.</li>
                    <li><b>Measure.</b> False challenges avoided, frauds the baseline missed, agreement rate — the comparison on the right.</li>
                    <li><b>Enable tiers.</b> Switch to ACTIVE; the ladder (inform → confirm → hold → hold + CircuitBreaker) is applied before the provider is called.</li>
                  </ol>
                </div>
              </Panel>
              <Panel kicker="Shadow comparison" title="Bank baseline vs Vigil recommendation" q="recorded on every decision">
                <div className="mstrip dense" style={{ marginBottom: 10, gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
                  <Metric k="Shadow" v={String(s.shadow.evaluated)} d="decisions evaluated" />
                  <Metric k="Vigil" v={String(s.shadow.vigil_would_intervene)} d="would intervene (T2+)" />
                  <Metric k="Baseline" v={String(s.shadow.baseline_would_challenge)} d="would challenge" />
                  <Metric k="Agreement" v={s.shadow.agreement_rate === null ? "—" : pct(s.shadow.agreement_rate)} d={s.shadow.evaluated ? "both challenge, or both pass" : "no shadow decisions yet"} />
                </div>
                <Async load={records} what="Decision records" endpoint="/api/decisions/{id}/record">
                  {(rs) => rs.length === 0 ? <div className="empty">No decisions yet. Decisions appear here as payments are assessed.</div> : (
                    <table className="dt compact">
                      <thead><tr><th>Decision</th><th>Mode</th><th className="num">Amount</th><th>Vigil</th><th>Applied</th><th>Bank baseline</th><th>Agree</th></tr></thead>
                      <tbody>
                        {rs.map((r) => {
                          const d = r.decision;
                          const rec = d.recommended_tier ?? d.tier;
                          const base = d.baseline?.decision;
                          const agree = base ? (rec >= 2) === (base !== "approve") : null;
                          return (
                            <tr key={d.decision_id}>
                              <td className="mono xs"><Link to={`/governance/decision/${d.decision_id}`}>{d.decision_id}</Link></td>
                              <td>{d.mode === "shadow" ? <Pill status="watch">shadow</Pill> : <span className="xs dim">active</span>}</td>
                              <td className="num">{formatINR(d.amount_paise)}</td>
                              <td><TierPill tier={rec} /></td>
                              <td>{d.applied_tier == null ? <span className="dim xs">—</span> : <TierPill tier={d.applied_tier} />}</td>
                              <td className="xs" title={d.baseline?.reason}>{base ? base.replace(/_/g, " ") : <span className="dim">not recorded</span>}</td>
                              <td className="xs">{agree === null ? "—" : agree ? "yes" : <b>no</b>}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </Async>
                <div className="xs muted" style={{ marginTop: 6 }}>Agreement uses the server's definition: Vigil recommends tier ≥ 2 exactly when the baseline challenges. The baseline is a simple bank rule (e.g. OTP step-up for high value), recorded for comparison only.</div>
              </Panel>
            </div>

            <div className="grid cols-ms align-start">
              <Panel kicker="Policy" title={<span className="mono">{pol.version}</span>} q="transparent, versioned — the only thing on the authorisation path"
                     footer={pol.note}>
                <div className="grid cols-2 align-start">
                  <div>
                    <div className="up" style={{ marginBottom: 4 }}>Dimension weights</div>
                    {Object.entries(pol.weights).map(([k, w]) => (
                      <div key={k} className="barrow"><span className="lbl"><Glyph code={DIM_GLYPH[k]} /> {DIM_LABEL[k] ?? k}</span><Bar value={w} max={0.5} /><span className="val">{w.toFixed(2)}</span></div>
                    ))}
                    {pol.corroboration && (
                      <div style={{ marginTop: 10 }}>
                        <div className="up" style={{ marginBottom: 4 }}>Corroboration</div>
                        <KV rows={Object.entries(pol.corroboration).map(([k, v]) => [humanKey(k), <span className="mono">{String(v)}</span>])} />
                      </div>
                    )}
                  </div>
                  <div>
                    <div className="up" style={{ marginBottom: 4 }}>Intervention ladder</div>
                    <table className="dt compact">
                      <thead><tr><th>Tier</th><th>Final score</th><th>Action</th></tr></thead>
                      <tbody>
                        {pol.ladder.map((l, i) => (
                          <tr key={l.tier}>
                            <td><TierPill tier={l.tier} /></td>
                            <td className="mono xs nowrap">{i === 0 ? "0" : pol.ladder[i - 1].below.toFixed(2)} – {l.below > 1 ? "1.00" : `< ${l.below.toFixed(2)}`}</td>
                            <td className="xs">{l.title}<div className="dim">{l.kind.replace(/_/g, " ")}</div></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
                {pol.adjustments && (
                  <div style={{ marginTop: 10 }}>
                    <div className="up" style={{ marginBottom: 4 }}>Named adjustments (floors · guards)</div>
                    <div className="grid cols-3 align-start">
                      {Object.entries(pol.adjustments).map(([k, v]) => (
                        <div key={k} className="trace-col">
                          <div className="mono xs b" style={{ marginBottom: 4 }}>{k}</div>
                          {v && typeof v === "object"
                            ? <KV rows={Object.entries(v as Record<string, unknown>).map(([a, b]) => [humanKey(a), <span className="mono xs">{typeof b === "object" ? JSON.stringify(b) : String(b)}</span>])} />
                            : <span className="mono xs">{String(v)}</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </Panel>
              <div className="stack">
                <Panel kicker="Decisions" title={`${total.toLocaleString("en-IN")} by tier`} q="all sources, since seed">
                  <div className="dist" style={{ marginBottom: 8 }}>
                    {Object.entries(s.decisions_by_tier).map(([t, n]) => n > 0 && <span key={t} title={`T${t}: ${n}`} style={{ width: `${(n / Math.max(1, total)) * 100}%`, background: `var(--st-${tierStatus(Number(t))})` }} />)}
                  </div>
                  <div className="chart-shell" style={{ marginBottom: 10 }}>
                    <div className="chart-h">{live.data?.tiers_over_time?.length ? "Per minute · live" : "Since seed"}</div>
                    <TiersOverTimeChart stats={live.data} tierMix={s.decisions_by_tier} height={190} />
                  </div>
                  <table className="dt compact"><tbody>
                    {Object.entries(s.decisions_by_tier).map(([t, n]) => (
                      <tr key={t}><td style={{ width: 60 }}><TierPill tier={Number(t)} /></td><td className="xs muted">{TIER_SHORT[Number(t)]?.split(" · ")[1]}</td><td className="num">{n.toLocaleString("en-IN")}</td><td className="num xs dim">{pct(n / Math.max(1, total), 1)}</td></tr>
                    ))}
                  </tbody></table>
                </Panel>
                <Panel kicker="Models" title="Registered models" q="corroborating evidence only" flush>
                  {s.models.length === 0 ? (
                    <div className="sect"><div className="xs muted">No model is registered on this server (the detection-intelligence layer, <span className="mono">/api/intel/models</span>, is not merged yet). The authorisation path uses only the transparent policy engine; operational component versions are on each decision record.</div></div>
                  ) : (
                    <table className="dt compact">
                      <thead><tr><th>Model</th><th>Version</th><th>Status</th><th>Use</th></tr></thead>
                      <tbody>{s.models.map((m) => (
                        <tr key={m.model_id}><td className="xs">{m.model_id}</td><td className="mono xs">{m.version}</td><td><Pill status={m.status === "active" ? "normal" : "unknown"}>{m.status}</Pill></td><td className="xs muted">{m.operational_use}</td></tr>
                      ))}</tbody>
                    </table>
                  )}
                  <div className="panel-f"><Link to="/detection">Detection & Models →</Link> · <span className="banner-val" style={{ display: "inline-flex", padding: "1px 6px" }}><span className="stamp" style={{ padding: "2px 5px" }}>SYNTHETIC VALIDATION</span></span></div>
                </Panel>
              </div>
            </div>

            <Panel kicker="Audit trail" title="Recent operator, customer and contact actions" flush q="intent transitions by humans (newest 15)">
              {s.recent_actions.length === 0 ? <div className="empty">No human action recorded yet.</div> : (
                <table className="dt compact">
                  <thead><tr><th>Time</th><th>Actor</th><th>Intent</th><th>New state</th><th>Detail</th></tr></thead>
                  <tbody>{s.recent_actions.map((a, i) => (
                    <tr key={i}><td className="mono xs">{formatStamp(a.ts)}</td><td className="xs"><span className="tag">{a.actor}</span></td><td className="mono xs">{a.intent_id}</td><td className="xs">{a.to_state.replace(/_/g, " ").toLowerCase()}</td><td className="xs muted">{a.detail}</td></tr>
                  ))}</tbody>
                </table>
              )}
            </Panel>
          </div>
        );
      }}
    </Async>
  );
}

// ── decision records ─────────────────────────────────────────────────────────
function Records() {
  const nav = useNavigate();
  const [id, setId] = useState("");
  const recent = useLoad<DecisionSummary[]>(() => api.decisions(0));
  const alerts = useLoad<InterventionRow[]>(() => api.interventions("all"));
  const rows = useMemo(() => {
    const out = new Map<string, { id: string; ts: string; sender: string; recipient: string; amount: number; tier: number; kind: string; origin: string }>();
    (recent.data ?? []).forEach((d) => out.set(d.decision_id, { id: d.decision_id, ts: d.created_at, sender: d.sender_id, recipient: d.recipient_id, amount: d.amount_paise, tier: d.tier, kind: d.kind, origin: d.source ?? "scenario/customer" }));
    (alerts.data ?? []).forEach((r) => { if (!out.has(r.decision_id)) out.set(r.decision_id, { id: r.decision_id, ts: r.opened_at, sender: r.sender_id, recipient: r.recipient_id, amount: r.amount_paise, tier: r.tier, kind: r.kind, origin: "stream" }); });
    return [...out.values()].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
  }, [recent.data, alerts.data]);
  const go = (e: FormEvent) => { e.preventDefault(); const v = id.trim().toUpperCase(); if (v) nav(`/governance/decision/${/^\d+$/.test(v) ? `DEC-${v.padStart(6, "0")}` : v}`); };
  return (
    <div className="grid cols-ms align-start">
      <Panel kicker="Records" title="Recent decision records" flush q="scenario / customer decisions + intervention alerts"
             footer="Each record is append-only and carries a SHA-256 of its payload (an integrity check, not a signature).">
        <Async load={recent} what="Decisions" endpoint="/api/decisions">
          {() => rows.length === 0 ? <div className="empty">No decisions recorded yet.</div> : (
            <div className="tscroll" style={{ maxHeight: "calc(100vh - 290px)" }}>
              <table className="dt compact">
                <thead><tr><th>Decision</th><th>Time</th><th>Sender → recipient</th><th className="num">Amount</th><th>Tier</th><th>Action</th><th>Origin</th></tr></thead>
                <tbody>{rows.map((r) => (
                  <tr key={r.id} className="click" onClick={() => nav(`/governance/decision/${r.id}`)}>
                    <td className="mono xs">{r.id}</td><td className="mono xs">{formatStamp(r.ts)}</td>
                    <td className="xs">{r.sender.replace("@vigil", "")} → {r.recipient.replace("@vigil", "")}</td>
                    <td className="num">{formatINR(r.amount)}</td><td><TierPill tier={r.tier} /></td>
                    <td className="xs">{r.kind.replace(/_/g, " ")}</td><td className="xs muted">{r.origin}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Async>
      </Panel>
      <Panel kicker="Lookup" title="Open a record by id">
        <form className="row tight" onSubmit={go}>
          <input className="input sm grow" placeholder="DEC-000003 or 3" value={id} onChange={(e) => setId(e.target.value)} aria-label="Decision id" />
          <button className="btn sm" type="submit" disabled={!id.trim()}>Open</button>
        </form>
        <div className="xs muted" style={{ marginTop: 8 }}>A record shows: decision id · transaction intent · timestamp · signals available · data provenance · model and policy versions · subscores · thresholds · reason codes · chosen action · operator / customer actions · payment result — with VIEW RAW RECORD and REPLAY DECISION.</div>
      </Panel>
    </div>
  );
}

// ── deployment positioning (v1 "About", kept) ────────────────────────────────
const LAYERS: [string, string, string, string][] = [
  ["Bank / payment app", "Customer initiates a payment. In this prototype: the Transaction Guard customer device.", "Built (demo UI)", "normal"],
  ["Existing institutional intelligence", "Bank EFRMS / AML, MuleHunter.AI deployments (RBIH), a DPIP-style shared registry, the I4C suspect registry, DoT FRI. Vigil consumes such signals through one adapter.", "Simulated (LocalRegistryProvider)", "sim"],
  ["Vigil pre-commit decision engine", "Fuses external + network + journey + behaviour + context evidence at commit time; picks a proportionate intervention; explains it three ways.", "Built", "normal"],
  ["Pass / explain / challenge / hold / escalate", "Interrupt ladder. Holds are scoped to the payment amount; no account freeze exists.", "Built", "normal"],
  ["Payment provider / rail", "Called only after approval. Simulated rail behind a provider port: a bank plugs its own rail in here. No real money moves.", "Built (simulated)", "normal"],
  ["Post-transaction monitoring", "Ledger + incremental graph; RingWatch re-scores; TaintTrace attributes value from confirmed scams (LIBR / pro rata).", "Built", "normal"],
  ["Model intelligence (RF · GNN · drift · pattern memory)", "Corroborating evidence beside the decision; never fused into the tier. Validated on synthetic data only.", "In progress (intelligence layer)", "watch"],
];
const LIFECYCLE: [string, string][] = [
  ["Intent", "Customer presses Pay. No money moves."],
  ["Evaluate", "External · network · journey · behaviour · context"],
  ["Fuse + explain", "Versioned weights, named adjustments, ReasonLine"],
  ["Interrupt ladder", "Pass · inform · confirm · hold · hold + CircuitBreaker"],
  ["Provider", "Simulated rail — only after approval"],
  ["Ledger + PathGraph", "Double-entry posting; edge appended incrementally"],
  ["RingWatch / TaintTrace", "Network re-scored; confirmed scams traced"],
  ["Next decision", "Inherits what the network just learned"],
];

function Positioning() {
  return (
    <div className="stack loose" style={{ maxWidth: 1180 }}>
      <Panel kicker="Positioning" title="Where Vigil sits">
        <div className="stack md ink2" style={{ maxWidth: 940 }}>
          <div>India already has serious detection: bank EFRMS and AML systems, RBIH's <b>MuleHunter.AI</b> deployed at banks, the RBI-led <b>Digital Payments Intelligence Platform (DPIP)</b> being built for shared intelligence, I4C's <b>NCRP / 1930</b> reporting and suspect registry, and DoT's Financial Fraud Risk Indicator.</div>
          <div><b style={{ color: "var(--ink)" }}>Vigil is not another fraud classifier and does not replace any of these.</b> It is the bank-side layer that turns those signals — plus local journey and network evidence — into an explainable, proportionate intervention at the last reversible moment, then watches where the money goes and feeds that back into the next decision.</div>
          <div className="notice warn sm">Vigil has no access to RBI, NPCI, RBIH, I4C or DoT systems. External intelligence in this prototype is simulated and labelled <Sim /> wherever it appears. All data is synthetic.</div>
        </div>
      </Panel>
      <Panel kicker="Who hosts what" title="Layers" flush>
        <table className="dt">
          <thead><tr><th style={{ width: "24%" }}>Layer</th><th>What happens</th><th style={{ width: "22%" }}>In this prototype</th></tr></thead>
          <tbody>{LAYERS.map(([a, b, c, s]) => (
            <tr key={a}><td><b>{a}</b></td><td className="md ink2">{b}</td><td className="xs">{s === "sim" ? <><Sim /> {c}</> : s === "watch" ? <Pill status="watch">{c}</Pill> : c}</td></tr>
          ))}</tbody>
        </table>
      </Panel>
      <Panel kicker="Lifecycle" title="One payment, end to end" q="pre-commit (left of the provider) · post-transaction (right)">
        <div className="lifecycle">
          {LIFECYCLE.map(([t, d], i) => (
            <div key={t} className={`lc ${i < 4 ? "pre" : i === 4 ? "rail" : "post"}`}><span className="mono xs dim">{String(i + 1).padStart(2, "0")}</span><b>{t}</b><span className="xs muted">{d}</span></div>
          ))}
        </div>
      </Panel>
      <div className="xs muted">Status colours used throughout: {(["normal", "watch", "high", "critical", "held", "fraud"] as const).map((k) => STATUS_LABEL[k]).join(" · ")}. Module-by-module positioning: docs/REAL_WORLD_POSITIONING.md · limitations: docs/KNOWN_LIMITATIONS.md.</div>
    </div>
  );
}
