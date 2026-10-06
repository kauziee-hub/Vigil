"""External fraud-intelligence adapter.

`ExternalFraudIntelProvider` is the seam where a bank would plug in what it
already receives from institutional sources (e.g. a DPIP-style registry
response, MuleHunter-style mule flags from its own deployment, I4C suspect
registry matches). Vigil does NOT have access to any of those systems.

`LocalRegistryProvider` emulates such a feed from the local `external_intel`
table. Every result is marked `simulated=True` and the UI must label it
"SIMULATED EXTERNAL INTELLIGENCE".
"""

from __future__ import annotations

from typing import Protocol

from vigil import db
from vigil.contracts import ExternalIntel, RiskSignal
from vigil.settings import get_policy

REASON_TEXT = {
    "MULTIPLE_VICTIM_REPORTS": "multiple customers have reported payments to it",
    "VICTIM_REPORT": "a customer has reported a payment to it",
    "RAPID_PASS_THROUGH": "money arriving there is typically moved on quickly",
    "NEW_ACCOUNT_HIGH_INFLOW": "it is a new account receiving unusually large inflows",
    "LINKED_TO_REPORTED_DEVICE": "it is linked to a device seen in other reports",
    "LE_REQUEST": "a law-enforcement request references it",
    "CONFIRMED_MULE": "an institution has confirmed it as a mule account",
}


class ExternalFraudIntelProvider(Protocol):
    name: str

    def lookup(self, identifier: str) -> ExternalIntel | None: ...


class LocalRegistryProvider:
    """Reads the seeded `external_intel` table. Local, offline, deterministic."""

    name = "local_registry (SIMULATED)"

    def lookup(self, identifier: str) -> ExternalIntel | None:
        row = db.q1("SELECT * FROM external_intel WHERE identifier = ?", (identifier,))
        if row is None:
            return None
        return ExternalIntel(
            identifier=row["identifier"],
            status=row["status"],
            risk_score=float(row["risk_score"]),
            reason_codes=db.loads(row["reason_codes"], []),
            source=row["source"],
            last_updated=row["last_updated"],
            simulated=True,
        )


_provider: ExternalFraudIntelProvider = LocalRegistryProvider()


def provider() -> ExternalFraudIntelProvider:
    return _provider


def set_provider(p: ExternalFraudIntelProvider) -> None:
    global _provider
    _provider = p


def evaluate(recipient_id: str) -> tuple[list[RiskSignal], ExternalIntel | None]:
    intel = provider().lookup(recipient_id)
    if intel is None or intel.status == "clean":
        return [], intel
    status_scores = get_policy()["external"]["status_scores"]
    contribution = float(status_scores.get(intel.status, 0.0))
    reasons = [REASON_TEXT.get(code, code.lower().replace("_", " ")) for code in intel.reason_codes]
    label = {
        "confirmed_mule": "Registry: confirmed mule",
        "reported": "Registry: reported",
        "watchlist": "Registry: watchlist",
    }[intel.status]
    reason = f"Simulated external registry ({intel.source}) lists this recipient as {intel.status.replace('_', ' ')}"
    if reasons:
        reason += ": " + "; ".join(reasons[:2])
    signal = RiskSignal(
        rule_id=f"EXT_{intel.status.upper()}",
        dimension="external",
        label=label,
        reason=reason + ".",
        evidence={
            "status": intel.status,
            "registry_risk_score": intel.risk_score,
            "reason_codes": intel.reason_codes,
            "source": intel.source,
            "last_updated": intel.last_updated,
            "simulated": True,
        },
        contribution=contribution,
    )
    return [signal], intel
