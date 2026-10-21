"""Where a top-up asks a payment provider for money. A provider is one object with `charge`; `PROVIDERS` maps the
`PAYMENT_PROVIDER` setting to it. Only the fake provider exists here: payments (module 21) brings Stripe and the saved
card flow, and registers itself in `PROVIDERS` without anything else changing.

The fake provider stands in for a card: a payment method token starting with `pm_fake_decline` is declined (a permanent
failure), `pm_fake_error` fails as a provider outage would (a retryable one), anything else succeeds. It remembers the
idempotency keys it has seen in memory for the life of the process, as a real provider does for a day, so a retried
charge answers the first one."""
import os
import uuid
from dataclasses import dataclass
from typing import Protocol


class PaymentError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True)
class Charge:
    reference: str  # the provider's id of the payment


class Provider(Protocol):
    name: str

    def charge(self, *, amount_minor: int, currency: str, payment_method: str, idempotency_key: str,
               description: str) -> Charge:
        """Takes `amount_minor` (minor units of `currency`) from the saved method, once per `idempotency_key`; raises
        PaymentError when it cannot."""
        ...


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.seen: dict[str, Charge] = {}
        self.calls: list[dict] = []  # what it was asked, for tests

    def charge(self, *, amount_minor: int, currency: str, payment_method: str, idempotency_key: str,
               description: str) -> Charge:
        self.calls.append({"amount_minor": amount_minor, "currency": currency, "payment_method": payment_method,
                           "idempotency_key": idempotency_key})
        if idempotency_key in self.seen:
            return self.seen[idempotency_key]
        if payment_method.startswith("pm_fake_decline"):
            raise PaymentError("The card was declined")
        if payment_method.startswith("pm_fake_error"):
            raise PaymentError("The payment provider did not answer", retryable=True)
        self.seen[idempotency_key] = Charge(f"fake_ch_{uuid.uuid4().hex[:16]}")
        return self.seen[idempotency_key]


PROVIDERS: dict[str, Provider] = {"fake": FakeProvider()}


def configured() -> str:
    """The name of the provider top-ups go to (`PAYMENT_PROVIDER`, default fake)."""
    return os.getenv("PAYMENT_PROVIDER", "fake")


def provider() -> Provider:
    name = configured()
    if name not in PROVIDERS:
        raise PaymentError(f"The payment provider {name!r} is not available")
    return PROVIDERS[name]
