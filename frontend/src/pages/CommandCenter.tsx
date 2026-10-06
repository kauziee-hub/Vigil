import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { DecisionSummary, Metrics, RingRow, ScenarioExplain, ScenarioStatus } from "../api/types";
import { TierPill as TierChip } from "../components/ui";
import { useConsoleEvents } from "../components/Shell";
import { formatINR, formatPaiseShort, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return <div className="kpi"><div className="l">{label}</div><div className="v">{value}</div>{sub && <div className="s">{sub}</div>}</div>;
}

const LIFECYCLE = [
  ["pre", "Intent", "Customer presses Pay. No money moves."],
  ["pre", "Evaluate", "External · Network · Journey · Behaviour · Context"],
  ["pre", "Fuse + explain", "Versioned weights, named adjustments, ReasonLine"],
  ["pre", "Interrupt ladder", "Pass · Inform · Confirm · Hold · Hold + CircuitBreaker"],
  ["", "Payment provider", "Mock or Razorpay TEST — only after approval"],
  ["post", "Ledger + PathGraph", "Debit + credit, edge appended incrementally"],
  ["post", "RingWatch / TaintTrace", "Network re-scored; confirmed scams traced"],
  ["post", "Next decision", "Inherits what the network just learned"],
];

export function CommandCenter() {
  const nav = useNavigate();
  const metrics = useLoad<Metrics>(api.metrics);
  const feed = useLoad<DecisionSummary[]>(() => api.decisions(0));
  const ring = useLoad<RingRow[]>(api.ringwatch);
  const scen = useLoad<ScenarioStatus[]>(api.scenarios);
  const health = useLoad(api.health);
  const [explain, setExplain] = useState<ScenarioExplain | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const [showAmbient, setShowAmbient] = useState(false);
  const [ambientFeed, setAmbientFeed] = useState<DecisionSummary[]>([]);

  const refreshMetrics = useDebounced(() => { metrics.reload(); ring.reload(); }, 700);
  const refreshScen = useDebounced(() => scen.reload(), 250);

  useConsoleEvents((e) => {
    if (e.type === "decision.created") {
      const d = e.data as DecisionSummary;
      setAmbientFeed((f) => [d, ...f].slice(0, 40));
      if (d.source !== "ambient") {
        feed.setData((f) => (f ? [d, ...f.filter((x) => x.decision_id !== d.decision_id)] : [d]).slice(0, 60));
      }
      setFresh(d.decision_id);
      refreshMetrics();
    } else if (e.type.startsWith("scenario.")) {
      refreshScen();
    } else if (["ledger.posted", "taint.updated", "intent.updated", "ringwatch.scan", "monitor.finding", "metrics.dirty"].includes(e.type)) {
      refreshMetrics();
    } else if (e.type === "demo.reset") {
      feed.reload(); scen.reload(); refreshMetrics(); setExplain(null); setAmbientFeed([]);
    } else if (e.type === "ambient.changed") {
      health.reload();
    }
  });

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setErr(null);
    try { await fn(); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); scen.reload(); }
  };

  const m = metrics.data;
  const visibleFeed = showAmbient ? ambientFeed : feed.data ?? [];

  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="spread">
        <div>
          <h1>Command center</h1>
          <div className="muted small">Every payment intent is evaluated <b>before</b> the provider is called. Most pass silently.</div>
        </div>
        <div className="row wrap">
          <button className="btn sm" onClick={() => act("ambient", () => api.ambient(!health.data?.ambient))}>
            <span className={`dot ${health.data?.ambient ? "ok" : ""}`} /> Background stream {health.data?.ambient ? "on" : "off"}
          </button>
          <button className="btn sm danger" disabled={busy === "reset"}
                  onClick={() => window.confirm("Reset the demo to its seeded starting state?") && act("reset", api.reset)}>
            {busy === "reset" ? "Resetting…" : "Reset demo"}
          </button>
        </div>
      </div>
      {err && <div className="notice error">{err}</div>}

      <div className="lifecycle">
        {LIFECYCLE.map(([cls, t, d]) => (
          <div key={t} className={`lc-step ${cls}`}><b>{t}</b><span className="muted">{d}</span></div>
        ))}
      </div>

      <div className="kpis">
        <Kpi label="Payments last 10 min" value={m ? String(m.transactions_last_10m) : "—"} sub={m ? `${m.decisions_total} decisions total` : undefined} />
        <Kpi label="Zero-friction rate" value={m?.zero_friction_rate != null ? `${Math.round(m.zero_friction_rate * 100)}%` : "—"} sub="Tier 0 share of decisions" />
        <Kpi label="Pending intents" value={m ? String(m.pending_intents) : "—"} sub={m ? `${m.open_interventions} open interventions` : undefined} />
        <Kpi label="Held (scoped)" value={m ? formatPaiseShort(m.held_paise) : "—"} sub="per-payment amounts only" />
        <Kpi label="Suspicious accounts" value={m ? String(m.suspicious_accounts) : "—"} sub={m ? `${formatPaiseShort(m.suspicious_value_paise)} inflow (72 h)` : undefined} />
        <Kpi label="Traced to confirmed scams" value={m ? formatPaiseShort(m.attributable_paise) : "—"} sub="LIBR, still attributable" />
        <Kpi label="Challenges overturned" value={m ? `${m.challenges_overturned}/${m.challenges}` : "—"} sub="released / continued / expected" />
        <Kpi label="Decision latency" value={m?.latency_p95_ms != null ? `${m.latency_p95_ms} ms` : "—"} sub={m?.latency_p50_ms != null ? `p95 · p50 ${m.latency_p50_ms} ms` : "p95"} />
      </div>

      <div className="grid-cc">
        <div className="card">
          <div className="card-title"><h2>Demo scenarios</h2><span className="small muted">deterministic · same result every reset</span></div>
          <div className="scenarios">
            {(scen.data ?? []).map((s) => {
              const pct = s.total_steps ? (s.step / s.total_steps) * 100 : 0;
              return (
                <div key={s.id} className={`scn ${s.state === "running" ? "running" : ""}`}>
                  <div className="scn-head">
                    <span className="chip">{s.act}</span><b className="grow">{s.name}</b>
                    <span className="small muted">{s.state}{s.state !== "idle" ? ` · ${s.step}/${s.total_steps}` : ""}</span>
                  </div>
                  <p>{s.summary} <span className="muted">Expected: {s.expected}</span></p>
                  {s.state !== "idle" && <div className="progress"><i style={{ width: `${pct}%` }} /></div>}
                  <div className="row wrap" style={{ marginTop: 8 }}>
                    {(s.state === "idle" || s.state === "done") && (
                      <button className="btn sm primary" disabled={!!busy} onClick={() => act(s.id, () => api.scenarioStart(s.id))}>▶ Start</button>
                    )}
                    {s.state === "running" && <button className="btn sm" onClick={() => act(s.id, () => api.scenarioPause(s.id))}>❚❚ Pause</button>}
                    {s.state === "paused" && <button className="btn sm primary" onClick={() => act(s.id, () => api.scenarioResume(s.id))}>▶ Resume</button>}
                    <button className="btn sm" disabled={!!busy}
                            onClick={() => window.confirm("Reset resets the whole demo to its seeded state. Continue?") && act(`r${s.id}`, () => api.scenarioReset(s.id))}>↺ Reset</button>
                    <button className="btn sm" onClick={() => api.scenarioExplain(s.id).then(setExplain)}>? Explain</button>
                    {s.payer && <Link className="btn sm ghost" to={`/pay?as=${encodeURIComponent(s.payer)}`}>Payer screen →</Link>}
                    {s.id === "s2" && <Link className="btn sm ghost" to="/network">Network →</Link>}
                    {s.id === "s3" && <a className="btn sm ghost" href="/contact/arjun" target="_blank" rel="noreferrer">Arjun's phone ↗</a>}
                  </div>
                  {s.log.length > 0 && (
                    <div className="scn-log">
                      {s.log.map((l) => (
                        <div key={l.step}>
                          <span className="mono muted">{l.step}.</span> {l.title}
                          {l.result && typeof l.result === "object" && "decision_id" in l.result && (
                            <> → <TierChip tier={(l.result as { tier: number }).tier} />{" "}
                              <Link to={`/investigate/${(l.result as { decision_id: string }).decision_id}`}>investigate</Link></>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {explain?.id === s.id && (
                    <div className="notice small" style={{ marginTop: 8 }}>
                      <div className="spread"><b>{explain.act}: {explain.name}</b><button className="btn ghost sm" aria-label="Close explanation" onClick={() => setExplain(null)}>✕</button></div>
                      <ul style={{ margin: "6px 0", paddingLeft: 18 }}>{explain.explain.map((x) => <li key={x}>{x}</li>)}</ul>
                      {explain.time_compressed && <div className="chip sim">Time-compressed: journey events are back-dated to replay 8 minutes in seconds</div>}{" "}
                      {explain.simulated_inputs && <span className="chip sim">Uses simulated inputs</span>}
                      {explain.decisions.map((d) => (
                        <div key={d.decision_id}><Link to={`/investigate/${d.decision_id}`}>{d.decision_id}</Link> · Tier {d.tier} · {d.state} · score {d.final_score.toFixed(2)}</div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="stack" style={{ gap: 16 }}>
          <div className="card">
            <div className="card-title">
              <h2>Live decisions</h2>
              <label className="row small muted"><input type="checkbox" checked={showAmbient} onChange={(e) => setShowAmbient(e.target.checked)} /> include background stream</label>
            </div>
            <div className="feed">
              {visibleFeed.length === 0 && <div className="empty">No decisions yet. Start a scenario or make a payment.</div>}
              {visibleFeed.map((d) => (
                <div key={d.decision_id} className={`feed-item ${fresh === d.decision_id ? "flash" : ""}`}
                     onClick={() => nav(`/investigate/${d.decision_id}`)}>
                  <TierChip tier={d.tier} />
                  <div className="grow">
                    <div className="who ellipsis">{handle(d.sender_id)} → {handle(d.recipient_id)} · <b className="mono">{formatINR(d.amount_paise)}</b></div>
                    <div className="why ellipsis">{d.tier === 0 ? "approved silently" : d.labels.join(" · ")}</div>
                  </div>
                  <div className="small muted mono">{formatTime(d.created_at)}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="card-title"><h2>RingWatch — accounts with network evidence</h2><Link className="small" to="/network">open network →</Link></div>
            <table className="data">
              <thead><tr><th>Account</th><th>Role</th><th>Evidence</th><th style={{ textAlign: "right" }}>Score</th></tr></thead>
              <tbody>
                {(ring.data ?? []).slice(0, 8).map((r) => (
                  <tr key={r.account_id} className="clickable" onClick={() => nav(`/network?focus=${encodeURIComponent(r.account_id)}`)}>
                    <td>{handle(r.account_id)}{r.labelled && <span className="chip t3" style={{ marginLeft: 4 }}>confirmed</span>}</td>
                    <td className="small">{r.role ?? "—"}</td>
                    <td className="small muted">{r.labels.slice(0, 3).join(", ")}</td>
                    <td className="mono" style={{ textAlign: "right" }}>{r.score.toFixed(2)}</td>
                  </tr>
                ))}
                {ring.data && ring.data.length === 0 && <tr><td colSpan={4} className="empty">No account currently shows network evidence.</td></tr>}
              </tbody>
            </table>
          </div>
          {health.data && (
            <div className="small muted">
              Policy <span className="mono">{health.data.policy_version}</span> · intel: {health.data.external_intel_provider} ·
              payments: {health.data.payment_provider_label} · ML on decision path: no · ledger total {m ? formatINR(m.system_total_paise) : "—"} (must be ₹0)
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
