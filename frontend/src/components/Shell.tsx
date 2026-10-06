import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import { useRealtime, type ConnState } from "../api/realtime";
import type { Health, Metrics, ModeView, WsEnvelope } from "../api/types";
import { useDebounced } from "../lib/hooks";
import { Sim } from "./ui";

type Listener = (e: WsEnvelope<any>) => void;
interface Platform {
  subscribe: (l: Listener) => () => void;
  conn: ConnState;
  health: Health | null;
  mode: ModeView | null;
  modeAvailable: boolean | null;
  intelAvailable: boolean | null;
  refreshMode: () => void;
}
const ConsoleBus = createContext<Platform>({
  subscribe: () => () => undefined, conn: "connecting", health: null, mode: null, modeAvailable: null,
  intelAvailable: null, refreshMode: () => undefined,
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

export const NAV: { to: string; label: string; end?: boolean }[] = [
  { to: "/", label: "Overview", end: true },
  { to: "/guard", label: "Transaction Guard" },
  { to: "/network", label: "Network Intelligence" },
  { to: "/detection", label: "Detection & Models" },
  { to: "/investigations", label: "Investigations" },
  { to: "/interventions", label: "Interventions" },
  { to: "/governance", label: "Governance & Audit" },
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
    api.health().then(setHealth).catch(() => undefined);
    api.systemHealth()
      .then((h) => setIntelAvailable(h.intel_available))
      .catch(() => api.intelModels().then(() => setIntelAvailable(true)).catch(() => setIntelAvailable(false)));
  }, []);
  const refreshMode = useCallback(() => {
    api.mode().then((m) => { setMode(m); setModeAvailable(true); })
      .catch((e) => { setMode(null); setModeAvailable(e?.status === 404 ? false : null); });
  }, []);
  const loadMetrics = useDebounced(() => { api.metrics().then(setMetrics).catch(() => undefined); }, 1500);

  const conn = useRealtime(["console"], (e) => {
    if (e.type === "ambient.changed" || e.type === "demo.reset") loadHealth();
    if (e.type === "mode.changed") {
      const d = e.data as Partial<ModeView>;
      if (d && d.mode) setMode((m) => ({ since: null, note: "", ...m, ...d } as ModeView)); else refreshMode();
    }
    if (["decision.created", "intent.updated", "demo.reset", "metrics.dirty"].includes(e.type)) loadMetrics();
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

  return (
    <ConsoleBus.Provider value={{ subscribe, conn, health, mode, modeAvailable, intelAvailable, refreshMode }}>
      <div className="shell">
        <aside className="side" aria-label="Primary">
          <NavLink to="/" className="side-brand">
            <span className="mark">V</span>
            <span className="txt">
              <div className="name">VIGIL</div>
              <div className="sub">Financial intelligence · PRIMA</div>
            </span>
          </NavLink>
          <nav className="side-nav">
            {NAV.map((n, i) => (
              <div key={n.to} style={{ display: "contents" }}>
                {(i === 2 || i === 6) && <div className="side-sep" />}
                <NavLink to={n.to} end={n.end} title={n.label}>
                  <span className="idx">{String(i + 1).padStart(2, "0")}</span>
                  <span className="lbl">{n.label}</span>
                  {n.to === "/interventions" && open > 0 ? <span className="badge hot">{open}</span> : <span />}
                </NavLink>
              </div>
            ))}
          </nav>
          <div className="side-foot">
            <span>Prototype · synthetic data</span>
            <span>Not connected to any regulator, NPCI or bank system.</span>
          </div>
        </aside>
        <div className="main">
          <div className="strip" role="status" aria-label="Platform status">
            <div className="strip-item" title={mode?.note || "Operating mode"}>
              <span className="k">Mode</span>
              {mode ? <span className={`pill nodot ${mode.mode === "shadow" ? "s-watch" : "s-normal"}`}>{mode.mode === "shadow" ? "SHADOW" : "ACTIVE"}</span>
                : <span className="v muted">{modeAvailable === false ? "n/a" : "…"}</span>}
            </div>
            <div className="strip-item" title={health?.payment_provider_label}>
              <span className="k">Payments</span>
              <span className="v">{health ? (health.payment_provider === "razorpay_test" ? "Razorpay TEST" : "Mock") : "…"}</span>
              {gwBad && <span className="pill s-watch nodot">gateway keys rejected</span>}
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
            <div className="strip-item" title="Detection intelligence layer (RF / GNN / drift / pattern memory)">
              <span className="k">Intel</span>
              <span className={`dot ${intelAvailable ? "ok" : intelAvailable === false ? "" : "warn"}`} />
              <span className="v">{intelAvailable === null ? "…" : intelAvailable ? "available" : "unavailable"}</span>
            </div>
            <div className="strip-item" title={health?.external_intel_provider}>
              <span className="k">Ext. intel</span>
              <Sim />
            </div>
            <div className="strip-item">
              <span className="k">Stream</span>
              <span className="v">{health ? (health.ambient ? "on" : "off") : "…"}</span>
            </div>
            <div className="strip-item end">
              <Clock />
              <button aria-label="Toggle colour theme" title="Theme"
                      onClick={() => setTheme(theme === "light" ? "" : "light")}>{theme === "light" ? "◑" : "◐"}</button>
            </div>
          </div>
          <main className="page">{children}</main>
        </div>
      </div>
    </ConsoleBus.Provider>
  );
}
