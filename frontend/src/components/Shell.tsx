import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { api } from "../api/client";
import { useRealtime, type ConnState } from "../api/realtime";
import type { Health, Metrics, ModeView, SystemHealth, WsEnvelope } from "../api/types";
import { useDebounced } from "../lib/hooks";
import { ErrorBoundary, Sim } from "./ui";

type Listener = (e: WsEnvelope<any>) => void;
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
  { to: "/", label: "Overview", end: true, group: "Operate" },
  { to: "/guard", label: "Transaction Guard" },
  { to: "/network", label: "Network Intelligence", group: "Intelligence" },
  { to: "/detection", label: "Detection & Models" },
  { to: "/investigations", label: "Investigations" },
  { to: "/interventions", label: "Interventions" },
  { to: "/governance", label: "Governance & Audit", group: "Control" },
  { to: "/lab", label: "Scenario Lab" },
  { to: "/health", label: "System Health" },
];

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

  const conn = useRealtime(["console"], (e) => {
    if (e.type === "ambient.changed" || e.type === "demo.reset" || e.type === "intel.updated") loadHealth();
    if (e.type === "mode.changed") {
      const d = e.data as Partial<ModeView>;
      if (d && d.mode) { setMode((m) => ({ since: null, note: "", ...m, ...d } as ModeView)); setModeAvailable(true); }
      else refreshMode();
    }
    if (["decision.created", "intent.updated", "demo.reset", "metrics.dirty", "ledger.posted"].includes(e.type)) loadMetrics();
    listeners.current.forEach((l) => l(e));
  });
  useEffect(() => { loadHealth(); refreshMode(); api.metrics().then(setMetrics).catch(() => undefined); }, [conn, loadHealth, refreshMode]);

  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("vigil-theme") ?? ""; } catch { return ""; }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("vigil-theme", theme); } catch { /* ignore */ }
  }, [theme]);

  const gwBad = health?.gateway?.status === "auth_failed";
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
            {NAV.map((n, i) => (
              <div key={n.to} style={{ display: "contents" }}>
                {n.group && <div className="side-group">{n.group}</div>}
                <NavLink to={n.to} end={n.end} title={n.label}>
                  <span className="idx">{String(i + 1).padStart(2, "0")}</span>
                  <span className="lbl">{n.label}</span>
                  {n.to === "/interventions" && open > 0 ? <span className="badge hot">{open}</span> : <span />}
                </NavLink>
              </div>
            ))}
          </nav>
          <div className="side-foot">
            <span>PRIMA architecture · prototype</span>
            <span>Synthetic data. Not connected to any regulator, payment network or bank system.</span>
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
              {gwBad && <span className="pill s-watch nodot" title={health?.gateway?.detail}>gateway keys rejected</span>}
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
    </ConsoleBus.Provider>
  );
}
