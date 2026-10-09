// Chart.js v4 wrapper. chart.js is imported dynamically so only pages that draw charts pay for it, and every chart
// updates in place (update("none")) at most once per second regardless of how often its data changes.
import { useEffect, useRef, type ReactNode } from "react";
import type { Chart, ChartConfiguration, ChartData, ChartOptions, ChartType } from "chart.js";
import { withChunkReload } from "../lib/chunks";

let lib: Promise<typeof import("chart.js")> | null = null;
function loadChart() {
  if (!lib) {
    lib = withChunkReload(() => import("chart.js")).then((m) => {
      m.Chart.register(...m.registerables);
      m.Chart.defaults.font.family = '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif';
      m.Chart.defaults.font.size = 11;
      m.Chart.defaults.color = "#8790a0";
      m.Chart.defaults.borderColor = "rgba(160,170,185,0.08)";
      return m;
    });
  }
  return lib;
}

export const CH = {
  teal: "rgba(95, 176, 214, 0.85)",
  amber: "rgba(214, 162, 63, 0.85)",
  red: "rgba(226, 86, 78, 0.85)",
  magenta: "rgba(197, 111, 176, 0.85)",
  blue: "rgba(95, 134, 184, 0.85)",
  grey: "rgba(133, 147, 168, 0.6)",
  violet: "rgba(146, 131, 214, 0.85)",
  orange: "rgba(221, 122, 62, 0.85)",
  mint: "rgba(91, 147, 240, 0.85)",
};
export const TIER_COLORS = [CH.blue, CH.amber, CH.orange, CH.violet, CH.red];

export function baseOptions(extra: Record<string, unknown> = {}): ChartOptions {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: { legend: { labels: { color: "#8790a0", boxWidth: 12, boxHeight: 12 } }, tooltip: { backgroundColor: "rgba(14,18,23,0.95)", borderColor: "rgba(91,147,240,0.3)", borderWidth: 1 } },
    scales: {
      x: { ticks: { color: "#8790a0", maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }, grid: { color: "rgba(160,170,185,0.05)" } },
      y: { ticks: { color: "#8790a0" }, grid: { color: "rgba(160,170,185,0.08)" }, beginAtZero: true },
    },
    ...extra,
  } as ChartOptions;
}

export function ChartCanvas<T extends ChartType>({ type, data, options, height = 250, empty }: {
  type: T; data: ChartData<T>; options?: ChartOptions<T>; height?: number; empty?: ReactNode;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const chart = useRef<Chart | null>(null);
  const latest = useRef({ data, options });
  latest.current = { data, options };
  const lastUpdate = useRef(0);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    loadChart().then((m) => {
      if (!alive || !canvas.current) return;
      chart.current = new m.Chart(canvas.current, {
        type, data: latest.current.data, options: latest.current.options ?? (baseOptions() as ChartOptions<T>),
      } as ChartConfiguration<T>) as unknown as Chart;
      lastUpdate.current = performance.now();
    });
    return () => { alive = false; window.clearTimeout(timer.current); chart.current?.destroy(); chart.current = null; };
    // the chart type never changes for a mounted canvas
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const apply = () => {
      const c = chart.current;
      if (!c) return;
      const d = latest.current.data as ChartData;
      c.data.labels = d.labels;
      d.datasets.forEach((ds, i) => {
        if (c.data.datasets[i]) Object.assign(c.data.datasets[i], ds);
        else c.data.datasets.push(ds);
      });
      c.data.datasets.length = d.datasets.length;
      c.update("none");
      lastUpdate.current = performance.now();
    };
    const wait = lastUpdate.current + 1000 - performance.now();
    window.clearTimeout(timer.current);
    if (wait <= 0) apply();
    else timer.current = window.setTimeout(apply, wait);
  }, [data]);

  const isEmpty = !data.datasets.length || data.datasets.every((d) => !(d.data as unknown[]).length);
  return (
    <div className="chart-box" style={{ height }}>
      <canvas ref={canvas} />
      {isEmpty && empty && <div className="chart-empty">{empty}</div>}
    </div>
  );
}
