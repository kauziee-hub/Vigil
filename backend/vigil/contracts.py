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


class RiskSignal(BaseModel):
    """One fired rule. Never just `fraud = 1`."""

    rule_id: str
    dimension: Dimension
    label: str                         # short chip text, e.g. "Rapid pass-through"
    reason: str                        # one plain sentence, built from evidence
    evidence: dict[str, Any] = Field(default_factory=dict)  # raw values behind the reason
    contribution: float                # added to the dimension score (0..1)


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


class PaymentInfo(BaseModel):
    provider: str                      # mock | razorpay_test
    status: str                        # created | succeeded | failed
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    key_id: Optional[str] = None       # publishable Razorpay key id (test)
    amount_paise: int
    label: str                         # "DEMO PAYMENT (mock)" | "RAZORPAY TEST MODE — no real money moved"


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
