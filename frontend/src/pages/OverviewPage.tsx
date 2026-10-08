// LIVE OPERATIONS (Overview) — the refined reference's single-page operations view, Vigil-branded:
// hero status → KPIs → PRIMA strip → live transaction universe → command center + attack subgraph → live streams →
// rule / model score tables → last attack result + PRIMA attention → attack history → live statistics.
// Push-only: one console WebSocket (Shell) fans out; the 3D canvas is imperative; lists flush ≤ 2/s, charts ≤ 1/s.
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { AccountStatus, DetectorFamily, IntelOverview, ScenarioStatus, UniverseAccount } from "../api/types";
import { RoleIcon } from "../components/intel";
import { AttackHistory, LastAttackResult } from "../components/live/AttackResults";
import { AttackSubgraph } from "../components/live/AttackSubgraph";
import { CommandCenter, catOf } from "../components/live/CommandCenter";
import { LiveStatsCharts } from "../components/live/LiveStatsCharts";
import { LiveStreams } from "../components/live/LiveStreams";
import { ScoreTables } from "../components/live/ScoreTables";
import { LiveUniverse3D, UniverseLegend, type UStats, type UniverseInfo } from "../components/LiveUniverse3D";
import { useConsoleEvents, usePlatform } from "../components/Shell";
import { Bar, Glyph, Panel, Sim, StatePill, TierPill } from "../components/ui";
import { UniverseDrawer } from "../components/UniverseDrawer";
import { duration, formatINR, formatPaiseShort, handle } from "../lib/format";
import { useDebounced, useLoad, useNow } from "../lib/hooks";
import { useAttackRuns, useLiveStats, useThrottled } from "../lib/live";
import { rowAge, useInterventionQueue } from "../lib/queue";
import { FAMILY, ROLE_LABEL, tierStatus } from "../lib/status";

type Sub<T> = { set: ((v: T) => void) | null };

function Header() {
  const { conn, health } = usePlatform();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ambient = health?.ambient ?? null;
  const run = async (what: "ambient" | "reset") => {
    if (what === "reset" && !window.confirm("Reset the demo world? Every posting, decision and attack run since seeding is discarded and the world is re-seeded.")) return;
    setBusy(what); setErr(null);
    try { if (what === "ambient") await api.ambient(!ambient); else await api.reset(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  return (
    <header className="page-head compact">
      <div>
        <div className="crumb">Operate</div>
        <h1>Live operations</h1>
        <div className="lede">Every payment intent is assessed before money moves; every posting is scored against the whole network.
          All figures on this page come from the Vigil ledger and are pushed as they change.</div>
      </div>
      <div className="page-actions">
        {err && <span className="notice err sm">{err}</span>}
        <span className="chip live" title="Realtime push channel">
          <span className={`dot ${conn === "open" ? "ok pulse" : conn === "connecting" ? "warn" : "bad"}`} />{conn === "open" ? "Live" : conn}
        </span>
        <button className="btn" disabled={ambient === null || !!busy} onClick={() => run("ambient")} title="Background (ambient) payment stream">
          {busy === "ambient" ? "…" : ambient ? "Pause traffic" : "Resume traffic"}</button>
        <button className="btn ghost" disabled={!!busy} onClick={() => run("reset")}>{busy === "reset" ? "Resetting…" : "Reset demo"}</button>
      </div>
    </header>
  );
}

/** KPI grid — re-renders once per second from the universe engine and pushed events, never the whole page. */
const KpiGrid = memo(function KpiGrid({ statsSub, liveCounts, tps }: {
  statsSub: Sub<UStats>; liveCounts: Record<string, number> | null; tps: number | null;
}) {
  const { metrics: m } = usePlatform();
  const [u, setU] = useState<UStats | null>(null);
  useEffect(() => { statsSub.set = setU; return () => { statsSub.set = null; }; }, [statsSub]);
  // client-measured throughput (postings received over the last 10 s) while /api/live/stats is not served
  const stamps = useRef<number[]>([]);
  const [localTps, setLocalTps] = useState<number | null>(null);
  const flush = useThrottled(() => {
    const cut = Date.now() - 10_000;
    stamps.current = stamps.current.filter((t) => t >= cut);
    setLocalTps(stamps.current.length / 10);
  }, 1000);
  useConsoleEvents((e) => { if (e.type === "ledger.posted") { stamps.current.push(Date.now()); flush(); } });
  useEffect(() => { const i = window.setInterval(flush, 2000); return () => window.clearInterval(i); }, [flush]);

  const c = liveCounts ?? {};
  // once the universe has loaded, a status with no accounts is 0, not unknown
  const by = new Proxy((u?.byStatus ?? {}) as Record<string, number | undefined>, { get: (t, k: string) => t[k] ?? (u ? 0 : undefined) });
  const n = (k: string, fb: number | undefined) => (c[k] ?? fb);
  const tile = (k: string, v: React.ReactNode, d: React.ReactNode, cls = "") => (
    <div className={`m ${cls}`}><div className="k">{k}</div><div className="v">{v}</div><div className="d">{d}</div></div>
  );
  const val = (x: number | undefined | null) => (x === undefined || x === null ? "—" : x.toLocaleString("en-IN"));
  const rate = tps ?? localTps;
  const warn = n("warnings", by.early_warning) ?? 0, flagged = n("flagged", by.flagged) ?? 0, held = n("held", by.held) ?? 0;
  return (
    <div className="mstrip kpi-grid">
      {tile("Postings · 10 min", val(m?.transactions_last_10m), m ? `${val(n("transactions", m.transactions_total))} in the ledger` : "")}
      {tile("Throughput", rate === null ? "—" : `${rate.toFixed(2)} tx/s`, tps !== null ? "measured by the server" : "received here, last 10 s")}
      {tile("Active accounts", val(n("active", u?.active)), `of ${val(n("accounts", u?.nodes))} · live window`)}
      {tile("Early warnings", val(warn), "behaviour or network", warn > 0 ? "st-watch" : "")}
      {tile("Flagged", val(flagged), "agreement above weak", flagged > 0 ? "st-critical" : "")}
      {tile("Held / confirmed", <>{val(held)}<span className="muted"> / {val(n("confirmed", by.confirmed_fraud))}</span></>,
        m ? `${formatPaiseShort(m.held_paise)} held in scoped holds` : "", held > 0 ? "st-held" : "")}
      {tile("Open interventions", val(m?.open_interventions), m ? `of ${val(m.decisions_total)} decisions` : "", (m?.open_interventions ?? 0) > 0 ? "st-high" : "")}
      {tile("Decision latency", m?.latency_p95_ms != null ? `${m.latency_p95_ms.toFixed(1)} ms` : "—", m?.latency_p50_ms != null ? `p95 · p50 ${m.latency_p50_ms.toFixed(1)} ms` : "pre-commit assessment")}
    </div>
  );
});

/** Tier mix of every pre-commit decision, with exact counts (no rounding that hides an intervention). */
function TierMix() {
  const { metrics: m, mode } = usePlatform();
  const tiers = m?.decisions_by_tier ?? {};
  const total = Object.values(tiers).reduce((a, b) => a + b, 0);
  const passed = tiers["0"] ?? 0;
  return (
    <div className="sect">
      <div className="spread xs muted" style={{ marginBottom: 6 }}>
        <span>Tier mix · {total.toLocaleString("en-IN")} decisions · {mode?.mode === "shadow" ? "shadow" : "active"} mode</span>
        <span>{total ? `${passed.toLocaleString("en-IN")} of ${total.toLocaleString("en-IN")} passed without friction` : "no decisions yet"}</span>
      </div>
      <div className="dist">{Object.entries(tiers).map(([t, k]) => k > 0 && <span key={t} title={`Tier ${t}: ${k}`} style={{ width: `${(k / Math.max(1, total)) * 100}%`, background: `var(--st-${tierStatus(Number(t))})` }} />)}</div>
      <div className="legend xs" style={{ marginTop: 6 }}>
        {Object.entries(tiers).map(([t, k]) => <span key={t}><i className="sw" style={{ background: `var(--st-${tierStatus(Number(t))})` }} />T{t} {k.toLocaleString("en-IN")}</span>)}
      </div>
    </div>
  );
}

function AttentionPanel() {
  const nav = useNavigate();
  const { metrics: m } = usePlatform();
  const now = useNow(10000);
  const q = useInterventionQueue("open");
  const refresh = useDebounced(() => q.rows.reload(), 1200);
  useConsoleEvents((e) => {
    if ((e.type === "decision.created" && (e.data as { tier?: number })?.tier! >= 2) || e.type === "intent.updated" || e.type.startsWith("breaker.") || e.type === "demo.reset") refresh();
  });
  const attention = q.all.filter((r) => r.tier >= 2);
  return (
    <Panel title="Needs attention" q="open interventions · tier ≥ 2" flush actions={<Link className="btn xs ghost" to="/interventions">Queue →</Link>}
           footer={m ? <>Ledger {m.system_total_paise === 0 ? <span style={{ color: "var(--ok)" }}>balanced (system total ₹0)</span> : <span style={{ color: "var(--st-critical)" }}>imbalance {formatINR(m.system_total_paise)}</span>} · inflow to suspicious accounts (72 h) {formatINR(m.suspicious_value_paise)} · traced (LIBR) {formatINR(m.attributable_paise)}</> : undefined}>
      <TierMix />
      {attention.length === 0 ? <div className="empty" style={{ borderTop: "1px solid var(--line)" }}>Nothing needs attention. Holds and purpose confirmations appear here the moment they are decided.</div> : (
        <table className="dt compact">
          <tbody>
            {attention.slice(0, 8).map((r) => (
              <tr key={r.decision_id} className="click" onClick={() => nav(`/investigations/decision/${r.decision_id}`)}>
                <td style={{ width: 52 }}><TierPill tier={r.tier} /></td>
                <td className="xs fill"><div className="ell"><b>{handle(r.sender_id)}</b> → {handle(r.recipient_id)}</div><div className="dim ell">{r.headline}</div></td>
                <td className="num">{formatINR(r.amount_paise)}<div className="xs dim">{duration(rowAge(r, now, q.fetchedAt))}</div></td>
                <td><StatePill state={r.state} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function AgreementPanel() {
  const intel = useLoad<IntelOverview>(api.intelOverview);
  useConsoleEvents((e) => { if (e.type === "intel.updated" || e.type === "demo.reset") intel.reload(); });
  const d = intel.data;
  return (
    <Panel title="Detector agreement" q="accounts flagged per family">
      {!d ? <div className="xs muted">{intel.unavailable ? "Detection intelligence (/api/intel/overview) not served." : intel.loading ? "Loading…" : intel.error?.message}</div> : (
        <>
          {Object.entries(d.detector_agreement).sort((a, b) => b[1] - a[1]).map(([fam, n]) => (
            <div key={fam} className="barrow"><span className="lbl"><Glyph family={fam as DetectorFamily} /> {FAMILY[fam as DetectorFamily]?.label ?? fam}</span>
              <Bar value={n} max={Math.max(1, ...Object.values(d.detector_agreement))} status="watch" /><span className="val">{n}</span></div>
          ))}
          {Object.keys(d.role_counts).length > 0 && (
            <div className="row wrap tight" style={{ marginTop: 10 }}>
              {Object.entries(d.role_counts).map(([r, n]) => <span key={r} className="tag"><RoleIcon role={r} size={11} />&nbsp;{ROLE_LABEL[r] ?? r} {n}</span>)}
            </div>
          )}
          <div className="row wrap tight xs muted" style={{ marginTop: 10 }}><span className="stamp-sv">Synthetic validation</span><span>Model families are corroborating evidence, not used for authorisation.</span></div>
        </>
      )}
    </Panel>
  );
}

export function OverviewPage() {
  const runs = useAttackRuns();
  const stats = useLiveStats(5000);
  const { metrics } = usePlatform();
  const scen = useLoad<ScenarioStatus[]>(api.scenarios);
  const refreshScen = useDebounced(() => scen.reload(), 400);
  useConsoleEvents((e) => { if (e.type.startsWith("scenario.") || e.type === "demo.reset") refreshScen(); });

  const [scenarioId, setScenarioId] = useState<string | null>(null);
  useEffect(() => {
    if (scenarioId || !scen.data) return;
    const running = scen.data.find((s) => s.state === "running" && catOf(s) === "attack");
    const first = running ?? scen.data.find((s) => catOf(s) === "attack") ?? scen.data[0];
    if (first) setScenarioId(first.id);
  }, [scen.data, scenarioId]);
  const scenario = (scen.data ?? []).find((s) => s.id === scenarioId) ?? null;
  const attackScenario = scenario && catOf(scenario) === "attack" ? scenario
    : (scen.data ?? []).find((s) => s.id === runs.data?.[0]?.scenario_id) ?? null;
  const attackLive = (scen.data ?? []).some((s) => s.state === "running" && catOf(s) === "attack")
    || (runs.data ?? []).some((r) => r.status === "running");

  // universe state shared with tables (status lookup) — a ref, so live status changes never re-render the page
  const accounts = useRef(new Map<string, UniverseAccount>());
  const [uniVersion, setUniVersion] = useState(0);
  const [recent, setRecent] = useState<UniverseInfo["recent"] | null>(null);
  const onInfo = useCallback((i: UniverseInfo) => { accounts.current = i.accounts; setRecent((r) => r ?? i.recent); setUniVersion((n) => n + 1); }, []);
  const statusOf = useCallback((id: string): AccountStatus | null => accounts.current.get(id)?.status ?? null, []);
  const statsSub = useMemo<Sub<UStats>>(() => ({ set: null }), []);
  const onStats = useCallback((s: UStats) => statsSub.set?.(s), [statsSub]);
  const [sel, setSel] = useState<{ id: string; acct: UniverseAccount | null } | null>(null);
  const [orbit, setOrbit] = useState(true);
  const [gt, setGt] = useState(false);
  const [focus, setFocus] = useState<{ ids: string[]; seq: number } | null>(null);
  const onSelect = useCallback((id: string | null, acct: UniverseAccount | null) => setSel(id ? { id, acct } : null), []);


  return (
    <>
      <Header />
      <KpiGrid statsSub={statsSub} liveCounts={stats.data?.counts ?? null} tps={stats.data?.throughput_tps ?? null} />

      <div className="ov-top">
        <section className={`stage ${attackLive ? "attack-flash" : ""}`}>
          <div className="stage-h">
            <div>
              <div className="t">Live transaction network</div>
              <UniverseLegend groundTruth={gt} />
            </div>
            <div className="row wrap" style={{ justifyContent: "flex-end", gap: 6 }}>
              <button className={`btn xs ${orbit ? "on" : ""}`} onClick={() => setOrbit(!orbit)}>Auto-orbit</button>
              <button className={`btn xs ${gt ? "on" : ""}`} onClick={() => setGt(!gt)} title="Colour postings tagged by the simulator (evaluation only — never scored)">Ground truth</button>
              <button className="btn xs" onClick={() => setFocus({ ids: [...accounts.current.keys()], seq: Date.now() })}>Reset view</button>
              <Link className="btn xs" to="/network">Open full view</Link>
            </div>
          </div>
          <div style={{ position: "relative" }}>
            <LiveUniverse3D mode="live" groundTruth={gt} autoRotate={orbit && !sel} size="hero" selected={sel?.id ?? null}
                            onSelect={onSelect} onInfo={onInfo} onStats={onStats} focus={focus} />
            {sel && <UniverseDrawer id={sel.id} acct={accounts.current.get(sel.id) ?? sel.acct} onClose={() => setSel(null)}
                                    onFocus={() => setFocus({ ids: [sel.id], seq: Date.now() })} />}
          </div>
          <div className="xs" style={{ padding: "8px 14px", borderTop: "1px solid #1c222b", color: "#7d8796", background: "#0e1217" }}>
            Each account sits at a fixed position; each new posting draws an edge with a travelling marker and fades after the live window.
            Colour is the account's live status; a violet ring marks a scoped hold, crimson a confirmed scam recipient. Click a node to investigate.
          </div>
        </section>
        <div className="ov-side">
          <AttentionPanel />
          <AgreementPanel />
        </div>
      </div>

      <div className="grid cols-2 align-start section-gap">
        <CommandCenter scenarios={scen.data} runs={runs.data} runsUnavailable={runs.unavailable} selected={scenarioId}
                       onSelect={setScenarioId} onChanged={() => { scen.reload(); }} />
        <AttackSubgraph scenario={attackScenario} statusOf={statusOf} />
      </div>

      <div className="grid cols-2 align-start section-gap">
        <LastAttackResult runs={runs.data} unavailable={runs.unavailable} />
        <AttackHistory runs={runs.data} unavailable={runs.unavailable}
                       onPick={(r) => { setScenarioId(r.scenario_id); setFocus({ ids: r.injected, seq: Date.now() }); }} />
      </div>

      <div className="section-gap"><LiveStreams statusOf={statusOf} recent={recent} /></div>
      <div className="section-gap"><ScoreTables key={uniVersion > 0 ? "u" : "n"} statusOf={statusOf} /></div>
      <div className="section-gap">
        <LiveStatsCharts stats={stats.data} statsUnavailable={stats.unavailable} runs={runs.data} metrics={metrics} />
      </div>
      <div className="xs dim section-gap center">
        <Sim /> external intelligence and scenario inputs are simulated · model metrics are <span className="stamp-sv">SYNTHETIC VALIDATION</span> ·
        anything derived from scenario tags is simulator ground truth · SHAP explains the model, ReasonLine explains the decision.
      </div>
    </>
  );
}
