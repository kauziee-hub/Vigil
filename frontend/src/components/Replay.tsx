// Decision Replay, Risk Evolution, Counterfactual ladder, Evidence provenance.
// All deterministic outputs of the policy engine (Claude 1's /replay, /counterfactuals, /record,
// /risk-timeline). Nothing here is interpolated: the chart only connects points the API returned.
import { useEffect, useMemo, useState } from "react";
import type { Counterfactual, DecisionRecord, Dimension, PolicyView, ReplayFrame, RiskPoint } from "../api/types";
import { DIM_LABEL, evValue, formatStamp, formatTime, freshness, humanKey } from "../lib/format";
import { DIM_GLYPH, TIER_SHORT, tierStatus } from "../lib/status";
import { Bar, Glyph, Pill, Sim, TierPill } from "./ui";

const DIMS: Dimension[] = ["external", "network", "sequence", "behaviour", "context"];
const KIND_LABEL: Record<ReplayFrame["kind"], string> = { event: "event", evaluation: "evaluation", decision: "decision", action: "action", outcome: "outcome" };

// ── Decision Replay ─────────────────────────────────────────────────────────
export function DecisionReplayView({ frames, ladder, note }: { frames: ReplayFrame[]; ladder?: PolicyView["ladder"]; note?: string }) {
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => { setI(0); setPlaying(false); }, [frames]);
  useEffect(() => {
    if (!playing) return;
    if (i >= frames.length - 1) { setPlaying(false); return; }
    const t = window.setTimeout(() => setI((x) => Math.min(frames.length - 1, x + 1)), 1100);
    return () => window.clearTimeout(t);
  }, [playing, i, frames.length]);
  if (!frames.length) return <div className="empty">No frames recorded for this decision.</div>;
  const f = frames[i];
  const prev = i > 0 ? frames[i - 1] : null;
  const tierChanged = prev && prev.tier !== f.tier;

  return (
    <div className="replay">
      <div className="replay-ctl">
        <button className="btn sm primary" onClick={() => { if (i >= frames.length - 1) setI(0); setPlaying(!playing); }}>{playing ? "❚❚ Pause" : i >= frames.length - 1 ? "↺ Replay" : "▶ Play"}</button>
        <button className="btn sm ghost" onClick={() => { setPlaying(false); setI(Math.max(0, i - 1)); }} aria-label="Previous frame">‹ prev</button>
        <button className="btn sm ghost" onClick={() => { setPlaying(false); setI(Math.min(frames.length - 1, i + 1)); }} aria-label="Next frame">next ›</button>
        <input type="range" min={0} max={frames.length - 1} value={i} onChange={(e) => { setPlaying(false); setI(Number(e.target.value)); }} aria-label="Replay frame" />
        <span className="mono xs muted">frame {i + 1}/{frames.length} · {formatTime(f.ts)}</span>
      </div>
      <div className="replay-body">
        <div className="tl replay-tl">
          {frames.map((fr, k) => {
            const cls = k > i ? "future" : k === i ? "now" : "";
            const mark = fr.kind === "decision" ? (fr.tier >= 4 ? "crit" : fr.tier >= 2 ? "hot" : "ok")
              : fr.kind === "action" ? "held" : fr.signals_added.length ? "hot" : "";
            const sim = /SIMULATED/i.test(fr.label) || /SIMULATED/i.test(fr.detail);
            return (
              <div key={fr.index} className={`tl-i ${cls} ${mark} ${sim ? "sim-i" : ""}`} onClick={() => { setPlaying(false); setI(k); }} style={{ cursor: "pointer" }}>
                <div className="t">{formatTime(fr.ts)} · {KIND_LABEL[fr.kind]} · score {fr.final_score.toFixed(2)} · T{fr.tier}</div>
                <div className="row tight wrap"><span>{fr.label}</span>{sim && <Sim />}</div>
                {k === i && fr.detail && <div className="xs muted">{fr.detail}</div>}
                {k === i && fr.signals_added.length > 0 && <div className="ev">{fr.signals_added.map((s) => <span key={s} className="ev-kv mono">+ {s}</span>)}</div>}
              </div>
            );
          })}
        </div>
        <div className="replay-state">
          <div className="spread">
            <div>
              <div className="up">Final score at this frame</div>
              <div className="big-score" style={{ color: `var(--st-${tierStatus(f.tier)})` }}>{f.final_score.toFixed(3)}</div>
            </div>
            <div className="stack tight" style={{ alignItems: "flex-end" }}>
              <TierPill tier={f.tier} full lg />
              {tierChanged && <span className="xs" style={{ color: `var(--st-${tierStatus(f.tier)})` }}>tier {prev!.tier} → {f.tier}</span>}
            </div>
          </div>
          <div className="bar thick" style={{ margin: "8px 0 2px" }}>
            <i style={{ width: `${Math.min(1, f.final_score) * 100}%`, background: `var(--st-${tierStatus(f.tier)})`, transition: "width 0.35s ease" }} />
            {(ladder ?? []).filter((l) => l.below < 1).map((l) => <span key={l.tier} className="tick" style={{ left: `${l.below * 100}%` }} title={`T${l.tier} below ${l.below}`} />)}
          </div>
          <div className="spread xs dim mono"><span>0</span><span>ticks = policy ladder thresholds</span><span>1</span></div>
          <div className="subs" style={{ marginTop: 10 }}>
            <div className="up">Dimension subscores</div>
            {DIMS.map((d) => {
              const v = f.subscores[d] ?? 0;
              const pv = prev?.subscores[d] ?? 0;
              return (
                <div key={d} className={`barrow ${v !== pv ? "changed" : ""}`}>
                  <span className="lbl"><Glyph code={DIM_GLYPH[d]} /> {DIM_LABEL[d]}</span>
                  <Bar value={v} />
                  <span className="val">{v.toFixed(2)}{v !== pv && <span className="delta"> {v > pv ? "▲" : "▼"}</span>}</span>
                </div>
              );
            })}
          </div>
          <Spark frames={frames} i={i} onPick={(k) => { setPlaying(false); setI(k); }} />
        </div>
      </div>
      {note && <div className="panel-f">{note}</div>}
    </div>
  );
}

function Spark({ frames, i, onPick }: { frames: ReplayFrame[]; i: number; onPick: (k: number) => void }) {
  const W = 300, H = 54, n = frames.length;
  const x = (k: number) => 6 + (k / Math.max(1, n - 1)) * (W - 12);
  const y = (v: number) => H - 6 - Math.min(1, v) * (H - 12);
  const path = frames.map((f, k) => `${k === 0 ? "M" : "H"}${x(k).toFixed(1)} V${y(f.final_score).toFixed(1)}`).join(" ");
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} style={{ marginTop: 10, height: H }} role="img" aria-label="Final score by frame">
      <line x1="6" x2={W - 6} y1={y(0)} y2={y(0)} className="axis-l" />
      <path d={path} fill="none" stroke="var(--ink-3)" strokeWidth="1.3" />
      {frames.map((f, k) => (
        <circle key={k} cx={x(k)} cy={y(f.final_score)} r={k === i ? 4 : 2.4} onClick={() => onPick(k)} style={{ cursor: "pointer" }}
                fill={k <= i ? `var(--st-${tierStatus(f.tier)})` : "var(--surface-3)"} stroke={k === i ? "var(--ink)" : "none"} />
      ))}
    </svg>
  );
}

// ── Risk evolution ──────────────────────────────────────────────────────────
/** Short "why" for an on-chart marker label. */
function shortWhy(p: RiskPoint): string {
  const l = p.label.replace(/\s*\(SIMULATED\)/i, "").replace(/ — .*$/, "").replace(/transfer attempted → .*/, "transfer attempted");
  return l.length > 30 ? `${l.slice(0, 29)}…` : l;
}

/**
 * Step chart of the account's risk over its evaluation events (ordinal x-axis: events in order, clock time printed
 * under each marker). Each marker where the score moved carries its WHY on the chart; the table below gives the full
 * reason codes. Only points returned by /risk-timeline are drawn — nothing is interpolated.
 */
export function RiskEvolution({ points, ladder, height = 250, decisionId, onPickDecision }: {
  points: RiskPoint[]; ladder?: PolicyView["ladder"]; height?: number; decisionId?: string;
  onPickDecision?: (id: string) => void;
}) {
  const W = 900, H = height, L = 40, R = 118, T = 44, B = 34;
  const n = points.length;
  const pts = useMemo(() => points.map((p, k) => ({ ...p, k })), [points]);
  const decisions = useMemo(() => [...new Set(points.map((p) => p.decision_id).filter(Boolean))] as string[], [points]);
  if (!n) return <div className="empty">No risk events recorded for this account in the evaluation window.</div>;
  const x = (k: number) => L + (n === 1 ? (W - L - R) / 2 : (k / (n - 1)) * (W - L - R));
  const y = (v: number) => T + (1 - Math.min(1, Math.max(0, v))) * (H - T - B);
  const bands = (ladder ?? []).map((l, idx, arr) => ({ tier: l.tier, from: idx === 0 ? 0 : arr[idx - 1].below, to: Math.min(1, l.below) }));
  const path = pts.map((p, k) => (k === 0 ? `M${x(k)},${y(p.score)}` : `H${x(k)} V${y(p.score)}`)).join(" ");
  // WHY labels only where the score (or tier) moved — staggered on three rows so neighbours never collide.
  const moved = pts.filter((p, k) => k === 0 || p.score !== pts[k - 1].score || p.tier !== pts[k - 1].tier);
  const spacing = n > 1 ? (W - L - R) / (n - 1) : W;
  const multi = decisions.length > 1;
  return (
    <div className="stack">
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Risk score over time; each marker labelled with why it changed">
        {bands.map((b) => (
          <g key={b.tier}>
            <rect x={L} width={W - L - R} y={y(b.to)} height={Math.max(0, y(b.from) - y(b.to))} fill={`var(--st-${tierStatus(b.tier)}-bg)`} opacity={0.6} />
            <text x={W - R + 6} y={(y(b.to) + y(b.from)) / 2 + 3}>{TIER_SHORT[b.tier]?.split(" · ")[0]} · {TIER_SHORT[b.tier]?.split(" · ")[1]}</text>
          </g>
        ))}
        {[0, 0.25, 0.5, 0.75, 1].map((v) => (
          <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="grid-l" /><text x={L - 6} y={y(v) + 3} textAnchor="end">{v.toFixed(2)}</text></g>
        ))}
        <path d={path} fill="none" stroke="var(--ink)" strokeWidth="1.6" />
        {moved.map((p, j) => {
          const row = j % 3;
          const ly = 10 + row * 12;
          const chars = Math.max(8, Math.floor((spacing * 3) / 6.2));
          const txt = shortWhy(p);
          return (
            <g key={`w${p.k}`}>
              <line x1={x(p.k)} x2={x(p.k)} y1={ly + 3} y2={y(p.score) - 6} stroke="var(--line-3)" strokeDasharray="2 2" />
              <text x={x(p.k)} y={ly} textAnchor={p.k === 0 ? "start" : p.k === n - 1 ? "end" : "middle"} className="why-l">
                {p.score.toFixed(2)} {txt.length > chars ? `${txt.slice(0, chars - 1)}…` : txt}
              </text>
            </g>
          );
        })}
        {pts.map((p, k) => {
          const other = !!decisionId && !!p.decision_id && p.decision_id !== decisionId;
          return (
            <g key={k} opacity={other ? 0.45 : 1}>
              <circle cx={x(k)} cy={y(p.score)} r="5" fill={`var(--st-${tierStatus(p.tier)})`} stroke="var(--surface)" strokeWidth="1.5" />
              <text x={x(k) + 7} y={y(p.score) + 12} style={{ fill: "var(--ink-2)", fontWeight: 600 }}>{k + 1}</text>
              <text x={x(k)} y={H - 18} textAnchor="middle">{formatTime(p.ts)}</text>
              <text x={x(k)} y={H - 6} textAnchor="middle">T{p.tier}</text>
            </g>
          );
        })}
      </svg>
      <table className="dt compact">
        <thead><tr><th style={{ width: 28 }}>#</th><th style={{ width: 76 }}>Time</th><th className="num" style={{ width: 92 }}>Score</th><th style={{ width: 64 }}>Tier</th><th>What changed</th><th>Why (rules / evidence)</th>{multi && <th>Decision</th>}</tr></thead>
        <tbody>
          {pts.map((p, k) => (
            <tr key={k} className={decisionId && p.decision_id === decisionId && multi ? "sel" : ""}>
              <td className="mono">{k + 1}</td>
              <td className="mono xs">{formatTime(p.ts)}</td>
              <td className="num">{p.score.toFixed(2)}{k > 0 && p.score !== pts[k - 1].score && <span className="xs" style={{ color: p.score > pts[k - 1].score ? "var(--st-high)" : "var(--st-normal)" }}> {p.score > pts[k - 1].score ? "+" : ""}{(p.score - pts[k - 1].score).toFixed(2)}</span>}</td>
              <td><TierPill tier={p.tier} /></td>
              <td>{p.label.replace(/\s*\(SIMULATED\)/i, "")}{/SIMULATED/i.test(p.label) && <> <Sim /></>}</td>
              <td className="xs mono muted">{p.reason}</td>
              {multi && <td className="mono xs">{p.decision_id ? (onPickDecision ? <a href="#" onClick={(e) => { e.preventDefault(); onPickDecision(p.decision_id!); }}>{p.decision_id}</a> : p.decision_id) : "—"}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Counterfactual ladder ───────────────────────────────────────────────────
export function CounterfactualLadder({ items, tier, score }: { items: Counterfactual[]; tier: number; score: number }) {
  if (!items.length) {
    return tier === 0
      ? <div className="notice info sm">Already the lowest tier, nothing would need to change.</div>
      : <div className="empty">The policy engine produced no counterfactuals for this decision.</div>;
  }
  const sorted = [...items].sort((a, b) => b.tier - a.tier || b.final_score - a.final_score);
  return (
    <div className="ladder">
      <div className="rung cur">
        <TierPill tier={tier} full />
        <div><b>As decided</b><div className="xs muted">all evidence present — why this tier: every signal in the provenance table below</div></div>
        <span className="mono right">{score.toFixed(3)}</span>
      </div>
      {sorted.map((c) => (
        <div key={c.id} className="rung">
          <TierPill tier={c.tier} full />
          <div>
            <b>{c.label}</b>
            <ul className="xs muted" style={{ margin: "2px 0 0" }}>{c.changes.map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
          <span className="mono right">{c.final_score.toFixed(3)}<div className="xs" style={{ color: c.tier_delta < 0 ? "var(--st-normal)" : "var(--ink-3)" }}>{c.tier_delta === 0 ? "same tier" : `${c.tier_delta} tier${Math.abs(c.tier_delta) > 1 ? "s" : ""}`}</div></span>
        </div>
      ))}
      <div className="xs muted" style={{ paddingTop: 6 }}>Generated deterministically by re-running the versioned policy engine without the named evidence. No language model is involved.</div>
    </div>
  );
}

// ── Evidence provenance ─────────────────────────────────────────────────────
const SKIP_EV = new Set(["simulated", "ts", "event_type", "minutes_ago"]);
function ProvValue({ ev }: { ev: Record<string, unknown> | undefined }) {
  const rows = Object.entries(ev ?? {}).filter(([k, v]) => !SKIP_EV.has(k) && v !== null && v !== undefined && typeof v !== "object").slice(0, 3);
  if (!rows.length) return <span className="xs dim">event observed</span>;
  return <span className="ev">{rows.map(([k, v]) => <span key={k} className="ev-kv">{humanKey(k)} <b>{evValue(k, v)}</b></span>)}</span>;
}

export function ProvenanceTable({ record }: { record: DecisionRecord }) {
  // Values live on the decision's signals (evidence); provenance rows are joined to them by rule id.
  const evidence = useMemo(() => {
    const m = new Map<string, Record<string, unknown>>();
    record.decision.dimensions.forEach((d) => d.signals.forEach((s) => m.set(s.rule_id, s.evidence)));
    return m;
  }, [record]);
  if (!record.provenance.length) return <div className="empty">No signal fired; nothing to attribute.</div>;
  return (
    <div className="tscroll">
      <table className="dt compact">
        <thead><tr><th>Signal</th><th>Dim.</th><th>Value (evidence)</th><th className="num">Contrib.</th><th>Source</th><th>Observed</th><th>Freshness</th><th>Rule / model version</th><th>Status</th><th>Confidence</th></tr></thead>
        <tbody>
          {record.provenance.map((p) => (
            <tr key={p.rule_id}>
              <td><b>{p.label}</b><div className="mono xs dim">{p.rule_id}</div></td>
              <td><Glyph code={DIM_GLYPH[p.dimension]} /></td>
              <td style={{ maxWidth: 260 }}><ProvValue ev={evidence.get(p.rule_id)} /></td>
              <td className="num">+{p.contribution.toFixed(3)}</td>
              <td className="xs">{p.provenance.source}</td>
              <td className="mono xs">{formatStamp(p.provenance.observed_at)}</td>
              <td className="mono xs">{freshness(p.provenance.freshness_s)}</td>
              <td className="mono xs">{p.provenance.version}</td>
              <td>{p.provenance.status === "simulated" ? <Sim /> : <Pill status={p.provenance.status === "unavailable" ? "unknown" : "normal"}>{p.provenance.status.replace("_", " ")}</Pill>}</td>
              <td className="xs muted">{p.provenance.confidence}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
