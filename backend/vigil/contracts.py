"""Shared contracts. THE single source of truth for data shapes.

Frontend mirror: frontend/src/api/types.ts (keep in sync; contract test checks keys).
Money is integer paise. Time is ISO-8601 UTC 'Z' strings. Scores are 0..1.
Do not define these shapes anywhere else.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class IntentState(str, Enum):
    CREATED = "CREATED"
    RISK_EVALUATED = "RISK_EVALUATED"
    APPROVED = "APPROVED"
    CHALLENGED = "CHALLENGED"
    HELD = "HELD"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    PAYMENT_INITIATED = "PAYMENT_INITIATED"
    PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    MONITORED = "MONITORED"


Dimension = Literal["external", "network", "sequence", "behaviour", "context"]
DIMENSIONS: tuple[str, ...] = ("external", "network", "sequence", "behaviour", "context")

InterventionKind = Literal[
    "pass", "inform", "confirm_purpose", "scoped_hold", "hold_and_circuit_breaker"
]


ProvenanceStatus = Literal["observed", "computed", "simulated", "model_evidence", "unavailable"]


class Provenance(BaseModel):
    """Where a piece of evidence came from. Shown next to every material signal."""

    source: str                        # e.g. "PathGraph · RingWatch rules", "Simulated external registry"
    observed_at: str                   # ISO time the underlying fact was observed
    freshness_s: float                 # seconds between observed_at and the decision
    version: str                       # rule/model/policy version that produced it
    status: ProvenanceStatus
    confidence: str = "deterministic"  # "deterministic" | "uncalibrated model score" | "simulated input" | ...


class RiskSignal(BaseModel):
    """One fired rule. Never just `fraud = 1`."""

    rule_id: str
    dimension: Dimension
    label: str                         # short chip text, e.g. "Rapid pass-through"
    reason: str                        # one plain sentence, built from evidence
    evidence: dict[str, Any] = Field(default_factory=dict)  # raw values behind the reason
    contribution: float                # added to the dimension score (0..1)
    provenance: Optional[Provenance] = None  # filled by engine/decide.py


class DimensionScore(BaseModel):
    dimension: Dimension
    score: float
    weight: float
    contribution: float                # weight * score (sums to base_score)
    signals: list[RiskSignal] = Field(default_factory=list)


class PolicyAdjustment(BaseModel):
    rule_id: str
    kind: Literal["corroboration", "floor", "cap"]
    effect: str                        # e.g. "+0.08", "tier >= 3", "tier <= 1"
    reason: str


class Intervention(BaseModel):
    tier: int
    kind: InterventionKind
    title: str
    customer_action: str
    bank_action: str
    hold_paise: int = 0
    circuit_breaker: bool = False


class CustomerReason(BaseModel):
    headline: str
    summary: str                       # one sentence, e.g. "You're sending ₹45,000 to a recipient …"
    facts: list[str]
    what_happens_next: str


class AnalystReason(BaseModel):
    summary: str
    top_dimensions: list[str]
    signals: list[RiskSignal]
    adjustments: list[PolicyAdjustment]
    counterfactual: str
    journey: list[dict[str, Any]] = Field(default_factory=list)
    external: Optional[dict[str, Any]] = None
    network: dict[str, Any] = Field(default_factory=dict)


class ReasonLine(BaseModel):
    customer: CustomerReason
    analyst: AnalystReason
    audit: dict[str, Any]


class RiskDecision(BaseModel):
    decision_id: str
    intent_id: str
    sender_id: str
    recipient_id: str
    amount_paise: int
    created_at: str
    dimensions: list[DimensionScore]
    base_score: float
    adjustments: list[PolicyAdjustment]
    final_score: float
    tier: int
    intervention: Intervention
    rules_fired: list[str]
    reasons: ReasonLine
    policy_version: str
    latency_ms: float
    payload_sha256: str
    # v2 additions (optional so v1 records still parse)
    mode: Literal["active", "shadow"] = "active"
    recommended_tier: Optional[int] = None   # what Vigil recommends (== tier in active mode)
    applied_tier: Optional[int] = None       # what was actually applied (0 in shadow mode)
    baseline: Optional["BaselineDecision"] = None
    model_evidence: list["DetectorResult"] = Field(default_factory=list)  # corroborating only, never fused


class PaymentInfo(BaseModel):
    provider: str                      # mock (simulated payment rail)
    status: str                        # created | succeeded | failed
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    amount_paise: int
    label: str                         # "Simulated payment — no real money moved"


class Transition(BaseModel):
    from_state: Optional[str]
    to_state: str
    actor: str
    detail: Optional[str] = None
    ts: str


class TransactionIntent(BaseModel):
    intent_id: str
    sender_id: str
    recipient_id: str
    amount_paise: int
    note: Optional[str] = None
    channel: str = "upi"
    device_id: Optional[str] = None
    source: Literal["user", "scenario", "ambient"] = "user"
    state: IntentState
    tier: Optional[int] = None
    decision_id: Optional[str] = None
    purpose: Optional[str] = None
    hold_id: Optional[str] = None
    transaction_id: Optional[str] = None
    payment: Optional[PaymentInfo] = None
    created_at: str
    updated_at: str
    transitions: list[Transition] = Field(default_factory=list)


class CreateIntentRequest(BaseModel):
    sender_id: str
    recipient_id: str
    amount_paise: int = Field(gt=0)
    note: Optional[str] = None
    context_text: Optional[str] = Field(
        default=None,
        description="SIMULATED call/message context supplied by the demo operator.",
    )
    device_id: Optional[str] = None
    source: Literal["user", "scenario", "ambient"] = "user"
    channel: Literal["upi", "imps", "neft", "rtgs", "card", "atm", "wallet", "intl_wire"] = "upi"  # v10 rail


class IntentWithDecision(BaseModel):
    intent: TransactionIntent
    decision: Optional[RiskDecision] = None


class ExternalIntel(BaseModel):
    identifier: str
    status: Literal["clean", "watchlist", "reported", "confirmed_mule"]
    risk_score: float
    reason_codes: list[str]
    source: str
    last_updated: str
    simulated: bool = True


class GraphNode(BaseModel):
    id: str
    label: str
    kind: Literal["customer", "external", "device"]
    risk: float = 0.0
    flags: list[str] = Field(default_factory=list)
    role: Optional[str] = None         # collector | pass-through | distributor | cash-out | source | victim
    balance_paise: int = 0
    labelled: bool = False
    attributable_paise: int = 0


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    amount_paise: int
    count: int
    first_ts: str
    last_ts: str
    tainted_paise: int = 0             # value attributable (LIBR) to a confirmed scam on this edge
    tx_ids: list[str] = Field(default_factory=list)  # up to 5 underlying ledger postings
    highlight: bool = False


class GraphEvidence(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    focus: Optional[str] = None
    truncated: bool = False
    total_nodes: int = 0


class ScenarioEvent(BaseModel):
    scenario_id: str
    run_id: str
    step: int
    total_steps: int
    kind: str                          # event | transaction | intent | label | info
    title: str
    detail: str = ""
    ts: str
    state: Literal["idle", "running", "paused", "done"]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[dict[str, Any]] = None


# ══ v2 contracts (frozen 2026-10-06 by Claude 1 — see docs/archive/plans/FINAL_PARALLEL_PLAN.md) ══

# ── Detection intelligence (implemented by Claude 2 in vigil/intel/**) ─────
DetectorFamily = Literal[
    "rules", "random_forest", "gnn", "drift", "early_warning", "pattern_memory",
    "ringwatch", "trailscore", "context", "external",
]
ValueKind = Literal["score", "probability_uncalibrated", "probability_calibrated", "level", "similarity", "count"]


class DetectorResult(BaseModel):
    family: DetectorFamily
    label: str                         # "Random Forest", "GNN (GAT)", "Rule engine", ...
    value: Optional[float] = None      # numeric value when meaningful
    display: str                       # what the UI prints: "0.81", "HIGH", "89% similar"
    kind: ValueKind                    # never call a value a probability unless it is one
    flagged: bool                      # does this family consider the account risky?
    status: Literal["ok", "unavailable", "not_applicable"] = "ok"
    version: str
    observed_at: str
    detail: dict[str, Any] = Field(default_factory=dict)


class DetectorConsensus(BaseModel):
    families_flagging: int
    families_evaluated: int
    agreement: Literal["none", "weak", "moderate", "strong"]
    summary: str                       # "5 independent signal families agree"


class ShapContribution(BaseModel):
    feature: str
    value: float                       # the feature's value for this account
    contribution: float                # SHAP value (model output units)
    category: str                      # "Velocity Risk", "Shared Device Risk", "Ring Participation", ...


class ShapExplanation(BaseModel):
    model_version: str
    base_value: float
    prediction: float
    prediction_kind: ValueKind
    top_positive: list[ShapContribution]
    top_negative: list[ShapContribution]
    categories: dict[str, float]       # category -> summed |SHAP| (influence, unsigned)
    category_net: dict[str, float] = Field(default_factory=dict)   # category -> summed SHAP (signed: + raises, - lowers)


class DriftFeature(BaseModel):
    feature: str
    baseline: float
    current: float
    change: float                      # normalised change used for ranking


class DriftReport(BaseModel):
    baseline_window: str
    current_window: str
    drift_score: float
    level: Literal["LOW", "MEDIUM", "HIGH"]
    features: list[DriftFeature]


class PatternMatch(BaseModel):
    signature_id: str
    name: str                          # "Rapid Fan-In / Pass-Through"
    similarity: float                  # 0..1 structural similarity
    description: str
    note: str = "Structural similarity to a known pattern — not criminal attribution."


MuleRole = Literal["coordinator", "collector", "distributor", "entry", "exit", "unclassified"]


class RoleAssessment(BaseModel):
    role: MuleRole
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class AccountIntel(BaseModel):
    account_id: str
    as_of: str
    graph_version: int
    detectors: list[DetectorResult]
    consensus: DetectorConsensus
    shap: Optional[ShapExplanation] = None
    drift: Optional[DriftReport] = None
    role: RoleAssessment
    patterns: list[PatternMatch] = Field(default_factory=list)
    features: dict[str, float] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    model_id: str                      # "rf-v2", "gnn-gat-v2"
    family: Literal["random_forest", "gnn", "rules", "drift", "pattern_memory"]
    version: str
    trained_at: Optional[str] = None
    seed: Optional[int] = None
    data: str = "SYNTHETIC"
    split: str                         # e.g. "split-by-run; held-out attack families"
    metrics: dict[str, Any] = Field(default_factory=dict)
    per_attack: dict[str, Any] = Field(default_factory=dict)
    calibration: dict[str, Any] = Field(default_factory=dict)
    operational_use: str = "Corroborating evidence only — not used for payment authorisation."
    status: Literal["active", "unavailable", "retired"] = "active"


# ── Decision replay / counterfactuals / shadow mode (Claude 1) ────────────
class ReplayFrame(BaseModel):
    index: int
    ts: str
    kind: Literal["event", "evaluation", "decision", "action", "outcome"]
    label: str
    detail: str = ""
    signals_added: list[str] = Field(default_factory=list)
    subscores: dict[str, float]
    final_score: float
    tier: int


class DecisionReplay(BaseModel):
    decision_id: str
    intent_id: str
    policy_version: str
    frames: list[ReplayFrame]
    note: str = "Reconstructed from recorded evidence with the same policy engine; not a re-run against live data."


class Counterfactual(BaseModel):
    id: str
    label: str
    changes: list[str]
    final_score: float
    tier: int
    tier_delta: int                    # tier - actual tier (negative = lower)


class BaselineDecision(BaseModel):
    """What a conventional bank rule set would do (SHADOW MODE comparison)."""

    decision: Literal["approve", "otp_step_up", "decline"]
    reason: str


# ── 3D / 2D graph scene (Claude 1 backend, Claude 3 rendering) ─────────────
class SceneNode(BaseModel):
    id: str
    label: str
    kind: Literal["customer", "external"]
    x: float
    y: float
    z: float                           # frozen, precomputed layout
    layer: int                         # money-flow depth used for layout
    role: Optional[str] = None         # victim | collector | pass-through | distributor | cash-out | source | normal
    risk: float = 0.0                  # RingWatch network score
    taint_paise: int = 0               # LIBR-attributable value
    labelled: bool = False             # received a confirmed scam payment
    victim: bool = False               # sender of a confirmed scam payment
    held: bool = False                 # has an active scoped hold
    balance_paise: int = 0
    flags: list[str] = Field(default_factory=list)


class SceneTx(BaseModel):
    id: str
    ts: str
    amount_paise: int
    channel: str


class SceneEdge(BaseModel):
    id: str
    source: str
    target: str
    amount_paise: int
    count: int
    first_ts: str
    last_ts: str
    tainted_paise: int = 0
    channels: list[str] = Field(default_factory=list)
    txs: list[SceneTx] = Field(default_factory=list)


class GraphScene(BaseModel):
    version: str                       # cache key
    layout: str = "layered-3d-v1"
    nodes: list[SceneNode]
    edges: list[SceneEdge]
    focus: Optional[str] = None
    cap: int
    truncated: bool = False
    total_candidates: int = 0
    time_range: Optional[list[str]] = None
    built_ms: float = 0.0
    cached: bool = False


RiskDecision.model_rebuild()


# ══ v3 live-platform contracts (frozen 2026-10-07 by Claude 1 — see docs/archive/plans/V3_LIVE_PLATFORM_PLAN.md) ══
AccountStatus = Literal["normal", "idle", "new", "early_warning", "flagged", "held", "confirmed_fraud", "external"]


class UniverseAccount(BaseModel):
    """One node of the live 3D transaction universe (every account, not a subgraph)."""

    id: str
    label: str
    kind: Literal["customer", "external"]
    group: Literal["customer", "merchant", "demo", "mule_attack", "external"]
    status: AccountStatus
    risk: float = 0.0                  # RingWatch network score (authorisation path)
    model_risk: Optional[float] = None # strongest model-evidence value (corroborating only)
    role: Optional[str] = None
    opened_at: str
    balance_paise: int = 0
    last_active: Optional[str] = None
    # v8 (additive): why the account has its status, which detector families flag it, and since when
    reason: Optional[str] = None
    families_flagging: int = 0
    families: list[str] = Field(default_factory=list)
    status_since: Optional[str] = None


class UniverseEdge(BaseModel):
    id: str                            # ledger transaction id
    source: str
    target: str
    amount_paise: int
    ts: str
    channel: str
    kind: str                          # transfer | external_credit | external_debit
    origin: Literal["history", "ambient", "scenario", "user"]
    scenario: Optional[str] = None     # SIMULATOR GROUND TRUTH tag — display/evaluation only, never scored


class LiveUniverse(BaseModel):
    version: str
    as_of: str
    window_minutes: int
    accounts: list[UniverseAccount]
    edges: list[UniverseEdge]          # postings inside the live window (newest last), capped
    history_edges: list[UniverseEdge] = Field(default_factory=list)  # sampled older postings ("constellation")
    totals: dict[str, int] = Field(default_factory=dict)


class TxScored(BaseModel):
    """Pushed for every live posting after detection ran (WS topic console, type 'intel.tx_scored')."""

    tx_id: str
    ts: str
    sender_id: str
    recipient_id: str
    amount_paise: int
    channel: str
    origin: str
    scenario: Optional[str] = None
    sender_status: AccountStatus
    recipient_status: AccountStatus
    sender_risk: Optional[float] = None
    recipient_risk: Optional[float] = None
    scored_ms: float


class AccountStatusChange(BaseModel):
    """Pushed when an account's live detector status changes (type 'intel.account_status')."""

    account_id: str
    status: AccountStatus
    previous: AccountStatus
    risk: Optional[float] = None
    role: Optional[str] = None
    families_flagging: int = 0
    reason: str = ""
    ts: str


class AttackRun(BaseModel):
    """One execution of an attack scenario, evaluated against SIMULATOR GROUND TRUTH."""

    run_id: str
    scenario_id: str
    name: str
    category: str
    status: Literal["running", "paused", "evaluating", "completed"]
    started_at: str
    completed_at: Optional[str] = None
    steps_total: int
    steps_done: int
    tx_count: int = 0
    injected: list[str] = Field(default_factory=list)        # ground-truth mule accounts of this attack
    warned: list[str] = Field(default_factory=list)          # reached early_warning or worse
    detected: list[str] = Field(default_factory=list)        # reached flagged / confirmed
    missed: list[str] = Field(default_factory=list)
    false_positives: list[str] = Field(default_factory=list) # non-mule participants flagged during the run
    first_warning_ms: Optional[float] = None                 # from first attack posting
    detection_ms: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    model_threshold: Optional[float] = None


class LiveStats(BaseModel):
    as_of: str
    throughput_tps: float
    volume: list[dict[str, Any]]           # [{t, normal, attack}] per 10 s bucket, last 10 min ("attack" = simulator ground truth)
    channels: dict[str, int]
    tiers: dict[str, int]                  # decisions by tier (all time since reset)
    tiers_over_time: list[dict[str, Any]]  # [{t, t0..t4}] per minute
    runs_by_type: list[dict[str, Any]]     # [{scenario_id, name, runs, detected_runs}]
    runs: list[AttackRun]
    roles_flagged: dict[str, int]
    threshold_history: list[dict[str, Any]] = Field(default_factory=list)  # [{t, value, reason}] model-evidence threshold
    counts: dict[str, int] = Field(default_factory=dict)  # transactions, accounts, active, warnings, flagged, held, confirmed
    # v8 (additive): the last 10 minutes of ledger traffic, by origin, for the operations center —
    # {bucket_seconds, buckets: [{t, everyday, customer, injected, value_paise}], postings, value_paise, avg_paise,
    #  risky_postings, channels: {channel: n}, largest: [{id, ts, sender_id, recipient_id, amount_paise, channel, origin}]}
    traffic: dict[str, Any] = Field(default_factory=dict)


class NewAccount(BaseModel):
    """An account opened recently, and what has flowed through it since (v8 operations center)."""

    id: str
    label: str
    opened_at: str
    age_days: float
    status: AccountStatus
    reason: Optional[str] = None
    in_paise: int = 0                     # received since opening
    out_paise: int = 0                    # sent since opening
    inflows: int = 0
    senders: int = 0                      # distinct senders since opening
    first_inflow_at: Optional[str] = None
    shared_device_accounts: int = 0       # other accounts on the same device(s)
    large_inflow_rule: bool = False       # policy rule new_account_inflow would fire (age and inflow thresholds)


# ══ v8 close monitoring (watchlist) — additive ═══════════════════════════════════════════════
class WatchActivity(BaseModel):
    """What the detectors measure for the account over the detection window (same features the models see)."""

    window: str = "last 72 h"
    in_paise: int = 0
    out_paise: int = 0
    forwarded_fraction: float = 0.0        # share of inflow value forwarded within 60 min (pass-through speed)
    counterparties: int = 0
    new_counterparty_ratio: float = 0.0    # share of counterparties never seen before the window
    tx_count: int = 0


class WatchEntry(BaseModel):
    account_id: str
    label: str
    pinned: bool = False
    sources: list[str] = Field(default_factory=list)   # pinned | early_warning | model_only | pattern_memory
    note: Optional[str] = None
    added_at: Optional[str] = None
    status: AccountStatus
    status_since: Optional[str] = None
    reason: Optional[str] = None
    families_flagging: int = 0
    families: list[str] = Field(default_factory=list)
    network_risk: float = 0.0              # RingWatch (authorisation path)
    model_risk: Optional[float] = None     # strongest calibrated model evidence (corroborating only)
    model_threshold: Optional[float] = None
    role: Optional[str] = None
    early_warning_signals: list[str] = Field(default_factory=list)
    pattern: Optional[dict[str, Any]] = None           # {name, similarity} — structural similarity, not attribution
    activity: Optional[WatchActivity] = None
    last_active: Optional[str] = None
    next_step: str = ""                    # what would change its status (or what to do now)


class Watchlist(BaseModel):
    as_of: str
    model_threshold: Optional[float] = None
    pinned: int = 0
    suggested: int = 0
    entries: list[WatchEntry] = Field(default_factory=list)
