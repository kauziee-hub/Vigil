// LIVE STREAMS — Live transactions (intel.tx_scored: statuses, risks, scoring latency), Risky transactions (either
// party in early warning or worse right after scoring) and the Alert stream (status changes, decisions tier ≥ 1,
// CircuitBreaker). Push-only; lists flush to React at most every 600 ms.
// Until intel.tx_scored is served, raw ledger postings carry each party's CURRENT live status from the universe
// (RingWatch + Vigil state), the transaction list is seeded with the newest postings of the live window, and the alert
// stream with the newest PRIMA decisions tier ≥ 1 — all real rows, labelled as such.
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { AccountStatus, AccountStatusChange, DecisionSummary, LedgerTx, TxScored, UniverseEdge } from "../../api/types";
import { formatINR, formatTime, handle } from "../../lib/format";
import { useBufferedList } from "../../lib/live";
import { ACCOUNT_STATUS_LABEL, ACCOUNT_STATUS_RANK, TIER_SHORT, isRisky } from "../../lib/status";
import { useConsoleEvents } from "../Shell";
import { Panel, Sim } from "../ui";

type Row = { id: string; ts: string; s: string; r: string; amount: number; channel: string; origin: string; scored: boolean;
             ss?: AccountStatus; rs?: AccountStatus; sr?: number | null; rr?: number | null; ms?: number; scenario?: string | null };
type Alert = { key: string; ts: string; sev: "high" | "medium" | "low" | "held"; kind: string; who: string; text: string; link?: string };

const acct = (id: string) => <Link className="acct" to={`/investigations/account/${encodeURIComponent(id)}`}>{handle(id)}</Link>;

function TxRow({ x }: { x: Row }) {
  const risky = isRisky(x.ss) || isRisky(x.rs);
  const alarm = x.ss === "flagged" || x.rs === "flagged" || x.ss === "confirmed_fraud" || x.rs === "confirmed_fraud";
  return (
    <div className={`feed-row ${alarm ? "attack" : risky ? "risky" : ""}`}>
      <div className="h">{acct(x.s)}<span className="arr">→</span>{acct(x.r)}
        {x.ss && x.ss !== "normal" && x.ss !== "idle" && x.ss !== "external" && <span className={`pill as-${x.ss}`}>{ACCOUNT_STATUS_LABEL[x.ss].toLowerCase()}</span>}
        {x.rs && x.rs !== "normal" && x.rs !== "idle" && x.rs !== "external" && x.rs !== x.ss && <span className={`pill as-${x.rs}`}>{ACCOUNT_STATUS_LABEL[x.rs].toLowerCase()}</span>}
      </div>
      <div className="s">{formatINR(x.amount)} · {x.channel.toUpperCase()} · {formatTime(x.ts)} · {x.origin}{x.origin === "scenario" && <> <Sim text="SIM" /></>}</div>
      <div className="d">{x.id}{x.scored ? ` · risk ${x.sr != null ? x.sr.toFixed(2) : "—"} / ${x.rr != null ? x.rr.toFixed(2) : "—"} · ${x.ms != null ? `${x.ms.toFixed(1)} ms` : ""}` : ""}</div>
    </div>
  );
}

function decisionAlert(d: DecisionSummary): Alert {
  return {
    key: d.decision_id, ts: d.created_at, sev: d.tier >= 3 ? "held" : d.tier === 2 ? "medium" : "low", kind: `PRIMA ${TIER_SHORT[d.tier]}`,
    who: d.sender_id, text: `${handle(d.sender_id)} → ${handle(d.recipient_id)} ${formatINR(d.amount_paise)} · ${d.headline}${d.source === "ambient" ? " · background stream" : ""}`,
    link: `/investigations/decision/${d.decision_id}`,
  };
}

export function LiveStreams({ statusOf, recent }: { statusOf?: (id: string) => AccountStatus | null; recent?: UniverseEdge[] | null }) {
  const live = useBufferedList<Row>(40);
  const risky = useBufferedList<Row>(40);
  const alerts = useBufferedList<Alert>(50);
  const scoredSeen = useRef(false);
  const seeded = useRef(false);
  const alertsSeeded = useRef(false);

  const rawRow = (id: string, ts: string, s: string, r: string, amount: number, channel: string, origin: string, scenario: string | null): Row => ({
    id, ts, s, r, amount, channel, origin, scored: false, ss: statusOf?.(s) ?? undefined, rs: statusOf?.(r) ?? undefined, scenario,
  });

  // seed with the newest postings of the live window (oldest first, so the newest ends on top)
  useEffect(() => {
    if (seeded.current || !recent || !recent.length || scoredSeen.current) return;
    seeded.current = true;
    [...recent].reverse().forEach((x) => {
      const row = rawRow(x.id, x.ts, x.source, x.target, x.amount_paise, x.channel || "upi", x.origin, x.scenario);
      live.push(row);
      if (isRisky(row.ss) || isRisky(row.rs)) risky.push(row);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recent]);
  useEffect(() => {
    if (alertsSeeded.current) return;
    alertsSeeded.current = true;
    api.decisions(1).then((ds) => {
      ds.filter((d) => d.tier >= 1).slice(0, 12).reverse().forEach((d) => alerts.push(decisionAlert(d)));
    }).catch(() => undefined);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useConsoleEvents((e) => {
    switch (e.type) {
      case "intel.tx_scored": {
        const t = e.data as TxScored;
        if (!t?.tx_id) return;
        scoredSeen.current = true;
        const row: Row = { id: t.tx_id, ts: t.ts, s: t.sender_id, r: t.recipient_id, amount: t.amount_paise, channel: t.channel, origin: t.origin,
          scored: true, ss: t.sender_status, rs: t.recipient_status, sr: t.sender_risk, rr: t.recipient_risk, ms: t.scored_ms, scenario: t.scenario };
        live.push(row);
        if (isRisky(t.sender_status) || isRisky(t.recipient_status)) risky.push(row);
        break;
      }
      case "ledger.posted": {
        if (scoredSeen.current) return;          // once scored events flow, the scored row replaces the raw posting
        const t = e.data as LedgerTx & { channel?: string; seed_attack?: string | null };
        if (!t?.id) return;
        const row = rawRow(t.id, t.ts, t.sender_id, t.recipient_id, t.amount_paise, t.channel ?? "upi", t.source, t.seed_attack ?? null);
        live.push(row);
        if (isRisky(row.ss) || isRisky(row.rs)) risky.push(row);
        break;
      }
      case "intel.account_status": {
        const c = e.data as AccountStatusChange;
        if (!c?.account_id) return;
        // only risk changes are alerts: idle ↔ normal ↔ new is activity, not an alert
        if (!isRisky(c.status) && !isRisky(c.previous)) return;
        const up = ACCOUNT_STATUS_RANK[c.status] > ACCOUNT_STATUS_RANK[c.previous];
        const sev = c.status === "held" ? "held" : c.status === "flagged" || c.status === "confirmed_fraud" ? "high" : c.status === "early_warning" ? "medium" : "low";
        alerts.push({ key: `s${c.account_id}${c.ts}`, ts: c.ts, sev: up ? sev : "low", kind: `${ACCOUNT_STATUS_LABEL[c.status].toLowerCase()}`, who: c.account_id,
          text: `${handle(c.account_id)} ${up ? "entered" : "returned to"} ${ACCOUNT_STATUS_LABEL[c.status].toLowerCase()} (was ${ACCOUNT_STATUS_LABEL[c.previous].toLowerCase()})${c.reason ? `: ${c.reason}` : ""}${c.families_flagging ? ` · ${c.families_flagging} families` : ""}`,
          link: `/investigations/account/${encodeURIComponent(c.account_id)}` });
        break;
      }
      case "decision.created": {
        const d = e.data as DecisionSummary;
        if (!d?.decision_id || d.tier < 1) return;
        alerts.push(decisionAlert(d));
        break;
      }
      case "breaker.fired": {
        const b = e.data as { breaker_id: string; intent_id: string; headline: string; contact_name?: string; account_holder?: string };
        alerts.push({ key: b.breaker_id, ts: new Date().toISOString(), sev: "high", kind: "CircuitBreaker fired", who: b.account_holder ?? "",
          text: `${b.contact_name ? `Trusted contact ${b.contact_name} alerted` : "Trusted contact alerted"} · ${b.headline}`, link: "/interventions" });
        break;
      }
      case "breaker.responded": {
        const b = e.data as { breaker_id: string; text: string; ts: string };
        alerts.push({ key: `${b.breaker_id}r`, ts: b.ts, sev: "low", kind: "CircuitBreaker response", who: "", text: b.text, link: "/interventions" });
        break;
      }
      case "demo.reset":
        live.clear(); risky.clear(); alerts.clear(); scoredSeen.current = false; seeded.current = false;
        break;
    }
  });

  const scored = scoredSeen.current;
  return (
    <div className="grid cols-3 align-start">
      <Panel kicker="Stream" title="Live transactions" flush actions={<span className="chip mute">last {live.items.length} of {live.count}</span>}
             footer={scored ? "Each posting after live scoring: sender / recipient status and network risk, scoring latency."
               : "Ledger postings — the newest of the live window, then each one as it posts. Pills = each party's current live status (RingWatch + Vigil state); per-posting scores appear once intel.tx_scored is served."}>
        <div className="feed feed-scroll">
          {live.items.length === 0 ? <div className="empty">Waiting for the next posting…</div> : live.items.map((x) => <TxRow key={x.id} x={x} />)}
        </div>
      </Panel>
      <Panel kicker="Detector" title="Risky transactions" flush actions={<span className={`chip ${risky.count ? "danger" : "mute"}`}>{risky.count} in last {live.count}</span>}
             footer={scored ? "Postings where the sender or recipient was in early warning or worse right after scoring."
               : "Postings where the sender or recipient is in early warning or worse (live status at the time it was shown)."}>
        <div className="feed feed-scroll">
          {risky.items.length === 0 ? <div className="empty">No risky posting in the live window or since this page opened.</div> : risky.items.map((x) => <TxRow key={x.id} x={x} />)}
        </div>
      </Panel>
      <Panel kicker="Alerts" title="Alert stream" flush actions={<span className="chip mute">{alerts.count} total</span>}
             footer="Account status changes · PRIMA decisions tier ≥ 1 (newest at load, then pushed) · CircuitBreaker.">
        <div className="feed-scroll">
          {alerts.items.length === 0 ? <div className="empty">No PRIMA alert and no status change yet.</div> : alerts.items.map((a) => (
            <div key={a.key} className="alert-row">
              <div className="h"><span className={`sev ${a.sev}`}>{a.sev}</span>{a.link ? <Link to={a.link}>{a.kind}</Link> : <b>{a.kind}</b>}</div>
              <div className="ink2">{a.text}</div>
              <div className="dim mono xs">{formatTime(a.ts)}</div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
