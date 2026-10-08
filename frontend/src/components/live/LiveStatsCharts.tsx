// LIVE STATISTICS (Chart.js) — volume per 10 s (normal vs injected = simulator ground truth), channels, attack runs by
// type, threshold & recall per run, detection latency per run, roles of flagged mules, PRIMA decisions by tier over time.
// Source: /api/live/stats + AttackRun. While /api/live/stats is not served, volume and channels are counted honestly from
// the postings this browser received since the page opened (labelled as such). Charts redraw at most once per second.
import { useMemo, useRef, useState } from "react";
import type { AttackRun, LedgerTx, LiveStats, Metrics } from "../../api/types";
import { formatTime } from "../../lib/format";
import { useThrottled } from "../../lib/live";
import { ROLE_LABEL } from "../../lib/status";
import { CH, ChartCanvas, TIER_COLORS, baseOptions } from "../charts";
import { useConsoleEvents } from "../Shell";
import { Panel } from "../ui";

type Bucket = { t: number; normal: number; attack: number };
const BUCKET = 10_000;

/** Client-side counting of received postings (fallback only). */
function useLocalVolume() {
  const buckets = useRef(new Map<number, Bucket>());
  const channels = useRef(new Map<string, number>());
  const [snap, setSnap] = useState<{ volume: Bucket[]; channels: Record<string, number>; since: number }>({ volume: [], channels: {}, since: Date.now() });
  const since = useRef(Date.now());
  const flush = useThrottled(() => {
    const v = [...buckets.current.values()].sort((a, b) => a.t - b.t).slice(-60);
    setSnap({ volume: v, channels: Object.fromEntries(channels.current), since: since.current });
  }, 1000);
  useConsoleEvents((e) => {
    if (e.type === "ledger.posted") {
      const tx = e.data as LedgerTx & { seed_attack?: string | null; channel?: string };
      if (!tx?.ts) return;
      const k = Math.floor(Date.parse(tx.ts) / BUCKET) * BUCKET;
      const b = buckets.current.get(k) ?? { t: k, normal: 0, attack: 0 };
      if (tx.seed_attack) b.attack++; else b.normal++;
      buckets.current.set(k, b);
      const ch = (tx.channel ?? "upi").toUpperCase();
      channels.current.set(ch, (channels.current.get(ch) ?? 0) + 1);
      flush();
    } else if (e.type === "demo.reset") {
      buckets.current.clear(); channels.current.clear(); since.current = Date.now(); flush();
    }
  });
  return snap;
}

const CHANNEL_COLORS = [CH.teal, CH.blue, CH.amber, CH.magenta, CH.grey, CH.violet, CH.orange];

export function LiveStatsCharts({ stats, statsUnavailable, runs, metrics }: {
  stats: LiveStats | null; statsUnavailable: boolean; runs: AttackRun[] | null; metrics: Metrics | null;
}) {
  const local = useLocalVolume();
  const useLocal = !stats;
  const volume = useMemo(() => (stats ? stats.volume.map((v) => ({ t: Date.parse(v.t), normal: v.normal, attack: v.attack })) : local.volume), [stats, local.volume]);
  const channels = stats ? stats.channels : local.channels;
  const chrono = useMemo(() => [...(runs ?? [])].filter((r) => r.status === "completed").sort((a, b) => a.started_at.localeCompare(b.started_at)).slice(-12), [runs]);
  const byType = useMemo(() => {
    if (stats?.runs_by_type?.length) return stats.runs_by_type;
    const m = new Map<string, { scenario_id: string; name: string; runs: number; detected_runs: number }>();
    (runs ?? []).filter((r) => r.status === "completed").forEach((r) => {
      const x = m.get(r.scenario_id) ?? { scenario_id: r.scenario_id, name: r.name, runs: 0, detected_runs: 0 };
      x.runs++; if (r.detected.length) x.detected_runs++;
      m.set(r.scenario_id, x);
    });
    return [...m.values()];
  }, [stats, runs]);
  const roles = stats ? Object.entries(stats.roles_flagged ?? {}).sort((a, b) => b[1] - a[1]) : [];
  const tiersOT = stats?.tiers_over_time ?? [];
  const tierMix = stats?.tiers ?? metrics?.decisions_by_tier ?? {};

  const noRuns = "No completed attack run yet.";
  return (
    <Panel kicker="System intelligence" title="Live Statistics"
           q={useLocal ? `volume and channels counted from postings received since ${formatTime(new Date(local.since).toISOString())} — /api/live/stats not served${statsUnavailable ? "" : " yet"}` : undefined}>
      <div className="charts-grid">
        <div>
          <div className="chart-h">Transaction volume (per 10 s)</div>
          <div className="chart-shell">
            <ChartCanvas type="bar" height={240} empty="Waiting for postings…"
              data={{ labels: volume.map((v) => formatTime(new Date(v.t).toISOString())), datasets: [
                { label: "Normal", data: volume.map((v) => v.normal), backgroundColor: CH.teal, stack: "v" },
                { label: "Injected (simulator ground truth)", data: volume.map((v) => v.attack), backgroundColor: CH.magenta, stack: "v" }] }}
              options={baseOptions({ scales: { x: { stacked: true, ticks: { color: "#8790a0", maxTicksLimit: 6, maxRotation: 0 }, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { color: "#8790a0", precision: 0 }, grid: { color: "rgba(160,170,185,0.08)" } } } }) as never} />
          </div>
        </div>
        <div>
          <div className="chart-h">Transactions by channel</div>
          <div className="chart-shell">
            <ChartCanvas type="doughnut" height={240} empty="No postings counted yet."
              data={{ labels: Object.keys(channels).map((c) => c.toUpperCase()), datasets: [{ data: Object.values(channels), backgroundColor: CHANNEL_COLORS, borderColor: "rgba(14,18,23,0.9)", borderWidth: 2 }] }}
              options={{ responsive: true, maintainAspectRatio: false, animation: false, cutout: "58%", plugins: { legend: { position: "right", labels: { color: "#8790a0", boxWidth: 12 } } } } as never} />
          </div>
        </div>
        <div>
          <div className="chart-h">Attack runs by type</div>
          <div className="chart-shell">
            <ChartCanvas type="bar" height={240} empty={noRuns}
              data={{ labels: byType.map((x) => x.name), datasets: [
                { label: "Runs", data: byType.map((x) => x.runs), backgroundColor: CH.blue },
                { label: "Detected", data: byType.map((x) => x.detected_runs), backgroundColor: CH.red }] }}
              options={baseOptions({ scales: { x: { ticks: { color: "#8790a0", maxRotation: 0, autoSkip: true }, grid: { display: false } }, y: { beginAtZero: true, ticks: { color: "#8790a0", precision: 0 }, grid: { color: "rgba(160,170,185,0.08)" } } } }) as never} />
          </div>
        </div>
        <div>
          <div className="chart-h">Threshold &amp; recall per run</div>
          <div className="chart-shell">
            <ChartCanvas type="line" height={240} empty={noRuns}
              data={{ labels: chrono.map((r) => r.run_id), datasets: [
                { label: "Model-evidence threshold", data: chrono.map((r) => r.model_threshold), borderColor: CH.amber, backgroundColor: CH.amber, tension: 0.25 },
                { label: "Recall", data: chrono.map((r) => r.recall), borderColor: CH.teal, backgroundColor: CH.teal, tension: 0.25 },
                { label: "Precision", data: chrono.map((r) => r.precision), borderColor: CH.red, backgroundColor: CH.red, tension: 0.25 }] }}
              options={baseOptions({ scales: { x: { ticks: { color: "#8790a0" }, grid: { display: false } }, y: { min: 0, max: 1, ticks: { color: "#8790a0" }, grid: { color: "rgba(160,170,185,0.08)" } } } }) as never} />
          </div>
        </div>
        <div>
          <div className="chart-h">Detection latency per run</div>
          <div className="chart-shell">
            <ChartCanvas type="bar" height={240} empty={noRuns}
              data={{ labels: chrono.map((r) => r.run_id), datasets: [
                { label: "First warning (ms)", data: chrono.map((r) => r.first_warning_ms), backgroundColor: CH.amber },
                { label: "Detection (ms)", data: chrono.map((r) => r.detection_ms), backgroundColor: CH.red }] }}
              options={baseOptions() as never} />
          </div>
        </div>
        <div>
          <div className="chart-h">Roles of flagged mules</div>
          <div className="chart-shell">
            <ChartCanvas type="bar" height={240} empty={stats ? "No account is flagged with a role." : "Needs /api/live/stats."}
              data={{ labels: roles.map(([r]) => ROLE_LABEL[r] ?? r), datasets: [{ label: "Flagged accounts", data: roles.map(([, n]) => n), backgroundColor: CH.red }] }}
              options={baseOptions({ indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { color: "#8790a0", precision: 0 }, grid: { color: "rgba(160,170,185,0.08)" } }, y: { ticks: { color: "#8790a0" }, grid: { display: false } } } }) as never} />
          </div>
        </div>
        <div className="span-2">
          <div className="chart-h">PRIMA decisions by tier · {tiersOT.length ? "per minute" : "since reset"}</div>
          <div className="chart-shell">
            {tiersOT.length ? (
              <ChartCanvas type="bar" height={240}
                data={{ labels: tiersOT.map((x) => formatTime(x.t)), datasets: (["t0", "t1", "t2", "t3", "t4"] as const).map((k, i) => ({
                  label: `T${i}`, data: tiersOT.map((x) => x[k]), backgroundColor: TIER_COLORS[i], stack: "t" })) }}
                options={baseOptions({ scales: { x: { stacked: true, ticks: { color: "#8790a0", maxTicksLimit: 10, maxRotation: 0 }, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { color: "#8790a0", precision: 0 }, grid: { color: "rgba(160,170,185,0.08)" } } } }) as never} />
            ) : (
              <ChartCanvas type="bar" height={240} empty="No decisions yet."
                data={{ labels: Object.keys(tierMix).map((t) => `T${t}`), datasets: [{ label: "Decisions", data: Object.values(tierMix), backgroundColor: Object.keys(tierMix).map((t) => TIER_COLORS[Number(t)] ?? CH.grey) }] }}
                options={baseOptions({ plugins: { legend: { display: false } } }) as never} />
            )}
          </div>
        </div>
        <div>
          <div className="chart-h">Model-evidence threshold history</div>
          <div className="chart-shell">
            <ChartCanvas type="line" height={240} empty={stats ? "No threshold change yet." : "Needs /api/live/stats."}
              data={{ labels: (stats?.threshold_history ?? []).map((x) => formatTime(x.t)), datasets: [
                { label: "Threshold", data: (stats?.threshold_history ?? []).map((x) => x.value), borderColor: CH.amber, backgroundColor: CH.amber, stepped: true }] }}
              options={baseOptions({ plugins: { legend: { display: false } }, scales: { x: { ticks: { color: "#8790a0", maxTicksLimit: 6 }, grid: { display: false } }, y: { min: 0, max: 1, ticks: { color: "#8790a0" }, grid: { color: "rgba(160,170,185,0.08)" } } } }) as never} />
          </div>
        </div>
      </div>
    </Panel>
  );
}

const LEGEND_BOTTOM = { position: "bottom", labels: { color: "#8790a0", boxWidth: 10, boxHeight: 10 } };
const STACK_SCALES = (ticks = 8) => ({
  x: { stacked: true, ticks: { color: "#8790a0", maxTicksLimit: ticks, maxRotation: 0 }, grid: { display: false } },
  y: { stacked: true, beginAtZero: true, ticks: { color: "#8790a0", precision: 0 }, grid: { color: "rgba(160,170,185,0.08)" } },
});

/** PRIMA decisions by tier per minute (live stats), stacked; falls back to the tier mix since reset. */
export function TiersOverTimeChart({ stats, tierMix, height = 220 }: { stats: LiveStats | null; tierMix?: Record<string, number>; height?: number }) {
  const tiersOT = stats?.tiers_over_time ?? [];
  const mix = stats?.tiers ?? tierMix ?? {};
  if (tiersOT.length) {
    return (
      <ChartCanvas type="bar" height={height}
        data={{ labels: tiersOT.map((x) => formatTime(x.t)), datasets: (["t0", "t1", "t2", "t3", "t4"] as const).map((k, i) => ({
          label: `T${i}`, data: tiersOT.map((x) => x[k]), backgroundColor: TIER_COLORS[i], stack: "t" })) }}
        options={baseOptions({ plugins: { legend: LEGEND_BOTTOM }, scales: STACK_SCALES() }) as never} />
    );
  }
  return (
    <ChartCanvas type="bar" height={height} empty="No decisions yet."
      data={{ labels: Object.keys(mix).map((t) => `T${t}`), datasets: [{ label: "Decisions", data: Object.values(mix), backgroundColor: Object.keys(mix).map((t) => TIER_COLORS[Number(t)] ?? CH.grey) }] }}
      options={baseOptions({ plugins: { legend: { display: false } } }) as never} />
  );
}

/** Ledger volume per 10 s from live stats (normal vs injected = simulator ground truth). */
export function VolumeChart({ stats, height = 220 }: { stats: LiveStats | null; height?: number }) {
  const v = stats?.volume ?? [];
  return (
    <ChartCanvas type="bar" height={height} empty={stats ? "No postings in the stats window." : "Waiting for /api/live/stats…"}
      data={{ labels: v.map((x) => formatTime(x.t)), datasets: [
        { label: "Normal", data: v.map((x) => x.normal), backgroundColor: CH.teal, stack: "v" },
        { label: "Injected (simulator ground truth)", data: v.map((x) => x.attack), backgroundColor: CH.magenta, stack: "v" }] }}
      options={baseOptions({ plugins: { legend: LEGEND_BOTTOM }, scales: STACK_SCALES(6) }) as never} />
  );
}
