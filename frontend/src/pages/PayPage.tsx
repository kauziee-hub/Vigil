import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useRealtime } from "../api/realtime";
import type { AccountSummary, RiskDecision, TransactionIntent, WsEnvelope } from "../api/types";
import { ContributionPanel, SimChip, TierChip } from "../components/Decision";
import { STATE_LABEL, formatINR, formatTime, handle, rupeesToPaise } from "../lib/format";

declare global {
  interface Window { Razorpay?: new (opts: Record<string, unknown>) => { open: () => void; on: (e: string, cb: (r: unknown) => void) => void } }
}

const DEMO_PAYERS = ["ramesh@vigil", "sunita@vigil"];
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
const COERCION_SCRIPT = "Inspector Sharma, cyber police: a warrant has been issued in your name. You are under digital arrest. Do not tell anyone, not even your family. Transfer immediately to the RBI verification account.";

function loadRazorpay(): Promise<boolean> {
  if (window.Razorpay) return Promise.resolve(true);
  return new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve(true);
    s.onerror = () => resolve(false);
    document.body.appendChild(s);
  });
}

type View = "form" | "checking" | "result";

export function PayPage() {
  const [params, setParams] = useSearchParams();
  const payer = params.get("as") || "ramesh@vigil";
  const kiosk = params.get("kiosk") === "1";
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [ctxOpen, setCtxOpen] = useState(false);
  const [ctx, setCtx] = useState("");
  const [view, setView] = useState<View>("form");
  const [intent, setIntent] = useState<TransactionIntent | null>(null);
  const [decision, setDecision] = useState<RiskDecision | null>(null);
  const [purpose, setPurpose] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [contactNews, setContactNews] = useState<string[]>([]);
  const [gatewayIssue, setGatewayIssue] = useState<string | null>(null);
  const current = useRef<string | null>(null);
  current.current = intent?.intent_id ?? null;

  const refreshAccount = () => api.account(payer).then(setAccount).catch(() => setAccount(null));
  useEffect(() => { refreshAccount(); resetForm(); /* eslint-disable-next-line */ }, [payer]);

  function resetForm() {
    setView("form"); setIntent(null); setDecision(null); setPurpose(""); setErr(null); setContactNews([]); setGatewayIssue(null);
  }

  const onEvent = async (e: WsEnvelope<any>) => {
    if (e.type === "intent.updated") {
      const it = e.data as TransactionIntent;
      if (it.intent_id === current.current) {
        setIntent(it);
        if (["MONITORED", "REJECTED", "CANCELLED"].includes(it.state)) refreshAccount();
      } else if (it.source === "scenario" && it.decision_id && it.state !== "CREATED" && it.state !== "RISK_EVALUATED"
                 && !current.current) {
        // A scenario submitted a payment for this payer: show it as if they had pressed Pay.
        const d = await api.decision(it.decision_id);
        setIntent(it); setDecision(d); setView("result"); refreshAccount();
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
                                           note: note || undefined, context_text: ctx.trim() || undefined });
      await new Promise((r) => setTimeout(r, Math.max(0, 900 - (Date.now() - started))));
      setIntent(res.intent); setDecision(res.decision); setView("result"); refreshAccount();
      if (res.intent.state === "APPROVED") await startPayment(res.intent.intent_id);
    } catch (e) {
      setView("form");
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };

  async function startPayment(intentId: string, provider?: "mock" | "razorpay_test") {
    setBusy(true); setGatewayIssue(null);
    try {
      const it = await api.pay(intentId, provider);
      setIntent(it);
      if (it.state === "PAYMENT_INITIATED" && it.payment?.provider === "razorpay_test" && it.payment.order_id) {
        const ok = await loadRazorpay();
        if (!ok || !window.Razorpay) { setGatewayIssue("Razorpay Checkout could not load (offline?)."); return; }
        const rzp = new window.Razorpay({
          key: it.payment.key_id, order_id: it.payment.order_id, amount: it.payment.amount_paise, currency: "INR",
          name: "Vigil demo · Razorpay TEST MODE", description: `${it.intent_id} → ${handle(it.recipient_id)} (test funds)`,
          theme: { color: "#1d4f91" },
          handler: async (r: { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string }) => {
            try { setIntent(await api.confirmRazorpay(it.intent_id, r)); refreshAccount(); }
            catch (e) { setGatewayIssue(e instanceof ApiError ? e.message : String(e)); }
          },
          modal: { ondismiss: () => setGatewayIssue("Razorpay checkout was closed before completing.") },
        });
        rzp.on("payment.failed", () => setGatewayIssue("Razorpay reported the test payment as failed."));
        rzp.open();
      } else if (it.state === "PAYMENT_FAILED") {
        setGatewayIssue(it.transitions[it.transitions.length - 1]?.detail ?? "Gateway unavailable.");
      } else {
        refreshAccount();
      }
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

  return (
    <div className="pay-wrap">
      <div className="phone" aria-live="polite">
        <div className="phone-head">
          <div className="spread">
            <div>
              <div className="sub">Paying as</div>
              {kiosk ? <b>{account?.display_name ?? handle(payer)}</b> : (
                <select className="select" style={{ background: "rgba(255,255,255,.12)", color: "#fff", border: "1px solid rgba(255,255,255,.3)", padding: "4px 8px" }}
                        value={payer} onChange={(e) => setParams({ as: e.target.value })} aria-label="Choose demo customer">
                  {DEMO_PAYERS.map((p) => <option key={p} value={p} style={{ color: "#000" }}>{p}</option>)}
                </select>
              )}
            </div>
            <span className="chip" style={{ background: "rgba(255,255,255,.15)", color: "#fff" }}>VGL Bank · UPI</span>
          </div>
          <div className="bal">{formatINR(account?.available_paise)}</div>
          <div className="sub">available{account && account.held_paise > 0 ? ` · ${formatINR(account.held_paise)} on scoped hold` : ""}</div>
        </div>

        <div className="phone-body">
          {view === "form" && (
            <>
              <label className="field">To (UPI ID)
                <input className="input" value={to} onChange={(e) => setTo(e.target.value)} placeholder="name@vigil" list="payees" />
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
              <div>
                <button className="btn ghost sm" onClick={() => setCtxOpen(!ctxOpen)}>{ctxOpen ? "▾" : "▸"} Simulated call / message context <SimChip text="DEMO ONLY" /></button>
                {ctxOpen && (
                  <div className="stack" style={{ marginTop: 6 }}>
                    <div className="notice sim small">Vigil cannot read calls or chats. This box simulates context a legitimate, consented upstream channel could provide.</div>
                    <textarea className="textarea" value={ctx} onChange={(e) => setCtx(e.target.value)} placeholder="e.g. caller says it's urgent and secret…" />
                    <button className="btn sm" onClick={() => setCtx(COERCION_SCRIPT)}>Insert 'digital arrest' script</button>
                  </div>
                )}
              </div>
              {err && <div className="notice error">{err}</div>}
              <div style={{ marginTop: "auto" }}>
                <button className="btn primary lg block" onClick={submit}>Pay {rupeesToPaise(amount) ? formatINR(rupeesToPaise(amount)!) : ""}</button>
                <div className="small muted" style={{ textAlign: "center", marginTop: 6 }}>Vigil checks every payment before it is sent.</div>
              </div>
            </>
          )}

          {view === "checking" && (
            <div className="checking">
              <div className="spinner lg" />
              <div><b>Vigil is checking this payment</b><div className="small muted">recipient · network · your recent activity · behaviour · context</div></div>
            </div>
          )}

          {view === "result" && intent && decision && (
            <ResultPanel intent={intent} decision={decision} purpose={purpose} setPurpose={setPurpose}
                         busy={busy} err={err} contactNews={contactNews} gatewayIssue={gatewayIssue}
                         onAck={doAck} onCancel={doCancel} onNew={() => { resetForm(); setTo(""); setAmount(""); setNote(""); setCtx(""); }}
                         onPay={(p) => startPayment(intent.intent_id, p)}
                         onFallback={async () => { setBusy(true); try { setIntent(await api.fallbackMock(intent.intent_id)); setGatewayIssue(null); refreshAccount(); } finally { setBusy(false); } }} />
          )}
        </div>
      </div>

      {!kiosk && (
        <div className="side-panel">
          <div className="card">
            <h3>Quick fill (demo acts)</h3>
            <div className="stack">
              {(QUICK[payer] ?? []).map((q) => (
                <button key={q.label} className="btn sm" style={{ justifyContent: "flex-start" }}
                        onClick={() => { resetForm(); setTo(q.to); setAmount(q.amount); setNote(q.note); }}>{q.label}</button>
              ))}
              {payer === "sunita@vigil" && (
                <div className="notice small">Act 4: start <b>Scenario 3</b> in the <Link to="/">command center</Link>. Its payment appears here live; Arjun's phone (<a href="/contact/arjun" target="_blank" rel="noreferrer">/contact/arjun</a>) gets the alert.</div>
              )}
            </div>
          </div>
          {decision && (
            <div className="card">
              <div className="card-title"><h3>What the bank sees</h3><Link className="small" to={`/investigate/${decision.decision_id}`}>full investigation →</Link></div>
              <ContributionPanel decision={decision} />
            </div>
          )}
          {intent && (
            <div className="card">
              <h3>Intent lifecycle <span className="mono small muted">{intent.intent_id}</span></h3>
              <div className="stack small">
                {intent.transitions.map((t, i) => (
                  <div key={i}><span className="mono muted">{formatTime(t.ts)}</span> <b>{STATE_LABEL[t.to_state] ?? t.to_state}</b> <span className="muted">· {t.actor}</span>
                    {t.detail && <div className="muted">{t.detail}</div>}</div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultPanel(p: {
  intent: TransactionIntent; decision: RiskDecision; purpose: string; setPurpose: (s: string) => void; busy: boolean;
  err: string | null; contactNews: string[]; gatewayIssue: string | null;
  onAck: () => void; onCancel: () => void; onNew: () => void; onPay: (p?: "mock" | "razorpay_test") => void; onFallback: () => void;
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
        <div className="notice small"><b>{intent.payment?.label ?? "DEMO PAYMENT"}</b></div>
        {decision.tier === 0 && <div className="small muted" style={{ textAlign: "center" }}>{c.summary}</div>}
        <div className="q-block small"><div className="q">After the payment</div>
          {intent.transitions.find((t) => t.to_state === "MONITORED")?.detail ?? "Monitoring…"}</div>
        <button className="btn block" onClick={p.onNew}>New payment</button>
      </div>
    );
  }
  if (state === "CANCELLED" || state === "REJECTED") {
    return (
      <div className="result">
        <div className="tier-banner t0"><div className="h">{state === "CANCELLED" ? "Payment cancelled" : "The bank stopped this payment"}</div>
          <div style={{ color: "var(--ink)" }}>Nothing was sent. Your account works normally.</div></div>
        <button className="btn block" onClick={p.onNew}>New payment</button>
      </div>
    );
  }

  const paying = state === "APPROVED" || state === "PAYMENT_INITIATED" || state === "PAYMENT_FAILED";
  return (
    <div className="result">
      {decision.tier === 0 && paying ? (
        <div className="tier-banner t0"><div className="h">Approved — completing payment…</div>
          <div style={{ color: "var(--ink)" }}>{c.summary}</div></div>
      ) : (
        <>
          <div className="spread"><span className="upper">Risk level</span><TierChip tier={decision.tier} big /></div>
          <div className={`tier-banner t${decision.tier}`}>
            <div className="h">{c.headline}</div>
            <div style={{ marginTop: 6, color: "var(--ink)", fontSize: 13.5 }}>{c.summary}</div>
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

      {p.contactNews.map((n) => <div key={n} className="notice small">👤 {n}</div>)}
      {p.err && <div className="notice error">{p.err}</div>}

      {state === "CHALLENGED" && decision.tier === 1 && (
        <div className="row"><button className="btn grow" onClick={p.onCancel} disabled={p.busy}>Cancel</button>
          <button className="btn primary grow" onClick={p.onAck} disabled={p.busy}>Continue</button></div>
      )}
      {state === "CHALLENGED" && decision.tier === 2 && (
        <div className="stack">
          <label className="field">What is this payment for?
            <input className="input" value={p.purpose} onChange={(e) => p.setPurpose(e.target.value)} placeholder="e.g. advance for an order I placed" /></label>
          <div className="row"><button className="btn primary grow" onClick={p.onCancel} disabled={p.busy}>Don't send</button>
            <button className="btn grow" onClick={p.onAck} disabled={p.busy || p.purpose.trim().length < 3}>Confirm & pay</button></div>
        </div>
      )}
      {(state === "HELD" || state === "ESCALATED") && (
        <div className="stack">
          <div className="notice small">⏸ {formatINR(intent.amount_paise)} on scoped hold · ref {intent.hold_id} · waiting for bank review{decision.intervention.circuit_breaker ? " · trusted contact notified" : ""}</div>
          <button className="btn primary block" onClick={p.onCancel} disabled={p.busy}>Cancel this payment</button>
        </div>
      )}
      {paying && decision.tier > 0 && state === "APPROVED" && (
        <button className="btn primary block" onClick={() => p.onPay()} disabled={p.busy}>
          {decision.tier >= 3 ? "Bank released this payment — complete it" : "Complete payment"}</button>
      )}
      {state === "PAYMENT_INITIATED" && intent.payment?.provider === "razorpay_test" && (
        <div className="notice small"><b>RAZORPAY TEST MODE</b> — real gateway API with test funds; no real money moves. Complete the payment in the Razorpay window.</div>
      )}
      {(p.gatewayIssue || state === "PAYMENT_FAILED") && (
        <div className="stack">
          <div className="notice error small">{p.gatewayIssue ?? "Payment gateway failed."}</div>
          <div className="row">
            <button className="btn grow" onClick={() => p.onPay("razorpay_test")} disabled={p.busy}>Retry Razorpay</button>
            <button className="btn primary grow" onClick={p.onFallback} disabled={p.busy}>Complete as DEMO payment</button>
          </div>
        </div>
      )}
      <div className="small muted" style={{ textAlign: "center" }}>{intent.intent_id} · {STATE_LABEL[state]}</div>
    </div>
  );
}
