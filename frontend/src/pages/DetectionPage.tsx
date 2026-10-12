// DETECTION & MODELS (v9) — how Vigil finds mule accounts, read top to bottom:
//   1 what the detectors see right now (live) → 2 did we catch the injected attacks (graded against simulator ground
//   truth) → 3 every account, every detector → 4 how good the models are (SYNTHETIC VALIDATION).
// Every chart carries a plain-language caption: what it shows, how to read it, and what it says right now. Model outputs
// (RF · GNN · drift · early warning · pattern memory) are corroborating evidence only; the payment tier comes from the
// transparent policy engine. Traffic volume lives on the Overview and decisions by tier on Governance (not repeated here).
import { useCallback, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { AccountStatus, IntelOverview, LiveUniverse, ModelInfo, RingRow } from "../api/types";
import {
  FlaggedPerFamilyChart, ModelDriversChart, ModelMetricsChart, PerAttackRecallChart, RunSpeedChart, RunsByPatternChart, SHAP_HELP,
  ThresholdChart, modelHeadline, useModelDrivers,
} from "../components/DetectionCharts";
import { RoleIcon } from "../components/intel";
import { AttackHistory, LastAttackResult } from "../components/live/AttackResults";
import { ModelCard, ModelComparison, Synthetic } from "../components/ModelCard";
import { AccountScoring } from "../components/OverviewAnalytics";
import { useConsoleEvents } from "../components/Shell";
import { Async, Bar, Explain, Metric, PageHead, Panel } from "../components/ui";
import { handle, pct } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";
import { msLabel, useAttackRuns, useLiveStats } from "../lib/live";
import { FAMILY, ROLE_LABEL, isRisky, scoreStatus } from "../lib/status";

type Obj = Record<string, unknown>;
const obj = (v: unknown): Obj => (v && typeof v === "object" && !Array.isArray(v) ? (v as Obj) : {});
const fx = (v: number | null, d: number) => (v === null ? "—" : v.toFixed(d));
const MODEL_NAME: Record<string, string> = { random_forest: "Random Forest", gnn: "Graph neural network", rules: "Rule engine", drift: "Drift", pattern_memory: "Pattern memory" };

function Sec({ n, title, d }: { n: number; title: string; d: string }) {
  return <div className="det-sec"><span className="n">{n}</span><h2>{title}</h2><span className="d">{d}</span></div>;
}

export function DetectionPage() {
  const nav = useNavigate();
  const overview = useLoad<IntelOverview>(api.intelOverview);
  const models = useLoad<ModelInfo[]>(api.intelModels);
  const ring = useLoad<RingRow[]>(api.ringwatch);
  const universe = useLoad<LiveUniverse>(() => api.universe({ history: 0 }));
  const runs = useAttackRuns();
  const stats = useLiveStats(5000);
  const [picked, setPicked] = useState<string | null>(null);
  const refresh = useDebounced(() => { overview.reload(); models.reload(); }, 800);
  const refreshRing = useDebounced(() => ring.reload(), 1500);
  const refreshUni = useDebounced(() => universe.reload(), 2500);
  useConsoleEvents((e) => {
    if (e.type === "intel.updated" || e.type === "demo.reset" || e.type === "attack.run_updated") refresh();
    if (["ringwatch.scan", "taint.updated", "demo.reset", "attack.run_updated"].includes(e.type)) refreshRing();
    if (["intel.account_status", "demo.reset", "attack.run_updated"].includes(e.type)) refreshUni();
  });

  // ── live derived values ──
  const accts = useMemo(() => (universe.data?.accounts ?? []).filter((a) => a.kind === "customer"), [universe.data]);
  const liveStatus = useMemo(() => new Map(accts.map((a) => [a.id, a.status])), [accts]);
  const statusOf = useCallback((id: string): AccountStatus | null => liveStatus.get(id) ?? null, [liveStatus]);
  const agreeing = accts.filter((a) => (a.families_flagging ?? 0) >= 2).length;
  const subjects = useMemo(() => {
    const risky = accts.filter((a) => isRisky(a.status)).sort((p, q) => (q.model_risk ?? 0) - (p.model_risk ?? 0));
    const list = risky.length ? risky.slice(0, 5) : [...accts].sort((p, q) => (q.model_risk ?? 0) - (p.model_risk ?? 0)).slice(0, 3);
    return list.map((a) => a.id);
  }, [accts]);
  const drivers = useModelDrivers(subjects);
  const famRows = Object.entries(overview.data?.detector_agreement ?? {}).sort((a, b) => b[1] - a[1]);
  const topUp = drivers.agg?.cats.filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])[0] ?? null;
  const topDown = drivers.agg?.cats.filter(([, v]) => v < 0).sort((a, b) => a[1] - b[1])[0] ?? null;
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

  // ── runs ──
  const done = useMemo(() => [...(runs.data ?? [])].filter((r) => r.status === "completed").sort((a, b) => a.started_at.localeCompare(b.started_at)).slice(-12), [runs.data]);
  const byType = stats.data?.runs_by_type ?? [];
  const caughtTypes = byType.filter((x) => x.detected_runs > 0).length;
  const thr = stats.data?.threshold_history ?? [];
  const lastThr = thr[thr.length - 1];
  const medDetect = done.length ? [...done].map((r) => r.detection_ms ?? 0).sort((a, b) => a - b)[Math.floor((done.length - 1) / 2)] : null;
  const avgRecall = done.length ? done.reduce((a, r) => a + (r.recall ?? 0), 0) / done.length : null;

  // ── models ──
  const ms = models.data ?? [];
  const bestPr = [...ms].filter((m) => typeof obj(m.metrics).pr_auc === "number").sort((a, b) => (obj(b.metrics).pr_auc as number) - (obj(a.metrics).pr_auc as number))[0];
  const rf = ms.find((m) => m.family === "random_forest");
  const rfWeak = rf ? Object.entries(obj(rf.per_attack)).map(([k, v]) => [k, obj(v).recall] as [string, unknown])
    .filter(([, v]) => typeof v === "number").sort((a, b) => (a[1] as number) - (b[1] as number))[0] : undefined;

  return (
    <>
      <PageHead crumb="Intelligence" title="Detection & models"
        lede="How Vigil finds mule accounts. Read it top to bottom: what the detectors see right now, whether the attacks you injected were caught, every account's scores, and how good the models are." />

      <div className="det-intro">
        Vigil runs <b>eight independent detector families</b> on every account: the rule engine and RingWatch network rules, two machine-learning
        models (Random Forest and a graph neural network), behavioural drift, early warning, pattern memory and the external registry (simulated).
        {" "}<b>One family alone never makes an account "flagged"</b>: a busy shop trips the rules and a salaried customer shows drift. An account gets a
        status only when independent families agree, and "flagged" also needs money moving onward. <b>Models never decide a payment</b>: the transparent
        policy engine does, and the models corroborate it.
      </div>

      {/* ── 1 · right now ─────────────────────────────────────────────── */}
      <Sec n={1} title="What the detectors see right now" d="Live: every chart here updates as payments are scored." />
      <div className="det-grid">
        <Panel title="Which detectors are flagging accounts?" q={overview.data ? `graph v${overview.data.graph_version}` : undefined}>
          <Explain shows="How many accounts each detector family flags at this moment, counting every family on its own."
            read="A longer bar means that detector flags more accounts. The counts overlap: one account can be flagged by several families. What matters is agreement, because an account needs two or more families before it gets a status."
            now={famRows.length ? <>{FAMILY[famRows[0][0] as keyof typeof FAMILY]?.label ?? famRows[0][0]} flags the most accounts ({famRows[0][1]}){famRows[0][0] === "rules" ? ", mostly busy shops and customers, which is why rules alone never set a status" : ""}. {agreeing} account{agreeing === 1 ? " has" : "s have"} two or more families agreeing.</> : undefined} />
          <div className="chart-shell"><FlaggedPerFamilyChart overview={overview.data} /></div>
        </Panel>

        <Panel title="Why does the model think these accounts are mules?" actions={<span className="stamp-sv">SHAP</span>}>
          <Explain shows={<>What pushed the Random Forest's score up or down for the {drivers.agg?.n ?? subjects.length} riskiest accounts right now, grouped into plain categories (SHAP values).</>}
            read="Red bar: this behaviour made the accounts look more like mules. Blue bar: it made them look normal. Longer means stronger. Hover a bar to see what the category measures. SHAP explains the model's opinion, not the payment decision."
            now={topUp ? <>The strongest push is <b style={{ minWidth: 0, textTransform: "none", letterSpacing: 0, fontSize: 12.5, color: "var(--ink)" }}>{topUp[0]}</b>: {SHAP_HELP[topUp[0]] ?? "see the account page"}.{topDown ? ` ${topDown[0]} pulls the other way.` : ""}</> : undefined} />
          <div className="chart-shell"><ModelDriversChart agg={drivers.agg} err={drivers.err} /></div>
          {drivers.agg && <div className="row wrap tight" style={{ marginTop: 8 }}>{drivers.agg.ids.map((id) => <Link key={id} className="tag mono" to={`/investigations/account/${encodeURIComponent(id)}`}>{handle(id)}</Link>)}</div>}
        </Panel>

        <Panel title="Which network rules are firing?" q="RingWatch · on the payment path">
          <Explain shows="The transparent money-flow rules the payment engine itself uses (fan-in, pass-through, fast chains, circular flow …) and how many accounts trip each one."
            read="One row per rule; the number is how many accounts trip it now. These rules feed the network part of every payment's risk score, so they directly change what a customer sees."
            now={ring.data ? `${ring.data.length} account${ring.data.length === 1 ? "" : "s"} score 0.30 or more on RingWatch${ruleCounts[0] ? `; the most common rule is "${ruleCounts[0][0]}"` : ""}.` : undefined} />
          {ruleCounts.length === 0 ? <div className="empty">No network rule fires on any account.</div> : (
            <div className="stack tight" style={{ gap: 6 }}>
              {ruleCounts.map(([l, v]) => (
                <div key={l} className="barrow" title={v.rule}><span className="lbl">{l}</span><Bar value={v.n} max={Math.max(1, ruleCounts[0][1].n)} /><span className="val">{v.n}</span></div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <div className="det-grid">
        <Panel title="Who is suddenly behaving differently?" q="early warning">
          <Explain shows="Accounts whose recent activity changed sharply compared with everyone else: bursts of new payees, inflow spikes, a new account suddenly busy."
            read="The score is relative to the rest of the population, not a probability. Signals say what changed. Behaviour change alone is not mule evidence: a scam victim, or someone who was just paid, shows it too."
            now={overview.data ? `${overview.data.early_warnings.length} account${overview.data.early_warnings.length === 1 ? "" : "s"} raise an early warning.` : undefined} />
          <Async load={overview} what="Early warnings" endpoint="/api/intel/overview">
            {(o) => o.early_warnings.length === 0 ? <div className="empty">No early warning raised.</div> : (
              <table className="dt compact">
                <thead><tr><th>Account</th><th style={{ width: "30%" }}>Score</th><th>What changed</th></tr></thead>
                <tbody>{o.early_warnings.slice(0, 10).map((w) => (
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

        <Panel title="What role does each mule play?" q="inside flagged structure only">
          <Explain shows="Inside a corroborated mule structure, what each account does: collector (gathers money from many), distributor (spreads it to many), entry, exit (cashes out) and coordinator."
            read="Roles are only given to accounts already inside flagged mule structure, so an ordinary account never gets one. The second list is the same idea from the RingWatch rules the payment engine uses." />
          <Async load={overview} what="Role analysis" endpoint="/api/intel/overview">
            {(o) => (
              <div className="stack tight" style={{ gap: 6 }}>
                {Object.entries(o.role_counts).sort((a, b) => b[1] - a[1]).map(([r, n]) => (
                  <div key={r} className="barrow"><span className="lbl"><span className="row tight"><RoleIcon role={r} />{ROLE_LABEL[r] ?? r}</span></span><Bar value={n} max={Math.max(1, ...Object.values(o.role_counts))} /><span className="val">{n}</span></div>
                ))}
              </div>
            )}
          </Async>
          <div className="sect-t" style={{ marginTop: 12 }}>RingWatch structural roles</div>
          <div className="stack tight" style={{ gap: 6 }}>
            {roleCounts.length === 0 ? <div className="xs muted">No account shows network evidence.</div> : roleCounts.map(([r, n]) => (
              <div key={r} className="barrow"><span className="lbl"><span className="row tight"><RoleIcon role={r} />{ROLE_LABEL[r] ?? r}</span></span><Bar value={n} max={Math.max(1, roleCounts[0]?.[1] ?? 1)} /><span className="val">{n}</span></div>
            ))}
          </div>
        </Panel>

        <Panel title="Does anything look like a known mule pattern?" q="pattern memory · not attribution">
          <Explain shows="How closely an account's money-flow shape matches stored signatures of known mule patterns (fan-in, velocity chain, smurfing …)."
            read="The percentage is structural similarity. It means 'looks like', not proof, and never identifies who is behind it."
            now={overview.data ? `${overview.data.pattern_alerts.length} account${overview.data.pattern_alerts.length === 1 ? "" : "s"} resemble a stored signature closely enough to count.` : undefined} />
          <Async load={overview} what="Pattern alerts" endpoint="/api/intel/overview">
            {(o) => o.pattern_alerts.length === 0 ? <div className="empty">No account resembles a known signature.</div> : (
              <div className="stack tight" style={{ gap: 6 }}>
                {o.pattern_alerts.slice(0, 12).map((p) => (
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

      {/* ── 2 · injected attacks ──────────────────────────────────────── */}
      <Sec n={2} title="Did we catch the attacks you injected?" d="Each pattern started from Test inputs is scored live, then graded against the simulator's answer key." />
      <div className="det-intro">
        When you inject a pattern, the simulator knows which accounts are the mules (the <b>answer key</b>, labelled "simulator ground truth"). Vigil never sees
        that list. It scores the payments as they arrive, and when the run ends the result is graded: mules <b>detected</b>, mules <b>missed</b>, ordinary accounts
        wrongly flagged (<b>false positives</b>), and how fast.
      </div>
      <div className="det-grid two">
        <LastAttackResult runs={runs.data} unavailable={runs.unavailable} emptyText="No pattern has been injected since the last reset. Use Test inputs → Inject a mule-network pattern." />
        <AttackHistory runs={runs.data} unavailable={runs.unavailable} />
      </div>
      <div className="det-grid">
        <Panel title="Which attack patterns were caught?">
          <Explain shows="For each pattern you injected: how many times, and how many of those runs had at least one mule flagged."
            read="Grey bar = times injected. Green bar = times caught. Green as tall as grey means that pattern was caught every time."
            now={byType.length ? `${caughtTypes} of ${byType.length} injected pattern${byType.length === 1 ? "" : "s"} caught.` : "Inject a pattern from Test inputs to fill this chart."} />
          <div className="chart-shell"><RunsByPatternChart byType={byType} /></div>
        </Panel>
        <Panel title="How fast, and how complete?">
          <Explain shows="For each run: the time from the first injected payment to the first mule being flagged (bars), and the share of that run's mules that were flagged (red line)."
            read="Shorter bars = faster. A line at 100% = every mule in the run was flagged; lower means some stayed at early warning or were missed."
            now={done.length ? `Typical time to first flag ${msLabel(medDetect)}; on average ${Math.round((avgRecall ?? 0) * 100)}% of injected mules flagged.` : undefined} />
          <div className="chart-shell"><RunSpeedChart runs={done} /></div>
        </Panel>
        <Panel title="How the flagged bar adjusts itself" q="never changes payment tiers">
          <Explain shows="The live threshold model evidence must reach before an account can be flagged, and every time it changed."
            read="After each graded run: if an ordinary account was wrongly flagged, the bar moves up; if mules were missed, it moves down. It stays between 0.45 and 0.85, and only the live status uses it."
            now={lastThr ? `${lastThr.value.toFixed(2)} now. Latest note: ${lastThr.reason}` : undefined} />
          <div className="chart-shell"><ThresholdChart history={thr} /></div>
        </Panel>
      </div>

      {/* ── 3 · every account ─────────────────────────────────────────── */}
      <Sec n={3} title="Every account, every detector" d="All scored accounts with each detector's score side by side. Click a row to investigate." />
      <div className="det-intro">
        <b>Rules</b> = points from six simple checks (for example "received money from 4+ accounts in 72 h") divided by the maximum; 4 of 12 points flags.
        {" "}<b>RF / GNN</b> = the models' probability that the account is a mule (calibrated on synthetic worlds). <b>Drift</b> = how much the account changed
        compared with its own last 45 days. <b>Early warning</b> = sudden behaviour change. <b>Role</b> = its job inside a flagged structure.
        The <b>Rules vs models disagree</b> filter shows accounts where one side says risky and the other does not: worth a second look.
      </div>
      <div style={{ marginTop: 12 }}>
        <AccountScoring statusOf={statusOf} />
      </div>

      {/* ── 4 · model quality ─────────────────────────────────────────── */}
      <Sec n={4} title="How good are the models?" d="Measured on computer-generated test worlds the models never saw in training. Not real-bank accuracy." />
      <div className="banner-val" style={{ margin: "12px 0" }}>
        <span className="stamp">SYNTHETIC VALIDATION</span>
        <span>Every number in this section is measured on synthetic, simulator-generated worlds held out from training. It is <b>not</b> real-bank accuracy.</span>
        <span className="grow" />
        <b>Operational use: corroborating evidence only</b>
      </div>
      <div className="mstrip kpi-row" style={{ marginBottom: 6 }}>
        <Metric k="Random Forest · ROC-AUC" v={fx(modelHeadline(models.data, "random_forest", "roc_auc"), 3)} d={`PR-AUC ${fx(modelHeadline(models.data, "random_forest", "pr_auc"), 3)}`} />
        <Metric k="Graph neural net · ROC-AUC" v={fx(modelHeadline(models.data, "gnn", "roc_auc"), 3)} d={`PR-AUC ${fx(modelHeadline(models.data, "gnn", "pr_auc"), 3)}`} />
        <Metric k="Rule engine · recall" v={fx(modelHeadline(models.data, "rules", "recall"), 2)} d={`precision ${fx(modelHeadline(models.data, "rules", "precision"), 2)}`} />
      </div>
      <div className="ksub" style={{ marginBottom: 4 }}>ROC-AUC: if you pick one mule and one ordinary account at random, how often the model ranks the mule higher (1.0 = always, 0.5 = coin toss).</div>
      <div className="det-grid two">
        <Panel title="How accurate is each detector?" actions={<Synthetic />}>
          <Explain shows="Each detector tested on synthetic worlds it never saw in training."
            read="Precision = of the accounts it flagged, how many really were mules. Recall = of all the mules, how many it found. F1 = the balance of both. PR-AUC = overall ranking quality when mules are rare. 1.0 is perfect."
            now={bestPr ? `${MODEL_NAME[bestPr.family] ?? bestPr.model_id} ranks best (PR-AUC ${(obj(bestPr.metrics).pr_auc as number).toFixed(2)}). The rule engine alone finds ${fx(modelHeadline(models.data, "rules", "recall"), 2)} of mules, which is why the models corroborate it.` : undefined} />
          <div className="chart-shell"><ModelMetricsChart models={models.data} /></div>
        </Panel>
        <Panel title="Which attack types does each detector catch?" actions={<Synthetic />}>
          <Explain shows="For each of the ten attack families, the share of its mules each detector found on the test worlds."
            read="Longer bar = better. A short bar is a blind spot for that detector, which is why several detector families are combined."
            now={rfWeak ? `The Random Forest's hardest family is ${String(rfWeak[0]).replace(/_/g, " ")} (${Math.round((rfWeak[1] as number) * 100)}% found).` : undefined} />
          <div className="chart-shell"><PerAttackRecallChart models={models.data} /></div>
        </Panel>
      </div>

      <div style={{ marginTop: 16 }}>
        <Async load={models} what="Model registry" endpoint="/api/intel/models">
          {(list) => {
            if (list.length === 0) return <div className="empty">No model is registered.</div>;
            const cur = list.find((m) => m.model_id === picked) ?? list[0];
            return (
              <div className="stack">
                <Panel kicker="Model registry" title="All detectors on the same held-out test worlds" flush actions={<Synthetic />}
                       footer="Click a row (or a tab below) for the full validation record: confusion matrix, calibration, per-attack detection, leave-one-attack-out generalisation, leakage audit and global SHAP.">
                  <ModelComparison models={list} picked={cur.model_id} onPick={setPicked} />
                </Panel>
                <div className="tabs">
                  {list.map((m) => <button key={m.model_id} className={m.model_id === cur.model_id ? "on" : ""} onClick={() => setPicked(m.model_id)}>{m.model_id}</button>)}
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
