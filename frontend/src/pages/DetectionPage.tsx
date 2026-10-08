// DETECTION & MODELS — what each detector family sees across accounts, and how good the models are on
// SYNTHETIC VALIDATION. Model outputs (RF · GNN · drift · early warning · pattern memory) are corroborating
// evidence only; the operational tier comes from the transparent policy engine. Renders /api/intel/overview,
// /api/intel/models and /api/intel/scores; until those are served it says so and shows the rule engine only.
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { IntelOverview, IntelScores, ModelInfo, RingRow } from "../api/types";
import { FlaggedPerFamilyChart, ModelMetricsChart, PerAttackRecallChart, modelHeadline } from "../components/DetectionCharts";
import { RoleIcon } from "../components/intel";
import { ModelCard, ModelComparison, Synthetic } from "../components/ModelCard";
import { useConsoleEvents } from "../components/Shell";
import { Async, Bar, Metric, PageHead, Panel, Pill, Seg } from "../components/ui";
import { handle, pct } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";
import { ROLE_LABEL, levelStatus, scoreStatus } from "../lib/status";

type SortKey = "max" | "rules" | "rf" | "gnn";

export function DetectionPage() {
  const nav = useNavigate();
  const overview = useLoad<IntelOverview>(api.intelOverview);
  const models = useLoad<ModelInfo[]>(api.intelModels);
  const scores = useLoad<IntelScores>(api.intelScores);
  const ring = useLoad<RingRow[]>(api.ringwatch);
  const [sort, setSort] = useState<SortKey>("max");
  const [picked, setPicked] = useState<string | null>(null);
  const refresh = useDebounced(() => { overview.reload(); models.reload(); scores.reload(); }, 800);
  const refreshRing = useDebounced(() => ring.reload(), 1500);
  useConsoleEvents((e) => {
    if (e.type === "intel.updated" || e.type === "demo.reset") refresh();
    if (["ringwatch.scan", "taint.updated", "demo.reset"].includes(e.type)) refreshRing();
  });

  const scoreRows = useMemo(() => {
    const rows = Object.entries(scores.data?.scores ?? {}).map(([id, s]) => ({ id, ...s, max: Math.max(s.rules ?? 0, s.rf ?? 0, s.gnn ?? 0) }));
    return rows.sort((a, b) => ((b[sort] ?? -1) as number) - ((a[sort] ?? -1) as number));
  }, [scores.data, sort]);
  const ruleCounts = useMemo(() => {
    const c = new Map<string, { n: number; rule: string }>();
    (ring.data ?? []).forEach((r) => r.labels.forEach((l, i) => c.set(l, { n: (c.get(l)?.n ?? 0) + 1, rule: r.rules[i] ?? "" })));
    return [...c.entries()].sort((a, b) => b[1].n - a[1].n);
  }, [ring.data]);
  const roleCounts = useMemo(() => {
    const c = new Map<string, number>();
    (ring.data ?? []).forEach((r) => c.set(r.role ?? "unclassified", (c.get(r.role ?? "unclassified") ?? 0) + 1));
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  }, [ring.data]);
  const intelDown = overview.unavailable && models.unavailable;

  return (
    <>
      <PageHead crumb="Intelligence" title="Detection & models"
        lede="What each detector family sees across the network, and how well the models perform on synthetic validation. Rules decide; models corroborate." />

      <div className="banner-val" style={{ marginBottom: 12 }}>
        <span className="stamp">SYNTHETIC VALIDATION</span>
        <span>Every model metric on this page is measured on synthetic, simulator-generated worlds, evaluated on held-out worlds never seen in training. It is <b>not</b> real-bank accuracy.</span>
        <span className="grow" />
        <b>Operational use: corroborating evidence only</b>
        <span className="xs muted">RF · GNN · drift · early warning · pattern memory never set a payment's tier.</span>
      </div>

      <div className="mstrip kpi-row" style={{ marginBottom: 20 }}>
        <Metric k={<>RF held-out ROC-AUC</>} v={fx(modelHeadline(models.data, "random_forest", "roc_auc"), 3)} d={`PR-AUC ${fx(modelHeadline(models.data, "random_forest", "pr_auc"), 3)} · synthetic validation`} />
        <Metric k={<>GNN held-out ROC-AUC</>} v={fx(modelHeadline(models.data, "gnn", "roc_auc"), 3)} d={`PR-AUC ${fx(modelHeadline(models.data, "gnn", "pr_auc"), 3)} · synthetic validation`} />
        <Metric k="Rule engine recall" v={fx(modelHeadline(models.data, "rules", "recall"), 2)} d={`precision ${fx(modelHeadline(models.data, "rules", "precision"), 2)} · point score, not a probability`} />
        <Metric k="Accounts scored" v={scores.data ? String(scoreRows.length) : "—"} d={scores.data ? `graph v${scores.data.graph_version}` : scores.unavailable ? "/api/intel/scores not served" : "loading"} />
        <Metric k="RingWatch flags" v={ring.data ? String(ring.data.length) : "—"} status={ring.data && ring.data.length ? "high" : undefined} d="operational · score ≥ 0.30" />
        <Metric k="Early warnings" v={overview.data ? String(overview.data.early_warnings.length) : "—"} status={overview.data && overview.data.early_warnings.length ? "watch" : undefined} d="behaviour change · not mule evidence alone" />
      </div>

      <div className="grid cols-3 align-start" style={{ marginBottom: 20 }}>
        <Panel kicker="Live · all families" title="Accounts flagged per family" q={overview.data ? `graph v${overview.data.graph_version}` : undefined}>
          <div className="chart-shell"><FlaggedPerFamilyChart overview={overview.data} /></div>
        </Panel>
        <Panel kicker="Held-out test worlds" title="Metrics by model" actions={<Synthetic />}>
          <div className="chart-shell"><ModelMetricsChart models={models.data} /></div>
        </Panel>
        <Panel kicker="Per attack family" title="Recall · RF vs GNN vs rules" actions={<Synthetic />}>
          <div className="chart-shell"><PerAttackRecallChart models={models.data} /></div>
        </Panel>
      </div>

      {intelDown && (
        <div style={{ marginBottom: 12 }}>
          <Unavail />
        </div>
      )}

      <div className="grid cols-3 align-start">
        <Panel kicker="Rule engine · RingWatch" title="Network rules firing now" flush q="operational — feeds every payment's recipient-network dimension">
          <div className="sect">
            {ruleCounts.length === 0 ? <div className="xs muted">No network rule fires on any account.</div> : ruleCounts.map(([l, v]) => (
              <div key={l} className="barrow" title={v.rule}><span className="lbl">{l}</span><Bar value={v.n} max={Math.max(1, ruleCounts[0][1].n)} /><span className="val">{v.n}</span></div>
            ))}
          </div>
        </Panel>

        <Panel kicker="Early warning" title="Behaviour change — not mule evidence on its own" flush>
          <Async load={overview} what="Early warnings" endpoint="/api/intel/overview">
            {(o) => o.early_warnings.length === 0 ? <div className="empty">No early warning raised.</div> : (
              <table className="dt compact">
                <thead><tr><th>Account</th><th style={{ width: "30%" }}>Score</th><th>Signals</th></tr></thead>
                <tbody>{o.early_warnings.slice(0, 12).map((w) => (
                  <tr key={w.account_id} className="click" onClick={() => nav(`/investigations/account/${encodeURIComponent(w.account_id)}`)}>
                    <td className="xs">{handle(w.account_id)}</td>
                    <td><span className="row tight"><span className="grow"><Bar value={w.score} status={scoreStatus(w.score)} /></span><span className="mono xs">{w.score.toFixed(2)}</span></span></td>
                    <td className="xs muted">{w.signals.join(" · ")}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </Async>
        </Panel>

        <Panel kicker="Roles" title="Mule role analysis" flush>
          <Async load={overview} what="Role analysis" endpoint="/api/intel/overview">
            {(o) => (
              <div className="sect">
                {Object.entries(o.role_counts).sort((a, b) => b[1] - a[1]).map(([r, n]) => (
                  <div key={r} className="barrow"><span className="lbl"><span className="row tight"><RoleIcon role={r} />{ROLE_LABEL[r] ?? r}</span></span><Bar value={n} max={Math.max(1, ...Object.values(o.role_counts))} /><span className="val">{n}</span></div>
                ))}
              </div>
            )}
          </Async>
          <div className="sect">
            <div className="sect-t">RingWatch structural roles (operational)</div>
            {roleCounts.map(([r, n]) => (
              <div key={r} className="barrow"><span className="lbl"><span className="row tight"><RoleIcon role={r} />{ROLE_LABEL[r] ?? r}</span></span><Bar value={n} max={Math.max(1, roleCounts[0]?.[1] ?? 1)} /><span className="val">{n}</span></div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="grid cols-ms align-start" style={{ marginTop: 12 }}>
        <Panel kicker="Per-account scores" title="Rules · Random Forest · GNN side by side" flush
               q={scores.data ? `${scoreRows.length} accounts in the default scene · graph v${scores.data.graph_version}` : undefined}
               actions={<Seg options={[["max", "Max"], ["rules", "Rules"], ["rf", "RF"], ["gnn", "GNN"]]} value={sort} onChange={setSort} />}
               footer="Rules = rule-engine point score (points ÷ maximum; hand-set thresholds, not a probability). RF / GNN = calibrated on synthetic worlds — not a real-world probability. Model evidence never sets a payment's tier.">
          <Async load={scores} what="Per-account model scores" endpoint="/api/intel/scores">
            {() => scoreRows.length === 0 ? <div className="empty">No scored accounts.</div> : (
              <div className="tscroll" style={{ maxHeight: 460 }}>
                <table className="dt compact">
                  <thead><tr><th>Account</th><th>Rules</th><th>RF</th><th>GNN</th><th>Drift</th><th>Role</th><th>EW</th></tr></thead>
                  <tbody>{scoreRows.slice(0, 60).map((r) => (
                    <tr key={r.id} className="click" onClick={() => nav(`/investigations/account/${encodeURIComponent(r.id)}`)}>
                      <td className="xs">{handle(r.id)}</td>
                      {(["rules", "rf", "gnn"] as const).map((k) => (
                        <td key={k} style={{ width: "16%" }}>{r[k] == null ? <span className="dim xs">—</span> :
                          <span className="row tight"><span className="grow"><Bar value={r[k]} status={scoreStatus(r[k])} /></span><span className="mono xs">{r[k]!.toFixed(2)}</span></span>}</td>
                      ))}
                      <td>{r.drift_level ? <Pill status={levelStatus(r.drift_level)}>{r.drift_level}</Pill> : <span className="dim xs">—</span>}</td>
                      <td className="xs"><span className="row tight"><RoleIcon role={r.role} />{r.role ? ROLE_LABEL[r.role] ?? r.role : "—"}</span></td>
                      <td className="xs">{r.early_warning ? <Pill status="watch">EW</Pill> : <span className="dim">—</span>}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </Async>
        </Panel>
        <Panel kicker="Pattern memory" title="Structural similarity to known signatures" flush q="not criminal attribution">
          <Async load={overview} what="Pattern alerts" endpoint="/api/intel/overview">
            {(o) => o.pattern_alerts.length === 0 ? <div className="empty">No account resembles a known signature.</div> : (
              <div className="sect">
                {o.pattern_alerts.slice(0, 14).map((p) => (
                  <div key={`${p.account_id}-${p.match.signature_id}`} className="barrow" title={`${p.match.description}${p.match.note ? ` — ${p.match.note}` : ""}`}>
                    <span className="lbl"><Link to={`/investigations/account/${encodeURIComponent(p.account_id)}`}>{handle(p.account_id)}</Link> · {p.match.name}</span>
                    <Bar value={p.match.similarity} status={p.match.similarity >= 0.75 ? "high" : p.match.similarity >= 0.5 ? "watch" : undefined} />
                    <span className="val">{pct(p.match.similarity)}</span>
                  </div>
                ))}
              </div>
            )}
          </Async>
        </Panel>
      </div>

      <div style={{ marginTop: 12 }}>
        <Async load={models} what="Model registry" endpoint="/api/intel/models">
          {(ms) => {
            if (ms.length === 0) return <div className="empty">No model is registered.</div>;
            const cur = ms.find((m) => m.model_id === picked) ?? ms[0];
            return (
              <div className="stack">
                <Panel kicker="Model registry" title="All detectors on the same held-out test worlds" flush
                       actions={<Synthetic />}
                       footer="Click a row for the full validation record: confusion matrix, calibration, per-attack detection, leave-one-attack-out generalisation, leakage audit and global SHAP.">
                  <ModelComparison models={ms} picked={cur.model_id} onPick={setPicked} />
                </Panel>
                <div className="tabs">
                  {ms.map((m) => <button key={m.model_id} className={m.model_id === cur.model_id ? "on" : ""} onClick={() => setPicked(m.model_id)}>{m.model_id}</button>)}
                </div>
                <ModelCard m={cur} />
              </div>
            );
          }}
        </Async>
      </div>
    </>
  );
}

const fx = (v: number | null, d: number) => (v === null ? "—" : v.toFixed(d));

function Unavail() {
  return (
    <div className="unavail" role="status">
      <span className="ic">∅</span>
      <div>
        <b>Detection-intelligence layer: not yet available.</b> This server does not serve <span className="mono">/api/intel/overview</span>, <span className="mono">/api/intel/models</span> or <span className="mono">/api/intel/scores</span> yet,
        so model panels below show nothing rather than estimates. What is shown live is the operational rule engine (RingWatch), which is on the authorisation path.
        Once merged, this page shows the Random Forest and GNN registry with synthetic-validation metrics, detector agreement, early warnings, pattern memory and role analysis.
      </div>
    </div>
  );
}
