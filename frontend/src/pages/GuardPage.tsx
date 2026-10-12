// TRANSACTION GUARD — customer device on the left, the bank's pre-commit assessment of the same payment
// on the right: sender · recipient · amount · relationship · device · behaviour · network · external ·
// journey · context → decision → intervention → provider / ledger / monitoring outcome.
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { AccountSummary, DecisionRecord, PolicyView, RiskDecision, TransactionIntent } from "../api/types";
import { AssessmentTable, CaseLinks, CaseMeta, InterventionShown, Outcome } from "../components/Assessment";
import { CustomerDevice, type DeviceState, type Prefill } from "../components/CustomerDevice";
import { useConsoleEvents, usePlatform } from "../components/Shell";
import { Metric, PageHead, Panel, StatePill, TierPill } from "../components/ui";
import { formatINR, formatTime, handle, pct } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";

export function GuardPage() {
  const [params, setParams] = useSearchParams();
  const payer = params.get("as") || "ramesh@vigil";
  const [prefill, setPrefill] = useState<Prefill | null>(null);
  const [device, setDevice] = useState<DeviceState>({ intent: null, decision: null });
  const [picked, setPicked] = useState<{ intent: TransactionIntent; decision: RiskDecision | null } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const { metrics: m, mode, health } = usePlatform();
  const recent = useLoad<TransactionIntent[]>(() => api.intents(payer), [payer]);
  const refreshRecent = useDebounced(() => recent.reload(), 800);

  useEffect(() => { setPicked(null); }, [payer]);
  // prefill from the test console (/guard?as=&to=&amount=&note=&context=), then drop those params
  useEffect(() => {
    const to = params.get("to");
    if (!to) return;
    setPrefill({ to, amount: params.get("amount") ?? "", note: params.get("note") ?? "", context: params.get("context") ?? undefined, nonce: Date.now() });
    setParams({ as: payer }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.get("to")]);
  // the device always wins: a new payment on the phone replaces a historical selection
  useEffect(() => { if (device.intent) setPicked(null); }, [device.intent?.intent_id]);

  const intent = device.intent && device.decision ? device.intent : picked?.intent ?? null;
  const decision = device.intent && device.decision ? device.decision : picked?.decision ?? null;

  useConsoleEvents((e) => {
    if (e.type === "intent.updated") {
      const it = e.data as TransactionIntent;
      if (it.sender_id === payer) refreshRecent();
      if (picked && it.intent_id === picked.intent.intent_id) setPicked({ ...picked, intent: it });
    } else if (e.type === "demo.reset") { setPicked(null); recent.reload(); }
  });

  const pick = async (id: string) => {
    setErr(null);
    try { const r = await api.intent(id); setPicked({ intent: r.intent, decision: r.decision }); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  };

  return (
    <>
      <PageHead crumb="Operate" title="Transaction guard"
        lede="Every payment intent is assessed before the provider is called. The customer sees one proportionate intervention; the bank sees the full case."
        actions={<a className="btn sm ghost" href={`/pay?as=${encodeURIComponent(payer)}`} target="_blank" rel="noreferrer">Customer kiosk ↗</a>} />
      <div className="guard">
        <div className="stack">
          <CustomerDevice payer={payer} onPayerChange={(p) => setParams({ as: p })} onChange={setDevice} prefill={prefill} />
        </div>

        <div className="stack loose" style={{ minWidth: 0 }}>
          <div className="mstrip dense guard-kpis">
            <Metric k="Decision p50 · p95" v={m?.latency_p50_ms != null ? `${m.latency_p50_ms.toFixed(1)} · ${m.latency_p95_ms?.toFixed(1) ?? "—"} ms` : "—"} d="pre-commit evaluation" />
            <Metric k="Zero friction" v={m?.zero_friction_rate != null ? pct(m.zero_friction_rate, 1) : "—"} d="payments passed at Tier 0" />
            <Metric k="Decisions" v={m ? m.decisions_total.toLocaleString("en-IN") : "—"} d={`policy ${health?.policy_version.split("+")[0] ?? "…"}`} />
            <Metric k="Open interventions" v={m ? String(m.open_interventions) : "—"} status={m && m.open_interventions ? "held" : undefined} d={m ? `held ${formatINR(m.held_paise)}` : ""} />
            <Metric k="Mode" v={mode ? mode.mode.toUpperCase() : "—"} status={mode?.mode === "shadow" ? "watch" : undefined} d={mode?.mode === "shadow" ? "recommend only" : "interventions applied"} />
          </div>
          {err && <div className="notice err">{err}</div>}
          {intent && decision ? (
            <CaseView intent={intent} decision={decision} historical={!device.intent && !!picked} />
          ) : (
            <Panel kicker="Pre-commit assessment" title="No payment under assessment"
                   q={`Submit a payment on ${handle(payer)}'s phone, or open a recent intent below.`}>
              <PolicyPrimer />
            </Panel>
          )}
          <Panel kicker="History" title={`Recent intents · ${handle(payer)}`} flush>
            {recent.data && recent.data.length === 0 && <div className="empty">No intents yet for this customer.</div>}
            {recent.data && recent.data.length > 0 && (
              <table className="dt compact">
                <thead><tr><th>Time</th><th>Intent</th><th>Recipient</th><th className="num">Amount</th><th>Tier</th><th>State</th><th>Source</th></tr></thead>
                <tbody>
                  {recent.data.slice(0, 8).map((it) => (
                    <tr key={it.intent_id} className={`click ${intent?.intent_id === it.intent_id ? "sel" : ""}`} onClick={() => pick(it.intent_id)}>
                      <td className="mono xs">{formatTime(it.created_at)}</td>
                      <td className="mono xs">{it.intent_id}</td>
                      <td>{handle(it.recipient_id)}</td>
                      <td className="num">{formatINR(it.amount_paise)}</td>
                      <td><TierPill tier={it.tier} /></td>
                      <td><StatePill state={it.state} /></td>
                      <td className="xs muted">{it.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>
      </div>
    </>
  );
}

function CaseView({ intent, decision, historical }: { intent: TransactionIntent; decision: RiskDecision; historical: boolean }) {
  const [sender, setSender] = useState<AccountSummary | null>(null);
  const [recipient, setRecipient] = useState<AccountSummary | null>(null);
  const [record, setRecord] = useState<DecisionRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.account(intent.sender_id).then((a) => live && setSender(a)).catch(() => live && setSender(null));
    api.account(intent.recipient_id).then((a) => live && setRecipient(a)).catch(() => live && setRecipient(null));
    return () => { live = false; };
  }, [intent.sender_id, intent.recipient_id, decision.decision_id]);
  useEffect(() => {
    let live = true;
    api.record(decision.decision_id).then((r) => live && setRecord(r)).catch(() => live && setRecord(null));
    return () => { live = false; };
  }, [decision.decision_id, intent.state]);

  const act = async (action: "release" | "reject") => {
    setBusy(true); setErr(null);
    try { await api.bankAction(intent.intent_id, action); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const held = intent.state === "HELD" || intent.state === "ESCALATED";

  return (
    <>
      <Panel kicker={historical ? "Pre-commit assessment · historical" : "Pre-commit assessment"}
             title={<>{handle(intent.sender_id)} → {handle(intent.recipient_id)} · <span className="mono">{formatINR(intent.amount_paise)}</span></>}
             actions={<>
               {held && <button className="btn sm ok" disabled={busy} onClick={() => act("release")}>Release hold</button>}
               {held && <button className="btn sm danger" disabled={busy} onClick={() => act("reject")}>Reject payment</button>}
             </>}
             footer={<div className="spread wrap"><CaseMeta decision={decision} intent={intent} /><CaseLinks decisionId={decision.decision_id} /></div>} flush>
        {err && <div className="notice err" style={{ margin: 10 }}>{err}</div>}
        <AssessmentTable decision={decision} intent={intent} sender={sender} recipient={recipient} record={record} />
      </Panel>
      <div className="grid cols-2 align-start">
        <Panel kicker="Intervention" title="Exactly what the customer was shown"><InterventionShown decision={decision} intent={intent} /></Panel>
        <Panel kicker="Outcome" title="Provider · ledger · monitoring"><Outcome intent={intent} record={record} /></Panel>
      </div>
    </>
  );
}

/** What Vigil checks before money moves — read live from the versioned policy (no hard-coded weights). */
function PolicyPrimer() {
  const policy = useLoad<PolicyView>(api.policy);
  const p = policy.data;
  const DIM: Record<string, [string, string]> = {
    external: ["External intelligence", "registry / consortium reports on the recipient (simulated)"],
    network: ["Network (RingWatch)", "fan-in, pass-through, chains, rings, confirmed-scam neighbours, traced value"],
    sequence: ["Journey (TrailScore)", "new device → payee added → limit raised before this payment"],
    behaviour: ["Behaviour", "amount vs the customer's own history, first-time payee, balance drain, hour"],
    context: ["Context (ContextFlag)", "urgency / secrecy / authority cues in call or message context (simulated)"],
  };
  return (
    <div className="primer">
      <div className="ksub">The assessment appears here the moment the intent is evaluated — before any money moves. Every payment is scored on five dimensions:</div>
      {!p ? <div className="ksub">{policy.loading ? "Loading policy…" : "Policy unavailable."}</div> : (
        <div className="grid cols-2 align-start" style={{ gap: 18, marginTop: 10 }}>
          <div className="stack tight" style={{ gap: 10 }}>
            {Object.entries(p.weights).sort((x, y) => y[1] - x[1]).map(([k, w]) => (
              <div key={k} className="primer-row">
                <div className="spread"><b>{DIM[k]?.[0] ?? k}</b><span className="mono sm">{Math.round(w * 100)}%</span></div>
                <div className="bar"><i style={{ width: `${w * 100 * 3}%`, background: "var(--mint)" }} /></div>
                <div className="xs muted">{DIM[k]?.[1]}</div>
              </div>
            ))}
          </div>
          <div>
            <div className="xs muted" style={{ marginBottom: 6 }}>Proportionate response · policy {p.version.split("+")[0]}</div>
            <div className="stack tight" style={{ gap: 6 }}>
              {p.ladder.map((t, i) => (
                <div key={t.tier} className="row" style={{ gap: 10 }}>
                  <TierPill tier={t.tier} />
                  <span className="grow sm"><b>{t.title}</b></span>
                  <span className="mono xs muted">{i === 0 ? "<" : "≥"} {i === 0 ? t.below.toFixed(2) : p.ladder[i - 1].below.toFixed(2)}</span>
                </div>
              ))}
            </div>
            <div className="xs muted" style={{ marginTop: 10 }}>{p.note}</div>
          </div>
        </div>
      )}
    </div>
  );
}
