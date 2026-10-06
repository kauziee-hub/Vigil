// Mirror of backend/vigil/contracts.py — the ONLY frontend copy of these shapes.
// Money: integer paise. Time: ISO-8601 UTC "Z". Scores: 0..1.

export type IntentState =
  | "CREATED" | "RISK_EVALUATED" | "APPROVED" | "CHALLENGED" | "HELD" | "ESCALATED"
  | "CANCELLED" | "REJECTED" | "PAYMENT_INITIATED" | "PAYMENT_SUCCEEDED" | "PAYMENT_FAILED" | "MONITORED";

export type Dimension = "external" | "network" | "sequence" | "behaviour" | "context";
export type InterventionKind = "pass" | "inform" | "confirm_purpose" | "scoped_hold" | "hold_and_circuit_breaker";

export interface RiskSignal {
  rule_id: string;
  dimension: Dimension;
  label: string;
  reason: string;
  evidence: Record<string, unknown>;
  contribution: number;
}

export interface DimensionScore {
  dimension: Dimension;
  score: number;
  weight: number;
  contribution: number;
  signals: RiskSignal[];
}

export interface PolicyAdjustment {
  rule_id: string;
  kind: "corroboration" | "floor" | "cap";
  effect: string;
  reason: string;
}

export interface Intervention {
  tier: number;
  kind: InterventionKind;
  title: string;
  customer_action: string;
  bank_action: string;
  hold_paise: number;
  circuit_breaker: boolean;
}

export interface CustomerReason {
  headline: string;
  summary: string;
  facts: string[];
  what_happens_next: string;
}

export interface AnalystReason {
  summary: string;
  top_dimensions: string[];
  signals: RiskSignal[];
  adjustments: PolicyAdjustment[];
  counterfactual: string;
  journey: JourneyItem[];
  external: ExternalIntel | null;
  network: Record<string, unknown>;
}

export interface ReasonLine {
  customer: CustomerReason;
  analyst: AnalystReason;
  audit: Record<string, unknown>;
}

export interface RiskDecision {
  decision_id: string;
  intent_id: string;
  sender_id: string;
  recipient_id: string;
  amount_paise: number;
  created_at: string;
  dimensions: DimensionScore[];
  base_score: number;
  adjustments: PolicyAdjustment[];
  final_score: number;
  tier: number;
  intervention: Intervention;
  rules_fired: string[];
  reasons: ReasonLine;
  policy_version: string;
  latency_ms: number;
  payload_sha256: string;
}

export interface PaymentInfo {
  provider: string;
  status: string;
  order_id: string | null;
  payment_id: string | null;
  key_id: string | null;
  amount_paise: number;
  label: string;
}

export interface Transition {
  from_state: string | null;
  to_state: string;
  actor: string;
  detail: string | null;
  ts: string;
}

export interface TransactionIntent {
  intent_id: string;
  sender_id: string;
  recipient_id: string;
  amount_paise: number;
  note: string | null;
  channel: string;
  device_id: string | null;
  source: "user" | "scenario" | "ambient";
  state: IntentState;
  tier: number | null;
  decision_id: string | null;
  purpose: string | null;
  hold_id: string | null;
  transaction_id: string | null;
  payment: PaymentInfo | null;
  created_at: string;
  updated_at: string;
  transitions: Transition[];
}

export interface IntentWithDecision {
  intent: TransactionIntent;
  decision: RiskDecision | null;
}

export interface ExternalIntel {
  identifier: string;
  status: "clean" | "watchlist" | "reported" | "confirmed_mule";
  risk_score: number;
  reason_codes: string[];
  source: string;
  last_updated: string;
  simulated: boolean;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: "customer" | "external" | "device";
  risk: number;
  flags: string[];
  role: string | null;
  balance_paise: number;
  labelled: boolean;
  attributable_paise: number;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  amount_paise: number;
  count: number;
  first_ts: string;
  last_ts: string;
  tainted_paise: number;
  tx_ids: string[];
  highlight: boolean;
}

export interface GraphEvidence {
  nodes: GraphNode[];
  edges: GraphEdge[];
  focus: string | null;
  truncated: boolean;
  total_nodes: number;
}

export interface ScenarioEvent {
  scenario_id: string;
  run_id: string;
  step: number;
  total_steps: number;
  kind: string;
  title: string;
  detail: string;
  ts: string;
  state: "idle" | "running" | "paused" | "done";
}

// ── read models (api/views.py) ──────────────────────────────────────────
export interface JourneyItem {
  kind?: string;
  event_id?: string;
  event_type: string;
  label: string;
  payload: Record<string, unknown>;
  ts: string;
  minutes_ago: number;
  source?: string;
}

export interface AccountSummary {
  id: string;
  display_name: string;
  kind: string;
  persona: string | null;
  opened_at: string;
  balance_paise: number;
  available_paise: number;
  held_paise: number;
  daily_limit_paise: number;
  primary_device: string | null;
  devices: string[];
  payees: { payee_id: string; display_name: string; payments: number }[];
  trusted_contact: { name: string; relation: string; phone_masked: string } | null;
  is_demo_customer: boolean;
}

export interface DecisionSummary {
  decision_id: string;
  intent_id: string;
  sender_id: string;
  recipient_id: string;
  amount_paise: number;
  tier: number;
  kind: InterventionKind;
  final_score: number;
  headline: string;
  labels: string[];
  latency_ms: number;
  created_at: string;
  source?: "user" | "scenario" | "ambient";
}

export interface Metrics {
  transactions_last_10m: number;
  transactions_total: number;
  decisions_total: number;
  decisions_by_tier: Record<string, number>;
  zero_friction_rate: number | null;
  pending_intents: number;
  open_interventions: number;
  held_paise: number;
  suspicious_accounts: number;
  suspicious_value_paise: number;
  attributable_paise: number;
  challenges: number;
  challenges_overturned: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  system_total_paise: number;
}

export interface Health {
  status: string;
  time: string;
  policy_version: string;
  payment_provider: "mock" | "razorpay_test";
  payment_provider_label: string;
  gateway: { status: string; detail: string };
  razorpay_key_id: string | null;
  external_intel_provider: string;
  ambient: boolean;
  ws_clients: number;
  seeded_at: string | null;
  graph_version: number;
  accounts: number;
  transactions: number;
  ml_on_decision_path: boolean;
}

export interface ScenarioStatus {
  id: string;
  name: string;
  act: string;
  summary: string;
  expected: string;
  payer: string | null;
  category?: "payment" | "attack" | "control";
  state: "idle" | "running" | "paused" | "done";
  step: number;
  total_steps: number;
  log: (ScenarioEvent & { result?: Record<string, unknown> | null })[];
}

export interface ScenarioExplain {
  id: string;
  name: string;
  act: string;
  summary: string;
  expected: string;
  explain: string[];
  decisions: { intent_id: string; decision_id: string; tier: number; state: string; final_score: number }[];
  time_compressed: boolean;
  simulated_inputs: boolean;
}

export interface RingRow {
  account_id: string;
  score: number;
  rules: string[];
  labels: string[];
  role: string | null;
  attributable_paise: number;
  total_in_paise: number;
  labelled: boolean;
}

export interface TaintRuleResult {
  origin_paise: number;
  attributable_total_paise: number;
  left_perimeter_paise: number;
  spent_paise: number;
  retagged_paise: number;
  extinguished_paise: number;
  coverage: number;
  claims: { account_id: string; amount_paise: number; rule: string; incident_id: string }[];
  steps: { journal_id: string; journal_seq: number; occurred_at: string; from_account: string; to_account: string;
           moved_paise: number; traced_paise: number; left_perimeter: boolean }[];
  digest: string;
  conserved: boolean;
}

export interface TaintIncident {
  label_id: string;
  transaction_id: string;
  source_account: string;
  first_recipient: string;
  origin_paise: number;
  grade: string;
  labelled_at: string;
  rules: { libr: TaintRuleResult; pro_rata: TaintRuleResult };
  hops: Record<string, number>;
}

export interface TaintView {
  incidents: TaintIncident[];
  exposure: { account_id: string; name: string; attributable_paise: number; hop: number | null }[];
  hops: Record<string, number>;
  computed_ms: number;
  through_seq: number | null;
  journals_considered?: number;
}

export interface Investigation {
  decision: RiskDecision;
  intent: TransactionIntent;
  sender: AccountSummary;
  recipient: AccountSummary;
  external_intel: ExternalIntel | null;
  graph: GraphEvidence;
  timeline: JourneyItem[];
  money_trace: TaintIncident[];
  hold: { id: string; held_paise: number; reference: string; opened_at: string; review_by: string;
          released_at: string | null; outcome: string | null } | null;
  circuit_breaker: { id: string; fired_at: string; response: string | null; responded_at: string | null;
                     payload: Record<string, unknown> }[];
}

export interface PolicyView {
  version: string;
  weights: Record<Dimension, number>;
  ladder: { tier: number; below: number; kind: InterventionKind; title: string }[];
  note: string;
}

export interface LedgerTx {
  id: string;
  seq: number;
  kind: string;
  sender_id: string;
  recipient_id: string;
  amount_paise: number;
  ts: string;
  note: string | null;
  source: string;
}

export interface ContactView {
  contact_name: string;
  relation: string;
  account_holder: string;
  alerts: ({ breaker_id: string; intent_id: string; fired_at: string; response: string | null;
             responded_at: string | null; headline: string; amount_paise: number; facts: string[];
             status: string; asks: string })[];
}

export interface WsEnvelope<T = unknown> {
  type: string;
  topic: string;
  ts: string;
  data: T;
}

// ══ v2 contracts (frozen 2026-10-06, mirror of backend/vigil/contracts.py) ══

export type ProvenanceStatus = "observed" | "computed" | "simulated" | "model_evidence" | "unavailable";
export interface Provenance {
  source: string;
  observed_at: string;
  freshness_s: number;
  version: string;
  status: ProvenanceStatus;
  confidence: string;
}
/** RiskSignal.provenance is optional: v1 records have none. */
export interface RiskSignalV2 extends RiskSignal { provenance?: Provenance | null }

export type DetectorFamily =
  | "rules" | "random_forest" | "gnn" | "drift" | "early_warning" | "pattern_memory"
  | "ringwatch" | "trailscore" | "context" | "external";
export type ValueKind = "score" | "probability_uncalibrated" | "probability_calibrated" | "level" | "similarity" | "count";

export interface DetectorResult {
  family: DetectorFamily;
  label: string;
  value: number | null;
  display: string;
  kind: ValueKind;
  flagged: boolean;
  status: "ok" | "unavailable" | "not_applicable";
  version: string;
  observed_at: string;
  detail: Record<string, unknown>;
}
export interface DetectorConsensus {
  families_flagging: number;
  families_evaluated: number;
  agreement: "none" | "weak" | "moderate" | "strong";
  summary: string;
}
export interface ShapContribution { feature: string; value: number; contribution: number; category: string }
export interface ShapExplanation {
  model_version: string;
  base_value: number;
  prediction: number;
  prediction_kind: ValueKind;
  top_positive: ShapContribution[];
  top_negative: ShapContribution[];
  categories: Record<string, number>;
}
export interface DriftFeature { feature: string; baseline: number; current: number; change: number }
export interface DriftReport {
  baseline_window: string;
  current_window: string;
  drift_score: number;
  level: "LOW" | "MEDIUM" | "HIGH";
  features: DriftFeature[];
}
export interface PatternMatch { signature_id: string; name: string; similarity: number; description: string; note: string }
export type MuleRole = "coordinator" | "collector" | "distributor" | "entry" | "exit" | "unclassified";
export interface RoleAssessment { role: MuleRole; reason: string; evidence: Record<string, unknown> }
export interface AccountIntel {
  account_id: string;
  as_of: string;
  graph_version: number;
  detectors: DetectorResult[];
  consensus: DetectorConsensus;
  shap: ShapExplanation | null;
  drift: DriftReport | null;
  role: RoleAssessment;
  patterns: PatternMatch[];
  features: Record<string, number>;
}
export interface ModelInfo {
  model_id: string;
  family: "random_forest" | "gnn" | "rules" | "drift" | "pattern_memory";
  version: string;
  trained_at: string | null;
  seed: number | null;
  data: string;
  split: string;
  metrics: Record<string, unknown>;
  per_attack: Record<string, unknown>;
  calibration: Record<string, unknown>;
  operational_use: string;
  status: "active" | "unavailable" | "retired";
}
export interface IntelScores {
  graph_version: number;
  scores: Record<string, { rules: number | null; rf: number | null; gnn: number | null; drift_level: string | null;
                           role: MuleRole | null; early_warning: boolean }>;
}
export interface ScenarioCompare {
  scenario_id: string;
  accounts: { account_id: string; seed_role: string | null; detectors: DetectorResult[]; consensus: DetectorConsensus }[];
}

export interface ReplayFrame {
  index: number;
  ts: string;
  kind: "event" | "evaluation" | "decision" | "action" | "outcome";
  label: string;
  detail: string;
  signals_added: string[];
  subscores: Record<Dimension, number>;
  final_score: number;
  tier: number;
}
export interface DecisionReplay { decision_id: string; intent_id: string; policy_version: string; frames: ReplayFrame[]; note: string }
export interface Counterfactual { id: string; label: string; changes: string[]; final_score: number; tier: number; tier_delta: number }
export interface BaselineDecision { decision: "approve" | "otp_step_up" | "decline"; reason: string }

/** RiskDecision v2 fields (optional on v1 records). */
export interface RiskDecisionV2 extends RiskDecision {
  mode?: "active" | "shadow";
  recommended_tier?: number | null;
  applied_tier?: number | null;
  baseline?: BaselineDecision | null;
  model_evidence?: DetectorResult[];
}

export interface DecisionRecord {
  decision: RiskDecisionV2;
  intent: TransactionIntent;
  provenance: { rule_id: string; dimension: Dimension; label: string; contribution: number; provenance: Provenance }[];
  model_versions: Record<string, string>;
  thresholds: PolicyView["ladder"];
  weights: Record<Dimension, number>;
  reason_codes: string[];
  operator_actions: Transition[];
  payment_result: PaymentInfo | null;
  ledger_transaction: LedgerTx | null;
}

export interface SceneNode {
  id: string; label: string; kind: "customer" | "external";
  x: number; y: number; z: number; layer: number;
  role: string | null; risk: number; taint_paise: number; labelled: boolean; victim: boolean; held: boolean;
  balance_paise: number; flags: string[];
}
export interface SceneTx { id: string; ts: string; amount_paise: number; channel: string }
export interface SceneEdge {
  id: string; source: string; target: string; amount_paise: number; count: number; first_ts: string; last_ts: string;
  tainted_paise: number; channels: string[]; txs: SceneTx[];
}
export interface GraphScene {
  version: string; layout: string; nodes: SceneNode[]; edges: SceneEdge[]; focus: string | null; cap: number;
  truncated: boolean; total_candidates: number; time_range: string[] | null; built_ms: number; cached: boolean;
}

export interface RiskPoint { ts: string; score: number; tier: number; label: string; reason: string; decision_id?: string | null }
export interface ModeView { mode: "active" | "shadow"; since: string | null; note: string }
export interface GovernanceSummary {
  mode: ModeView;
  policy: PolicyView;
  models: ModelInfo[];
  decisions_by_tier: Record<string, number>;
  shadow: { evaluated: number; vigil_would_intervene: number; baseline_would_challenge: number; agreement_rate: number | null };
  recent_actions: { intent_id: string; actor: string; to_state: string; detail: string | null; ts: string }[];
}
export interface SystemHealth extends Health {
  uptime_s: number;
  db_size_bytes: number;
  graph_nodes: number;
  graph_edges: number;
  cache: Record<string, unknown>;
  intel_available: boolean;
  latency_p95_ms: number | null;
}
export interface InterventionRow {
  intent_id: string;
  decision_id: string;
  sender_id: string;
  recipient_id: string;
  amount_paise: number;
  tier: number;
  kind: InterventionKind;
  state: IntentState;
  headline: string;
  opened_at: string;
  age_s: number;
  sla_due: string | null;               // review-by for holds
  hold: { id: string; held_paise: number; reference: string; outcome: string | null } | null;
  circuit_breaker: { id: string; contact: string; response: string | null; responded_at: string | null } | null;
  mode: "active" | "shadow";
}
export interface IntelOverview {
  graph_version: number;
  detector_agreement: Record<string, number>;   // family -> accounts flagged
  early_warnings: { account_id: string; score: number; signals: string[] }[];
  pattern_alerts: { account_id: string; match: PatternMatch }[];
  role_counts: Record<string, number>;
  models: ModelInfo[];
}
export interface ScenarioReplay {
  scenario_id: string;
  events: { ts: string; kind: string; title: string; tx_id: string | null; source: string | null; target: string | null;
            amount_paise: number | null }[];
}
