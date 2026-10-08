// SYSTEM HEALTH — decision latency, payment provider, realtime, caches, data, intel availability.
// Reads /api/system/health on load, on demand ("Check now") and when the console bus reports a change
// (ambient / reset / intel / mode). Nothing is polled.
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import type { SystemHealth } from "../api/types";
import { TiersOverTimeChart, VolumeChart } from "../components/live/LiveStatsCharts";
import { usePlatform, useConsoleEvents } from "../components/Shell";
import { ErrorNote, KV, Loading, Metric, PageHead, Panel, Pill, Sim } from "../components/ui";
import { duration, formatBytes, formatINR, formatStamp, pct } from "../lib/format";
import { useDebounced } from "../lib/hooks";
import { useLiveStats } from "../lib/live";

type Probe = { name: string; path: string; status: number | null; ms: number | null; note?: string };
const PROBES: { name: string; path: string; run: () => Promise<unknown> }[] = [
  { name: "Graph scene (3D)", path: "/api/graph/scene", run: () => api.scene({ cap: 10 }) },
  { name: "Governance summary", path: "/api/governance/summary", run: () => api.governance() },
  { name: "Intervention queue", path: "/api/interventions", run: () => api.interventions("open") },
  { name: "Operating mode", path: "/api/mode", run: () => api.mode() },
  { name: "Scenarios", path: "/api/scenarios", run: () => api.scenarios() },
  { name: "Intel · overview", path: "/api/intel/overview", run: () => api.intelOverview() },
  { name: "Intel · models", path: "/api/intel/models", run: () => api.intelModels() },
  { name: "Intel · per-account scores", path: "/api/intel/scores", run: () => api.intelScores() },
];

export function HealthPage() {
  const { conn, metrics: m, mode } = usePlatform();
  const [h, setH] = useState<SystemHealth | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [rtt, setRtt] = useState<number | null>(null);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [probes, setProbes] = useState<Probe[]>([]);
  const [busy, setBusy] = useState(false);
  const live = useLiveStats(5000);

  const check = useCallback(async () => {
    const t0 = performance.now();
    try {
      const x = await api.systemHealth();
      setRtt(Math.round(performance.now() - t0)); setH(x); setErr(null); setCheckedAt(new Date().toISOString());
    } catch (e) { setErr(e instanceof ApiError ? e : new ApiError(0, "error", String(e))); }
  }, []);
  const probe = useCallback(async () => {
    setBusy(true);
    const out = await Promise.all(PROBES.map(async (p): Promise<Probe> => {
      const t0 = performance.now();
      try { await p.run(); return { name: p.name, path: p.path, status: 200, ms: Math.round(performance.now() - t0) }; }
      catch (e) {
        const ae = e instanceof ApiError ? e : null;
        return { name: p.name, path: p.path, status: ae?.status ?? 0, ms: Math.round(performance.now() - t0), note: ae?.status === 404 ? "not served yet" : ae?.message };
      }
    }));
    setProbes(out); setBusy(false);
  }, []);
  useEffect(() => { check(); probe(); }, [check, probe]);
  const onEvent = useDebounced(() => check(), 600);
  useConsoleEvents((e) => { if (["ambient.changed", "demo.reset", "intel.updated", "mode.changed"].includes(e.type)) onEvent(); });

  const toggleAmbient = async () => {
    if (!h) return;
    try { await api.ambient(!h.ambient); check(); } catch (e) { setErr(e instanceof ApiError ? e : null); }
  };

  const scene = (h?.cache?.scene ?? null) as { entries?: number; hits?: number; misses?: number } | null;
  return (
    <>
      <PageHead crumb="Control" title="System health"
        lede="Is the platform able to decide, pay, push and explain right now? Values are read on load, on demand and when the realtime channel reports a change."
        actions={<>
          <span className="xs muted">{checkedAt ? `checked ${formatStamp(checkedAt)}` : ""}</span>
          <button className="btn sm" disabled={busy} onClick={() => { check(); probe(); }}>{busy ? "Checking…" : "Check now"}</button>
          <button className="btn sm" disabled={!h} onClick={toggleAmbient}><span className={`dot ${h?.ambient ? "ok" : ""}`} /> Background stream {h ? (h.ambient ? "on" : "off") : "…"}</button>
        </>} />
      <ErrorNote error={err} />
      {!h && !err && <Loading text="Reading system health" />}
      {h && (
        <div className="stack loose">
          <div className="mstrip inv-tiles">
            <Metric k="Status" v={h.status.toUpperCase()} status={h.status === "ok" ? "normal" : "critical"} d={`server time ${formatStamp(h.time)}`} />
            <Metric k="Uptime" v={duration(h.uptime_s)} d={h.seeded_at ? `seeded ${formatStamp(h.seeded_at)}` : "not seeded"} />
            <Metric k="Decision p95" v={h.latency_p95_ms != null ? `${h.latency_p95_ms.toFixed(1)} ms` : "—"} d={m?.latency_p50_ms != null ? `p50 ${m.latency_p50_ms.toFixed(1)} ms` : "per payment evaluation"} />
            <Metric k="API round-trip" v={rtt != null ? `${rtt} ms` : "—"} d="this browser → /api/system/health" />
            <Metric k="Realtime" v={conn === "open" ? "LIVE" : conn.toUpperCase()} status={conn === "open" ? "normal" : conn === "connecting" ? "watch" : "critical"} d={`${h.ws_clients} socket${h.ws_clients === 1 ? "" : "s"} on the server`} />
            <Metric k="Intel layer" v={h.intel_available ? "ON" : "OFF"} status={h.intel_available ? "normal" : undefined} d="RF · GNN · drift · pattern memory" />
            <Metric k="Database" v={formatBytes(h.db_size_bytes)} d="SQLite + WAL" />
            <Metric k="Throughput" v={live.data ? `${live.data.throughput_tps.toFixed(2)} tx/s` : "—"} d={live.unavailable ? "/api/live/stats not served" : "ledger postings · live stats"} />
          </div>

          <div className="grid cols-2 align-start">
            <Panel kicker="Live pipeline" title="Ledger postings per 10 s" q="every posting is scored live; injected = simulator ground truth">
              <div className="chart-shell"><VolumeChart stats={live.data} height={210} /></div>
            </Panel>
            <Panel kicker="Decision path" title="PRIMA decisions by tier" q={live.data?.tiers_over_time?.length ? "per minute" : "since seed"}>
              <div className="chart-shell"><TiersOverTimeChart stats={live.data} tierMix={m?.decisions_by_tier} height={210} /></div>
            </Panel>
          </div>

          <div className="grid cols-3 align-start">
            <Panel kicker="Decision path" title="Pre-commit engine">
              <KV rows={[
                ["Policy", <span className="mono xs">{h.policy_version}</span>],
                ["Mode", <Pill status={mode?.mode === "shadow" ? "watch" : "normal"}>{mode?.mode ?? "—"}</Pill>],
                ["ML on decision path", h.ml_on_decision_path ? <Pill status="watch">yes</Pill> : "no — transparent engine only"],
                ["Decisions", m ? m.decisions_total.toLocaleString("en-IN") : "—"],
                ["Pending intents", m ? String(m.pending_intents) : "—"],
                ["Latency p50 · p95", m ? `${m.latency_p50_ms?.toFixed(1) ?? "—"} ms · ${m.latency_p95_ms?.toFixed(1) ?? "—"} ms` : "—"],
              ]} />
            </Panel>
            <Panel kicker="Payments" title="Provider & gateway">
              <KV rows={[
                ["Provider", h.payment_provider === "razorpay_test" ? "Razorpay TEST" : "Mock provider"],
                ["Label", <span className="xs">{h.payment_provider_label}</span>],
                ["Gateway", <span className="row tight">{h.gateway.status === "ok" ? <Pill status="normal">ok</Pill> : h.gateway.status === "auth_failed" ? <Pill status="watch">keys rejected</Pill> : <Pill status="unknown">{h.gateway.status}</Pill>}<span className="xs muted">{h.gateway.detail}</span></span>],
                ["Razorpay key", h.razorpay_key_id ? <span className="mono xs">{h.razorpay_key_id.slice(0, 12)}…</span> : <span className="muted">not configured</span>],
                ["Money moves", "only after approval or a bank release; test funds only"],
              ]} />
            </Panel>
            <Panel kicker="Realtime" title="Push channel">
              <KV rows={[
                ["This browser", <span className="row tight"><span className={`dot ${conn === "open" ? "ok" : conn === "connecting" ? "warn" : "bad"}`} />{conn}</span>],
                ["Server sockets", String(h.ws_clients)],
                ["Pattern", "one console WebSocket; pages debounce bursts into one refetch"],
                ["Polling", "none"],
                ["Background stream", h.ambient ? "on" : "off"],
              ]} />
            </Panel>
            <Panel kicker="Data" title="Ledger & graph">
              <KV rows={[
                ["Accounts", h.accounts.toLocaleString("en-IN")],
                ["Transactions", h.transactions.toLocaleString("en-IN")],
                ["Graph", `${h.graph_nodes} nodes · ${h.graph_edges.toLocaleString("en-IN")} edges · v${h.graph_version}`],
                ["Ledger conservation", m ? (m.system_total_paise === 0 ? <span style={{ color: "var(--st-normal)" }}>balanced (₹0)</span> : <span style={{ color: "var(--st-critical)" }}>{formatINR(m.system_total_paise)}</span>) : "—"],
                ["Seeded", h.seeded_at ? formatStamp(h.seeded_at) : "—"],
              ]} />
            </Panel>
            <Panel kicker="Caches" title="Server-side caches" flush>
              <table className="dt compact">
                <thead><tr><th>Cache</th><th className="num">Entries</th><th className="num">Hits</th><th className="num">Misses</th><th className="num">Hit rate</th></tr></thead>
                <tbody>
                  {Object.entries(h.cache).map(([k, v]) => {
                    const c = (v ?? {}) as { entries?: number; hits?: number; misses?: number };
                    const tot = (c.hits ?? 0) + (c.misses ?? 0);
                    return <tr key={k}><td className="mono xs">{k}</td><td className="num">{c.entries ?? "—"}</td><td className="num">{c.hits ?? "—"}</td><td className="num">{c.misses ?? "—"}</td><td className="num">{tot ? pct((c.hits ?? 0) / tot) : "—"}</td></tr>;
                  })}
                  {!Object.keys(h.cache).length && <tr><td colSpan={5} className="muted">No cache reported.</td></tr>}
                </tbody>
              </table>
              {scene && <div className="panel-f">The 3D scene is cached per query and graph version; the browser also caches scene payloads per scope.</div>}
            </Panel>
            <Panel kicker="Intelligence" title="Inputs and models">
              <KV rows={[
                ["Detection intelligence", h.intel_available ? <Pill status="normal">available</Pill> : <span className="muted">not available — model panels show honest empty states</span>],
                ["External intel provider", <span className="row tight"><span className="xs">{h.external_intel_provider}</span><Sim /></span>],
                ["Context signals", <Sim text="SIMULATED CONTEXT" />],
              ]} />
            </Panel>
          </div>

          <Panel kicker="Endpoints" title="v2 endpoint coverage" flush q="checked on load and on demand — not polled">
            <table className="dt compact">
              <thead><tr><th>Capability</th><th>Endpoint</th><th>Status</th><th className="num">Time</th><th>Note</th></tr></thead>
              <tbody>
                {probes.map((p) => (
                  <tr key={p.path}>
                    <td>{p.name}</td><td className="mono xs">{p.path}</td>
                    <td>{p.status === 200 ? <Pill status="normal">200</Pill> : p.status === 404 ? <Pill status="unknown">404</Pill> : <Pill status="critical">{String(p.status ?? "—")}</Pill>}</td>
                    <td className="num">{p.ms != null ? `${p.ms} ms` : "—"}</td><td className="xs muted">{p.note ?? ""}</td>
                  </tr>
                ))}
                {!probes.length && <tr><td colSpan={5}><Loading /></td></tr>}
              </tbody>
            </table>
          </Panel>
        </div>
      )}
    </>
  );
}
