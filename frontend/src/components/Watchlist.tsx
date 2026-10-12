// CLOSE MONITORING (v8) — accounts an analyst pinned, plus accounts the detectors suggest watching (early warning,
// uncorroborated model evidence, similarity to a stored mule signature). Each entry shows the live status and why,
// how long it has had it, the 72 h activity the detectors measure, and what would move it to "flagged".
// Source: GET /api/watchlist; refreshed on pushed events only (watchlist / status changes, postings that touch a
// watched account, resets). Watching never changes a status or a payment tier.
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { LedgerTx, WatchEntry, Watchlist } from "../api/types";
import { useConsoleEvents } from "./Shell";
import { formatPaiseShort, formatTime, handle } from "../lib/format";
import { useDebounced, useLoad, useNow } from "../lib/hooks";
import { ACCOUNT_STATUS_LABEL } from "../lib/status";

const SOURCE_LABEL: Record<string, string> = {
  pinned: "Pinned", early_warning: "Early warning", model_only: "Model only", pattern_memory: "Pattern match",
};
const FAM: Record<string, string> = {
  rules: "rules", random_forest: "RF", gnn: "GNN", drift: "drift", early_warning: "early warning", pattern_memory: "pattern memory",
};

function since(iso: string | null, now: number): string {
  if (!iso) return "";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  const rel = s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.floor(s / 60)}m` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `since ${formatTime(iso).slice(0, 5)} · ${rel}`;
}

export function useWatchlist() {
  const w = useLoad<Watchlist>(api.watchlist);
  const refresh = useDebounced(() => w.reload(), 1200);
  const ids = useRef(new Set<string>());
  ids.current = new Set((w.data?.entries ?? []).map((e) => e.account_id));
  useConsoleEvents((e) => {
    if (["watchlist.updated", "intel.account_status", "demo.reset", "attack.run_updated", "taint.updated", "intent.updated"].includes(e.type)) refresh();
    else if (e.type === "ledger.posted") {
      const tx = e.data as LedgerTx;
      if (tx && (ids.current.has(tx.sender_id) || ids.current.has(tx.recipient_id))) refresh();
    }
  });
  return w;
}

/** Whether one account is pinned (and its note), following `watchlist.updated` pushes. */
export function useWatched(accountId: string) {
  const w = useLoad<Watchlist>(api.watchlist, [accountId]);
  const refresh = useDebounced(() => w.reload(), 300);
  useConsoleEvents((e) => { if (e.type === "watchlist.updated" || e.type === "demo.reset") refresh(); });
  const entry = (w.data?.entries ?? []).find((x) => x.account_id === accountId && x.pinned) ?? null;
  return { pinned: !!entry, entry, reload: w.reload, available: !w.unavailable };
}

/** Pin / unpin toggle for one account (Account page, network drawer, watchlist rows). */
export function WatchButton({ accountId, pinned, onChange, size = "sm", askNote = false }: {
  accountId: string; pinned: boolean; onChange?: (on: boolean) => void; size?: "xs" | "sm"; askNote?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toggle = async () => {
    setBusy(true); setErr(null);
    try {
      if (pinned) { await api.unwatch(accountId); onChange?.(false); }
      else {
        const note = askNote ? window.prompt("Why are you watching this account? (optional note)") ?? undefined : undefined;
        await api.watch(accountId, note || undefined); onChange?.(true);
      }
    } catch (e) { setErr(e instanceof ApiError ? e.message : String(e)); }
    finally { setBusy(false); }
  };
  return (
    <button className={`btn ${size} ${pinned ? "on" : ""}`} onClick={(e) => { e.stopPropagation(); toggle(); }} disabled={busy}
            title={err ?? (pinned ? "Remove from close monitoring" : "Add to close monitoring (watchlist)")}>
      <svg viewBox="0 0 24 24" width="13" height="13" fill={pinned ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round" style={{ marginRight: 5, verticalAlign: -2 }}>
        <path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z" />
      </svg>
      {pinned ? "Watching" : "Watch"}
    </button>
  );
}

function Entry({ e, now, onPin }: { e: WatchEntry; now: number; onPin: () => void }) {
  const nav = useNavigate();
  const a = e.activity;
  return (
    <div className="watch-row" onClick={() => nav(`/investigations/account/${encodeURIComponent(e.account_id)}`)} role="link" tabIndex={0}>
      <div className="watch-top">
        <span className="cell-2l grow">
          <b>{e.label}</b>
          <small>{handle(e.account_id)}{e.families.length ? ` · ${e.families.length} famil${e.families.length === 1 ? "y" : "ies"}: ${e.families.map((f) => FAM[f] ?? f).join(", ")}` : " · no detector family flags it"}</small>
        </span>
        <span className="watch-st">
          <span className={`pill as-${e.status}`}>{ACCOUNT_STATUS_LABEL[e.status]}</span>
          <small>{since(e.status_since, now)}</small>
        </span>
        <WatchButton accountId={e.account_id} pinned={e.pinned} size="xs" onChange={onPin} />
      </div>
      {a && (
        <div className="watch-act">
          <span title="Money received in the detection window">In <b>{formatPaiseShort(a.in_paise)}</b></span>
          <span title="Money sent in the detection window">Out <b>{formatPaiseShort(a.out_paise)}</b></span>
          <span title="Share of received value forwarded within 60 minutes (pass-through speed)">Forwards <b>{Math.round(a.forwarded_fraction * 100)}%</b></span>
          <span title="Distinct counterparties in the window, and how many are new">Counterparties <b>{a.counterparties}</b>{a.counterparties ? ` (${Math.round(a.new_counterparty_ratio * 100)}% new)` : ""}</span>
          <span className="dim">{a.window}</span>
        </div>
      )}
      <div className="watch-next"><span className="lbl">Next</span>{e.next_step}</div>
      <div className="row tight wrap">
        {e.sources.map((s) => <span key={s} className={`tag ${s === "pinned" ? "pin" : ""}`}>{SOURCE_LABEL[s] ?? s}</span>)}
        {e.model_risk != null && <span className="tag mono" title="Strongest calibrated model evidence (corroborating only) vs the live threshold">model {e.model_risk.toFixed(2)}{e.model_threshold != null ? ` / ${e.model_threshold.toFixed(2)}` : ""}</span>}
        {e.network_risk > 0 && <span className="tag mono" title="RingWatch network score (authorisation path)">network {e.network_risk.toFixed(2)}</span>}
        {e.pattern && <span className="tag" title="Structural similarity to a stored signature — not attribution">{e.pattern.name} {Math.round(e.pattern.similarity * 100)}%</span>}
        {e.note && <span className="tag note" title="Analyst note">“{e.note}”</span>}
      </div>
    </div>
  );
}

/** The close-monitoring list (Operations center). `limit` shows only the first N entries. */
export function WatchlistCard({ limit, title = "Close monitoring" }: { limit?: number; title?: string }) {
  const w = useWatchlist();
  const now = useNow(10000);
  const [tab, setTab] = useState<"all" | "pinned" | "suggested">("all");
  const entries = useMemo(() => (w.data?.entries ?? []).filter((e) => tab === "all" || (tab === "pinned" ? e.pinned : !e.pinned)), [w.data, tab]);
  const shown = limit ? entries.slice(0, limit) : entries;
  return (
    <div className="kcard watch-card">
      <div className="kcard-h">
        <span className="ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></svg></span>
        <span>{title}</span>
        <span className="act">
          <div className="seg">
            <button className={tab === "all" ? "on" : ""} onClick={() => setTab("all")}>All · {w.data?.entries.length ?? 0}</button>
            <button className={tab === "pinned" ? "on" : ""} onClick={() => setTab("pinned")}>Pinned · {w.data?.pinned ?? 0}</button>
            <button className={tab === "suggested" ? "on" : ""} onClick={() => setTab("suggested")}>Suggested · {w.data?.suggested ?? 0}</button>
          </div>
        </span>
      </div>
      <div className="ksub">Accounts one step before "flagged": what they are doing now and what would tip them over. Pin any account from its page or the network.</div>
      {!w.data ? <div className="ksub">{w.unavailable ? "Close monitoring is not available on this server." : w.error ? w.error.message : "Loading…"}</div>
        : shown.length === 0 ? <div className="empty">{tab === "pinned" ? "No account pinned yet. Open an account and press Watch." : "Nothing to watch right now: no early warning, no uncorroborated model evidence, no pattern match."}</div>
        : <div className="watch-list">{shown.map((e) => <Entry key={e.account_id} e={e} now={now} onPin={() => w.reload()} />)}</div>}
    </div>
  );
}
