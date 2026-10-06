"""Risk fusion + interrupt ladder. Transparent by construction.

    base  = Σ weight_d × score_d          (contributions shown in the UI, sum to base)
    final = min(1, base + corroboration)
    tier  = ladder(final), then named floors / caps from the policy

Every adjustment is returned as a PolicyAdjustment so the analyst sees exactly
which piece of evidence changed the outcome. Weights are hand-set demo values
held in config/risk_policy.yaml, versioned, and not presented as validated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vigil.contracts import DIMENSIONS, DimensionScore, PolicyAdjustment, RiskSignal
from vigil.settings import get_policy


@dataclass
class FusionResult:
    dimensions: list[DimensionScore]
    base_score: float
    final_score: float
    ladder_tier: int
    tier: int
    adjustments: list[PolicyAdjustment]
    counterfactual: str


def ladder(final: float) -> int:
    for row in get_policy()["ladder"]:
        if final < float(row["below"]):
            return int(row["tier"])
    return int(get_policy()["ladder"][-1]["tier"])


def ladder_row(tier: int) -> dict[str, Any]:
    return next(r for r in get_policy()["ladder"] if int(r["tier"]) == tier)


def _dimension_scores(signals: dict[str, list[RiskSignal]]) -> list[DimensionScore]:
    weights = get_policy()["fusion"]["weights"]
    out = []
    for dim in DIMENSIONS:
        sigs = signals.get(dim, [])
        score = round(min(1.0, sum(s.contribution for s in sigs)), 4)
        weight = float(weights[dim])
        out.append(DimensionScore(dimension=dim, score=score, weight=weight,
                                  contribution=round(weight * score, 4), signals=sigs))
    return out


def _tier_for(dims: list[DimensionScore], facts: dict[str, Any]) -> tuple[float, float, int, int, list[PolicyAdjustment]]:
    policy = get_policy()
    fcfg = policy["fusion"]["corroboration"]
    acfg = policy["adjustments"]
    by = {d.dimension: d for d in dims}
    adjustments: list[PolicyAdjustment] = []

    base = round(sum(d.contribution for d in dims), 4)
    strong = [d.dimension for d in dims if d.score >= float(fcfg["dimension_threshold"])]
    bonus = 0.0
    if len(strong) >= 2:
        bonus = round(float(fcfg["bonus_per_extra_dimension"]) * (len(strong) - 1), 4)
        adjustments.append(PolicyAdjustment(
            rule_id="ADJ_CORROBORATION", kind="corroboration", effect=f"+{bonus:.2f}",
            reason=f"{len(strong)} independent dimensions agree ({', '.join(strong)}).",
        ))
    final = round(min(1.0, base + bonus), 4)
    ladder_tier = ladder(final)
    tier = ladder_tier

    floors_fired = False
    if facts.get("external_status") == "confirmed_mule" and tier < acfg["floors"]["external_confirmed_min_tier"]:
        tier = int(acfg["floors"]["external_confirmed_min_tier"])
        floors_fired = True
        adjustments.append(PolicyAdjustment(
            rule_id="FLOOR_EXTERNAL_CONFIRMED", kind="floor", effect=f"tier >= {tier}",
            reason="Recipient is confirmed as a mule by the (simulated) external registry.",
        ))
    if facts.get("attributable_paise", 0) >= acfg["floors"]["taint_exposure_min_paise"] and tier < acfg["floors"]["taint_exposure_min_tier"]:
        tier = int(acfg["floors"]["taint_exposure_min_tier"])
        floors_fired = True
        adjustments.append(PolicyAdjustment(
            rule_id="FLOOR_TAINT_EXPOSURE", kind="floor", effect=f"tier >= {tier}",
            reason="Recipient currently holds value attributable to a confirmed scam.",
        ))

    fg = acfg["friction_guard"]
    if (fg["enabled"] and not floors_fired
            and facts.get("prior_payments", 0) >= fg["min_prior_payments"]
            and by["sequence"].score <= fg["max_sequence"]
            and by["context"].score <= fg["max_context"]
            and by["external"].score <= fg["max_external"]
            and tier > fg["max_tier"]):
        adjustments.append(PolicyAdjustment(
            rule_id="CAP_FRICTION_GUARD", kind="cap", effect=f"tier <= {fg['max_tier']}",
            reason=(f"Established relationship ({facts.get('prior_payments')} prior payments), "
                    "no account-takeover or pressure signals, clean registry: avoid needless friction."),
        ))
        tier = int(fg["max_tier"])

    cb = acfg["circuit_breaker_requires_sender_evidence"]
    if cb["enabled"] and tier == 4 and not (
        by["sequence"].score >= cb["min_sequence"] or by["context"].score >= cb["min_context"]
    ):
        tier = int(cb["else_max_tier"])
        adjustments.append(PolicyAdjustment(
            rule_id="CAP_NO_SENDER_EVIDENCE", kind="cap", effect=f"tier <= {tier}",
            reason="Trusted-contact escalation is reserved for signs the sender is compromised or coerced; "
                   "recipient risk alone gets a scoped hold.",
        ))
    return base, final, ladder_tier, tier, adjustments


def fuse(signals: dict[str, list[RiskSignal]], facts: dict[str, Any]) -> FusionResult:
    dims = _dimension_scores(signals)
    base, final, ladder_tier, tier, adjustments = _tier_for(dims, facts)

    counterfactual = "No single dimension drove this outcome."
    top = max(dims, key=lambda d: d.contribution)
    if top.contribution > 0 and tier > 0:
        reduced = [d if d.dimension != top.dimension else DimensionScore(
            dimension=d.dimension, score=0.0, weight=d.weight, contribution=0.0, signals=[]) for d in dims]
        cf_facts = dict(facts)
        if top.dimension == "external":
            cf_facts["external_status"] = "clean"
        if top.dimension == "network":
            cf_facts["attributable_paise"] = 0
        _, cf_final, _, cf_tier, _ = _tier_for(reduced, cf_facts)
        counterfactual = (
            f"Without the {top.dimension} evidence the score would be {cf_final:.2f} "
            f"(Tier {cf_tier} instead of Tier {tier})."
        )
    return FusionResult(dims, base, final, ladder_tier, tier, adjustments, counterfactual)
