// OPERATIONS CENTER (Overview v5) — reference layout (docs/reference_v5): what needs action first, then how money is
// moving, then why the models flag accounts (SHAP) and how detection is performing. Every number is read from the
// Vigil backend; live state arrives over the Shell's console WebSocket (no polling); the 3D canvas is imperative.
// Demo-only controls live in the Test inputs console (top bar), never on this page.
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AccountStatus, DetectorFamily, IntelOverview, UniverseAccount } from "../api/types";
import { CH, ChartCanvas, TIER_COLORS, baseOptions } from "../components/charts";
import { RoleIcon } from "../components/intel";
import { LiveStreams } from "../components/live/LiveStreams";
import { ScoreTables } from "../components/live/ScoreTables";
import { LiveUniverse3D, UniverseLegend, type UStats, type UniverseInfo } from "../components/LiveUniverse3D";
import { useConsoleEvents, usePlatform } from "../components/Shell";
import { StatePill, TierPill } from "../components/ui";
import { UniverseDrawer } from "../components/UniverseDrawer";
import { duration, formatINR, formatPaiseShort, handle } from "../lib/format";
import { useDebounced, useLoad, useNow } from "../lib/hooks";
import { useLiveStats } from "../lib/live";
import { rowAge, useInterventionQueue } from "../lib/queue";
import { ACCOUNT_STATUS_LABEL, ACCOUNT_STATUS_RANK, FAMILY, ROLE_LABEL, isAlarm, isRisky } from "../lib/status";

const I = {
  pulse: <path d="M3 12h4l3-8 4 16 3-8h4" />,
  shield: <><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M9 12l2 2 4-4" /></>,
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  alert: <><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4M12 17.5v.5" /></>,
  bars: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  brain: <><circle cx="12" cy="12" r="3" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></>,
  pay: <><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M3 10h18M7 15h3" /></>,
};
function Icon({ k }: { k: keyof typeof I }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">{I[k]}</svg>;
}
function KHead({ icon, title, act }: { icon: keyof typeof I; title: ReactNode; act?: ReactNode }) {
  return <div className="kcard-h"><span className="ic"><Icon k={icon} /></span><span>{title}</span>{act && <span className="act">{act}</span>}</div>;
}

/** Bars sparkline (reference "candles"), drawn from real per-bucket counts. */
function Spark({ values, color = "#2fbfa0" }: { values: number[]; color?: string }) {
  if (values.length < 2) return <div className="ksub" style={{ height: 60, display: "grid", alignItems: "center" }}>collecting live postings…</div>;
  const max = Math.max(1, ...values);
  const w = 300, h = 60, bw = w / values.length;
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-label="postings per 10 seconds">
      {values.map((v, i) => {
        const bh = Math.max(2, (v / max) * (h - 4));
        return <rect key={i} x={i * bw + bw * 0.18} y={h - bh} width={bw * 0.64} height={bh} rx={Math.min(2, bw * 0.3)} fill={color} opacity={0.35 + 0.65 * (i / values.length)} />;
      })}
    </svg>
  );
}

/** Semicircle gauge (reference "exposure" dial). */
function Gauge({ value }: { value: number | null }) {
  const v = value === null ? 0 : Math.max(0, Math.min(1, value));
  const r = 80, cx = 100, cy = 96;
  const a = Math.PI * (1 - v);
  const x = cx + r * Math.cos(a), y = cy - r * Math.sin(a);
  return (
    <svg className="gauge" viewBox="0 0 200 112" aria-hidden="true">
      <defs><linearGradient id="g-mint" x1="0" x2="1"><stop offset="0" stopColor="#bdf3e6" /><stop offset="1" stopColor="#2fbfa0" /></linearGradient></defs>
      <path d={`M${cx - r} ${cy} A${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="var(--surface-3)" strokeWidth="14" strokeLinecap="round" />
      {value !== null && <path d={`M${cx - r} ${cy} A${r} ${r} 0 0 1 ${x.toFixed(2)} ${y.toFixed(2)}`} fill="none" stroke="url(#g-mint)" strokeWidth="14" strokeLinecap="round" />}
      {value !== null && <><line x1={cx} y1={cy} x2={cx + (r - 22) * Math.cos(a)} y2={cy - (r - 22) * Math.sin(a)} stroke="#0f1419" strokeWidth="3" strokeLinecap="round" /><circle cx={cx} cy={cy} r="6" fill="#0f1419" /></>}
    </svg>
  );
}

function RiskBar({ value, status }: { value: number; status: AccountStatus }) {
  const on = Math.round(Math.max(0, Math.min(1, value)) * 10);
  const cls = status === "held" ? "held" : status === "flagged" || status === "confirmed_fraud" ? "crit" : "";
  return <span className={`riskbar ${cls}`} title={`risk ${value.toFixed(2)}`}>{Array.from({ length: 10 }, (_, i) => <i key={i} className={i < on ? "on" : ""} />)}</span>;
}

// ── header ────────────────────────────────────────────────────────────────
function Header({ suggest }: { suggest: UniverseAccount[] }) {
  const nav = useNavigate();
  const { conn, mode } = usePlatform();
  const [q, setQ] = useState("");
  const go = (e: FormEvent) => {
    e.preventDefault();
    const id = q.trim();
    if (id) nav(`/investigations/account/${encodeURIComponent(id.includes("@") ? id : `${id}@vigil`)}`);
  };
  return (
    <div className="oc-head">
      <h1>Operations center</h1>
      <form onSubmit={go} style={{ flex: "0 1 420px", minWidth: 220 }}>
        <input className="input search" placeholder="Search an account — e.g. kiran.traders" value={q} onChange={(e) => setQ(e.target.value)} list="oc-accounts" aria-label="Search an account" />
        <datalist id="oc-accounts">{suggest.slice(0, 40).map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</datalist>
      </form>
      <span className="spacer" />
      <span className="chip live" title="Realtime push channel"><span className={`dot ${conn === "open" ? "ok pulse" : conn === "connecting" ? "warn" : "bad"}`} />{conn === "open" ? "Live" : conn}</span>
      <span className="chip" title={mode?.note}>{mode?.mode === "shadow" ? "Shadow mode" : "Active mode"}</span>
      <Link className="btn" to="/network">Network view</Link>
    </div>
  );
}

// ── cards ─────────────────────────────────────────────────────────────────
function AlertsCard({ by, spark }: { by: Record<string, number> | null; spark: number[] }) {
  const n = (k: string) => (by ? by[k] ?? 0 : null);
  const alarm = by ? (n("flagged")! + n("held")! + n("confirmed_fraud")!) : null;
  return (
    <div className="kcard">
      <KHead icon="pulse" title="Accounts at risk" act={<Link className="btn xs" to="/network">View</Link>} />
      <div className="kbig">
        <span className="n">{alarm ?? "—"}</span>
        {by && <span className={`delta ${alarm ? "bad" : "flat"}`}>{alarm ? "action needed" : "all clear"}</span>}
      </div>
      <div className="ksub">{by ? `${n("flagged")} flagged · ${n("held")} held · ${n("confirmed_fraud")} confirmed · ${n("early_warning")} early warning` : "loading live statuses…"}</div>
      <Spark values={spark} />
      <div className="ksub" style={{ fontSize: 11.5 }}>Postings per 10 s, live</div>
    </div>
  );
}

function FrictionCard() {
  const { metrics: m } = usePlatform();
  const tiers = m?.decisions_by_tier ?? {};
  const total = Object.values(tiers).reduce((a, b) => a + b, 0);
  const passed = tiers["0"] ?? 0;
  const rate = total ? passed / total : null;
  return (
    <div className="kcard">
      <KHead icon="shield" title="Payments protected" act={<Link className="btn xs" to="/guard">Payments</Link>} />
      <div className="row" style={{ alignItems: "flex-end", gap: 12 }}>
        <div style={{ flex: "0 0 auto" }}>
          <div className="kbig"><span className="n">{rate === null ? "—" : `${(rate * 100).toFixed(1)}%`}</span></div>
          <div className="ksub">passed without friction</div>
        </div>
        <div className="grow"><Gauge value={rate} /></div>
      </div>
      <div className="ksub">{total ? `${passed.toLocaleString("en-IN")} of ${total.toLocaleString("en-IN")} pre-commit decisions · ${m?.open_interventions ?? 0} open · ${formatPaiseShort(m?.held_paise ?? 0)} held` : "no decisions yet"}</div>
    </div>
  );
}

function DetectorsCard() {
  const intel = useLoad<IntelOverview>(api.intelOverview);
  const refresh = useDebounced(() => intel.reload(), 1500);
  useConsoleEvents((e) => { if (e.type === "intel.updated" || e.type === "demo.reset" || e.type === "attack.run_updated") refresh(); });
  const d = intel.data;
  const rows = d ? Object.entries(d.detector_agreement).sort((a, b) => b[1] - a[1]) : [];
  const max = Math.max(1, ...rows.map(([, n]) => n));
  return (
    <div className="kcard">
      <KHead icon="grid" title="Detector families" act={<Link className="btn xs" to="/detection">Details</Link>} />
      <div className="ksub">Accounts each independent family flags right now</div>
      {!d ? <div className="ksub">{intel.unavailable ? "Detection intelligence not available." : "Loading…"}</div> : (
        <div className="heat" style={{ gridTemplateColumns: "minmax(100px, auto) 1fr 28px", marginTop: 6 }}>
          {rows.map(([fam, n]) => (
            <div key={fam} style={{ display: "contents" }}>
              <span className="lbl">{FAMILY[fam as DetectorFamily]?.label ?? fam}</span>
              <span className="cell" style={{ position: "relative", overflow: "hidden" }}>
                <i style={{ position: "absolute", inset: 0, width: `${(n / max) * 100}%`, background: n ? "linear-gradient(90deg, #bdf3e6, #4fd6b8)" : "transparent", borderRadius: 6 }} />
              </span>
              <span className="mono" style={{ textAlign: "right", color: "var(--ink)" }}>{n}</span>
            </div>
          ))}
        </div>
      )}
      {d && Object.keys(d.role_counts).length > 0 && (
        <div className="row wrap tight" style={{ marginTop: 8 }}>
          {Object.entries(d.role_counts).map(([r, n]) => <span key={r} className="tag"><RoleIcon role={r} size={11} />&nbsp;{ROLE_LABEL[r] ?? r} {n}</span>)}
        </div>
      )}
      <div className="row wrap tight" style={{ marginTop: 6 }}><span className="stamp-sv">Synthetic validation</span><span className="ksub">models corroborate; rules decide</span></div>
    </div>
  );
}

function AttentionCard({ risky }: { risky: UniverseAccount[] }) {
  const nav = useNavigate();
  const [tab, setTab] = useState<"accounts" | "payments">("accounts");
  const now = useNow(10000);
  const q = useInterventionQueue("open");
  const refresh = useDebounced(() => q.rows.reload(), 1200);
  useConsoleEvents((e) => {
    if ((e.type === "decision.created" && ((e.data as { tier?: number })?.tier ?? 0) >= 2) || e.type === "intent.updated" || e.type.startsWith("breaker.") || e.type === "demo.reset") refresh();
  });
  const payments = q.all.filter((r) => r.tier >= 2);
  return (
    <div className="kcard" style={{ paddingBottom: 10 }}>
      <KHead icon="alert" title="Needs attention" act={
        <div className="seg">
          <button className={tab === "accounts" ? "on" : ""} onClick={() => setTab("accounts")}>Accounts · {risky.length}</button>
          <button className={tab === "payments" ? "on" : ""} onClick={() => setTab("payments")}>Payments · {payments.length}</button>
        </div>} />
      {tab === "accounts" ? (
        risky.length === 0 ? <div className="empty">No account is flagged, held or under early warning. Statuses update live as postings are scored.</div> : (
          <table className="dt" style={{ marginTop: 6 }}>
            <thead><tr><th>Account</th><th>Status</th><th>Risk</th><th>Role</th><th /></tr></thead>
            <tbody>
              {risky.slice(0, 7).map((a) => (
                <tr key={a.id} className="click" onClick={() => nav(`/investigations/account/${encodeURIComponent(a.id)}`)}>
                  <td><div className="row tight"><span className={`av-ic ${a.status === "held" ? "held" : isAlarm(a.status) ? "crit" : "warn"}`}><Icon k="user" /></span>
                    <span className="cell-2l"><b>{a.label}</b><small>{a.id}</small></span></div></td>
                  <td><span className={`pill as-${a.status}`}>{ACCOUNT_STATUS_LABEL[a.status]}</span></td>
                  <td><RiskBar value={Math.max(a.risk ?? 0, a.model_risk ?? 0)} status={a.status} /></td>
                  <td className="sm">{a.role ? <span className="row tight"><RoleIcon role={a.role} size={12} />{ROLE_LABEL[a.role] ?? a.role}</span> : <span className="dim">—</span>}</td>
                  <td className="right"><span className="btn xs">Open</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : payments.length === 0 ? <div className="empty">No payment is held or awaiting confirmation. Holds appear here the moment they are decided.</div> : (
        <table className="dt" style={{ marginTop: 6 }}>
          <thead><tr><th>Payment</th><th className="num">Amount</th><th>Tier</th><th>State</th><th className="num">Age</th></tr></thead>
          <tbody>
            {payments.slice(0, 7).map((r) => (
              <tr key={r.decision_id} className="click" onClick={() => nav(`/investigations/decision/${r.decision_id}`)}>
                <td><div className="row tight"><span className={`av-ic ${r.tier >= 3 ? "held" : "warn"}`}><Icon k="pay" /></span>
                  <span className="cell-2l"><b>{handle(r.sender_id)} → {handle(r.recipient_id)}</b><small>{r.decision_id} · {r.headline}</small></span></div></td>
                <td className="num">{formatINR(r.amount_paise)}</td>
                <td><TierPill tier={r.tier} /></td>
                <td><StatePill state={r.state} /></td>
                <td className="num xs">{duration(rowAge(r, now, q.fetchedAt))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function TrafficCard({ stats }: { stats: ReturnType<typeof useLiveStats> }) {
  const v = stats.data?.volume ?? [];
  const labels = v.map((p) => new Date(p.t).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }));
  const total = v.reduce((a, p) => a + p.normal + p.attack, 0);
  const injected = v.reduce((a, p) => a + p.attack, 0);
  return (
    <div className="kcard">
      <KHead icon="bars" title="Transaction traffic" act={<span className="row tight"><span className="legend-dot"><i style={{ background: CH.teal }} />Postings</span><span className="legend-dot"><i style={{ background: CH.red }} />Test injections</span></span>} />
      <div className="kbig">
        <span className="n">{stats.data ? total.toLocaleString("en-IN") : "—"}</span>
        <span className="unit">postings in the window</span>
        {stats.data && <span className="delta flat">{stats.data.throughput_tps.toFixed(2)} tx/s</span>}
        {injected > 0 && <span className="delta bad">{injected} injected</span>}
      </div>
      <ChartCanvas type="line" height={232} empty={stats.unavailable ? "Live statistics not available." : "Collecting live postings…"}
        data={{ labels, datasets: [
          { label: "Postings", data: v.map((p) => p.normal), borderColor: CH.teal, backgroundColor: "rgba(79,214,184,0.16)", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2 },
          { label: "Test injections", data: v.map((p) => p.attack), borderColor: CH.red, backgroundColor: "rgba(224,71,61,0.08)", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2 },
        ] }}
        options={baseOptions({ plugins: { legend: { display: false } }, interaction: { mode: "index", intersect: false } }) as never} />
    </div>
  );
}

/** Model drivers: signed SHAP by category, summed over the accounts that are flagged / warned right now. */
function DriversCard({ risky, top }: { risky: UniverseAccount[]; top: UniverseAccount[] }) {
  const subjects = (risky.length ? risky : top).slice(0, 5);
  const key = subjects.map((a) => `${a.id}:${a.status}`).join("|");
  const [agg, setAgg] = useState<{ cats: [string, number][]; n: number; ids: string[] } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!subjects.length) { setAgg(null); return; }
    let alive = true;
    const t = window.setTimeout(() => {
      Promise.all(subjects.map((a) => api.intelAccount(a.id).catch(() => null))).then((res) => {
        if (!alive) return;
        const sum: Record<string, number> = {};
        let n = 0;
        res.forEach((x) => {
          const net = x?.shap?.category_net;
          if (!net) return;
          n++;
          Object.entries(net).forEach(([c, v]) => { sum[c] = (sum[c] ?? 0) + v; });
        });
        setErr(n ? null : "No SHAP explanation available for these accounts.");
        setAgg({ cats: Object.entries(sum).filter(([, v]) => Math.abs(v) >= 0.001).sort((p, q) => Math.abs(q[1]) - Math.abs(p[1])).slice(0, 7), n, ids: subjects.map((a) => a.id) });
      });
    }, 600);
    return () => { alive = false; window.clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return (
    <div className="kcard">
      <KHead icon="brain" title="What drives the model" act={<span className="stamp-sv">SHAP</span>} />
      <div className="ksub">{risky.length ? `Signed SHAP by category, summed over the ${subjects.length} highest-risk flagged / warned accounts` : `No account is flagged — showing the ${subjects.length} highest model scores`}. Explains the Random Forest, not the payment decision.</div>
      {err ? <div className="ksub">{err}</div> : !agg ? <div className="ksub">Loading…</div> : (
        <ChartCanvas type="bar" height={210} empty="No category moved the score."
          data={{ labels: agg.cats.map(([c]) => c), datasets: [{ label: "SHAP (signed)", data: agg.cats.map(([, v]) => v),
            backgroundColor: agg.cats.map(([, v]) => (v >= 0 ? CH.red : CH.blue)), borderRadius: 6, barThickness: 14 }] }}
          options={baseOptions({ indexAxis: "y", plugins: { legend: { display: false } },
            scales: { x: { grid: { color: "rgba(15,20,25,0.06)" }, border: { display: false }, ticks: { color: "#8a939e" } }, y: { grid: { display: false }, border: { display: false }, ticks: { color: "#3c4652" } } } }) as never} />
      )}
      {agg && <div className="row wrap tight">{agg.ids.map((id) => <Link key={id} className="tag mono" to={`/investigations/account/${encodeURIComponent(id)}`}>{handle(id)}</Link>)}</div>}
      <div className="ksub"><span style={{ color: CH.red }}>■</span> raised the score · <span style={{ color: CH.blue }}>■</span> lowered it</div>
    </div>
  );
}

function DecisionsCard({ stats }: { stats: ReturnType<typeof useLiveStats> }) {
  const t = stats.data?.tiers_over_time ?? [];
  const labels = t.map((p) => new Date(p.t).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }));
  const keys = ["t0", "t1", "t2", "t3", "t4"] as const;
  const names = ["T0 pass", "T1 inform", "T2 confirm", "T3 hold", "T4 hold + contact"];
  return (
    <div className="kcard">
      <KHead icon="shield" title="Pre-commit decisions" act={<Link className="btn xs" to="/interventions">Queue</Link>} />
      <div className="ksub">Every payment intent, by intervention tier, per minute</div>
      <ChartCanvas type="bar" height={232} empty={stats.unavailable ? "Live statistics not available." : "No decisions in the window yet."}
        data={{ labels, datasets: keys.map((k, i) => ({ label: names[i], data: t.map((p) => p[k]), backgroundColor: TIER_COLORS[i], borderRadius: 4, stack: "t", maxBarThickness: 26 })) }}
        options={baseOptions({ scales: { x: { stacked: true, grid: { display: false }, border: { display: false }, ticks: { color: "#8a939e", maxTicksLimit: 6 } }, y: { stacked: true, beginAtZero: true, grid: { color: "rgba(15,20,25,0.06)" }, border: { display: false }, ticks: { color: "#8a939e" } } },
          plugins: { legend: { position: "bottom", labels: { color: "#69737f", boxWidth: 8, boxHeight: 8, usePointStyle: true } } } }) as never} />
    </div>
  );
}

function PatternsCard() {
  const intel = useLoad<IntelOverview>(api.intelOverview);
  const refresh = useDebounced(() => intel.reload(), 1500);
  useConsoleEvents((e) => { if (e.type === "intel.updated" || e.type === "demo.reset" || e.type === "attack.run_updated") refresh(); });
  const d = intel.data;
  const pats = (d?.pattern_alerts ?? []).slice(0, 5);
  const ews = (d?.early_warnings ?? []).slice(0, 4);
  return (
    <div className="kcard">
      <KHead icon="grid" title="Pattern memory & early warning" act={<Link className="btn xs" to="/detection">All</Link>} />
      <div className="ksub">Structural similarity to stored mule signatures (not attribution), and behaviour change before mule structure exists</div>
      {!d ? <div className="ksub">{intel.unavailable ? "Detection intelligence not available." : "Loading…"}</div> : (
        <div className="stack tight" style={{ gap: 8, marginTop: 4 }}>
          {pats.length === 0 && ews.length === 0 && <div className="empty" style={{ padding: 12 }}>No pattern match or early warning right now.</div>}
          {pats.map((p) => (
            <Link key={`p-${p.account_id}`} to={`/investigations/account/${encodeURIComponent(p.account_id)}`} className="row" style={{ color: "inherit", textDecoration: "none" }}>
              <span className="cell-2l grow"><b>{handle(p.account_id)}</b><small>similar to {p.match.name}</small></span>
              <span className="mono sm">{Math.round(p.match.similarity * 100)}%</span>
            </Link>
          ))}
          {ews.map((w) => (
            <Link key={`e-${w.account_id}`} to={`/investigations/account/${encodeURIComponent(w.account_id)}`} className="row" style={{ color: "inherit", textDecoration: "none" }}>
              <span className="cell-2l grow"><b>{handle(w.account_id)}</b><small>early warning · {w.signals.join(", ") || "behaviour change"}</small></span>
              <span className="pill as-early_warning nodot">{w.score.toFixed(2)}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// ── page ──────────────────────────────────────────────────────────────────
export function OverviewPage() {
  const stats = useLiveStats(5000);
  const accounts = useRef(new Map<string, UniverseAccount>());
  const [by, setBy] = useState<Record<string, number> | null>(null);
  const [lists, setLists] = useState<{ risky: UniverseAccount[]; top: UniverseAccount[] }>({ risky: [], top: [] });
  const [recent, setRecent] = useState<UniverseInfo["recent"] | null>(null);
  const [uniVersion, setUniVersion] = useState(0);
  const [sel, setSel] = useState<{ id: string; acct: UniverseAccount | null } | null>(null);
  const [focus, setFocus] = useState<{ ids: string[]; seq: number } | null>(null);

  const recompute = useCallback(() => {
    const all = [...accounts.current.values()].filter((a) => a.kind === "customer");
    const risky = all.filter((a) => isRisky(a.status))
      .sort((p, q) => ACCOUNT_STATUS_RANK[q.status] - ACCOUNT_STATUS_RANK[p.status] || Math.max(q.risk, q.model_risk ?? 0) - Math.max(p.risk, p.model_risk ?? 0));
    const top = [...all].sort((p, q) => (q.model_risk ?? 0) - (p.model_risk ?? 0)).slice(0, 3);
    setLists((prev) => {
      const k = (xs: UniverseAccount[]) => xs.map((a) => `${a.id}:${a.status}`).join("|");
      return k(prev.risky) === k(risky) && k(prev.top) === k(top) ? prev : { risky, top };
    });
  }, []);
  const onInfo = useCallback((i: UniverseInfo) => { accounts.current = i.accounts; setRecent((r) => r ?? i.recent); setUniVersion((n) => n + 1); recompute(); }, [recompute]);
  const onStats = useCallback((s: UStats) => { setBy(s.byStatus); recompute(); }, [recompute]);
  const statusOf = useCallback((id: string): AccountStatus | null => accounts.current.get(id)?.status ?? null, []);
  const onSelect = useCallback((id: string | null, acct: UniverseAccount | null) => setSel(id ? { id, acct } : null), []);
  const spark = useMemo(() => (stats.data?.volume ?? []).slice(-30).map((p) => p.normal + p.attack), [stats.data]);
  const counts = stats.data?.counts;
  const byStatus = by ?? (counts ? { flagged: counts.flagged ?? 0, held: counts.held ?? 0, confirmed_fraud: counts.confirmed ?? 0, early_warning: counts.warnings ?? 0 } : null);

  return (
    <>
      <Header suggest={lists.risky.length ? [...lists.risky, ...lists.top] : [...accounts.current.values()].filter((a) => a.kind === "customer").slice(0, 40)} />

      <div className="oc-grid">
        <section className="stage">
          <div className="stage-h">
            <div>
              <div className="t">Live transaction network</div>
              <UniverseLegend />
            </div>
            <div className="row tight">
              <button className="btn xs" onClick={() => setFocus({ ids: [...accounts.current.keys()], seq: Date.now() })}>Reset view</button>
              <Link className="btn xs on" to="/network">Open</Link>
            </div>
          </div>
          <div style={{ position: "relative" }}>
            <LiveUniverse3D mode="live" autoRotate={!sel} size="compact" selected={sel?.id ?? null}
                            onSelect={onSelect} onInfo={onInfo} onStats={onStats} focus={focus} />
            {sel && <UniverseDrawer id={sel.id} acct={accounts.current.get(sel.id) ?? sel.acct} onClose={() => setSel(null)}
                                    onFocus={() => setFocus({ ids: [sel.id], seq: Date.now() })} />}
          </div>
        </section>
        <div className="oc-col">
          <AlertsCard by={byStatus} spark={spark} />
          <FrictionCard />
        </div>
        <DetectorsCard />
      </div>

      <div className="oc-grid2">
        <AttentionCard risky={lists.risky} />
        <TrafficCard stats={stats} />
      </div>

      <div className="oc-section"><h2>Why accounts are flagged</h2><span>model explanations, structural patterns and decisions — live</span></div>
      <div className="oc-grid3" style={{ marginTop: 0 }}>
        <DriversCard risky={lists.risky} top={lists.top} />
        <PatternsCard />
        <DecisionsCard stats={stats} />
      </div>

      <div className="oc-section"><h2>Live activity</h2><span>every posting scored as it lands</span></div>
      <LiveStreams statusOf={statusOf} recent={recent} />

      <div className="oc-section"><h2>Scoring</h2><span>transparent rules beside the corroborating models</span></div>
      <ScoreTables key={uniVersion > 0 ? "u" : "n"} statusOf={statusOf} />
    </>
  );
}
