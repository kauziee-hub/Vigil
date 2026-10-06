// TRANSACTION GUARD — customer device on the left, the bank's pre-commit assessment of the same payment
// on the right: sender · recipient · amount · relationship · device · behaviour · network · external ·
// journey · context → decision → intervention → provider / ledger / monitoring outcome.
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { AccountSummary, DecisionRecord, RiskDecision, TransactionIntent } from "../api/types";
import { AssessmentTable, CaseLinks, CaseMeta, InterventionShown, Outcome } from "../components/Assessment";
import { CustomerDevice, type DeviceState, type Prefill } from "../components/CustomerDevice";
import { useConsoleEvents } from "../components/Shell";
import { PageHead, Panel, StatePill, TierPill } from "../components/ui";
import { formatINR, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";

const QUICK: Record<string, { label: string; to: string; amount: string; note: string }[]> = {
  "ramesh@vigil": [
    { label: "Act 1 · Grocer ₹500", to: "meena.grocer@vigil", amount: "500", note: "groceries" },
    { label: "Act 2 · Kiran Traders ₹45,000", to: "kiran.traders@vigil", amount: "45000", note: "advance for goods" },
    { label: "Control · Landlord ₹1,20,000", to: "landlord.iyer@vigil", amount: "120000", note: "deposit + October rent" },
  ],
  "sunita@vigil": [
    { label: "Pharmacy ₹2,000", to: "medplus.pharma@vigil", amount: "2000", note: "medicines" },
  ],
};

export function GuardPage() {
  const [params, setParams] = useSearchParams();
  const payer = params.get("as") || "ramesh@vigil";
  const [prefill, setPrefill] = useState<Prefill | null>(null);
  const [device, setDevice] = useState<DeviceState>({ intent: null, decision: null });
  const [picked, setPicked] = useState<{ intent: TransactionIntent; decision: RiskDecision | null } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const recent = useLoad<TransactionIntent[]>(() => api.intents(payer), [payer]);
  const refreshRecent = useDebounced(() => recent.reload(), 800);

  useEffect(() => { setPicked(null); }, [payer]);
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
  const runScenario = async (id: string) => {
    setBusy(id); setErr(null);
    try { await api.scenarioStart(id); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  return (
    <>
      <PageHead crumb="02 · Operate" title="Transaction Guard"
        lede="Every payment intent is assessed before the provider is called. The customer sees one proportionate intervention; the bank sees the full case."
        actions={<a className="btn sm ghost" href={`/pay?as=${encodeURIComponent(payer)}`} target="_blank" rel="noreferrer">Customer kiosk ↗</a>} />
      <div className="guard">
        <div className="stack">
          <CustomerDevice payer={payer} onPayerChange={(p) => setParams({ as: p })} onChange={setDevice} prefill={prefill} />
          <Panel kicker="Demo inputs" title="" className="demo-inputs">
            <div className="stack tight">
              {(QUICK[payer] ?? []).map((q) => (
                <button key={q.label} className="btn sm" style={{ justifyContent: "flex-start" }}
                        onClick={() => setPrefill({ to: q.to, amount: q.amount, note: q.note, nonce: Date.now() })}>{q.label}</button>
              ))}
              {payer === "sunita@vigil" && (
                <>
                  <button className="btn sm" style={{ justifyContent: "flex-start" }} disabled={busy === "s3"} onClick={() => runScenario("s3")}>
                    {busy === "s3" ? "Starting…" : "Act 4 · run coerced-payment scenario"}</button>
                  <div className="xs muted">The scenario's payment appears on this phone live; Arjun's phone (<a href="/contact/arjun" target="_blank" rel="noreferrer">/contact/arjun</a>) receives the CircuitBreaker alert.</div>
                </>
              )}
              {payer === "ramesh@vigil" && <div className="xs muted">Act 3 (mule network) runs in the <Link to="/lab">Scenario Lab</Link>; afterwards pay Kiran Traders again to see the network evidence carried into the next decision.</div>}
            </div>
          </Panel>
        </div>

        <div className="stack loose" style={{ minWidth: 0 }}>
          {err && <div className="notice err">{err}</div>}
          {intent && decision ? (
            <CaseView intent={intent} decision={decision} historical={!device.intent && !!picked} />
          ) : (
            <Panel kicker="Pre-commit assessment" title="No payment under assessment"
                   q={`Submit a payment on ${handle(payer)}'s device, use a demo input, or open a recent intent.`}>
              <div className="empty">The assessment appears here the moment the intent is evaluated — before any money moves.</div>
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
