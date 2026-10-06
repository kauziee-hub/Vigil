// DECISION RECORD — the audit view of one decision, structured from /api/decisions/{id}/record:
// identity · transaction intent · signals available · provenance · model + policy versions · subscores ·
// thresholds · reason codes · chosen action · operator / customer actions · payment result · evaluation context.
// VIEW RAW RECORD shows the exact JSON; REPLAY DECISION opens the Decision Replay.
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { DecisionRecord } from "../api/types";
import { AuditView, CustomerView, ReasonLinePanel, SIMULATED_DIMS } from "../components/Decision";
import { ProvenanceTable } from "../components/Replay";
import { useConsoleEvents } from "../components/Shell";
import { Async, Bar, Glyph, KV, PageHead, Panel, Pill, Sim, StatePill, Tabs, TierPill } from "../components/ui";
import { DIM_LABEL, STATE_LABEL, formatDateTime, formatINR, formatStamp, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";
import { DIM_GLYPH, tierStatus } from "../lib/status";

export function RecordPage() {
  const { decisionId = "" } = useParams();
  const rec = useLoad<DecisionRecord>(() => api.record(decisionId), [decisionId]);
  const [raw, setRaw] = useState(false);
  const [view, setView] = useState<"analyst" | "customer" | "audit">("analyst");
  const [copied, setCopied] = useState(false);
  const refresh = useDebounced(() => rec.reload(), 500);
  useConsoleEvents((e) => {
    if (e.type === "intent.updated" && rec.data && (e.data as { intent_id?: string })?.intent_id === rec.data.intent.intent_id) refresh();
  });
  const copy = async () => {
    if (!rec.data) return;
    try { await navigator.clipboard.writeText(JSON.stringify(rec.data, null, 2)); setCopied(true); window.setTimeout(() => setCopied(false), 1500); }
    catch { setCopied(false); }
  };

  return (
    <>
      <PageHead crumb={<><Link to="/governance?tab=records">07 · Governance & Audit</Link> / record</>}
        title={<>Decision record <span className="mono">{decisionId}</span></>}
        lede="Append-only, versioned. Every value below is read from the stored record; nothing is recomputed in the browser."
        actions={<>
          <button className={`btn sm ${raw ? "on" : ""}`} onClick={() => setRaw(!raw)} disabled={!rec.data}>{raw ? "Hide raw record" : "View raw record"}</button>
          <Link className="btn sm primary" to={`/investigations/decision/${decisionId}#replay`}>Replay decision</Link>
          <Link className="btn sm ghost" to={`/investigations/decision/${decisionId}`}>Investigate</Link>
        </>} />
      <Async load={rec} what="Decision record" endpoint="/api/decisions/{id}/record">
        {(r) => {
          const d = r.decision;
          const it = r.intent;
          const audit = (d.reasons.audit ?? {}) as Record<string, unknown>;
          const ctx = audit.evaluation_context as { local_hour_ist?: number; local_hour_source?: string } | undefined;
          const iv = d.intervention;
          return (
            <div className="stack loose">
              {raw && (
                <Panel kicker="Raw record" title={<span className="mono">GET /api/decisions/{d.decision_id}/record</span>}
                       actions={<button className="btn xs" onClick={copy}>{copied ? "Copied" : "Copy JSON"}</button>}
                       footer={<span className="mono">payload sha256 {d.payload_sha256}</span>}>
                  <pre className="raw">{JSON.stringify(r, null, 2)}</pre>
                </Panel>
              )}

              <div className="grid cols-2 align-start">
                <Panel kicker="Identity" title="Decision and transaction intent">
                  <KV c4 rows={[
                    ["Decision", <span className="mono">{d.decision_id}</span>], ["Intent", <span className="mono">{it.intent_id}</span>],
                    ["Timestamp", <span className="mono">{formatStamp(d.created_at)}</span>], ["Source", it.source],
                    ["Sender", <Link to={`/investigations/account/${encodeURIComponent(d.sender_id)}`}>{handle(d.sender_id)}</Link>],
                    ["Recipient", <Link to={`/investigations/account/${encodeURIComponent(d.recipient_id)}`}>{handle(d.recipient_id)}</Link>],
                    ["Amount", <b className="mono">{formatINR(d.amount_paise)}</b>], ["Channel", it.channel],
                    ["Device", <span className="mono xs">{it.device_id ?? "not supplied"}</span>], ["Note · purpose", `${it.note ?? "—"} · ${it.purpose ?? "—"}`],
                    ["Policy version", <span className="mono xs">{d.policy_version}</span>], ["Evaluated in", `${d.latency_ms.toFixed(1)} ms`],
                  ]} />
                  {ctx && (
                    <div className="xs muted" style={{ marginTop: 8 }}>
                      Evaluation context: local hour <b className="mono">{String(ctx.local_hour_ist ?? "—")}</b> IST · {ctx.local_hour_source ?? "source not recorded"}
                      {ctx.local_hour_source && /pinned/i.test(ctx.local_hour_source) && " (scripted scenarios evaluate at a fixed hour so they are reproducible)"}
                    </div>
                  )}
                </Panel>
                <Panel kicker="Chosen action" title={<span className="row tight"><TierPill tier={d.tier} full lg /> {iv.title}</span>}>
                  <KV rows={[
                    ["Final score", <span className="row tight"><b className="mono" style={{ color: `var(--st-${tierStatus(d.tier)})` }}>{d.final_score.toFixed(3)}</b><span className="xs muted mono">base {d.base_score.toFixed(3)}</span></span>],
                    ["Intervention", `${iv.kind.replace(/_/g, " ")} — ${iv.customer_action}`],
                    ["Bank action", iv.bank_action],
                    ["Scoped hold", iv.hold_paise ? <span className="mono" style={{ color: "var(--st-held)" }}>{formatINR(iv.hold_paise)}{it.hold_id ? ` · ${it.hold_id}` : ""}</span> : "none"],
                    ["CircuitBreaker", iv.circuit_breaker ? "trusted contact alerted" : "not used"],
                    ["Mode", <span className="row tight">{d.mode === "shadow" ? <Pill status="watch">shadow — not applied</Pill> : <span>active</span>}
                      {d.recommended_tier != null && <span className="xs muted">Vigil recommended T{d.recommended_tier}</span>}
                      {d.applied_tier != null && <span className="xs muted">· applied T{d.applied_tier}</span>}</span>],
                    ["Bank baseline", d.baseline ? <span>{d.baseline.decision.replace(/_/g, " ")} <span className="xs muted">— {d.baseline.reason}</span></span> : "not recorded"],
                    ["Current state", <StatePill state={it.state} />],
                  ]} />
                </Panel>
              </div>

              <div className="grid cols-2 align-start">
                <Panel kicker="Signals available · subscores" title="Dimensions evaluated" flush>
                  <table className="dt compact">
                    <thead><tr><th>Dimension</th><th style={{ width: "30%" }}>Subscore</th><th className="num">Weight</th><th className="num">Contrib.</th><th className="num">Signals</th></tr></thead>
                    <tbody>{d.dimensions.map((x) => (
                      <tr key={x.dimension}>
                        <td><span className="row tight"><Glyph code={DIM_GLYPH[x.dimension]} />{DIM_LABEL[x.dimension]}{SIMULATED_DIMS.includes(x.dimension) && (x.dimension === "external" || x.signals.length > 0) && <Sim />}</span></td>
                        <td><span className="row tight"><span className="grow"><Bar value={x.score} /></span><span className="mono xs">{x.score.toFixed(2)}</span></span></td>
                        <td className="num">{(r.weights[x.dimension] ?? x.weight).toFixed(2)}</td>
                        <td className="num">{x.contribution.toFixed(3)}</td>
                        <td className="num">{x.signals.length}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                  <div className="sect">
                    <div className="sect-t">Reason codes</div>
                    <div className="row wrap tight">{r.reason_codes.map((c) => <span key={c} className="tag mono">{c}</span>)}{!r.reason_codes.length && <span className="xs muted">none</span>}</div>
                    {d.adjustments.length > 0 && <div className="stack tight" style={{ marginTop: 8 }}>{d.adjustments.map((a) => (
                      <div key={a.rule_id} className="xs"><span className="mono">{a.rule_id}</span> <span className="tag">{a.kind}</span> <b className="mono">{a.effect}</b> <span className="muted">{a.reason}</span></div>
                    ))}</div>}
                  </div>
                </Panel>
                <Panel kicker="Thresholds" title="Policy ladder at decision time" flush>
                  <table className="dt compact">
                    <thead><tr><th>Tier</th><th>Final score range</th><th>Action</th></tr></thead>
                    <tbody>{r.thresholds.map((l, i) => (
                      <tr key={l.tier} className={l.tier === d.tier ? "sel" : ""}>
                        <td><TierPill tier={l.tier} /></td>
                        <td className="mono xs nowrap">{i === 0 ? "0.00" : r.thresholds[i - 1].below.toFixed(2)} – {l.below > 1 ? "1.00" : `< ${l.below.toFixed(2)}`}</td>
                        <td className="xs">{l.title}{l.tier === d.tier && <b> ← this decision</b>}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                  <div className="sect">
                    <div className="sect-t">Model / component versions</div>
                    <KV rows={Object.entries(r.model_versions).map(([k, v]) => [k, <span className="mono xs">{v}</span>])} />
                  </div>
                </Panel>
              </div>

              <Panel kicker="Data provenance" title="Source · value · observed at · freshness · version · status" flush>
                <ProvenanceTable record={r} />
              </Panel>

              <div className="grid cols-2 align-start">
                <Panel kicker="Operator / customer actions" title="Who did what after the decision" flush>
                  <table className="dt compact">
                    <thead><tr><th>Time</th><th>Actor</th><th>State</th><th>Detail</th></tr></thead>
                    <tbody>
                      {it.transitions.map((t, i) => (
                        <tr key={i}><td className="mono xs">{formatTime(t.ts)}</td><td className="xs"><span className="tag">{t.actor}</span></td>
                          <td className="xs">{STATE_LABEL[t.to_state] ?? t.to_state}</td><td className="xs muted">{t.detail}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  {r.operator_actions.length === 0 && <div className="sect xs muted">No operator (bank / customer / contact) action recorded on this decision yet.</div>}
                </Panel>
                <Panel kicker="Payment result" title="Provider and ledger">
                  <KV rows={[
                    ["Provider", r.payment_result ? <span>{r.payment_result.provider === "razorpay_test" ? "Razorpay TEST" : "Mock provider"} · {r.payment_result.status} <Sim text={r.payment_result.label} /></span> : <span className="dim">not called</span>],
                    ["Payment id", <span className="mono xs">{r.payment_result?.payment_id ?? r.payment_result?.order_id ?? "—"}</span>],
                    ["Ledger", r.ledger_transaction ? <span className="mono xs">{r.ledger_transaction.id} · seq {r.ledger_transaction.seq} · {formatINR(r.ledger_transaction.amount_paise)} · {formatDateTime(r.ledger_transaction.ts)}</span> : <span className="dim">no posting</span>],
                  ]} />
                  {!r.payment_result && <div className="notice info sm" style={{ marginTop: 8 }}>No money has moved for this intent. The provider is called only after approval or a bank release.</div>}
                </Panel>
              </div>

              <Panel flush title={<span>One decision, three renderings · deterministic templates, no language model</span>}>
                <div style={{ padding: "0 12px" }}><Tabs tabs={[["analyst", "Bank analyst (ReasonLine)"], ["customer", "Customer"], ["audit", "Audit payload"]]} value={view} onChange={setView} /></div>
                <div className="panel-b">
                  {view === "analyst" && <ReasonLinePanel decision={d} />}
                  {view === "customer" && <CustomerView decision={d} />}
                  {view === "audit" && <AuditView decision={d} />}
                </div>
              </Panel>
            </div>
          );
        }}
      </Async>
    </>
  );
}
