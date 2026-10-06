// Trusted contact's phone. Alerts arrive over WebSocket — no refresh, no polling.
import { useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useRealtime } from "../api/realtime";
import type { ContactView } from "../api/types";
import { formatINR, formatTime } from "../lib/format";
import { useLoad } from "../lib/hooks";

const RESPONSES = [
  { key: "calling_user", label: "📞 I'm calling them now", cls: "primary" },
  { key: "acknowledged", label: "👁 Acknowledge", cls: "" },
  { key: "marked_expected", label: "✓ This payment is expected", cls: "good" },
] as const;

export function ContactPage() {
  const { token = "" } = useParams();
  const view = useLoad<ContactView>(() => api.contact(token), [token]);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState<Record<string, string>>({});
  const conn = useRealtime([`contact:${token}`], (e) => {
    if (e.type === "breaker.fired" || e.type === "breaker.responded") {
      view.reload();
      if (e.type === "breaker.fired" && "vibrate" in navigator) navigator.vibrate?.([200, 100, 200]);
    }
  });

  const respond = async (breakerId: string, response: (typeof RESPONSES)[number]["key"]) => {
    setErr(null);
    try { const r = await api.contactRespond(token, breakerId, response); setSent((s) => ({ ...s, [breakerId]: r.text })); view.reload(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  };

  const v = view.data;
  const latest = v?.alerts[0];
  return (
    <div className="contact">
      <div className="spread">
        <div className="brand"><span className="brand-mark">V</span> Vigil · Trusted contact</div>
        <span className="row small"><span className={`dot ${conn === "open" ? "ok" : "warn"}`} />{conn === "open" ? "live" : "connecting"}</span>
      </div>
      {view.error && <div className="notice error">{view.error.code === "unknown_token" ? "This link is not valid." : view.error.message}</div>}
      {v && (
        <>
          <div>
            <h1>Hi {v.contact_name.split(" ")[0]}</h1>
            <div className="muted">{v.account_holder} nominated you as their trusted contact for large or unusual payments.</div>
          </div>
          {!latest && <div className="quiet">No alerts. You'll see one here instantly if Vigil pauses a payment.</div>}
          {latest && (
            <div className="alert-card" key={latest.breaker_id}>
              <div className="small muted">{formatTime(latest.fired_at)} · payment on hold</div>
              <div className="h" style={{ marginTop: 6 }}>{latest.headline}</div>
              <div style={{ fontFamily: "var(--font-data)", fontSize: 24, fontWeight: 700, margin: "8px 0" }}>{formatINR(latest.amount_paise)}</div>
              <ul>{latest.facts.map((f) => <li key={f}>{f}</li>)}</ul>
              <div className="notice small">{latest.status} {latest.asks}</div>
              {latest.response || sent[latest.breaker_id] ? (
                <div className="notice small" style={{ marginTop: 10 }}>✓ Your response was sent to the bank: <b>{(sent[latest.breaker_id] ?? latest.response ?? "").replace("_", " ")}</b></div>
              ) : (
                <div className="actions">
                  {RESPONSES.map((r) => (
                    <button key={r.key} className={`btn ${r.cls}`} onClick={() => respond(latest.breaker_id, r.key)}>{r.label}</button>
                  ))}
                </div>
              )}
            </div>
          )}
          {err && <div className="notice error">{err}</div>}
          <div className="small muted" style={{ textAlign: "center" }}>Vigil shares facts, never accusations. Only this one payment is paused — the account keeps working. Demo prototype.</div>
        </>
      )}
    </div>
  );
}
