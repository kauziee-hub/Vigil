import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useRealtime, type ConnState } from "../api/realtime";
import type { AccountStatusChange, AttackRun, Health, Metrics, ModeView, SystemHealth, WsEnvelope } from "../api/types";
import { handle } from "../lib/format";
import { useDebounced } from "../lib/hooks";
import { ACCOUNT_STATUS_LABEL, ACCOUNT_STATUS_RANK } from "../lib/status";
import { Logo } from "./Logo";
import { TestConsole } from "./TestConsole";
import { ErrorBoundary } from "./ui";

type Listener = (e: WsEnvelope<any>) => void;
interface Toast { id: number; kind: "danger" | "held" | "warn" | "ok"; title: string; body: string; link?: string }
interface Platform {
  subscribe: (l: Listener) => () => void;
  conn: ConnState;
  health: Health | null;
  system: SystemHealth | null;
  metrics: Metrics | null;
  mode: ModeView | null;
  modeAvailable: boolean | null;
  intelAvailable: boolean | null;
  refreshMode: () => void;
}
const ConsoleBus = createContext<Platform>({
  subscribe: () => () => undefined, conn: "connecting", health: null, system: null, metrics: null, mode: null,
  modeAvailable: null, intelAvailable: null, refreshMode: () => undefined,
});

/** One console WebSocket for the whole bank-side app; pages subscribe to it (push-only, no polling). */
export function useConsoleEvents(listener: Listener) {
  const bus = useContext(ConsoleBus);
  const ref = useRef(listener);
  ref.current = listener;
  useEffect(() => bus.subscribe((e) => ref.current(e)), [bus]);
}

export function usePlatform() {
  return useContext(ConsoleBus);
}

export const NAV: { to: string; label: string; title: string; end?: boolean }[] = [
  { to: "/", label: "Overview", title: "Operations overview", end: true },
  { to: "/guard", label: "Payments", title: "Transaction guard — pre-commit assessment of each payment" },
  { to: "/network", label: "Network", title: "Live transaction network and evidence scenes" },
  { to: "/detection", label: "Detection", title: "Detectors, models (SYNTHETIC VALIDATION), SHAP, drift, pattern memory" },
  { to: "/investigations", label: "Cases", title: "Investigations — decisions and accounts" },
  { to: "/interventions", label: "Interventions", title: "Holds, confirmations and trusted-contact alerts" },
  { to: "/governance", label: "Governance", title: "Mode, policy, models, decision records" },
]

export function Shell({ children }: { children: ReactNode }) {
  const listeners = useRef(new Set<Listener>());
  const loc = useLocation();
  const [system, setSystem] = useState<SystemHealth | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [mode, setMode] = useState<ModeView | null>(null);
  const [modeAvailable, setModeAvailable] = useState<boolean | null>(null);
  const [intelAvailable, setIntelAvailable] = useState<boolean | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const announced = useRef(new Set<string>());

  const subscribe = useCallback((l: Listener) => {
    listeners.current.add(l);
    return () => { listeners.current.delete(l); };
  }, []);

  const loadHealth = useCallback(() => {
    api.systemHealth()
      .then((h) => { setSystem(h); setHealth(h); setIntelAvailable(h.intel_available); })
      .catch(() => {
        setSystem(null);
        api.health().then(setHealth).catch(() => undefined);
        api.intelModels().then(() => setIntelAvailable(true)).catch(() => setIntelAvailable(false));
      });
  }, []);
  const refreshMode = useCallback(() => {
    api.mode().then((m) => { setMode(m); setModeAvailable(true); })
      .catch((e) => { setMode(null); setModeAvailable(e?.status === 404 ? false : null); });
  }, []);
  const loadMetrics = useDebounced(() => { api.metrics().then(setMetrics).catch(() => undefined); }, 1500);

  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastSeq = useRef(0);
  const pushToast = useCallback((t: Omit<Toast, "id">) => {
    const id = ++toastSeq.current;
    setToasts((xs) => [...xs.slice(-3), { ...t, id }]);
    window.setTimeout(() => setToasts((xs) => xs.filter((x) => x.id !== id)), 6500);
  }, []);

  const conn = useRealtime(["console"], (e) => {
    if (e.type === "intel.account_status") {
      const c = e.data as AccountStatusChange;
      const up = c && ACCOUNT_STATUS_RANK[c.status] > ACCOUNT_STATUS_RANK[c.previous];
      if (up && (c.status === "flagged" || c.status === "held" || c.status === "confirmed_fraud")) {
        pushToast({ kind: c.status === "held" ? "held" : "danger", link: `/investigations/account/${encodeURIComponent(c.account_id)}`,
          title: `${handle(c.account_id)} · ${ACCOUNT_STATUS_LABEL[c.status].toLowerCase()}`,
          body: `${c.reason || `was ${ACCOUNT_STATUS_LABEL[c.previous].toLowerCase()}`}${c.families_flagging ? ` · ${c.families_flagging} detector families agree` : ""}` });
      }
    }
    if (e.type === "attack.run_updated") {
      const r = e.data as AttackRun;
      if (r?.status === "completed" && !announced.current.has(r.run_id)) {
        announced.current.add(r.run_id);
        pushToast({ kind: r.detected.length ? "ok" : "warn", link: "/#attack-history", title: `${r.run_id} · ${r.name} completed`,
          body: `Detected ${r.detected.length} of ${r.injected.length} injected mules (simulator ground truth)` });
      }
    }
    if (e.type === "ambient.changed" || e.type === "demo.reset" || e.type === "intel.updated") loadHealth();
    if (e.type === "mode.changed") {
      const d = e.data as Partial<ModeView>;
      if (d && d.mode) { setMode((m) => ({ since: null, note: "", ...m, ...d } as ModeView)); setModeAvailable(true); }
      else refreshMode();
    }
    if (["decision.created", "intent.updated", "demo.reset", "metrics.dirty", "ledger.posted"].includes(e.type)) loadMetrics();
    listeners.current.forEach((l) => l(e));
  });
  // Initial load, then a re-sync only when the push channel (re)opens — never on every reconnect attempt.
  const opened = useRef(false);
  useEffect(() => {
    if (conn !== "open" && opened.current) return;
    if (conn === "open") opened.current = true;
    loadHealth(); refreshMode(); api.metrics().then(setMetrics).catch(() => undefined);
  }, [conn, loadHealth, refreshMode]);

  // light is the default (v5); "dark" is the alternative
  const [theme, setTheme] = useState(() => {
    try { const t = localStorage.getItem("vigil-theme"); return t === "dark" ? "dark" : ""; } catch { return ""; }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("vigil-theme", theme); } catch { /* ignore */ }
  }, [theme]);

  // demo-only test inputs (PRIMA /ops style), opened from the top bar or with Alt+T
  const [testOpen, setTestOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.altKey && (e.key === "t" || e.key === "T")) { e.preventDefault(); setTestOpen((v) => !v); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const open = metrics?.open_interventions ?? 0;
  const shadow = mode?.mode === "shadow";
  const provider = "simulated rail (no real money)";
  const healthy = conn === "open" && intelAvailable !== false;
  const statusTitle = [
    `Mode: ${mode ? mode.mode.toUpperCase() : "…"}`, `Payments: ${provider}`,
    `Realtime: ${conn === "open" ? "live" : conn}`, `Policy: ${health?.policy_version ?? "…"}`,
    `Detection intelligence: ${intelAvailable === null ? "…" : intelAvailable ? "available" : "not available"}`,
    "External intelligence: SIMULATED", `Background traffic: ${health ? (health.ambient ? "on" : "off") : "…"}`,
  ].join("\n");

  return (
    <ConsoleBus.Provider value={{ subscribe, conn, health, system, metrics, mode, modeAvailable, intelAvailable, refreshMode }}>
      <div className="shell">
        <div className="main">
          <header className="topbar">
            <NavLink to="/" className="brand" aria-label="Vigil — overview"><Logo /></NavLink>
            <nav className="topnav" aria-label="Primary">
              {NAV.map((n) => (
                <NavLink key={n.to} to={n.to} end={n.end} title={n.title}>
                  {n.label}{n.to === "/interventions" && open > 0 && <span className="badge">{open}</span>}
                </NavLink>
              ))}
            </nav>
            <div className="tb-right">
              <button className="test-btn" onClick={() => setTestOpen(true)} title="Demo-only test inputs (Alt+T)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 3h6M10 3v6L4.5 18.5A1.5 1.5 0 0 0 5.8 21h12.4a1.5 1.5 0 0 0 1.3-2.5L14 9V3" /></svg>
                <span>Test inputs</span>
              </button>
              <Link className={`icon-btn ${healthy ? "ok" : "warn"}`} to="/health" title={statusTitle} aria-label="System health">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l3-8 4 16 3-8h4" /></svg>
                <span className="dot-n" />
              </Link>
              <Link className="icon-btn" to="/interventions" title={`${open} open intervention${open === 1 ? "" : "s"}`} aria-label="Open interventions">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 0 0 3.4 0" /></svg>
                {open > 0 && <span className="dot-n" />}
              </Link>
              <button className="icon-btn" aria-label="Toggle colour theme" title={theme === "dark" ? "Light theme" : "Dark theme"}
                      onClick={() => setTheme(theme === "dark" ? "" : "dark")}>
                {theme === "dark"
                  ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
                  : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>}
              </button>
              <div className="user-chip" title={statusTitle}>
                <span className="av">FO</span>
                <span className="who">Fraud operations<small>{shadow ? "Shadow mode" : "Active mode"} · {conn === "open" ? "live" : conn}</small></span>
              </div>
            </div>
          </header>
          {shadow && (
            <div className="shadow-band" role="note">
              <b>Shadow mode</b> — Vigil evaluates every payment and records its recommendation, but does not intervene. The bank's baseline decision is applied.
              <Link to="/governance">Governance →</Link>
            </div>
          )}
          <main className="page"><ErrorBoundary resetKey={loc.pathname}>{children}</ErrorBoundary></main>
          <footer className="xs dim center" style={{ padding: "0 28px 28px" }}>
            Vigil · PRIMA architecture · prototype on synthetic data — not connected to any bank, regulator or payment network.
            {" "}Payments: {provider} · external intelligence simulated.
          </footer>
        </div>
      </div>
      {testOpen && <TestConsole onClose={() => setTestOpen(false)} />}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <b>{t.link ? <Link to={t.link}>{t.title}</Link> : t.title}</b>
            <span className="muted sm">{t.body}</span>
          </div>
        ))}
      </div>
    </ConsoleBus.Provider>
  );
}
