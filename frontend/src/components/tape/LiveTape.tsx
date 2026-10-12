// LIVE TRANSACTION TAPE — every posting as it lands, newest first, with the live status of both parties.
// Virtualised (only the visible rows are rendered), ≤ 300 rows in memory. Loads once, then on each pushed
// `ledger.posted` it fetches only the postings after the newest one it has (event-driven, throttled — no polling).
// Pause on hover ("N new" pill). Click / Enter on a row opens the connections drawer and highlights the posting on
// the map and in the 3D network.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { RAILS, RAIL_LABEL, v10, type Rail, type TapeRow } from "../../api/v10";
import { formatINR, formatTime } from "../../lib/format";
import { useThrottled } from "../../lib/live";
import { selectionAccounts, useSelection } from "../../lib/selection";
import { ACCOUNT_STATUS_LABEL } from "../../lib/status";
import { useConsoleEvents } from "../Shell";

const ROW_H = 60;
const MAX_ROWS = 300;
const RISKY = new Set(["flagged", "held", "confirmed_fraud", "early_warning"]);

export function RailBadge({ rail }: { rail: Rail | string }) {
  return <span className={`rail rail-${rail}`}>{RAIL_LABEL[rail as Rail] ?? rail.toUpperCase()}</span>;
}

export function LiveTape({ height = 470, onOpen }: { height?: number; onOpen: (row: TapeRow) => void }) {
  const { channel, setChannel, tapeOnly, setTapeOnly, selected, select, incident } = useSelection();
  const [rows, setRows] = useState<TapeRow[]>([]);
  const [pending, setPending] = useState<TapeRow[]>([]);
  const [paused, setPaused] = useState(false);
  const [q, setQ] = useState("");
  const [qDeb, setQDeb] = useState("");
  const [scroll, setScroll] = useState(0);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const box = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const scopeAccounts = useMemo(() => incident ? incident.entities
    : selected && (selected.kind === "account" || selected.kind === "cluster" || selected.kind === "incident") ? selectionAccounts(selected) : [],
  [incident, selected]);
  const cityFilter = selected?.kind === "city" ? selected.id : null;
  const filters = useMemo(() => ({ channel, only: tapeOnly, q: qDeb || undefined, accounts: scopeAccounts.length ? scopeAccounts : undefined }),
    [channel, tapeOnly, qDeb, scopeAccounts]);

  useEffect(() => { const id = window.setTimeout(() => setQDeb(q.trim()), 300); return () => window.clearTimeout(id); }, [q]);
  const load = useCallback(() => {
    v10.tape({ limit: 150, ...filters }).then((d) => { setRows(d.rows); setPending([]); }).catch(() => {});
  }, [filters]);
  useEffect(() => { load(); }, [load]);
  const reload = useThrottled(load, 3000);
  const newestRef = useRef<string | undefined>(undefined);
  newestRef.current = (pending[0] ?? rows[0])?.tx_id;
  const fetchNew = useThrottled(() => {
    const since = newestRef.current;
    if (!since) { load(); return; }
    v10.tape({ limit: 60, since_id: since, ...filters }).then((d) => {
      if (!d.rows.length) return;
      const ids = new Set(d.rows.map((r) => r.tx_id));
      setFresh(ids);
      window.setTimeout(() => setFresh(new Set()), 1400);
      if (pausedRef.current) setPending((p) => [...d.rows, ...p].slice(0, MAX_ROWS));
      else setRows((r) => [...d.rows, ...r.filter((x) => !ids.has(x.tx_id))].slice(0, MAX_ROWS));
    }).catch(() => {});
  }, 900);
  useConsoleEvents((e) => {
    if (e.type === "ledger.posted") fetchNew();
    else if (e.type === "intel.account_status" || e.type === "demo.reset" || e.type === "taint.updated") reload();
  });
  useEffect(() => {
    if (!paused && pending.length) {
      setRows((r) => { const ids = new Set(pending.map((x) => x.tx_id)); return [...pending, ...r.filter((x) => !ids.has(x.tx_id))].slice(0, MAX_ROWS); });
      setPending([]);
    }
  }, [paused, pending]);

  const shown = cityFilter ? rows.filter((r) => r.geo.city === cityFilter || r.geo.peer_city === cityFilter) : rows;
  const listH = height - 96;
  const first = Math.max(0, Math.floor(scroll / ROW_H) - 4);
  const last = Math.min(shown.length, first + Math.ceil(listH / ROW_H) + 8);
  const open = (r: TapeRow) => {
    select({ kind: "tx", id: r.tx_id, accounts: [r.sender_id, r.recipient_id], lat: r.geo.lat, lng: r.geo.lng,
             peer: { lat: r.geo.peer_lat, lng: r.geo.peer_lng }, label: r.geo.label });
    onOpen(r);
  };

  return (
    <div className="kcard tape-card" style={{ height }}>
      <div className="kcard-h"><span>Live transaction tape</span>
        <span className="act">{pending.length > 0 && <button className="pill-new" onClick={() => setPaused(false)}>{pending.length} new</button>}
          {paused && <span className="chip mute">paused</span>}</span></div>
      <div className="tape-filters">
        <div className="seg" role="group" aria-label="Filter by risk">
          {(["all", "suspicious", "fraud"] as const).map((o) => <button key={o} className={tapeOnly === o ? "on" : ""} onClick={() => setTapeOnly(o)}>{o === "all" ? "All" : o === "suspicious" ? "Suspicious" : "Fraud"}</button>)}
        </div>
        <select className="input sm" value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="Filter by rail">
          <option value="all">All rails</option>
          {RAILS.map((r) => <option key={r} value={r}>{RAIL_LABEL[r]}</option>)}
        </select>
        <input className="input sm grow" placeholder="Search id / name" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search the tape" />
      </div>
      {(cityFilter || scopeAccounts.length > 0) && (
        <div className="tape-scope">{incident ? <>Incident mode: <b>{incident.title}</b></> : cityFilter ? <>Filtered to <b>{cityFilter}</b></> : <>Filtered to <b>{scopeAccounts.length}</b> selected account{scopeAccounts.length > 1 ? "s" : ""}</>}
          {!incident && <button className="link" onClick={() => select(null)}>clear</button>}</div>
      )}
      <div className="tape-list" ref={box} style={{ height: listH }} onScroll={(e) => setScroll(e.currentTarget.scrollTop)}
           onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)} role="list" aria-label="Live postings, newest first">
        {shown.length === 0 && <div className="empty">No posting matches these filters yet.</div>}
        <div style={{ height: shown.length * ROW_H, position: "relative" }}>
          {shown.slice(first, last).map((r, i) => {
            const idx = first + i;
            const sel = selected?.kind === "tx" && selected.id === r.tx_id;
            const st = RISKY.has(r.recipient_status) ? r.recipient_status : RISKY.has(r.sender_status) ? r.sender_status : null;
            return (
              <div key={r.tx_id} role="listitem" tabIndex={0} className={`tape-row risk-${r.risk} ${sel ? "sel" : ""} ${fresh.has(r.tx_id) ? "fresh" : ""}`}
                   style={{ top: idx * ROW_H, height: ROW_H }} onClick={() => open(r)}
                   onKeyDown={(e) => { if (e.key === "Enter") open(r); }}
                   title={`${r.tx_id} · ${r.geo.label}`}>
                <div className="tr-l">
                  <span className="tr-time mono">{formatTime(r.ts).slice(0, 8)}</span>
                  <span className="tr-parties"><b>{r.sender_name}</b> → <b>{r.recipient_name}</b></span>
                  <span className="tr-meta"><RailBadge rail={r.rail} />{r.geo.city && <span className="dim">{r.geo.city}{r.geo.peer_city && r.geo.peer_city !== r.geo.city ? ` → ${r.geo.peer_city}` : ""}</span>}
                    {r.origin === "scenario" && <span className="sim">test injection</span>}</span>
                </div>
                <div className="tr-r">
                  <span className="mono tr-amt">{formatINR(r.amount_paise)}</span>
                  {st ? <span className={`pill as-${st}`}>{ACCOUNT_STATUS_LABEL[st as keyof typeof ACCOUNT_STATUS_LABEL]}</span>
                    : r.tier != null && r.tier > 0 ? <span className="pill nodot">T{r.tier}</span> : <span className="dim xs">normal</span>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <div className="tape-foot">Red bar = fraud-linked (an account flagged / held / confirmed / in a ring), amber = early warning. Hover pauses; click for connections.</div>
    </div>
  );
}
