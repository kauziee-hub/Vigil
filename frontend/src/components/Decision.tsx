// Operational-decision building blocks (ReasonLine). Every number comes from the backend decision
// record; nothing is re-computed or re-thresholded here. These explain the OPERATIONAL DECISION —
// model explanations (SHAP) live in components/intel.tsx and are never mixed in.
import { Fragment, useState } from "react";
import type { Dimension, JourneyItem, Provenance, RiskDecision, RiskSignal, RiskSignalV2 } from "../api/types";
import { DIM_LABEL, evValue, formatStamp, formatTime, freshness, humanKey } from "../lib/format";
import { DIM_GLYPH, scoreStatus } from "../lib/status";
import { Bar, Glyph, Pill, Sim, TierPill } from "./ui";

export const SIMULATED_DIMS: Dimension[] = ["external", "context"];

export function EvidenceChips({ ev }: { ev: Record<string, unknown> }) {
  const entries = Object.entries(ev).filter(([k, v]) => k !== "simulated" && v !== null && v !== undefined && typeof v !== "object");
  if (!entries.length) return null;
  return (
    <span className="ev">
      {entries.map(([k, v]) => <span key={k} className="ev-kv">{humanKey(k)} <b>{evValue(k, v)}</b></span>)}
    </span>
  );
}

export function ProvenanceLine({ p }: { p: Provenance | null | undefined }) {
  if (!p) return <span className="xs dim">provenance not recorded (v1 record)</span>;
  return (
    <span className="xs muted mono">
      {p.source} · observed {formatTime(p.observed_at)} · {freshness(p.freshness_s)} · {p.version} · {p.status}
      {p.confidence ? ` · ${p.confidence}` : ""}
    </span>
  );
}

export function SignalRow({ s }: { s: RiskSignal }) {
  const p = (s as RiskSignalV2).provenance;
  return (
    <div className="sig">
      <span><b>{s.label}</b> <span className="mono xs dim">{s.rule_id}</span>{p?.status === "simulated" && <> <Sim /></>}</span>
      <span className="mono sm">+{s.contribution.toFixed(3)}</span>
      <span className="r">{s.reason}</span>
      <EvidenceChips ev={s.evidence} />
      {p !== undefined && <span style={{ gridColumn: "1 / -1" }}><ProvenanceLine p={p} /></span>}
    </div>
  );
}

/** Final score against the policy ladder thresholds. */
export function ScoreLine({ decision, ladder }: { decision: RiskDecision; ladder?: { tier: number; below: number }[] }) {
  const bonus = decision.final_score - decision.base_score;
  return (
    <div className="stack tight">
      <div style={{ position: "relative" }}>
        <div className="bar thick">
          <i style={{ width: `${Math.min(1, decision.final_score) * 100}%`, background: `var(--st-${scoreStatus(decision.final_score)})` }} />
          {(ladder ?? []).filter((l) => l.below < 1).map((l) => <span key={l.tier} className="tick" style={{ left: `${l.below * 100}%` }} />)}
        </div>
      </div>
      <div className="spread xs muted mono">
        <span>base {decision.base_score.toFixed(3)}{Math.abs(bonus) > 1e-6 ? ` ${bonus > 0 ? "+" : "−"} ${Math.abs(bonus).toFixed(3)} policy` : ""}</span>
        <span>final <b style={{ color: "var(--ink)" }}>{decision.final_score.toFixed(3)}</b> → <TierPill tier={decision.tier} /></span>
      </div>
    </div>
  );
}

export function ContributionTable({ decision, openFirst = true }: { decision: RiskDecision; openFirst?: boolean }) {
  const top = [...decision.dimensions].sort((a, b) => b.contribution - a.contribution)[0]?.dimension ?? null;
  const [open, setOpen] = useState<Dimension | null>(openFirst ? top : null);
  return (
    <table className="dt compact">
      <thead><tr><th>Dimension</th><th style={{ width: "34%" }}>Score</th><th className="num">Weight</th><th className="num">Contrib.</th></tr></thead>
      <tbody>
        {decision.dimensions.map((d) => (
          <Fragment key={d.dimension}>
            <tr className={d.signals.length ? "click" : ""} onClick={() => d.signals.length && setOpen(open === d.dimension ? null : d.dimension)}>
              <td>
                <span className="row tight">
                  <Glyph code={DIM_GLYPH[d.dimension]} />
                  <span>{DIM_LABEL[d.dimension]}</span>
                  {SIMULATED_DIMS.includes(d.dimension) && (d.dimension === "external" || d.signals.length > 0) && <Sim />}
                  {d.signals.length > 0 && <span className="xs dim">{open === d.dimension ? "▾" : "▸"} {d.signals.length}</span>}
                </span>
              </td>
              <td><div className="row tight"><div className="grow"><Bar value={d.score} status={d.score > 0 ? scoreStatus(d.score) : undefined} /></div><span className="mono xs">{d.score.toFixed(2)}</span></div></td>
              <td className="num">{d.weight.toFixed(2)}</td>
              <td className="num"><b>{d.contribution.toFixed(3)}</b></td>
            </tr>
            {open === d.dimension && d.signals.length > 0 && (
              <tr><td colSpan={4} style={{ background: "var(--surface-2)", height: "auto" }}>
                {d.signals.map((s) => <SignalRow key={s.rule_id} s={s} />)}
              </td></tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

/** ReasonLine — explains the OPERATIONAL decision (policy engine), not the model. */
export function ReasonLinePanel({ decision }: { decision: RiskDecision }) {
  return (
    <div className="stack">
      <div className="md">{decision.reasons.analyst.summary}</div>
      <ScoreLine decision={decision} />
      <ContributionTable decision={decision} />
      {decision.adjustments.length > 0 && (
        <div className="stack tight">
          <div className="up">Policy adjustments (named, versioned)</div>
          {decision.adjustments.map((a) => (
            <div key={a.rule_id} className="sig">
              <span><span className="mono sm">{a.rule_id}</span> <span className="tag">{a.kind}</span></span>
              <span className="mono sm">{a.effect}</span>
              <span className="r">{a.reason}</span>
            </div>
          ))}
        </div>
      )}
      <div className="xs muted mono">policy {decision.policy_version} · evaluated in {decision.latency_ms.toFixed(1)} ms · transparent engine only — no ML model on the authorisation path</div>
    </div>
  );
}

export function CustomerView({ decision }: { decision: RiskDecision }) {
  const c = decision.reasons.customer;
  return (
    <div className="stack">
      <div className="spread"><b>{c.headline}</b><TierPill tier={decision.tier} full /></div>
      <div className="ink2">{c.summary}</div>
      {c.facts.length > 0 && <div><div className="up">Why we are interrupting</div><ul className="md">{c.facts.map((f) => <li key={f}>{f}</li>)}</ul></div>}
      <div><div className="up">What happens next</div><div className="md">{c.what_happens_next}</div></div>
    </div>
  );
}

export function AuditView({ decision }: { decision: RiskDecision }) {
  return (
    <div className="stack">
      <div className="xs muted">Exact inputs, scores, policy version and action. SHA-256 is an integrity check, not a signature. The decision row is append-only.</div>
      <div className="mono xs">sha256 {decision.payload_sha256}</div>
      <pre className="raw">{JSON.stringify(decision.reasons.audit, null, 2)}</pre>
    </div>
  );
}

const HOT = new Set(["login_new_device", "payee_added", "limit_raised", "credential_changed", "screen_share_active"]);

export function Timeline({ items, empty = "No journey events in this window." }: { items: JourneyItem[]; empty?: string }) {
  if (!items.length) return <div className="empty">{empty}</div>;
  return (
    <div className="tl">
      {items.map((it, i) => {
        const sim = it.event_type === "simulated_context";
        const cls = sim ? "sim-i hot" : HOT.has(it.event_type) ? "hot" : "";
        const text = sim ? String((it.payload as { text?: string }).text ?? "") : "";
        return (
          <div key={`${it.ts}-${i}`} className={`tl-i ${cls}`}>
            <div className="t">{formatStamp(it.ts)} · {Math.round(it.minutes_ago)} min before</div>
            <div className="row tight"><span>{it.label}</span>{sim && <Sim text="SIMULATED CONTEXT" />}</div>
            {text && <div className="xs muted" style={{ fontStyle: "italic" }}>“{text.slice(0, 200)}{text.length > 200 ? "…" : ""}”</div>}
          </div>
        );
      })}
    </div>
  );
}

export function StatusFromScore({ score }: { score: number }) {
  return <Pill status={scoreStatus(score)}>{score.toFixed(2)}</Pill>;
}
