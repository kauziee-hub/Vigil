// Overview analytics blocks: KPI strip, detection performance (the mule-detection analytics), account scoring table.
// Every value comes from the backend (metrics, live stats, attack runs, intel scores / models); nothing is fabricated.
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AccountStatus, AttackRun, IntelScores, LiveStats, ModelInfo } from "../api/types";
import { CH, ChartCanvas, baseOptions } from "./charts";
import { RoleIcon } from "./intel";
import { LastAttackResult } from "./live/AttackResults";
import { useConsoleEvents, usePlatform } from "./Shell";
import { formatINR, formatPaiseShort, handle } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";
import { msLabel } from "../lib/live";
import { ACCOUNT_STATUS_LABEL, ROLE_LABEL } from "../lib/status";

// ── KPI strip ─────────────────────────────────────────────────────────────
export function KpiStrip({ stats, runs }: { stats: LiveStats | null; runs: AttackRun[] | null }) {
  const { metrics: m, system, intelAvailable } = usePlatform();
  const models = useLoad<ModelInfo[]>(api.intelModels);
  const last = (runs ?? []).find((r) => r.status === "completed") ?? null;
  const active = (models.data ?? []).filter((x) => x.status === "active");
  const item = (k: string, v: React.ReactNode, d: React.ReactNode, tone?: "bad" | "ok" | "warn") => (
    <div className={`kpi ${tone ?? ""}`}><div className="k">{k}</div><div className="v">{v}</div><div className="d">{d}</div></div>
  );
  const balanced = m ? m.system_total_paise === 0 : null;
  return (
    <div className="kpi-strip">
      {item("Payments assessed", m ? m.decisions_total.toLocaleString("en-IN") : "—",
        m?.latency_p95_ms != null ? `pre-commit · p95 ${m.latency_p95_ms.toFixed(1)} ms` : "pre-commit decisions")}
      {item("Postings · 10 min", m ? m.transactions_last_10m.toLocaleString("en-IN") : "—",
        stats ? `${stats.throughput_tps.toFixed(2)} tx/s · ${m?.transactions_total.toLocaleString("en-IN") ?? "—"} in ledger` : "live")}
      {item("Open interventions", m ? String(m.open_interventions) : "—", m ? `${formatPaiseShort(m.held_paise)} held in scoped holds` : "", m && m.open_interventions ? "warn" : undefined)}
      {item("Detection (last run)", last && last.precision != null ? `${(last.precision * 100).toFixed(0)}% · ${((last.recall ?? 0) * 100).toFixed(0)}%` : "—",
        last ? `precision · recall · ${last.name} · ${msLabel(last.detection_ms)}` : "no pattern injected yet")}
      {item("Models active", models.data ? `${active.length} / ${models.data.length}` : intelAvailable === false ? "off" : "—",
        models.data ? active.map((x) => x.family.replace("_", " ")).join(" · ") : "RF · GNN · rules · drift · pattern memory", intelAvailable === false ? "bad" : undefined)}
      {item("Ledger integrity", balanced === null ? "—" : balanced ? "Balanced" : formatINR(m!.system_total_paise),
        m ? `traced (LIBR) ${formatPaiseShort(m.attributable_paise)} · ${system?.payment_provider === "razorpay_test" ? "Razorpay TEST" : "mock provider"}` : "",
        balanced === false ? "bad" : balanced ? "ok" : undefined)}
    </div>
  );
}

// ── detection performance (mule detection analytics) ──────────────────────
export function DetectionPerformance({ stats, runs, runsUnavailable }: { stats: LiveStats | null; runs: AttackRun[] | null; runsUnavailable: boolean }) {
  const done = (runs ?? []).filter((r) => r.status === "completed").slice(0, 12).reverse();
  const byType = stats?.runs_by_type ?? [];
  const roles = Object.entries(stats?.roles_flagged ?? {}).filter(([, n]) => n > 0);
  const channels = Object.entries(stats?.channels ?? {}).filter(([, n]) => n > 0);
  const thr = stats?.threshold_history ?? [];
  const noRuns = runsUnavailable ? "Attack-run evaluation not available." : "No pattern injected since the last reset — Test inputs → Inject.";
  const ax = { x: { grid: { display: false }, border: { display: false }, ticks: { color: "#8a939e", maxRotation: 0, autoSkip: true } },
               y: { beginAtZero: true, grid: { color: "rgba(15,20,25,0.06)" }, border: { display: false }, ticks: { color: "#8a939e" } } };
  return (
    <>
      <div className="oc-grid3" style={{ marginTop: 0 }}>
        <LastAttackResult runs={runs} unavailable={runsUnavailable} emptyText={noRuns} />
        <div className="kcard">
          <div className="kcard-h"><span>Runs by pattern</span><span className="act"><span className="sim gt">simulator ground truth</span></span></div>
          <div className="ksub">How many injected patterns were detected (≥ 1 injected account flagged)</div>
          <ChartCanvas type="bar" height={230} empty={noRuns}
            data={{ labels: byType.map((r) => r.name), datasets: [
              { label: "Runs", data: byType.map((r) => r.runs), backgroundColor: "rgba(107,122,143,0.35)", borderRadius: 6, maxBarThickness: 22 },
              { label: "Detected", data: byType.map((r) => r.detected_runs), backgroundColor: CH.mint, borderRadius: 6, maxBarThickness: 22 },
            ] }} options={baseOptions({ scales: ax, plugins: { legend: { position: "bottom" } } }) as never} />
        </div>
        <div className="kcard">
          <div className="kcard-h"><span>Latency & recall per run</span></div>
          <div className="ksub">Time from first injected posting to detection; recall of injected mule accounts</div>
          <ChartCanvas type="bar" height={230} empty={noRuns}
            data={{ labels: done.map((r) => r.run_id.replace("RUN-", "#")), datasets: [
              { type: "bar", label: "Detection (s)", data: done.map((r) => (r.detection_ms ?? 0) / 1000), backgroundColor: CH.blue, borderRadius: 6, maxBarThickness: 18, yAxisID: "y" },
              { type: "line", label: "Recall", data: done.map((r) => r.recall ?? 0), borderColor: CH.red, backgroundColor: CH.red, tension: 0.3, pointRadius: 3, yAxisID: "y1" },
            ] as never }} options={baseOptions({ plugins: { legend: { position: "bottom" } },
              scales: { ...ax, y1: { position: "right", min: 0, max: 1, grid: { display: false }, border: { display: false }, ticks: { color: "#8a939e" } } } }) as never} />
        </div>
      </div>
      <div className="oc-grid3">
        <div className="kcard">
          <div className="kcard-h"><span>Adaptive model threshold</span></div>
          <div className="ksub">The live "flagged" gate adapts after each evaluated run — bounded, logged, never changes payment tiers</div>
          <ChartCanvas type="line" height={210} empty="No threshold change yet."
            data={{ labels: thr.map((p) => new Date(p.t).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false })),
                    datasets: [{ label: "Threshold", data: thr.map((p) => p.value), borderColor: CH.violet, backgroundColor: "rgba(122,107,224,0.12)", fill: true, stepped: true, pointRadius: 3 }] }}
            options={baseOptions({ plugins: { legend: { display: false } }, scales: { ...ax, y: { ...ax.y, beginAtZero: false, suggestedMin: 0.4, suggestedMax: 0.9 } } }) as never} />
          {thr.length > 0 && <div className="ksub" title={thr[thr.length - 1].reason}>Latest: {thr[thr.length - 1].reason}</div>}
        </div>
        <div className="kcard">
          <div className="kcard-h"><span>Mule roles in flagged structure</span></div>
          <div className="ksub">Roles are only assigned inside corroborated mule structure</div>
          {roles.length === 0 ? <div className="empty">No account is flagged with a role.</div> : (
            <div className="stack tight" style={{ gap: 8, marginTop: 6 }}>
              {roles.sort((a, b) => b[1] - a[1]).map(([r, n]) => (
                <div key={r} className="barrow" style={{ gridTemplateColumns: "minmax(110px, 150px) 1fr 40px" }}>
                  <span className="lbl"><RoleIcon role={r} size={13} /> {ROLE_LABEL[r] ?? r}</span>
                  <span className="bar thick"><i style={{ width: `${(n / Math.max(1, ...roles.map(([, k]) => k))) * 100}%`, background: CH.mint }} /></span>
                  <span className="val">{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="kcard">
          <div className="kcard-h"><span>Channel mix</span></div>
          <div className="ksub">Postings by rail in the live window — cross-channel bursts show up here</div>
          <ChartCanvas type="doughnut" height={210} empty="No postings counted yet."
            data={{ labels: channels.map(([c]) => c.toUpperCase()), datasets: [{ data: channels.map(([, n]) => n),
              backgroundColor: [CH.mint, CH.blue, CH.violet, CH.amber, CH.orange, CH.slate], borderWidth: 0 }] }}
            options={{ responsive: true, maintainAspectRatio: false, animation: false, cutout: "68%",
              plugins: { legend: { position: "right", labels: { color: "#3c4652", usePointStyle: true, boxWidth: 8 } } } } as never} />
        </div>
      </div>
    </>
  );
}

// ── account scoring (rules · RF · GNN · drift · early warning · role · live status) ─
type Row = { id: string; rules: number | null; rf: number | null; gnn: number | null; drift_level: string; role: string | null; early_warning: boolean };
type Sort = "max" | "rules" | "rf" | "gnn";
type Filter = "risk" | "all" | "ew" | "disagree";

function Score({ v, kind }: { v: number | null; kind: "rules" | "model" }) {
  if (v === null || v === undefined) return <span className="dim">—</span>;
  const tone = v >= 0.75 ? "var(--st-critical)" : v >= 0.5 ? "var(--st-high)" : v >= 0.3 ? "var(--st-watch)" : "var(--ink-4)";
  return (
    <span className="score-cell" title={kind === "rules" ? "rule points ÷ max (a score, not a probability)" : "model probability (SYNTHETIC VALIDATION)"}>
      <span className="bar"><i style={{ width: `${Math.max(2, v * 100)}%`, background: tone }} /></span>
      <span className="mono" style={{ color: v >= 0.3 ? "var(--ink)" : "var(--ink-4)" }}>{v.toFixed(2)}</span>
    </span>
  );
}

export function AccountScoring({ statusOf }: { statusOf: (id: string) => AccountStatus | null }) {
  const nav = useNavigate();
  const scores = useLoad<IntelScores>(api.intelScores);
  const refresh = useDebounced(() => scores.reload(), 3000);
  useConsoleEvents((e) => { if (e.type === "intel.updated" || e.type === "demo.reset" || e.type === "attack.run_updated" || e.type === "intel.account_status") refresh(); });
  const [sort, setSort] = useState<Sort>("max");
  const [filter, setFilter] = useState<Filter>("risk");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(15);
  const rows: Row[] = useMemo(() => Object.entries(scores.data?.scores ?? {}).map(([id, s]) => ({ id, ...(s as Omit<Row, "id">) })), [scores.data]);
  const mx = (r: Row) => Math.max(r.rules ?? 0, r.rf ?? 0, r.gnn ?? 0);
  const list = useMemo(() => {
    let xs = rows;
    if (q.trim()) xs = xs.filter((r) => r.id.includes(q.trim().toLowerCase()));
    if (filter === "risk") xs = xs.filter((r) => mx(r) >= 0.3 || r.early_warning || r.drift_level === "HIGH" || !!r.role);
    if (filter === "ew") xs = xs.filter((r) => r.early_warning || r.drift_level === "HIGH");
    if (filter === "disagree") xs = xs.filter((r) => Math.abs((r.rules ?? 0) - Math.max(r.rf ?? 0, r.gnn ?? 0)) >= 0.4);
    const key = (r: Row) => (sort === "max" ? mx(r) : (r[sort] ?? -1));
    return [...xs].sort((a, b) => key(b) - key(a));
  }, [rows, q, filter, sort]);
  const counts = useMemo(() => ({
    risk: rows.filter((r) => mx(r) >= 0.3 || r.early_warning || r.drift_level === "HIGH" || !!r.role).length,
    ew: rows.filter((r) => r.early_warning || r.drift_level === "HIGH").length,
    disagree: rows.filter((r) => Math.abs((r.rules ?? 0) - Math.max(r.rf ?? 0, r.gnn ?? 0)) >= 0.4).length,
  }), [rows]);
  const th = (k: Sort, label: string) => (
    <th className={`num sortable ${sort === k ? "on" : ""}`} onClick={() => setSort(k)} title={`Sort by ${label}`}>{label}{sort === k ? " ↓" : ""}</th>
  );
  return (
    <div className="kcard" style={{ paddingBottom: 12 }}>
      <div className="kcard-h">
        <span>Account scoring</span>
        <span className="act">
          <span className="stamp-sv">Synthetic validation</span>
        </span>
      </div>
      <div className="row wrap" style={{ gap: 10, margin: "4px 0 6px" }}>
        <div className="seg">
          <button className={filter === "risk" ? "on" : ""} onClick={() => { setFilter("risk"); setShown(15); }}>Elevated · {counts.risk}</button>
          <button className={filter === "ew" ? "on" : ""} onClick={() => { setFilter("ew"); setShown(15); }}>Behaviour change · {counts.ew}</button>
          <button className={filter === "disagree" ? "on" : ""} onClick={() => { setFilter("disagree"); setShown(15); }}>Rules vs models disagree · {counts.disagree}</button>
          <button className={filter === "all" ? "on" : ""} onClick={() => { setFilter("all"); setShown(15); }}>All · {rows.length}</button>
        </div>
        <span className="grow" />
        <input className="input" style={{ width: 240, height: 34, borderRadius: 999 }} placeholder="Filter by account id" value={q} onChange={(e) => { setQ(e.target.value); setShown(15); }} />
      </div>
      <div className="ksub">Transparent rule points beside the corroborating models — rules decide payments, models corroborate. Click a column to sort; click a row to investigate.</div>
      {!scores.data ? <div className="empty">{scores.unavailable ? "Per-account detector scores are not available." : "Loading scores…"}</div> : list.length === 0 ? <div className="empty">No account matches this filter.</div> : (
        <>
          <table className="dt" style={{ marginTop: 8 }}>
            <thead><tr>
              <th>Account</th><th>Live status</th>
              {th("max", "Strongest")}{th("rules", "Rules")}{th("rf", "Random Forest")}{th("gnn", "GNN")}
              <th>Drift</th><th>Early warning</th><th>Role</th>
            </tr></thead>
            <tbody>
              {list.slice(0, shown).map((r) => {
                const st = statusOf(r.id);
                return (
                  <tr key={r.id} className="click" onClick={() => nav(`/investigations/account/${encodeURIComponent(r.id)}`)}>
                    <td><span className="cell-2l"><b>{handle(r.id)}</b><small>{r.id}</small></span></td>
                    <td>{st ? <span className={`pill as-${st}`}>{ACCOUNT_STATUS_LABEL[st]}</span> : <span className="dim">—</span>}</td>
                    <td className="num"><Score v={mx(r)} kind="model" /></td>
                    <td className="num"><Score v={r.rules} kind="rules" /></td>
                    <td className="num"><Score v={r.rf} kind="model" /></td>
                    <td className="num"><Score v={r.gnn} kind="model" /></td>
                    <td><span className={`pill nodot ${r.drift_level === "HIGH" ? "s-high" : r.drift_level === "MEDIUM" ? "s-watch" : "s-normal"}`}>{r.drift_level.toLowerCase()}</span></td>
                    <td>{r.early_warning ? <span className="pill as-early_warning">warning</span> : <span className="dim">—</span>}</td>
                    <td className="sm">{r.role ? <span className="row tight"><RoleIcon role={r.role} size={12} />{ROLE_LABEL[r.role] ?? r.role}</span> : <span className="dim">—</span>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="row" style={{ justifyContent: "space-between", marginTop: 10 }}>
            <span className="ksub">Showing {Math.min(shown, list.length)} of {list.length} · {rows.length} accounts scored · graph v{scores.data.graph_version}</span>
            <span className="row tight">
              {shown < list.length && <button className="btn sm" onClick={() => setShown(shown + 25)}>Show 25 more</button>}
              {shown < list.length && <button className="btn sm ghost" onClick={() => setShown(list.length)}>Show all</button>}
              <Link className="btn sm ghost" to="/detection">Detection & models</Link>
            </span>
          </div>
        </>
      )}
    </div>
  );
}
