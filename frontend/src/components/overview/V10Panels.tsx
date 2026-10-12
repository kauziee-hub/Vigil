// Overview v10 panels: KPI strip, needs attention, situation brief, mule pipeline, money by channel.
// Every number comes from /api/overview/* (read-only, live via WebSocket-triggered refreshes, no polling).
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { v10, type AttentionRow, type Brief, type ChannelMix, type KpiTile, type Kpis, type Pipeline, type Stage } from "../../api/v10";
import { formatINR, formatPaiseShort, formatTime, handle } from "../../lib/format";
import { useThrottled } from "../../lib/live";
import { useSelection } from "../../lib/selection";
import { ACCOUNT_STATUS_LABEL, ROLE_LABEL } from "../../lib/status";
import { RoleIcon } from "../intel";
import { useConsoleEvents } from "../Shell";

function useLive<T>(fn: () => Promise<T>, deps: unknown[], events: string[], ms = 3000) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState(false);
  const load = useCallback(() => { fn().then((d) => { setData(d); setErr(false); }).catch(() => setErr(true)); },
    deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  const t = useThrottled(load, ms);
  useConsoleEvents((e) => { if (events.includes(e.type)) t(); });
  return { data, err, reload: load };
}

const LIVE = ["ledger.posted", "intel.account_status", "decision.created", "intent.updated", "demo.reset", "attack.run_updated",
  "taint.updated", "account.opened"];

// ── KPI strip ─────────────────────────────────────────────────────────────
function Spark({ v, tone }: { v: number[]; tone?: string | null }) {
  const max = Math.max(1, ...v);
  const pts = v.map((x, i) => `${(i / Math.max(1, v.length - 1)) * 100},${28 - (x / max) * 26}`).join(" ");
  return <svg className={`kspark ${tone ?? ""}`} viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true"><polyline points={pts} /></svg>;
}

function fmt(t: KpiTile, v: number | null) {
  if (v == null) return "—";
  return t.unit === "paise" ? formatPaiseShort(v) : v.toLocaleString("en-IN");
}

export function KpiStripV10({ onTile }: { onTile: (key: KpiTile["key"]) => void }) {
  const { window, channel, incident } = useSelection();
  const k = useLive<Kpis>(() => v10.kpis(window, channel, incident?.entities), [window, channel, incident?.id], LIVE, 2500);
  return (
    <div className="kpi-strip v10" role="list" aria-label="Key figures">
      {(k.data?.tiles ?? Array.from({ length: 6 }, () => null)).map((t, i) => t ? (
        <button key={t.key} className={`kpi ${t.tone ?? ""}`} role="listitem" onClick={() => onTile(t.key)} title={t.how}>
          <div className="k">{t.label}{k.data?.scope ? " · incident" : ""}</div>
          <div className="v">{fmt(t, t.value)}</div>
          <div className="d">
            {t.delta != null ? <span className={`delta ${t.delta > 0 ? "up" : t.delta < 0 ? "down" : "flat"}`}>
              {t.delta > 0 ? "▲" : t.delta < 0 ? "▼" : "•"} {fmt(t, Math.abs(t.delta))}<span className="delta-tail"> vs previous {window}</span></span>
              : <span className="dim">{t.how.length > 60 ? t.how.slice(0, 58) + "…" : t.how}</span>}
          </div>
          {t.spark && <Spark v={t.spark} tone={t.tone} />}
        </button>
      ) : <div key={i} className="kpi"><div className="k">…</div><div className="v">—</div></div>)}
    </div>
  );
}

// ── needs attention ───────────────────────────────────────────────────────
export function NeedsAttention({ onAsk }: { onAsk: (accountId: string) => void }) {
  const nav = useNavigate();
  const { select } = useSelection();
  const a = useLive(() => v10.attention(), [], LIVE, 3000);
  const rows: AttentionRow[] = a.data?.accounts ?? [];
  return (
    <div className="kcard attn-v10">
      <div className="kcard-h"><span>Needs attention</span><span className="act"><span className="chip mute">{rows.length} account{rows.length === 1 ? "" : "s"}</span></span></div>
      <div className="ksub">Flagged, held, confirmed or early-warning accounts right now — money in / out (24 h), since when, and why.</div>
      {rows.length === 0 ? <div className="empty">Nothing needs action. Statuses update live.</div> : (
        <div className="attn-list">
          {rows.slice(0, 12).map((r) => (
            <div key={r.id} className={`attn-row as-b-${r.status}`} tabIndex={0}
                 onClick={() => select({ kind: "account", id: r.id, label: r.name })}
                 onKeyDown={(e) => { if (e.key === "Enter") select({ kind: "account", id: r.id, label: r.name }); }}>
              <div className="row tight" style={{ justifyContent: "space-between" }}>
                <span className="cell-2l"><b>{r.name}</b><small className="why" title={r.reason ?? ""}>{r.reason || handle(r.id)}</small></span>
                <span className={`pill as-${r.status}`}>{ACCOUNT_STATUS_LABEL[r.status]}</span>
              </div>
              <div className="attn-meta">
                <span>in <b>{formatPaiseShort(r.in_paise_24h)}</b></span><span>out <b>{formatPaiseShort(r.out_paise_24h)}</b></span>
                {r.since && <span className="dim">since {formatTime(r.since).slice(0, 5)}</span>}
                {r.families_flagging > 0 && <span className="dim" title="Independent detector families agreeing">{r.families_flagging} families</span>}
                {r.role && <span className="row tight"><RoleIcon role={r.role} size={11} />{ROLE_LABEL[r.role] ?? r.role}</span>}
                {r.ring_id && <span className="tag danger" title="Part of a detected cluster of risky accounts">ring</span>}
                {r.collection_point && <span className="tag warn" title="Distinct-sender fan-in at or above the risk policy's threshold">collection point</span>}
              </div>
              <div className="attn-act">
                <button className="btn xs" onClick={(e) => { e.stopPropagation(); nav(`/investigations/account/${encodeURIComponent(r.id)}`); }}>Open</button>
                <button className="btn xs" onClick={(e) => { e.stopPropagation(); onAsk(r.id); }}>Ask Copilot</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── situation brief ───────────────────────────────────────────────────────
export function SituationBrief({ onAsk }: { onAsk: () => void }) {
  const { window } = useSelection();
  const b = useLive<Brief>(() => v10.brief(window), [window], LIVE, 4000);
  return (
    <div className="kcard brief-card">
      <div className="kcard-h"><span>Situation brief</span><span className="act"><span className="chip mute" title="Built deterministically from live data — no AI">{b.data?.llm_used ? "AI-polished" : "deterministic"}</span></span></div>
      {!b.data ? <div className="ksub">Loading…</div> : (
        <ol className="brief-lines">{b.data.lines.map((l, i) => <li key={i}>{l}</li>)}</ol>
      )}
      <button className="btn sm primary" onClick={onAsk}>Ask Copilot</button>
    </div>
  );
}

// ── mule pipeline ─────────────────────────────────────────────────────────
const STAGE_HELP: Record<Stage, string> = {
  opened: "Accounts opened in the last 60 days.",
  funded: "Received their first money.",
  active: "Have also sent money out.",
  passing_through: "Forwarded most of what came in within hours (rule below).",
  exited: "…and sent money out of the bank (cash, other banks, international).",
};

export function MulePipeline() {
  const nav = useNavigate();
  const { select } = useSelection();
  const p = useLive<Pipeline>(() => v10.pipeline(60), [], ["account.opened", "ledger.posted", "demo.reset", "intel.account_status"], 4000);
  const [stage, setStage] = useState<Stage | null>(null);
  const [onlySus, setOnlySus] = useState(false);
  const d = p.data;
  const maxN = Math.max(1, ...(d?.stages ?? []).map((s) => s.count));
  const order: Stage[] = ["opened", "funded", "active", "passing_through", "exited"];
  const list = (d?.accounts ?? []).filter((a) => (!stage || order.indexOf(a.stage) >= order.indexOf(stage)) && (!onlySus || a.suspicious_path))
    .sort((x, y) => Number(y.suspicious_path) - Number(x.suspicious_path) || y.in_paise - x.in_paise);
  return (
    <div className="kcard pipe-card">
      <div className="kcard-h"><span>Mule pipeline</span><span className="act">
        <button className={`chipbtn ${onlySus ? "on" : ""}`} onClick={() => setOnlySus((v) => !v)} aria-pressed={onlySus}>Suspicious path · {d?.suspicious ?? 0}</button></span></div>
      <div className="ksub">How new accounts are being used. Ordinary new customers stop at <i>Active</i>; a mule account races on to <i>Passing through</i> and <i>Exited</i>. Click a stage to list its accounts.</div>
      <div className="pipe-funnel" role="list">
        {(d?.stages ?? []).map((s) => (
          <button key={s.key} role="listitem" className={`pipe-stage ${stage === s.key ? "on" : ""} st-${s.key}`} title={STAGE_HELP[s.key]}
                  onClick={() => setStage((x) => (x === s.key ? null : s.key))}>
            <span className="ps-label">{s.label}</span>
            <span className="ps-bar"><i style={{ width: `${(s.count / maxN) * 100}%` }} /></span>
            <span className="ps-n">{s.count}</span>
            <span className="ps-v dim">{formatPaiseShort(s.value_paise)} in</span>
          </button>
        ))}
      </div>
      <div className="pipe-list">
        {list.length === 0 ? <div className="empty">{d ? "No account at this stage." : "Loading…"}</div> : list.slice(0, 8).map((a) => (
          <div key={a.id} className={`pipe-row ${a.suspicious_path ? "sus" : ""}`} tabIndex={0}
               onClick={() => select({ kind: "account", id: a.id, label: a.name })}
               onDoubleClick={() => nav(`/investigations/account/${encodeURIComponent(a.id)}`)}>
            <div className="row tight" style={{ justifyContent: "space-between" }}>
              <span className="cell-2l"><b>{a.name}</b><small>{a.age_days < 1 ? `${Math.round(a.age_days * 24)} h` : `${a.age_days.toFixed(0)} d`} old
                {a.opened_via ? ` · opened via ${a.opened_via}` : ""}{a.opened_city ? ` · ${a.opened_city}` : ""}</small></span>
              <span className={`pill as-${a.status}`}>{ACCOUNT_STATUS_LABEL[a.status]}</span>
            </div>
            <div className="attn-meta">
              <span>in <b>{formatPaiseShort(a.in_paise)}</b></span><span>out <b>{formatPaiseShort(a.out_paise)}</b></span>
              {a.retention_pct != null && <span title="Share of what came in that is still in the account">keeps {a.retention_pct.toFixed(0)}%</span>}
              {a.forwarded_pct > 0 && <span title="Share of inflow forwarded within the pass-through window">forwards {a.forwarded_pct.toFixed(0)}%</span>}
              {a.exited_via.length > 0 && <span className="dim">exit: {a.exited_via.join(", ")}</span>}
              {a.device_shared_with.length > 0 && <span className={a.shared_note ? "tag" : "tag warn"} title={a.shared_note ?? "Device shared with other accounts"}>
                device shared ×{a.device_shared_with.length}{a.shared_note ? " · family/shop pattern" : ""}</span>}
              {a.suspicious_path && <span className="tag danger">suspicious path</span>}
            </div>
          </div>
        ))}
      </div>
      {d && <div className="ksub how">{d.rule}</div>}
    </div>
  );
}

// ── money by channel ──────────────────────────────────────────────────────
export function ChannelChart() {
  const { window, channel, setChannel } = useSelection();
  const m = useLive<ChannelMix>(() => v10.channels(window), [window], LIVE, 4000);
  const rails = (m.data?.rails ?? []).filter((r) => r.count > 0 || r.value_paise > 0);
  return (
    <div className="kcard chan-card">
      <div className="kcard-h"><span>Money by channel</span><span className="act">
        {channel !== "all" && <button className="chipbtn on" onClick={() => setChannel("all")}>Rail: {channel.toUpperCase()} ✕</button>}</span></div>
      <div className="ksub">For each payment rail: grey = its share of all money moved in the last {window}; red = its share of fraud-linked money.
        A rail whose red bar is longer than its grey bar is over-represented in fraud. Click a rail to filter the whole page.</div>
      {!m.data ? <div className="ksub">Loading…</div> : rails.length === 0 ? <div className="empty">No postings in this window.</div> : (
        <div className="chan-rows">
          {rails.map((r) => (
            <button key={r.rail} className={`chan-row ${channel === r.rail ? "on" : ""}`} onClick={() => setChannel(channel === r.rail ? "all" : r.rail)}
                    title={`${r.label}: ${r.count} postings, ${formatINR(r.value_paise)}; fraud-linked ${formatINR(r.fraud_linked_paise)}`}>
              <span className="cr-l">{r.label}</span>
              <span className="cr-bars">
                <span className="cr-bar value"><i style={{ width: `${r.share_value * 100}%` }} /><em>{(r.share_value * 100).toFixed(0)}%</em></span>
                <span className="cr-bar fraud"><i style={{ width: `${r.share_fraud * 100}%` }} /><em>{(r.share_fraud * 100).toFixed(0)}%</em></span>
              </span>
              <span className="cr-n mono xs">{formatPaiseShort(r.value_paise)}</span>
            </button>
          ))}
        </div>
      )}
      {m.data && <div className="ksub">{formatPaiseShort(m.data.total_paise)} moved · {formatPaiseShort(m.data.fraud_total_paise)} fraud-linked in the window.</div>}
    </div>
  );
}
