// The one status scale (FINAL_PARALLEL_PLAN §2). Colour encodes status ONLY.
import type { AccountStatus, DetectorFamily, IntentState, ValueKind } from "../api/types";

export type Status = "normal" | "watch" | "high" | "critical" | "held" | "fraud" | "unknown";

export const STATUS_LABEL: Record<Status, string> = {
  normal: "Normal",
  watch: "Watch",
  high: "High risk",
  critical: "Critical",
  held: "Held",
  fraud: "Confirmed fraud",
  unknown: "Unknown",
};

/** Hex values used where CSS variables are unavailable (WebGL). Mirror of tokens.css. */
export const STATUS_HEX: Record<Status, string> = {
  normal: "#5b9bff",
  watch: "#ffbc4d",
  high: "#ff9157",
  critical: "#ff647f",
  held: "#a68bff",
  fraud: "#e8264f",
  unknown: "#6d8a7b",
};

/** Tier → status. T3 is a scoped hold: its *risk* level is HIGH; the HELD state is shown separately. */
export function tierStatus(tier: number | null | undefined): Status {
  if (tier === null || tier === undefined) return "unknown";
  if (tier <= 0) return "normal";
  if (tier === 1) return "watch";
  if (tier <= 3) return "high";
  return "critical";
}

/** 0..1 score → status (normal < 0.30 ≤ watch < 0.50 ≤ high < 0.75 ≤ critical). */
export function scoreStatus(score: number | null | undefined): Status {
  if (score === null || score === undefined || Number.isNaN(score)) return "unknown";
  if (score >= 0.75) return "critical";
  if (score >= 0.5) return "high";
  if (score >= 0.3) return "watch";
  return "normal";
}

export function levelStatus(level: string | null | undefined): Status {
  const l = (level ?? "").toUpperCase();
  if (l === "HIGH") return "high";
  if (l === "MEDIUM") return "watch";
  if (l === "LOW") return "normal";
  return "unknown";
}

export function stateStatus(state: IntentState | string | null | undefined): Status {
  switch (state) {
    case "HELD":
    case "ESCALATED":
      return "held";
    case "REJECTED":
      return "critical";
    case "CHALLENGED":
      return "watch";
    case "APPROVED":
    case "PAYMENT_SUCCEEDED":
    case "MONITORED":
      return "normal";
    default:
      return "unknown";
  }
}

export const TIER_SHORT: Record<number, string> = {
  0: "T0 · Pass",
  1: "T1 · Inform",
  2: "T2 · Confirm",
  3: "T3 · Scoped hold",
  4: "T4 · Hold + CircuitBreaker",
};

/** Neutral identifiers for detector families — glyph + label, never a competing hue. */
export const FAMILY: Record<DetectorFamily, { glyph: string; label: string }> = {
  rules: { glyph: "RUL", label: "Rule engine" },
  random_forest: { glyph: "RF", label: "Random Forest" },
  gnn: { glyph: "GNN", label: "Graph neural net" },
  drift: { glyph: "DRF", label: "Behavioural drift" },
  early_warning: { glyph: "EW", label: "Early warning" },
  pattern_memory: { glyph: "PM", label: "Pattern memory" },
  ringwatch: { glyph: "RW", label: "RingWatch" },
  trailscore: { glyph: "TS", label: "TrailScore" },
  context: { glyph: "CTX", label: "Context" },
  external: { glyph: "EXT", label: "External intel" },
};

export const DIM_GLYPH: Record<string, string> = {
  external: "EXT",
  network: "RW",
  sequence: "TS",
  behaviour: "BEH",
  context: "CTX",
};

/** Honest naming of what a value is. Never call a score a probability. */
export const KIND_LABEL: Record<ValueKind, string> = {
  score: "score",
  probability_uncalibrated: "uncalibrated probability",
  probability_calibrated: "calibrated probability (synthetic worlds)",
  level: "level",
  similarity: "similarity",
  count: "count",
};

export const ROLE_LABEL: Record<string, string> = {
  coordinator: "Coordinator",
  collector: "Collector",
  distributor: "Distributor",
  entry: "Entry",
  exit: "Exit",
  unclassified: "Unclassified",
  source: "Source",
  "pass-through": "Pass-through mule",
  "cash-out": "Cash-out (exit)",
  suspected: "Suspected mule",
  normal: "Account",
  victim: "Victim",
};

// ── v3 live account status (universe, streams). Precedence (contract):
//    confirmed_fraud > held > flagged > early_warning > new > normal > idle.

export const ACCOUNT_STATUS_LABEL: Record<AccountStatus, string> = {
  normal: "Normal",
  idle: "Idle",
  new: "New account",
  early_warning: "Early warning",
  flagged: "Flagged",
  held: "Held",
  confirmed_fraud: "Confirmed fraud",
  external: "External",
};

/** WebGL / canvas colours for live account status (mirror of --as-* in tokens.css). */
export const ACCOUNT_STATUS_HEX: Record<AccountStatus, string> = {
  normal: "#2f7dff",
  idle: "#1f4a8f",
  new: "#22ff99",
  early_warning: "#ffc34d",
  flagged: "#ff3d63",
  held: "#9b7bff",
  confirmed_fraud: "#c8102e",
  external: "#5d6b67",
};

export const ACCOUNT_STATUS_RANK: Record<AccountStatus, number> = {
  idle: 0, external: 0, normal: 1, new: 2, early_warning: 3, flagged: 4, held: 5, confirmed_fraud: 6,
};

/** Live status → risk status scale (for pills that use the decision scale). */
export function accountStatusToStatus(s: AccountStatus | null | undefined): Status {
  switch (s) {
    case "confirmed_fraud": return "fraud";
    case "held": return "held";
    case "flagged": return "critical";
    case "early_warning": return "watch";
    case "normal": case "new": case "idle": return "normal";
    default: return "unknown";
  }
}

export const isAlarm = (s: AccountStatus | null | undefined) =>
  s === "flagged" || s === "held" || s === "confirmed_fraud";
export const isRisky = (s: AccountStatus | null | undefined) => s === "early_warning" || isAlarm(s);
