// Detection & Models charts (chart.js, loaded on demand): accounts flagged per family and model drivers (live), injected-
// attack runs (caught per pattern, speed + completeness, roles, adaptive threshold), held-out metrics per model and
// per-attack recall (both SYNTHETIC VALIDATION). Values come from /api/intel/*, /api/live/stats and /api/attacks/runs.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AttackRun, DetectorFamily, IntelOverview, ModelInfo } from "../api/types";
import { FAMILY, ROLE_LABEL } from "../lib/status";
import { CH, ChartCanvas, baseOptions } from "./charts";

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {});
const num = (v: unknown): number | null => (typeof v === "number" && !Number.isNaN(v) ? v : null);

const MODEL_LABEL: Record<string, string> = { random_forest: "Random Forest", gnn: "GNN (GAT)", rules: "Rules", drift: "Drift", pattern_memory: "Pattern memory" };
const ATTACK_LABEL: Record<string, string> = {
  fan_in: "Fan-in", fan_out: "Fan-out", circular: "Circular", velocity_chain: "Velocity chain", cross_channel: "Cross-channel",
  shared_device: "Shared device", behavioural_drift: "Behav. drift", volume_spike: "Volume spike", smurfing: "Smurfing", dormant: "Dormant",
};
const AXIS = { color: "#8790a0" };
const GRID = { color: "rgba(160,170,185,0.16)" };

export function FlaggedPerFamilyChart({ overview }: { overview: IntelOverview | null }) {
  const rows = Object.entries(overview?.detector_agreement ?? {}).sort((a, b) => b[1] - a[1]);
  return (
    <ChartCanvas type="bar" height={300} empty={overview ? "No family flags any account." : "Waiting for /api/intel/overview…"}
      data={{ labels: rows.map(([f]) => FAMILY[f as DetectorFamily]?.label ?? f), datasets: [{ label: "Accounts flagged", data: rows.map(([, n]) => n), backgroundColor: CH.mint, borderRadius: 4 }] }}
      options={baseOptions({ indexAxis: "y", plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { ...AXIS, precision: 0 }, grid: GRID }, y: { ticks: { color: "#a7b0bd" }, grid: { display: false } } } }) as never} />
  );
}

export function ModelMetricsChart({ models }: { models: ModelInfo[] | null }) {
  const ms = models ?? [];
  const m = (k: string) => ms.map((x) => num(obj(x.metrics)[k]));
  return (
    <ChartCanvas type="bar" height={300} empty={models ? "No model registered." : "Waiting for /api/intel/models…"}
      data={{ labels: ms.map((x) => MODEL_LABEL[x.family] ?? x.model_id), datasets: [
        { label: "Precision", data: m("precision"), backgroundColor: CH.teal, borderRadius: 3 },
        { label: "Recall", data: m("recall"), backgroundColor: CH.amber, borderRadius: 3 },
        { label: "F1", data: m("f1"), backgroundColor: CH.blue, borderRadius: 3 },
        { label: "PR-AUC", data: m("pr_auc"), backgroundColor: CH.magenta, borderRadius: 3 },
      ] }}
      options={baseOptions({ plugins: { legend: { position: "bottom", labels: { ...AXIS, boxWidth: 10, boxHeight: 10 } } },
        scales: { x: { ticks: { color: "#a7b0bd", maxRotation: 0, autoSkip: false, font: { size: 10 } }, grid: { display: false } }, y: { min: 0, max: 1, ticks: AXIS, grid: GRID } } }) as never} />
  );
}

export function PerAttackRecallChart({ models }: { models: ModelInfo[] | null }) {
  const pick = (fam: string) => (models ?? []).find((x) => x.family === fam) ?? null;
  const series = ([["random_forest", CH.blue], ["gnn", CH.magenta], ["rules", CH.teal]] as const)
    .map(([fam, color]) => ({ fam, color, m: pick(fam) })).filter((s) => s.m);
  const keys = [...new Set(series.flatMap((s) => Object.keys(obj(s.m!.per_attack))))];
  return (
    <ChartCanvas type="bar" height={300} empty={models ? "No per-attack results reported." : "Waiting for /api/intel/models…"}
      data={{ labels: keys.map((k) => ATTACK_LABEL[k] ?? k), datasets: series.map((s) => ({
        label: MODEL_LABEL[s.fam], data: keys.map((k) => num(obj(obj(s.m!.per_attack)[k]).recall)), backgroundColor: s.color, borderRadius: 2,
        barPercentage: 0.9, categoryPercentage: 0.8 })) }}
      options={baseOptions({ indexAxis: "y", plugins: { legend: { position: "bottom", labels: { ...AXIS, boxWidth: 10, boxHeight: 10 } } },
        scales: { y: { ticks: { color: "#a7b0bd", autoSkip: false, font: { size: 10.5 } }, grid: { display: false } }, x: { min: 0, max: 1, ticks: AXIS, grid: GRID } } }) as never} />
  );
}

/** Headline numbers for the KPI row. */
export function modelHeadline(models: ModelInfo[] | null, fam: string, key: string): number | null {
  const m = (models ?? []).find((x) => x.family === fam);
  return m ? num(obj(m.metrics)[key]) : null;
}

// ── v9: explained live charts (Detection page) ─────────────────────────────
/** Plain meaning of each SHAP category (the 15 model features grouped by what they measure). */
export const SHAP_HELP: Record<string, string> = {
  "Value Risk": "how much money came in and went out in the last 72 h",
  "Ring Participation": "how many different accounts it pays and is paid by",
  "Velocity Risk": "how many payments it makes compared with its usual rate",
  "Retention Risk": "how little of the money it receives it keeps (how fast it forwards it)",
  "Account Newness": "how recently the account was opened",
  "Dormancy Risk": "how long it was quiet before this activity",
  "Counterparty Novelty": "how many of its counterparties are new to it",
  "Shared Device Risk": "how many accounts are registered on the same device",
  "Channel Risk": "how many payment rails (UPI, IMPS, NEFT …) it uses",
  "Structuring Risk": "how many payments sit just below the ₹10,000 band",
};

export interface DriverAgg { cats: [string, number][]; n: number; ids: string[] }

/** Signed SHAP by category, summed over the given accounts (from /api/intel/accounts/{id}). */
export function useModelDrivers(ids: string[]) {
  const key = ids.join("|");
  const [agg, setAgg] = useState<DriverAgg | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!ids.length) { setAgg(null); setErr(null); return; }
    let alive = true;
    const t = window.setTimeout(() => {
      Promise.all(ids.map((a) => api.intelAccount(a).catch(() => null))).then((res) => {
        if (!alive) return;
        const sum: Record<string, number> = {};
        let n = 0;
        res.forEach((x) => {
          const net = x?.shap?.category_net;
          if (!net) return;
          n++;
          Object.entries(net).forEach(([c, v]) => { sum[c] = (sum[c] ?? 0) + v; });
        });
        setErr(n ? null : "No SHAP explanation available for these accounts.");
        setAgg({ cats: Object.entries(sum).filter(([, v]) => Math.abs(v) >= 0.001).sort((p, q) => Math.abs(q[1]) - Math.abs(p[1])).slice(0, 8), n, ids });
      });
    }, 400);
    return () => { alive = false; window.clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return { agg, err };
}

export function ModelDriversChart({ agg, err }: { agg: DriverAgg | null; err: string | null }) {
  if (err) return <div className="empty">{err}</div>;
  if (!agg) return <div className="empty">Loading…</div>;
  return (
    <ChartCanvas type="bar" height={260} empty="No behaviour moved the score."
      data={{ labels: agg.cats.map(([c]) => c), datasets: [{ label: "Push on the model score (SHAP)", data: agg.cats.map(([, v]) => v),
        backgroundColor: agg.cats.map(([, v]) => (v >= 0 ? CH.red : CH.blue)), borderRadius: 5, barThickness: 14 }] }}
      options={baseOptions({ indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: {
          afterLabel: (it: { label: string }) => SHAP_HELP[it.label] ?? "" } } },
        scales: { x: { grid: GRID, border: { display: false }, ticks: AXIS, title: { display: true, text: "← lowers the score · raises the score →", color: "#8a939e", font: { size: 10.5 } } },
                  y: { grid: { display: false }, border: { display: false }, ticks: { color: "#3c4652" } } } }) as never} />
  );
}

export function RunsByPatternChart({ byType }: { byType: { name: string; runs: number; detected_runs: number }[] }) {
  return (
    <ChartCanvas type="bar" height={240} empty="No pattern injected since the last reset."
      data={{ labels: byType.map((x) => x.name), datasets: [
        { label: "Times injected", data: byType.map((x) => x.runs), backgroundColor: CH.grey, borderRadius: 4, maxBarThickness: 26 },
        { label: "Caught (at least 1 mule flagged)", data: byType.map((x) => x.detected_runs), backgroundColor: CH.teal, borderRadius: 4, maxBarThickness: 26 }] }}
      options={baseOptions({ plugins: { legend: { position: "bottom" } },
        scales: { x: { grid: { display: false }, ticks: { ...AXIS, maxRotation: 40, minRotation: 0, autoSkip: false, font: { size: 10 } } }, y: { beginAtZero: true, suggestedMax: 2, grid: GRID, ticks: { ...AXIS, precision: 0, stepSize: 1 } } } }) as never} />
  );
}

export function RunSpeedChart({ runs }: { runs: AttackRun[] }) {
  return (
    <ChartCanvas type="bar" height={240} empty="No completed run yet."
      data={{ labels: runs.map((r) => r.run_id.replace("RUN-", "#")), datasets: [
        { type: "bar", label: "Time to first flag (s)", data: runs.map((r) => (r.detection_ms ?? 0) / 1000), backgroundColor: CH.blue, borderRadius: 4, maxBarThickness: 22, yAxisID: "y" },
        { type: "line", label: "Share of injected mules flagged", data: runs.map((r) => r.recall ?? 0), borderColor: CH.red, backgroundColor: CH.red, tension: 0.3, pointRadius: 4, yAxisID: "y1" },
      ] as never }}
      options={baseOptions({ plugins: { legend: { position: "bottom" }, tooltip: { callbacks: {
          title: (items: { dataIndex: number }[]) => (items.length ? `${runs[items[0].dataIndex]?.run_id} · ${runs[items[0].dataIndex]?.name}` : "") } } },
        scales: { x: { grid: { display: false }, ticks: { ...AXIS, maxRotation: 0, autoSkip: true } },
                  y: { beginAtZero: true, grid: GRID, ticks: AXIS, title: { display: true, text: "seconds", color: "#8a939e", font: { size: 10.5 } } },
                  y1: { position: "right", min: 0, max: 1, grid: { display: false }, ticks: { ...AXIS, callback: (v: number) => `${Math.round(v * 100)}%` } } } }) as never} />
  );
}

export function RolesChart({ roles }: { roles: [string, number][] }) {
  return (
    <ChartCanvas type="bar" height={220} empty="No flagged account has a role yet."
      data={{ labels: roles.map(([r]) => ROLE_LABEL[r] ?? r), datasets: [{ label: "Flagged accounts", data: roles.map(([, n]) => n), backgroundColor: CH.red, borderRadius: 4, barThickness: 16 }] }}
      options={baseOptions({ indexAxis: "y", plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, grid: GRID, ticks: { ...AXIS, precision: 0 } }, y: { grid: { display: false }, ticks: { color: "#3c4652" } } } }) as never} />
  );
}

export function ThresholdChart({ history }: { history: { t: string; value: number }[] }) {
  return (
    <ChartCanvas type="line" height={220} empty="No evaluation yet."
      data={{ labels: history.map((x) => new Date(x.t).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false })), datasets: [
        { label: "Live flagged threshold", data: history.map((x) => x.value), borderColor: CH.violet, backgroundColor: "rgba(122,107,224,0.12)", fill: true, stepped: true, pointRadius: 3 }] }}
      options={baseOptions({ plugins: { legend: { display: false } },
        scales: { x: { grid: { display: false }, ticks: { ...AXIS, maxTicksLimit: 6 } }, y: { min: 0.4, max: 0.9, grid: GRID, ticks: AXIS } } }) as never} />
  );
}
