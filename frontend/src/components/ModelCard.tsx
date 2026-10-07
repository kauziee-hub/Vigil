// Model registry presentation for /api/intel/models (Claude 2). Every number is read from ModelInfo; the
// layout knows the common metric keys (precision / recall / F1 / ROC-AUC / PR-AUC / confusion / calibration bins /
// per-attack / leave-one-attack-out / old-protocol audit / global SHAP / rule table) and shows anything else raw
// under "training details", so nothing reported by the model is hidden or re-derived.
import type { ReactNode } from "react";
import type { ModelInfo } from "../api/types";
import { formatStamp, humanKey, pct } from "../lib/format";
import { Bar, Glyph, Pill } from "./ui";

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {});
const num = (v: unknown): number | null => (typeof v === "number" && !Number.isNaN(v) ? v : null);
const f3 = (v: unknown) => (num(v) === null ? "—" : num(v)!.toFixed(3));
const ATTACK_LABEL: Record<string, string> = {
  fan_in: "Fan-in", fan_out: "Fan-out", circular: "Circular ring", velocity_chain: "Velocity chain", cross_channel: "Cross-channel burst",
  shared_device: "Shared device", behavioural_drift: "Behavioural drift", volume_spike: "Early volume spike", smurfing: "Smurfing", dormant: "Dormant activation",
};
const FAMILY_LABEL: Record<string, string> = { random_forest: "Random Forest", gnn: "Graph attention network", rules: "Rule engine (points)", drift: "Behavioural drift", pattern_memory: "Pattern memory" };
const KNOWN = new Set(["label", "evaluated_on", "precision", "recall", "f1", "roc_auc", "pr_auc", "pr_auc_active_accounts", "confusion", "n", "positives",
  "prevalence", "flag_rate", "false_positives_by_persona", "threshold", "threshold_rule", "leave_one_attack_out", "old_protocol", "shap_global", "rules",
  "early_warning", "note", "architecture", "per_attack"]);

export function Synthetic() {
  return <span className="stamp-sv" title="Measured on synthetic, simulator-generated worlds — not real-bank accuracy">SYNTHETIC VALIDATION</span>;
}

/** All models side by side on the same held-out test worlds. */
export function ModelComparison({ models, onPick, picked }: { models: ModelInfo[]; onPick?: (id: string) => void; picked?: string }) {
  const cols: [string, string][] = [["precision", "Precision"], ["recall", "Recall"], ["f1", "F1"], ["roc_auc", "ROC-AUC"], ["pr_auc", "PR-AUC"], ["flag_rate", "Flag rate"]];
  return (
    <table className="dt compact">
      <thead><tr><th>Model</th><th>Version</th>{cols.map(([, l]) => <th key={l} className="num">{l}</th>)}<th className="num">FP (of negatives)</th><th>Output kind</th></tr></thead>
      <tbody>
        {models.map((m) => {
          const x = obj(m.metrics);
          const cm = obj(x.confusion);
          const neg = (num(cm.fp) ?? 0) + (num(cm.tn) ?? 0);
          return (
            <tr key={m.model_id} className={`${onPick ? "click" : ""} ${picked === m.model_id ? "sel" : ""}`} onClick={() => onPick?.(m.model_id)}>
              <td><span className="row tight"><Glyph family={m.family} /><span>{FAMILY_LABEL[m.family] ?? m.family}</span></span></td>
              <td className="mono xs">{m.version}</td>
              {cols.map(([k]) => (
                <td key={k} className="num">{num(x[k]) === null ? "—" : k === "flag_rate" ? pct(num(x[k]), 1) : (
                  <span className="row tight" style={{ justifyContent: "flex-end" }}><span style={{ width: 44 }}><Bar value={num(x[k])} /></span>{num(x[k])!.toFixed(3)}</span>)}</td>
              ))}
              <td className="num xs">{num(cm.fp) === null ? "—" : `${cm.fp} / ${neg.toLocaleString("en-IN")}`}</td>
              <td className="xs muted">{m.family === "rules" ? "point score" : m.family === "drift" ? "level" : m.family === "pattern_memory" ? "similarity" : "calibrated (synthetic worlds)"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function Confusion({ c }: { c: Obj }) {
  const tn = num(c.tn), fp = num(c.fp), fn = num(c.fn), tp = num(c.tp);
  if ([tn, fp, fn, tp].some((v) => v === null)) return null;
  return (
    <table className="cm">
      <tbody>
        <tr><td /><th>pred. normal</th><th>pred. mule</th></tr>
        <tr><th>actual normal</th><td>{tn!.toLocaleString("en-IN")}<span>TN</span></td><td className="bad">{fp}<span>FP</span></td></tr>
        <tr><th>actual mule</th><td className="bad">{fn}<span>FN</span></td><td>{tp}<span>TP</span></td></tr>
      </tbody>
    </table>
  );
}

function Reliability({ cal }: { cal: Obj }) {
  const series = (["raw", "calibrated"] as const).map((k) => ({ k, bins: (Array.isArray(obj(cal[k]).bins) ? obj(cal[k]).bins : []) as Obj[], o: obj(cal[k]) }))
    .filter((s) => s.bins.length);
  if (!series.length) return null;
  const S = 170, P = 22;
  const px = (v: number) => P + v * (S - P - 6), py = (v: number) => S - P - v * (S - P - 6);
  return (
    <div className="row top wrap" style={{ gap: 14 }}>
      <svg className="chart" viewBox={`0 0 ${S} ${S}`} style={{ width: S, height: S }} role="img" aria-label="Reliability diagram: mean predicted vs observed rate per bin">
        <rect x={P} y={6} width={S - P - 6} height={S - P - 6} fill="none" className="axis-l" />
        <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(1)} className="grid-l" strokeDasharray="3 3" />
        {series.map((s) => {
          const pts = s.bins.filter((b) => num(b.mean_predicted) !== null && num(b.observed_rate) !== null && (num(b.n) ?? 1) > 0);
          return (
            <g key={s.k}>
              <polyline fill="none" stroke={s.k === "calibrated" ? "var(--accent)" : "var(--ink-3)"} strokeWidth="1.5" strokeDasharray={s.k === "raw" ? "4 3" : undefined}
                        points={pts.map((b) => `${px(num(b.mean_predicted)!)},${py(num(b.observed_rate)!)}`).join(" ")} />
              {pts.map((b, i) => <circle key={i} cx={px(num(b.mean_predicted)!)} cy={py(num(b.observed_rate)!)} r="2.3" fill={s.k === "calibrated" ? "var(--accent)" : "var(--ink-3)"}><title>{`${s.k}: bin ${b.lo}–${b.hi} · n ${b.n} · predicted ${f3(b.mean_predicted)} · observed ${f3(b.observed_rate)}`}</title></circle>)}
            </g>
          );
        })}
        <text x={P} y={S - 6}>0</text><text x={S - 12} y={S - 6}>1</text><text x={4} y={14}>1</text>
      </svg>
      <div className="stack tight">
        <table className="dt compact" style={{ width: "auto" }}>
          <thead><tr><th /><th className="num">Brier</th><th className="num">ECE</th></tr></thead>
          <tbody>{series.map((s) => (
            <tr key={s.k}><td className="xs"><span className="row tight"><i className="sw" style={{ background: s.k === "calibrated" ? "var(--accent)" : "var(--ink-3)" }} />{s.k}</span></td>
              <td className="num">{f3(s.o.brier)}</td><td className="num">{f3(s.o.ece)}</td></tr>
          ))}</tbody>
        </table>
        <div className="xs muted" style={{ maxWidth: 260 }}>x = mean predicted · y = observed mule rate · diagonal = perfect calibration. {typeof cal.method === "string" && cal.method}</div>
      </div>
    </div>
  );
}

function AttackTable({ perAttack, loao }: { perAttack: Obj; loao: Obj }) {
  const keys = [...new Set([...Object.keys(perAttack), ...Object.keys(loao)])];
  if (!keys.length) return null;
  const hasLoao = Object.keys(loao).length > 0;
  return (
    <div className="tscroll">
      <table className="dt compact">
        <thead>
          <tr><th>Attack family</th><th className="num">Mules</th><th className="num">Detected</th><th style={{ width: "22%" }}>Recall</th><th className="num">PR-AUC</th>
            {hasLoao && <><th className="num" title="Recall when this attack family was in training">LOAO recall seen</th><th className="num" title="Recall when this family was held out of training entirely">unseen</th><th className="num">PR-AUC unseen</th></>}</tr>
        </thead>
        <tbody>
          {keys.map((k) => {
            const a = obj(perAttack[k]), l = obj(loao[k]);
            const drop = num(l.recall_seen) !== null && num(l.recall_unseen) !== null ? num(l.recall_unseen)! - num(l.recall_seen)! : null;
            return (
              <tr key={k}>
                <td>{ATTACK_LABEL[k] ?? humanKey(k)}</td>
                <td className="num">{num(a.mules) ?? "—"}</td><td className="num">{num(a.detected) ?? "—"}</td>
                <td>{num(a.recall) === null ? "—" : <span className="row tight"><span className="grow"><Bar value={num(a.recall)} /></span><span className="mono xs">{num(a.recall)!.toFixed(2)}</span></span>}</td>
                <td className="num">{f3(a.pr_auc_vs_negatives)}</td>
                {hasLoao && <>
                  <td className="num">{f3(l.recall_seen)}</td>
                  <td className="num" style={{ color: drop !== null && drop < -0.15 ? "var(--st-high)" : undefined }}>{f3(l.recall_unseen)}</td>
                  <td className="num">{f3(l.pr_auc_unseen)}</td>
                </>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function OldProtocol({ op, honest }: { op: Obj; honest: Obj }) {
  const rows = Object.entries(op).filter(([, v]) => v && typeof v === "object") as [string, Obj][];
  if (!rows.length) return null;
  const all: [string, Obj, boolean][] = [...rows.map(([k, v]) => [humanKey(k), v, false] as [string, Obj, boolean]), ["current model · honest split-by-world test", honest, true]];
  return (
    <div className="stack tight">
      <table className="dt compact">
        <thead><tr><th>Evaluation</th><th className="num">Precision</th><th className="num">Recall</th><th className="num">F1</th><th className="num">PR-AUC</th><th className="num">Flag rate</th></tr></thead>
        <tbody>{all.map(([label, v, cur]) => (
          <tr key={label} className={cur ? "sel" : ""}><td className="xs">{label}</td><td className="num">{f3(v.precision)}</td><td className="num">{f3(v.recall)}</td><td className="num">{f3(v.f1)}</td><td className="num">{f3(v.pr_auc)}</td><td className="num">{num(v.flag_rate) === null ? "—" : pct(num(v.flag_rate), 1)}</td></tr>
        ))}</tbody>
      </table>
      {typeof op.note === "string" && <div className="xs muted">{op.note}</div>}
    </div>
  );
}

function ShapGlobal({ sg }: { sg: Obj }) {
  const cats = Object.entries(obj(sg.by_category)).filter(([, v]) => num(v) !== null) as [string, number][];
  const feats = Object.entries(obj(sg.mean_abs_shap)).filter(([, v]) => num(v) !== null) as [string, number][];
  if (!cats.length && !feats.length) return null;
  const cmax = Math.max(1e-9, ...cats.map(([, v]) => v)), fmax = Math.max(1e-9, ...feats.map(([, v]) => v));
  return (
    <div className="grid cols-2 align-start">
      <div>
        <div className="up" style={{ marginBottom: 4 }}>By human-readable category</div>
        {cats.sort((a, b) => b[1] - a[1]).map(([k, v]) => <div key={k} className="barrow"><span className="lbl">{k}</span><Bar value={v} max={cmax} /><span className="val">{v.toFixed(3)}</span></div>)}
      </div>
      <div>
        <div className="up" style={{ marginBottom: 4 }}>Top features · mean |SHAP|</div>
        {feats.sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, v]) => <div key={k} className="barrow"><span className="lbl">{humanKey(k)}</span><Bar value={v} max={fmax} /><span className="val">{v.toFixed(3)}</span></div>)}
      </div>
      {num(sg.rows) !== null && <div className="xs muted span-all">Global attribution over {num(sg.rows)!.toLocaleString("en-IN")} test rows. SHAP explains the MODEL, not any operational decision.</div>}
    </div>
  );
}

function Personas({ p }: { p: Obj }) {
  const rows = Object.entries(p).map(([k, v]) => [k, obj(v)] as [string, Obj]).filter(([, v]) => num(v.of) !== null);
  if (!rows.length) return null;
  return (
    <table className="dt compact">
      <thead><tr><th>Persona (negatives)</th><th className="num">Wrongly flagged</th><th className="num">Rate</th></tr></thead>
      <tbody>{rows.map(([k, v]) => (
        <tr key={k}><td className="xs">{k}</td><td className="num">{num(v.flagged)} / {num(v.of)!.toLocaleString("en-IN")}</td><td className="num">{pct((num(v.flagged) ?? 0) / Math.max(1, num(v.of)!), 1)}</td></tr>
      ))}</tbody>
    </table>
  );
}

function Strip({ x }: { x: Obj }) {
  const items: [string, string, ReactNode][] = [
    ["precision", "Precision", f3(x.precision)], ["recall", "Recall", f3(x.recall)], ["f1", "F1", f3(x.f1)],
    ["roc_auc", "ROC-AUC", f3(x.roc_auc)], ["pr_auc", "PR-AUC", f3(x.pr_auc)],
    ["threshold", "Threshold", f3(x.threshold)], ["flag_rate", "Flag rate", num(x.flag_rate) === null ? "—" : pct(num(x.flag_rate), 1)],
    ["prevalence", "Prevalence", num(x.prevalence) === null ? "—" : `${pct(num(x.prevalence), 1)}`],
  ];
  return (
    <div className="mstrip dense">
      {items.filter(([k]) => x[k] !== undefined).map(([k, l, v]) => <div key={k} className="m"><div className="k">{l}</div><div className="v">{v}</div></div>)}
      {num(x.n) !== null && <div className="m"><div className="k">Test accounts</div><div className="v">{num(x.n)!.toLocaleString("en-IN")}</div><div className="d">{num(x.positives) ?? "—"} mules</div></div>}
    </div>
  );
}

function Sect({ title, tag, children }: { title: ReactNode; tag?: ReactNode; children: ReactNode }) {
  return <div className="sect"><div className="sect-t">{title}{tag && <span style={{ marginLeft: "auto" }}>{tag}</span>}</div>{children}</div>;
}

export function ModelCard({ m }: { m: ModelInfo }) {
  const x = obj(m.metrics);
  const cal = obj(m.calibration);
  const ew = obj(x.early_warning);
  const rules = Array.isArray(x.rules) ? (x.rules as Obj[]) : [];
  const extra = Object.entries(x).filter(([k]) => !KNOWN.has(k));
  return (
    <section className="panel">
      <header className="panel-h">
        <Glyph family={m.family} />
        <span className="t">{FAMILY_LABEL[m.family] ?? m.family}</span>
        <span className="mono xs dim">{m.model_id} · {m.version}</span>
        <div className="act"><Synthetic /><Pill status={m.status === "active" ? "normal" : "unknown"}>{m.status}</Pill></div>
      </header>
      <div className="sect">
        <div className="notice info sm" style={{ marginBottom: 8 }}><b>Operational use:</b> {m.operational_use || "corroborating evidence only"}</div>
        <dl className="kv c4">
          <dt>Evaluated on</dt><dd>{String(x.evaluated_on ?? "—")}</dd>
          <dt>Trained</dt><dd className="mono">{m.trained_at ? formatStamp(m.trained_at) : "—"} · seed {m.seed ?? "—"}</dd>
          <dt>Split</dt><dd>{m.split}</dd>
          <dt>Data</dt><dd>{m.data}</dd>
          {typeof x.threshold_rule === "string" && <><dt>Threshold rule</dt><dd>{x.threshold_rule}</dd></>}
          {typeof x.architecture === "string" && <><dt>Architecture</dt><dd>{x.architecture}</dd></>}
        </dl>
        {typeof x.note === "string" && <div className="xs muted" style={{ marginTop: 6 }}>{x.note}</div>}
      </div>
      <Sect title="Held-out test performance" tag={typeof x.label === "string" ? <span className="xs dim">{x.label}</span> : undefined}><Strip x={x} /></Sect>
      <div className="grid cols-2 align-start" style={{ gap: 0 }}>
        <Sect title="Confusion matrix">{Object.keys(obj(x.confusion)).length ? <Confusion c={obj(x.confusion)} /> : <span className="xs muted">not reported</span>}</Sect>
        <Sect title="Calibration">{Object.keys(cal).length ? <Reliability cal={cal} /> : <span className="xs muted">Not applicable — {m.family === "rules" ? "a point score" : m.family === "drift" ? "a level" : "a similarity"}, not a probability.</span>}</Sect>
      </div>
      <Sect title="Per-attack detection · leave-one-attack-out generalisation" tag={<span className="xs dim">orange = recall falls &gt; 0.15 when the family is unseen in training</span>}>
        <AttackTable perAttack={obj(m.per_attack)} loao={obj(x.leave_one_attack_out)} />
      </Sect>
      {Object.keys(obj(x.old_protocol)).length > 0 && <Sect title="Leakage audit · old protocol vs honest split"><OldProtocol op={obj(x.old_protocol)} honest={x} /></Sect>}
      {Object.keys(obj(x.shap_global)).length > 0 && <Sect title="Global SHAP · explains the MODEL"><ShapGlobal sg={obj(x.shap_global)} /></Sect>}
      {rules.length > 0 && (
        <Sect title={`Rules · flag at ≥ ${num(x.flag_points) ?? "—"} points`}>
          <table className="dt compact">
            <thead><tr><th>Rule</th><th>Label</th><th className="num">Points</th><th>Previous (v1) threshold</th></tr></thead>
            <tbody>{rules.map((r) => <tr key={String(r.rule_id)}><td className="mono xs">{String(r.rule_id)}</td><td className="xs">{String(r.label)}</td><td className="num">{String(r.points)}</td><td className="xs muted mono">{String(r.old_threshold ?? "—")}</td></tr>)}</tbody>
          </table>
        </Sect>
      )}
      {Object.keys(ew).length > 0 && (
        <Sect title={`Early warning · ${String(ew.version ?? "")}`}>
          <Strip x={ew} />
          <div style={{ marginTop: 8 }}><AttackTable perAttack={obj(ew.per_attack)} loao={{}} /></div>
        </Sect>
      )}
      {Object.keys(obj(x.false_positives_by_persona)).length > 0 && <Sect title="False positives by persona"><Personas p={obj(x.false_positives_by_persona)} /></Sect>}
      {extra.length > 0 && (
        <details className="sect">
          <summary className="sect-t" style={{ cursor: "pointer" }}>Training details · {extra.map(([k]) => humanKey(k)).join(" · ")}</summary>
          <div className="stack tight">
            {extra.map(([k, v]) => (
              <div key={k}><div className="up">{humanKey(k)}</div>
                {typeof v === "string" || typeof v === "number" ? <div className="md mono">{String(v)}</div> : <pre className="raw" style={{ maxHeight: 220 }}>{JSON.stringify(v, null, 1)}</pre>}
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}
