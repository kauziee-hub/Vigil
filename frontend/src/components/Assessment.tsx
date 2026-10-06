// Bank-side pre-commitment ASSESSMENT of one payment, as a structured case:
// sender · recipient · amount · relationship · device · behaviour · network · external (SIMULATED) ·
// journey · context (SIMULATED) · model evidence (corroborating) · final decision → intervention → outcome.
// Every value is read from the decision record / account summaries; nothing is recomputed here.
import { Link } from "react-router-dom";
import type {
  AccountSummary, DecisionRecord, Dimension, DimensionScore, Provenance, RiskDecision, RiskDecisionV2, TransactionIntent,
} from "../api/types";
import { DIM_LABEL, STATE_LABEL, ago, evValue, formatDateTime, formatINR, formatStamp, formatTime, freshness, handle } from "../lib/format";
import { scoreStatus, stateStatus, tierStatus } from "../lib/status";
import { EvidenceChips, ScoreLine } from "./Decision";
import { DetectorTable } from "./intel";
import { KV, Pill, Sim, StatePill, TierPill } from "./ui";

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {});
const numOr = (v: unknown): number | null => (typeof v === "number" && !Number.isNaN(v) ? v : null);

function DimScore({ d }: { d: DimensionScore | undefined }) {
  if (!d) return <span className="dim">—</span>;
  return (
    <div className="stack tight" style={{ alignItems: "flex-end" }}>
      <span><b style={{ color: d.score > 0 ? `var(--st-${scoreStatus(d.score)})` : undefined }}>{d.score.toFixed(2)}</b>
        <span className="dim"> × {d.weight.toFixed(2)}</span></span>
      <span className="dim">= {d.contribution.toFixed(3)}</span>
    </div>
  );
}

/** One compact row per fired rule: label + reason · evidence · provenance (status/freshness; full line on hover) · contribution. */
function Signals({ d }: { d: DimensionScore | undefined }) {
  if (!d || !d.signals.length) return <div className="xs muted">No rule fired in this family.</div>;
  return (
    <table className="sigt">
      <tbody>
        {d.signals.map((s) => {
          const p = (s as { provenance?: Provenance | null }).provenance;
          return (
            <tr key={s.rule_id}>
              <td className="s-l">
                <b>{s.label}</b> <span className="mono xs dim">{s.rule_id}</span>
                <div className="xs muted">{s.reason}</div>
              </td>
              <td className="s-e"><EvidenceChips ev={s.evidence} /></td>
              <td className="s-p" title={p ? `${p.source} · observed ${formatStamp(p.observed_at)} · ${p.version} · ${p.confidence}` : "provenance not recorded (v1 record)"}>
                {p ? <>{p.status === "simulated" ? <Sim /> : <span className="tag">{p.status.replace("_", " ")}</span>}<div className="xs dim mono">{freshness(p.freshness_s)}</div></>
                  : <span className="xs dim">—</span>}
              </td>
              <td className="s-c mono">+{s.contribution.toFixed(3)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function accountAge(iso: string | undefined): string {
  if (!iso) return "—";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days < 1) return "opened today";
  if (days < 60) return `${days} days old`;
  return `${(days / 365).toFixed(days > 730 ? 0 : 1)} years old`;
}

export function AssessmentTable({ decision, intent, sender, recipient, record }: {
  decision: RiskDecision; intent: TransactionIntent; sender: AccountSummary | null; recipient: AccountSummary | null;
  record: DecisionRecord | null;
}) {
  const d2 = decision as RiskDecisionV2;
  const dim = (k: Dimension) => decision.dimensions.find((x) => x.dimension === k);
  const net = obj(decision.reasons.analyst.network);
  const beh = obj(net.behaviour);
  const ctx = obj(net.context);
  const ext = decision.reasons.analyst.external;
  const priorPaid = numOr(beh.prior_payments_to_recipient) ?? sender?.payees.find((p) => p.payee_id === intent.recipient_id)?.payments ?? null;
  const known = sender?.devices ?? [];
  const dev = intent.device_id;
  const journey = decision.reasons.analyst.journey;
  const ctxItems = Array.isArray(ctx.contexts) ? (ctx.contexts as Obj[]) : [];
  const evidence = d2.model_evidence ?? [];

  return (
    <table className="assess">
      <tbody>
        <tr>
          <th>Sender<span className="up">who is paying</span></th>
          <td>
            {sender ? (
              <KV c4 rows={[
                ["Account", <><b>{sender.display_name}</b> <span className="mono xs dim">{sender.id}</span></>],
                ["Age", accountAge(sender.opened_at)],
                ["Available", <span className="mono">{formatINR(sender.available_paise)}</span>],
                ["Held", sender.held_paise ? <span className="mono" style={{ color: "var(--st-held)" }}>{formatINR(sender.held_paise)}</span> : <span className="mono">₹0</span>],
                ["Daily limit", <span className="mono">{formatINR(sender.daily_limit_paise)}</span>],
                ["Trusted contact", sender.trusted_contact ? `${sender.trusted_contact.name} (${sender.trusted_contact.relation})` : "none nominated"],
              ]} />
            ) : <span className="muted">{handle(intent.sender_id)}</span>}
            {sender?.persona && <div className="xs muted" style={{ marginTop: 4 }}>{sender.persona}</div>}
          </td>
          <td className="sc" />
        </tr>
        <tr>
          <th>Recipient<span className="up">who receives</span></th>
          <td>
            {recipient ? (
              <KV c4 rows={[
                ["Account", <><b>{recipient.display_name}</b> <span className="mono xs dim">{recipient.id}</span></>],
                ["Age", accountAge(recipient.opened_at)],
                ["Kind", recipient.kind],
                ["Balance", <span className="mono">{formatINR(recipient.balance_paise)}</span>],
              ]} />
            ) : <span className="muted">{handle(intent.recipient_id)} <span className="xs">(outside the bank's view)</span></span>}
          </td>
          <td className="sc" />
        </tr>
        <tr>
          <th>Amount<span className="up">what is asked</span></th>
          <td>
            <div className="row wrap"><b className="mono" style={{ fontSize: 15 }}>{formatINR(intent.amount_paise)}</b>
              {numOr(beh.balance_fraction) !== null && <span className="tag">{Math.round(numOr(beh.balance_fraction)! * 100)}% of available balance</span>}
              {intent.note && <span className="xs muted">note “{intent.note}”</span>}
              {intent.purpose && <span className="xs muted">purpose “{intent.purpose}”</span>}
            </div>
            <div className="xs muted" style={{ marginTop: 3 }}>
              {numOr(beh.median_paise) !== null && <>sender's median payment {formatINR(numOr(beh.median_paise))} over {String(beh.history_count ?? "—")} payments</>}
              {numOr(beh.robust_z) !== null && <> · robust z {numOr(beh.robust_z)!.toFixed(1)}</>}
            </div>
          </td>
          <td className="sc" />
        </tr>
        <tr>
          <th>Relationship<span className="up">sender ↔ recipient</span></th>
          <td>
            {priorPaid === null ? <span className="muted">not recorded</span>
              : priorPaid === 0 ? <><Pill status="watch">first payment</Pill> <span className="xs muted">never paid this recipient before</span></>
              : <><Pill status="normal">established</Pill> <span className="xs muted">paid {priorPaid} time{priorPaid > 1 ? "s" : ""} before
                  {numOr(beh.typical_to_recipient_paise) !== null && <> · typically {formatINR(numOr(beh.typical_to_recipient_paise))}</>}</span></>}
          </td>
          <td className="sc" />
        </tr>
        <tr>
          <th>Device<span className="up">where it came from</span></th>
          <td>
            <div className="row wrap">
              <span className="mono sm">{dev ?? "not supplied with intent"}</span>
              {dev && known.length > 0 && (dev === sender?.primary_device ? <Pill status="normal">primary device</Pill>
                : known.includes(dev) ? <Pill status="watch">secondary device</Pill> : <Pill status="high">unknown device</Pill>)}
            </div>
            <div className="xs muted">primary {sender?.primary_device ?? "—"} · {known.length} device{known.length === 1 ? "" : "s"} on record
              {journey.some((j) => j.event_type === "login_new_device") && " · new-device sign-in in the journey window"}</div>
          </td>
          <td className="sc" />
        </tr>
        <tr>
          <th>Behaviour<span className="up">{DIM_LABEL.behaviour}</span></th>
          <td><Signals d={dim("behaviour")} /></td>
          <td className="sc"><DimScore d={dim("behaviour")} /></td>
        </tr>
        <tr>
          <th>Network intelligence<span className="up">RingWatch · recipient</span></th>
          <td>
            <div className="xs muted" style={{ marginBottom: 4 }}>
              {["inflow_count", "distinct_senders", "first_time_senders", "forwarded_fraction", "median_forward_minutes", "device_peers", "age_days"]
                .filter((k) => net[k] !== undefined)
                .map((k) => <span key={k} className="ev-kv" style={{ marginRight: 4 }}>{k.replace(/_/g, " ")} <b>{evValue(k, net[k])}</b></span>)}
              <span className="dim">({String(net.window_hours ?? 72)} h window)</span>
            </div>
            <Signals d={dim("network")} />
          </td>
          <td className="sc"><DimScore d={dim("network")} /></td>
        </tr>
        <tr>
          <th>External intelligence<span className="up"><Sim /></span></th>
          <td>
            {ext ? (
              <div className="row wrap">
                <Pill status={ext.status === "confirmed_mule" ? "fraud" : ext.status === "reported" ? "high" : ext.status === "watchlist" ? "watch" : "normal"}>{ext.status.replace("_", " ")}</Pill>
                <span className="mono xs">risk {ext.risk_score.toFixed(2)}</span>
                {ext.reason_codes.map((c) => <span key={c} className="tag mono">{c}</span>)}
                <span className="xs muted">{ext.source} · updated {formatStamp(ext.last_updated)}</span>
              </div>
            ) : <div className="xs muted">No registry entry for the recipient (simulated local registry).</div>}
            <Signals d={dim("external")} />
          </td>
          <td className="sc"><DimScore d={dim("external")} /></td>
        </tr>
        <tr>
          <th>Journey signals<span className="up">{DIM_LABEL.sequence}</span></th>
          <td>
            {journey.length > 0 && (
              <div className="jrny">
                {journey.map((j, i) => (
                  <span key={`${j.ts}-${i}`} className={`jstep ${j.event_type === "simulated_context" ? "sim-j" : ""}`}>
                    <span className="mono xs dim">−{Math.round(j.minutes_ago)}m</span> {j.label}
                    {j.source === "scenario" && <span className="sim" title="Scenario-injected journey event">SIM</span>}
                  </span>
                ))}
              </div>
            )}
            <Signals d={dim("sequence")} />
          </td>
          <td className="sc"><DimScore d={dim("sequence")} /></td>
        </tr>
        <tr>
          <th>Context<span className="up"><Sim text="SIMULATED CONTEXT" /></span></th>
          <td>
            {ctxItems.slice(0, 1).map((c, i) => (
              <div key={i} className="xs muted" style={{ fontStyle: "italic", marginBottom: 4 }}>
                {String(c.channel ?? "context")} · “{String(c.text ?? "").slice(0, 180)}{String(c.text ?? "").length > 180 ? "…" : ""}”
              </div>
            ))}
            <Signals d={dim("context")} />
          </td>
          <td className="sc"><DimScore d={dim("context")} /></td>
        </tr>
        <tr>
          <th>Model evidence<span className="up">corroborating only</span></th>
          <td>
            {evidence.length ? <DetectorTable detectors={evidence} compact />
              : <div className="xs muted">No model evidence recorded on this decision. RF / GNN / drift / pattern memory are corroborating evidence and never set the tier.</div>}
          </td>
          <td className="sc" />
        </tr>
        <tr className="decision">
          <th>Final decision<span className="up">policy engine</span></th>
          <td>
            <ScoreLine decision={decision} ladder={record?.thresholds} />
            {decision.adjustments.map((a) => (
              <div key={a.rule_id} className="xs" style={{ marginTop: 4 }}><span className="mono">{a.rule_id}</span> <span className="tag">{a.kind}</span> <b className="mono">{a.effect}</b> <span className="muted">{a.reason}</span></div>
            ))}
            <div className="row wrap" style={{ marginTop: 6 }}>
              <TierPill tier={decision.tier} full lg />
              <StatePill state={intent.state} />
              {d2.mode === "shadow" && <Pill status="watch">shadow · not applied</Pill>}
              <b>{decision.intervention.title}</b>
            </div>
            <div className="xs muted" style={{ marginTop: 4 }}>Bank action: {decision.intervention.bank_action}</div>
            {(d2.mode || d2.baseline) && (
              <div className="xs" style={{ marginTop: 4 }}>
                mode <b>{(d2.mode ?? "active").toUpperCase()}</b>
                {d2.recommended_tier != null && <> · Vigil recommended <b>T{d2.recommended_tier}</b></>}
                {d2.applied_tier != null && <> · applied <b>T{d2.applied_tier}</b></>}
                {d2.baseline && <> · bank baseline <b>{d2.baseline.decision.replace(/_/g, " ")}</b> <span className="muted">({d2.baseline.reason})</span></>}
              </div>
            )}
          </td>
          <td className="sc"><b style={{ fontSize: 15, color: `var(--st-${tierStatus(decision.tier)})` }}>{decision.final_score.toFixed(3)}</b><div className="dim">{decision.latency_ms.toFixed(1)} ms</div></td>
        </tr>
      </tbody>
    </table>
  );
}

/** What the customer was shown — the exact intervention, from ReasonLine (customer rendering). */
export function InterventionShown({ decision, intent }: { decision: RiskDecision; intent: TransactionIntent }) {
  const c = decision.reasons.customer;
  const iv = decision.intervention;
  return (
    <div className="stack">
      <div className="spread"><b>{c.headline}</b><TierPill tier={decision.tier} full /></div>
      <div className="ink2 md">{c.summary}</div>
      {c.facts.length > 0 && <ul className="md">{c.facts.map((f) => <li key={f}>{f}</li>)}</ul>}
      <KV rows={[
        ["Customer action", iv.customer_action],
        ["What happens next", c.what_happens_next],
        ["Scoped hold", iv.hold_paise ? <span className="mono" style={{ color: "var(--st-held)" }}>{formatINR(iv.hold_paise)} {intent.hold_id ? `· ${intent.hold_id}` : ""}</span> : "none"],
        ["CircuitBreaker", iv.circuit_breaker ? "trusted contact alerted with facts, not accusations" : "not used"],
      ]} />
    </div>
  );
}

/** After payment: provider → ledger → monitoring; before payment: what has (not) happened. */
export function Outcome({ intent, record }: { intent: TransactionIntent; record: DecisionRecord | null }) {
  const pay = record?.payment_result ?? intent.payment;
  const ledger = record?.ledger_transaction ?? null;
  const monitored = intent.transitions.find((t) => t.to_state === "MONITORED");
  const moved = ["PAYMENT_SUCCEEDED", "MONITORED"].includes(intent.state);
  return (
    <div className="stack">
      {!moved && <div className="notice info sm">No money has moved. The payment provider is called only after Vigil approves (or the bank releases) the intent.</div>}
      <table className="dt compact">
        <tbody>
          <tr><td className="muted" style={{ width: 120 }}>Provider</td><td>{pay ? <><b>{pay.provider === "razorpay_test" ? "Razorpay TEST" : "Mock provider"}</b> · {pay.status} · <span className="mono xs">{pay.payment_id ?? pay.order_id ?? "—"}</span> <span className="sim">{pay.label}</span></> : <span className="dim">not called</span>}</td></tr>
          <tr><td className="muted">Ledger</td><td>{ledger ? <><span className="mono">{ledger.id}</span> · seq {ledger.seq} · <b className="mono">{formatINR(ledger.amount_paise)}</b> · {formatTime(ledger.ts)} · double-entry posted</> : <span className="dim">no posting</span>}</td></tr>
          <tr><td className="muted">Monitoring</td><td>{monitored ? <span>{monitored.detail ?? "monitored"} <span className="xs dim">{formatTime(monitored.ts)}</span></span> : <span className="dim">{moved ? "pending" : "not applicable before payment"}</span>}</td></tr>
        </tbody>
      </table>
      <div>
        <div className="up" style={{ marginBottom: 4 }}>Intent lifecycle <span className="mono">{intent.intent_id}</span></div>
        <div className="tl">
          {intent.transitions.map((t, i) => (
            <div key={i} className={`tl-i ${stateStatus(t.to_state) === "held" ? "held" : stateStatus(t.to_state) === "normal" ? "ok" : t.to_state === "REJECTED" ? "crit" : ""}`}>
              <div className="t">{formatTime(t.ts)} · {t.actor}</div>
              <div><b>{STATE_LABEL[t.to_state] ?? t.to_state}</b>{t.detail && <span className="muted"> — {t.detail}</span>}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function CaseLinks({ decisionId }: { decisionId: string }) {
  return (
    <div className="row wrap">
      <Link className="btn sm" to={`/investigations/decision/${decisionId}`}>Investigate</Link>
      <Link className="btn sm" to={`/investigations/decision/${decisionId}#replay`}>Replay decision</Link>
      <Link className="btn sm ghost" to={`/governance/decision/${decisionId}`}>Decision record</Link>
    </div>
  );
}

export function CaseMeta({ decision, intent }: { decision: RiskDecision; intent: TransactionIntent }) {
  return (
    <span className="xs muted mono">{decision.decision_id} · {intent.intent_id} · {intent.source} · {formatDateTime(decision.created_at)} · {ago(decision.created_at)} · policy {decision.policy_version}</span>
  );
}
