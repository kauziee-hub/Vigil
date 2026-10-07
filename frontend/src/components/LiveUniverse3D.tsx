// LIVE TRANSACTION UNIVERSE — every account as a node, every live posting as an edge + travelling particle.
// Data: GET /api/live/universe on mount (and on demo.reset); then WebSocket deltas over the console bus:
//   ledger.posted (edge + traveller) · intel.tx_scored (statuses) · intel.account_status (recolour / rescale).
// The canvas is driven imperatively (UniverseEngine): WS events never re-render React. Only the 1 Hz footer and the
// hover tooltip own React state, and each lives in its own tiny component.
// If /api/live/universe is not served yet, the universe is built honestly from /api/accounts (+ RingWatch and model
// scores for the RISK / MODEL modes); statuses are then unavailable and the banner says so. Nothing is fabricated.
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { AccountStatus, AccountStatusChange, LedgerTx, LiveUniverse, TxScored, UniverseAccount } from "../api/types";
import { formatINR, handle } from "../lib/format";
import { ACCOUNT_STATUS_HEX, ACCOUNT_STATUS_LABEL, ROLE_LABEL } from "../lib/status";
import { UniverseEngine, type UEdge, type UStats, type UniverseMode } from "../lib/universe3d";
import { useConsoleEvents } from "./Shell";

export type { UniverseMode, UStats } from "../lib/universe3d";
export interface UniverseInfo {
  source: "live" | "fallback" | "error";
  version: string | null;
  windowMinutes: number;
  accounts: Map<string, UniverseAccount>;
  totals: Record<string, number>;
}

type Sub<T> = { set: ((v: T) => void) | null };
function useSub<T>() { return useRef<Sub<T>>({ set: null }).current; }

const Footer = memo(function Footer({ sub, info }: { sub: Sub<UStats>; info: { windowMinutes: number; source: string } }) {
  const [s, setS] = useState<UStats | null>(null);
  useEffect(() => { sub.set = setS; return () => { sub.set = null; }; }, [sub]);
  if (!s) return null;
  return (
    <div className="uni-foot">
      {s.liveEdges} postings in the last {info.windowMinutes} min · {s.pairs} live edges · {s.active} accounts active · {s.nodes} nodes
      {(s.byStatus.flagged || s.byStatus.early_warning || s.byStatus.held || s.byStatus.confirmed_fraud)
        ? <> · <span style={{ color: ACCOUNT_STATUS_HEX.early_warning }}>{s.byStatus.early_warning ?? 0} early warning</span>
            {" · "}<span style={{ color: ACCOUNT_STATUS_HEX.flagged }}>{s.byStatus.flagged ?? 0} flagged</span>
            {s.byStatus.held ? <> · <span style={{ color: ACCOUNT_STATUS_HEX.held }}>{s.byStatus.held} held</span></> : null}</>
        : null}
    </div>
  );
});

const Tip = memo(function Tip({ sub }: { sub: Sub<{ x: number; y: number; text: string } | null> }) {
  const [t, setT] = useState<{ x: number; y: number; text: string } | null>(null);
  useEffect(() => { sub.set = setT; return () => { sub.set = null; }; }, [sub]);
  return t ? <div className="uni-tip" style={{ left: t.x, top: t.y }}>{t.text}</div> : null;
});

function groupOf(a: { id: string; kind: string; is_demo_customer: number; persona: string | null }): UniverseAccount["group"] {
  if (a.kind === "external" || a.id.startsWith("ext:")) return "external";
  if (a.is_demo_customer) return "demo";
  if (a.persona === "merchant") return "merchant";
  return "customer";
}

/** Honest fallback while /api/live/universe is not served: real accounts, real scores, no statuses, no history. */
async function fallbackUniverse(): Promise<LiveUniverse> {
  const [accts, ring, scores] = await Promise.all([
    api.accounts(),
    api.ringwatch().catch(() => []),
    api.intelScores().catch(() => null),
  ]);
  const risk = new Map(ring.map((r) => [r.account_id, r]));
  return {
    version: "fallback", as_of: new Date().toISOString(), window_minutes: 10, edges: [], history_edges: [], totals: {},
    accounts: accts.map((a) => {
      const s = scores?.scores[a.id];
      const model = s ? Math.max(s.rf ?? -1, s.gnn ?? -1) : -1;
      const r = risk.get(a.id);
      return {
        id: a.id, label: a.display_name || a.id, kind: a.kind === "external" ? "external" : "customer", group: groupOf(a),
        status: (a.kind === "external" ? "external" : "idle") as AccountStatus, risk: r?.score ?? 0,
        model_risk: model >= 0 ? model : null, role: r?.role ?? s?.role ?? null, opened_at: "", balance_paise: a.balance_paise, last_active: null,
      };
    }),
  };
}

export interface LiveUniverse3DProps {
  mode?: UniverseMode;
  groundTruth?: boolean;
  autoRotate?: boolean;
  size?: "hero" | "full" | "compact";
  selected?: string | null;
  onSelect?: (id: string | null, acct: UniverseAccount | null) => void;
  taint?: Map<string, number> | null;
  focus?: { ids: string[]; seq: number } | null;
  windowMinutes?: number;
  onInfo?: (info: UniverseInfo) => void;
  /** Called for every live posting (after the canvas got it) — for feeds that piggy-back on the same stream. */
  onPosting?: (tx: LedgerTx) => void;
  /** Engine statistics, once per second (status counts, active accounts, live edges). */
  onStats?: (s: UStats) => void;
}

export function LiveUniverse3D(p: LiveUniverse3DProps) {
  const host = useRef<HTMLDivElement>(null);
  const labels = useRef<HTMLDivElement>(null);
  const eng = useRef<UniverseEngine | null>(null);
  const accounts = useRef(new Map<string, UniverseAccount>());
  const seen = useRef(new Set<string>());
  const props = useRef(p);
  props.current = p;
  const statsSub = useSub<UStats>();
  const tipSub = useSub<{ x: number; y: number; text: string } | null>();
  const [info, setInfo] = useState<UniverseInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const reloadTimer = useRef<number | undefined>(undefined);

  const load = useCallback(async () => {
    const e = eng.current;
    if (!e) return;
    let u: LiveUniverse;
    let source: UniverseInfo["source"] = "live";
    try {
      u = await api.universe({ window_minutes: props.current.windowMinutes });
    } catch (ex) {
      if (ex instanceof ApiError && ex.status === 404) {
        try { u = await fallbackUniverse(); source = "fallback"; }
        catch (ex2) { setErr(ex2 instanceof ApiError ? ex2.message : String(ex2)); return; }
      } else { setErr(ex instanceof ApiError ? ex.message : String(ex)); return; }
    }
    if (!eng.current) return;
    setErr(null);
    e.clear();
    e.setClock(u.as_of);
    e.setWindow(u.window_minutes || 10);
    accounts.current = new Map(u.accounts.map((a) => [a.id, a]));
    seen.current = new Set(u.edges.map((x) => x.id));
    u.accounts.forEach((a) => e.upsertNode(a));
    e.setHistory(u.history_edges ?? []);
    u.edges.forEach((x) => e.addEdge(x, false));
    if (props.current.taint) e.setTaint(props.current.taint);
    e.setSelected(props.current.selected ?? null);
    const i: UniverseInfo = { source, version: u.version, windowMinutes: u.window_minutes || 10, accounts: accounts.current, totals: u.totals ?? {} };
    setInfo(i);
    props.current.onInfo?.(i);
    statsSub.set?.(e.stats());
  }, [statsSub]);

  // engine lifetime
  useEffect(() => {
    const e = new UniverseEngine(host.current!, labels.current, { autoRotate: props.current.autoRotate });
    eng.current = e;
    e.on("stats", (s) => { statsSub.set?.(s); props.current.onStats?.(s); });
    e.on("click", (id) => props.current.onSelect?.(id, accounts.current.get(id) ?? null));
    e.on("hover", (h) => {
      if (!h) { tipSub.set?.(null); return; }
      const a = accounts.current.get(h.id);
      const st = a?.status ?? "normal";
      const text = `${a?.label ?? handle(h.id)} · ${handle(h.id)}\n${ACCOUNT_STATUS_LABEL[st]}` +
        `${a?.role ? ` · ${ROLE_LABEL[a.role] ?? a.role}` : ""}${a ? ` · network ${a.risk.toFixed(2)}` : ""}` +
        `${a?.model_risk != null ? ` · model ${a.model_risk.toFixed(2)}` : ""}`;
      tipSub.set?.({ x: h.x, y: h.y, text });
    });
    load();
    return () => { window.clearTimeout(reloadTimer.current); e.dispose(); eng.current = null; };
  }, [load, statsSub, tipSub]);

  useEffect(() => { eng.current?.setMode(p.mode ?? "live"); }, [p.mode]);
  useEffect(() => { eng.current?.setGroundTruth(!!p.groundTruth); }, [p.groundTruth]);
  useEffect(() => { eng.current?.setAutoRotate(!!p.autoRotate); }, [p.autoRotate]);
  useEffect(() => { eng.current?.setSelected(p.selected ?? null); }, [p.selected]);
  useEffect(() => { if (p.taint) eng.current?.setTaint(p.taint); }, [p.taint]);
  useEffect(() => { if (p.focus && p.focus.ids.length) eng.current?.focus(p.focus.ids); }, [p.focus]);

  const scheduleReload = useCallback(() => {
    window.clearTimeout(reloadTimer.current);
    reloadTimer.current = window.setTimeout(() => { load(); }, 4000);
  }, [load]);

  useConsoleEvents((ev) => {
    const e = eng.current;
    if (!e) return;
    switch (ev.type) {
      case "ledger.posted": {
        const tx = ev.data as LedgerTx & { seed_attack?: string | null; channel?: string };
        if (!tx?.id || seen.current.has(tx.id)) { if (tx?.id) props.current.onPosting?.(tx); return; }
        seen.current.add(tx.id);
        for (const id of [tx.sender_id, tx.recipient_id]) {
          if (!e.has(id)) {
            const ext = id.startsWith("ext:");
            const a: UniverseAccount = { id, label: id, kind: ext ? "external" : "customer", group: ext ? "external" : "customer",
              status: ext ? "external" : "normal", risk: 0, model_risk: null, role: null, opened_at: "", balance_paise: 0, last_active: tx.ts };
            accounts.current.set(id, a);
            e.upsertNode(a, { pulse: true });
            if (info?.source === "live") scheduleReload();     // pick up the real record (group, status, opened_at)
          }
        }
        const edge: UEdge = { id: tx.id, source: tx.sender_id, target: tx.recipient_id, ts: tx.ts, amount_paise: tx.amount_paise,
                              origin: tx.source, scenario: tx.seed_attack ?? null };
        e.addEdge(edge, true);
        props.current.onPosting?.(tx);
        break;
      }
      case "intel.tx_scored": {
        const t = ev.data as TxScored;
        if (!t?.tx_id) return;
        const upd = (id: string, s: AccountStatus, r: number | null) => {
          const a = accounts.current.get(id);
          if (a) { a.status = s; if (r !== null) a.risk = r; }
          e.setStatus(id, s, { risk: r });
        };
        upd(t.sender_id, t.sender_status, t.sender_risk);
        upd(t.recipient_id, t.recipient_status, t.recipient_risk);
        if (!seen.current.has(t.tx_id) && e.has(t.sender_id) && e.has(t.recipient_id)) {
          seen.current.add(t.tx_id);
          e.addEdge({ id: t.tx_id, source: t.sender_id, target: t.recipient_id, ts: t.ts, amount_paise: t.amount_paise,
                      origin: t.origin, scenario: t.scenario }, true);
        }
        break;
      }
      case "intel.account_status": {
        const c = ev.data as AccountStatusChange;
        if (!c?.account_id) return;
        const a = accounts.current.get(c.account_id);
        if (a) { a.status = c.status; if (c.risk !== null) a.risk = c.risk; if (c.role !== undefined) a.role = c.role; }
        e.setStatus(c.account_id, c.status, { risk: c.risk, role: c.role });
        break;
      }
      case "demo.reset":
        load();
        break;
    }
  });

  const cls = p.size === "full" ? "uni full" : p.size === "compact" ? "uni compact" : "uni";
  return (
    <div className={cls}>
      <div ref={host} style={{ position: "absolute", inset: 0 }} />
      <div ref={labels} style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }} />
      <Tip sub={tipSub} />
      {info?.source === "fallback" && (
        <div className="uni-banner notice warn sm">
          <b>Live universe endpoint not served yet</b> (<span className="mono">/api/live/universe</span>). Nodes are the real accounts from
          <span className="mono"> /api/accounts</span>; edges are postings received since this page opened. Detection statuses are
          unavailable, so colours show activity only — RISK and MODEL modes use RingWatch and model scores.
        </div>
      )}
      {err && <div className="uni-empty"><div><b>Universe unavailable.</b><br />{err}</div></div>}
      {!info && !err && <div className="uni-empty"><span className="spinner lg" /></div>}
      <Footer sub={statsSub} info={{ windowMinutes: info?.windowMinutes ?? 10, source: info?.source ?? "" }} />
    </div>
  );
}

/** Status legend for the universe (LIVE mode) — the v3 account status scale. */
export function UniverseLegend({ mode = "live", groundTruth }: { mode?: UniverseMode; groundTruth?: boolean }) {
  const live: AccountStatus[] = ["normal", "idle", "new", "early_warning", "flagged", "held", "confirmed_fraud"];
  if (mode === "live") {
    return (
      <div className="uni-legend">
        {live.map((s) => <span key={s} style={{ color: ACCOUNT_STATUS_HEX[s] }}><i style={{ background: ACCOUNT_STATUS_HEX[s] }} /><span style={{ color: "#b9cfc3" }}>{ACCOUNT_STATUS_LABEL[s]}</span></span>)}
        {groundTruth && <span style={{ color: "#d65cff" }}><i style={{ background: "#d65cff" }} /><span style={{ color: "#b9cfc3" }}>Injected — simulator ground truth</span></span>}
      </div>
    );
  }
  const bands: [string, string][] = [["#2f7dff", "< 0.30"], ["#ffc34d", "0.30–0.50"], ["#ff9157", "0.50–0.75"], ["#ff3d63", "≥ 0.75"]];
  if (mode === "risk" || mode === "model") {
    return (
      <div className="uni-legend">
        <span style={{ color: "#96b1a2" }}>{mode === "risk" ? "RingWatch network score" : "Strongest model evidence (corroborating)"}</span>
        {bands.map(([c, l]) => <span key={l} style={{ color: c }}><i style={{ background: c }} /><span style={{ color: "#b9cfc3" }}>{l}</span></span>)}
        {mode === "model" && <span><i style={{ background: "#1c3a30" }} /><span style={{ color: "#b9cfc3" }}>not scored</span></span>}
      </div>
    );
  }
  return (
    <div className="uni-legend">
      {mode === "roles"
        ? <><span style={{ color: "#d6efe2" }}><i style={{ background: "#d6efe2" }} /><span style={{ color: "#b9cfc3" }}>Mule role assigned</span></span><span><i style={{ background: "#1c3a30" }} /><span style={{ color: "#b9cfc3" }}>no role</span></span></>
        : <><span style={{ color: "#ff1744" }}><i style={{ background: "#ff1744" }} /><span style={{ color: "#b9cfc3" }}>Value traced from a confirmed scam (LIBR) — size ∝ amount</span></span><span><i style={{ background: "#1c3a30" }} /><span style={{ color: "#b9cfc3" }}>untainted</span></span></>}
    </div>
  );
}

export function formatPostingLine(tx: { sender_id: string; recipient_id: string; amount_paise: number }) {
  return `${handle(tx.sender_id)} → ${handle(tx.recipient_id)} · ${formatINR(tx.amount_paise)}`;
}
