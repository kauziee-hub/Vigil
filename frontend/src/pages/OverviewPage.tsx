// LIVE OPERATIONS (Overview) — the refined reference's single-page operations view, Vigil-branded:
// hero status → KPIs → PRIMA strip → live transaction universe → command center + attack subgraph → live streams →
// rule / model score tables → last attack result + PRIMA attention → attack history → live statistics.
// Push-only: one console WebSocket (Shell) fans out; the 3D canvas is imperative; lists flush ≤ 2/s, charts ≤ 1/s.
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { AccountStatus, DetectorFamily, IntelOverview, ModelInfo, ScenarioStatus, UniverseAccount } from "../api/types";
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
import { msLabel, useAttackRuns, useLiveStats, useThrottled } from "../lib/live";
import { rowAge, useInterventionQueue } from "../lib/queue";
import { FAMILY, ROLE_LABEL, tierStatus } from "../lib/status";

type Sub<T> = { set: ((v: T) => void) | null };

function Hero() {
  const { conn, system, health, intelAvailable } = usePlatform();
  const models = useLoad<ModelInfo[]>(api.intelModels);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const fam = (f: string) => (models.data ?? []).some((m) => m.family === f && m.status === "active");
  const chip = (label: string, ok: boolean | null, title: string) => (
    <span className={`chip ${ok ? "" : ok === false ? "off" : "mute"}`} title={title}>{label} {ok ? "✓" : ok === false ? "✕" : "…"}</span>
  );
  const ambient = health?.ambient ?? null;
  const run = async (what: "ambient" | "reset") => {
    if (what === "reset" && !window.confirm("Reset the demo world? Every posting, decision and attack run since seeding is discarded and the world is re-seeded.")) return;
    setBusy(what); setErr(null);
    try { if (what === "ambient") await api.ambient(!ambient); else await api.reset(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };
  return (
    <section className="hero">
      <div>
        <div className="eyebrow">PRIMA · pre-commit payment risk + live mule intelligence</div>
        <h1>Vigil Live Operations</h1>
        <p>Every payment intent is assessed before money moves; every posting that does move is scored live against the whole
          network. Transactions, scores, alerts and attack runs on this page are pushed from the Vigil backend and stored in its ledger.</p>
      </div>
      <div className="hero-actions">
        <span className="chip live"><span className={`dot ${conn === "open" ? "ok pulse" : conn === "connecting" ? "warn" : "bad"}`} />{conn === "open" ? "LIVE" : conn.toUpperCase()}</span>
        <div className="hero-chips">
          {chip("RF", models.data ? fam("random_forest") : models.error ? false : null, "Random Forest model (/api/intel/models)")}
          {chip("GNN", models.data ? fam("gnn") : models.error ? false : null, "Graph neural network (/api/intel/models)")}
          {chip("SHAP", intelAvailable, "Per-account SHAP explanations (detection intelligence layer)")}
          {chip("DB", system ? system.db_size_bytes > 0 : health ? true : null, system ? `SQLite ledger · ${(system.db_size_bytes / 1e6).toFixed(1)} MB` : "Ledger database")}
          {system && <span className={`chip ${system.ml_on_decision_path ? "warn" : "mute"}`} title="Model evidence never sets the operational tier">ML on decision path: {system.ml_on_decision_path ? "yes" : "no"}</span>}
        </div>
        <div className="row wrap" style={{ justifyContent: "flex-end" }}>
          <button className="btn lg" disabled={ambient === null || !!busy} onClick={() => run("ambient")} title="Background (ambient) payment stream">
            {busy === "ambient" ? "…" : ambient ? "Pause traffic" : "Resume traffic"}</button>
          <button className="btn lg ghost" disabled={!!busy} onClick={() => run("reset")}>{busy === "reset" ? "Resetting…" : "Reset demo"}</button>
        </div>
        {err && <div className="notice err sm">{err}</div>}
      </div>
    </section>
  );
}

/** KPI grid — re-renders once per second from the universe engine and pushed events, never the whole page. */
const KpiGrid = memo(function KpiGrid({ statsSub, runs, liveCounts, tps }: {
  statsSub: Sub<UStats>; runs: ReturnType<typeof useAttackRuns>; liveCounts: Record<string, number> | null; tps: number | null;
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
  const by = u?.byStatus ?? {};
  const list = runs.data ?? [];
  const done = list.filter((r) => r.status === "completed");
  const running = list.filter((r) => r.status === "running" || r.status === "evaluating").length;
  const detectedRuns = done.filter((r) => r.detected.length > 0).length;
  const avg = (xs: (number | null)[]) => { const v = xs.filter((x): x is number => x !== null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const last = done[0] ?? null;
  const tiers = m?.decisions_by_tier ?? {};
  const alerts = Object.entries(tiers).filter(([t]) => Number(t) >= 1).reduce((a, [, n]) => a + n, 0);
  const n = (k: string, fb: number | undefined) => (c[k] ?? fb);
  const tile = (k: string, v: React.ReactNode, d: React.ReactNode, cls = "") => (
    <div className={`m ${cls}`}><div className="k">{k}</div><div className="v">{v}</div><div className="d">{d}</div></div>
  );
  const val = (x: number | undefined | null) => (x === undefined || x === null ? "—" : x.toLocaleString("en-IN"));
  const rate = tps ?? localTps;
  return (
    <div className="mstrip kpi-grid">
      {tile("Transactions stored", val(n("transactions", m?.transactions_total)), m ? `${m.transactions_last_10m} in the last 10 min` : "")}
      {tile("Throughput", rate === null ? "—" : rate.toFixed(2), tps !== null ? "tx/s · server" : "tx/s · received here, last 10 s")}
      {tile("Active accounts", val(n("active", u?.active)), `${val(n("accounts", u?.nodes))} accounts · live window`)}
      {tile("Early warnings", val(n("warnings", by.early_warning)), "behaviour or network signals", (n("warnings", by.early_warning) ?? 0) > 0 ? "st-watch" : "")}
      {tile("Flagged", val(n("flagged", by.flagged)), "detector consensus above weak", (n("flagged", by.flagged) ?? 0) > 0 ? "st-critical" : "")}
      {tile("Held / confirmed", <>{val(n("held", by.held))}<span className="muted" style={{ fontSize: 18 }}> / {val(n("confirmed", by.confirmed_fraud))}</span></>,
        m ? `${formatPaiseShort(m.held_paise)} held · ${m.open_interventions} open interventions` : "", (n("held", by.held) ?? 0) > 0 ? "st-held" : "")}
      {tile("PRIMA alerts", val(alerts), `tier ≥ 1 of ${val(m?.decisions_total)} decisions`)}
      {tile("Attacks spawned", runs.unavailable ? "—" : val(list.length), runs.unavailable ? "/api/attacks/runs not served" : `${running} running · ${done.length} evaluated`)}
      {tile("Attacks detected", runs.unavailable ? "—" : val(detectedRuns), done.length ? `${detectedRuns} of ${done.length} runs` : "no evaluated runs yet")}
      {tile("Detection latency", msLabel(avg(done.map((r) => r.detection_ms))), `first warning avg ${msLabel(avg(done.map((r) => r.first_warning_ms)))}`)}
      {tile("Precision / recall", last && last.precision != null ? `${last.precision.toFixed(2)} / ${last.recall?.toFixed(2) ?? "—"}` : "—", last ? `last run ${last.run_id} · simulator ground truth` : "no evaluated run yet")}
      {tile("Decision latency", m?.latency_p95_ms != null ? `${m.latency_p95_ms.toFixed(1)} ms` : "—", m?.latency_p50_ms != null ? `p95 · p50 ${m.latency_p50_ms.toFixed(1)} ms` : "PRIMA pre-commit assessment")}
    </div>
  );
});

function PrimaStrip() {
  const { metrics: m, mode } = usePlatform();
  const tiers = m?.decisions_by_tier ?? {};
  const total = Object.values(tiers).reduce((a, b) => a + b, 0);
  return (
    <div className="prima-strip">
      <div><div className="eyebrow">PRIMA layer</div><div className="b" style={{ fontSize: 17 }}>Pre-commit interventions</div></div>
      <div className="m"><div className="k">Open interventions</div><div className="v" style={{ color: m?.open_interventions ? "var(--st-high)" : undefined }}>{m?.open_interventions ?? "—"}</div></div>
      <div className="m"><div className="k">Held value (scoped)</div><div className="v" style={{ color: m?.held_paise ? "var(--st-held)" : undefined }}>{m ? formatINR(m.held_paise) : "—"}</div></div>
      <div className="m"><div className="k">Zero-friction</div><div className="v">{m?.zero_friction_rate != null ? `${Math.round(m.zero_friction_rate * 100)}%` : "—"}</div></div>
      <div className="m">
        <div className="k">Tier mix · {total.toLocaleString("en-IN")} decisions · {mode?.mode === "shadow" ? "SHADOW" : "ACTIVE"}</div>
        <div className="dist" style={{ marginTop: 8 }}>{Object.entries(tiers).map(([t, n]) => n > 0 && <span key={t} title={`T${t}: ${n}`} style={{ width: `${(n / Math.max(1, total)) * 100}%`, background: `var(--st-${tierStatus(Number(t))})` }} />)}</div>
      </div>
      <Link className="btn sm" to="/interventions">Interventions →</Link>
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
    <Panel kicker="PRIMA · needs attention" title="Open interventions · tier ≥ 2" flush actions={<Link className="btn xs ghost" to="/interventions">Queue →</Link>}
           footer={m ? <>Ledger {m.system_total_paise === 0 ? <span style={{ color: "var(--accent)" }}>balanced · system total ₹0</span> : <span style={{ color: "var(--st-critical)" }}>imbalance {formatINR(m.system_total_paise)}</span>} · inflow to suspicious accounts (72 h) {formatINR(m.suspicious_value_paise)} · traced (LIBR) {formatINR(m.attributable_paise)}</> : undefined}>
      {attention.length === 0 ? <div className="empty">Nothing needs attention. Holds and purpose confirmations appear here the moment they are decided.</div> : (
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
    <Panel kicker="Detector agreement" title="What each detector family sees" q="accounts flagged per family">
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
          <div className="xs muted" style={{ marginTop: 10 }}>Model families are corroborating evidence (<span className="stamp-sv">SYNTHETIC VALIDATION</span>) — not used for authorisation.</div>
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
  const onInfo = useCallback((i: UniverseInfo) => { accounts.current = i.accounts; setUniVersion((n) => n + 1); }, []);
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
      <Hero />
      <KpiGrid statsSub={statsSub} runs={runs} liveCounts={stats.data?.counts ?? null} tps={stats.data?.throughput_tps ?? null} />
      <PrimaStrip />

      <section className={`stage ${attackLive ? "attack-flash" : ""}`}>
        <div className="stage-h">
          <div>
            <div className="k">Network intelligence</div>
            <div className="t">Live Transaction Universe</div>
          </div>
          <div className="stack" style={{ gap: 10, alignItems: "flex-end" }}>
            <UniverseLegend groundTruth={gt} />
            <div className="row wrap" style={{ justifyContent: "flex-end" }}>
              <button className={`btn xs ${orbit ? "on" : "ghost"}`} onClick={() => setOrbit(!orbit)}>Auto-orbit</button>
              <button className={`btn xs ${gt ? "on" : "ghost"}`} onClick={() => setGt(!gt)} title="Colour postings tagged by the simulator (evaluation only — never scored)">Simulator ground truth</button>
              <button className="btn xs ghost" onClick={() => setFocus({ ids: [...accounts.current.keys()], seq: Date.now() })}>Reset view</button>
              <Link className="btn xs" to="/network">Full screen ↗</Link>
            </div>
          </div>
        </div>
        <details className="uni-how" style={{ margin: "4px 22px 8px", position: "relative", zIndex: 3 }}>
          <summary className="xs muted" style={{ cursor: "pointer" }}>How the universe works</summary>
          <div className="xs ink2" style={{ maxWidth: 980, lineHeight: 1.6, marginTop: 6 }}>
            Every account is a node at a fixed position derived from its id (merchants in the core, demo customers in their own shell, external
            counterparties on the outer ring). Each new ledger posting draws an edge with a travelling particle; edges fade and expire after the live
            window. Faint lines are a sample of older history. Colour is the account's live status from detection intelligence; size grows with severity;
            a crimson ring marks confirmed fraud, violet a scoped hold. Click a node to investigate it.
          </div>
        </details>
        <div style={{ position: "relative" }}>
          <LiveUniverse3D mode="live" groundTruth={gt} autoRotate={orbit && !sel} size="hero" selected={sel?.id ?? null}
                          onSelect={onSelect} onInfo={onInfo} onStats={onStats} focus={focus} />
          {sel && <UniverseDrawer id={sel.id} acct={accounts.current.get(sel.id) ?? sel.acct} onClose={() => setSel(null)}
                                  onFocus={() => setFocus({ ids: [sel.id], seq: Date.now() })} />}
        </div>
      </section>

      <div className="grid cols-2 align-start section-gap">
        <CommandCenter scenarios={scen.data} runs={runs.data} runsUnavailable={runs.unavailable} selected={scenarioId}
                       onSelect={setScenarioId} onChanged={() => { scen.reload(); }} />
        <AttackSubgraph scenario={attackScenario} statusOf={statusOf} />
      </div>

      <div className="section-gap"><LiveStreams /></div>
      <div className="section-gap"><ScoreTables key={uniVersion > 0 ? "u" : "n"} statusOf={statusOf} /></div>

      <div className="grid cols-2 align-start section-gap">
        <LastAttackResult runs={runs.data} unavailable={runs.unavailable} />
        <div className="stack">
          <AttentionPanel />
          <AgreementPanel />
        </div>
      </div>

      <div className="section-gap">
        <AttackHistory runs={runs.data} unavailable={runs.unavailable}
                       onPick={(r) => { setScenarioId(r.scenario_id); setFocus({ ids: r.injected, seq: Date.now() }); }} />
      </div>
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
