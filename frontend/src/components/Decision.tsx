// Decision explanation building blocks. Every number shown comes from the
// backend decision record; nothing is re-computed or re-thresholded here.
import { useState } from "react";
import type { Dimension, JourneyItem, RiskDecision, RiskSignal } from "../api/types";
import { DIM_LABEL, TIER_LABEL, formatINR, formatTime } from "../lib/format";

export const DIM_COLOR: Record<Dimension, string> = {
  external: "var(--d-external)",
  network: "var(--d-network)",
  sequence: "var(--d-sequence)",
  behaviour: "var(--d-behaviour)",
  context: "var(--d-context)",
};

export function TierChip({ tier, big = false }: { tier: number | null | undefined; big?: boolean }) {
  if (tier === null || tier === undefined) return <span className="chip">—</span>;
  return <span className={`chip t${tier}`} style={big ? { fontSize: 13, padding: "4px 10px" } : undefined}>{TIER_LABEL[tier]}</span>;
}

export function SimChip({ text = "SIMULATED" }: { text?: string }) {
  return <span className="chip sim" title="Simulated input — not a live institutional feed">{text}</span>;
}

export function ScoreBar({ decision }: { decision: RiskDecision }) {
  const total = Math.max(decision.final_score, decision.base_score, 0.0001);
  const bonus = Math.max(0, decision.final_score - decision.base_score);
  return (
    <div>
      <div className="stacked" title="Contributions add up to the base score; the hatched part is the corroboration bonus">
        {decision.dimensions.filter((d) => d.contribution > 0).map((d) => (
          <span key={d.dimension} style={{ width: `${(d.contribution / Math.max(1, total)) * 100}%`, background: DIM_COLOR[d.dimension] }} />
        ))}
        {bonus > 0 && <span style={{ width: `${bonus * 100}%`, background: "repeating-linear-gradient(45deg, var(--ink-3) 0 3px, transparent 3px 6px)" }} />}
      </div>
      <div className="spread small muted" style={{ marginTop: 4 }}>
        <span>0</span>
        <span className="mono">base {decision.base_score.toFixed(2)}{bonus > 0 ? ` + ${bonus.toFixed(2)}` : ""} = <b style={{ color: "var(--ink)" }}>{decision.final_score.toFixed(2)}</b></span>
        <span>1</span>
      </div>
    </div>
  );
}

function evidenceText(ev: Record<string, unknown>): string {
  return Object.entries(ev)
    .filter(([k]) => !["simulated"].includes(k))
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join("  ");
}

export function SignalCard({ s }: { s: RiskSignal }) {
  return (
    <div className="signal" style={{ borderLeftColor: DIM_COLOR[s.dimension] }}>
      <div className="spread">
        <b>{s.label}</b>
        <span className="mono small">+{s.contribution.toFixed(2)}</span>
      </div>
      <div>{s.reason}</div>
      <div className="rid">{s.rule_id}</div>
      <div className="evidence">{evidenceText(s.evidence)}</div>
    </div>
  );
}

export function ContributionPanel({ decision }: { decision: RiskDecision }) {
  const [open, setOpen] = useState<Dimension | null>(
    [...decision.dimensions].sort((a, b) => b.contribution - a.contribution)[0]?.dimension ?? null);
  return (
    <div className="stack" style={{ gap: 14 }}>
      <ScoreBar decision={decision} />
      <div className="contrib">
        {decision.dimensions.map((d) => (
          <div key={d.dimension} className="contrib-row" style={{ cursor: d.signals.length ? "pointer" : "default" }}
               onClick={() => setOpen(open === d.dimension ? null : d.dimension)}>
            <div className="contrib-head">
              <span><b style={{ color: DIM_COLOR[d.dimension] }}>●</b> {DIM_LABEL[d.dimension]}
                {d.dimension === "external" && <> <SimChip /></>}
                {d.dimension === "context" && d.signals.length > 0 && <> <SimChip text="SIMULATED CONTEXT" /></>}
              </span>
              <span className="mono small">{d.score.toFixed(2)} × {d.weight.toFixed(2)} = <b>{d.contribution.toFixed(3)}</b></span>
            </div>
            <div className="bar"><i style={{ width: `${d.score * 100}%`, background: DIM_COLOR[d.dimension] }} /></div>
            {open === d.dimension && d.signals.length > 0 && (
              <div className="stack" style={{ marginTop: 8 }}>
                {d.signals.map((s) => <SignalCard key={s.rule_id} s={s} />)}
              </div>
            )}
          </div>
        ))}
      </div>
      {decision.adjustments.length > 0 && (
        <div className="stack">
          <div className="upper">Policy adjustments (named, versioned)</div>
          {decision.adjustments.map((a) => (
            <div key={a.rule_id} className="notice small">
              <b className="mono">{a.rule_id}</b> <span className="chip">{a.effect}</span><br />{a.reason}
            </div>
          ))}
        </div>
      )}
      <div className="notice small"><b>Counterfactual:</b> {decision.reasons.analyst.counterfactual}</div>
      <div className="small muted mono">policy {decision.policy_version} · evaluated in {decision.latency_ms.toFixed(1)} ms · no ML model on this path</div>
    </div>
  );
}

export function CustomerView({ decision }: { decision: RiskDecision }) {
  const c = decision.reasons.customer;
  return (
    <div className="stack">
      <div className={`tier-banner t${decision.tier}`}>
        <div className="h">{c.headline}</div>
        <div style={{ marginTop: 6, color: "var(--ink)" }}>{c.summary}</div>
      </div>
      {c.facts.length > 0 && (
        <div className="q-block"><div className="q">Why we are interrupting</div>
          <ul>{c.facts.map((f) => <li key={f}>{f}</li>)}</ul></div>
      )}
      <div className="q-block"><div className="q">What happens next</div>{c.what_happens_next}</div>
    </div>
  );
}

export function BankView({ decision }: { decision: RiskDecision }) {
  const a = decision.reasons.analyst;
  return (
    <div className="stack">
      <div className="notice"><b>{a.summary}</b><br /><span className="small">Intervention: {decision.intervention.bank_action}</span></div>
      <ContributionPanel decision={decision} />
      {a.external && (
        <div className="q-block">
          <div className="q">External intelligence <SimChip text="SIMULATED EXTERNAL INTELLIGENCE" /></div>
          <div className="small">{a.external.identifier} · <b>{a.external.status}</b> · registry score {a.external.risk_score.toFixed(2)} · {a.external.source} · updated {formatTime(a.external.last_updated)}</div>
          <div className="small mono">{a.external.reason_codes.join(", ") || "no reason codes"}</div>
        </div>
      )}
    </div>
  );
}

export function AuditView({ decision }: { decision: RiskDecision }) {
  return (
    <div className="stack">
      <div className="small muted">Exact inputs, scores, policy version and action. SHA-256 is an integrity check, not a signature. The decision row is append-only (a database trigger rejects updates).</div>
      <div className="mono small">sha256 {decision.payload_sha256}</div>
      <pre className="audit">{JSON.stringify(decision.reasons.audit, null, 2)}</pre>
    </div>
  );
}

export function ExplainTabs({ decision, initial = "customer" }: { decision: RiskDecision; initial?: "customer" | "bank" | "audit" }) {
  const [tab, setTab] = useState(initial);
  return (
    <div>
      <div className="tabs">
        <button className={tab === "customer" ? "active" : ""} onClick={() => setTab("customer")}>Customer reason</button>
        <button className={tab === "bank" ? "active" : ""} onClick={() => setTab("bank")}>Bank evidence</button>
        <button className={tab === "audit" ? "active" : ""} onClick={() => setTab("audit")}>Audit record</button>
      </div>
      {tab === "customer" && <CustomerView decision={decision} />}
      {tab === "bank" && <BankView decision={decision} />}
      {tab === "audit" && <AuditView decision={decision} />}
    </div>
  );
}

export function Timeline({ items, empty = "No journey events in this window." }: { items: JourneyItem[]; empty?: string }) {
  if (!items.length) return <div className="empty">{empty}</div>;
  const hot = new Set(["login_new_device", "payee_added", "limit_raised", "credential_changed", "screen_share_active"]);
  return (
    <div className="timeline">
      {items.map((it, i) => {
        const cls = it.event_type === "simulated_context" ? "ctx" : hot.has(it.event_type) ? "hot"
          : it.kind === "payment" || it.kind === "intent" ? "pay" : "";
        const text = it.event_type === "simulated_context" ? String((it.payload as { text?: string }).text ?? "") : "";
        return (
          <div key={`${it.ts}-${i}`} className={`tl-item ${cls}`}>
            <div className="t">{formatTime(it.ts)} · {it.minutes_ago} min ago</div>
            <div><b>{it.label}</b>{it.event_type === "simulated_context" && <> <SimChip text="SIMULATED CONTEXT" /></>}</div>
            {text && <div className="small muted" style={{ fontStyle: "italic" }}>“{text.slice(0, 220)}{text.length > 220 ? "…" : ""}”</div>}
          </div>
        );
      })}
    </div>
  );
}

export function Amount({ paise }: { paise: number }) {
  return <span className="mono">{formatINR(paise)}</span>;
}
