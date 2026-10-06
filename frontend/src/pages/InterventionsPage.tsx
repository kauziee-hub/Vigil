// INTERVENTIONS — what action is active, its SLA, and the bank's release / reject decision.
// Queue = /api/interventions (newest alerts). Scenario / customer T2+ decisions that fell outside that window are
// added with their LIVE intent state from /api/intents/{id} (never guessed). Release / reject call the real
// bank-action endpoint; the payment provider is only called on release.
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { InterventionRow, IntentState } from "../api/types";
import { usePlatform, useConsoleEvents } from "../components/Shell";
import { Async, Metric, PageHead, Panel, Pill, Seg, StatePill, TierPill } from "../components/ui";
import { duration, formatINR, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad, useNow } from "../lib/hooks";

type Row = InterventionRow & { outside?: boolean };
type Queue = "holds" | "confirm" | "inform" | "all";
const QUEUE_MIN: Record<Queue, (t: number) => boolean> = {
  holds: (t) => t >= 3, confirm: (t) => t === 2, inform: (t) => t === 1, all: () => true,
};
const OPEN_STATES = new Set<IntentState | string>(["HELD", "ESCALATED", "CHALLENGED", "CREATED", "RISK_EVALUATED"]);
const KIND_LABEL: Record<string, string> = {
  pass: "Pass", inform: "Inform (heads-up)", confirm_purpose: "Confirm purpose", scoped_hold: "Scoped hold",
  hold_and_circuit_breaker: "Hold + CircuitBreaker",
};

export function InterventionsPage() {
  const nav = useNavigate();
  const { mode } = usePlatform();
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") as "open" | "all") || "open";
  const queue = (params.get("queue") as Queue) || "holds";
  const now = useNow(5000);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ id: string; text: string; err?: boolean } | null>(null);
  const rows = useLoad<InterventionRow[]>(() => api.interventions(status), [status]);
  const fetchedAt = useMemo(() => Date.now(), [rows.data]);

  // Scenario / customer decisions (T2+) missing from the window, with their live intent state.
  const extra = useLoad<Row[]>(async () => {
    const have = new Set((rows.data ?? []).map((r) => r.decision_id));
    const ds = (await api.decisions(2)).filter((d) => !have.has(d.decision_id)).slice(0, 12);
    const out = await Promise.all(ds.map(async (d): Promise<Row | null> => {
      try {
        const r = await api.intent(d.intent_id);
        const it = r.intent;
        const holdPaise = r.decision?.intervention.hold_paise ?? 0;
        return {
          intent_id: it.intent_id, decision_id: d.decision_id, sender_id: d.sender_id, recipient_id: d.recipient_id,
          amount_paise: d.amount_paise, tier: d.tier, kind: d.kind, state: it.state, headline: d.headline, opened_at: d.created_at,
          age_s: (Date.now() - Date.parse(d.created_at)) / 1000, sla_due: null,
          hold: it.hold_id && holdPaise ? { id: it.hold_id, held_paise: holdPaise, reference: "", outcome: OPEN_STATES.has(it.state) ? null : it.state.toLowerCase() } : null,
          circuit_breaker: null, mode: ((r.decision as { mode?: "active" | "shadow" } | null)?.mode ?? "active"), outside: true,
        };
      } catch { return null; }
    }));
    return out.filter((x): x is Row => !!x).filter((x) => status === "all" || OPEN_STATES.has(x.state));
  }, [rows.data, status]);

  const refresh = useDebounced(() => rows.reload(), 1000);
  useConsoleEvents((e) => {
    const t = (e.data as { tier?: number | null } | null)?.tier ?? 0;
    if ((e.type === "decision.created" || e.type === "intent.updated") && (queue === "all" || queue === "inform" || t >= 2)) refresh();
    else if (["breaker.fired", "breaker.responded", "demo.reset", "mode.changed"].includes(e.type)) refresh();
  });

  const setParam = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v === null) next.delete(k); else next.set(k, v);
    setParams(next, { replace: true });
  };

  const all: Row[] = useMemo(() => [...(rows.data ?? []), ...(extra.data ?? [])]
    .sort((a, b) => Date.parse(b.opened_at) - Date.parse(a.opened_at)), [rows.data, extra.data]);
  const shown = all.filter((r) => QUEUE_MIN[queue](r.tier));
  const count = (q: Queue) => all.filter((r) => QUEUE_MIN[q](r.tier)).length;

  const stats = useMemo(() => {
    let held = 0, holds = 0, overdue = 0, cbWait = 0, shadow = 0;
    all.forEach((r) => {
      if (r.hold && !r.hold.outcome && (r.state === "HELD" || r.state === "ESCALATED")) {
        holds++; held += r.hold.held_paise;
        if (r.sla_due && Date.parse(r.sla_due) < now) overdue++;
      }
      if (r.circuit_breaker && !r.circuit_breaker.response) cbWait++;
      if (r.mode === "shadow") shadow++;
    });
    return { held, holds, overdue, cbWait, shadow };
  }, [all, now]);

  const act = async (r: Row, action: "release" | "reject") => {
    if (action === "reject" && !window.confirm(`Reject ${formatINR(r.amount_paise)} from ${handle(r.sender_id)} to ${handle(r.recipient_id)}? The hold is closed and the payment is not sent.`)) return;
    setBusy(r.intent_id); setMsg(null);
    try {
      const it = await api.bankAction(r.intent_id, action);
      setMsg({ id: r.intent_id, text: `${r.intent_id}: ${action === "release" ? "released" : "rejected"} — state now ${it.state.replace(/_/g, " ").toLowerCase()}` });
      rows.reload(); extra.reload();
    } catch (e) {
      setMsg({ id: r.intent_id, text: e instanceof ApiError ? e.message : String(e), err: true });
    } finally { setBusy(null); }
  };

  return (
    <>
      <PageHead crumb="06 · Intelligence" title="Interventions"
        lede="Every active intervention, its review clock and the bank's decision. Holds are scoped to the single payment amount — no account is frozen. Release approves the payment; reject closes it without sending anything."
        actions={mode?.mode === "shadow" ? <Pill status="watch">shadow mode — new decisions are not enforced</Pill> : undefined} />

      <div className="mstrip" style={{ marginBottom: 12 }}>
        <Metric k="In queue" v={String(all.length)} d={status === "open" ? "open alerts" : "all alerts in window"} />
        <Metric k="Holds active" v={String(stats.holds)} status={stats.holds ? "held" : undefined} d="scoped to one payment" />
        <Metric k="Value held" v={formatINR(stats.held)} status={stats.held ? "held" : undefined} d="sum of active holds" />
        <Metric k="Review overdue" v={String(stats.overdue)} status={stats.overdue ? "critical" : undefined} d="past review-by time" />
        <Metric k="Trusted contact" v={String(stats.cbWait)} d="CircuitBreaker alerts awaiting a response" />
        <Metric k="T4 · T3 · T2 · T1" v={`${all.filter((r) => r.tier === 4).length} · ${all.filter((r) => r.tier === 3).length} · ${count("confirm")} · ${count("inform")}`} d="by tier in this view" />
        <Metric k="Shadow" v={String(stats.shadow)} status={stats.shadow ? "watch" : undefined} d="recommended, not enforced" />
      </div>

      {msg && <div className={`notice ${msg.err ? "err" : "info"}`} style={{ marginBottom: 10 }}>{msg.text}</div>}

      <Panel kicker="Queue" title={`${shown.length} intervention${shown.length === 1 ? "" : "s"}`} flush
             actions={<>
               <Seg options={[["holds", `Holds T3/T4 · ${count("holds")}`], ["confirm", `Confirm T2 · ${count("confirm")}`], ["inform", `Inform T1 · ${count("inform")}`], ["all", "All"]]}
                    value={queue} onChange={(v) => setParam("queue", v === "holds" ? null : v)} />
               <Seg options={[["open", "Open"], ["all", "All states"]]} value={status} onChange={(v) => setParam("status", v === "open" ? null : v)} />
             </>}
             footer={<>Source: <span className="mono">/api/interventions</span> (newest 100 alerts){(extra.data ?? []).length > 0 && <> + {(extra.data ?? []).length} scenario/customer case{(extra.data ?? []).length === 1 ? "" : "s"} outside that window, shown with live intent state (review clock and contact response are on the case page)</>}. Ages advance on a local clock between pushes; nothing is polled.</>}>
        <Async load={rows} what="Intervention queue" endpoint="/api/interventions">
          {() => shown.length === 0 ? (
            <div className="empty">{queue === "holds" ? "No payment is on hold. Holds appear here the moment a Tier 3 / Tier 4 decision is made (Scenario Lab · Act 4)." : "Nothing in this queue."}</div>
          ) : (
            <div className="tscroll" style={{ maxHeight: "calc(100vh - 300px)" }}>
              <table className="dt compact">
                <thead>
                  <tr><th>Opened · age</th><th>Tier</th><th>Intervention</th><th>State</th><th>Sender → recipient</th><th className="num">Amount</th><th>Hold</th><th>Review SLA</th><th>CircuitBreaker</th><th>Mode</th><th className="right">Bank action</th></tr>
                </thead>
                <tbody>
                  {shown.map((r) => {
                    const age = r.outside ? (now - Date.parse(r.opened_at)) / 1000 : r.age_s + Math.max(0, now - fetchedAt) / 1000;
                    const due = r.sla_due ? (Date.parse(r.sla_due) - now) / 1000 : null;
                    const actionable = (r.state === "HELD" || r.state === "ESCALATED") && r.mode !== "shadow";
                    return (
                      <tr key={r.decision_id} className={msg?.id === r.intent_id && !msg.err ? "flash" : ""}>
                        <td className="mono xs nowrap">{formatTime(r.opened_at)}<div className="dim">{duration(age)}</div></td>
                        <td><TierPill tier={r.tier} /></td>
                        <td className="xs">{KIND_LABEL[r.kind] ?? r.kind}<div className="dim ell" style={{ maxWidth: 220 }}>{r.headline}</div></td>
                        <td><StatePill state={r.state} />{r.outside && <div className="xs dim">outside alert window</div>}</td>
                        <td className="xs"><Link to={`/investigations/account/${encodeURIComponent(r.sender_id)}`}>{handle(r.sender_id)}</Link>
                          <div>→ <Link to={`/investigations/account/${encodeURIComponent(r.recipient_id)}`}>{handle(r.recipient_id)}</Link></div></td>
                        <td className="num">{formatINR(r.amount_paise)}</td>
                        <td className="xs nowrap">{r.hold ? <><span className="mono" style={{ color: r.hold.outcome ? undefined : "var(--st-held)" }}>{formatINR(r.hold.held_paise)}</span>
                          <div className="dim mono">{r.hold.reference || r.hold.id}{r.hold.outcome && ` · ${r.hold.outcome}`}</div></> : <span className="dim">—</span>}</td>
                        <td className="xs nowrap">{due === null ? <span className="dim">{r.outside && r.hold ? "see case" : "—"}</span>
                          : r.hold?.outcome ? <span className="dim">closed</span>
                          : due < 0 ? <span style={{ color: "var(--st-critical)" }}>overdue {duration(-due)}</span>
                          : <span>{duration(due)} left<div className="dim">by {formatTime(r.sla_due)}</div></span>}</td>
                        <td className="xs">{r.circuit_breaker ? <>{r.circuit_breaker.contact}
                          <div className={r.circuit_breaker.response ? "" : "dim"}>{r.circuit_breaker.response ? `${r.circuit_breaker.response.replace(/_/g, " ")} · ${formatTime(r.circuit_breaker.responded_at)}` : "awaiting response"}</div></> : <span className="dim">{r.tier === 4 && r.outside ? "see case" : "—"}</span>}</td>
                        <td>{r.mode === "shadow" ? <Pill status="watch">shadow</Pill> : <span className="xs dim">active</span>}</td>
                        <td className="right nowrap">
                          {actionable && <>
                            <button className="btn xs ok" disabled={busy === r.intent_id} onClick={() => act(r, "release")}>Release</button>{" "}
                            <button className="btn xs danger" disabled={busy === r.intent_id} onClick={() => act(r, "reject")}>Reject</button>{" "}
                          </>}
                          <button className="btn xs ghost" onClick={() => nav(`/investigations/decision/${r.decision_id}`)}>Case →</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Async>
      </Panel>

      <div className="grid cols-3 align-start" style={{ marginTop: 12 }}>
        <Panel kicker="Ladder" title="What each tier does">
          <table className="dt compact"><tbody>
            {[[1, "Inform", "Heads-up shown; customer continues."], [2, "Confirm purpose", "Customer must state the purpose before paying."],
              [3, "Scoped hold", "This payment's amount is held for bank review; account keeps working."],
              [4, "Hold + CircuitBreaker", "Held, and the nominated trusted contact receives the facts."]].map(([t, k, d]) => (
              <tr key={t as number}><td style={{ width: 54 }}><TierPill tier={t as number} /></td><td className="xs"><b>{k}</b> — <span className="muted">{d}</span></td></tr>
            ))}
          </tbody></table>
        </Panel>
        <Panel kicker="Release" title="What release does">
          <div className="md ink2">Closes the scoped hold and moves the intent to <b>approved</b>. Scenario and background-stream payments are then sent through the mock provider automatically; a customer's own payment continues on their device. The decision record keeps the operator action (actor <span className="mono">bank</span>).</div>
        </Panel>
        <Panel kicker="Reject" title="What reject does">
          <div className="md ink2">Closes the scoped hold and moves the intent to <b>rejected</b>: nothing is sent and the amount is no longer held, so it is available to the customer again. The customer device sees the outcome over the realtime channel.</div>
        </Panel>
      </div>
    </>
  );
}
