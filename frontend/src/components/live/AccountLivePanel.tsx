// Account investigation (v3): live status from the universe + pushed status changes, alerts (PRIMA decisions involving
// the account and status transitions), and SIMULATOR GROUND TRUTH (attack runs that injected this account).
// `useAccountLive` holds the state; `AccountAlerts` / `GroundTruth` render it; `AccountLivePanel` is the compact panel.
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

export interface AccountLive {
  status: AccountStatus | null;
  risk: number | null;
  modelRisk: number | null;
  role: string | null;
  lastActive: string | null;
  reason: string;
  families: number | null;
  changes: AccountStatusChange[];
  decisions: DecisionSummary[];
  injectedBy: AttackRun[];
  falsePositiveIn: AttackRun[];
  universeUnavailable: boolean;
  runsUnavailable: boolean;
  loading: boolean;
  /** Live status of any account in the universe (neighbours), or null when unknown. */
  statusOf: (id: string) => AccountStatus | null;
}

export function useAccountLive(accountId: string): AccountLive {
  const uni = useLoad<LiveUniverse>(() => api.universe({ history: 0 }), [accountId]);
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
    } else if (e.type === "demo.reset") {
      setLive(null); setChanges([]); uni.reload(); decisions.reload();
    }
  });
  const acct = uni.data?.accounts.find((a) => a.id === accountId) ?? null;
  const statusMap = useMemo(() => new Map((uni.data?.accounts ?? []).map((a) => [a.id, a.status] as const)), [uni.data]);
  const mine = useMemo(() => (decisions.data ?? []).filter((d) => d.sender_id === accountId || d.recipient_id === accountId).slice(0, 10), [decisions.data, accountId]);
  return {
    status: live?.status ?? acct?.status ?? null,
    risk: live?.risk ?? acct?.risk ?? null,
    modelRisk: acct?.model_risk ?? null,
    role: live?.role ?? acct?.role ?? null,
    lastActive: acct?.last_active ?? null,
    reason: live?.reason ?? "",
    families: live?.families ?? null,
    changes,
    decisions: mine,
    injectedBy: (runs.data ?? []).filter((r) => r.injected.includes(accountId)),
    falsePositiveIn: (runs.data ?? []).filter((r) => r.false_positives.includes(accountId)),
    universeUnavailable: uni.unavailable,
    runsUnavailable: runs.unavailable,
    loading: uni.loading && !uni.data,
    statusOf: (id: string) => statusMap.get(id) ?? null,
  };
}

export function AccountAlerts({ live, accountId }: { live: AccountLive; accountId: string }) {
  if (live.changes.length === 0 && live.decisions.length === 0) {
    return <div className="xs muted">No PRIMA decision tier ≥ 1 involves this account; no status change since this page opened.</div>;
  }
  return (
    <>
      {live.changes.map((c) => (
        <div key={c.ts + c.status} className="alert-row" style={{ padding: "6px 0" }}>
          <div className="h"><span className={`pill as-${c.status}`}>{ACCOUNT_STATUS_LABEL[c.status].toLowerCase()}</span><span className="mono xs dim">{formatTime(c.ts)}</span></div>
          <div className="ink2 sm">was {ACCOUNT_STATUS_LABEL[c.previous].toLowerCase()}{c.reason ? ` — ${c.reason}` : ""}</div>
        </div>
      ))}
      {live.decisions.length > 0 && (
        <table className="dt compact">
          <thead><tr><th>Tier</th><th>Decision</th><th className="num">Amount</th><th>Time</th></tr></thead>
          <tbody>
            {live.decisions.map((d) => (
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
    </>
  );
}

export function GroundTruth({ live, accountId }: { live: AccountLive; accountId: string }) {
  if (live.runsUnavailable) return <div className="xs muted">Attack runs (/api/attacks/runs) not served.</div>;
  if (live.injectedBy.length === 0 && live.falsePositiveIn.length === 0) return <div className="xs muted">Not part of any simulated attack run since the last reset.</div>;
  return (
    <div className="stack" style={{ gap: 4 }}>
      {live.injectedBy.map((r) => (
        <div key={r.run_id} className="sm">Injected as a mule by <b className="mono">{r.run_id}</b> · {r.name} — {r.detected.includes(accountId)
          ? <span style={{ color: "var(--st-critical)" }}>detected{r.detection_ms != null ? ` (+${(r.detection_ms / 1000).toFixed(2)} s)` : ""}</span>
          : r.warned.includes(accountId) ? <span style={{ color: "var(--st-watch)" }}>warned, not flagged</span>
          : r.status === "completed" ? <span style={{ color: "var(--st-watch)" }}>missed</span> : r.status}</div>
      ))}
      {live.falsePositiveIn.map((r) => <div key={`fp${r.run_id}`} className="sm">Flagged during <b className="mono">{r.run_id}</b> without being injected — counted as a false positive.</div>)}
    </div>
  );
}

export function LiveStatusLine({ live }: { live: AccountLive }) {
  if (live.universeUnavailable && !live.status) return <div className="xs muted">Live status (/api/live/universe) not served yet.</div>;
  return (
    <div className="row wrap">
      {live.status ? <span className={`pill lg as-${live.status}`}>{ACCOUNT_STATUS_LABEL[live.status]}</span> : <span className="xs muted">{live.loading ? "loading…" : "not in the live universe"}</span>}
      {live.role && <span className="tag">{ROLE_LABEL[live.role] ?? live.role}</span>}
      {live.risk != null && <span className="mono sm" style={{ color: STATUS_HEX[scoreStatus(live.risk)] }}>network risk {live.risk.toFixed(2)}</span>}
      {live.modelRisk != null && <span className="mono sm muted">model evidence {live.modelRisk.toFixed(2)} (corroborating)</span>}
      {live.lastActive && <span className="xs muted">last active {formatTime(live.lastActive)}</span>}
    </div>
  );
}

/** Compact panel (used where the full investigation layout is not shown). */
export function AccountLivePanel({ accountId }: { accountId: string }) {
  const live = useAccountLive(accountId);
  return (
    <Panel kicker="Live status · alerts" title="Where this account stands now" flush>
      <div className="sect">
        <LiveStatusLine live={live} />
        {live.reason && <div className="sm ink2" style={{ marginTop: 8 }}>{live.reason}{live.families ? ` · ${live.families} detector families agree` : ""}</div>}
      </div>
      <div className="sect"><div className="sect-t">Alerts</div><AccountAlerts live={live} accountId={accountId} /></div>
      <div className="sect">
        <div className="sect-t">Simulator ground truth <span className="sim gt">evaluation only — never scored</span></div>
        <GroundTruth live={live} accountId={accountId} />
      </div>
    </Panel>
  );
}
