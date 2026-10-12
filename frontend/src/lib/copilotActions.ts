// Executes the Copilot's PROPOSED UI actions. Only the whitelisted, navigation/selection-only actions below exist;
// anything else is ignored (and logged). `watch_account` is a proposal: the analyst confirms it in a dialog and the
// existing watchlist API is called by the human's click — the Copilot itself never changes state.
import type { UiAction } from "../api/v10";
import type { Selection, TapeOnly } from "./selection";

export const ALLOWED_ACTIONS = ["select_entity", "open_page", "show_on_map", "show_in_network", "open_connections",
  "filter_tape", "watch_account"] as const;
const PAGES = new Set(["/", "/detection", "/network", "/investigations", "/interventions", "/governance", "/guard"]);

export const ACTION_LABEL: Record<(typeof ALLOWED_ACTIONS)[number], string> = {
  select_entity: "Select", open_page: "Open page", show_on_map: "Show on map", show_in_network: "Show in network",
  open_connections: "Open connections", filter_tape: "Filter tape", watch_account: "Watch (confirm)",
};

export interface ActionDeps {
  select: (s: Selection | null) => void;
  navigate: (to: string) => void;
  openConnections: (txId: string) => void;
  focusNetwork: (ids: string[]) => void;
  setTapeOnly: (o: TapeOnly) => void;
  confirmWatch: (accountId: string) => void;
  cityPoint: (city: string) => { lat: number; lng: number } | null;
}

export function isAllowed(a: UiAction | null | undefined): a is UiAction {
  return !!a && (ALLOWED_ACTIONS as readonly string[]).includes(a.type);
}

/** Returns true if the action was executed. */
export function runAction(a: UiAction | null | undefined, d: ActionDeps): boolean {
  if (!isAllowed(a)) {
    if (a) console.warn("Copilot proposed an action outside the whitelist; ignored:", (a as UiAction).type);
    return false;
  }
  const t = (a.target || "").trim();
  switch (a.type) {
    case "select_entity":
      if (/^TX-\d+$/i.test(t)) { d.openConnections(t.toUpperCase()); return true; }
      if (t) { d.select({ kind: "account", id: t }); return true; }
      return false;
    case "open_page":
      if (PAGES.has(t)) { d.navigate(t); return true; }
      if (/^\/investigations\/account\/[^/]+$/.test(t)) { d.navigate(t); return true; }
      return false;
    case "show_on_map": {
      const p = d.cityPoint(t);
      if (p) { d.select({ kind: "city", id: t, lat: p.lat, lng: p.lng, label: t }); return true; }
      if (t) { d.select({ kind: "account", id: t }); return true; }
      return false;
    }
    case "show_in_network":
      if (t) { d.focusNetwork(t.split(",").map((x) => x.trim()).filter(Boolean)); return true; }
      return false;
    case "open_connections":
      if (/^TX-\d+$/i.test(t)) { d.openConnections(t.toUpperCase()); return true; }
      return false;
    case "filter_tape":
      d.setTapeOnly(t === "fraud" || t === "suspicious" ? t : "all");
      return true;
    case "watch_account":
      if (t && t.includes("@")) { d.confirmWatch(t); return true; }
      return false;
  }
  return false;
}
