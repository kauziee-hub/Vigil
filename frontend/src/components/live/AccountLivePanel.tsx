// Account investigation (v3): live status from the universe + pushed status changes, alerts (PRIMA decisions involving
// the account and status transitions), and SIMULATOR GROUND TRUTH (attack runs that injected this account).
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { AccountStatus, AccountStatusChange, AttackRun, DecisionSummary, LiveUniverse, TxScored } from "../../api/types";
import { formatINR, formatTime, handle } from "../../lib/format";
import { useLoad } from "../../lib/hooks";
import { useAttackRuns } from "../../lib/live";
import { ACCOUNT_STATUS_LABEL, ROLE_LABEL, STATUS_HEX, scoreStatus } from "../../lib/status";
import { useConsoleEvents } from "../Shell";
import { Panel, TierPill } from "../ui";

export function AccountLivePanel({ accountId }: { accountId: string }) {
  const uni = useLoad<LiveUniverse>(() => api.universe(), [accountId]);
  const decisions = useLoad<DecisionSummary[]>(() => api.decisions(1), [accountId]);
  const runs = useAttackRuns();
  const [live, setLive] = useState<{ status: AccountStatus; risk: number | null; role: string | null; families: number | null; reason: string } | null>(null);
  const [changes, setChanges] = useState<AccountStatusChange[]>([]);
  useConsoleEvents((e) => {
    if (e.type === "intel.account_status") {
      const c = e.data as AccountStatusChange;
      if (c?.account_id !== accountId) return;
      setLive({ status: c.status, risk: c.risk, role: c.role, families: c.families_flagging, reason: c.reason });
      setChanges((xs) => [c, ...xs].slice(0, 20));
    } else if (e.type === "intel.tx_scored") {
      const t = e.data as TxScored;
      if (t?.sender_id === accountId) setLive((l) => ({ status: t.sender_status, risk: t.sender_risk, role: l?.role ?? null, families: l?.families ?? null, reason: l?.reason ?? "" }));
      else if (t?.recipient_id === accountId) setLive((l) => ({ status: t.recipient_status, risk: t.recipient_risk, role: l?.role ?? null, families: l?.families ?? null, reason: l?.reason ?? "" }));
    } else if (e.type === "decision.created") {
      const d = e.data as DecisionSummary;
      if (d && d.tier >= 1 && (d.sender_id === accountId || d.recipient_id === accountId)) decisions.setData((xs) => [d, ...(xs ?? [])]);
    }
  });
  const acct = uni.data?.accounts.find((a) => a.id === accountId) ?? null;
  const status = live?.status ?? acct?.status ?? null;
  const risk = live?.risk ?? acct?.risk ?? null;
  const role = live?.role ?? acct?.role ?? null;
  const mine = useMemo(() => (decisions.data ?? []).filter((d) => d.sender_id === accountId || d.recipient_id === accountId).slice(0, 8), [decisions.data, accountId]);
  const injectedBy: AttackRun[] = (runs.data ?? []).filter((r) => r.injected.includes(accountId));
  const fpIn: AttackRun[] = (runs.data ?? []).filter((r) => r.false_positives.includes(accountId));

  return (
    <Panel kicker="Live status · alerts" title="Where this account stands now" flush>
      <div className="sect">
        {uni.unavailable && !live ? <div className="xs muted">Live status (/api/live/universe) not served yet.</div> : (
          <div className="row wrap">
            {status ? <span className={`pill lg as-${status}`}>{ACCOUNT_STATUS_LABEL[status]}</span> : <span className="xs muted">loading…</span>}
            {role && <span className="tag">{ROLE_LABEL[role] ?? role}</span>}
            {risk != null && <span className="mono sm" style={{ color: STATUS_HEX[scoreStatus(risk)] }}>network risk {risk.toFixed(2)}</span>}
            {acct?.model_risk != null && <span className="mono sm muted">model evidence {acct.model_risk.toFixed(2)} (corroborating)</span>}
            {acct?.last_active && <span className="xs muted">last active {formatTime(acct.last_active)}</span>}
          </div>
        )}
        {live?.reason && <div className="sm ink2" style={{ marginTop: 8 }}>{live.reason}{live.families ? ` · ${live.families} detector families agree` : ""}</div>}
      </div>
      <div className="sect">
        <div className="sect-t">Alerts</div>
        {changes.length === 0 && mine.length === 0 && <div className="xs muted">No PRIMA decision tier ≥ 1 involves this account; no status change since this page opened.</div>}
        {changes.map((c) => (
          <div key={c.ts + c.status} className="alert-row" style={{ padding: "6px 0" }}>
            <div className="h"><span className={`pill as-${c.status}`}>{ACCOUNT_STATUS_LABEL[c.status].toLowerCase()}</span><span className="mono xs dim">{formatTime(c.ts)}</span></div>
            <div className="ink2 sm">was {ACCOUNT_STATUS_LABEL[c.previous].toLowerCase()}{c.reason ? ` — ${c.reason}` : ""}</div>
          </div>
        ))}
        {mine.length > 0 && (
          <table className="dt compact">
            <tbody>
              {mine.map((d) => (
                <tr key={d.decision_id}>
                  <td style={{ width: 52 }}><TierPill tier={d.tier} /></td>
                  <td className="xs fill"><div className="ell"><Link to={`/investigations/decision/${d.decision_id}`}>{d.sender_id === accountId ? `→ ${handle(d.recipient_id)}` : `← ${handle(d.sender_id)}`}</Link> · {d.headline}</div></td>
                  <td className="num xs">{formatINR(d.amount_paise)}</td>
                  <td className="mono xs dim">{formatTime(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="sect">
        <div className="sect-t">Simulator ground truth <span className="sim gt">evaluation only — never scored</span></div>
        {runs.unavailable ? <div className="xs muted">Attack runs (/api/attacks/runs) not served.</div>
          : injectedBy.length === 0 && fpIn.length === 0 ? <div className="xs muted">Not injected by any attack run since the last reset.</div> : (
            <div className="stack" style={{ gap: 4 }}>
              {injectedBy.map((r) => (
                <div key={r.run_id} className="sm">Injected as a mule by <b className="mono">{r.run_id}</b> · {r.name} — {r.detected.includes(accountId) ? <span style={{ color: "var(--st-critical)" }}>detected{r.detection_ms != null ? ` (+${(r.detection_ms / 1000).toFixed(2)} s)` : ""}</span> : r.warned.includes(accountId) ? <span style={{ color: "var(--st-watch)" }}>warned, not flagged</span> : r.status === "completed" ? <span style={{ color: "var(--st-watch)" }}>missed</span> : r.status}</div>
              ))}
              {fpIn.map((r) => <div key={`fp${r.run_id}`} className="sm">Flagged during <b className="mono">{r.run_id}</b> without being injected — counted as a false positive.</div>)}
            </div>
          )}
      </div>
    </Panel>
  );
}
