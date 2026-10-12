// Analytics blocks: the Overview KPI strip and the full account scoring table (Detection page).
// Every value comes from the backend (metrics, live stats, attack runs, intel scores / models); nothing is fabricated.
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AccountStatus, AttackRun, IntelScores, LiveStats } from "../api/types";
import { RoleIcon } from "./intel";
import { useConsoleEvents, usePlatform } from "./Shell";
import { formatPaiseShort, handle } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";
import { msLabel } from "../lib/live";
import { ACCOUNT_STATUS_LABEL, ROLE_LABEL } from "../lib/status";

// ── KPI strip ─────────────────────────────────────────────────────────────
export function KpiStrip({ stats, runs, by }: { stats: LiveStats | null; runs: AttackRun[] | null; by: Record<string, number> | null }) {
  const { metrics: m } = usePlatform();
  const last = (runs ?? []).find((r) => r.status === "completed") ?? null;
  const n = (k: string) => by?.[k] ?? 0;
  const atRisk = by ? n("flagged") + n("held") + n("confirmed_fraud") : null;
  const tiers = m?.decisions_by_tier ?? {};
  const total = Object.values(tiers).reduce((x, y) => x + y, 0);
  const passed = tiers["0"] ?? 0;
  const item = (k: string, v: React.ReactNode, d: React.ReactNode, tone?: "bad" | "ok" | "warn") => (
    <div className={`kpi ${tone ?? ""}`}><div className="k">{k}</div><div className="v">{v}</div><div className="d">{d}</div></div>
  );
  return (
    <div className="kpi-strip">
      {item("Accounts at risk", atRisk ?? "—", by ? `${n("flagged")} flagged · ${n("held")} held · ${n("early_warning")} early warning` : "loading live statuses…",
        atRisk ? "bad" : atRisk === 0 ? "ok" : undefined)}
      {item("Open interventions", m ? String(m.open_interventions) : "—", m ? `${formatPaiseShort(m.held_paise)} held in scoped holds` : "",
        m && m.open_interventions ? "warn" : undefined)}
      {item("Passed without friction", total ? `${((passed / total) * 100).toFixed(1)}%` : "—",
        total ? `${passed.toLocaleString("en-IN")} of ${total.toLocaleString("en-IN")} payments at Tier 0` : "no payments yet")}
      {item("Decision latency", m?.latency_p95_ms != null ? `${m.latency_p95_ms.toFixed(1)} ms` : "—",
        m ? `p95 pre-commit · ${m.decisions_total.toLocaleString("en-IN")} payments assessed` : "")}
      {item("Last detection run", last && last.recall != null ? `${last.detected.filter((x) => last.injected.includes(x)).length} / ${last.injected.length}` : "—",
        last ? `mules caught · ${last.name} · ${last.false_positives.length} false positive${last.false_positives.length === 1 ? "" : "s"} · ${msLabel(last.detection_ms)}` : "no pattern injected yet",
        last ? (last.missed.length ? "warn" : "ok") : undefined)}
      {item("Postings · 10 min", m ? m.transactions_last_10m.toLocaleString("en-IN") : "—",
        stats ? `${stats.throughput_tps.toFixed(2)} tx/s · ${m?.transactions_total.toLocaleString("en-IN") ?? "—"} in ledger` : "live")}
    </div>
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

export function AccountScoring({ statusOf }: { statusOf?: (id: string) => AccountStatus | null }) {
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
                const st = statusOf?.(r.id) ?? null;
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
            </span>
          </div>
        </>
      )}
    </div>
  );
}
