// Overview shared state: ONE selection + the global filters, shared by the KPI strip, money map (flat + globe),
// live tape, live network, needs attention and Vigilance. Selecting anywhere highlights everywhere.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { Incident, Window } from "../api/v10";
import { useVigilance, type VigilanceOpen, type VigilanceReq } from "./vigilance";

export type SelKind = "tx" | "account" | "city" | "cluster" | "incident";
export interface Selection {
  kind: SelKind;
  id: string;
  /** optional context: accounts involved (for the 3D focus / tape filter), coordinates, label */
  accounts?: string[];
  lat?: number | null;
  lng?: number | null;
  peer?: { lat: number | null; lng: number | null } | null;
  label?: string;
}
export type TapeOnly = "all" | "suspicious" | "fraud";

interface Ctx {
  selected: Selection | null;
  select: (s: Selection | null) => void;
  window: Window;
  setWindow: (w: Window) => void;
  channel: string;
  setChannel: (c: string) => void;
  tapeOnly: TapeOnly;
  setTapeOnly: (o: TapeOnly) => void;
  incident: Incident | null;           // incident mode: the whole page focuses on it
  setIncident: (i: Incident | null) => void;
  /** Vigilance dock: open on a case (incidentId), with a question (prompt, optionally about an incident), or plain */
  vigilance: VigilanceReq;
  openVigilance: (o: VigilanceOpen) => void;
  closeVigilance: () => void;
}

const SelectionCtx = createContext<Ctx | null>(null);

function stored<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<Selection | null>(null);
  const [window, setWindowState] = useState<Window>(() => stored("vigil.ov.window", "1h", ["15m", "1h", "24h", "7d"] as const));
  const [channel, setChannel] = useState("all");
  const [tapeOnly, setTapeOnly] = useState<TapeOnly>("all");
  const [incident, setIncident] = useState<Incident | null>(null);
  const { vigilance, openVigilance, closeVigilance } = useVigilance();     // the dock is global (lib/vigilance)
  const setWindow = useCallback((w: Window) => {
    setWindowState(w);
    try { localStorage.setItem("vigil.ov.window", w); } catch { /* private mode */ }
  }, []);
  const value = useMemo<Ctx>(() => ({
    selected, select: setSelected, window, setWindow, channel, setChannel, tapeOnly, setTapeOnly, incident, setIncident,
    vigilance, openVigilance, closeVigilance,
  }), [selected, window, setWindow, channel, tapeOnly, incident, vigilance, openVigilance, closeVigilance]);
  return <SelectionCtx.Provider value={value}>{children}</SelectionCtx.Provider>;
}

export function useSelection(): Ctx {
  const c = useContext(SelectionCtx);
  if (!c) throw new Error("useSelection outside SelectionProvider");
  return c;
}

/** Accounts a selection refers to (for highlighting in the 3D network and filtering lists). */
export function selectionAccounts(s: Selection | null): string[] {
  if (!s) return [];
  if (s.kind === "account") return [s.id];
  return s.accounts ?? [];
}
