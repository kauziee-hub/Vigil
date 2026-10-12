// LIVE STATISTICS charts (Chart.js) shared by Governance and Health: PRIMA decisions by tier per minute, and ledger
// volume per 10 s (normal vs injected = simulator ground truth). Source: /api/live/stats. Detection-run charts live in
// DetectionCharts.tsx; the operations-center traffic chart in OverviewPage. Charts redraw at most once per second.
import type { LiveStats } from "../../api/types";
import { formatTime } from "../../lib/format";
import { CH, ChartCanvas, TIER_COLORS, baseOptions } from "../charts";

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
