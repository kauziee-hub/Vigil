// TaintTrace output: LIBR and pro rata side by side — two established tracing rules that can
// disagree; Vigil shows both rather than asserting a legal conclusion.
import type { TaintIncident } from "../api/types";
import { formatINR, formatTime, handle } from "../lib/format";

export function MoneyTrace({ incidents, focus }: { incidents: TaintIncident[]; focus?: string }) {
  if (!incidents.length) {
    return <div className="empty">No confirmed scam has been traced yet. Confirm a victim payment from the Network Intelligence drawer or an account investigation.</div>;
  }
  return (
    <div className="stack loose">
      {incidents.map((inc) => (
        <div key={inc.label_id} className="stack">
          <div className="md">
            <span className="mono b">{inc.label_id}</span> · source {handle(inc.source_account)} → {handle(inc.first_recipient)} ·
            origin <b className="mono">{formatINR(inc.origin_paise)}</b> · <span className="tag">{inc.grade.replace(/_/g, " ")}</span> · <span className="mono xs muted">{formatTime(inc.labelled_at)}</span>
          </div>
          <div className="grid cols-2">
            {(["libr", "pro_rata"] as const).map((rule) => {
              const r = inc.rules[rule];
              const claims = [...r.claims].sort((a, b) => b.amount_paise - a.amount_paise);
              return (
                <div key={rule} className="trace-col">
                  <div className="up" style={{ marginBottom: 4 }}>{rule === "libr" ? "LIBR · lowest intermediate balance" : "Pro rata"}</div>
                  <table className="dt compact">
                    <thead><tr><th>Account</th><th className="num">Hop</th><th className="num">Attributable</th></tr></thead>
                    <tbody>
                      {claims.map((c) => (
                        <tr key={c.account_id} className={c.account_id === focus ? "sel" : ""}>
                          <td>{handle(c.account_id)}</td>
                          <td className="num">{inc.hops[c.account_id] ?? "—"}</td>
                          <td className="num" style={{ color: "var(--st-fraud)" }}>{formatINR(c.amount_paise)}</td>
                        </tr>
                      ))}
                      {!claims.length && <tr><td colSpan={3} className="muted">nothing still attributable</td></tr>}
                    </tbody>
                  </table>
                  <div className="xs mono muted" style={{ marginTop: 6 }}>
                    attributable {formatINR(r.attributable_total_paise)} · left perimeter {formatINR(r.left_perimeter_paise)} ·
                    no longer attributable {formatINR(r.spent_paise)} · coverage {(r.coverage * 100).toFixed(0)}%
                  </div>
                  <div className="xs" style={{ color: r.conserved ? "var(--st-normal)" : "var(--st-critical)" }}>
                    {r.conserved ? "✓ conserved: attributable + left + no-longer = origin" : "✗ conservation check failed"}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="xs muted">Amounts are “attributable under the named rule”, not proof that specific rupees moved. Dilution happens when traced value mixes with an account's own money.</div>
        </div>
      ))}
    </div>
  );
}
