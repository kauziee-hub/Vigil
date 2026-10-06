// Detection-intelligence panels (Claude 2's /api/intel/*). These explain the MODELS and the detector
// families — they are corroborating evidence and never set the operational tier. Every panel renders an
// honest "not yet available" state when the endpoint is not served; nothing is estimated client-side.
import type { ReactNode } from "react";
import { api } from "../api/client";
import type {
  AccountIntel, DetectorConsensus, DetectorResult, DriftReport, ModelInfo, PatternMatch, RoleAssessment, ShapExplanation,
} from "../api/types";
import { evValue, formatStamp, humanKey, pct } from "../lib/format";
import { ROLE_SHAPE, SHAPE_ICON, roleKey } from "../lib/graphStyle";
import { useLoad } from "../lib/hooks";
import { FAMILY, KIND_LABEL, ROLE_LABEL, levelStatus, scoreStatus, type Status } from "../lib/status";
import { Bar, Glyph, Loading, Pill, Unavailable } from "./ui";

const UNIT_KINDS = new Set(["score", "probability_uncalibrated", "probability_calibrated", "similarity"]);

export function detectorStatus(d: DetectorResult): Status {
  if (d.status !== "ok") return "unknown";
  if (d.kind === "level") return levelStatus(d.display);
  if (d.value !== null && UNIT_KINDS.has(d.kind)) return d.flagged ? scoreStatus(Math.max(d.value, 0.5)) : scoreStatus(Math.min(d.value, 0.29));
  return d.flagged ? "high" : "normal";
}

export function DetectorTable({ detectors, compact }: { detectors: DetectorResult[]; compact?: boolean }) {
  return (
    <table className="dt compact">
      <thead>
        <tr><th>Family</th><th style={{ width: compact ? "22%" : "26%" }}>Value</th><th>Kind</th><th>Flag</th>{!compact && <th>Version · observed</th>}</tr>
      </thead>
      <tbody>
        {detectors.map((d) => {
          const st = detectorStatus(d);
          return (
            <tr key={`${d.family}-${d.label}`}>
              <td><span className="row tight"><Glyph family={d.family} /><span>{d.label || FAMILY[d.family]?.label}</span></span></td>
              <td>
                {d.status !== "ok" ? <span className="dim">{d.status.replace("_", " ")}</span> : (
                  <span className="row tight">
                    {d.value !== null && UNIT_KINDS.has(d.kind) && <span className="grow"><Bar value={d.value} status={st} /></span>}
                    <span className="mono sm" style={{ color: `var(--st-${st})` }}>{d.display}</span>
                  </span>
                )}
              </td>
              <td className="xs muted">{KIND_LABEL[d.kind] ?? d.kind}</td>
              <td>{d.status === "ok" ? (d.flagged ? <Pill status={st === "normal" ? "watch" : st}>flagged</Pill> : <span className="xs dim">no</span>) : <span className="xs dim">—</span>}</td>
              {!compact && <td className="xs dim mono">{d.version} · {formatStamp(d.observed_at)}</td>}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function ConsensusStrip({ consensus, detectors }: { consensus: DetectorConsensus; detectors: DetectorResult[] }) {
  const st: Status = consensus.agreement === "strong" ? "critical" : consensus.agreement === "moderate" ? "high"
    : consensus.agreement === "weak" ? "watch" : "normal";
  return (
    <div className="consensus">
      <div className="spread">
        <div><span className="big mono">{consensus.families_flagging}</span><span className="muted"> of {consensus.families_evaluated} independent signal families flag this account</span></div>
        <Pill status={st}>{consensus.agreement} agreement</Pill>
      </div>
      <div className="fam-row">
        {detectors.map((d) => (
          <span key={`${d.family}-${d.label}`} className={`fam ${d.status !== "ok" ? "na" : d.flagged ? "on" : ""}`}
                title={`${d.label}: ${d.status === "ok" ? d.display : d.status}`}
                style={d.flagged && d.status === "ok" ? { borderColor: `var(--st-${detectorStatus(d)})`, color: `var(--st-${detectorStatus(d)})` } : undefined}>
            {FAMILY[d.family]?.glyph ?? d.family}
          </span>
        ))}
      </div>
      <div className="xs muted">{consensus.summary}</div>
    </div>
  );
}

export function ShapPanel({ shap }: { shap: ShapExplanation }) {
  const all = [...shap.top_positive, ...shap.top_negative];
  const max = Math.max(1e-9, ...all.map((c) => Math.abs(c.contribution)));
  const cats = Object.entries(shap.categories).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const cmax = Math.max(1e-9, ...cats.map(([, v]) => Math.abs(v)));
  return (
    <div className="stack">
      <div className="row wrap xs muted">
        <span>raw model prediction <b className="mono" style={{ color: "var(--ink)" }}>{shap.prediction.toFixed(3)}</b> ({KIND_LABEL[shap.prediction_kind] ?? shap.prediction_kind})</span>
        <span>· base value <span className="mono">{shap.base_value.toFixed(3)}</span></span>
        <span>· model <span className="mono">{shap.model_version}</span></span>
      </div>
      <div className="shap">
        {shap.top_positive.map((c) => (
          <div key={`p-${c.feature}`} className="shap-r">
            <span className="f" title={c.feature}>{humanKey(c.feature)} <span className="dim mono">= {evValue(c.feature, c.value)}</span></span>
            <span className="neg-h" />
            <span className="pos-h"><i style={{ width: `${(Math.abs(c.contribution) / max) * 100}%` }} /></span>
            <span className="v mono">+{c.contribution.toFixed(3)}</span>
            <span className="c xs dim">{c.category}</span>
          </div>
        ))}
        {shap.top_negative.map((c) => (
          <div key={`n-${c.feature}`} className="shap-r">
            <span className="f" title={c.feature}>{humanKey(c.feature)} <span className="dim mono">= {evValue(c.feature, c.value)}</span></span>
            <span className="neg-h"><i style={{ width: `${(Math.abs(c.contribution) / max) * 100}%` }} /></span>
            <span className="pos-h" />
            <span className="v mono">{c.contribution.toFixed(3)}</span>
            <span className="c xs dim">{c.category}</span>
          </div>
        ))}
      </div>
      <div className="xs dim">left = pushes the model's output down · right = pushes it up</div>
      {cats.length > 0 && (
        <div>
          <div className="up" style={{ marginBottom: 4 }}>By human-readable category</div>
          {cats.map(([k, v]) => (
            <div key={k} className="barrow">
              <span className="lbl">{k}</span>
              <Bar value={Math.abs(v)} max={cmax} status={v > 0 ? "high" : undefined} />
              <span className="val">{v > 0 ? "+" : ""}{v.toFixed(3)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function DriftPanel({ drift }: { drift: DriftReport }) {
  return (
    <div className="stack">
      <div className="spread">
        <span className="xs muted">baseline <b className="ink2">{drift.baseline_window}</b> → current <b className="ink2">{drift.current_window}</b></span>
        <span className="row tight"><span className="mono sm">drift {drift.drift_score.toFixed(2)}</span><Pill status={levelStatus(drift.level)}>{drift.level}</Pill></span>
      </div>
      <table className="dt compact">
        <thead><tr><th>Feature</th><th className="num">Baseline</th><th /><th className="num">Current</th><th className="num">Change</th></tr></thead>
        <tbody>
          {drift.features.map((f) => (
            <tr key={f.feature}>
              <td>{humanKey(f.feature)}</td>
              <td className="num">{evValue(f.feature, f.baseline)}</td>
              <td className="center dim">→</td>
              <td className="num"><b>{evValue(f.feature, f.current)}</b></td>
              <td className="num" style={{ color: Math.abs(f.change) >= 1 ? "var(--st-high)" : undefined }}>{f.change > 0 ? "+" : ""}{Math.abs(f.change) < 10 ? f.change.toFixed(2) : f.change.toFixed(0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PatternPanel({ patterns }: { patterns: PatternMatch[] }) {
  if (!patterns.length) return <div className="empty">No known signature resembles this account's current structure.</div>;
  return (
    <div className="stack">
      {[...patterns].sort((a, b) => b.similarity - a.similarity).map((p) => (
        <div key={p.signature_id} className="barrow" title={`${p.description}${p.note ? ` — ${p.note}` : ""}`}>
          <span className="lbl">{p.name}</span>
          <Bar value={p.similarity} status={p.similarity >= 0.75 ? "high" : p.similarity >= 0.5 ? "watch" : undefined} />
          <span className="val">{pct(p.similarity)}</span>
        </div>
      ))}
      <div className="xs muted">Structural similarity to known signatures — not criminal attribution.</div>
    </div>
  );
}

export function RoleIcon({ role, size = 14 }: { role: string | null | undefined; size?: number }) {
  const rk = roleKey(role);
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden style={{ flex: "none" }}>
      <path d={SHAPE_ICON[ROLE_SHAPE[rk].shape]} fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

export function RolePanel({ role }: { role: RoleAssessment }) {
  const ev = Object.entries(role.evidence ?? {}).filter(([, v]) => v !== null && typeof v !== "object");
  return (
    <div className="stack tight">
      <div className="row"><RoleIcon role={role.role} size={18} /><b style={{ fontSize: 14 }}>{ROLE_LABEL[role.role] ?? role.role}</b></div>
      <div className="md ink2">{role.reason}</div>
      {ev.length > 0 && <div className="ev">{ev.map(([k, v]) => <span key={k} className="ev-kv">{humanKey(k)} <b>{evValue(k, v)}</b></span>)}</div>}
    </div>
  );
}

function Sub({ title, tag, children }: { title: ReactNode; tag?: ReactNode; children: ReactNode }) {
  return (
    <div className="sect">
      <div className="sect-t">{title}{tag && <span style={{ marginLeft: "auto" }}>{tag}</span>}</div>
      {children}
    </div>
  );
}

/** Full model-evidence block for one account. */
export function AccountIntelBlock({ accountId, compact }: { accountId: string; compact?: boolean }) {
  const intel = useLoad<AccountIntel>(() => api.intelAccount(accountId), [accountId]);
  if (intel.loading && !intel.data) return <Loading text="Loading detector evidence" />;
  if (intel.unavailable) {
    return (
      <div className="sect">
        <Unavailable what="Detection intelligence" endpoint="/api/intel/accounts/{id}">
          Detector consensus (Rules · RF · GNN · drift · early warning · pattern memory · TrailScore · context · external), SHAP, behavioural drift,
          pattern similarity and role analysis appear here once the intelligence layer is merged.
        </Unavailable>
      </div>
    );
  }
  if (intel.error) return <div className="sect"><div className="notice err">{intel.error.message}</div></div>;
  const x = intel.data!;
  return (
    <>
      <Sub title="Detector consensus" tag={<span className="xs dim mono">graph v{x.graph_version} · {formatStamp(x.as_of)}</span>}>
        <ConsensusStrip consensus={x.consensus} detectors={x.detectors} />
        <div style={{ marginTop: 8 }}><DetectorTable detectors={x.detectors} compact={compact} /></div>
      </Sub>
      <Sub title={<>SHAP · explains the MODEL</>} tag={<span className="xs dim">not the operational decision</span>}>
        {x.shap ? <ShapPanel shap={x.shap} /> : <div className="xs muted">No SHAP explanation: the RF model was not run for this account.</div>}
      </Sub>
      <Sub title="Behavioural drift">
        {x.drift ? <DriftPanel drift={x.drift} /> : <div className="xs muted">Not enough history to establish a baseline.</div>}
      </Sub>
      <Sub title="Pattern memory" tag={<span className="xs dim">structural similarity, not attribution</span>}>
        <PatternPanel patterns={x.patterns} />
      </Sub>
      <Sub title="Role"><RolePanel role={x.role} /></Sub>
    </>
  );
}

// ── model registry / validation metrics (generic, since metric schemas are model-specific) ──

function isNum(v: unknown): v is number { return typeof v === "number" && !Number.isNaN(v); }

function ConfusionMatrix({ m }: { m: unknown }) {
  let tn: number | null = null, fp: number | null = null, fn: number | null = null, tp: number | null = null;
  if (Array.isArray(m) && m.length === 2 && Array.isArray(m[0]) && Array.isArray(m[1])) {
    [[tn, fp], [fn, tp]] = m as number[][];
  } else if (m && typeof m === "object") {
    const o = m as Record<string, number>;
    tn = o.tn ?? null; fp = o.fp ?? null; fn = o.fn ?? null; tp = o.tp ?? null;
  }
  if ([tn, fp, fn, tp].some((v) => v === null)) return <pre className="raw">{JSON.stringify(m)}</pre>;
  return (
    <table className="cm">
      <tbody>
        <tr><td /><th>pred. normal</th><th>pred. mule</th></tr>
        <tr><th>actual normal</th><td>{tn}<span>TN</span></td><td className="bad">{fp}<span>FP</span></td></tr>
        <tr><th>actual mule</th><td className="bad">{fn}<span>FN</span></td><td>{tp}<span>TP</span></td></tr>
      </tbody>
    </table>
  );
}

const HEADLINE = ["precision", "recall", "f1", "roc_auc", "pr_auc", "brier", "ece", "accuracy", "support", "n_test", "threshold"];

export function MetricsView({ metrics }: { metrics: Record<string, unknown> }) {
  const entries = Object.entries(metrics);
  const head = HEADLINE.map((k) => [k, metrics[k]] as const).filter(([, v]) => isNum(v));
  const rest = entries.filter(([k, v]) => !HEADLINE.includes(k) || !isNum(v));
  return (
    <div className="stack">
      {head.length > 0 && (
        <div className="mstrip">
          {head.map(([k, v]) => (
            <div key={k} className="m"><div className="k">{k.replace(/_/g, "-").toUpperCase()}</div><div className="v">{Number.isInteger(v) ? String(v) : (v as number).toFixed(3)}</div></div>
          ))}
        </div>
      )}
      {rest.map(([k, v]) => <MetricEntry key={k} k={k} v={v} />)}
    </div>
  );
}

function MetricEntry({ k, v }: { k: string; v: unknown }) {
  if (/confusion/i.test(k)) return <div><div className="up">{humanKey(k)}</div><ConfusionMatrix m={v} /></div>;
  if (isNum(v) || typeof v === "string" || typeof v === "boolean") {
    return <div className="kv"><dt>{humanKey(k)}</dt><dd className="mono">{isNum(v) ? (Number.isInteger(v) ? v : v.toFixed(3)) : String(v)}</dd></div>;
  }
  if (v && typeof v === "object" && !Array.isArray(v)) return <NestedTable title={humanKey(k)} data={v as Record<string, unknown>} />;
  return <div><div className="up">{humanKey(k)}</div><pre className="raw">{JSON.stringify(v, null, 1)}</pre></div>;
}

/** Record<row, number | Record<col, number>> → dense table (per-attack, leave-one-attack-out, calibration bins…). */
export function NestedTable({ title, data }: { title?: string; data: Record<string, unknown> }) {
  const rows = Object.entries(data);
  if (!rows.length) return null;
  const objRows = rows.filter(([, v]) => v && typeof v === "object" && !Array.isArray(v));
  const cols = [...new Set(objRows.flatMap(([, v]) => Object.keys(v as object)))];
  const flat = rows.every(([, v]) => isNum(v) || typeof v === "string" || v === null);
  return (
    <div>
      {title && <div className="up" style={{ marginBottom: 4 }}>{title}</div>}
      <div className="tscroll">
        <table className="dt compact">
          {!flat && <thead><tr><th /> {cols.map((c) => <th key={c} className="num">{humanKey(c)}</th>)}</tr></thead>}
          <tbody>
            {rows.map(([r, v]) => (
              <tr key={r}>
                <td>{humanKey(r)}</td>
                {flat ? (
                  <td className="num">{isNum(v) ? (v <= 1 && v >= 0 && !Number.isInteger(v) ? (
                    <span className="row tight" style={{ justifyContent: "flex-end" }}><span style={{ width: 80 }}><Bar value={v} /></span>{v.toFixed(3)}</span>
                  ) : v) : String(v ?? "—")}</td>
                ) : cols.map((c) => {
                  const cell = (v as Record<string, unknown> | null)?.[c];
                  return <td key={c} className="num">{isNum(cell) ? (Number.isInteger(cell) ? cell : cell.toFixed(3)) : cell === undefined || cell === null ? "—" : typeof cell === "object" ? JSON.stringify(cell) : String(cell)}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ModelCard({ m }: { m: ModelInfo }) {
  return (
    <div className="panel">
      <header className="panel-h">
        <Glyph family={m.family === "rules" ? "rules" : m.family} />
        <span className="t">{m.model_id}</span>
        <span className="mono xs dim">{m.version}</span>
        <div className="act">
          <span className="banner-val" style={{ padding: "2px 6px" }}><span className="stamp">SYNTHETIC VALIDATION</span></span>
          <Pill status={m.status === "active" ? "normal" : "unknown"}>{m.status}</Pill>
        </div>
      </header>
      <div className="panel-b stack">
        <div className="kv c4">
          <dt>Trained</dt><dd className="mono">{m.trained_at ? formatStamp(m.trained_at) : "—"}</dd>
          <dt>Seed</dt><dd className="mono">{m.seed ?? "—"}</dd>
          <dt>Data</dt><dd>{m.data}</dd>
          <dt>Split</dt><dd>{m.split}</dd>
        </div>
        <div className="notice info sm"><b>Operational use:</b> {m.operational_use || "corroborating evidence only"}</div>
        {Object.keys(m.metrics).length > 0 ? <MetricsView metrics={m.metrics} /> : <div className="xs muted">No metrics recorded.</div>}
        {Object.keys(m.per_attack).length > 0 && <NestedTable title="Per-attack detection" data={m.per_attack} />}
        {Object.keys(m.calibration).length > 0 && <CalibrationView cal={m.calibration} />}
      </div>
    </div>
  );
}

/** Reliability diagram if bins are present; otherwise a table. */
function CalibrationView({ cal }: { cal: Record<string, unknown> }) {
  const bins = (cal.bins ?? cal.reliability ?? cal.reliability_bins) as unknown;
  const pts: { x: number; y: number; n?: number }[] = [];
  if (Array.isArray(bins)) {
    for (const b of bins) {
      if (Array.isArray(b) && b.length >= 2 && isNum(b[0]) && isNum(b[1])) pts.push({ x: b[0], y: b[1], n: isNum(b[2]) ? b[2] : undefined });
      else if (b && typeof b === "object") {
        const o = b as Record<string, unknown>;
        const x = o.mean_predicted ?? o.predicted ?? o.mean_pred ?? o.confidence ?? o.x;
        const y = o.fraction_positive ?? o.observed ?? o.frac_pos ?? o.accuracy ?? o.y;
        if (isNum(x) && isNum(y)) pts.push({ x, y, n: isNum(o.count) ? o.count : undefined });
      }
    }
  }
  const scalars = Object.entries(cal).filter(([, v]) => isNum(v) || typeof v === "string");
  return (
    <div>
      <div className="up" style={{ marginBottom: 4 }}>Calibration</div>
      <div className="row top wrap" style={{ gap: 16 }}>
        {pts.length > 1 && (
          <svg className="chart" viewBox="0 0 160 160" style={{ width: 160, height: 160 }}>
            <rect x="20" y="10" width="130" height="130" fill="none" className="axis-l" />
            <line x1="20" y1="140" x2="150" y2="10" className="grid-l" strokeDasharray="3 3" />
            <polyline fill="none" stroke="var(--accent)" strokeWidth="1.5"
                      points={pts.map((p) => `${20 + p.x * 130},${140 - p.y * 130}`).join(" ")} />
            {pts.map((p, i) => <circle key={i} cx={20 + p.x * 130} cy={140 - p.y * 130} r="2.4" fill="var(--accent)" />)}
            <text x="20" y="154">0</text><text x="140" y="154">1</text><text x="2" y="14">1</text>
          </svg>
        )}
        <div className="kv">{scalars.map(([k, v]) => <div key={k} style={{ display: "contents" }}><dt>{humanKey(k)}</dt><dd className="mono">{isNum(v) ? v.toFixed(3) : String(v)}</dd></div>)}</div>
      </div>
      {pts.length <= 1 && !scalars.length && <pre className="raw">{JSON.stringify(cal, null, 1)}</pre>}
    </div>
  );
}
