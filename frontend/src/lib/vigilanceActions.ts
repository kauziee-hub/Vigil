// Executes Vigilance's PROPOSED UI actions (procedure steps, assessment buttons). Only the whitelisted,
// navigation/selection-only actions below exist; anything else is ignored (and logged). `watch_account` is a proposal:
// the analyst confirms it in a dialog and the existing watchlist API is called by the human's click — Vigilance itself
// never changes state.
import type { UiAction } from "../api/v10";
import type { Selection, TapeOnly } from "./selection";

export const ALLOWED_ACTIONS = ["select_entity", "open_page", "show_on_map", "show_in_network", "open_connections",
  "filter_tape", "watch_account"] as const;
const PAGES = new Set(["/", "/detection", "/network", "/investigations", "/interventions", "/governance", "/guard"]);
const PAGE_PATTERNS = [/^\/investigations\/account\/[^/]+$/, /^\/investigations\/decision\/[A-Za-z0-9_-]+$/];

export const ACTION_LABEL: Record<(typeof ALLOWED_ACTIONS)[number], string> = {
  select_entity: "Select", open_page: "Open", show_on_map: "Show on map", show_in_network: "Show in network",
  open_connections: "Trace the money", filter_tape: "Filter tape", watch_account: "Watch (confirm)",
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

/** Actions that show something on the Overview (map, network, tape, a posting's connections). */
export function needsOverview(a: UiAction): boolean {
  if (a.type === "select_entity") return /^TX-\d+$/i.test((a.target || "").trim());
  return a.type === "show_on_map" || a.type === "show_in_network" || a.type === "open_connections" || a.type === "filter_tape";
}

/** A short button label for an action ("Show in network", "Open case", "Watch kiran.traders"). */
export function actionLabel(a: UiAction): string {
  const t = (a.target || "").replace("@vigil", "");
  if (a.type === "open_page") {
    if (a.target.startsWith("/investigations/decision/")) return "Open the case";
    if (a.target.startsWith("/investigations/account/")) return "Open the account";
    if (a.target === "/interventions") return "Open Interventions";
    return "Open page";
  }
  if (a.type === "watch_account") return `Watch ${t}`;
  if (a.type === "show_on_map") return a.target.includes("@") || !t ? "Show on the map" : `Show ${t} on the map`;
  return ACTION_LABEL[a.type as keyof typeof ACTION_LABEL];
}

/** Returns true if the action was executed. */
export function runAction(a: UiAction | null | undefined, d: ActionDeps): boolean {
  if (!isAllowed(a)) {
    if (a) console.warn("Vigilance proposed an action outside the whitelist; ignored:", (a as UiAction).type);
    return false;
  }
  const t = (a.target || "").trim();
  switch (a.type) {
    case "select_entity":
      if (/^TX-\d+$/i.test(t)) { d.openConnections(t.toUpperCase()); return true; }
      if (t) { d.select({ kind: "account", id: t }); return true; }
      return false;
    case "open_page":
      if (PAGES.has(t) || PAGE_PATTERNS.some((p) => p.test(t))) { d.navigate(t); return true; }
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
