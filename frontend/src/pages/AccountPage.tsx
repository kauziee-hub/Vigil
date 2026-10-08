// ACCOUNT INVESTIGATION (v3, the reference's investigation layout + Vigil's PRIMA evidence):
// score tiles (live status · RingWatch network score · consensus · role / RF · GNN · rules · early warning) → profile line →
// risk over time (sampled live) + SHAP breakdown (explains the MODEL) → why flagged · rules fired · early-warning signals +
// window features (now · baseline · SHAP) → recent transactions + neighbours · alerts · SIMULATOR GROUND TRUTH →
// PRIMA risk evolution (decisions as sender, markers say why) + payment intents → full model evidence → account record.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  AccountIntel, AccountSummary, DetectorFamily, DetectorResult, GraphScene, LedgerTx, PolicyView, RiskPoint, RiskSignal, TransactionIntent,
} from "../api/types";
import { CH, ChartCanvas, baseOptions } from "../components/charts";
import { SignalRow } from "../components/Decision";
import { AccountIntelView, RoleIcon, detectorStatus } from "../components/intel";
import { AccountAlerts, GroundTruth, LiveStatusLine, useAccountLive } from "../components/live/AccountLivePanel";
import { RiskEvolution } from "../components/Replay";
import { SceneThumb } from "../components/SceneThumb";
import { useConsoleEvents } from "../components/Shell";
import { Async, ErrorNote, KV, Loading, PageHead, Panel, Pill, Seg, Sim, StatePill, TierPill, Unavailable } from "../components/ui";
import { clean, evValue, formatINR, formatStamp, formatTime, handle, humanKey } from "../lib/format";
import { nodeStatus } from "../lib/graphStyle";
import { useLoad } from "../lib/hooks";
import { useThrottled } from "../lib/live";
import { ACCOUNT_STATUS_LABEL, FAMILY, KIND_LABEL, ROLE_LABEL, STATUS_LABEL, scoreStatus, type Status } from "../lib/status";

type Sample = { t: string; rf: number | null; gnn: number | null; rules: number | null; ew: number | null; net: number | null };
type Fired = { rule_id?: string; label?: string; points?: number; reason?: string };

const det = (x: AccountIntel | null, f: DetectorFamily): DetectorResult | null =>
  x?.detectors.find((d) => d.family === f && d.status === "ok") ?? null;
const val = (d: DetectorResult | null) => (d && d.value !== null ? d.value : null);

export function AccountPage() {
  const { accountId = "" } = useParams();
  const nav = useNavigate();
  const [hops, setHops] = useState<"1" | "2">("1");
  const acct = useLoad<AccountSummary>(() => api.account(accountId), [accountId]);
  const net = useLoad(() => api.accountNetwork(accountId), [accountId]);
  const intel = useLoad<AccountIntel>(() => api.intelAccount(accountId), [accountId]);
  const rt = useLoad<RiskPoint[]>(() => api.riskTimeline(accountId), [accountId]);
  const txs = useLoad<LedgerTx[]>(() => api.accountTransactions(accountId), [accountId]);
  const intents = useLoad<TransactionIntent[]>(() => api.intents(accountId), [accountId]);
  const scene = useLoad<GraphScene>(() => api.scene({ focus: accountId, hops: Number(hops), cap: 60 }), [accountId, hops]);
  const policy = useLoad<PolicyView>(api.policy);
  const live = useAccountLive(accountId);

  // Event-driven refresh, throttled: postings touching this account re-score it (intel + RingWatch + ledger + scene).
  const refreshScores = useThrottled(() => { net.reload(); intel.reload(); txs.reload(); scene.reload(); }, 4000);
  const refreshDecisions = useThrottled(() => { rt.reload(); intents.reload(); }, 1500);
  useConsoleEvents((e) => {
    const data = e.data as { sender_id?: string; recipient_id?: string; account_id?: string } | null;
    const mine = !!data && (data.sender_id === accountId || data.recipient_id === accountId || data.account_id === accountId);
    if ((e.type === "ledger.posted" || e.type === "intel.tx_scored" || e.type === "intel.account_status") && mine) refreshScores();
    else if ((e.type === "decision.created" || e.type === "intent.updated") && mine) { refreshDecisions(); refreshScores(); }
    else if (e.type === "taint.updated") refreshScores();
    else if (e.type === "demo.reset") { refreshScores(); refreshDecisions(); }
  });

  // Risk over time: there is no stored per-account score history for the model families, so the chart samples the
  // backend's own values each time they are re-computed while this page is open (honestly labelled as such).
  const [series, setSeries] = useState<Sample[]>([]);
  useEffect(() => { setSeries([]); }, [accountId]);
  useEffect(() => {
    const x = intel.data;
    if (!x || x.account_id !== accountId) return;
    const s: Sample = {
      t: x.as_of, rf: val(det(x, "random_forest")), gnn: val(det(x, "gnn")), rules: val(det(x, "rules")),
      ew: val(det(x, "early_warning")), net: net.data?.account_id === accountId ? net.data.score : val(det(x, "ringwatch")),
    };
    setSeries((xs) => (xs.length && xs[xs.length - 1].t === s.t ? [...xs.slice(0, -1), s] : [...xs, s].slice(-120)));
  }, [intel.data, net.data, accountId]);

  const node = scene.data?.nodes.find((n) => n.id === accountId) ?? null;
  const flows = useMemo(() => {
    const list = txs.data ?? [];
    let inn = 0, out = 0;
    list.forEach((t) => { if (t.recipient_id === accountId) inn += t.amount_paise; else if (t.sender_id === accountId) out += t.amount_paise; });
    return { inn, out, n: list.length };
  }, [txs.data, accountId]);
  const neighbours = useMemo(() => {
    const s = scene.data;
    if (!s) return [];
    const byId = new Map(s.nodes.map((n) => [n.id, n]));
    return s.edges.filter((e) => e.source === accountId || e.target === accountId).map((e) => {
      const other = e.source === accountId ? e.target : e.source;
      return { id: other, dir: e.source === accountId ? "out" as const : "in" as const, count: e.count, amount: e.amount_paise, tainted: e.tainted_paise, node: byId.get(other) ?? null };
    }).sort((a, b) => b.amount - a.amount);
  }, [scene.data, accountId]);

  if (acct.error && !acct.data) {
    return (
      <>
        <PageHead crumb={<Link to="/investigations">05 · Investigations</Link>} title={handle(accountId)} />
        <ErrorNote error={acct.error} />
      </>
    );
  }
  if (!acct.data) return <Loading text="Loading account" />;
  const a = acct.data;
  const x = intel.data?.account_id === accountId ? intel.data : null;
  const score = net.data?.score ?? null;
  const signals = (net.data?.signals ?? []) as RiskSignal[];
  const ext = net.data?.external_intel as { status?: string; risk_score?: number; reason_codes?: string[]; source?: string } | null | undefined;
  const netFeatures = Object.entries(net.data?.features ?? {}).filter(([, v]) => v !== null && typeof v !== "object");
  const st: Status = node ? nodeStatus(node) : scoreStatus(score);
  const rf = det(x, "random_forest"), gnn = det(x, "gnn"), rules = det(x, "rules"), ew = det(x, "early_warning");
  const fired = (((rules?.detail ?? {}) as { fired?: Fired[] }).fired ?? []);
  const ewSignals = (((ew?.detail ?? {}) as { signals?: string[] }).signals ?? []);
  const role = x?.role.role && x.role.role !== "unclassified" ? x.role.role : live.role ?? node?.role ?? null;
  const flaggedLike = live.status === "flagged" || live.status === "held" || live.status === "confirmed_fraud" || (x?.consensus.families_flagging ?? 0) >= 2 || signals.length > 0;

  return (
    <>
      <PageHead crumb={<><Link to="/investigations">05 · Investigations</Link> / account investigation</>}
        title={<span className="row wrap tight"><RoleIcon role={role} size={22} /><span>{a.display_name}</span><span className="mono sm muted">{a.id}</span></span>}
        lede={<span className="row wrap tight">
          {live.status ? <span className={`pill as-${live.status}`}>{ACCOUNT_STATUS_LABEL[live.status]}</span> : <Pill status={st}>{STATUS_LABEL[st]}</Pill>}
          {role && role !== "normal" && <span className="tag">{ROLE_LABEL[role] ?? role}</span>}
          {node?.labelled && <Pill status="fraud">confirmed fraud</Pill>}
          {a.held_paise > 0 && <Pill status="held">held {formatINR(a.held_paise)}</Pill>}
          {a.is_demo_customer && <span className="tag">demo customer</span>}
          <span>{a.persona ?? a.kind}</span>
        </span>}
        actions={<>
          <Link className="btn sm" to={`/network?focus=${encodeURIComponent(a.id)}&hops=1`}>3D network · 1-hop</Link>
          <Link className="btn sm ghost" to={`/network?focus=${encodeURIComponent(a.id)}&hops=2`}>2-hop</Link>
          {a.is_demo_customer && <Link className="btn sm ghost" to={`/guard?as=${encodeURIComponent(a.id)}`}>Transaction Guard</Link>}
        </>} />

      {/* score tiles — operational (top row) then model evidence (second row) */}
      <div className="mstrip inv-tiles">
        <Tile k="Live status" v={live.status ? <span className={`pill lg as-${live.status}`}>{ACCOUNT_STATUS_LABEL[live.status]}</span> : "—"}
              d={live.lastActive ? `last active ${formatTime(live.lastActive)}` : live.universeUnavailable ? "/api/live/universe not served" : "no posting in the live window"} />
        <Tile k="Network score · RingWatch" v={score === null ? "—" : score.toFixed(2)} st={score === null ? undefined : scoreStatus(score)}
              d={`operational · ${signals.length} rule${signals.length === 1 ? "" : "s"} fired`} />
        <Tile k="Detector consensus" v={x ? `${x.consensus.families_flagging} / ${x.consensus.families_evaluated}` : "—"}
              st={x ? (x.consensus.agreement === "strong" ? "critical" : x.consensus.agreement === "moderate" ? "high" : x.consensus.agreement === "weak" ? "watch" : undefined) : undefined}
              d={x ? `${x.consensus.agreement} agreement · corroborating` : intel.unavailable ? "intel not served" : "loading"} />
        <Tile k="Role" v={<span className="row tight"><RoleIcon role={role} size={16} />{role ? ROLE_LABEL[role] ?? role : "—"}</span>}
              d={x ? clean(x.role.reason) : "role analysis"} small />
        <ModelTile k="Random Forest" d={rf} />
        <ModelTile k="GNN (GAT)" d={gnn} />
        <ModelTile k="Rule engine" d={rules} />
        <ModelTile k="Early warning" d={ew} />
      </div>

      <div className="profile-line">
        <span>opened {new Date(a.opened_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}</span>
        <span>{a.devices.length} device{a.devices.length === 1 ? "" : "s"}{a.primary_device ? ` · primary ${a.primary_device}` : ""}</span>
        <span>balance {formatINR(a.balance_paise)} · available {formatINR(a.available_paise)}</span>
        {a.held_paise > 0 && <span className="hl-held">held {formatINR(a.held_paise)} (scoped)</span>}
        <span>{txs.data ? `${flows.n} postings · in ${formatINR(flows.inn)} · out ${formatINR(flows.out)}` : "postings loading"}</span>
        <span className={node && node.taint_paise > 0 ? "hl-fraud" : ""}>traced value {node ? formatINR(node.taint_paise) : "—"} (LIBR)</span>
        <span>daily limit {formatINR(a.daily_limit_paise)}</span>
        <span>trusted contact {a.trusted_contact ? `${a.trusted_contact.name} (${a.trusted_contact.relation})` : "none"}</span>
      </div>

      <div className="grid cols-2 align-start section-gap">
        <Panel kicker="Risk over time" title="Scores as they are re-computed"
               q={`${series.length} sample${series.length === 1 ? "" : "s"} since this page opened`}
               footer="Each point is the backend's own value at that moment (RingWatch network score = operational; RF · GNN · rules · early warning = model evidence). Model families keep no stored score history, so the series starts when the page opens and grows as this account transacts.">
          {intel.unavailable && !net.data ? <Unavailable what="Risk samples" endpoint="/api/intel/accounts/{id}" /> : (
            <div className="chart-shell">
              <ChartCanvas type="line" height={250} empty="Waiting for the first score…"
                data={{ labels: series.map((s) => formatTime(s.t)), datasets: [
                  { label: "Network · RingWatch", data: series.map((s) => s.net), borderColor: CH.red, backgroundColor: CH.red, tension: 0.25, pointRadius: 3, borderWidth: 2 },
                  { label: "Random Forest", data: series.map((s) => s.rf), borderColor: CH.blue, backgroundColor: CH.blue, tension: 0.25, pointRadius: 2 },
                  { label: "GNN", data: series.map((s) => s.gnn), borderColor: CH.magenta, backgroundColor: CH.magenta, tension: 0.25, pointRadius: 2 },
                  { label: "Rules (pts ÷ max)", data: series.map((s) => s.rules), borderColor: CH.teal, backgroundColor: CH.teal, tension: 0.25, pointRadius: 2 },
                  { label: "Early warning", data: series.map((s) => s.ew), borderColor: CH.amber, backgroundColor: CH.amber, tension: 0.25, pointRadius: 2 },
                ] }}
                options={baseOptions({ plugins: { legend: { position: "bottom", labels: { color: "#8790a0", boxWidth: 10, boxHeight: 10 } } },
                  scales: { x: { offset: true, ticks: { color: "#8790a0", maxTicksLimit: 6, maxRotation: 0 }, grid: { display: false } }, y: { min: 0, max: 1, ticks: { color: "#8790a0" }, grid: { color: "rgba(160,170,185,0.08)" } } } }) as never} />
            </div>
          )}
        </Panel>
        <Panel kicker="SHAP · explains the MODEL" title="Risk breakdown by category" q="Random Forest · not the operational decision"
               footer={x?.shap ? <>raw model prediction <b className="mono">{x.shap.prediction.toFixed(3)}</b> ({KIND_LABEL[x.shap.prediction_kind] ?? x.shap.prediction_kind}) · base value <span className="mono">{x.shap.base_value.toFixed(3)}</span> · model <span className="mono">{x.shap.model_version}</span> · red pushes the model's output up, blue pushes it down</> : undefined}>
          {intel.unavailable ? <Unavailable what="SHAP" endpoint="/api/intel/accounts/{id}" /> : !x ? <Loading /> : !x.shap ? (
            <div className="empty">No SHAP explanation: the Random Forest was not run for this account.</div>
          ) : (() => {
            const cats = Object.entries(x.shap.categories).sort((p, q) => Math.abs(q[1]) - Math.abs(p[1])).slice(0, 10);
            return (
              <div className="chart-shell">
                <ChartCanvas type="bar" height={250} empty="No category contributions."
                  data={{ labels: cats.map(([k]) => k), datasets: [{ label: "SHAP contribution", data: cats.map(([, v]) => v),
                    backgroundColor: cats.map(([, v]) => (v >= 0 ? CH.red : CH.blue)), borderRadius: 4 }] }}
                  options={baseOptions({ indexAxis: "y", plugins: { legend: { display: false } },
                    scales: { x: { ticks: { color: "#8790a0" }, grid: { color: "rgba(160,170,185,0.08)" } }, y: { ticks: { color: "#a7b0bd" }, grid: { display: false } } } }) as never} />
              </div>
            );
          })()}
        </Panel>
      </div>

      <div className="grid cols-2 align-start section-gap">
        <Panel kicker="Fraud analyst" title={flaggedLike ? "Why flagged?" : "Why it is not flagged"} flush>
          <div className="sect">
            <ul className="why-list">
              {live.reason && <li><b>Live status:</b> {clean(live.reason)}</li>}
              {signals.map((s) => <li key={s.rule_id}><b>{s.label}</b> <span className="xs dim mono">RingWatch · operational</span> — {clean(s.reason)}</li>)}
              {x && <li><b>Detector consensus:</b> {clean(x.consensus.summary)}</li>}
              {x && x.role.role !== "unclassified" && <li><b>Role · {ROLE_LABEL[x.role.role] ?? x.role.role}:</b> {clean(x.role.reason)}</li>}
              {x?.shap && x.shap.top_positive.slice(0, 3).map((c) => (
                <li key={c.feature}><b>{humanKey(c.feature)}</b> = {evValue(c.feature, c.value)} pushes the model's output up by <span className="mono">{c.contribution.toFixed(3)}</span> <span className="xs dim">(SHAP · {c.category})</span></li>
              ))}
              {!live.reason && signals.length === 0 && !x && <li className="muted">No network rule fires in the 72-hour window; model evidence is loading or not served.</li>}
            </ul>
            <div className="xs dim" style={{ marginTop: 6 }}>RingWatch reasons feed the recipient-network dimension of every payment to this account (operational). SHAP / consensus explain the models — corroborating only.</div>
          </div>
          <div className="sect">
            <div className="sect-t">Rules fired</div>
            <div className="token-row">
              {signals.map((s) => <span key={s.rule_id} className="token danger" title={`${s.rule_id} · RingWatch (operational)`}>{s.label} ✓</span>)}
              {fired.map((f, i) => <span key={`${f.rule_id ?? i}`} className="token warn" title={clean(f.reason)}>{f.label ?? f.rule_id}{f.points != null ? ` · ${f.points} pts` : ""}</span>)}
              {signals.length === 0 && fired.length === 0 && <span className="xs muted">none — no RingWatch rule and no rule-engine points</span>}
            </div>
          </div>
          <div className="sect">
            <div className="sect-t">Early-warning signals</div>
            <div className="token-row">
              {ewSignals.length ? ewSignals.map((s) => <span key={s} className="token warn">{s}</span>) : <span className="xs muted">{ew ? "no active signals" : "early warning not available"}</span>}
              {ew && <span className="xs dim mono" style={{ marginLeft: "auto" }}>{ew.display}</span>}
            </div>
          </div>
          {netFeatures.length > 0 && (
            <div className="sect">
              <div className="sect-t">Network features · RingWatch (72 h)</div>
              <div className="ev">{netFeatures.map(([k, v]) => <span key={k} className="ev-kv">{humanKey(k)} <b>{evValue(k, v)}</b></span>)}</div>
            </div>
          )}
          <div className="sect">
            <div className="sect-t">External intelligence <Sim /></div>
            {ext && ext.status ? (
              <div className="row wrap">
                <Pill status={ext.status === "confirmed_mule" ? "fraud" : ext.status === "reported" ? "high" : ext.status === "watchlist" ? "watch" : "normal"}>{ext.status.replace("_", " ")}</Pill>
                {typeof ext.risk_score === "number" && <span className="mono xs">risk {ext.risk_score.toFixed(2)}</span>}
                {(ext.reason_codes ?? []).map((c) => <span key={c} className="tag mono">{c}</span>)}
                {ext.source && <span className="xs muted">{ext.source}</span>}
              </div>
            ) : <div className="xs muted">No registry entry for this account (simulated local registry).</div>}
          </div>
          {signals.length > 0 && (
            <details className="sect fold">
              <summary className="sect-t">RingWatch evidence · contributions, evidence values, provenance</summary>
              {signals.map((s) => <SignalRow key={s.rule_id} s={s} />)}
            </details>
          )}
        </Panel>
        <Panel kicker="Model inputs" title="Window features" q="now · own baseline · SHAP" flush
               footer={x?.drift ? `Baseline = ${x.drift.baseline_window}; current = ${x.drift.current_window}. SHAP is the Random Forest's per-feature contribution.` : "Features the models read for this account's current window."}>
          {intel.unavailable ? <div className="sect"><Unavailable what="Window features" endpoint="/api/intel/accounts/{id}" /></div> : !x ? <Loading /> : (
            <WindowFeatures x={x} />
          )}
        </Panel>
      </div>

      <div className="grid cols-2 align-start section-gap">
        <Panel kicker="Ledger" title="Recent transactions" flush q="double-entry postings, newest first">
          <Async load={txs} what="Ledger postings" endpoint="/api/accounts/{id}/transactions">
            {(list) => list.length === 0 ? <div className="empty">No ledger postings.</div> : (
              <div className="tscroll" style={{ maxHeight: 460 }}>
                <table className="dt compact">
                  <thead><tr><th>Tx</th><th>Time</th><th>Dir</th><th>Counterparty</th><th className="num">Amount</th><th>Source</th></tr></thead>
                  <tbody>
                    {list.slice(0, 40).map((t) => {
                      const inbound = t.recipient_id === accountId;
                      const other = inbound ? t.sender_id : t.recipient_id;
                      return (
                        <tr key={t.id}>
                          <td className="mono xs dim">{t.id}</td>
                          <td className="mono xs">{formatTime(t.ts)}</td>
                          <td className="xs">{inbound ? <span className="c-accent">← in</span> : <span className="ink2">out →</span>}</td>
                          <td className="xs"><Link className="acct" to={`/investigations/account/${encodeURIComponent(other)}`}>{handle(other)}</Link></td>
                          <td className="num" style={{ color: inbound ? undefined : "var(--ink-2)" }}>{inbound ? "+" : "−"}{formatINR(t.amount_paise)}</td>
                          <td className="xs muted">{t.source === "scenario" ? <span className="tag danger" title="Scenario posting — simulator ground truth tag">scenario</span> : t.source}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Async>
        </Panel>
        <div className="stack">
          <Panel kicker="Neighbourhood" title={`Neighbours · ${hops}-hop scene`} flush
                 q={scene.data ? `${neighbours.length} direct counterpart${neighbours.length === 1 ? "" : "ies"} · ${scene.data.nodes.length} accounts in scope` : undefined}
                 actions={<>
                   <Seg options={[["1", "1-hop"], ["2", "2-hop"]]} value={hops} onChange={setHops} />
                   <Link className="btn xs" to={`/network?focus=${encodeURIComponent(a.id)}&hops=${hops}`}>Open in 3D ↗</Link>
                 </>}>
            <Async load={scene} what="Graph scene" endpoint="/api/graph/scene">
              {(s) => (
                <>
                  <SceneThumb scene={s} height={220} focus={a.id} onPick={(id) => id !== a.id && nav(`/investigations/account/${encodeURIComponent(id)}`)} />
                  {neighbours.length > 0 && (
                    <div className="tscroll" style={{ maxHeight: 240 }}>
                      <table className="dt compact">
                        <thead><tr><th>Account</th><th>Direction</th><th className="num">Tx</th><th className="num">Amount</th><th>Status</th></tr></thead>
                        <tbody>
                          {neighbours.map((n) => {
                            const ls = live.statusOf(n.id);
                            const ns = n.node ? nodeStatus(n.node) : "unknown";
                            return (
                              <tr key={`${n.dir}${n.id}`} className="click" onClick={() => nav(`/investigations/account/${encodeURIComponent(n.id)}`)}>
                                <td className="xs"><span className="acct">{handle(n.id)}</span></td>
                                <td className="xs muted">{n.dir === "out" ? "sent to" : "received from"}</td>
                                <td className="num xs">{n.count}</td>
                                <td className="num xs">{formatINR(n.amount)}{n.tainted > 0 && <div style={{ color: "var(--st-fraud)" }}>traced {formatINR(n.tainted)}</div>}</td>
                                <td>{ls ? <span className={`pill as-${ls}`}>{ACCOUNT_STATUS_LABEL[ls].toLowerCase()}</span> : <Pill status={ns}>{STATUS_LABEL[ns]}</Pill>}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </Async>
          </Panel>
          <Panel kicker="Alerts" title="Status changes · PRIMA decisions" flush>
            <div className="sect">
              <LiveStatusLine live={live} />
              {live.reason && <div className="sm ink2" style={{ marginTop: 8 }}>{clean(live.reason)}{live.families ? ` · ${live.families} detector families agree` : ""}</div>}
            </div>
            <div className="sect"><AccountAlerts live={live} accountId={a.id} /></div>
            <div className="sect">
              <div className="sect-t">Simulator ground truth <span className="sim gt">evaluation only — never scored</span></div>
              <GroundTruth live={live} accountId={a.id} />
            </div>
          </Panel>
        </div>
      </div>

      <div className="grid cols-2 align-start section-gap">
        <Panel kicker="PRIMA · risk evolution" title="Payment decisions as sender" q="each marker says why the score moved">
          <Async load={rt} what="Risk evolution" endpoint="/api/accounts/{id}/risk-timeline">
            {(pts) => pts.length === 0
              ? <div className="empty">This account has not initiated an evaluated payment. Its risk as a recipient is the network evidence above.</div>
              : <RiskEvolution points={pts} ladder={policy.data?.ladder} onPickDecision={(id) => nav(`/investigations/decision/${id}`)}
                               decisionId={pts[pts.length - 1].decision_id ?? undefined} />}
          </Async>
        </Panel>
        <Panel kicker="As sender" title="Payment intents" flush q="customer / scenario intents (background stream excluded)">
          <Async load={intents} what="Intents" endpoint="/api/intents">
            {(list) => list.length === 0 ? <div className="empty">No customer or scenario payment intents from this account.</div> : (
              <div className="tscroll" style={{ maxHeight: 330 }}>
                <table className="dt compact">
                  <thead><tr><th>Time</th><th>Recipient</th><th className="num">Amount</th><th>Tier</th><th>State</th><th>Decision</th></tr></thead>
                  <tbody>
                    {list.slice(0, 15).map((it) => (
                      <tr key={it.intent_id} className={it.decision_id ? "click" : ""} onClick={() => it.decision_id && nav(`/investigations/decision/${it.decision_id}`)}>
                        <td className="mono xs">{formatTime(it.created_at)}</td>
                        <td className="xs">{handle(it.recipient_id)}</td>
                        <td className="num">{formatINR(it.amount_paise)}</td>
                        <td><TierPill tier={it.tier} /></td>
                        <td><StatePill state={it.state} /></td>
                        <td className="mono xs">{it.decision_id ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Async>
        </Panel>
      </div>

      <Panel className="section-gap" kicker="Model evidence" title="Explains the MODEL" flush
             q="detector consensus · SHAP per feature · behavioural drift · pattern memory · role — corroborating, never sets a tier">
        {intel.unavailable ? (
          <div className="sect"><Unavailable what="Detection intelligence" endpoint="/api/intel/accounts/{id}" /></div>
        ) : x ? <AccountIntelView x={x} grid /> : intel.error ? <div className="sect"><div className="notice err">{intel.error.message}</div></div> : <Loading text="Loading detector evidence" />}
      </Panel>

      <Panel className="section-gap" kicker="Profile" title="Account record">
        <KV c4 rows={[
          ["Kind", a.kind], ["Persona", a.persona ?? "—"],
          ["Primary device", <span className="mono xs">{a.primary_device ?? "—"}</span>], ["All devices", <span className="mono xs">{a.devices.join(", ") || "—"}</span>],
          ["Trusted contact", a.trusted_contact ? `${a.trusted_contact.name} (${a.trusted_contact.relation}) ${a.trusted_contact.phone_masked}` : "none nominated"],
          ["Payees", a.payees.length ? a.payees.slice(0, 6).map((p) => `${p.display_name} (${p.payments})`).join(" · ") + (a.payees.length > 6 ? ` +${a.payees.length - 6}` : "") : "none"],
          ["Opened", formatStamp(a.opened_at)], ["Scene flags", node && node.flags.length ? node.flags.join(" · ") : "—"],
        ]} />
      </Panel>
    </>
  );
}

function Tile({ k, v, d, st, small }: { k: ReactNode; v: ReactNode; d?: ReactNode; st?: Status; small?: boolean }) {
  return (
    <div className={`m ${st ? `st-${st}` : ""} ${small ? "small" : ""}`}>
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {d && <div className="d">{d}</div>}
    </div>
  );
}

function ModelTile({ k, d }: { k: string; d: DetectorResult | null }) {
  if (!d) return <Tile k={k} v="—" d="not evaluated" />;
  const st = detectorStatus(d);
  const thr = (d.detail as { threshold?: number }).threshold;
  return (
    <Tile k={<>{k} <span className="glyph" style={{ marginLeft: 4 }}>{FAMILY[d.family]?.glyph}</span></>}
          v={<span style={{ color: d.flagged ? `var(--st-${st === "normal" ? "watch" : st})` : undefined }}>{d.display.split(" · ")[0]}</span>}
          d={`${KIND_LABEL[d.kind] ?? d.kind}${typeof thr === "number" ? ` · threshold ${thr.toFixed(3)}` : ""}${d.flagged ? " · flagged" : ""}`} />
  );
}

function WindowFeatures({ x }: { x: AccountIntel }) {
  const baseline = new Map((x.drift?.features ?? []).map((f) => [f.feature, f]));
  const shap = new Map([...(x.shap?.top_positive ?? []), ...(x.shap?.top_negative ?? [])].map((c) => [c.feature, c.contribution]));
  const rows = Object.entries(x.features);
  if (!rows.length) return <div className="empty">No window features.</div>;
  return (
    <div className="tscroll" style={{ maxHeight: 520 }}>
      <table className="dt compact">
        <thead><tr><th>Feature</th><th className="num">Now</th><th className="num">Baseline</th><th className="num">Change</th><th className="num">SHAP</th></tr></thead>
        <tbody>
          {rows.map(([k, v]) => {
            const b = baseline.get(k);
            const s = shap.get(k);
            return (
              <tr key={k}>
                <td className="xs">{humanKey(k)}</td>
                <td className="num xs"><b>{evValue(k, v)}</b></td>
                <td className="num xs muted">{b ? evValue(k, b.baseline) : "—"}</td>
                <td className="num xs" style={{ color: b && Math.abs(b.change) >= 1 ? "var(--st-high)" : undefined }}>{b ? `${b.change > 0 ? "+" : ""}${Math.abs(b.change) < 10 ? b.change.toFixed(2) : b.change.toFixed(0)}` : "—"}</td>
                <td className="num xs" style={{ color: s === undefined ? undefined : s > 0 ? "var(--st-critical)" : "var(--st-normal)" }}>{s === undefined ? "—" : `${s > 0 ? "+" : ""}${s.toFixed(3)}`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
