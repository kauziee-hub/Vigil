// RULE-BASED SCORING + HYBRID ML SCORES — per-account values from /api/intel/scores, with honest value kinds:
// the rule engine is a point score; RF / GNN are calibrated probabilities on synthetic worlds (SYNTHETIC VALIDATION);
// all model values are corroborating evidence and never set the operational tier.
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { AccountStatus, IntelScores, ModelInfo } from "../../api/types";
import { handle } from "../../lib/format";
import { useLoad } from "../../lib/hooks";
import { useThrottled } from "../../lib/live";
import { ACCOUNT_STATUS_LABEL, ROLE_LABEL, STATUS_HEX, scoreStatus } from "../../lib/status";
import { useConsoleEvents } from "../Shell";
import { Panel, Unavailable } from "../ui";

const f = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v.toFixed(3));
const col = (v: number | null | undefined) => (v === null || v === undefined ? undefined : STATUS_HEX[scoreStatus(v)]);

function StatusCell({ s }: { s: AccountStatus | null }) {
  if (!s) return <span className="xs dim">—</span>;
  return <span className={`pill as-${s}`}>{ACCOUNT_STATUS_LABEL[s].toLowerCase()}</span>;
}

export function ScoreTables({ statusOf }: { statusOf: (id: string) => AccountStatus | null }) {
  const scores = useLoad<IntelScores>(api.intelScores);
  const models = useLoad<ModelInfo[]>(api.intelModels);
  const refresh = useThrottled(() => scores.reload(), 5000);
  useConsoleEvents((e) => {
    if (e.type === "intel.updated" || e.type === "demo.reset") scores.reload();
    else if (e.type === "intel.account_status") refresh();
  });

  const rows = useMemo(() => Object.entries(scores.data?.scores ?? {}).map(([id, s]) => ({ id, ...s })), [scores.data]);
  const rules = useMemo(() => rows.filter((r) => r.rules != null).sort((a, b) => (b.rules ?? 0) - (a.rules ?? 0)), [rows]);
  const ml = useMemo(() => rows.filter((r) => r.rf != null || r.gnn != null)
    .sort((a, b) => Math.max(b.rf ?? 0, b.gnn ?? 0) - Math.max(a.rf ?? 0, a.gnn ?? 0)), [rows]);
  const auc = (fam: string) => {
    const m = (models.data ?? []).find((x) => x.family === fam && x.status === "active");
    const v = m?.metrics?.roc_auc;
    return typeof v === "number" ? v.toFixed(3) : "—";
  };
  const hi = rules.filter((r) => (r.rules ?? 0) >= 0.5).length;
  const med = rules.filter((r) => (r.rules ?? 0) >= 0.3 && (r.rules ?? 0) < 0.5).length;

  if (scores.unavailable) {
    return <Panel kicker="Rules · models" title="Per-account scores"><Unavailable what="Per-account detector scores" endpoint="/api/intel/scores" /></Panel>;
  }
  return (
    <div className="grid cols-2 align-start">
      <Panel kicker="Rules" title="Rule-Based Risk Scoring" flush
             footer="Rule engine point score per account (fraction of the rule budget fired). Transparent and on the evidence path; the authorisation tier itself comes from PRIMA's five-dimension assessment.">
        <div className="mstrip dense" style={{ padding: "0 20px 12px" }}>
          <div className="m st-critical"><div className="k">High (≥ 0.50)</div><div className="v">{hi}</div></div>
          <div className="m st-watch"><div className="k">Medium (0.30–0.50)</div><div className="v">{med}</div></div>
          <div className="m"><div className="k">Scored</div><div className="v">{rules.length}</div></div>
        </div>
        <div className="tscroll" style={{ maxHeight: 360 }}>
          <table className="dt compact">
            <thead><tr><th>Account</th><th className="num">Rule score</th><th>Role</th><th>Status</th></tr></thead>
            <tbody>
              {rules.slice(0, 60).map((r) => (
                <tr key={r.id}>
                  <td><Link className="acct" to={`/investigations/account/${encodeURIComponent(r.id)}`}>{handle(r.id)}</Link></td>
                  <td className="num" style={{ color: col(r.rules) }}>{f(r.rules)}</td>
                  <td className="xs">{r.role ? ROLE_LABEL[r.role] ?? r.role : <span className="dim">—</span>}</td>
                  <td><StatusCell s={statusOf(r.id)} /></td>
                </tr>
              ))}
              {scores.data && rules.length === 0 && <tr><td colSpan={4} className="empty">No rule scores.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel kicker="Models" title="Hybrid ML Scores" flush actions={<span className="stamp-sv">SYNTHETIC VALIDATION</span>}
             footer="RF / GNN values are calibrated probabilities on synthetic worlds; drift is a level. Model evidence is corroborating — not used for authorisation.">
        <div className="mstrip dense" style={{ padding: "0 20px 12px" }}>
          <div className="m"><div className="k">RF held-out ROC-AUC</div><div className="v">{auc("random_forest")}</div></div>
          <div className="m"><div className="k">GNN held-out ROC-AUC</div><div className="v">{auc("gnn")}</div></div>
          <div className="m"><div className="k">Accounts scored</div><div className="v">{ml.length}</div></div>
        </div>
        <div className="tscroll" style={{ maxHeight: 360 }}>
          <table className="dt compact">
            <thead><tr><th>Account</th><th className="num">RF</th><th className="num">GNN</th><th className="num">Rules</th><th>Drift</th><th>Status</th></tr></thead>
            <tbody>
              {ml.slice(0, 60).map((r) => (
                <tr key={r.id}>
                  <td><Link className="acct" to={`/investigations/account/${encodeURIComponent(r.id)}`}>{handle(r.id)}</Link></td>
                  <td className="num" style={{ color: col(r.rf) }}>{f(r.rf)}</td>
                  <td className="num" style={{ color: col(r.gnn) }}>{f(r.gnn)}</td>
                  <td className="num">{f(r.rules)}</td>
                  <td className="xs">{r.drift_level ?? "—"}</td>
                  <td><StatusCell s={statusOf(r.id)} /></td>
                </tr>
              ))}
              {scores.data && ml.length === 0 && <tr><td colSpan={6} className="empty">No model scores.</td></tr>}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
