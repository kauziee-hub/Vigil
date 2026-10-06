import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { api } from "../api/client";
import { useRealtime } from "../api/realtime";
import type { Health, WsEnvelope } from "../api/types";

type Listener = (e: WsEnvelope<any>) => void;
const ConsoleBus = createContext<{ subscribe: (l: Listener) => () => void; conn: string }>({
  subscribe: () => () => undefined, conn: "connecting",
});

/** One console WebSocket for the whole bank-side app; pages subscribe to it. */
export function useConsoleEvents(listener: Listener) {
  const bus = useContext(ConsoleBus);
  const ref = useRef(listener);
  ref.current = listener;
  useEffect(() => bus.subscribe((e) => ref.current(e)), [bus]);
}

export function Shell({ children }: { children: ReactNode }) {
  const listeners = useRef(new Set<Listener>());
  const [health, setHealth] = useState<Health | null>(null);
  const subscribe = useCallback((l: Listener) => {
    listeners.current.add(l);
    return () => { listeners.current.delete(l); };
  }, []);
  const conn = useRealtime(["console"], (e) => {
    if (e.type === "ambient.changed" || e.type === "demo.reset") api.health().then(setHealth).catch(() => undefined);
    listeners.current.forEach((l) => l(e));
  });
  useEffect(() => { api.health().then(setHealth).catch(() => undefined); }, [conn]);
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("vigil-theme") ?? ""; } catch { return ""; }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try { localStorage.setItem("vigil-theme", theme); } catch { /* ignore */ }
  }, [theme]);

  return (
    <ConsoleBus.Provider value={{ subscribe, conn }}>
      <div className="shell">
        <header className="topbar">
          <NavLink to="/" className="brand" style={{ textDecoration: "none" }}>
            <span className="brand-mark">V</span>
            <span>Vigil <small>· PRIMA pre-commit engine</small></span>
          </NavLink>
          <nav className="nav">
            <NavLink to="/" end>Command center</NavLink>
            <NavLink to="/pay">Pay</NavLink>
            <NavLink to="/investigate">Investigate</NavLink>
            <NavLink to="/network">Network</NavLink>
            <NavLink to="/about">Where it sits</NavLink>
          </nav>
          <div className="topbar-right small">
            {health && (
              <span className={`chip ${health.gateway?.status === "auth_failed" ? "t1" : ""}`} title={health.payment_provider_label}>
                {health.payment_provider === "razorpay_test" ? "Razorpay TEST" : "Mock payments"}
                {health.gateway?.status === "auth_failed" ? " · keys rejected" : ""}
              </span>
            )}
            <span className="row" title="Realtime connection"><span className={`dot ${conn === "open" ? "ok" : conn === "connecting" ? "warn" : "bad"}`} />live</span>
            <button className="btn ghost sm" aria-label="Toggle colour theme"
                    onClick={() => setTheme(theme === "dark" ? "light" : theme === "light" ? "" : "dark")}>
              {theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"}
            </button>
          </div>
        </header>
        <main className="page">{children}</main>
      </div>
    </ConsoleBus.Provider>
  );
}
