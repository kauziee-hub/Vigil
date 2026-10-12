// Single HTTP client. Same-origin by default (FastAPI serves the built app),
// so no host is hard-coded anywhere in the frontend.
import type {
  AccountIntel, Counterfactual, DecisionRecord, DecisionReplay, GovernanceSummary, GraphScene, IntelScores,
  AttackRun, LiveStats, LiveUniverse,
  IntelOverview, InterventionRow, ModeView, ModelInfo, RiskPoint, ScenarioCompare, ScenarioReplay, SystemHealth,
  AccountSummary, ContactView, DecisionSummary, GraphEvidence, Health, IntentWithDecision, Investigation,
  LedgerTx, Metrics, PolicyView, RingRow, RiskDecision, ScenarioExplain, ScenarioStatus, TaintView,
  NewAccount, TransactionIntent, Watchlist,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) {
    super(message);
  }
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the Vigil server.");
  }
  const text = await res.text();
  const body = text ? JSON.parse(text) : {};
  if (!res.ok) {
    throw new ApiError(res.status, body?.error?.code ?? "http_error", body?.error?.message ?? res.statusText,
      body?.error?.details);
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? "{}" : JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  policy: () => request<PolicyView>("/api/policy"),
  metrics: () => request<Metrics>("/api/metrics"),
  reset: () => post<Record<string, unknown>>("/api/demo/reset"),
  ambient: (enabled: boolean) => post<{ enabled: boolean }>("/api/ambient", { enabled }),

  accounts: (role?: string, q?: string) =>
    request<{ id: string; display_name: string; kind: string; balance_paise: number; is_demo_customer: number;
              persona: string | null }[]>(`/api/accounts?${new URLSearchParams({ ...(role ? { role } : {}), ...(q ? { q } : {}) })}`),
  account: (id: string) => request<AccountSummary>(`/api/accounts/${encodeURIComponent(id)}`),
  accountNetwork: (id: string) =>
    request<{ account_id: string; score: number; signals: RiskDecision["dimensions"][number]["signals"];
              features: Record<string, unknown>; external_intel: unknown }>(`/api/accounts/${encodeURIComponent(id)}/network`),
  accountTransactions: (id: string) => request<LedgerTx[]>(`/api/accounts/${encodeURIComponent(id)}/transactions`),

  createIntent: (body: { sender_id: string; recipient_id: string; amount_paise: number; note?: string;
                         context_text?: string; device_id?: string; channel?: string }) =>
    post<IntentWithDecision>("/api/intents", { ...body, source: "user" }),
  intent: (id: string) => request<IntentWithDecision>(`/api/intents/${id}`),
  intents: (sender?: string) => request<TransactionIntent[]>(`/api/intents${sender ? `?sender_id=${encodeURIComponent(sender)}` : ""}`),
  acknowledge: (id: string, purpose?: string) => post<TransactionIntent>(`/api/intents/${id}/acknowledge`, { purpose }),
  cancel: (id: string) => post<TransactionIntent>(`/api/intents/${id}/cancel`),
  bankAction: (id: string, action: "release" | "reject", note?: string) =>
    post<TransactionIntent>(`/api/intents/${id}/bank-action`, { action, note }),
  pay: (id: string) => post<TransactionIntent>(`/api/intents/${id}/pay`),

  decisions: (minTier = 0) => request<DecisionSummary[]>(`/api/decisions?min_tier=${minTier}`),
  decision: (id: string) => request<RiskDecision>(`/api/decisions/${id}`),
  investigate: (id: string) => request<Investigation>(`/api/investigate/${id}`),

  graphSuspicious: () => request<GraphEvidence>("/api/graph/suspicious"),
  graphNeighbourhood: (id: string, hops = 1) =>
    request<GraphEvidence>(`/api/graph/neighborhood/${encodeURIComponent(id)}?hops=${hops}`),
  ringwatch: () => request<RingRow[]>("/api/ringwatch?min_score=0.3"),
  label: (transaction_id: string) => post<{ label_id: string; taint: TaintView }>("/api/labels", { transaction_id }),
  taint: () => request<TaintView>("/api/taint"),

  scenarios: () => request<ScenarioStatus[]>("/api/scenarios"),
  scenarioStart: (id: string) => post(`/api/scenarios/${id}/start`),
  scenarioPause: (id: string) => post(`/api/scenarios/${id}/pause`),
  scenarioResume: (id: string) => post(`/api/scenarios/${id}/resume`),
  scenarioReset: (id: string) => post(`/api/scenarios/${id}/reset`),
  scenarioExplain: (id: string) => request<ScenarioExplain>(`/api/scenarios/${id}/explain`),

  // ── v2: decision replay / counterfactuals / governance / mode / scene (Claude 1) ──
  replay: (decisionId: string) => request<DecisionReplay>(`/api/decisions/${decisionId}/replay`),
  counterfactuals: (decisionId: string) => request<Counterfactual[]>(`/api/decisions/${decisionId}/counterfactuals`),
  record: (decisionId: string) => request<DecisionRecord>(`/api/decisions/${decisionId}/record`),
  riskTimeline: (accountId: string) => request<RiskPoint[]>(`/api/accounts/${encodeURIComponent(accountId)}/risk-timeline`),
  mode: () => request<ModeView>("/api/mode"),
  setMode: (mode: "active" | "shadow") => post<ModeView>("/api/mode", { mode }),
  governance: () => request<GovernanceSummary>("/api/governance/summary"),
  systemHealth: () => request<SystemHealth>("/api/system/health"),
  scene: (p: { cap?: number; focus?: string; hops?: number; scenario?: string } = {}) =>
    request<GraphScene>(`/api/graph/scene?${new URLSearchParams(
      Object.entries(p).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))}`),
  scenarioReplay: (id: string) => request<ScenarioReplay>(`/api/scenarios/${id}/replay`),

  // ── v3: live platform (Claude 1) ──
  universe: (p: { window_minutes?: number; history?: number } = {}) =>
    request<LiveUniverse>(`/api/live/universe?${new URLSearchParams(
      Object.entries(p).filter(([, v]) => v !== undefined).map(([k, v]) => [k, String(v)]))}`),
  liveStats: () => request<LiveStats>("/api/live/stats"),
  newAccounts: (days = 30) => request<NewAccount[]>(`/api/live/new-accounts?days=${days}`),
  attackRuns: () => request<AttackRun[]>("/api/attacks/runs"),
  attackRun: (runId: string) => request<AttackRun>(`/api/attacks/runs/${runId}`),

  // ── v8: close monitoring (watchlist) ──
  watchlist: () => request<Watchlist>("/api/watchlist"),
  watch: (account_id: string, note?: string) =>
    post<{ account_id: string; note: string | null; added_at: string }>("/api/watchlist", { account_id, note }),
  unwatch: (account_id: string) =>
    request<{ account_id: string; removed: boolean }>(`/api/watchlist/${encodeURIComponent(account_id)}`, { method: "DELETE" }),

  // ── v2: detection intelligence (Claude 2, /api/intel/**) ──
  intelAccount: (accountId: string) => request<AccountIntel>(`/api/intel/accounts/${encodeURIComponent(accountId)}`),
  intelScores: () => request<IntelScores>("/api/intel/scores"),
  intelModels: () => request<ModelInfo[]>("/api/intel/models"),
  intelOverview: () => request<IntelOverview>("/api/intel/overview"),
  interventions: (status: "open" | "all" = "open", opts: { limit?: number; minTier?: number } = {}) =>
    request<InterventionRow[]>(`/api/interventions?status=${status}` + (opts.limit ? `&limit=${opts.limit}` : "")
      + (opts.minTier ? `&min_tier=${opts.minTier}` : "")),
  intelCompare: (scenarioId: string) => request<ScenarioCompare>(`/api/intel/scenarios/${scenarioId}/compare`),

  contact: (token: string) => request<ContactView>(`/api/contact/${encodeURIComponent(token)}`),
  contactRespond: (token: string, breaker_id: string, response: "acknowledged" | "calling_user" | "marked_expected") =>
    post<{ text: string }>(`/api/contact/${encodeURIComponent(token)}/respond`, { breaker_id, response }),
};

export function wsUrl(topics: string[]): string {
  const origin = BASE || window.location.origin;
  const url = new URL(`/ws?topics=${encodeURIComponent(topics.join(","))}`, origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
