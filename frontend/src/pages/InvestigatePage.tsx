import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { DecisionSummary, Investigation } from "../api/types";
import { ReasonLinePanel as ContributionPanel, CustomerView, AuditView, Timeline } from "../components/Decision";
import { Sim as SimChip, TierPill as TierChip } from "../components/ui";
import { EvidenceGraph } from "../components/EvidenceGraph";
import { MoneyTrace } from "../components/MoneyTrace";
import { useConsoleEvents } from "../components/Shell";
import { STATE_LABEL, formatDateTime, formatINR, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";

export function InvestigatePage() {
  const { decisionId } = useParams();
  const nav = useNavigate();
  const queue = useLoad<DecisionSummary[]>(() => api.decisions(1));
  const inv = useLoad<Investigation | null>(() => (decisionId ? api.investigate(decisionId) : Promise.resolve(null)), [decisionId]);
  const [tab, setTab] = useState<"timeline" | "trace" | "actions" | "customer" | "audit">("timeline");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const refresh = useDebounced(() => { queue.reload(); if (decisionId) inv.reload(); }, 400);

  useConsoleEvents((e) => {
    if (["decision.created", "intent.updated", "breaker.responded", "taint.updated", "demo.reset", "breaker.fired"].includes(e.type)) refresh();
  });

  const act = async (action: "release" | "reject") => {
    if (!inv.data) return;
    setBusy(true); setErr(null);
    try { await api.bankAction(inv.data.intent.intent_id, action); await inv.reload(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const d = inv.data?.decision;
  const it = inv.data?.intent;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="spread">
        <div><h1>Bank investigation</h1><div className="small muted">Every intervention, with the evidence that produced it.</div></div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: decisionId ? "260px minmax(0,1fr)" : "1fr", gap: 16 }} className="inv-outer">
        <div className="card" style={{ padding: 10, alignSelf: "start", maxHeight: "calc(100vh - 140px)", overflowY: "auto" }}>
          <div className="upper" style={{ padding: "4px 6px" }}>Interventions (Tier ≥ 1)</div>
          {(queue.data ?? []).length === 0 && <div className="empty">No interventions yet.</div>}
          {(queue.data ?? []).map((q) => (
            <div key={q.decision_id} className="feed-item" style={{ gridTemplateColumns: "1fr", background: q.decision_id === decisionId ? "var(--brand-soft)" : undefined }}
                 onClick={() => nav(`/investigate/${q.decision_id}`)}>
              <div className="spread"><TierChip tier={q.tier} /><span className="mono small muted">{formatTime(q.created_at)}</span></div>
              <div className="who ellipsis">{handle(q.sender_id)} → {handle(q.recipient_id)} · <b className="mono">{formatINR(q.amount_paise)}</b></div>
              <div className="why ellipsis">{q.labels.join(" · ")}</div>
            </div>
          ))}
        </div>

        {decisionId && (
          <div className="stack" style={{ gap: 16, minWidth: 0 }}>
            {inv.error && <div className="notice error">{inv.error.message}</div>}
            {inv.loading && !inv.data && <div className="card"><div className="spinner" /></div>}
            {d && it && inv.data && (
              <>
                <div className="card">
                  <div className="spread wrap">
                    <div className="row wrap">
                      <TierChip tier={d.tier} lg />
                      <b style={{ fontSize: 16 }}>{handle(d.sender_id)} → {handle(d.recipient_id)} · <span className="mono">{formatINR(d.amount_paise)}</span></b>
                      <span className="chip">{STATE_LABEL[it.state]}</span>
                    </div>
                    <div className="row">
                      {(it.state === "HELD" || it.state === "ESCALATED") && (
                        <>
                          <button className="btn good sm" disabled={busy} onClick={() => act("release")}>Release hold</button>
                          <button className="btn danger sm" disabled={busy} onClick={() => act("reject")}>Reject payment</button>
                        </>
                      )}
                      <Link className="btn sm" to={`/decision/${d.decision_id}`}>Explain (3 views)</Link>
                    </div>
                  </div>
                  <div className="small muted" style={{ marginTop: 6 }}>{d.reasons.analyst.summary} · {d.intervention.bank_action}</div>
                  {err && <div className="notice error" style={{ marginTop: 8 }}>{err}</div>}
                </div>

                <div className="grid-inv">
                  <div className="card stack">
                    <h3>Payment & accounts</h3>
                    <div className="small"><span className="upper">Intent</span><br /><span className="mono">{it.intent_id}</span> · {it.source} · {formatDateTime(it.created_at)}{it.note && <> · “{it.note}”</>}</div>
                    <AccountBlock title="Sender" a={inv.data.sender} />
                    <AccountBlock title="Recipient" a={inv.data.recipient} />
                    {inv.data.external_intel && (
                      <div className="q-block small"><div className="q">Registry <SimChip /></div>
                        <b>{inv.data.external_intel.status}</b> · {inv.data.external_intel.reason_codes.join(", ") || "—"}<br />
                        <span className="muted">{inv.data.external_intel.source}</span></div>
                    )}
                    {inv.data.hold && (
                      <div className="q-block small"><div className="q">Scoped hold</div>
                        {formatINR(inv.data.hold.held_paise)} · {inv.data.hold.reference}<br />
                        review by {formatTime(inv.data.hold.review_by)} · {inv.data.hold.outcome ?? "active"}</div>
                    )}
                    {inv.data.circuit_breaker.map((cb) => (
                      <div key={cb.id} className="q-block small"><div className="q">CircuitBreaker</div>
                        Sent to {String(cb.payload.contact_name)} ({String(cb.payload.relation)}) at {formatTime(cb.fired_at)}<br />
                        Response: <b>{cb.response ? cb.response.replace("_", " ") : "awaiting"}</b>{cb.responded_at && ` · ${formatTime(cb.responded_at)}`}</div>
                    ))}
                  </div>
                  <div className="card"><h3>Why: contribution by dimension</h3><ContributionPanel decision={d} /></div>
                  <div className="card stack">
                    <div className="card-title"><h3>Recipient network</h3><Link className="small" to={`/network?focus=${encodeURIComponent(d.recipient_id)}`}>expand →</Link></div>
                    <EvidenceGraph evidence={inv.data.graph} compact height={300} selected={d.recipient_id}
                                   onNodeClick={(id) => nav(`/network?focus=${encodeURIComponent(id)}`)} />
                    <div className="small muted">Last 72 h of money movements around the recipient. Red = value traced to a confirmed scam.</div>
                  </div>
                </div>

                <div className="card">
                  <div className="tabs">
                    {([["timeline", "Event timeline"], ["trace", "Money trace"], ["actions", "Policy & action history"], ["customer", "Customer view"], ["audit", "Audit record"]] as const)
                      .map(([k, l]) => <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>)}
                  </div>
                  {tab === "timeline" && (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                      <div><div className="upper" style={{ marginBottom: 6 }}>Sender journey (last 60 min)</div>
                        <Timeline items={inv.data.timeline} />
                        {d.dimensions.find((x) => x.dimension === "sequence")!.score > 0 && (
                          <div className="notice small">Nothing here individually proves anything. Together, in a few minutes, the sequence is highly abnormal.</div>
                        )}</div>
                      <div><div className="upper" style={{ marginBottom: 6 }}>Recipient network features</div>
                        <table className="data"><tbody>
                          {Object.entries(d.reasons.analyst.network).filter(([, v]) => typeof v !== "object" || v === null).map(([k, v]) => (
                            <tr key={k}><td className="muted">{k}</td><td className="mono">{String(v)}</td></tr>
                          ))}
                        </tbody></table></div>
                    </div>
                  )}
                  {tab === "trace" && <MoneyTrace incidents={inv.data.money_trace} focus={d.recipient_id} />}
                  {tab === "actions" && (
                    <table className="data">
                      <thead><tr><th>Time</th><th>State</th><th>Actor</th><th>Detail</th></tr></thead>
                      <tbody>{it.transitions.map((t, i) => (
                        <tr key={i}><td className="mono small">{formatTime(t.ts)}</td><td>{STATE_LABEL[t.to_state] ?? t.to_state}</td>
                          <td>{t.actor}</td><td className="small">{t.detail}</td></tr>
                      ))}</tbody>
                    </table>
                  )}
                  {tab === "customer" && <CustomerView decision={d} />}
                  {tab === "audit" && <AuditView decision={d} />}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function AccountBlock({ title, a }: { title: string; a: Investigation["sender"] }) {
  return (
    <div className="q-block small">
      <div className="q">{title}</div>
      <b>{a.display_name}</b> <span className="mono muted">{a.id}</span><br />
      {a.persona && <span className="muted">{a.persona}<br /></span>}
      opened {formatDateTime(a.opened_at)} · balance <span className="mono">{formatINR(a.balance_paise)}</span>
      {a.held_paise > 0 && <> · held <span className="mono">{formatINR(a.held_paise)}</span></>}<br />
      devices: <span className="mono">{a.devices.join(", ") || "—"}</span>
      {a.trusted_contact && <><br />trusted contact: {a.trusted_contact.name} ({a.trusted_contact.relation})</>}
    </div>
  );
}
