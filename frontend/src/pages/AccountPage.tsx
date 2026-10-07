// ACCOUNT INVESTIGATION — one account: risk over time (with reasons), its 1–2 hop money neighbourhood,
// rule-engine network evidence (operational), model evidence (explains the MODEL: consensus, SHAP, drift,
// pattern memory, role), its payment intents and ledger postings.
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AccountSummary, GraphScene, LedgerTx, PolicyView, RiskPoint, RiskSignal, TransactionIntent } from "../api/types";
import { SignalRow } from "../components/Decision";
import { AccountIntelBlock, RoleIcon } from "../components/intel";
import { RiskEvolution } from "../components/Replay";
import { SceneThumb } from "../components/SceneThumb";
import { useConsoleEvents } from "../components/Shell";
import { Async, ErrorNote, KV, Loading, Metric, PageHead, Panel, Pill, Seg, Sim, StatePill, TierPill } from "../components/ui";
import { evValue, formatINR, formatTime, handle, humanKey } from "../lib/format";
import { nodeStatus } from "../lib/graphStyle";
import { useDebounced, useLoad } from "../lib/hooks";
import { ROLE_LABEL, STATUS_LABEL, scoreStatus } from "../lib/status";

export function AccountPage() {
  const { accountId = "" } = useParams();
  const nav = useNavigate();
  const [hops, setHops] = useState<"1" | "2">("1");
  const acct = useLoad<AccountSummary>(() => api.account(accountId), [accountId]);
  const net = useLoad(() => api.accountNetwork(accountId), [accountId]);
  const rt = useLoad<RiskPoint[]>(() => api.riskTimeline(accountId), [accountId]);
  const txs = useLoad<LedgerTx[]>(() => api.accountTransactions(accountId), [accountId]);
  const intents = useLoad<TransactionIntent[]>(() => api.intents(accountId), [accountId]);
  const scene = useLoad<GraphScene>(() => api.scene({ focus: accountId, hops: Number(hops), cap: 60 }), [accountId, hops]);
  const policy = useLoad<PolicyView>(api.policy);

  const refresh = useDebounced(() => { net.reload(); rt.reload(); txs.reload(); intents.reload(); scene.reload(); }, 1500);
  useConsoleEvents((e) => {
    const data = e.data as { sender_id?: string; recipient_id?: string } | null;
    const mine = data && (data.sender_id === accountId || data.recipient_id === accountId);
    if ((e.type === "decision.created" || e.type === "intent.updated") && mine) refresh();
    else if (["ringwatch.scan", "taint.updated", "demo.reset"].includes(e.type)) refresh();
  });

  const node = scene.data?.nodes.find((n) => n.id === accountId) ?? null;
  const flows = useMemo(() => {
    const list = txs.data ?? [];
    let inn = 0, out = 0;
    list.forEach((t) => { if (t.recipient_id === accountId) inn += t.amount_paise; else if (t.sender_id === accountId) out += t.amount_paise; });
    return { inn, out, n: list.length };
  }, [txs.data, accountId]);

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
  const score = net.data?.score ?? null;
  const signals = (net.data?.signals ?? []) as RiskSignal[];
  const ext = net.data?.external_intel as { status?: string; risk_score?: number; reason_codes?: string[]; source?: string } | null | undefined;
  const features = Object.entries(net.data?.features ?? {}).filter(([, v]) => v !== null && typeof v !== "object");
  const st = node ? nodeStatus(node) : scoreStatus(score);

  return (
    <>
      <PageHead crumb={<><Link to="/investigations">05 · Investigations</Link> / account</>}
        title={<span className="row wrap tight"><RoleIcon role={node?.role} size={18} /><span>{a.display_name}</span><span className="mono sm muted">{a.id}</span></span>}
        lede={<span className="row wrap tight">
          <Pill status={st}>{STATUS_LABEL[st]}</Pill>
          {node?.role && node.role !== "normal" && <span className="tag">{ROLE_LABEL[node.role] ?? node.role}</span>}
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

      <div className="mstrip" style={{ marginBottom: 12 }}>
        <Metric k="Network score" v={score === null ? "—" : score.toFixed(2)} status={score === null ? undefined : scoreStatus(score)}
                d={`RingWatch · ${signals.length} rule${signals.length === 1 ? "" : "s"} fired`} />
        <Metric k="Balance" v={formatINR(a.balance_paise)} d={`available ${formatINR(a.available_paise)}`} />
        <Metric k="Held" v={formatINR(a.held_paise)} status={a.held_paise > 0 ? "held" : undefined} d="scoped holds only" />
        <Metric k="Ledger postings" v={txs.data ? String(flows.n) : "—"} d={txs.data ? `in ${formatINR(flows.inn)} · out ${formatINR(flows.out)}` : "loading"} />
        <Metric k="Traced value" v={node ? formatINR(node.taint_paise) : "—"} status={node && node.taint_paise > 0 ? "fraud" : undefined} d="LIBR attributable" />
        <Metric k="Devices" v={String(a.devices.length)} d={a.primary_device ? `primary ${a.primary_device}` : "no primary device"} />
        <Metric k="Opened" v={<span style={{ fontSize: 13 }}>{new Date(a.opened_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}</span>} d={`daily limit ${formatINR(a.daily_limit_paise)}`} />
      </div>

      {/* two independent columns: operational evidence + activity (left), network + model evidence (right) */}
      <div className="grid cols-2 align-start">
        <div className="stack">
            <Panel kicker="Risk evolution" title="Risk over time" q="each marker says why the score moved">
              <Async load={rt} what="Risk evolution" endpoint="/api/accounts/{id}/risk-timeline">
                {(pts) => pts.length === 0
                  ? <div className="empty">This account has not initiated an evaluated payment. Its risk as a recipient is the network evidence below.</div>
                  : <RiskEvolution points={pts} ladder={policy.data?.ladder} onPickDecision={(id) => nav(`/investigations/decision/${id}`)}
                                   decisionId={pts[pts.length - 1].decision_id ?? undefined} />}
              </Async>
            </Panel>
            <Panel kicker="Rule engine · RingWatch" title="Network evidence" q="operational — feeds the recipient-network dimension of every payment to this account" flush>
              <div className="sect">
                {net.loading && !net.data && <Loading />}
                {net.data && signals.length === 0 && <div className="xs muted">No network rule fires for this account in the 72-hour window.</div>}
                {signals.map((s) => <SignalRow key={s.rule_id} s={s} />)}
              </div>
              {features.length > 0 && (
                <div className="sect">
                  <div className="sect-t">Network features</div>
                  <div className="ev">{features.map(([k, v]) => <span key={k} className="ev-kv">{humanKey(k)} <b>{evValue(k, v)}</b></span>)}</div>
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
              {node && node.flags.length > 0 && (
                <div className="sect"><div className="sect-t">Scene flags</div><div className="row wrap tight">{node.flags.map((f) => <span key={f} className="tag">{f}</span>)}</div></div>
              )}
            </Panel>
            <Panel kicker="As sender" title="Payment intents" flush q="customer / scenario intents (background stream excluded)">
              <Async load={intents} what="Intents" endpoint="/api/intents">
                {(list) => list.length === 0 ? <div className="empty">No customer or scenario payment intents from this account.</div> : (
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
                )}
              </Async>
            </Panel>
            <Panel kicker="Ledger" title="Recent postings" flush q="double-entry, newest first">
              <Async load={txs} what="Ledger postings" endpoint="/api/accounts/{id}/transactions">
                {(list) => list.length === 0 ? <div className="empty">No ledger postings.</div> : (
                  <div className="tscroll" style={{ maxHeight: 360 }}>
                    <table className="dt compact">
                      <thead><tr><th>Time</th><th>Tx</th><th>Counterparty</th><th className="num">Amount</th><th>Source</th></tr></thead>
                      <tbody>
                        {list.slice(0, 40).map((t) => {
                          const inbound = t.recipient_id === accountId;
                          return (
                            <tr key={t.id}>
                              <td className="mono xs">{formatTime(t.ts)}</td>
                              <td className="mono xs dim">{t.id}</td>
                              <td className="xs"><Link to={`/investigations/account/${encodeURIComponent(inbound ? t.sender_id : t.recipient_id)}`}>{inbound ? "← " : "→ "}{handle(inbound ? t.sender_id : t.recipient_id)}</Link></td>
                              <td className="num" style={{ color: inbound ? undefined : "var(--ink-2)" }}>{inbound ? "+" : "−"}{formatINR(t.amount_paise)}</td>
                              <td className="xs muted">{t.source}{t.source === "scenario" && <> <Sim text="SIM" /></>}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </Async>
            </Panel>
          <Panel kicker="Profile" title="Account record">
            <KV c4 rows={[
              ["Kind", a.kind], ["Persona", a.persona ?? "—"],
              ["Primary device", <span className="mono xs">{a.primary_device ?? "—"}</span>], ["All devices", <span className="mono xs">{a.devices.join(", ") || "—"}</span>],
              ["Trusted contact", a.trusted_contact ? `${a.trusted_contact.name} (${a.trusted_contact.relation}) ${a.trusted_contact.phone_masked}` : "none nominated"],
              ["Payees", a.payees.length ? a.payees.slice(0, 6).map((p) => `${p.display_name} (${p.payments})`).join(" · ") + (a.payees.length > 6 ? ` +${a.payees.length - 6}` : "") : "none"],
            ]} />
          </Panel>
        </div>
        <div className="stack">
            <Panel kicker="Neighbourhood" title={`${hops}-hop money network`} flush
                   q={scene.data ? `${scene.data.nodes.length} accounts · ${scene.data.edges.length} flows` : undefined}
                   actions={<>
                     <Seg options={[["1", "1-hop"], ["2", "2-hop"]]} value={hops} onChange={setHops} />
                     <Link className="btn xs" to={`/network?focus=${encodeURIComponent(a.id)}&hops=${hops}`}>Open in 3D ↗</Link>
                   </>}
                   footer="Frozen server layout (/api/graph/scene?focus=), projected flat. Click an account to open it.">
              <Async load={scene} what="Graph scene" endpoint="/api/graph/scene">
                {(s) => <SceneThumb scene={s} height={290} focus={a.id} onPick={(id) => id !== a.id && nav(`/investigations/account/${encodeURIComponent(id)}`)} />}
              </Async>
            </Panel>
            <Panel kicker="Model evidence" title="Explains the MODEL" q="detector consensus · SHAP · drift · pattern memory · role — corroborating only" flush>
              <AccountIntelBlock accountId={a.id} />
            </Panel>
        </div>
      </div>
    </>
  );
}
