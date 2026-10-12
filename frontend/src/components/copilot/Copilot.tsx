// VIGIL COPILOT — incident strip + dock (Briefing · Chat). Read-only: every button either navigates, selects, or (for
// "watch") asks the analyst to confirm. Text from the model is rendered through SafeMarkdown (no raw HTML).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import { streamMessage, v10, type CopilotStatus, type Incident, type IncidentBrief, type ToolCall } from "../../api/v10";
import { ACTION_LABEL, isAllowed, runAction, type ActionDeps } from "../../lib/copilotActions";
import { formatPaiseShort } from "../../lib/format";
import { useThrottled } from "../../lib/live";
import { SafeMarkdown, type EntityRef } from "../../lib/safeMarkdown";
import { useSelection } from "../../lib/selection";
import { useConsoleEvents } from "../Shell";
import { sortIncidents } from "../../lib/incidents";

const KIND_GLYPH: Record<string, string> = {
  ring_formed: "◎", account_flagged: "⚑", cash_out_cluster: "₹", impossible_travel: "✈", payment_held_t3: "⏸",
  tier4_coercion: "☎", fast_pass_through_new_account: "➜", device_farm: "▣", confirmed_scam_trace: "⛓",
};

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  return s < 60 ? `${Math.round(s)}s` : s < 3600 ? `${Math.round(s / 60)}m` : `${Math.round(s / 3600)}h`;
}

export function useIncidents() {
  const [list, setList] = useState<Incident[]>([]);
  const [max, setMax] = useState(5);
  const load = useCallback(() => {
    v10.incidents("open").then((d) => {
      setList(sortIncidents(d.incidents));
      setMax(d.max_visible);
    }).catch(() => {});
  }, []);
  useEffect(() => { load(); }, [load]);
  const t = useThrottled(load, 800);
  useConsoleEvents((e) => { if (e.type === "copilot.incident" || e.type === "demo.reset") t(); });
  return { list, max, reload: load };
}

// ── incident strip ────────────────────────────────────────────────────────
export function IncidentStrip({ incidents, max }: { incidents: Incident[]; max: number }) {
  const { openCopilot } = useSelection();
  const [more, setMore] = useState(false);
  const visible = incidents.slice(0, max);
  const rest = incidents.slice(max);
  return (
    <div className="inc-strip" role="list" aria-label="Copilot incidents">
      <span className="inc-k"><span className="cp-logo">✦</span> Copilot</span>
      {incidents.length === 0 && <span className="inc-empty">No active incidents — Copilot is watching.</span>}
      {visible.map((i) => (
        <button key={i.id} role="listitem" className={`inc-chip sev-${i.severity} ${Date.now() - new Date(i.created_ts).getTime() < 60000 ? "fresh" : ""}`}
                onClick={() => openCopilot({ incidentId: i.id })} title={`${i.kind_label} · ${i.severity} (${i.score}/100) · raised by ${i.engine}`}>
          <span className="sev-dot" aria-label={i.severity} />
          <span className="inc-sev">{i.severity.toUpperCase()}</span>
          <span className="inc-glyph" aria-hidden="true">{KIND_GLYPH[i.kind] ?? "•"}</span>
          <span className="inc-title">{i.title}</span>
          {i.value_paise ? <span className="inc-val">{formatPaiseShort(i.value_paise)}</span> : null}
          <span className="inc-age">{ago(i.updated_ts)}</span>
        </button>
      ))}
      {rest.length > 0 && (
        <span className="inc-more-wrap">
          <button className="inc-chip more" onClick={() => setMore((v) => !v)} aria-expanded={more}>+{rest.length} more</button>
          {more && (
            <div className="inc-pop" role="menu">
              {rest.map((i) => <button key={i.id} role="menuitem" className={`inc-pop-row sev-${i.severity}`} onClick={() => { setMore(false); openCopilot({ incidentId: i.id }); }}>
                <span className="sev-dot" /><b>{i.severity}</b> {i.title}</button>)}
            </div>
          )}
        </span>
      )}
    </div>
  );
}

// ── dock ──────────────────────────────────────────────────────────────────
interface ChatMsg { role: "user" | "assistant"; content: string; tools: ToolCall[]; streaming?: boolean; error?: string; llm?: boolean }
const SUGGEST_INC = ["What should I do first?", "Trace the money", "Who else is linked?", "Is this a false positive?", "Explain this like I'm new"];
const SUGGEST_GEN = ["Show open incidents", "Which rings are active?", "Situation summary", "New accounts pipeline", "Where is money leaving the bank?", "Channel mix"];

export function CopilotDock({ incidents, deps }: { incidents: Incident[]; deps: Omit<ActionDeps, "confirmWatch"> }) {
  const { copilot, openCopilot, closeCopilot, setIncident } = useSelection();
  const nav = useNavigate();
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const [tab, setTab] = useState<"brief" | "chat">("brief");
  const [incId, setIncId] = useState<string | null>(null);
  const [brief, setBrief] = useState<IncidentBrief | null>(null);
  const [briefErr, setBriefErr] = useState<string | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [width, setWidth] = useState(440);
  const abort = useRef<AbortController | null>(null);
  const panel = useRef<HTMLDivElement>(null);
  const incident = useMemo(() => incidents.find((i) => i.id === incId) ?? null, [incidents, incId]);

  useEffect(() => { v10.copilotStatus().then(setStatus).catch(() => {}); }, [copilot.seq]);
  const confirmWatch = useCallback((id: string) => {
    if (window.confirm(`Copilot proposes adding ${id} to close monitoring.\n\nAdd it? (You are making this change, not the Copilot.)`)) {
      api.watch(id, "Proposed by Copilot, confirmed by the analyst").catch(() => {});
    }
  }, []);
  const allDeps: ActionDeps = useMemo(() => ({ ...deps, confirmWatch }), [deps, confirmWatch]);
  const onEntity = useCallback((e: EntityRef) => {
    if (e.kind === "tx") deps.openConnections(e.id);
    else deps.select({ kind: "account", id: e.id });
  }, [deps]);

  const loadBrief = useCallback(async (id: string, deep = false) => {
    setBriefBusy(true); setBriefErr(null);
    try {
      const r = await v10.incidentBrief(id, deep);
      setBrief(r.brief);
      if (r.thread_id) {
        setThreadId(r.thread_id);
        const t = await v10.thread(r.thread_id);
        setMsgs(t.messages.map((m) => ({ role: m.role, content: m.content, tools: m.tool_calls })));
      }
    } catch (e) { setBriefErr(String(e)); }
    finally { setBriefBusy(false); }
  }, []);

  const send = useCallback(async (text: string) => {
    const content = text.trim();
    if (!content) return;
    let tid = threadId;
    if (!tid) {
      try { tid = (await v10.newThread(incId ?? undefined)).id; setThreadId(tid); } catch { return; }
    }
    setTab("chat");
    setInput("");
    setMsgs((m) => [...m, { role: "user", content, tools: [] }, { role: "assistant", content: "", tools: [], streaming: true }]);
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    const patch = (fn: (m: ChatMsg) => ChatMsg) => setMsgs((all) => { const c = [...all]; c[c.length - 1] = fn(c[c.length - 1]); return c; });
    try {
      await streamMessage(tid!, content, (e) => {
        if (e.event === "token") patch((m) => ({ ...m, content: m.content + e.data.text }));
        else if (e.event === "tool_call") patch((m) => ({ ...m, tools: [...m.tools, { name: e.data.name, args: e.data.args }] }));
        else if (e.event === "tool_result_summary") patch((m) => ({ ...m, tools: m.tools.map((t, i) => i === m.tools.length - 1 && !t.summary ? { ...t, summary: e.data.summary } : t) }));
        else if (e.event === "done") patch((m) => ({ ...m, content: e.data.content, streaming: false, llm: e.data.llm_used }));
        else if (e.event === "error") patch((m) => ({ ...m, streaming: false, error: e.data.message }));
      }, ctl.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") patch((m) => ({ ...m, streaming: false, error: String(err) }));
    }
    patch((m) => ({ ...m, streaming: false }));
  }, [threadId, incId]);

  // open requests from anywhere (strip chip, "Ask Copilot" buttons)
  useEffect(() => {
    if (!copilot.open) return;
    if (copilot.incidentId) {
      if (copilot.incidentId !== incId) { setIncId(copilot.incidentId); setBrief(null); setThreadId(null); setMsgs([]); }
      setTab("brief");
      loadBrief(copilot.incidentId);
    } else if (copilot.prompt) {
      setIncId(null); setBrief(null); setThreadId(null); setMsgs([]);
      window.setTimeout(() => send(copilot.prompt!), 0);
    }
    window.setTimeout(() => panel.current?.querySelector<HTMLElement>("button, textarea")?.focus(), 30);
  }, [copilot.seq]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!copilot.open) return;
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeCopilot();
      if (e.key === "Tab" && panel.current) {                 // focus trap
        const f = [...panel.current.querySelectorAll<HTMLElement>("button, textarea, input, a[href]")].filter((x) => !x.hasAttribute("disabled"));
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [copilot.open, closeCopilot]);

  const drag = (e: React.PointerEvent) => {
    const x0 = e.clientX, w0 = width;
    const mv = (ev: PointerEvent) => setWidth(Math.min(760, Math.max(360, w0 + (x0 - ev.clientX))));
    const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
  };

  if (!copilot.open) {
    return (
      <button className="cp-launcher" onClick={() => openCopilot({ incidentId: incidents[0]?.id ?? null })}
              aria-label={`Open Copilot (${incidents.length} open incidents)`}>
        <span className="cp-logo">✦</span> Copilot{incidents.length > 0 && <span className="cp-badge">{incidents.length}</span>}
      </button>
    );
  }
  const offline = status && !status.llm_available;
  return (
    <div className="cp-dock" ref={panel} style={{ width }} role="dialog" aria-label="Vigil Copilot">
      <div className="cp-resize" onPointerDown={drag} title="Drag to resize" />
      <div className="cp-head">
        <span className="cp-logo">✦</span><b>Vigil Copilot</b>
        <span className={`chip ${offline ? "mute" : "live"}`} title={status?.note}>{offline ? "offline · templates" : status ? `Gemini · ${status.model_fast}` : "…"}</span>
        <span className="spacer" />
        <button className="btn xs" onClick={closeCopilot} aria-label="Close Copilot">✕</button>
      </div>
      {offline && <div className="cp-banner">Copilot is running in offline mode (templates only): briefings are built deterministically from live data, and chat answers common questions with the same read-only tools. Add GEMINI_API_KEY to .env to enable AI answers.</div>}
      <div className="seg cp-tabs">
        <button className={tab === "brief" ? "on" : ""} onClick={() => setTab("brief")}>Briefing</button>
        <button className={tab === "chat" ? "on" : ""} onClick={() => setTab("chat")}>Chat</button>
      </div>
      {tab === "brief" ? (
        <div className="cp-body">
          {!incId ? (
            <div className="cp-pick">
              <div className="ksub">Pick an incident to brief, or ask anything in Chat.</div>
              {incidents.length === 0 ? <div className="empty">No open incidents — Copilot is watching.</div> :
                incidents.map((i) => <button key={i.id} className={`inc-pop-row sev-${i.severity}`} onClick={() => openCopilot({ incidentId: i.id })}><span className="sev-dot" /><b>{i.severity}</b> {i.title}</button>)}
            </div>
          ) : briefBusy && !brief ? (
            <div className="cp-skel"><div /><div /><div /><div className="short" /><span className="ksub">Generating briefing…</span></div>
          ) : briefErr ? (
            <div className="empty">Could not build the briefing. <button className="link" onClick={() => incId && loadBrief(incId)}>Retry</button></div>
          ) : brief ? (
            <BriefView brief={brief} incident={incident} deps={allDeps} onEntity={onEntity} busy={briefBusy}
                       onDeep={status?.llm_available ? () => incId && loadBrief(incId, true) : undefined}
                       onAck={() => incId && v10.incidentAction(incId, "ack")} onDismiss={() => incId && v10.incidentAction(incId, "dismiss")}
                       onFocus={() => incident && setIncident(incident)} onOpenPage={(p) => nav(p)} />
          ) : null}
        </div>
      ) : (
        <div className="cp-body chat">
          <div className="cp-msgs" aria-live="polite">
            {msgs.length === 0 && <div className="ksub">{incId ? "Ask about this incident — its facts are already loaded." : "Ask about accounts, postings, rings, the mule pipeline, rails or cities."}</div>}
            {msgs.map((m, i) => (
              <div key={i} className={`cp-msg ${m.role}`}>
                {m.tools.length > 0 && (
                  <div className="cp-tools">{m.tools.map((t, j) => (
                    <details key={j} className="cp-tool"><summary>🔎 {t.name.replace(/_/g, " ")}{t.summary ? "" : "…"}</summary>
                      <div className="mono xs">args: {JSON.stringify(t.args)}</div>{t.summary && <div className="xs">{t.summary}</div>}</details>))}</div>
                )}
                {m.role === "assistant" ? <SafeMarkdown text={m.content || (m.streaming ? "…" : "")} onEntity={onEntity} /> : <div className="cp-user">{m.content}</div>}
                {m.error && <div className="cp-err">{m.error} <button className="link" onClick={() => { const last = [...msgs].reverse().find((x) => x.role === "user"); if (last) send(last.content); }}>Retry</button></div>}
                {m.role === "assistant" && !m.streaming && m.content && (
                  <div className="cp-msg-foot"><span className="dim xs">{m.llm ? "AI-generated · verify before acting" : "From live data (deterministic)"}</span>
                    <button className="link xs" onClick={() => navigator.clipboard?.writeText(m.content)}>copy</button></div>
                )}
              </div>
            ))}
          </div>
          <div className="cp-suggest">{(incId ? SUGGEST_INC : SUGGEST_GEN).map((s) => <button key={s} className="chipbtn" onClick={() => send(s)}>{s}</button>)}</div>
          <form className="cp-input" onSubmit={(e) => { e.preventDefault(); send(input); }}>
            <textarea value={input} maxLength={2000} rows={2} placeholder="Ask the Copilot…" onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} aria-label="Message the Copilot" />
            {msgs[msgs.length - 1]?.streaming
              ? <button type="button" className="btn sm" onClick={() => abort.current?.abort()}>Stop</button>
              : <button type="submit" className="btn sm primary" disabled={!input.trim()}>Send</button>}
          </form>
        </div>
      )}
    </div>
  );
}

function BriefView({ brief, incident, deps, onEntity, onDeep, onAck, onDismiss, onFocus, busy }: {
  brief: IncidentBrief; incident: Incident | null; deps: ActionDeps; onEntity: (e: EntityRef) => void; onDeep?: () => void;
  onAck: () => void; onDismiss: () => void; onFocus: () => void; onOpenPage: (p: string) => void; busy: boolean;
}) {
  const [why, setWhy] = useState(false);
  return (
    <div className="cp-brief">
      <div className="cp-note">{brief.llm_used ? "AI-generated · verify before acting" : "Deterministic briefing (no AI) · built from live data"}{brief.raised_by ? ` · raised by ${brief.raised_by}` : ""}</div>
      <h3>{brief.headline}</h3>
      <div className="row tight wrap">
        <button className={`sev-badge sev-${brief.severity.level}`} onClick={() => setWhy((v) => !v)} aria-expanded={why}>
          {brief.severity.level.toUpperCase()}{incident ? ` · ${incident.score}/100` : ""} — why?</button>
        <span className={`conf conf-${brief.confidence.level}`} title={brief.confidence.reason}>Confidence: {brief.confidence.level}</span>
      </div>
      {why && incident && (
        <div className="cp-why">
          <div className="xs">{brief.severity.reason}</div>
          <table className="dt compact"><tbody>{Object.entries(incident.score_parts).map(([k, v]) => <tr key={k}><td>{k}</td><td className="num mono">{v > 0 ? `+${v}` : v}</td></tr>)}</tbody></table>
          <div className="xs dim">Severity = what is at stake (hand-set rubric, not validated on real data). Confidence = how sure the evidence is.</div>
        </div>
      )}
      <div className="sect-t">What happened</div>
      <ul className="cp-list">{brief.what_happened.map((x, i) => <li key={i}><SafeMarkdown text={x} onEntity={onEntity} /></li>)}</ul>
      <div className="sect-t">Why it matters</div>
      <SafeMarkdown text={brief.why_it_matters} onEntity={onEntity} />
      <div className="sect-t">What to do</div>
      <div className="cp-todo">
        {brief.what_to_do.map((t, i) => (
          <div key={i} className="cp-todo-card">
            <div><b>{i + 1}.</b> {t.action}</div>
            {t.rationale && <div className="xs dim">{t.rationale}</div>}
            {isAllowed(t.ui_action) && <button className="btn xs" onClick={() => runAction(t.ui_action, deps)}>{ACTION_LABEL[t.ui_action.type as keyof typeof ACTION_LABEL]}{t.ui_action.target ? ` · ${t.ui_action.target.replace("@vigil", "")}` : ""}</button>}
          </div>
        ))}
      </div>
      {brief.open_questions.length > 0 && (<><div className="sect-t">Open questions</div><ul className="cp-list">{brief.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></>)}
      {brief.evidence.length > 0 && (<><div className="sect-t">Evidence</div><div className="row tight wrap">{brief.evidence.map((e, i) => (
        <button key={i} className={`ent-chip ${e.ref.kind === "tx" ? "tx" : "acct"}`}
                onClick={() => e.ref.kind === "tx" ? deps.openConnections(e.ref.id) : e.ref.kind === "account" ? onEntity({ kind: "acct", id: e.ref.id }) : runAction({ type: "show_on_map", target: e.ref.id }, deps)}>
          {e.label.replace("@vigil", "")}</button>))}</div></>)}
      <div className="cp-brief-actions">
        <button className="btn sm" onClick={onFocus}>Incident mode</button>
        {onDeep && <button className="btn sm" onClick={onDeep} disabled={busy}>Deep dive</button>}
        <button className="btn sm" onClick={onAck}>Acknowledge</button>
        <button className="btn sm ghost" onClick={onDismiss}>Dismiss</button>
      </div>
    </div>
  );
}
