// CONNECTIONS DRAWER — for one posting: who funded the sender (upstream), where the money went next (downstream),
// shared devices, ring membership and how the parties are linked. Read-only; buttons only navigate / select.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { v10, type AccountCard, type Connections, type Hop } from "../../api/v10";
import { formatINR, formatTime, handle } from "../../lib/format";
import { ACCOUNT_STATUS_LABEL, ROLE_LABEL } from "../../lib/status";
import { RailBadge } from "./LiveTape";

const LINK_LABEL: Record<string, { t: string; d: string }> = {
  shared_device: { t: "Shared device", d: "One of the parties shares a phone with another account" },
  fan_in: { t: "Fan-in", d: "The recipient receives from many distinct senders (risk policy fan-in rule)" },
  fan_out: { t: "Fan-out", d: "The sender pays many distinct recipients (risk policy fan-out rule)" },
  ring: { t: "Same ring", d: "Both parties sit in one detected cluster of risky accounts" },
  same_payee: { t: "Same payee", d: "Both parties paid the same third account in the live window" },
};

function Card({ a, label }: { a: AccountCard; label: string }) {
  return (
    <div className="cd-card">
      <div className="cd-k">{label}</div>
      <Link to={`/investigations/account/${encodeURIComponent(a.id)}`} className="cd-name">{a.name}</Link>
      <div className="mono xs dim">{a.id}</div>
      <div className="row tight wrap" style={{ marginTop: 4 }}>
        <span className={`pill as-${a.status}`}>{ACCOUNT_STATUS_LABEL[a.status] ?? a.status}</span>
        {a.role && <span className="tag">{ROLE_LABEL[a.role] ?? a.role}</span>}
        {a.home_city && <span className="tag" title="Simulated home city">{a.home_city}</span>}
      </div>
      {a.reason && <div className="xs" style={{ marginTop: 4 }}>{a.reason}</div>}
    </div>
  );
}

function Hops({ hops, dir }: { hops: Hop[]; dir: "up" | "down" }) {
  if (!hops.length) return <div className="xs dim">{dir === "up" ? "No earlier inflow in view." : "The money has not moved on yet."}</div>;
  const byHop = [1, 2, 3].map((h) => hops.filter((x) => x.hops === h)).filter((l) => l.length);
  return (
    <div className="cd-hops">
      {byHop.map((list, i) => (
        <div key={i} className="cd-hop">
          <div className="cd-hop-k">{i + 1} hop{i ? "s" : ""} {dir === "up" ? "before" : "after"}</div>
          {list.slice(0, 6).map((h) => (
            <div key={`${h.tx_id}-${h.account}`} className="cd-hop-row">
              <span className={`dot as-${h.status}`} />
              <Link to={`/investigations/account/${encodeURIComponent(h.account)}`}>{h.account.startsWith("ext:") ? h.name : handle(h.account)}</Link>
              <span className="mono xs">{formatINR(h.amount_paise)}</span>
              <span className="mono xs dim">{formatTime(h.ts).slice(0, 5)}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function ConnectionsDrawer({ txId, onClose, onShowMap, onShowNetwork, onAsk }: {
  txId: string; onClose: () => void; onShowMap: (c: Connections) => void; onShowNetwork: (ids: string[]) => void;
  onAsk: (txId: string) => void;
}) {
  const [c, setC] = useState<Connections | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    setC(null); setErr(null);
    v10.connections(txId).then(setC).catch((e) => setErr(String(e)));
  }, [txId]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const tx = c?.tx;
  return (
    <aside className="cd-drawer" role="dialog" aria-label={`Connections of ${txId}`}>
      <div className="cd-head">
        <div>
          <div className="cd-k">Posting {txId}</div>
          {tx ? <div className="cd-title">{formatINR(tx.amount_paise)} <RailBadge rail={tx.rail} /> <span className="xs dim">{formatTime(tx.ts)}</span></div> : <div className="cd-title">Loading…</div>}
          {tx && <div className="xs dim">{tx.geo.label}{tx.geo.city ? ` · ${tx.geo.city}` : ""}{tx.geo.peer_city && tx.geo.peer_city !== tx.geo.city ? ` → ${tx.geo.peer_city}` : ""}</div>}
        </div>
        <button className="btn xs" onClick={onClose} aria-label="Close">✕</button>
      </div>
      {err && <div className="empty">Could not load the connections.</div>}
      {c && (
        <div className="cd-body">
          <div className="cd-pair"><Card a={c.sender} label="From" /><Card a={c.recipient} label="To" /></div>
          {c.linked_by.length > 0 && (
            <div className="row tight wrap">
              <span className="cd-k" style={{ marginRight: 4 }}>Linked by</span>
              {c.linked_by.map((l) => <span key={l} className="tag warn" title={LINK_LABEL[l]?.d}>{LINK_LABEL[l]?.t ?? l}</span>)}
            </div>
          )}
          <div className="cd-sect"><div className="sect-t">Upstream — who funded {handle(c.sender.id)}</div><Hops hops={c.upstream} dir="up" /></div>
          <div className="cd-sect"><div className="sect-t">Downstream — where {handle(c.recipient.id)} sent it next</div><Hops hops={c.downstream} dir="down" /></div>
          {c.shared_device.length > 0 && (
            <div className="cd-sect"><div className="sect-t">Shares a device with</div>
              <div className="row tight wrap">{c.shared_device.map((a) => <Link key={a.id} className={`tag as-${a.status}`} to={`/investigations/account/${encodeURIComponent(a.id)}`}>{handle(a.id)}</Link>)}</div></div>
          )}
          {c.same_ring && (
            <div className="cd-sect"><div className="sect-t">In a detected {c.same_ring.kind} of {c.same_ring.size} accounts</div>
              <div className="xs">{c.same_ring.flagged} flagged · {formatINR(c.same_ring.value_paise)} moved between them · {c.same_ring.rules.slice(0, 4).join(", ")}</div></div>
          )}
          <div className="cd-actions">
            <button className="btn sm" onClick={() => onShowMap(c)}>Show on map</button>
            <button className="btn sm" onClick={() => onShowNetwork([c.sender.id, c.recipient.id, ...c.downstream.map((d) => d.account)].filter((a) => !a.startsWith("ext:")))}>Show in network</button>
            <Link className="btn sm" to={`/investigations/account/${encodeURIComponent(c.recipient.id)}`}>Open recipient</Link>
            <button className="btn sm primary" onClick={() => onAsk(txId)}>Ask Copilot about this</button>
          </div>
        </div>
      )}
    </aside>
  );
}
