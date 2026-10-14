// INVESTIGATIONS — dense case list. Cases are the intervention alerts (/api/interventions), joined with the
// scenario / customer decision feed (/api/decisions) for reason labels. Accounts with network evidence
// (RingWatch) are the second entry point, into the account investigation view.
// v12.5: the page says where it sits (Transaction Guard decides → Cases follows up → Account Investigation goes
// deep), and each row shows why it is here — only engines named by the stored data (decision record, intent
// origin, RingWatch row, live detector status); a row with nothing to name shows no badge.
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { CaseSource, DecisionSummary, InterventionRow, RingRow } from "../api/types";
import { RoleIcon } from "../components/intel";
import { useConsoleEvents } from "../components/Shell";
import { Async, PageHead, Panel, Pill, Seg, StatePill, TierPill } from "../components/ui";
import { duration, formatINR, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad, useNow } from "../lib/hooks";
import { loadAlerts } from "../lib/queue";
import { ROLE_LABEL, scoreStatus } from "../lib/status";

const FAMILY_LABEL: Record<string, string> = {
  random_forest: "Random Forest", gnn: "GNN", rules: "Rules", drift: "Drift", early_warning: "Early warning",
  pattern_memory: "Pattern memory", ringwatch: "RingWatch", external: "Registry",
};
const MULE_FAMILIES = ["random_forest", "gnn", "rules", "drift", "early_warning", "pattern_memory"];
const names = (fs: string[]) => fs.map((f) => FAMILY_LABEL[f] ?? f).join(", ");

const SOURCE: Record<CaseSource | "location", { label: string; tip: (fs: string[]) => string }> = {
  ringwatch: { label: "RingWatch", tip: () => "RingWatch network rules fired on the recipient in this decision" },
  tainttrace: { label: "TaintTrace", tip: () => "Money traced to a confirmed scam (NET_TAINT_EXPOSURE)" },
  registry: { label: "Registry", tip: () => "The shared fraud registry has a report on the recipient" },
  mule_detection: { label: "Mule detection", tip: (fs) => `Flagged by ${names(fs)} — corroborating evidence, not used for the tier` },
  location: { label: "Location", tip: (fs) => `Location intelligence corroborates it: ${fs.join(", ")}` },
};
const ORIGIN: Record<string, { label: string; tip: string }> = {
  user: { label: "Customer", tip: "Customer decision: paid from the customer screen (Transaction guard phone or /pay)" },
  scenario: { label: "Scenario", tip: "Scenario or test input" },
  ambient: { label: "Stream", tip: "Background stream" },
};

function SourceBadges({ items }: { items: { key: CaseSource | "location"; fs?: string[] }[] }) {
  if (!items.length) return null;
  return (
    <div className="cs-src">
      {items.map(({ key, fs = [] }) => (
        <span key={key} className={`cs-b b-${key}`} title={SOURCE[key].tip(fs)}>
          {SOURCE[key].label}{key === "mule_detection" && fs.length > 0 && <i> · {fs.length}</i>}
        </span>
      ))}
    </div>
  );
}

export function InvestigationsPage() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = (params.get("status") as "open" | "all") || "all";
  const minTier = Number(params.get("tier") ?? 2);
  const [q, setQ] = useState("");
  const [acct, setAcct] = useState("");
  const now = useNow(10000);
  const rows = useLoad<InterventionRow[]>(() => loadAlerts(status), [status]);
  const feed = useLoad<DecisionSummary[]>(() => api.decisions(1));
  const ring = useLoad<RingRow[]>(api.ringwatch);
  const refresh = useDebounced(() => { rows.reload(); feed.reload(); }, 1200);
  const refreshRing = useDebounced(() => ring.reload(), 1500);

  useConsoleEvents((e) => {
    const t = (e.data as { tier?: number | null } | null)?.tier;
    if ((e.type === "decision.created" || e.type === "intent.updated") && (t ?? 0) >= Math.max(1, minTier)) refresh();
    else if (["breaker.fired", "breaker.responded", "demo.reset"].includes(e.type)) refresh();
    if (["ringwatch.scan", "taint.updated", "demo.reset"].includes(e.type)) refreshRing();
  });

  const setParam = (k: string, v: string | null) => {
    const next = new URLSearchParams(params);
    if (v === null) next.delete(k); else next.set(k, v);
    setParams(next, { replace: true });
  };

  // age_s is computed by the server at fetch time; the local clock only advances it between pushes.
  const fetchedAt = useMemo(() => Date.now(), [rows.data]);
  const labels = useMemo(() => new Map((feed.data ?? []).map((d) => [d.decision_id, d])), [feed.data]);
  // Alerts = every Tier ≥ 2 alert + the newest 100 of any tier (lib/queue.ts loadAlerts). Scenario / customer
  // decisions (≤ 50, non-ambient) without an alert row are merged in so they never drop out of the list;
  // their live state is shown only when the alert row is present (never guessed).
  const all = useMemo(() => {
    const out: (InterventionRow & { partial?: boolean })[] = [...(rows.data ?? [])];
    const seen = new Set(out.map((r) => r.decision_id));
    if (status === "all") {
      (feed.data ?? []).forEach((d) => {
        if (seen.has(d.decision_id)) return;
        out.push({
          intent_id: d.intent_id, decision_id: d.decision_id, sender_id: d.sender_id, recipient_id: d.recipient_id,
          amount_paise: d.amount_paise, tier: d.tier, kind: d.kind, state: "" as InterventionRow["state"], headline: d.headline,
          opened_at: d.created_at, age_s: (fetchedAt - Date.parse(d.created_at)) / 1000, sla_due: null, hold: null,
          circuit_breaker: null, mode: "active", partial: true, origin: d.source, sources: d.sources, flagged_by: d.flagged_by,
        });
      });
    }
    return out.sort((a, b) => Date.parse(b.opened_at) - Date.parse(a.opened_at));
  }, [rows.data, feed.data, status, fetchedAt]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return all.filter((r) => r.tier >= minTier).filter((r) => !needle ||
      [r.decision_id, r.intent_id, r.sender_id, r.recipient_id, r.headline].some((s) => s.toLowerCase().includes(needle)));
  }, [all, minTier, q]);
  const byTier = useMemo(() => {
    const c: Record<number, number> = {};
    all.forEach((r) => { c[r.tier] = (c[r.tier] ?? 0) + 1; });
    return c;
  }, [all]);
  const tierCount = (t: number) => Object.entries(byTier).filter(([k]) => Number(k) >= t).reduce((s, [, v]) => s + v, 0);

  return (
    <>
      <PageHead crumb="Intelligence · Investigations" title="Cases"
        lede={<>
          <div className="cs-sub">Payments and accounts requiring analyst attention</div>
          Every intervention is a case: why it was risky, what each detector saw, what would have made it safe, and what to do next. Open a case for its Decision Replay, or an account for its risk history and model evidence.
        </>} />

      <div className="cs-flow" aria-label="Where Cases sits">
        <Link className="cs-step" to="/guard" title="Open Transaction guard">
          <b>Transaction guard</b><span>decides one payment live, before money moves</span>
        </Link>
        <span className="cs-arrow" aria-hidden>→</span>
        <div className="cs-step here" aria-current="page">
          <b>Cases <em>you are here</em></b><span>the work queue after the decision: review and follow up — no payment is decided here</span>
        </div>
        <span className="cs-arrow" aria-hidden>→</span>
        <div className="cs-step">
          <b>Account investigation</b><span>one account in depth: mule behaviour, RingWatch network, related activity — even with no payment in flight</span>
        </div>
      </div>

      <div className="grid cols-ms align-start">
        <Panel kicker="Cases" title={<>Payment Cases <span className="dim">· {shown.length}</span></>} flush
               q={status === "open" ? "open alerts" : "every Tier ≥ 2 alert + newest 100 alerts + every scenario / customer decision"}
               actions={<>
                 <input className="input sm" style={{ width: 200 }} placeholder="Filter id / account / headline" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter cases" />
                 <Seg options={[["4", `T4 · ${tierCount(4)}`], ["3", `T3+ · ${tierCount(3)}`], ["2", `T2+ · ${tierCount(2)}`], ["1", `T1+ · ${tierCount(1)}`]]}
                      value={String(minTier) as "1" | "2" | "3" | "4"} onChange={(v) => setParam("tier", v === "2" ? null : v)} />
                 <Seg options={[["all", "All"], ["open", "Open"]]} value={status} onChange={(v) => setParam("status", v === "all" ? null : v)} />
               </>}
               footer="Tier 1 (inform) cases are mostly background-stream heads-ups; the default view starts at Tier 2. Org. = where the payment came from: Customer (customer screen), Scenario (scenario or test input), Stream (background stream). Badges under Why name the engines in the decision record.">
          <div className="cs-note">
            Tier 2+ payment decisions and interventions requiring review or follow-up.
            <span className="dim"> Each one was already decided by PRIMA in Transaction guard before money moved; open a row for its case, or <b>PRIMA record</b> for the audit copy.</span>
          </div>
          <Async load={rows} what="Intervention queue" endpoint="/api/interventions">
            {() => shown.length === 0 ? <div className="empty">No cases at this tier yet. Cases open as payments are assessed.</div> : (
              <div className="tscroll" style={{ maxHeight: "calc(100vh - 230px)" }}>
                <table className="dt compact">
                  <thead>
                    <tr><th>Opened</th><th>Case</th><th>Sender → recipient</th><th className="num">Amount</th><th>Tier</th><th>State</th><th>Why</th><th>Hold · review</th><th>Contact</th><th>Org.</th></tr>
                  </thead>
                  <tbody>
                    {shown.map((r) => {
                      const d = labels.get(r.decision_id);
                      const due = r.sla_due ? (Date.parse(r.sla_due) - now) / 1000 : null;
                      const holdOpen = r.hold && !r.hold.outcome;
                      const origin = r.origin ?? d?.source;
                      const srcs = (r.sources ?? d?.sources ?? []).map((key) => ({ key, fs: r.flagged_by ?? d?.flagged_by ?? [] }));
                      return (
                        <tr key={r.decision_id} className="click" onClick={() => nav(`/investigations/decision/${r.decision_id}`)}>
                          <td className="mono xs nowrap">{formatTime(r.opened_at)}<div className="dim">{duration(r.age_s + Math.max(0, now - fetchedAt) / 1000)} ago</div></td>
                          <td className="mono xs nowrap">{r.decision_id}{r.mode === "shadow" && <div><Pill status="watch">shadow</Pill></div>}
                            <div><Link className="cs-rec" to={`/governance/decision/${r.decision_id}`} onClick={(e) => e.stopPropagation()}
                                       title="The PRIMA decision record for this payment (audit copy)">PRIMA record ↗</Link></div>
                          </td>
                          <td className="xs">{handle(r.sender_id)}<div className="dim">→ {handle(r.recipient_id)}</div></td>
                          <td className="num">{formatINR(r.amount_paise)}</td>
                          <td><TierPill tier={r.tier} /></td>
                          <td>{r.partial ? <span className="xs dim" title="No alert row in the list; open the case for its live state">open case</span> : <StatePill state={r.state} />}</td>
                          <td className="xs" style={{ maxWidth: 300 }}>
                            <div className="ell">{d && d.labels.length ? d.labels.join(" · ") : r.headline}</div>
                            <SourceBadges items={srcs} />
                          </td>
                          <td className="xs nowrap">
                            {r.hold ? <>
                              <span className="mono" style={{ color: holdOpen ? "var(--st-held)" : undefined }}>{formatINR(r.hold.held_paise)}</span>
                              <div className={due !== null && due < 0 && holdOpen ? "" : "dim"} style={due !== null && due < 0 && holdOpen ? { color: "var(--st-critical)" } : undefined}>
                                {r.hold.outcome ? r.hold.outcome : due === null ? "—" : due < 0 ? `overdue ${duration(-due)}` : `review in ${duration(due)}`}
                              </div>
                            </> : <span className="dim">—</span>}
                          </td>
                          <td className="xs">{r.circuit_breaker ? <>{r.circuit_breaker.contact}<div className="dim">{r.circuit_breaker.response?.replace(/_/g, " ") ?? "awaiting"}</div></> : <span className="dim">—</span>}</td>
                          <td>{origin && ORIGIN[origin]
                            ? <span className={`tag cs-org o-${origin}`} title={ORIGIN[origin].tip}>{ORIGIN[origin].label}</span>
                            : <span className="dim">—</span>}</td>
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
          <Panel kicker="Accounts" title="Open an account investigation">
            <form className="row tight" onSubmit={(e) => { e.preventDefault(); if (acct.trim()) nav(`/investigations/account/${encodeURIComponent(acct.trim().includes("@") ? acct.trim() : `${acct.trim()}@vigil`)}`); }}>
              <input className="input sm grow" placeholder="account id, e.g. kiran.traders@vigil" value={acct} onChange={(e) => setAcct(e.target.value)} aria-label="Account id" />
              <button className="btn sm" type="submit" disabled={!acct.trim()}>Open</button>
            </form>
          </Panel>
          <Panel kicker="RingWatch" title="Accounts with Network Evidence" flush q="RingWatch rule engine · score ≥ 0.30">
            <div className="cs-note">
              Accounts surfaced by network/detection evidence for deeper investigation.
              <span className="dim"> Click one to open its account investigation — no payment needs to be in flight.</span>
            </div>
            <Async load={ring} what="RingWatch" endpoint="/api/ringwatch">
              {(list) => list.length === 0 ? <div className="empty">No account currently shows network evidence.</div> : (
                <div className="tscroll" style={{ maxHeight: "calc(100vh - 330px)" }}>
                  <table className="dt compact">
                    <thead><tr><th>Account</th><th style={{ width: "30%" }}>Role</th><th style={{ width: "34%" }}>Score</th></tr></thead>
                    <tbody>
                      {list.map((r) => {
                        const mule = (r.families ?? []).filter((f) => MULE_FAMILIES.includes(f));
                        const srcs: { key: CaseSource | "location"; fs?: string[] }[] = [
                          ...(r.rules.includes("NET_TAINT_EXPOSURE") ? [{ key: "tainttrace" as const }] : []),
                          ...((r.families ?? []).includes("external") ? [{ key: "registry" as const }] : []),
                          ...(mule.length ? [{ key: "mule_detection" as const, fs: mule }] : []),
                          ...(r.location_rules?.length ? [{ key: "location" as const, fs: r.location_rules }] : []),
                        ];
                        return (
                        <tr key={r.account_id} className="click" onClick={() => nav(`/investigations/account/${encodeURIComponent(r.account_id)}`)}
                            title={r.labels.join(" · ")}>
                          <td className="xs"><span className="cs-acct">{handle(r.account_id)}</span> {r.labelled && <Pill status="fraud">confirmed</Pill>}
                            <SourceBadges items={srcs} />
                          </td>
                          <td className="xs"><span className="row tight"><RoleIcon role={r.role} />{r.role ? ROLE_LABEL[r.role] ?? r.role : "—"}</span></td>
                          <td><span className="row tight"><span className="grow"><span className="bar" style={{ display: "block" }}><i style={{ width: `${r.score * 100}%`, background: `var(--st-${scoreStatus(r.score)})` }} /></span></span><span className="mono xs">{r.score.toFixed(2)}</span></span></td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </Async>
          </Panel>
        </div>
      </div>
    </>
  );
}
