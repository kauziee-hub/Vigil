"""PaymentProvider port.

Vigil decides BEFORE the provider is called. The provider only executes an
already-approved intent.

* MockPaymentProvider      — default, offline, instant; UI shows "DEMO PAYMENT".
* RazorpayTestProvider     — real Razorpay API in TEST MODE: server creates an
  order, the browser opens Razorpay Checkout, the server verifies the payment
  signature HMAC-SHA256(order_id + "|" + payment_id, key_secret).
  Test mode uses test funds: it proves a real gateway integration, it does NOT
  prove that money moved. The UI says so.
* RazorpayLiveProvider     — intentionally not implemented.

Razorpay is never a single point of failure: any gateway error leaves the
intent in PAYMENT_INITIATED/FAILED and the UI offers "complete as demo payment".
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from vigil.settings import get_settings

MOCK_LABEL = "DEMO PAYMENT (mock provider) — no real money moved"
RAZORPAY_LABEL = "RAZORPAY TEST MODE — real gateway API, test funds, no real money moved"


@dataclass
class InitiateResult:
    provider: str
    status: str                 # succeeded | created | failed
    order_id: str | None = None
    payment_id: str | None = None
    key_id: str | None = None
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


class RazorpayTestProvider:
    name = "razorpay_test"
    # Razorpay test orders are created for a small, capped amount: the gateway
    # leg demonstrates the integration; the ledger records the real intent amount.
    MAX_GATEWAY_PAISE = 5_00_000 * 100  # ₹5,00,000 cap for test orders

    def __init__(self, key_id: str, key_secret: str) -> None:
        if not key_id.startswith("rzp_test_"):
            raise ValueError("RazorpayTestProvider refuses non-test keys")
        self.key_id = key_id
        self._secret = key_secret

    def initiate(self, intent_id: str, amount_paise: int) -> InitiateResult:
        body = json.dumps({
            "amount": min(int(amount_paise), self.MAX_GATEWAY_PAISE),
            "currency": "INR",
            "receipt": intent_id,
            "notes": {"vigil_intent": intent_id, "mode": "test"},
        }).encode()
        auth = base64.b64encode(f"{self.key_id}:{self._secret}".encode()).decode()
        req = urllib.request.Request(
            "https://api.razorpay.com/v1/orders", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                order = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode())["error"]["description"]
            except Exception:
                pass
            if exc.code == 401:
                GATEWAY["status"] = "auth_failed"
            return InitiateResult(provider=self.name, status="failed", label=RAZORPAY_LABEL,
                                  error=f"Razorpay HTTP {exc.code}: {detail or 'error'}")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            return InitiateResult(provider=self.name, status="failed", label=RAZORPAY_LABEL,
                                  error=f"gateway unreachable: {type(exc).__name__}")
        return InitiateResult(provider=self.name, status="created", order_id=order["id"],
                              key_id=self.key_id, label=RAZORPAY_LABEL)

    def verify_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        expected = hmac.new(self._secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")


# Result of the one-time startup probe: unknown | ok | auth_failed | unreachable
GATEWAY: dict[str, str] = {"status": "unknown", "detail": ""}


def probe_gateway() -> dict[str, str]:
    """One cheap authenticated GET at startup. 401 → auto-fallback to mock (keys revoked/rotated)."""
    s = get_settings()
    if s.payment_provider != "razorpay_test":
        GATEWAY.update(status="not_configured", detail="mock provider selected")
        return GATEWAY
    auth = base64.b64encode(f"{s.razorpay_key_id}:{s.razorpay_key_secret}".encode()).decode()
    req = urllib.request.Request("https://api.razorpay.com/v1/orders?count=1", headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=5):
            GATEWAY.update(status="ok", detail="test keys accepted")
    except urllib.error.HTTPError as exc:
        GATEWAY.update(status="auth_failed" if exc.code == 401 else "error", detail=f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        GATEWAY.update(status="unreachable", detail=type(exc).__name__)
    return GATEWAY


def effective_provider() -> str:
    s = get_settings()
    if s.payment_provider == "razorpay_test" and GATEWAY["status"] in {"auth_failed"}:
        return "mock"
    return s.payment_provider


def get_provider(override: str | None = None) -> PaymentProvider:
    s = get_settings()
    name = override or effective_provider()
    if name == "razorpay_test" and s.razorpay_key_id and s.razorpay_key_secret:
        return RazorpayTestProvider(s.razorpay_key_id, s.razorpay_key_secret)
    return MockPaymentProvider()


def verify_razorpay_signature(order_id: str, payment_id: str, signature: str) -> bool:
    s = get_settings()
    if not s.razorpay_key_secret:
        return False
    expected = hmac.new(s.razorpay_key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")
