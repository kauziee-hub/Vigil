// Trusted contact's phone (CircuitBreaker). Light consumer variant of the design system, mobile-first.
// Alerts arrive over WebSocket — no refresh, no polling. Responses are real calls to /api/contact/{token}/respond.
import { Logo } from "../components/Logo";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useRealtime } from "../api/realtime";
import type { ContactView } from "../api/types";
import { formatINR, formatTime } from "../lib/format";
import { useLoad } from "../lib/hooks";

const RESPONSES = [
  { key: "calling_user", label: "I'm calling them now", cls: "primary" },
  { key: "acknowledged", label: "Acknowledge", cls: "" },
  { key: "marked_expected", label: "This payment is expected", cls: "" },
] as const;

const RESPONSE_TEXT: Record<string, string> = {
  calling_user: "You are calling them", acknowledged: "Acknowledged", marked_expected: "Marked as expected",
};

export function ContactPage() {
  const { token = "" } = useParams();
  const view = useLoad<ContactView>(() => api.contact(token), [token]);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const conn = useRealtime([`contact:${token}`], (e) => {
    if (e.type === "breaker.fired" || e.type === "breaker.responded") {
      view.reload();
      if (e.type === "breaker.fired" && "vibrate" in navigator) navigator.vibrate?.([200, 100, 200]);
    }
  });

  const respond = async (breakerId: string, response: (typeof RESPONSES)[number]["key"]) => {
    setErr(null); setBusy(response);
    try { const r = await api.contactRespond(token, breakerId, response); setSent((s) => ({ ...s, [breakerId]: r.text })); view.reload(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  const v = view.data;
  const latest = v?.alerts[0];
  const earlier = v?.alerts.slice(1, 4) ?? [];
  return (
    <div className="contact-wrap">
      <div className="contact">
        <div className="c-head">
          <div className="c-brand"><Logo tagline="Trusted contact" size={30} /></div>
          <span className="c-live"><span className={`dot ${conn === "open" ? "ok" : "warn"}`} />{conn === "open" ? "live" : "connecting"}</span>
        </div>
        {view.error && <div className="c-note err">{view.error.code === "unknown_token" ? "This link is not valid." : view.error.message}</div>}
        {view.loading && !v && <div className="c-quiet">Loading…</div>}
        {v && (
          <>
            <div>
              <h1>Hi {v.contact_name.split(" ")[0]}</h1>
              <div className="c-muted">{v.account_holder} nominated you as their trusted contact for large or unusual payments.</div>
            </div>
            {!latest && <div className="c-quiet">No alerts. You will see one here instantly if Vigil pauses a payment.</div>}
            {latest && (
              <div className="alert-card" key={latest.breaker_id}>
                <div className="c-kicker">{formatTime(latest.fired_at)} · payment on hold</div>
                <div className="h">{latest.headline}</div>
                <div className="amt">{formatINR(latest.amount_paise)}</div>
                <ul>{latest.facts.map((f) => <li key={f}>{f}</li>)}</ul>
                <div className="c-note">{latest.status} {latest.asks}</div>
                {latest.response || sent[latest.breaker_id] ? (
                  <div className="c-note ok">Your response was sent to the bank: <b>{sent[latest.breaker_id] ?? RESPONSE_TEXT[latest.response ?? ""] ?? latest.response}</b>
                    {latest.responded_at && <span className="c-muted"> · {formatTime(latest.responded_at)}</span>}</div>
                ) : (
                  <div className="actions">
                    {RESPONSES.map((r) => (
                      <button key={r.key} className={`btn ${r.cls}`} disabled={!!busy} onClick={() => respond(latest.breaker_id, r.key)}>
                        {busy === r.key ? "Sending…" : r.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {earlier.length > 0 && (
              <div className="c-earlier">
                <div className="c-kicker">Earlier alerts</div>
                {earlier.map((a) => (
                  <div key={a.breaker_id} className="c-row"><span>{formatTime(a.fired_at)} · {formatINR(a.amount_paise)}</span><span className="c-muted">{a.response ? RESPONSE_TEXT[a.response] ?? a.response : "no response"}</span></div>
                ))}
              </div>
            )}
            {err && <div className="c-note err">{err}</div>}
            <div className="c-foot">Vigil shares facts, never accusations. Only this one payment is paused — the account keeps working. Prototype with synthetic data; not connected to any bank.</div>
          </>
        )}
      </div>
    </div>
  );
}
