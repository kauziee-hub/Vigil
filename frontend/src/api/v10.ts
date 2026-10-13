// Overview v10 + Vigilance API (v11; the URL prefix stays /api/copilot): types and calls. Same-origin like
// api/client.ts; every location is SIMULATED and comes with a basis + accuracy label; Vigilance is read-only.
import type { AccountStatus } from "./types";

export type Window = "15m" | "1h" | "24h" | "7d";
export type Rail = "upi" | "imps" | "neft" | "rtgs" | "card" | "atm" | "wallet" | "intl_wire";
export type Risk = "normal" | "suspicious" | "fraud";
export type Severity = "critical" | "high" | "medium" | "low";

export const RAIL_LABEL: Record<Rail, string> = {
  upi: "UPI", imps: "IMPS", neft: "NEFT", rtgs: "RTGS", card: "Card", atm: "ATM", wallet: "Wallet", intl_wire: "Intl wire",
};
export const RAILS = Object.keys(RAIL_LABEL) as Rail[];

export interface KpiTile {
  key: "moved" | "fraud" | "at_risk" | "stopped" | "left" | "new"; label: string; value: number; previous: number | null;
  delta: number | null; unit: "paise" | "count"; how: string; spark: number[] | null; tone: "bad" | "ok" | "warn" | null;
}
export interface Kpis { window: Window; channel: string; generated_ts: string; tiles: KpiTile[]; scope?: string[] }

export interface MapCity {
  city: string; lat: number; lng: number; state?: string; kind?: "domestic" | "foreign"; tx_count: number;
  value_paise: number; fraud_linked_paise: number; suspicious_count: number; at_risk_accounts: number;
}
export interface MapFlow {
  from_city: string; to_city: string; from_lat: number; from_lng: number; to_lat: number; to_lng: number;
  tx_count: number; value_paise: number; risk: Risk; rails: Record<string, number>;
}
export interface MapAtm { terminal_id: string; city: string; lat: number; lng: number; bank: string; site: string;
  withdrawals: number; value_paise: number; risk_value_paise: number }
export interface MapCluster {
  id: string; kind: "cash_out" | "collection"; center: { lat: number; lng: number } | null; radius_km: number;
  accounts: string[]; value_paise: number; city: string | null; first_ts?: string; last_ts?: string; tx_ids?: string[];
  senders?: number; account?: string; status?: AccountStatus; rule?: string;
}
export interface StateFlow {
  from_state: string; to_state: string; tx_count: number; value_paise: number; fraud_linked_paise: number;
  suspicious_paise: number; accounts: number; risky_accounts: number; risk: Risk;
  top_pair: { from_city: string; to_city: string; from_lat: number; from_lng: number; to_lat: number; to_lng: number };
}
export interface GeoMap {
  window: Window; channel: string; generated_ts: string; synthetic: true; cities: MapCity[]; flows: MapFlow[];
  state_flows?: StateFlow[];
  atm: MapAtm[]; clusters: MapCluster[]; totals: { postings: number; value_paise: number };
}

// ── v12 location intelligence (GET /api/geo/intel) — simulated locations, corroborating evidence only ──
export interface GeoPoint { tx_id: string; ts: string; city: string; lat: number; lng: number; basis: string; acc_m: number; label: string }
export type LocRule = "LOC_IMPOSSIBLE_TRAVEL" | "LOC_UNUSUAL_REGION" | "LOC_MULTI_CITY_BURST";
export interface LocFinding {
  rule: LocRule; account: string; name?: string; status?: AccountStatus; confidence: "high" | "low"; reason: string;
  tx_ids: string[]; ts: string; points: GeoPoint[];
  from_city?: string; to_city?: string; km?: number; effective_km?: number; minutes?: number; kmh?: number; speed_text?: string; threshold_kmh?: number;
  city?: string; home_city?: string | null; home_km?: number | null; nearest_baseline_km?: number; baseline_cities?: string[];
  baseline_points?: number; cities?: string[]; threshold?: string; observed?: string;
}
export interface CashOutCluster extends MapCluster {
  atms: { terminal_id: string; bank: string; site: string; lat: number; lng: number }[]; atm_count: number; minutes: number;
  withdrawals: { tx_id: string; ts: string; account: string; amount_paise: number; lat: number; lng: number }[];
  account_names: string[]; basis: string;
}
export interface LocAnomaly { account: string; name: string; status: AccountStatus; score: number; corroborates: boolean;
  contributed: boolean; rules: LocFinding[] }
export interface LocSelectedAccount {
  kind: "account"; account: string; name: string; status: AccountStatus; home_city: string | null;
  home: { lat: number; lng: number } | null; usual_cities: string[]; baseline_points: number; has_baseline: boolean;
  route: GeoPoint[]; evidence: { rules: LocFinding[]; score: number; corroborates: boolean } | null;
  verdict: "normal" | "suspicious" | "unconfirmed"; travel: LocFinding[];
}
export interface LocSelectedCity {
  kind: "city"; city: string; accounts_here: number; precise_here: number;
  risky_accounts: { account: string; name: string; status: AccountStatus; postings: number; value_paise: number }[];
  atm_withdrawals: number; atm_value_paise: number; atm_risky: number; atm_risky_value_paise: number;
  travel: LocFinding[]; clusters: string[]; newcomers: { account: string; name: string; home_city: string | null }[];
}
export interface GeoIntel {
  generated_ts: string; since: string; policy_version: string; synthetic: true; corroboration_enabled: boolean;
  thresholds: { impossible_travel_kmh: number; min_km: number; unusual_region_min_km: number; multi_city: string;
    cash_out: { cash_out_min_withdrawals: number; cash_out_radius_km: number; cash_out_window_min: number } };
  impossible_travel: LocFinding[]; low_confidence: LocFinding[]; cash_out: CashOutCluster[]; anomalies: LocAnomaly[];
  normal: { located_postings: number; precise_postings: number; coarse_postings: number; accounts: number; cities: number;
    moves_checked: number; fastest_normal_kmh: number | null; accounts_with_signals: number };
  selected?: LocSelectedAccount | LocSelectedCity | ({ kind: "cluster" } & Omit<CashOutCluster, "kind">);
}

export interface TxGeo { city: string | null; lat: number | null; lng: number | null; basis: string | null;
  accuracy_m: number | null; label: string; peer_city: string | null; peer_lat: number | null; peer_lng: number | null }
export interface TapeRow {
  tx_id: string; seq: number; ts: string; kind: string; sender_id: string; sender_name: string; recipient_id: string;
  recipient_name: string; amount_paise: number; rail: Rail; origin: string; sender_status: AccountStatus;
  recipient_status: AccountStatus; risk: Risk; tier: number | null; geo: TxGeo;
}
export interface Hop { from: string; to: string; account: string; name: string; amount_paise: number; ts: string;
  tx_id: string; hops: number; status: AccountStatus; count?: number }
export interface AccountCard { id: string; name: string; status: AccountStatus; risk: number | null;
  model_risk: number | null; role: string | null; reason: string | null; home_city: string | null }
export interface Ring { id: string; kind: string; members: string[]; size: number; value_paise: number; flagged: number;
  rules: string[]; roles: Record<string, number>; city: string | null }
export interface Connections {
  tx: TapeRow; sender: AccountCard; recipient: AccountCard; upstream: Hop[]; downstream: Hop[];
  shared_device: AccountCard[]; same_ring: Ring | null; linked_by: string[]; common_payees: string[];
  geo_path: { city: string; lat: number; lng: number; account: string }[];
}
export interface PipelineAccount {
  id: string; name: string; age_days: number; opened_at: string; opened_via: string | null; opened_city: string | null;
  stage: Stage; suspicious_path: boolean; in_paise: number; out_paise: number; retention_pct: number | null;
  forwarded_pct: number; exited_via: string[]; device_shared_with: string[]; shared_note: string | null;
  status: AccountStatus; first_credit_ts: string | null; first_debit_ts: string | null;
}
export type Stage = "opened" | "funded" | "active" | "passing_through" | "exited";
export interface Pipeline { days: number; rule: string; suspicious: number;
  stages: { key: Stage; label: string; count: number; value_paise: number }[]; accounts: PipelineAccount[] }
export interface ChannelMix { window: Window; total_paise: number; fraud_total_paise: number;
  rails: { rail: Rail; label: string; count: number; value_paise: number; fraud_linked_paise: number; share_value: number; share_fraud: number }[] }
export interface Brief { window: Window; lines: string[]; generated_ts: string; llm_used: boolean }
export interface AttentionRow {
  id: string; name: string; status: AccountStatus; reason: string | null; role: string | null; since: string | null;
  families_flagging: number; risk: number; model_risk: number | null; in_paise_24h: number; out_paise_24h: number;
  ring_id: string | null; collection_point: boolean; home_city: string | null;
}

export interface Incident {
  id: string; kind: string; kind_label: string; severity: Severity; score: number; status: string; title: string;
  /** v11: what it is (e.g. "Mule ring forming"), the fraud typology, and the respond-within target */
  classification: string; typology: string; respond_within: string; respond_minutes: number;
  /** v11: who / where (chip) and one plain sentence with the numbers (what Vigilance says when it raises it) */
  subject: string; situation: string; contained: boolean;
  procedure: { done: number; total: number; next: string | null } | null;
  entities: string[]; tx_ids: string[]; value_paise: number | null; facts: string[]; score_parts: Record<string, number>;
  engine: string; city: string | null; created_ts: string; updated_ts: string; version: number; llm_used: boolean;
}
export interface UiAction { type: string; target: string }
export interface ProcedureStep {
  id: string; phase: "contain" | "investigate" | "report" | "close"; title: string; detail: string; owner: string;
  when: string; kind: "inside" | "outside"; outside: string | null; ui_action: UiAction | null; acknowledge: boolean;
  auto_rule: string | null; done: boolean; done_by: string | null; evidence: string | null;
}
export interface Procedure {
  incident_id: string; classification: string; typology: string; severity: Severity; respond_within: string;
  respond_minutes: number; phases: { id: ProcedureStep["phase"]; label: string; goal: string }[]; steps: ProcedureStep[];
  done: number; total: number; next_step: string | null; note: string;
}
/** The assessment: narrative (Gemini or template) + deterministic parts rebuilt from live data. */
export interface IncidentBrief {
  headline: string; summary: string; red_flags: string[]; risk_if_ignored: string; recommendation: string;
  confidence: { level: "high" | "medium" | "low"; reason: string };
  classification: string; typology: string; situation: string; respond_within: string; respond_minutes: number;
  severity: { level: Severity; score: number; parts: Record<string, number>; reason: string };
  key_facts: { label: string; value: string }[];
  next_step: Pick<ProcedureStep, "id" | "phase" | "title" | "detail" | "owner" | "when" | "kind" | "outside" | "ui_action"> | null;
  procedure: { done: number; total: number };
  evidence: { label: string; ref: { kind: "account" | "tx" | "city" | "cluster"; id: string } }[];
  llm_used: boolean; raised_by?: string; pending_ai?: boolean;
}
export interface CopilotStatus {
  enabled: boolean; llm_available: boolean; configured: boolean; model_fast: string; model_deep: string;
  tokens_left_today: number; mode: string; note: string; open_incidents: number;
}
export interface ToolCall { name: string; args: Record<string, unknown>; summary?: string }
export interface ThreadMessage { id: string; role: "user" | "assistant"; content: string; tool_calls: ToolCall[]; ts: string }
export interface Thread { id: string; incident_id: string | null; title: string; created_ts: string; messages: ThreadMessage[] }

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}
async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json() as Promise<T>;
}
const qs = (o: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => [k, String(v)])).toString();

export const v10 = {
  kpis: (window: Window, channel: string, accounts?: string[]) =>
    get<Kpis>(`/api/overview/kpis?${qs({ window, channel, accounts: accounts?.join(",") })}`),
  map: (window: Window, channel: string) => get<GeoMap>(`/api/geo/map?${qs({ window, channel })}`),
  geoIntel: (window: Window, sel: { account?: string; city?: string; cluster?: string } = {}) =>
    get<GeoIntel>(`/api/geo/intel?${qs({ window, ...sel })}`),
  tape: (o: { limit?: number; since_id?: string; channel?: string; only?: string; q?: string; accounts?: string[] }) =>
    get<{ rows: TapeRow[] }>(`/api/tx/tape?${qs({ ...o, accounts: o.accounts?.join(",") })}`),
  connections: (txId: string) => get<Connections>(`/api/tx/${encodeURIComponent(txId)}/connections`),
  pipeline: (days = 60) => get<Pipeline>(`/api/overview/pipeline?days=${days}`),
  channels: (window: Window) => get<ChannelMix>(`/api/overview/channels?window=${window}`),
  brief: (window: Window) => get<Brief>(`/api/overview/brief?window=${window}`),
  attention: () => get<{ accounts: AttentionRow[]; rings: Ring[]; collection_points: MapCluster[] }>("/api/overview/attention"),

  copilotStatus: () => get<CopilotStatus>("/api/copilot/status"),
  incidents: (status = "open") => get<{ incidents: Incident[]; max_visible: number }>(`/api/copilot/incidents?status=${status}`),
  incidentBrief: (id: string, o: { fast?: boolean; deep?: boolean } = {}) =>
    post<{ brief: IncidentBrief; thread_id: string; incident: Incident }>(`/api/copilot/incidents/${id}/brief`, o),
  incidentAction: (id: string, action: "ack" | "dismiss" | "reopen") => post<Incident>(`/api/copilot/incidents/${id}/${action}`),
  procedure: (id: string) => get<Procedure>(`/api/copilot/incidents/${id}/procedure`),
  setStep: (id: string, step: string, done: boolean) =>
    post<Procedure>(`/api/copilot/incidents/${id}/procedure/${encodeURIComponent(step)}`, { done }),
  newThread: (incident_id?: string, title?: string) => post<Thread>("/api/copilot/threads", { incident_id, title }),
  thread: (id: string) => get<Thread>(`/api/copilot/threads/${id}`),
};

export type CopilotEvent =
  | { event: "token"; data: { text: string } }
  | { event: "tool_call"; data: { name: string; args: Record<string, unknown> } }
  | { event: "tool_result_summary"; data: { name: string; summary: string } }
  | { event: "done"; data: { message_id: string; llm_used: boolean; content: string } }
  | { event: "error"; data: { message: string } };

/** POST a chat message and read the Server-Sent Events stream (fetch + ReadableStream; no EventSource for POST). */
export async function streamMessage(threadId: string, content: string, onEvent: (e: CopilotEvent) => void,
                                    signal?: AbortSignal): Promise<void> {
  const res = await fetch(`/api/copilot/threads/${threadId}/messages`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }), signal,
  });
  if (!res.ok || !res.body) {
    let msg = `${res.status}`;
    try { msg = (await res.json())?.error?.message ?? msg; } catch { /* not json */ }
    onEvent({ event: "error", data: { message: msg } });
    return;
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const ev = /^event: (.+)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (ev && data) {
        try { onEvent({ event: ev, data: JSON.parse(data) } as CopilotEvent); } catch { /* malformed chunk */ }
      }
    }
  }
}
