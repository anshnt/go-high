"""The test provider: everything a real provider does, with no network and no money. For tests and local development
only, so it is switched off unless `PAYMENTS_FAKE_PROVIDER=1` (with it on, anyone can "pay" with the test card).

- `connect` makes an account at once (`acct_fake_<workspace>`), able to take charges.
- `checkout` returns a URL of this app, `/api/public/payments/fake/<session>`, a page with a Pay and a Decline button.
  The session is a signed token that holds what to charge, so nothing is stored. Paying posts a signed webhook through
  the very route a real provider calls (`/api/hooks/payments/fake`), so the fake path checks signatures, replays and
  fulfilment the same way.
- `charge` of a kept card succeeds unless the payment method id contains `decline` (`pm_fake_decline`).
- `refund` succeeds at once.

Webhooks are signed like Stripe's (`t=...,v1=...`) with a secret derived from SECRET_KEY."""
import base64
import hashlib
import hmac
import json
import secrets
import time

from ... import config
from .base import (
    AccountState,
    ChargeRequest,
    ChargeResult,
    CheckoutRequest,
    CheckoutSession,
    Onboarding,
    RefundRequest,
    RefundResult,
    Update,
    sign,
    verify_signature,
)

key = "fake"
label = "Test provider"


def secret() -> str:
    return hmac.new(config.SECRET_KEY.encode(), b"payments-fake-webhook", hashlib.sha256).hexdigest()


def available() -> str | None:
    if not config.PAYMENTS_FAKE_PROVIDER:
        return "The test provider is only for development: set PAYMENTS_FAKE_PROVIDER=1 to use it."
    return None


def connect(workspace_id: str, account_id: str | None, return_url: str, refresh_url: str) -> Onboarding:
    return Onboarding(account_id or f"acct_fake_{workspace_id.replace('-', '')[:16]}", None)


def account(account_id: str) -> AccountState:
    return AccountState(account_id, True, True, True, False, "Test account")


def _seal(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(secret().encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{mac}"


def unseal(session: str) -> dict | None:
    """What a checkout session holds, or None for one this app did not sign."""
    raw, _, mac = session.rpartition(".")
    expected = hmac.new(secret().encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]
    if not raw or not hmac.compare_digest(mac, expected):
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except ValueError:
        return None


def checkout(account_id: str, req: CheckoutRequest) -> CheckoutSession:
    session = _seal({"a": account_id, "p": req.payment_id, "m": req.amount, "c": req.currency, "d": req.description,
                     "s": req.save_method, "ok": req.success_url, "no": req.cancel_url,
                     "pi": f"pi_fake_{hashlib.sha256(req.idempotency_key.encode()).hexdigest()[:20]}"})
    return CheckoutSession(f"cs_fake_{hashlib.sha256(session.encode()).hexdigest()[:24]}",
                           f"{config.ALLOWED_ORIGINS[0]}/api/public/payments/fake/{session}")


def charge(account_id: str, req: ChargeRequest) -> ChargeResult:
    pi = f"pi_fake_{hashlib.sha256(req.idempotency_key.encode()).hexdigest()[:20]}"  # the same key, the same payment
    if "decline" in req.payment_method_id:
        return ChargeResult("failed", pi, "card_declined", "Your card was declined.")
    return ChargeResult("succeeded", pi)


def refund(account_id: str, req: RefundRequest) -> RefundResult:
    return RefundResult("succeeded", f"re_fake_{hashlib.sha256(req.idempotency_key.encode()).hexdigest()[:20]}")


def event(account_id: str, type_: str, data: dict, event_id: str | None = None) -> bytes:
    """The body of a webhook of the test provider."""
    return json.dumps({"id": event_id or f"evt_fake_{secrets.token_hex(10)}", "type": type_, "account": account_id,
                       "created": int(time.time()), "data": data}).encode()


def signed(body: bytes, at: int | None = None) -> dict[str, str]:
    return {"fake-signature": sign(secret(), body, at), "content-type": "application/json"}


def verify(headers: dict[str, str], body: bytes, now: float | None = None) -> bool:
    found = next((v for k, v in headers.items() if k.lower() == "fake-signature"), None)
    return verify_signature([secret()], found, body, now)


def parse(body: bytes) -> list[Update]:
    """Types: `payment.succeeded`, `payment.failed` (data as in `Update`), `refund.updated`, `account.updated`."""
    e = json.loads(body)
    if not isinstance(e, dict) or not isinstance(e.get("data"), dict) or not isinstance(e.get("id"), str):
        raise ValueError("not an event")
    d, base = e["data"], {"event_id": e["id"], "event_type": str(e.get("type")), "account_id": e.get("account")}
    t = e.get("type")
    if t in ("payment.succeeded", "payment.failed"):
        return [Update(**base, kind="payment", status=t.split(".")[1], payment_id=d.get("payment_id"),
                       provider_payment_id=d.get("provider_payment_id"), amount=d.get("amount"),
                       currency=d.get("currency"), customer_id=d.get("customer_id"),
                       payment_method_id=d.get("payment_method_id"), card_brand=d.get("card_brand"),
                       card_last4=d.get("card_last4"), failure_code=d.get("failure_code"),
                       failure_message=d.get("failure_message"))]
    if t == "refund.updated":
        return [Update(**base, kind="refund", status=d.get("status"), refund_id=d.get("refund_id"),
                       provider_refund_id=d.get("provider_refund_id"),
                       provider_payment_id=d.get("provider_payment_id"), amount=d.get("amount"))]
    if t == "account.updated":
        return [Update(**base, kind="account", account=account(str(e.get("account"))))]
    return []
