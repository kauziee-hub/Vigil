// The customer's phone. One implementation shared by Transaction Guard (/guard, beside the bank
// assessment) and the customer-only kiosk (/pay?as=). The four-question intervention copy and the
// approve / confirm / hold / cancel / pay flows are v1's, unchanged: they work. Payments settle on the simulated rail.
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import { useRealtime } from "../api/realtime";
import type { AccountSummary, RiskDecision, TransactionIntent, WsEnvelope } from "../api/types";
import { STATE_LABEL, TIER_LABEL, formatINR, handle, rupeesToPaise } from "../lib/format";

export const DEMO_PAYERS = ["ramesh@vigil", "sunita@vigil"];
export const COERCION_SCRIPT = "Inspector Sharma, cyber police: a warrant has been issued in your name. You are under digital arrest. Do not tell anyone, not even your family. Transfer immediately to the RBI verification account.";

export interface Prefill { to: string; amount: string; note: string; context?: string; nonce: number }
export interface DeviceState { intent: TransactionIntent | null; decision: RiskDecision | null }

const TERMINAL = new Set(["MONITORED", "PAYMENT_SUCCEEDED", "CANCELLED", "REJECTED"]);
type View = "form" | "checking" | "result";

export function CustomerDevice({ payer, kiosk = false, onPayerChange, onChange, prefill }: {
  payer: string;
  kiosk?: boolean;
  onPayerChange?: (p: string) => void;
  onChange?: (s: DeviceState) => void;
  prefill?: Prefill | null;
}) {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [rail, setRail] = useState<"upi" | "imps" | "neft" | "rtgs" | "card" | "wallet">("upi");
  const [ctxOpen, setCtxOpen] = useState(false);
  const [ctx, setCtx] = useState("");
  const [view, setView] = useState<View>("form");
  const [intent, setIntent] = useState<TransactionIntent | null>(null);
  const [decision, setDecision] = useState<RiskDecision | null>(null);
  const [purpose, setPurpose] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [contactNews, setContactNews] = useState<string[]>([]);
  const [payIssue, setPayIssue] = useState<string | null>(null);
  const current = useRef<{ id: string | null; state: string | null }>({ id: null, state: null });
  current.current = { id: intent?.intent_id ?? null, state: intent?.state ?? null };

  const refreshAccount = () => api.account(payer).then(setAccount).catch(() => setAccount(null));
  useEffect(() => { refreshAccount(); resetForm(); setTo(""); setAmount(""); setNote(""); setCtx(""); /* eslint-disable-next-line */ }, [payer]);
  useEffect(() => { onChange?.({ intent, decision }); /* eslint-disable-next-line */ }, [intent, decision]);
  useEffect(() => {
    if (!prefill) return;
    resetForm(); setTo(prefill.to); setAmount(prefill.amount); setNote(prefill.note);
    setCtx(prefill.context ?? ""); setCtxOpen(!!prefill.context);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.nonce]);

  function resetForm() {
    setView("form"); setIntent(null); setDecision(null); setPurpose(""); setErr(null); setContactNews([]); setPayIssue(null);
  }

  const onEvent = async (e: WsEnvelope<any>) => {
    if (e.type === "intent.updated") {
      const it = e.data as TransactionIntent;
      if (it.intent_id === current.current.id) {
        setIntent(it);
        if (TERMINAL.has(it.state)) refreshAccount();
      } else if (it.source === "scenario" && it.decision_id && it.state !== "CREATED" && it.state !== "RISK_EVALUATED"
                 && (!current.current.id || TERMINAL.has(current.current.state ?? ""))) {
        // A scenario submitted a payment for this payer: show it as if they had pressed Pay.
        try {
          const d = await api.decision(it.decision_id);
          setIntent(it); setDecision(d); setView("result"); setContactNews([]); refreshAccount();
        } catch { /* the bank view will show the error */ }
      }
    } else if (e.type === "breaker.responded") {
      setContactNews((n) => [...n, (e.data as { text: string }).text]);
    }
  };
  useRealtime([`pay:${payer}`], onEvent);

  const submit = async () => {
    setErr(null);
    const paise = rupeesToPaise(amount);
    if (!to.trim()) return setErr("Enter who you are paying (UPI ID).");
    if (!paise || paise <= 0) return setErr("Enter a valid amount.");
    setView("checking");
    const started = Date.now();
    try {
      const res = await api.createIntent({ sender_id: payer, recipient_id: to.trim(), amount_paise: paise,
                                           note: note || undefined, context_text: ctx.trim() || undefined, channel: rail });
      await new Promise((r) => setTimeout(r, Math.max(0, 900 - (Date.now() - started))));
      setIntent(res.intent); setDecision(res.decision); setView("result"); refreshAccount();
      if (res.intent.state === "APPROVED") await startPayment(res.intent.intent_id);
    } catch (e) {
      setView("form");
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };

  async function startPayment(intentId: string) {
    setBusy(true); setPayIssue(null);
    try {
      const it = await api.pay(intentId);
      setIntent(it);
      if (it.state === "PAYMENT_FAILED") setPayIssue(it.transitions[it.transitions.length - 1]?.detail ?? "Payment failed.");
      else refreshAccount();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  const doAck = async () => {
    if (!intent) return;
    setBusy(true); setErr(null);
    try {
      const it = await api.acknowledge(intent.intent_id, purpose || undefined);
      setIntent(it);
      await startPayment(it.intent_id);
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  const doCancel = async () => {
    if (!intent) return;
    setBusy(true);
    try { setIntent(await api.cancel(intent.intent_id)); refreshAccount(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };

  const suggestions = useMemo(() => (account?.payees ?? []).slice(0, 4), [account]);
  const amtPaise = rupeesToPaise(amount);

  return (
    <div className="iphone">
      <span className="iphone-btn l1" /><span className="iphone-btn l2" /><span className="iphone-btn l3" /><span className="iphone-btn r1" />
    <div className="phone" aria-live="polite">
      <IosStatusBar />
      <div className="ph-head">
        <div className="spread">
          <div>
            <div className="sub">Paying as</div>
            {kiosk || !onPayerChange ? <b>{account?.display_name ?? handle(payer)}</b> : (
              <select value={payer} onChange={(e) => onPayerChange(e.target.value)} aria-label="Choose demo customer">
                {DEMO_PAYERS.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            )}
          </div>
          <span className="ph-bank">VGL Bank · UPI</span>
        </div>
        <div className="bal">{formatINR(account?.available_paise)}</div>
        <div className="sub">available{account && account.held_paise > 0 ? ` · ${formatINR(account.held_paise)} on scoped hold` : ""}</div>
      </div>

      <div className="ph-body">
        {view === "form" && (
          <>
            <label className="field">To (UPI ID)
              <input className="input" value={to} onChange={(e) => setTo(e.target.value)} placeholder="name@vigil" />
            </label>
            {suggestions.length > 0 && (
              <div className="suggest">{suggestions.map((p) => (
                <button key={p.payee_id} onClick={() => setTo(p.payee_id)} title={`${p.payments} previous payments`}>{p.display_name}</button>
              ))}</div>
            )}
            <label className="field">Amount (₹)
              <input className="input amount-input" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0" />
            </label>
            <label className="field">Note (optional)
              <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What is this for?" />
            </label>
            <label className="field">Pay via
              <select className="input" value={rail} onChange={(e) => setRail(e.target.value as typeof rail)} aria-label="Payment rail">
                <option value="upi">UPI</option><option value="imps">IMPS</option><option value="neft">NEFT</option>
                <option value="rtgs">RTGS (₹2 lakh +)</option><option value="card">Card</option><option value="wallet">Wallet</option>
              </select>
            </label>
            <div>
              <button className="btn ghost sm" onClick={() => setCtxOpen(!ctxOpen)}>
                {ctxOpen ? "▾" : "▸"} Simulated call / message context <span className="sim">DEMO ONLY</span>
              </button>
              {ctxOpen && (
                <div className="stack" style={{ marginTop: 6 }}>
                  <div className="notice sm">Vigil cannot read calls or chats. This box simulates context a legitimate, consented upstream channel could provide.</div>
                  <textarea className="textarea" value={ctx} onChange={(e) => setCtx(e.target.value)} placeholder="e.g. caller says it's urgent and secret…" />
                  <button className="btn sm" onClick={() => setCtx(COERCION_SCRIPT)}>Insert 'digital arrest' script</button>
                </div>
              )}
            </div>
            {err && <div className="notice err">{err}</div>}
            <div style={{ marginTop: "auto" }}>
              <button className="btn primary lg block" onClick={submit}>Pay {amtPaise ? formatINR(amtPaise) : ""}</button>
              <div className="sm muted center" style={{ marginTop: 6 }}>Vigil checks every payment before it is sent.</div>
            </div>
          </>
        )}

        {view === "checking" && (
          <div className="checking">
            <div className="spinner lg" />
            <div><b>Vigil is checking this payment</b><div className="sm muted">recipient · network · your recent activity · behaviour · context</div></div>
          </div>
        )}

        {view === "result" && intent && decision && (
          <ResultPanel intent={intent} decision={decision} purpose={purpose} setPurpose={setPurpose}
                       busy={busy} err={err} contactNews={contactNews} payIssue={payIssue}
                       onAck={doAck} onCancel={doCancel}
                       onNew={() => { resetForm(); setTo(""); setAmount(""); setNote(""); setCtx(""); }}
                       onPay={() => startPayment(intent.intent_id)} />
        )}
      </div>
      <div className="ios-home" aria-hidden="true" />
    </div>
    </div>
  );
}

/** iOS-style status bar with the Dynamic Island (decorative; the clock is the real local time). */
function IosStatusBar() {
  const [t, setT] = useState(() => new Date());
  useEffect(() => { const i = window.setInterval(() => setT(new Date()), 15000); return () => window.clearInterval(i); }, []);
  return (
    <div className="ios-status" aria-hidden="true">
      <span className="ios-time">{t.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: false })}</span>
      <span className="ios-island" />
      <span className="ios-icons">
        <svg viewBox="0 0 18 12" width="17" height="11"><rect x="0" y="8" width="3" height="4" rx="1" /><rect x="5" y="5.5" width="3" height="6.5" rx="1" /><rect x="10" y="3" width="3" height="9" rx="1" /><rect x="15" y="0" width="3" height="12" rx="1" /></svg>
        <svg viewBox="0 0 16 12" width="15" height="11"><path d="M8 11.2 5.6 8.6a3.4 3.4 0 0 1 4.8 0zM3.4 6.4a6.5 6.5 0 0 1 9.2 0l-1.4 1.5a4.5 4.5 0 0 0-6.4 0zM1 4a9.9 9.9 0 0 1 14 0l-1.4 1.5a7.9 7.9 0 0 0-11.2 0z" /></svg>
        <svg viewBox="0 0 27 12" width="25" height="12"><rect x="0.5" y="0.5" width="22" height="11" rx="3.2" fill="none" stroke="currentColor" opacity="0.4" /><rect x="2" y="2" width="16.5" height="8" rx="2" /><rect x="24" y="4" width="2" height="4" rx="1" opacity="0.45" /></svg>
      </span>
    </div>
  );
}

function ResultPanel(p: {
  intent: TransactionIntent; decision: RiskDecision; purpose: string; setPurpose: (s: string) => void; busy: boolean;
  err: string | null; contactNews: string[]; payIssue: string | null;
  onAck: () => void; onCancel: () => void; onNew: () => void; onPay: () => void;
}) {
  const { intent, decision } = p;
  const c = decision.reasons.customer;
  const state = intent.state;
  const done = state === "MONITORED" || state === "PAYMENT_SUCCEEDED";
  const changed = decision.reasons.analyst.journey.filter((j) => j.event_type !== "simulated_context");

  if (done) {
    return (
      <div className="result">
        <div className="receipt">
          <div className="tick">✓</div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>Paid {formatINR(intent.amount_paise)}</div>
          <div className="muted">to {handle(intent.recipient_id)}</div>
        </div>
        <div className="notice sm"><b>{intent.payment?.label ?? "DEMO PAYMENT"}</b></div>
        {decision.tier === 0 && <div className="sm muted center">{c.summary}</div>}
        <div className="q-block sm"><div className="q">After the payment</div>
          {intent.transitions.find((t) => t.to_state === "MONITORED")?.detail ?? "Monitoring…"}</div>
        <button className="btn block" onClick={p.onNew}>New payment</button>
      </div>
    );
  }
  if (state === "CANCELLED" || state === "REJECTED") {
    return (
      <div className="result">
        <div className="tier-banner t0"><div className="h">{state === "CANCELLED" ? "Payment cancelled" : "The bank stopped this payment"}</div>
          <div>Nothing was sent. Your account works normally.</div></div>
        <button className="btn block" onClick={p.onNew}>New payment</button>
      </div>
    );
  }

  const paying = state === "APPROVED" || state === "PAYMENT_INITIATED" || state === "PAYMENT_FAILED";
  return (
    <div className="result">
      {decision.tier === 0 && paying ? (
        <div className="tier-banner t0"><div className="h">Approved — completing payment…</div><div>{c.summary}</div></div>
      ) : (
        <>
          <div className="risk-row"><span className="q-label">Risk level</span>
            <span className={`risk-chip t${decision.tier}`}>{TIER_LABEL[decision.tier]}</span></div>
          <div className={`tier-banner t${decision.tier}`}>
            <div className="h">{c.headline}</div>
            <div style={{ marginTop: 6, fontSize: 13.5 }}>{c.summary}</div>
          </div>
          {changed.length > 0 && (
            <div className="q-block"><div className="q">What changed</div>
              <ul>{changed.map((j, i) => <li key={i}>{j.label} · {Math.round(j.minutes_ago)} min ago</li>)}</ul></div>
          )}
          {c.facts.length > 0 && (
            <div className="q-block"><div className="q">Why we are interrupting</div>
              <ul>{c.facts.map((f) => <li key={f}>{f}</li>)}</ul></div>
          )}
          <div className="q-block"><div className="q">What action is being taken</div>{c.what_happens_next}</div>
        </>
      )}

      {p.contactNews.map((n) => <div key={n} className="notice sm"><b>Trusted contact:</b> {n}</div>)}
      {p.err && <div className="notice err">{p.err}</div>}

      {state === "CHALLENGED" && decision.tier === 1 && (
        <div className="row"><button className="btn grow" onClick={p.onCancel} disabled={p.busy}>Cancel</button>
          <button className="btn primary grow" onClick={p.onAck} disabled={p.busy}>Continue</button></div>
      )}
      {state === "CHALLENGED" && decision.tier === 2 && (
        <div className="stack">
          <label className="field">What is this payment for?
            <input className="input" value={p.purpose} onChange={(e) => p.setPurpose(e.target.value)} placeholder="e.g. advance for an order I placed" /></label>
          <div className="row"><button className="btn primary grow" onClick={p.onCancel} disabled={p.busy}>Don't send</button>
            <button className="btn grow" onClick={p.onAck} disabled={p.busy || p.purpose.trim().length < 3}>Confirm &amp; pay</button></div>
        </div>
      )}
      {(state === "HELD" || state === "ESCALATED") && (
        <div className="stack">
          <div className="notice sm">{formatINR(intent.amount_paise)} on scoped hold · ref {intent.hold_id} · waiting for bank review{decision.intervention.circuit_breaker ? " · trusted contact notified" : ""}</div>
          <button className="btn primary block" onClick={p.onCancel} disabled={p.busy}>Cancel this payment</button>
        </div>
      )}
      {paying && decision.tier > 0 && state === "APPROVED" && (
        <button className="btn primary block" onClick={() => p.onPay()} disabled={p.busy}>
          {decision.tier >= 3 ? "Bank released this payment — complete it" : "Complete payment"}</button>
      )}
      {(p.payIssue || state === "PAYMENT_FAILED") && (
        <div className="stack">
          <div className="notice err sm">{p.payIssue ?? "Payment failed."}</div>
          <button className="btn primary block" onClick={() => p.onPay()} disabled={p.busy}>Retry payment</button>
        </div>
      )}
      <div className="sm muted center">{intent.intent_id} · {STATE_LABEL[state]}</div>
    </div>
  );
}
