"""The payment provider interface (module 21). A provider is a module-like object with the methods of `Provider`;
`providers.get(key)` returns one. Like the channel adapters (app/channels), they hold no tables and no routes: the
checkout pages, the jobs and the webhook route call them the same way, and they only ever see and return provider ids
(an account, a customer, a payment method, a payment, a refund), never card data.

What crosses the boundary:
- `connect` / `account`: onboarding a workspace's own account (Stripe Connect) and reading whether it can take money;
- `checkout`: a hosted page at the provider where the customer pays one amount, optionally keeping the card for later;
- `charge`: an off-session charge of a kept card (subscription renewals and dunning retries);
- `refund`: all or part of a payment back;
- `verify` and `parse`: a webhook, checked on the raw body before anything is read, then turned into `Update`s.

Every call that moves money takes an `idempotency_key` that the caller derives from its own row (a payment, a refund),
so a retried job can never charge or refund twice."""
import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Protocol

SIGNATURE_TOLERANCE = 300  # seconds a signed webhook stays valid (replays of older ones are refused)


class ProviderError(Exception):
    """A call the provider refused or could not answer. `retryable` for timeouts, 429 and 5xx; `code` is the
    provider's own (`card_declined`), and the message is safe to show staff (never a secret)."""

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


@dataclass(frozen=True)
class Onboarding:
    account_id: str
    url: str | None  # where the workspace owner finishes setting up (None: nothing left to do)


@dataclass(frozen=True)
class AccountState:
    account_id: str
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool
    livemode: bool
    display_name: str | None = None


@dataclass(frozen=True)
class CheckoutRequest:
    payment_id: str  # ours: comes back in the webhook as metadata
    amount: int
    currency: str
    description: str
    customer_email: str | None
    customer_id: str | None  # a provider customer we already know for this contact
    save_method: bool  # keep the card for off-session charges (subscriptions)
    success_url: str
    cancel_url: str
    idempotency_key: str


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


@dataclass(frozen=True)
class ChargeRequest:
    payment_id: str
    amount: int
    currency: str
    customer_id: str
    payment_method_id: str
    description: str
    idempotency_key: str


@dataclass(frozen=True)
class ChargeResult:
    status: str  # succeeded, failed, pending (the webhook settles it)
    provider_payment_id: str | None
    failure_code: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class RefundRequest:
    refund_id: str
    provider_payment_id: str
    amount: int
    reason: str | None
    idempotency_key: str


@dataclass(frozen=True)
class RefundResult:
    status: str  # succeeded, pending, failed
    provider_refund_id: str
    failure_message: str | None = None


@dataclass(frozen=True)
class Update:
    """One fact a webhook reported, in our words. `kind`:
    - `account`: `account` holds an AccountState;
    - `payment`: a payment moved: `payment_id` (ours, from metadata; None for one we did not start), `status`
      (`succeeded`, `failed`, `processing`), `provider_payment_id`, `amount`, `currency`, and the `customer_id` and
      `payment_method_id` to keep when the card was saved;
    - `refund`: `provider_refund_id`, `provider_payment_id`, `refund_id` (ours, None for one made at the provider),
      `amount`, `status`."""
    event_id: str
    event_type: str
    account_id: str | None
    kind: str
    status: str | None = None
    payment_id: str | None = None
    provider_payment_id: str | None = None
    provider_refund_id: str | None = None
    refund_id: str | None = None
    amount: int | None = None
    currency: str | None = None
    customer_id: str | None = None
    payment_method_id: str | None = None
    card_brand: str | None = None
    card_last4: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    account: AccountState | None = None
    extra: dict = field(default_factory=dict)


class Provider(Protocol):
    key: str
    label: str

    def available(self) -> str | None: ...  # None when usable, else the plain reason it is not
    def connect(self, workspace_id: str, account_id: str | None, return_url: str, refresh_url: str) -> Onboarding: ...
    def account(self, account_id: str) -> AccountState: ...
    def checkout(self, account_id: str, req: CheckoutRequest) -> CheckoutSession: ...
    def charge(self, account_id: str, req: ChargeRequest) -> ChargeResult: ...
    def refund(self, account_id: str, req: RefundRequest) -> RefundResult: ...
    def verify(self, headers: dict[str, str], body: bytes, now: float | None = None) -> bool: ...
    def parse(self, body: bytes) -> list[Update]: ...


def sign(secret: str, body: bytes, at: int | None = None) -> str:
    """A `t=<unix>,v1=<hex>` header over `<t>.<body>` (Stripe's scheme, which the fake provider uses too)."""
    t = int(time.time()) if at is None else at
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify_signature(secrets: list[str], header: str | None, body: bytes, now: float | None = None,
                     tolerance: int = SIGNATURE_TOLERANCE) -> bool:
    """Whether `header` (`t=...,v1=...[,v1=...]`) signs `body` with any of `secrets` (more than one while a secret is
    rotated) within `tolerance` seconds of now, either way. Compared in constant time; anything malformed is False."""
    if not header or not secrets:
        return False
    stamp, signatures = None, []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            stamp = value
        elif key == "v1" and value:
            signatures.append(value)
    try:
        t = int(stamp or "")
    except ValueError:
        return False
    if not signatures or abs((time.time() if now is None else now) - t) > tolerance:
        return False
    signed = f"{t}.".encode() + body
    for secret in secrets:
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if any(hmac.compare_digest(expected, s) for s in signatures):
            return True
    return False
