import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useRealtime, type ConnState } from "../api/realtime";
import type { AccountStatusChange, AttackRun, Health, Metrics, ModeView, SystemHealth, WsEnvelope } from "../api/types";
import { handle } from "../lib/format";
import { useDebounced } from "../lib/hooks";
import { ACCOUNT_STATUS_LABEL, ACCOUNT_STATUS_RANK } from "../lib/status";
import { ErrorBoundary, Sim } from "./ui";

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

export const NAV: { to: string; label: string; end?: boolean; group?: string }[] = [
  { to: "/", label: "Live operations", end: true, group: "Operate" },
  { to: "/guard", label: "Transaction guard" },
  { to: "/network", label: "Network intelligence", group: "Intelligence" },
  { to: "/detection", label: "Detection & models" },
  { to: "/investigations", label: "Investigations" },
  { to: "/interventions", label: "Interventions" },
  { to: "/governance", label: "Governance & audit", group: "Control" },
  { to: "/lab", label: "Scenario lab" },
  { to: "/health", label: "System health" },
];

/** 16px stroke icons for the primary navigation (one per area; no numbering). */
const NAV_ICON: Record<string, ReactNode> = {
  "/": <><path d="M3 12h4l3-8 4 16 3-8h4" /></>,
  "/guard": <><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z" /><path d="M9 12l2 2 4-4" /></>,
  "/network": <><circle cx="6" cy="6" r="2.2" /><circle cx="18" cy="7" r="2.2" /><circle cx="12" cy="18" r="2.2" /><path d="M8 7l8 0M7 8l4 8M17 9l-4 7" /></>,
  "/detection": <><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>,
  "/investigations": <><circle cx="11" cy="11" r="6" /><path d="M20 20l-4.5-4.5" /></>,
  "/interventions": <><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></>,
  "/governance": <><path d="M4 9h16M6 9v9M10 9v9M14 9v9M18 9v9M3 20h18M12 3l9 4H3z" /></>,
  "/lab": <><path d="M9 3h6M10 3v6L4.5 18.5A1.5 1.5 0 0 0 5.8 21h12.4a1.5 1.5 0 0 0 1.3-2.5L14 9V3" /></>,
  "/health": <><rect x="3" y="4" width="18" height="12" rx="1.5" /><path d="M8 20h8M12 16v4" /></>,
};
function NavIcon({ to }: { to: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {NAV_ICON[to]}
    </svg>
  );
}

function Clock() {
  const [t, setT] = useState(() => new Date());
  useEffect(() => { const i = window.setInterval(() => setT(new Date()), 1000); return () => window.clearInterval(i); }, []);
  return <span className="v">{t.toLocaleTimeString("en-IN", { hour12: false })} IST</span>;
}

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

  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("vigil-theme") ?? ""; } catch { return ""; }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("vigil-theme", theme); } catch { /* ignore */ }
  }, [theme]);

  // any gateway problem is shown, not only rejected keys (a probe can also fail with HTTP 429 / be unreachable)
  const gwStatus = health?.gateway?.status;
  const gwBad = gwStatus === "auth_failed" || gwStatus === "error" || gwStatus === "unreachable";
  const gwText = gwStatus === "auth_failed" ? "gateway keys rejected" : gwStatus === "unreachable" ? "gateway unreachable"
    : `gateway check failed${health?.gateway?.detail ? ` (${health.gateway.detail})` : ""}`;
  const open = metrics?.open_interventions ?? 0;
  const shadow = mode?.mode === "shadow";

  return (
    <ConsoleBus.Provider value={{ subscribe, conn, health, system, metrics, mode, modeAvailable, intelAvailable, refreshMode }}>
      <div className="shell">
        <aside className="side" aria-label="Primary">
          <NavLink to="/" className="side-brand">
            <span className="mark">V</span>
            <span className="txt">
              <div className="name">VIGIL</div>
              <div className="sub">Payment risk &amp; mule intelligence</div>
            </span>
          </NavLink>
          <nav className="side-nav">
            {NAV.map((n) => (
              <div key={n.to} style={{ display: "contents" }}>
                {n.group && <div className="side-group">{n.group}</div>}
                <NavLink to={n.to} end={n.end} title={n.label}>
                  <span className="idx"><NavIcon to={n.to} /></span>
                  <span className="lbl">{n.label}</span>
                  {n.to === "/interventions" && open > 0 ? <span className="badge hot">{open}</span> : <span />}
                </NavLink>
              </div>
            ))}
          </nav>
          <div className="side-foot">
            <span>PRIMA architecture · prototype on synthetic data.</span>
            <span>Not connected to any regulator, payment network or bank system.</span>
          </div>
        </aside>
        <div className="main">
          <div className="strip" role="status" aria-label="Platform status">
            <div className="strip-item" title={mode?.note || "Operating mode"}>
              <span className="k">Mode</span>
              {mode ? <span className={`pill nodot ${shadow ? "s-watch" : "s-normal"}`}>{shadow ? "SHADOW" : "ACTIVE"}</span>
                : <span className="v muted">{modeAvailable === false ? "n/a" : "…"}</span>}
            </div>
            <div className="strip-item" title={health?.payment_provider_label}>
              <span className="k">Payments</span>
              <span className="v">{health ? (health.payment_provider === "razorpay_test" ? "Razorpay TEST" : "Mock") : "…"}</span>
              {gwBad && <span className="pill s-watch nodot" title={health?.gateway?.detail}>{gwText}</span>}
            </div>
            <div className="strip-item" title="Realtime push channel (WebSocket)">
              <span className="k">Realtime</span>
              <span className={`dot ${conn === "open" ? "ok" : conn === "connecting" ? "warn" : "bad"}`} />
              <span className="v">{conn === "open" ? "live" : conn}</span>
            </div>
            <div className="strip-item" title="Risk policy version applied to new decisions">
              <span className="k">Policy</span>
              <span className="v">{health?.policy_version ?? "…"}</span>
            </div>
            <div className="strip-item" title="Detection intelligence layer (RF / GNN / drift / pattern memory) — /api/intel/*">
              <span className="k">Intel</span>
              <span className={`dot ${intelAvailable ? "ok" : intelAvailable === false ? "" : "warn"}`} />
              <span className="v">{intelAvailable === null ? "…" : intelAvailable ? "available" : "not available"}</span>
            </div>
            <div className="strip-item" title={health?.external_intel_provider}>
              <span className="k">Ext. intel</span>
              <Sim />
            </div>
            <div className="strip-item" title="Background (ambient) transaction stream">
              <span className="k">Stream</span>
              <span className="v">{health ? (health.ambient ? "on" : "off") : "…"}</span>
            </div>
            <div className="strip-item end">
              <Clock />
              <button aria-label="Toggle colour theme" title="Theme"
                      onClick={() => setTheme(theme === "light" ? "" : "light")}>{theme === "light" ? "◑" : "◐"}</button>
            </div>
          </div>
          {shadow && (
            <div className="shadow-band" role="note">
              <b>SHADOW MODE</b> — Vigil evaluates every payment and records its recommendation, but does not intervene. The bank's baseline decision is applied.
              <Link to="/governance">Governance →</Link>
            </div>
          )}
          <main className="page"><ErrorBoundary resetKey={loc.pathname}>{children}</ErrorBoundary></main>
        </div>
      </div>
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
