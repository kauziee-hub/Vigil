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
      m.Chart.defaults.font.family = '"Inter", "Segoe UI", system-ui, sans-serif';
      m.Chart.defaults.font.size = 11;
      m.Chart.defaults.color = "#69737f";
      m.Chart.defaults.borderColor = "rgba(15,20,25,0.06)";
      return m;
    });
  }
  return lib;
}

export const CH = {
  teal: "rgba(47, 191, 160, 0.9)",
  amber: "rgba(209, 149, 15, 0.9)",
  red: "rgba(224, 71, 61, 0.9)",
  magenta: "rgba(197, 111, 176, 0.9)",
  blue: "rgba(52, 140, 230, 0.9)",
  grey: "rgba(107, 122, 143, 0.55)",
  violet: "rgba(122, 107, 224, 0.9)",
  orange: "rgba(224, 116, 44, 0.9)",
  mint: "rgba(79, 214, 184, 0.9)",
  slate: "rgba(107, 122, 143, 0.85)",
};
export const TIER_COLORS = [CH.slate, CH.amber, CH.orange, CH.violet, CH.red];

export function baseOptions(extra: Record<string, unknown> = {}): ChartOptions {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: { legend: { labels: { color: "#69737f", boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "rectRounded" } },
               tooltip: { backgroundColor: "rgba(15,20,25,0.94)", borderColor: "rgba(79,214,184,0.4)", borderWidth: 1, padding: 10, cornerRadius: 10 } },
    scales: {
      x: { ticks: { color: "#8a939e", maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }, grid: { display: false }, border: { display: false } },
      y: { ticks: { color: "#8a939e" }, grid: { color: "rgba(15,20,25,0.06)" }, border: { display: false }, beginAtZero: true },
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
