import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { GraphEvidence, LedgerTx, RiskSignal, ScenarioStatus, TaintView } from "../api/types";
import { SignalRow as SignalCard } from "../components/Decision";
import { Sim as SimChip } from "../components/ui";
import { EvidenceGraph } from "../components/EvidenceGraph";
import { MoneyTrace } from "../components/MoneyTrace";
import { useConsoleEvents } from "../components/Shell";
import { formatINR, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad } from "../lib/hooks";

function merge(a: GraphEvidence, b: GraphEvidence): GraphEvidence {
  const nodes = new Map(a.nodes.map((n) => [n.id, n]));
  b.nodes.forEach((n) => nodes.set(n.id, n));
  const edges = new Map(a.edges.map((e) => [e.id, e]));
  b.edges.forEach((e) => edges.set(e.id, e));
  const list = [...nodes.values()].slice(0, 90);
  const keep = new Set(list.map((n) => n.id));
  return { nodes: list, edges: [...edges.values()].filter((e) => keep.has(e.source) && keep.has(e.target)),
           focus: b.focus, truncated: a.truncated || b.truncated || nodes.size > 90, total_nodes: Math.max(nodes.size, a.total_nodes) };
}

export function NetworkPage() {
  const [params] = useSearchParams();
  const focusParam = params.get("focus");
  const [evidence, setEvidence] = useState<GraphEvidence | null>(null);
  const [selected, setSelected] = useState<string | null>(focusParam);
  const [detail, setDetail] = useState<{ score: number; signals: RiskSignal[]; features: Record<string, unknown>; external_intel: unknown } | null>(null);
  const [txs, setTxs] = useState<LedgerTx[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loadMs, setLoadMs] = useState<number | null>(null);
  const taint = useLoad<TaintView>(api.taint);
  const s2 = useLoad<ScenarioStatus | undefined>(() => api.scenarios().then((all) => all.find((s) => s.id === "s2")));

  const loadGraph = async () => {
    const t = performance.now();
    try {
      let g = await api.graphSuspicious();
      if (focusParam && !g.nodes.some((n) => n.id === focusParam)) g = merge(g, await api.graphNeighbourhood(focusParam));
      setEvidence(g);
      setLoadMs(Math.round(performance.now() - t));
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
  };
  useEffect(() => { loadGraph(); /* eslint-disable-next-line */ }, [focusParam]);

  const loadDetail = async (id: string) => {
    setSelected(id);
    if (id.startsWith("ext:")) { setDetail(null); setTxs([]); return; }
    const [n, t] = await Promise.all([api.accountNetwork(id), api.accountTransactions(id)]);
    setDetail(n as never); setTxs(t);
  };
  useEffect(() => { if (selected) loadDetail(selected); /* eslint-disable-next-line */ }, []);

  const refresh = useDebounced(() => { loadGraph(); taint.reload(); s2.reload(); if (selected) loadDetail(selected); }, 500);
  useConsoleEvents((e) => {
    if (["ledger.posted", "taint.updated", "ringwatch.scan", "demo.reset", "monitor.finding"].includes(e.type)) refresh();
    if (e.type.startsWith("scenario.")) s2.reload();
  });

  const expand = async (id: string) => {
    if (!evidence) return;
    setEvidence(merge(evidence, await api.graphNeighbourhood(id)));
  };

  const confirmScam = async (txId: string) => {
    setBusy(txId); setErr(null);
    try { await api.label(txId); await Promise.all([loadGraph(), taint.reload()]); if (selected) await loadDetail(selected); }
    catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(null); }
  };

  const scenarioAct = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try { await fn(); } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    s2.reload();
  };

  const s = s2.data;
  const node = evidence?.nodes.find((n) => n.id === selected);
  const labelledTx = new Set((taint.data?.incidents ?? []).map((i) => i.transaction_id));

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="spread wrap">
        <div>
          <h1>Network — RingWatch & TaintTrace</h1>
          <div className="small muted">Default view: only accounts with network evidence plus their direct counterparties (last 72 h). Click a node for evidence; “expand” loads its neighbours.</div>
        </div>
        <div className="row wrap">
          {s && (
            <>
              <span className="small muted">Scenario 2 · mule ring: {s.state}{s.state !== "idle" ? ` ${s.step}/${s.total_steps}` : ""}</span>
              {s.state === "idle" && <button className="btn sm primary" onClick={() => scenarioAct(() => api.scenarioStart("s2"))}>▶ Inject mule ring</button>}
              {s.state === "done" && <span className="chip t0">ring injected · reset demo to replay</span>}
              {s.state === "running" && <button className="btn sm" onClick={() => scenarioAct(() => api.scenarioPause("s2"))}>❚❚ Pause</button>}
              {s.state === "paused" && <button className="btn sm primary" onClick={() => scenarioAct(() => api.scenarioResume("s2"))}>▶ Resume</button>}
            </>
          )}
          <button className="btn sm" onClick={loadGraph}>Refresh</button>
        </div>
      </div>
      {err && <div className="notice error">{err}</div>}
      <div className="grid-net">
        <div className="stack" style={{ minHeight: 0 }}>
          <div style={{ flex: 1, minHeight: 420 }}>
            <EvidenceGraph evidence={evidence} selected={selected} onNodeClick={loadDetail} />
          </div>
          <div className="small muted mono">{evidence ? `${evidence.nodes.length} nodes · ${evidence.edges.length} aggregated edges · loaded in ${loadMs ?? "—"} ms · layout computed once (dagre), no physics` : "loading…"}</div>
        </div>

        <div className="stack" style={{ overflowY: "auto", minHeight: 0 }}>
          {!selected && <div className="card"><div className="empty">Select a node to see why it is flagged.</div></div>}
          {selected && (
            <div className="card stack">
              <div className="spread">
                <div><b>{node?.label ?? handle(selected)}</b> <span className="mono small muted">{selected}</span></div>
                {!selected.startsWith("ext:") && <button className="btn sm" onClick={() => expand(selected)}>Expand</button>}
              </div>
              <div className="row wrap small">
                {node?.role && <span className="chip">{node.role}</span>}
                {node?.labelled && <span className="chip t3">received confirmed scam payment</span>}
                {node && node.attributable_paise > 0 && <span className="chip t3">{formatINR(node.attributable_paise)} traced (LIBR)</span>}
                {detail && <span className="chip">network score {detail.score.toFixed(2)}</span>}
                {selected.startsWith("ext:") && <span className="chip">outside the bank's view</span>}
              </div>
              {txs.length > 0 && (
                <>
                  <div className="upper">Recent ledger postings · confirm a victim payment to trace it</div>
                  <table className="data">
                    <tbody>
                      {txs.slice(0, 12).map((t) => {
                        const inbound = t.recipient_id === selected;
                        return (
                          <tr key={t.id}>
                            <td className="mono small">{formatTime(t.ts)}</td>
                            <td className="small">{inbound ? `← ${handle(t.sender_id)}` : `→ ${handle(t.recipient_id)}`}</td>
                            <td className="mono small" style={{ textAlign: "right" }}>{formatINR(t.amount_paise)}</td>
                            <td style={{ textAlign: "right" }}>
                              {labelledTx.has(t.id) ? <span className="chip t3">confirmed</span>
                                : inbound && t.kind === "transfer" && (t.source === "scenario" || (node?.risk ?? 0) >= 0.4) && (
                                  <button className="btn sm danger nowrap" disabled={busy === t.id} onClick={() => confirmScam(t.id)}
                                          title="Simulates a verified victim report (e.g. via 1930/NCRP) confirmed by the bank">
                                    {busy === t.id ? "Tracing…" : "Confirm scam"}</button>)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}
              {detail && detail.signals.length === 0 && <div className="small muted">No network rule fires for this account.</div>}
              {detail?.signals.map((sg) => <SignalCard key={sg.rule_id} s={sg} />)}
              {Boolean(detail?.external_intel) && (
                <div className="notice small"><SimChip text="SIMULATED EXTERNAL INTELLIGENCE" /> {String((detail!.external_intel as { status: string }).status)} · {((detail!.external_intel as { reason_codes: string[] }).reason_codes ?? []).join(", ")}</div>
              )}
            </div>
          )}
          <div className="card">
            <div className="card-title"><h3>TaintTrace</h3>{taint.data && taint.data.incidents.length > 0 && <span className="small muted mono">{taint.data.computed_ms} ms over {taint.data.journals_considered} journals</span>}</div>
            <MoneyTrace incidents={taint.data?.incidents ?? []} focus={selected ?? undefined} />
            {taint.data && taint.data.incidents.length > 0 && (
              <div className="notice small" style={{ marginTop: 10 }}>
                Feedback loop: the next payment to any of these accounts is evaluated with this evidence.{" "}
                <Link to="/pay?as=ramesh%40vigil">Try paying kiran.traders again →</Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
