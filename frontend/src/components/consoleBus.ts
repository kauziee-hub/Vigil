// The console push channel as a React context: ONE WebSocket for the bank-side app (opened by the Shell), fanned out to
// every subscriber. Kept in its own module so components that the Shell itself renders (Vigilance) can subscribe
// without an import cycle. `Shell` re-exports these for existing imports.
import { createContext, useContext, useEffect, useRef } from "react";
import type { ConnState } from "../api/realtime";
import type { Health, Metrics, ModeView, SystemHealth, WsEnvelope } from "../api/types";

export type Listener = (e: WsEnvelope<any>) => void; // eslint-disable-line @typescript-eslint/no-explicit-any
export interface Platform {
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
export const ConsoleBus = createContext<Platform>({
  subscribe: () => () => undefined, conn: "connecting", health: null, system: null, metrics: null, mode: null,
  modeAvailable: null, intelAvailable: null, refreshMode: () => undefined,
});

/** Subscribe to the console WebSocket (push-only, no polling). */
export function useConsoleEvents(listener: Listener) {
  const bus = useContext(ConsoleBus);
  const ref = useRef(listener);
  ref.current = listener;
  useEffect(() => bus.subscribe((e) => ref.current(e)), [bus]);
}

export function usePlatform() {
  return useContext(ConsoleBus);
}
