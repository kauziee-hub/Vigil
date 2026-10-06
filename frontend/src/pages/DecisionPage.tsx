// Act 5 — one decision, three representations.
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { RiskDecision } from "../api/types";
import { AuditView, BankView, CustomerView, TierChip } from "../components/Decision";
import { formatINR, formatDateTime, handle } from "../lib/format";
import { useLoad } from "../lib/hooks";

export function DecisionPage() {
  const { decisionId = "" } = useParams();
  const d = useLoad<RiskDecision>(() => api.decision(decisionId), [decisionId]);
  if (d.error) return <div className="notice error">{d.error.message}</div>;
  if (!d.data) return <div className="spinner" />;
  const x = d.data;
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="spread wrap">
        <div>
          <h1>Decision {x.decision_id}</h1>
          <div className="row wrap small" style={{ marginTop: 4 }}>
            <TierChip tier={x.tier} big /> {handle(x.sender_id)} → {handle(x.recipient_id)} · <b className="mono">{formatINR(x.amount_paise)}</b> · {formatDateTime(x.created_at)}
          </div>
        </div>
        <Link className="btn sm" to={`/investigate/${x.decision_id}`}>Open investigation →</Link>
      </div>
      <div className="small muted">The same decision rendered three ways from one evidence record. Deterministic templates — no LLM.</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 16, alignItems: "start" }}>
        <div className="card"><h2>1 · Customer</h2><CustomerView decision={x} /></div>
        <div className="card"><h2>2 · Bank analyst</h2><BankView decision={x} /></div>
        <div className="card"><h2>3 · Audit log</h2><AuditView decision={x} /></div>
      </div>
    </div>
  );
}
