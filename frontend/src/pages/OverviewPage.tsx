// OPERATIONS CENTER (Overview v9) — the live view of the bank's payment network, and nothing that has a home elsewhere:
//   KPI strip → live transaction network (full width) → needs attention · close monitoring → money moving now · new accounts.
// Analysis lives on its own pages: detector scores, SHAP and model metrics on Detection; payment decisions by tier on
// Governance; live streams on Network. Every number is read from the Vigil backend; live state arrives over the Shell's
// console WebSocket (no polling); the 3D canvas is imperative. Demo-only controls live in Test inputs (top bar).
import { useCallback, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AccountStatus, AttackRun, LedgerTx, NewAccount, UniverseAccount } from "../api/types";
import { CH, ChartCanvas, baseOptions } from "../components/charts";
import { RoleIcon } from "../components/intel";
import { KpiStrip } from "../components/OverviewAnalytics";
import { EdgeViewSeg, LiveUniverse3D, UniverseLegend, type EdgeView, type UStats, type UniverseInfo } from "../components/LiveUniverse3D";
import { useConsoleEvents, usePlatform } from "../components/Shell";
import { StatePill, TierPill } from "../components/ui";
import { UniverseDrawer } from "../components/UniverseDrawer";
import { WatchlistCard } from "../components/Watchlist";
import { duration, formatINR, formatPaiseShort, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad, useNow } from "../lib/hooks";
import { useAttackRuns, useLiveStats } from "../lib/live";
import { rowAge, useInterventionQueue } from "../lib/queue";
import { ACCOUNT_STATUS_LABEL, ACCOUNT_STATUS_RANK, ROLE_LABEL, isAlarm, isRisky } from "../lib/status";

const I = {
  alert: <><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4M12 17.5v.5" /></>,
  bars: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></>,
  userPlus: <><circle cx="10" cy="8" r="4" /><path d="M2 21c1.5-4 4.5-6 8-6 1.6 0 3.1.4 4.4 1.2M19 14v6M16 17h6" /></>,
  pay: <><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M3 10h18M7 15h3" /></>,
};
function Icon({ k }: { k: keyof typeof I }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">{I[k]}</svg>;
}
function KHead({ icon, title, act }: { icon: keyof typeof I; title: ReactNode; act?: ReactNode }) {
  return <div className="kcard-h"><span className="ic"><Icon k={icon} /></span><span>{title}</span>{act && <span className="act">{act}</span>}</div>;
}

function RiskBar({ value, status }: { value: number; status: AccountStatus }) {
  const on = Math.round(Math.max(0, Math.min(1, value)) * 10);
  const cls = status === "held" ? "held" : status === "flagged" || status === "confirmed_fraud" ? "crit" : "";
  return <span className={`riskbar ${cls}`} title={`risk ${value.toFixed(2)}`}>{Array.from({ length: 10 }, (_, i) => <i key={i} className={i < on ? "on" : ""} />)}</span>;
}

const EDGE_HELP: Record<EdgeView, string> = {
  recent: "Lines = payments in the last 2 minutes; they fade as they age.",
  window: "Lines = every payment in the last 10 minutes.",
  risk: "Only payments touching an account at early warning or worse (incl. older history); ordinary accounts dimmed.",
  all: "Last 10 minutes plus a faint sample of older history: how the economy is connected.",
  none: "Accounts only, no payment lines.",
};

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
    </div>
  );
}

// ── needs attention ───────────────────────────────────────────────────────
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
  const n = (k: AccountStatus) => risky.filter((a) => a.status === k).length;
  return (
    <div className="kcard attn-card">
      <KHead icon="alert" title="Needs attention" act={
        <div className="seg">
          <button className={tab === "accounts" ? "on" : ""} onClick={() => setTab("accounts")}>Accounts · {risky.length}</button>
          <button className={tab === "payments" ? "on" : ""} onClick={() => setTab("payments")}>Payments · {payments.length}</button>
        </div>} />
      <div className="ksub">{tab === "accounts"
        ? "Accounts flagged, held, confirmed as fraud or at early warning right now, and why. Click a row to investigate."
        : "Payments held or waiting for the customer to confirm. Click a row for the case; release or reject in Interventions."}</div>
      {tab === "accounts" ? (
        risky.length === 0 ? <div className="empty">No account is flagged, held or under early warning. Statuses update live as payments are scored.</div> : (
          <div className="attn-scroll">
            <table className="dt attn">
              <thead><tr><th>Account · why</th><th>Status</th><th title="Strongest of the network score (RingWatch) and model evidence">Risk</th><th className="num" title="Independent detector families flagging the account">Agree</th><th>Role</th></tr></thead>
              <tbody>
                {risky.map((a) => (
                  <tr key={a.id} className="click" onClick={() => nav(`/investigations/account/${encodeURIComponent(a.id)}`)}>
                    <td><div className="row tight"><span className={`av-ic ${a.status === "held" ? "held" : isAlarm(a.status) ? "crit" : "warn"}`}><Icon k="user" /></span>
                      <span className="cell-2l"><b>{a.label}</b><small className="why" title={a.reason ?? a.id}>{a.reason || a.id}</small></span></div></td>
                    <td><span className={`pill as-${a.status}`}>{ACCOUNT_STATUS_LABEL[a.status]}</span>
                      {a.status_since && <small className="since">since {formatTime(a.status_since).slice(0, 5)}</small>}</td>
                    <td><RiskBar value={Math.max(a.risk ?? 0, a.model_risk ?? 0)} status={a.status} /></td>
                    <td className="num mono">{a.families_flagging ? a.families_flagging : <span className="dim">—</span>}</td>
                    <td className="sm">{a.role ? <span className="row tight"><RoleIcon role={a.role} size={12} />{ROLE_LABEL[a.role] ?? a.role}</span> : <span className="dim">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : payments.length === 0 ? <div className="empty">No payment is held or awaiting confirmation. Holds appear here the moment they are decided.</div> : (
        <div className="attn-scroll">
          <table className="dt attn">
            <thead><tr><th>Payment</th><th className="num">Amount</th><th>Tier</th><th>State</th><th className="num">Age</th></tr></thead>
            <tbody>
              {payments.map((r) => (
                <tr key={r.decision_id} className="click" onClick={() => nav(`/investigations/decision/${r.decision_id}`)}>
                  <td><div className="row tight"><span className={`av-ic ${r.tier >= 3 ? "held" : "warn"}`}><Icon k="pay" /></span>
                    <span className="cell-2l"><b>{handle(r.sender_id)} → {handle(r.recipient_id)}</b><small className="why">{r.decision_id} · {r.headline}</small></span></div></td>
                  <td className="num">{formatINR(r.amount_paise)}</td>
                  <td><TierPill tier={r.tier} /></td>
                  <td><StatePill state={r.state} /></td>
                  <td className="num xs">{duration(rowAge(r, now, q.fetchedAt))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "accounts" && risky.length > 0 && (
        <div className="attn-foot">
          <span><i style={{ background: "var(--as-flagged)" }} />{n("flagged")} flagged</span>
          <span><i style={{ background: "var(--as-held)" }} />{n("held")} held</span>
          <span><i style={{ background: "var(--as-fraud)" }} />{n("confirmed_fraud")} confirmed</span>
          <span><i style={{ background: "var(--as-early)" }} />{n("early_warning")} early warning</span>
        </div>
      )}
    </div>
  );
}

// ── money moving now ──────────────────────────────────────────────────────
const ORIGIN_LABEL = { everyday: "Everyday", customer: "Customer", injected: "Injected" } as const;
const ORIGIN_COLOR = { everyday: CH.teal, customer: CH.blue, injected: CH.red } as const;

function MoneyCard({ stats, statusOf }: { stats: ReturnType<typeof useLiveStats>; statusOf: (id: string) => AccountStatus | null }) {
  const t = stats.data?.traffic;
  const b = t?.buckets ?? [];
  const labels = b.map((p) => new Date(p.t).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false }));
  const channels = Object.entries(t?.channels ?? {});
  const chTotal = channels.reduce((a, [, v]) => a + v, 0);
  const ds = (k: keyof typeof ORIGIN_LABEL) => ({
    label: ORIGIN_LABEL[k], data: b.map((p) => p[k]), backgroundColor: ORIGIN_COLOR[k], borderRadius: 3, stack: "s", maxBarThickness: 24,
  });
  return (
    <div className="kcard">
      <KHead icon="bars" title="Money moving now" act={<span className="row tight wrap">
        <span className="legend-dot"><i style={{ background: CH.teal }} />Everyday economy</span>
        <span className="legend-dot"><i style={{ background: CH.blue }} />Customer payments</span>
        <span className="legend-dot"><i style={{ background: CH.red }} />Test injections</span></span>} />
      <div className="mstrip dense money-strip">
        <div className="m"><div className="k">Payments · 10 min</div><div className="v">{t ? t.postings.toLocaleString("en-IN") : "—"}</div><div className="d">{stats.data ? `${stats.data.throughput_tps.toFixed(2)} per second now` : ""}</div></div>
        <div className="m"><div className="k">Value moved</div><div className="v">{t ? formatPaiseShort(t.value_paise) : "—"}</div><div className="d">{t && t.postings ? `average payment ${formatPaiseShort(t.avg_paise)}` : "no payments yet"}</div></div>
        <div className="m"><div className="k">Touching risky accounts</div><div className="v" style={{ color: t?.risky_postings ? "var(--st-high)" : undefined }}>{t ? t.risky_postings : "—"}</div><div className="d">sender or recipient at early warning+</div></div>
        <div className="m"><div className="k">Channels</div><div className="v">{channels.length ? channels.map(([c]) => c.toUpperCase()).slice(0, 3).join(" · ") : "—"}</div><div className="d">{channels.length ? channels.map(([c, v]) => `${c.toUpperCase()} ${Math.round((v / Math.max(1, chTotal)) * 100)}%`).join(" · ") : ""}</div></div>
      </div>
      <ChartCanvas type="bar" height={210} empty={stats.unavailable ? "Live statistics not available." : "Collecting live payments…"}
        data={{ labels, datasets: [ds("everyday"), ds("customer"), ds("injected")] }}
        options={baseOptions({ plugins: { legend: { display: false }, tooltip: { callbacks: {
            footer: (items: { dataIndex: number }[]) => (items.length ? `value ${formatINR(b[items[0].dataIndex]?.value_paise ?? 0)}` : "") } } },
          interaction: { mode: "index", intersect: false },
          scales: { x: { stacked: true, grid: { display: false }, border: { display: false }, ticks: { color: "#8a939e", maxTicksLimit: 6, maxRotation: 0 } },
                    y: { stacked: true, beginAtZero: true, grid: { color: "rgba(15,20,25,0.06)" }, border: { display: false }, ticks: { color: "#8a939e", precision: 0 },
                         title: { display: true, text: "payments per 30 s", color: "#8a939e", font: { size: 10.5 } } } } }) as never} />
      <div className="ksub how"><b>How to read:</b> each bar counts every payment posted to the ledger in 30 seconds, over the last 10 minutes. <b>Everyday</b> is the simulated economy running in the background (groceries, bills, rent). <b>Customer</b> is a payment made on the customer's phone (Payments page). <b>Injected</b> is an attack pattern started from Test inputs, so a red block appearing out of nowhere is an attack arriving.</div>
      <div className="sect-t" style={{ marginTop: 6 }}>Largest payments in the last 10 minutes</div>
      {!t || t.largest.length === 0 ? <div className="ksub">No payment yet.</div> : (
        <table className="dt compact money-top">
          <tbody>
            {t.largest.map((x) => {
              const st = statusOf(x.recipient_id);
              return (
                <tr key={x.id}>
                  <td className="mono xs dim">{formatTime(x.ts)}</td>
                  <td className="xs"><Link to={`/investigations/account/${encodeURIComponent(x.sender_id)}`}>{handle(x.sender_id)}</Link> → <Link to={`/investigations/account/${encodeURIComponent(x.recipient_id)}`}>{handle(x.recipient_id)}</Link>
                    {st && isRisky(st) && <span className={`pill as-${st}`} style={{ marginLeft: 6 }}>{ACCOUNT_STATUS_LABEL[st]}</span>}</td>
                  <td className="xs"><span className="tag" style={{ color: ORIGIN_COLOR[x.origin] }}>{ORIGIN_LABEL[x.origin]}</span></td>
                  <td className="xs mono dim">{x.channel.toUpperCase()}</td>
                  <td className="num mono">{formatINR(x.amount_paise)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── new accounts ──────────────────────────────────────────────────────────
function useNewAccounts() {
  const l = useLoad<NewAccount[]>(() => api.newAccounts(30));
  const refresh = useDebounced(() => l.reload(), 1500);
  const ids = useRef(new Set<string>());
  ids.current = new Set((l.data ?? []).map((a) => a.id));
  useConsoleEvents((e) => {
    if (["account.opened", "demo.reset", "intel.account_status"].includes(e.type)) refresh();
    else if (e.type === "ledger.posted") {
      const tx = e.data as LedgerTx;
      if (tx && (ids.current.has(tx.sender_id) || ids.current.has(tx.recipient_id))) refresh();
    }
  });
  return l;
}

function NewAccountsCard({ load }: { load: ReturnType<typeof useNewAccounts> }) {
  const nav = useNavigate();
  const rows = load.data ?? [];
  return (
    <div className="kcard">
      <KHead icon="userPlus" title="New accounts" act={<span className="chip mute">opened in the last 30 days</span>} />
      <div className="ksub">Mule accounts are often freshly opened and start receiving money from many people within days. Every recently opened account, and what has flowed through it since it was opened.</div>
      {!load.data ? <div className="ksub">{load.unavailable ? "Not available on this server." : "Loading…"}</div> : rows.length === 0 ? <div className="empty">No account opened in the last 30 days.</div> : (
        <div className="new-list">
          {rows.map((a) => (
            <div key={a.id} className="new-row" role="link" tabIndex={0} onClick={() => nav(`/investigations/account/${encodeURIComponent(a.id)}`)}>
              <div className="row tight" style={{ alignItems: "flex-start" }}>
                <span className="cell-2l grow"><b>{a.label}</b><small>{handle(a.id)} · opened {a.age_days < 1 ? `${Math.max(1, Math.round(a.age_days * 24))} h` : `${a.age_days.toFixed(a.age_days < 10 ? 1 : 0)} days`} ago</small></span>
                <span className={`pill as-${a.status}`}>{ACCOUNT_STATUS_LABEL[a.status]}</span>
              </div>
              <div className="watch-act">
                <span>In <b>{formatPaiseShort(a.in_paise)}</b>{a.senders ? ` from ${a.senders} sender${a.senders === 1 ? "" : "s"}` : ""}</span>
                <span>Out <b>{formatPaiseShort(a.out_paise)}</b></span>
                {a.first_inflow_at && <span className="dim">first money received {formatTime(a.first_inflow_at).slice(0, 5)}</span>}
              </div>
              {(a.large_inflow_rule || a.shared_device_accounts > 0) && (
                <div className="row tight wrap">
                  {a.large_inflow_rule && <span className="tag danger" title="Policy rule network.new_account_inflow: opened under 14 days ago and received at least ₹50,000">large inflow while new</span>}
                  {a.shared_device_accounts > 0 && <span className="tag warn" title="Other accounts registered on the same device">device shared with {a.shared_device_accounts} other account{a.shared_device_accounts === 1 ? "" : "s"}</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── page ──────────────────────────────────────────────────────────────────
export function OverviewPage() {
  const stats = useLiveStats(4000);
  const runs = useAttackRuns();
  const fresh = useNewAccounts();
  const [edgeView, setEdgeView] = useState<EdgeView>("recent");
  const accounts = useRef(new Map<string, UniverseAccount>());
  const [by, setBy] = useState<Record<string, number> | null>(null);
  const [risky, setRisky] = useState<UniverseAccount[]>([]);
  const [sel, setSel] = useState<{ id: string; acct: UniverseAccount | null } | null>(null);
  const [focus, setFocus] = useState<{ ids: string[]; seq: number } | null>(null);
  const netRef = useRef<HTMLElement>(null);

  const recompute = useCallback(() => {
    const list = [...accounts.current.values()].filter((a) => a.kind === "customer" && isRisky(a.status))
      .sort((p, q) => ACCOUNT_STATUS_RANK[q.status] - ACCOUNT_STATUS_RANK[p.status] || Math.max(q.risk, q.model_risk ?? 0) - Math.max(p.risk, p.model_risk ?? 0));
    setRisky((prev) => {
      const k = (xs: UniverseAccount[]) => xs.map((a) => `${a.id}:${a.status}:${a.reason ?? ""}`).join("|");
      return k(prev) === k(list) ? prev : list;
    });
  }, []);
  const onInfo = useCallback((i: UniverseInfo) => { accounts.current = i.accounts; recompute(); }, [recompute]);
  const onStats = useCallback((s: UStats) => { setBy(s.byStatus); recompute(); }, [recompute]);
  const onSelect = useCallback((id: string | null, acct: UniverseAccount | null) => setSel(id ? { id, acct } : null), []);
  const statusOf = useCallback((id: string): AccountStatus | null => accounts.current.get(id)?.status ?? null, []);
  const counts = stats.data?.counts;
  const byStatus = by ?? (counts ? { flagged: counts.flagged ?? 0, held: counts.held ?? 0, confirmed_fraud: counts.confirmed_fraud ?? 0, early_warning: counts.early_warning ?? 0 } : null);
  const showRun = useCallback((r: AttackRun) => {
    setEdgeView("risk");
    setFocus({ ids: r.injected, seq: Date.now() });
    const el = netRef.current;
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 84, behavior: "smooth" });
  }, []);
  const suggest = useMemo(() => (risky.length ? risky : [...accounts.current.values()].filter((a) => a.kind === "customer").slice(0, 40)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [risky, by]);

  return (
    <>
      <Header suggest={suggest} />
      <KpiStrip stats={stats.data} runs={runs.data} by={byStatus} fresh={fresh.data} onRun={showRun} />

      <section className="stage oc-net" ref={netRef}>
        <div className="stage-h">
          <div>
            <div className="t">Live transaction network</div>
            <div className="net-help">Every dot is an account and every line a payment, drawn the moment it is posted. Colour = the account's live status; labelled dots need attention. Click a dot to inspect it, drag to rotate, scroll to zoom.</div>
          </div>
          <div className="row tight">
            <button className="btn xs" onClick={() => setFocus({ ids: [...accounts.current.keys()], seq: Date.now() })}>Reset view</button>
            {risky.length > 0 && <button className="btn xs" onClick={() => { setEdgeView("risk"); setFocus({ ids: risky.map((a) => a.id), seq: Date.now() }); }}>Zoom to {risky.length} at risk</button>}
            <Link className="btn xs on" to="/network">Full network view</Link>
          </div>
        </div>
        <div className="stage-filter">
          <span>Edges</span><EdgeViewSeg value={edgeView} onChange={setEdgeView} />
          <span className="edge-help">{EDGE_HELP[edgeView]}</span>
          <span className="spacer" />
          <UniverseLegend />
        </div>
        <div style={{ position: "relative" }}>
          <LiveUniverse3D mode="live" edgeView={edgeView} autoRotate={!sel} size="hero" selected={sel?.id ?? null}
                          onSelect={onSelect} onInfo={onInfo} onStats={onStats} focus={focus} />
          {sel && <UniverseDrawer id={sel.id} acct={accounts.current.get(sel.id) ?? sel.acct} onClose={() => setSel(null)}
                                  onFocus={() => setFocus({ ids: [sel.id], seq: Date.now() })} />}
        </div>
      </section>

      <div className="oc-pair">
        <AttentionCard risky={risky} />
        <WatchlistCard />
      </div>

      <div className="oc-split">
        <MoneyCard stats={stats} statusOf={statusOf} />
        <NewAccountsCard load={fresh} />
      </div>
    </>
  );
}
