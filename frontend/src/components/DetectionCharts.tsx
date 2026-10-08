// Detection & Models charts (chart.js, loaded on demand): accounts flagged per family (live), held-out metrics per model
// and per-attack recall (both SYNTHETIC VALIDATION). Every value is read from /api/intel/overview or /api/intel/models.
import type { DetectorFamily, IntelOverview, ModelInfo } from "../api/types";
import { FAMILY } from "../lib/status";
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
const GRID = { color: "rgba(160,170,185,0.08)" };

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
