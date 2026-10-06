// TaintTrace output: LIBR and pro rata side by side — two established tracing
// rules that disagree; Vigil shows both rather than asserting a legal conclusion.
import type { TaintIncident } from "../api/types";
import { formatINR, formatTime, handle } from "../lib/format";

export function MoneyTrace({ incidents, focus }: { incidents: TaintIncident[]; focus?: string }) {
  if (!incidents.length) {
    return <div className="empty">No confirmed scam has been traced yet. Confirm a source transaction in the Network view.</div>;
  }
  return (
    <div className="stack" style={{ gap: 16 }}>
      {incidents.map((inc) => (
        <div key={inc.label_id} className="stack">
          <div className="small">
            <b>{inc.label_id}</b> · source {handle(inc.source_account)} → {handle(inc.first_recipient)} ·
            origin <b className="mono">{formatINR(inc.origin_paise)}</b> · {inc.grade.replace("_", " ")} · {formatTime(inc.labelled_at)}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {(["libr", "pro_rata"] as const).map((rule) => {
              const r = inc.rules[rule];
              const claims = [...r.claims].sort((a, b) => b.amount_paise - a.amount_paise);
              return (
                <div key={rule} className="q-block">
                  <div className="q">{rule === "libr" ? "LIBR (Lowest Intermediate Balance)" : "Pro rata"}</div>
                  <table className="data">
                    <thead><tr><th>Account</th><th>Hop</th><th style={{ textAlign: "right" }}>Attributable</th></tr></thead>
                    <tbody>
                      {claims.map((c) => (
                        <tr key={c.account_id} style={c.account_id === focus ? { background: "var(--t3-bg)" } : undefined}>
                          <td>{handle(c.account_id)}</td>
                          <td className="mono">{inc.hops[c.account_id] ?? "—"}</td>
                          <td className="mono" style={{ textAlign: "right" }}>{formatINR(c.amount_paise)}</td>
                        </tr>
                      ))}
                      {!claims.length && <tr><td colSpan={3} className="muted">nothing still attributable</td></tr>}
                    </tbody>
                  </table>
                  <div className="small mono" style={{ marginTop: 6 }}>
                    still attributable {formatINR(r.attributable_total_paise)} · left perimeter {formatINR(r.left_perimeter_paise)} ·
                    no longer attributable {formatINR(r.spent_paise)} · coverage {(r.coverage * 100).toFixed(0)}%
                  </div>
                  <div className="small" style={{ color: r.conserved ? "var(--t0)" : "var(--t3)" }}>
                    {r.conserved ? "✓ conserved: attributable + left + no-longer = origin" : "✗ conservation check failed"}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="small muted">Amounts are “attributable under the named rule”, not proof that specific rupees moved. Dilution happens when traced value mixes with an account's own money.</div>
        </div>
      ))}
    </div>
  );
}
