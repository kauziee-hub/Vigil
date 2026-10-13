// VIGILANCE — the fraud-operations agent of the console (v11; it was the "Copilot" in v10).
//   * VigilanceBar (top of the Overview): what is open right now, each alert CLASSIFIED ("High · Mule ring forming"),
//     who/where, ₹ at stake and the time left to respond.
//   * Toasts: when Vigilance raises or escalates an alert it says so, in one sentence with the numbers.
//   * VigilanceDock: ONE chat box. Vigilance posts its alerts there as cards and answers questions about anything on
//     screen. Opening an alert shows the case: the assessment (red flags, key facts, recommendation) and the bank
//     procedure — contain → investigate → report → recover & close — whose in-app steps open the right place in Vigil
//     and whose outside steps (freeze, STR, 1930) the analyst ticks. Steps also tick themselves when Vigil sees the
//     outcome (watched, hold decided, contact answered, scam confirmed, acknowledged).
// The provider and the dock are mounted by the Shell, so Vigilance is on every page and a case stays open while its
// procedure steps open the case page, the account page or Interventions (see lib/vigilance for the page bridge).
// Read-only: every button navigates, selects, or (watch) asks the analyst to confirm. Model text is rendered through
// SafeMarkdown (no raw HTML).
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import {
  streamMessage, v10, type CopilotStatus, type Incident, type IncidentBrief, type Procedure, type ProcedureStep,
  type Severity, type ToolCall, type UiAction,
} from "../../api/v10";
import { formatPaiseShort } from "../../lib/format";
import { SEV_ORDER, sortIncidents } from "../../lib/incidents";
import { useThrottled } from "../../lib/live";
import { SafeMarkdown, type EntityRef } from "../../lib/safeMarkdown";
import { useVigilance, VigilanceContext, type PageDeps, type Pending, type VigilanceCtx, type VigilanceOpen } from "../../lib/vigilance";
import { actionLabel, isAllowed, needsOverview, runAction, type ActionDeps } from "../../lib/vigilanceActions";
import { useConsoleEvents } from "../consoleBus";

export const SEV_LABEL: Record<Severity, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
const STATUS_LABEL: Record<string, string> = { open: "Open", acknowledged: "Acknowledged", dismissed: "Dismissed", resolved: "Resolved" };

function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  return s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.round(s / 60)} min` : s < 86400 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} d`;
}
const clockTime = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

function useNow(ms = 20000): number {
  const [n, setN] = useState(Date.now());
  useEffect(() => { const t = window.setInterval(() => setN(Date.now()), ms); return () => window.clearInterval(t); }, [ms]);
  return n;
}

function span(ms: number): string {
  const m = Math.max(1, Math.round(Math.abs(ms) / 60000));
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return h < 48 ? `${h} h${m % 60 ? ` ${m % 60} min` : ""}` : `${Math.round(h / 24)} days`;
}

/** Time left against the respond-within target (from when the alert was raised). */
export function sla(inc: Pick<Incident, "status" | "created_ts" | "respond_minutes">, now: number) {
  if (inc.status !== "open") return { text: STATUS_LABEL[inc.status] ?? inc.status, overdue: false, frac: 1, closed: true };
  const total = Math.max(1, inc.respond_minutes) * 60000;
  const left = new Date(inc.created_ts).getTime() + total - now;
  return left >= 0
    ? { text: `${span(left)} left`, overdue: false, frac: Math.min(1, Math.max(0, 1 - left / total)), closed: false }
    : { text: `overdue by ${span(left)}`, overdue: true, frac: 1, closed: false };
}

export function VgMark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="vg-mark">
      <path d="M12 2.5 4 5.6v6.1c0 4.7 3.3 8.6 8 9.8 4.7-1.2 8-5.1 8-9.8V5.6L12 2.5Z" fill="currentColor" opacity="0.16" />
      <path d="M12 2.5 4 5.6v6.1c0 4.7 3.3 8.6 8 9.8 4.7-1.2 8-5.1 8-9.8V5.6L12 2.5Z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M7.6 12s1.7-2.9 4.4-2.9 4.4 2.9 4.4 2.9-1.7 2.9-4.4 2.9S7.6 12 7.6 12Z" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="12" cy="12" r="1.35" fill="currentColor" />
    </svg>
  );
}

// ── provider (mounted once by the Shell) ─────────────────────────────────
function useIncidentList() {
  const [list, setList] = useState<Incident[]>([]);
  const [max, setMax] = useState(5);
  const [loaded, setLoaded] = useState(false);
  const load = useCallback(() => {
    v10.incidents("open").then((d) => { setList(sortIncidents(d.incidents)); setMax(d.max_visible); setLoaded(true); }).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);
  const t = useThrottled(load, 800);
  useConsoleEvents((e) => { if (e.type === "copilot.incident" || e.type === "demo.reset") t(); });
  return { list, max, loaded, reload: load };
}

function useStatus() {
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const load = useCallback(() => { v10.copilotStatus().then(setStatus).catch(() => {}); }, []);
  useEffect(() => { load(); }, [load]);
  useConsoleEvents((e) => { if (e.type === "demo.reset") load(); });
  return { status, reload: load };
}

export function VigilanceProvider({ children }: { children: ReactNode }) {
  const nav = useNavigate();
  const inc = useIncidentList();
  const st = useStatus();
  const [vigilance, setVigilance] = useState({ open: false, incidentId: null as string | null, prompt: null as string | null,
                                               about: null as string | null, seq: 0 });
  const [page, setPage] = useState<PageDeps | null>(null);
  const pending = useRef<Pending | null>(null);
  const openVigilance = useCallback((o: VigilanceOpen) =>
    setVigilance((c) => ({ open: true, incidentId: o.incidentId ?? null, prompt: o.prompt ?? null, about: o.about ?? null, seq: c.seq + 1 })), []);
  const closeVigilance = useCallback(() => setVigilance((c) => ({ ...c, open: false })), []);
  const registerPage = useCallback((d: PageDeps | null) => setPage(() => d), []);
  const carry = useCallback((p: Pending) => { pending.current = p; nav("/"); }, [nav]);
  const takePending = useCallback(() => { const p = pending.current; pending.current = null; return p; }, []);
  const value = useMemo<VigilanceCtx>(() => ({
    vigilance, openVigilance, closeVigilance, incidents: inc.list, max: inc.max, loaded: inc.loaded, reloadIncidents: inc.reload,
    status: st.status, reloadStatus: st.reload, page, registerPage, carry, takePending,
  }), [vigilance, openVigilance, closeVigilance, inc.list, inc.max, inc.loaded, inc.reload, st.status, st.reload, page, registerPage, carry, takePending]);
  return <VigilanceContext.Provider value={value}>{children}</VigilanceContext.Provider>;
}

/** The open alerts (severity first), loaded once for the whole app. */
export function useIncidents() {
  const v = useVigilance();
  return { list: v.incidents, max: v.max, loaded: v.loaded, reload: v.reloadIncidents };
}

// ── top bar ───────────────────────────────────────────────────────────────
export function VigilanceBar() {
  const { openVigilance, incidents, max, status } = useVigilance();
  const now = useNow();
  const [more, setMore] = useState(false);
  const top = incidents[0];
  const visible = incidents.slice(0, max);
  const rest = incidents.slice(max);
  const ai = !!status?.llm_available;
  return (
    <section className={`vg-bar ${top ? `sev-${top.severity}` : "clear"}`} aria-label="Vigilance alerts">
      <div className="vg-bar-h">
        <button className="vg-brand" onClick={() => openVigilance({})} title="Open Vigilance">
          <VgMark size={24} />
          <span className="vg-brand-t">
            <b>Vigilance</b>
            <span className="vg-brand-s">{top ? `${incidents.length} open alert${incidents.length > 1 ? "s" : ""} · highest ${SEV_LABEL[top.severity]}` : "All clear · watching every payment"}</span>
          </span>
        </button>
        {incidents.length === 0
          ? <span className="vg-empty">Nothing needs a person right now. When something does, Vigilance raises it here, classified, with the bank's next steps.</span>
          : <span className="vg-bar-hint">Most urgent first · click an alert for its case and the bank's procedure</span>}
        <span className="spacer" />
        <span className={`vg-mode ${ai ? "ai" : ""}`} title={status?.note}>{ai ? `AI · ${status?.model_fast}` : "Live-data answers"}</span>
        <button className="btn sm primary vg-ask" onClick={() => openVigilance({})}>Ask Vigilance</button>
      </div>
      {incidents.length > 0 && <div className="vg-chips" role="list" aria-label="Open alerts">
        {visible.map((i) => <AlertChip key={i.id} inc={i} now={now} onOpen={() => openVigilance({ incidentId: i.id })} />)}
        {rest.length > 0 && (
          <span className="vg-more-wrap">
            <button className="vg-chip more" onClick={() => setMore((v) => !v)} aria-expanded={more}>+{rest.length} more</button>
            {more && (
              <div className="vg-pop" role="menu">
                {rest.map((i) => (
                  <button key={i.id} role="menuitem" className="vg-pop-row" onClick={() => { setMore(false); openVigilance({ incidentId: i.id }); }}>
                    <span className={`vg-pill sev-${i.severity}`}>{SEV_LABEL[i.severity]}</span><b>{i.classification}</b><span className="dim">{i.subject}</span>
                  </button>
                ))}
              </div>
            )}
          </span>
        )}
      </div>}
    </section>
  );
}

function AlertChip({ inc, now, onOpen }: { inc: Incident; now: number; onOpen: () => void }) {
  const s = sla(inc, now);
  const fresh = now - new Date(inc.created_ts).getTime() < 90_000;
  return (
    <button role="listitem" className={`vg-chip sev-${inc.severity} ${fresh ? "fresh" : ""}`} onClick={onOpen}
            title={`${inc.situation}\n${inc.typology} · respond within ${inc.respond_within}`}>
      <span className="vg-sev"><i />{SEV_LABEL[inc.severity]}</span>
      <span className="vg-cls">{inc.classification}</span>
      <span className="vg-sub">{inc.subject}</span>
      <span className="vg-val">{inc.value_paise ? formatPaiseShort(inc.value_paise) : ""}</span>
      <span className="vg-nxt">{inc.procedure?.next ? <><b>Next</b> {inc.procedure.next}</> : null}</span>
      <span className="vg-steps" title="Procedure steps done">{inc.procedure ? `${inc.procedure.done}/${inc.procedure.total} steps` : ""}</span>
      <span className={`vg-sla ${s.overdue ? "over" : ""}`}>{s.text}</span>
      <span className="vg-go" aria-hidden="true">›</span>
    </button>
  );
}

// ── toasts ────────────────────────────────────────────────────────────────
interface ToastItem { key: string; inc: Incident; kind: "new" | "escalated"; from?: Severity }

function Toasts({ items, onOpen, onClose }: { items: ToastItem[]; onOpen: (t: ToastItem) => void; onClose: (k: string) => void }) {
  return (
    <div className="vg-toasts" aria-live="polite">
      {items.map((t) => (
        <div key={t.key} className={`vg-toast sev-${t.inc.severity}`} role="status">
          <div className="vg-toast-h"><VgMark size={15} /><b>Vigilance</b>
            <span>{t.kind === "new" ? "raised an alert" : `escalated it from ${SEV_LABEL[t.from ?? "low"]}`}</span>
            <button className="vg-x" onClick={() => onClose(t.key)} aria-label="Dismiss notification">✕</button></div>
          <div className="vg-toast-t"><span className={`vg-pill sev-${t.inc.severity}`}>{SEV_LABEL[t.inc.severity]}</span>{t.inc.classification}</div>
          <div className="vg-toast-b">{t.inc.situation}</div>
          <div className="vg-toast-a"><button className="btn xs primary" onClick={() => onOpen(t)}>Open case</button>
            <span className="dim xs">Respond within {t.inc.respond_within}</span></div>
        </div>
      ))}
    </div>
  );
}

// ── dock ──────────────────────────────────────────────────────────────────
interface MsgItem {
  kind: "msg"; key: string; role: "user" | "assistant"; content: string; tools: ToolCall[]; streaming?: boolean;
  error?: string; llm?: boolean; about: string | null;
}
interface AlertItem { kind: "alert"; key: string; incidentId: string; note: "open" | "new" | "escalated"; from?: Severity; at: string }
type FeedItem = MsgItem | AlertItem;

const ASK_CASE = ["What should I do first?", "Trace the money", "Is this a false positive?", "Draft the STR grounds"];
const ASK_ANY = ["What needs my attention now?", "Which rings are active?", "Where is money leaving the bank?", "New accounts pipeline", "Situation summary"];

export function VigilanceDock() {
  const { vigilance, openVigilance, closeVigilance, incidents, loaded, status, reloadStatus: onStatus, page, carry } = useVigilance();
  const nav = useNavigate();
  // On the Overview its own handlers run the actions; elsewhere accounts open their page and map / network / tape
  // actions are carried to the Overview.
  const deps: Omit<ActionDeps, "confirmWatch"> = useMemo(() => page ? { ...page, navigate: nav } : {
    select: (sel) => { if (sel?.kind === "account") nav(`/investigations/account/${encodeURIComponent(sel.id)}`); },
    navigate: nav,
    openConnections: (tx) => carry({ action: { type: "open_connections", target: tx } }),
    focusNetwork: (ids) => carry({ action: { type: "show_in_network", target: ids.join(",") } }),
    setTapeOnly: (o) => carry({ action: { type: "filter_tape", target: o } }),
    cityPoint: () => null,
  }, [page, nav, carry]);
  const act = useCallback((a: UiAction, d: ActionDeps): boolean => {
    if (!page && isAllowed(a) && needsOverview(a)) { carry({ action: a }); return true; }
    return runAction(a, d);
  }, [page, carry]);
  const setIncident = useCallback((i: Incident) => { if (page) page.focusIncident(i); else carry({ focus: i }); }, [page, carry]);
  const [view, setView] = useState<"feed" | "case">("feed");
  const [caseId, setCaseId] = useState<string | null>(null);
  const [items, setItems] = useState<FeedItem[]>([]);
  const [about, setAbout] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [width, setWidth] = useState(470);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [, setKnownVer] = useState(0);
  const known = useRef(new Map<string, Incident>());
  const threads = useRef<{ general: string | null; byIncident: Map<string, string> }>({ general: null, byIncident: new Map() });
  const seeded = useRef(false);
  const abort = useRef<AbortController | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const feedRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const now = useNow();
  const open = vigilance.open;

  // keep a copy of every incident seen (closed ones leave the open list but their cards stay in the feed)
  useEffect(() => {
    incidents.forEach((i) => known.current.set(i.id, i));
    setKnownVer((v) => v + 1);
    if (!seeded.current && loaded) {
      seeded.current = true;
      const first = [...incidents].sort((a, b) => a.created_ts.localeCompare(b.created_ts))
        .map<FeedItem>((i) => ({ kind: "alert", key: `a-${i.id}`, incidentId: i.id, note: "open", at: i.created_ts }));
      setItems((cur) => [...first, ...cur]);
    }
  }, [incidents, loaded]);

  const pushToast = useCallback((t: ToastItem) => {
    setToasts((cur) => [...cur.filter((x) => x.inc.id !== t.inc.id), t].slice(-3));
    window.setTimeout(() => setToasts((cur) => cur.filter((x) => x.key !== t.key)), 12_000);
  }, []);

  useConsoleEvents((e) => {
    if (e.type === "demo.reset") {
      abort.current?.abort();
      setItems([]); setToasts([]); setView("feed"); setCaseId(null); setAbout(null);
      seeded.current = false; known.current.clear();
      threads.current = { general: null, byIncident: new Map() };
      return;
    }
    if (e.type !== "copilot.incident") return;
    const { change, incident } = (e.data ?? {}) as { change?: string; incident?: Incident };
    if (!incident?.id) return;
    const prev = known.current.get(incident.id);
    known.current.set(incident.id, incident);
    setKnownVer((v) => v + 1);
    const at = new Date().toISOString();
    const watchingIt = open && view === "case" && caseId === incident.id;
    if (change === "created") {
      setItems((cur) => cur.some((x) => x.kind === "alert" && x.incidentId === incident.id) ? cur
        : [...cur, { kind: "alert", key: `a-${incident.id}-${at}`, incidentId: incident.id, note: "new", at }]);
      if (!watchingIt && (!open || view !== "feed")) pushToast({ key: `t-${incident.id}-${at}`, inc: incident, kind: "new" });
    } else if (change === "updated" && prev && SEV_ORDER[incident.severity] < SEV_ORDER[prev.severity]) {
      setItems((cur) => [...cur, { kind: "alert", key: `e-${incident.id}-${at}`, incidentId: incident.id, note: "escalated", from: prev.severity, at }]);
      if (!watchingIt) pushToast({ key: `t-${incident.id}-${at}`, inc: incident, kind: "escalated", from: prev.severity });
    }
  });

  const confirmWatch = useCallback((id: string, after?: () => void) => {
    if (window.confirm(`Vigilance proposes adding ${id} to close monitoring.\n\nAdd it? (You are making this change, not Vigilance.)`)) {
      api.watch(id, "Proposed by Vigilance, confirmed by the analyst").then(() => after?.()).catch(() => {});
    }
  }, []);
  const allDeps: ActionDeps = useMemo(() => ({ ...deps, confirmWatch: (id: string) => confirmWatch(id) }), [deps, confirmWatch]);
  const onEntity = useCallback((e: EntityRef) => {
    if (e.kind === "tx") deps.openConnections(e.id);
    else deps.select({ kind: "account", id: e.id });
  }, [deps]);

  const threadFor = useCallback(async (aboutId: string | null, fresh = false): Promise<string> => {
    if (aboutId) {
      let t = fresh ? undefined : threads.current.byIncident.get(aboutId);
      if (!t) { t = (await v10.newThread(aboutId)).id; threads.current.byIncident.set(aboutId, t); }
      return t;
    }
    if (!threads.current.general || fresh) threads.current.general = (await v10.newThread(undefined, "Vigilance chat")).id;
    return threads.current.general;
  }, []);

  const send = useCallback(async (text: string, aboutId: string | null) => {
    const content = text.trim();
    if (!content) return;
    setInput("");
    setView("feed");
    const k = `m-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setItems((cur) => [...cur, { kind: "msg", key: `${k}u`, role: "user", content, tools: [], about: aboutId },
      { kind: "msg", key: `${k}a`, role: "assistant", content: "", tools: [], streaming: true, about: aboutId }]);
    const patch = (fn: (m: MsgItem) => MsgItem) =>
      setItems((all) => all.map((it) => (it.kind === "msg" && it.key === `${k}a` ? fn(it) : it)));
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    const run = async (fresh: boolean): Promise<string | null> => {
      let tid: string;
      try { tid = await threadFor(aboutId, fresh); } catch { patch((m) => ({ ...m, streaming: false, error: "Vigilance is not reachable." })); return null; }
      let err: string | null = null;
      await streamMessage(tid, content, (ev) => {
        if (ev.event === "token") patch((m) => ({ ...m, content: m.content + ev.data.text }));
        else if (ev.event === "tool_call") patch((m) => ({ ...m, tools: [...m.tools, { name: ev.data.name, args: ev.data.args }] }));
        else if (ev.event === "tool_result_summary") patch((m) => ({ ...m, tools: m.tools.map((t, i) => (i === m.tools.length - 1 && !t.summary ? { ...t, summary: ev.data.summary } : t)) }));
        else if (ev.event === "done") patch((m) => ({ ...m, content: ev.data.content, streaming: false, llm: ev.data.llm_used }));
        else if (ev.event === "error") err = ev.data.message;
      }, ctl.signal);
      return err;
    };
    try {
      let err = await run(false);
      if (err && /full|unknown thread/i.test(err)) err = await run(true);     // conversation cap reached: start a new one
      if (err) patch((m) => ({ ...m, streaming: false, error: err ?? undefined }));
    } catch (e) {
      if ((e as Error).name !== "AbortError") patch((m) => ({ ...m, streaming: false, error: String(e) }));
    }
    patch((m) => ({ ...m, streaming: false }));
    onStatus();
  }, [threadFor, onStatus]);

  // open requests from anywhere (bar chips, toasts, "Ask Vigilance" buttons)
  useEffect(() => {
    if (!vigilance.open) return;
    setToasts([]);                       // the dock now shows every alert; pop-ups would only cover it
    if (vigilance.incidentId) { setCaseId(vigilance.incidentId); setView("case"); }
    else {
      setView("feed");
      setAbout(vigilance.about);
      if (vigilance.prompt) window.setTimeout(() => send(vigilance.prompt!, vigilance.about), 0);
    }
    window.setTimeout(() => (vigilance.incidentId ? panel.current?.querySelector<HTMLElement>(".vg-case button") : inputRef.current)?.focus(), 40);
  }, [vigilance.seq]); // eslint-disable-line react-hooks/exhaustive-deps

  // keep the feed scrolled to the newest item when the reader is near the bottom
  useEffect(() => {
    const el = feedRef.current;
    if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 220) el.scrollTop = el.scrollHeight;
  }, [items, view]);

  useEffect(() => {
    if (!open) return;
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeVigilance();
      if (e.key === "Tab" && panel.current) {                 // focus trap
        const f = [...panel.current.querySelectorAll<HTMLElement>("button, textarea, input, a[href]")].filter((x) => !x.hasAttribute("disabled"));
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [open, closeVigilance]);

  const drag = (e: React.PointerEvent) => {
    const x0 = e.clientX, w0 = width;
    const mv = (ev: PointerEvent) => setWidth(Math.min(780, Math.max(380, w0 + (x0 - ev.clientX))));
    const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
  };

  const caseInc = caseId ? (incidents.find((i) => i.id === caseId) ?? known.current.get(caseId) ?? null) : null;
  useEffect(() => {          // a case opened from a link may not be in memory yet
    if (caseId && !caseInc) v10.incidents("all").then((d) => { d.incidents.forEach((i) => known.current.set(i.id, i)); setKnownVer((v) => v + 1); }).catch(() => {});
  }, [caseId, caseInc]);
  const aboutInc = about ? (incidents.find((i) => i.id === about) ?? known.current.get(about) ?? null) : null;
  const ai = !!status?.llm_available;
  const streaming = items.some((x) => x.kind === "msg" && x.streaming);

  const toastLayer = <Toasts items={toasts} onClose={(k) => setToasts((c) => c.filter((x) => x.key !== k))}
                             onOpen={(t) => { setToasts((c) => c.filter((x) => x.key !== t.key)); openVigilance({ incidentId: t.inc.id }); }} />;

  if (!open) {
    return (
      <>
        {toastLayer}
        <button className={`vg-launcher ${incidents[0] ? `sev-${incidents[0].severity}` : ""}`} onClick={() => openVigilance({})}
                aria-label={`Open Vigilance (${incidents.length} open alerts)`}>
          <VgMark size={18} /> Vigilance{incidents.length > 0 && <span className="vg-badge">{incidents.length}</span>}
        </button>
      </>
    );
  }
  return (
    <>
      {toastLayer}
      <div className="vg-dock" ref={panel} style={{ width }} role="dialog" aria-label="Vigilance">
        <div className="vg-resize" onPointerDown={drag} title="Drag to resize" />
        <div className="vg-head">
          <VgMark size={22} />
          <div className="vg-head-t"><b>Vigilance</b><span>Fraud-operations agent · read-only</span></div>
          <span className="spacer" />
          <span className={`vg-mode ${ai ? "ai" : ""}`} title={status?.note}>{ai ? `Gemini · ${status?.model_fast}` : "Live-data answers"}</span>
          <button className="btn xs" onClick={closeVigilance} aria-label="Close Vigilance">✕</button>
        </div>

        {view === "case" && caseInc ? (
          <div className="vg-body">
            <CaseView key={caseInc.id} inc={caseInc} deps={allDeps} act={act} now={now} onEntity={onEntity}
                      confirmWatch={confirmWatch}
                      onBack={() => setView("feed")}
                      onAsk={() => { setAbout(caseInc.id); setView("feed"); window.setTimeout(() => inputRef.current?.focus(), 30); }}
                      onStr={() => send("Draft the STR grounds of suspicion for this case.", caseInc.id)}
                      onFocus={() => setIncident(caseInc)} />
          </div>
        ) : view === "case" ? (
          <div className="vg-body"><div className="empty">Loading the case…</div></div>
        ) : (
          <>
            <div className="vg-body vg-feed" ref={feedRef} aria-live="polite">
              <div className="vg-intro">
                <div className="vg-av"><VgMark size={16} /></div>
                <div>
                  <b>Vigilance</b> watches every payment, account and decision as it happens. When something needs a
                  person, it raises an alert here, classified, with the bank's next steps. Ask about any account,
                  payment, ring or city.
                  <div className="vg-intro-m">{ai ? `Answers by Gemini (${status?.model_fast}) from live data; facts come from read-only tools.` : "Answers come straight from live data (AI is off)."} Vigilance never freezes, files or calls: a person decides.</div>
                </div>
              </div>
              {loaded && incidents.length === 0 && !items.some((x) => x.kind === "alert") && (
                <div className="vg-clear"><span className="vg-dot ok" /> All clear — no open alerts.</div>
              )}
              {items.map((it) => it.kind === "alert" ? (
                <AlertCard key={it.key} item={it} inc={known.current.get(it.incidentId) ?? null} now={now}
                           onOpen={() => { setCaseId(it.incidentId); setView("case"); }}
                           onAsk={() => { setAbout(it.incidentId); window.setTimeout(() => inputRef.current?.focus(), 30); }} />
              ) : (
                <Message key={it.key} m={it} onEntity={onEntity} aboutLabel={it.about ? known.current.get(it.about)?.classification : undefined}
                         onRetry={() => { const u = items.filter((x): x is MsgItem => x.kind === "msg" && x.role === "user"); send(u[u.length - 1]?.content ?? "", it.about); }} />
              ))}
            </div>
            <div className="vg-compose">
              {aboutInc && (
                <div className="vg-context">
                  <span className={`vg-pill sev-${aboutInc.severity}`}>{SEV_LABEL[aboutInc.severity]}</span>
                  About: <b>{aboutInc.classification}</b> <span className="dim">· {aboutInc.subject}</span>
                  <button className="vg-x" onClick={() => setAbout(null)} aria-label="Stop asking about this case">✕</button>
                </div>
              )}
              <div className="vg-suggest">{(aboutInc ? ASK_CASE : ASK_ANY).map((s) => (
                <button key={s} className="chipbtn" disabled={streaming} onClick={() => send(s, about)}>{s}</button>))}</div>
              <form className="vg-input" onSubmit={(e) => { e.preventDefault(); send(input, about); }}>
                <textarea ref={inputRef} value={input} maxLength={2000} rows={2}
                          placeholder={aboutInc ? `Ask about this ${aboutInc.classification.toLowerCase()}…` : "Ask Vigilance about an account, payment, ring or city…"}
                          onChange={(e) => setInput(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input, about); } }} aria-label="Message Vigilance" />
                {streaming
                  ? <button type="button" className="btn sm" onClick={() => abort.current?.abort()}>Stop</button>
                  : <button type="submit" className="btn sm primary" disabled={!input.trim()}>Send</button>}
              </form>
            </div>
          </>
        )}
      </div>
    </>
  );
}

function AlertCard({ item, inc, now, onOpen, onAsk }: { item: AlertItem; inc: Incident | null; now: number; onOpen: () => void; onAsk: () => void }) {
  if (!inc) return null;
  const s = sla(inc, now);
  const closed = inc.status !== "open";
  const note = item.note === "new" ? "raised a new alert" : item.note === "escalated" ? `escalated it from ${SEV_LABEL[item.from ?? "low"]}` : "open alert";
  return (
    <div className={`vg-alert sev-${inc.severity} ${closed ? "closed" : ""}`}>
      <div className="vg-alert-h"><VgMark size={14} /><b>Vigilance</b><span>{note}</span><span className="vg-time">{clockTime(item.at)}</span></div>
      <div className="vg-alert-t"><span className={`vg-pill sev-${inc.severity}`}>{SEV_LABEL[inc.severity]}</span><b>{inc.classification}</b></div>
      <div className="vg-alert-b">{inc.situation}</div>
      <div className="vg-alert-m">{inc.typology}</div>
      <div className="vg-alert-f">
        <span className={`vg-sla ${s.overdue ? "over" : ""}`}>{closed ? STATUS_LABEL[inc.status] ?? inc.status : `Respond within ${inc.respond_within} · ${s.text}`}</span>
        {inc.procedure && <span className="vg-prog" title={`${inc.procedure.done} of ${inc.procedure.total} procedure steps done`}>
          <i style={{ width: `${(100 * inc.procedure.done) / Math.max(1, inc.procedure.total)}%` }} /></span>}
        {inc.procedure && <span className="dim xs">{inc.procedure.done}/{inc.procedure.total} steps</span>}
      </div>
      {!closed && inc.procedure?.next && <div className="vg-alert-next"><span>Next</span>{inc.procedure.next}</div>}
      <div className="vg-alert-a">
        <button className="btn xs primary" onClick={onOpen}>Open case →</button>
        <button className="btn xs" onClick={onAsk}>Ask about this</button>
      </div>
    </div>
  );
}

function Message({ m, onEntity, aboutLabel, onRetry }: { m: MsgItem; onEntity: (e: EntityRef) => void; aboutLabel?: string; onRetry: () => void }) {
  return (
    <div className={`vg-msg ${m.role}`}>
      {m.role === "user" ? (
        <div className="vg-user">{aboutLabel && <span className="vg-user-about">re: {aboutLabel}</span>}{m.content}</div>
      ) : (
        <div className="vg-ans">
          <div className="vg-av"><VgMark size={14} /></div>
          <div className="vg-ans-b">
            {m.tools.length > 0 && (
              <div className="vg-tools">{m.tools.map((t, j) => (
                <details key={j} className="vg-tool"><summary>{t.summary ? "✓" : "…"} {t.name.replace(/_/g, " ")}</summary>
                  <div className="mono xs">args: {JSON.stringify(t.args)}</div>{t.summary && <div className="xs">{t.summary}</div>}</details>))}</div>
            )}
            {m.content ? <SafeMarkdown text={m.content} onEntity={onEntity} />
              : m.streaming ? <div className="vg-typing" aria-label="Vigilance is answering"><i /><i /><i /></div> : null}
            {m.error && <div className="vg-err">{m.error} <button className="link" onClick={onRetry}>Retry</button></div>}
            {!m.streaming && m.content && (
              <div className="vg-msg-foot"><span>{m.llm ? "Gemini · from live data · verify before acting" : "From live data (no AI)"}</span>
                <button className="link xs" onClick={() => navigator.clipboard?.writeText(m.content)}>Copy</button></div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── the case: assessment + procedure ──────────────────────────────────────
function CaseView({ inc, deps, act, now, onEntity, confirmWatch, onBack, onAsk, onStr, onFocus }: {
  inc: Incident; deps: ActionDeps; act: (a: UiAction, d: ActionDeps) => boolean; now: number; onEntity: (e: EntityRef) => void;
  confirmWatch: (id: string, after?: () => void) => void; onBack: () => void; onAsk: () => void; onStr: () => void; onFocus: () => void;
}) {
  const [brief, setBrief] = useState<IncidentBrief | null>(null);
  const [briefErr, setBriefErr] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [proc, setProc] = useState<Procedure | null>(null);
  const [why, setWhy] = useState(false);
  const loadProc = useCallback(() => { v10.procedure(inc.id).then(setProc).catch(() => {}); }, [inc.id]);

  useEffect(() => {
    let live = true;
    setBriefErr(false);
    v10.incidentBrief(inc.id, { fast: true }).then((r) => {
      if (!live) return;
      setBrief(r.brief);
      if (r.brief.pending_ai) {
        setAiBusy(true);
        v10.incidentBrief(inc.id).then((r2) => { if (live) setBrief(r2.brief); }).catch(() => {}).finally(() => { if (live) setAiBusy(false); });
      }
    }).catch(() => { if (live) setBriefErr(true); });
    return () => { live = false; };
  }, [inc.id, inc.version]);
  useEffect(() => { loadProc(); }, [loadProc, inc.status, inc.updated_ts]);
  useConsoleEvents((e) => {
    if (e.type === "copilot.incident" && (e.data as { incident?: Incident })?.incident?.id === inc.id) loadProc();
    if (e.type === "intent.updated" || e.type === "breaker.responded" || e.type === "taint.updated") loadProc();
  });

  const caseDeps: ActionDeps = useMemo(() => ({ ...deps, confirmWatch: (id: string) => confirmWatch(id, loadProc) }), [deps, confirmWatch, loadProc]);
  const doStep = (st: ProcedureStep) => {
    if (st.acknowledge) { v10.incidentAction(inc.id, "ack").then(loadProc).catch(() => {}); return; }
    if (st.ui_action && isAllowed(st.ui_action)) {
      act(st.ui_action, caseDeps);
      if (!st.auto_rule && !st.done) v10.setStep(inc.id, st.id, true).then(setProc).catch(() => {});
    }
  };
  const tick = (st: ProcedureStep, done: boolean) => { v10.setStep(inc.id, st.id, done).then(setProc).catch(() => {}); };
  const s = sla(inc, now);
  const next = proc?.steps.find((x) => !x.done) ?? null;

  return (
    <div className="vg-case">
      <div className="vg-case-top">
        <button className="link" onClick={onBack}>← Alerts &amp; chat</button>
        <span className="spacer" />
        {inc.status === "open"
          ? <><button className="btn xs" onClick={() => v10.incidentAction(inc.id, "ack").catch(() => {})} title="Keep it on record but off the open list">Acknowledge</button>
              <button className="btn xs ghost" onClick={() => v10.incidentAction(inc.id, "dismiss").catch(() => {})} title="Not a real issue">Dismiss</button></>
          : <button className="btn xs" onClick={() => v10.incidentAction(inc.id, "reopen").catch(() => {})}>Reopen</button>}
        <span className={`vg-status st-${inc.status}`}>{STATUS_LABEL[inc.status] ?? inc.status}</span>
      </div>
      <div className={`vg-case-head sev-${inc.severity}`}>
        <div className="vg-case-cls"><span className={`vg-pill sev-${inc.severity}`}>{SEV_LABEL[inc.severity]}</span><b>{inc.classification}</b></div>
        <div className="vg-case-typ">{inc.typology}</div>
        <div className={`vg-sla-row ${s.overdue ? "over" : ""}`}><span>Respond within {inc.respond_within}</span><b>{s.text}</b></div>
        {!s.closed && <div className={`vg-sla-bar ${s.overdue ? "over" : ""}`}><i style={{ width: `${Math.round(s.frac * 100)}%` }} /></div>}
        <div className="vg-case-by">Raised {ago(inc.created_ts, now)} ago · {inc.engine}</div>
      </div>

      {!brief ? (
        briefErr ? <div className="empty">Could not load the assessment.</div>
          : <div className="cp-skel"><div /><div /><div className="short" /><span className="ksub">Reading the case…</span></div>
      ) : (
        <>
          <h3 className="vg-headline">{brief.headline}</h3>
          <SafeMarkdown text={brief.summary} onEntity={onEntity} />
          {brief.key_facts.length > 0 && (
            <div className="vg-facts">{brief.key_facts.map((f) => <div key={f.label} className="vg-fact"><span>{f.label}</span><b>{f.value}</b></div>)}</div>
          )}
          {brief.red_flags.length > 0 && (<>
            <div className="vg-sect">Red flags</div>
            <ul className="vg-flags">{brief.red_flags.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </>)}
          {brief.risk_if_ignored && <div className="vg-risk"><b>If nobody acts</b> {brief.risk_if_ignored}</div>}
          <div className="vg-rec">
            <div className="vg-rec-h"><VgMark size={15} /> Vigilance recommends{aiBusy && <span className="vg-ai-busy">refining with AI…</span>}</div>
            <div className="vg-rec-b">{brief.recommendation}</div>
            <div className="vg-rec-c">Confidence <b className={`conf-${brief.confidence.level}`}>{brief.confidence.level}</b> · {brief.confidence.reason}</div>
          </div>
          <div className="vg-src">{brief.llm_used ? "Assessment written by Gemini from live facts · verify before acting" : "Assessment written from live data (no AI)"} · severity, classification and procedure are computed by Vigil</div>
        </>
      )}

      <ProcedureView proc={proc} next={next} onDo={doStep} onTick={tick} />

      <div className="vg-why">
        <button className="link xs" onClick={() => setWhy((v) => !v)} aria-expanded={why}>Why {SEV_LABEL[inc.severity].toLowerCase()}? Score {inc.score}/100</button>
        {why && (
          <div className="cp-why">
            <table className="dt compact"><tbody>{Object.entries(inc.score_parts).map(([k, v]) => <tr key={k}><td>{k}</td><td className="num mono">{v > 0 ? `+${v}` : v}</td></tr>)}</tbody></table>
            <div className="xs dim">Severity = what is at stake (base by kind + ₹ at stake + accounts + confirmed + recency − contained). A hand-set rubric, not validated on real data. Confidence (above) = how sure the evidence is.</div>
          </div>
        )}
      </div>
      {brief && brief.evidence.length > 0 && (
        <div className="vg-evidence"><span className="vg-sect">Evidence</span>{brief.evidence.map((e, i) => (
          <button key={i} className={`ent-chip ${e.ref.kind === "tx" ? "tx" : "acct"}`}
                  onClick={() => (e.ref.kind === "tx" ? deps.openConnections(e.ref.id) : onEntity({ kind: "acct", id: e.ref.id }))}>
            {e.label.replace("@vigil", "")}</button>))}</div>
      )}
      <div className="vg-case-foot">
        <button className="btn sm primary" onClick={onAsk}>Ask about this case</button>
        <button className="btn sm" onClick={onStr} title="A draft of the grounds of suspicion for the Principal Officer; nothing is filed">Draft STR note</button>
        <button className="btn sm" onClick={onFocus} title="Focus the whole Overview on this alert">Incident mode</button>
      </div>
    </div>
  );
}

function ProcedureView({ proc, next, onDo, onTick }: {
  proc: Procedure | null; next: ProcedureStep | null; onDo: (s: ProcedureStep) => void; onTick: (s: ProcedureStep, done: boolean) => void;
}) {
  if (!proc) return <div className="vg-proc"><div className="ksub">Loading the procedure…</div></div>;
  return (
    <section className="vg-proc" aria-label="Bank procedure">
      <div className="vg-proc-h"><b>Procedure</b><span>{proc.done} of {proc.total} steps done</span></div>
      <div className="vg-proc-bar"><i style={{ width: `${proc.total ? (100 * proc.done) / proc.total : 0}%` }} /></div>
      {proc.phases.map((ph, pi) => {
        const steps = proc.steps.filter((x) => x.phase === ph.id);
        if (!steps.length) return null;
        const d = steps.filter((x) => x.done).length;
        return (
          <div key={ph.id} className={`vg-phase ${d === steps.length ? "done" : ""}`}>
            <div className="vg-phase-h"><span className="vg-phase-n">{d === steps.length ? "✓" : pi + 1}</span><b>{ph.label}</b>
              <span className="vg-phase-g">{ph.goal}</span><span className="vg-phase-c">{d}/{steps.length}</span></div>
            {steps.map((st) => <StepRow key={st.id} st={st} isNext={next?.id === st.id} onDo={onDo} onTick={onTick} />)}
          </div>
        );
      })}
      <div className="vg-proc-note">{proc.note}</div>
    </section>
  );
}

function StepRow({ st, isNext, onDo, onTick }: { st: ProcedureStep; isNext: boolean; onDo: (s: ProcedureStep) => void; onTick: (s: ProcedureStep, done: boolean) => void }) {
  const [openD, setOpenD] = useState(isNext);
  useEffect(() => { if (isNext) setOpenD(true); }, [isNext]);
  const action = !st.done && (st.acknowledge
    ? <button className={`btn xs ${isNext ? "primary" : ""}`} onClick={() => onDo(st)}>Acknowledge</button>
    : st.ui_action && isAllowed(st.ui_action)
      ? <button className={`btn xs ${isNext ? "primary" : ""}`} onClick={() => onDo(st)}>{actionLabel(st.ui_action)}</button>
      : st.kind === "outside" ? <button className="btn xs ghost" onClick={() => onTick(st, true)}>Mark done</button> : null);
  return (
    <div className={`vg-step ${st.done ? "done" : ""} ${isNext ? "next" : ""}`}>
      <input type="checkbox" checked={st.done} disabled={st.done_by === "vigil" || st.acknowledge}
             onChange={(e) => onTick(st, e.target.checked)} aria-label={`Mark "${st.title}" ${st.done ? "not done" : "done"}`}
             title={st.done_by === "vigil" ? "Vigil saw this happen" : st.done ? "Untick" : "Tick when done"} />
      <div className="vg-step-main">
        <button className="vg-step-t" onClick={() => setOpenD((o) => !o)} aria-expanded={openD}>
          {isNext && <span className="vg-next">Next</span>}{st.title}</button>
        <div className="vg-step-m">{st.owner} · {st.when}{st.kind === "outside" && st.outside && <span className="vg-out">Outside Vigil · {st.outside}</span>}</div>
        {st.done && st.evidence && <div className="vg-step-ev">✓ {st.done_by === "vigil" ? "Vigil saw: " : ""}{st.evidence}</div>}
        {openD && st.detail && <div className="vg-step-d">{st.detail}</div>}
      </div>
      {action && <div className="vg-step-a">{action}</div>}
    </div>
  );
}

// ── "Ask Vigilance" on the account and case pages ─────────────────────────
/** Opens the open alert that involves these accounts (if any) and asks Vigilance about what is on screen. */
export function AskVigilance({ entities, prompt }: { entities: string[]; prompt: string }) {
  const { incidents, openVigilance } = useVigilance();
  const inc = incidents.find((i) => i.entities.some((e) => entities.includes(e))) ?? null;
  return (
    <>
      {inc && (
        <button className="btn sm vg-case-btn" onClick={() => openVigilance({ incidentId: inc.id })}
                title={`${inc.situation}\nOpen the alert and its procedure`}>
          <span className={`vg-pill sev-${inc.severity}`}>{SEV_LABEL[inc.severity]}</span>{inc.classification}
        </button>
      )}
      <button className="btn sm primary vg-ask-btn" onClick={() => openVigilance({ prompt, about: inc?.id ?? null })}>
        <VgMark size={14} /> Ask Vigilance
      </button>
    </>
  );
}
