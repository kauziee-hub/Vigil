// Signal map (GET /api/intel/signals): every signal inside the eight detector families, plus the supporting signals
// outside them (payment-time evidence, location intelligence). Read-only; counts are live; metrics only where a family
// was benchmarked on held-out synthetic worlds.

export type ValidationKind = "benchmarked" | "live_graded" | "lookup" | "supporting";
export interface SignalRow {
  id: string; label: string; checks: string; firing: number; hit: boolean | null; why: string | null;
  group?: string; feeds?: string; live_route?: number;
}
export interface SignalGroup {
  id: string; label: string; kind: string; purpose: string; role: string; feeds: string[];
  validation: { kind: ValidationKind; text: string; headline?: string };
  signals: SignalRow[]; signal_count: number; firing_signals: number;
  flagged_now?: number; account_flagged?: boolean | null; account_value?: string | null;
  inputs?: string; note?: string; window?: string; changed_status_now?: number;
  account_decision?: { decision_id: string; tier: number; score: number; as: "sender" | "recipient" } | null;
}
export interface SignalMap {
  as_of: string; synthetic: true;
  totals: { families: number; family_signals: number; supporting_signals: number; firing_now: number;
    accounts_scored: number; accounts_two_plus_families: number };
  families: SignalGroup[]; supporting: SignalGroup[];
  validation_legend: { kind: ValidationKind; label: string; text: string }[];
  top_accounts: { id: string; name: string; families: number }[];
  account?: { id: string; name: string; status: string | null; families_flagging: number | null; reason: string | null;
    location: { rules: string[]; score: number; changed_status: boolean } | null };
}

export async function fetchSignalMap(account?: string | null): Promise<SignalMap> {
  const q = account ? `?account=${encodeURIComponent(account)}` : "";
  const res = await fetch(`/api/intel/signals${q}`);
  if (!res.ok) throw new Error(`${res.status} /api/intel/signals`);
  return res.json() as Promise<SignalMap>;
}

export const VALIDATION_LABEL: Record<ValidationKind, string> = {
  benchmarked: "Benchmarked", live_graded: "Live-world only", lookup: "Lookup", supporting: "Supporting",
};
