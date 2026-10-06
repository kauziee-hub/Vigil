// Where Vigil would sit in Indian payments infrastructure — stated without overclaiming.
const ROWS = [
  ["Bank / payment app", "Customer initiates a payment. Today Vigil's demo Pay screen.", "Built (demo UI)"],
  ["Existing institutional intelligence", "Bank EFRMS/AML, MuleHunter.AI deployments (RBIH), DPIP-style shared registry, I4C suspect registry, DoT FRI. Vigil consumes such signals through one adapter.", "Simulated (LocalRegistryProvider)"],
  ["Vigil pre-commit decision engine", "Fuses external + network + journey + behaviour + context evidence at commit time; picks a proportionate intervention; explains it three ways.", "Built"],
  ["Pass / explain / challenge / hold / escalate", "Interrupt ladder. Holds are scoped to the payment amount; no account freeze exists.", "Built"],
  ["Payment provider / rail", "Called only after approval. Mock provider offline; Razorpay in TEST mode (test funds — no real money moves).", "Built (mock) · Razorpay test if configured"],
  ["Post-transaction monitoring", "Ledger + incremental graph; RingWatch re-scores; TaintTrace attributes value from confirmed scams (LIBR / pro rata).", "Built"],
];

export function AboutPage() {
  return (
    <div className="stack" style={{ gap: 16, maxWidth: 980 }}>
      <h1>Where Vigil sits</h1>
      <div className="card">
        <p style={{ marginTop: 0 }}>
          India already has serious detection: bank EFRMS and AML systems, RBIH's <b>MuleHunter.AI</b> deployed at banks,
          the RBI-led <b>Digital Payments Intelligence Platform (DPIP)</b> being built for shared intelligence, I4C's
          <b> NCRP / 1930</b> reporting and suspect registry, and DoT's Financial Fraud Risk Indicator.
        </p>
        <p><b>Vigil is not another fraud classifier and does not replace any of these.</b> It is the bank-side layer that
          turns those signals — plus local journey and network evidence — into an explainable, proportionate intervention
          at the last reversible moment, then watches where the money goes and feeds that back into the next decision.</p>
        <p className="small muted" style={{ marginBottom: 0 }}>Vigil has no access to RBI, NPCI, RBIH or I4C systems. External intelligence in this demo is simulated and labelled as such.</p>
      </div>
      <div className="card">
        <table className="data">
          <thead><tr><th>Layer</th><th>What happens</th><th>In this prototype</th></tr></thead>
          <tbody>{ROWS.map(([a, b, c]) => <tr key={a}><td><b>{a}</b></td><td>{b}</td><td className="small">{c}</td></tr>)}</tbody>
        </table>
      </div>
      <div className="small muted">Full module-by-module positioning: docs/REAL_WORLD_POSITIONING.md · limitations: docs/KNOWN_LIMITATIONS.md</div>
    </div>
  );
}
