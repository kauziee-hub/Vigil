"""PaymentProvider port.

Vigil decides BEFORE the provider is called. The provider only executes an
already-approved intent. The only provider is the simulated payment rail:
offline, instant, and labelled in the UI — no real money moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

MOCK_LABEL = "Simulated payment — no real money moved"


@dataclass
class InitiateResult:
    provider: str
    status: str                 # succeeded | created | failed
    order_id: str | None = None
    payment_id: str | None = None
    label: str = MOCK_LABEL
    error: str | None = None


class PaymentProvider(Protocol):
    name: str

    def initiate(self, intent_id: str, amount_paise: int) -> InitiateResult: ...


class MockPaymentProvider:
    name = "mock"

    def initiate(self, intent_id: str, amount_paise: int) -> InitiateResult:
        return InitiateResult(provider=self.name, status="succeeded", order_id=f"mock_order_{intent_id}",
                              payment_id=f"mock_pay_{intent_id}", label=MOCK_LABEL)


def get_provider() -> PaymentProvider:
    return MockPaymentProvider()
