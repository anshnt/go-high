"""Stripe, through Connect: every workspace connects its own Stripe account and charges are direct charges on it (the
`Stripe-Account` header), so the money and the disputes are the workspace's. We store only Stripe's ids.

Settings (environment, the platform's): `STRIPE_SECRET_KEY` (the platform's secret key), `STRIPE_WEBHOOK_SECRETS`
(the signing secrets of the Connect webhook endpoint pointed at `/api/hooks/payments/stripe`, comma separated so one
can be rotated), `STRIPE_CONNECT_TYPE` (`standard`, default, or `express`) and `STRIPE_API_BASE` (tests point it at a
local server; nothing here ever calls the real Stripe in a test).

Events the endpoint should send: `account.updated`, `checkout.session.completed`,
`checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`, `payment_intent.succeeded`,
`payment_intent.payment_failed`, `payment_intent.processing`, `refund.created`, `refund.updated`, `refund.failed`.
Others are acknowledged and ignored (`charge.refunded` too: each refund has its own `refund.*` event, and counting both
would count a refund twice)."""
import base64
import http.client
import json
from urllib.parse import quote, urlencode, urlsplit

from ... import config
from .base import (
    AccountState,
    ChargeRequest,
    ChargeResult,
    CheckoutRequest,
    CheckoutSession,
    Onboarding,
    ProviderError,
    RefundRequest,
    RefundResult,
    Update,
    verify_signature,
)

key = "stripe"
label = "Stripe"
API_VERSION = "2024-06-20"  # pinned, so a change of Stripe's default cannot change what we read
TIMEOUT = 15
REFUND_REASONS = ("duplicate", "fraudulent", "requested_by_customer")


def available() -> str | None:
    if not config.STRIPE_SECRET_KEY:
        return "Stripe is not set up on this server: the operator sets STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRETS."
    if not config.STRIPE_WEBHOOK_SECRETS:
        return "Stripe webhooks are not set up on this server: the operator sets STRIPE_WEBHOOK_SECRETS."
    return None


def flatten(data: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's form encoding of nested values: `line_items[0][price_data][currency]=usd`."""
    out: list[tuple[str, str]] = []
    for k, v in data.items():
        name = f"{prefix}[{k}]" if prefix else str(k)
        if v is None:
            continue
        if isinstance(v, dict):
            out += flatten(v, name)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                out += flatten(item, f"{name}[{i}]") if isinstance(item, dict) else [(f"{name}[{i}]", str(item))]
        elif isinstance(v, bool):
            out.append((name, "true" if v else "false"))
        else:
            out.append((name, str(v)))
    return out


def call(method: str, path: str, data: dict | None = None, *, account: str | None = None,
         idempotency_key: str | None = None) -> dict:
    """One request to Stripe. Raises ProviderError (retryable for connection errors, 409 idempotency races, 429 and
    5xx), with the error body in `.body` so a declined charge can still name its payment intent. The secret key is
    sent in the Authorization header only and never appears in an error."""
    u = urlsplit(config.STRIPE_API_BASE.rstrip("/") + path)
    body = urlencode(flatten(data or {})).encode() if data is not None else None
    headers = {"Authorization": "Basic " + base64.b64encode(f"{config.STRIPE_SECRET_KEY}:".encode()).decode(),
               "Stripe-Version": API_VERSION, "Accept": "application/json", "User-Agent": "go-high/1"}
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if account:
        headers["Stripe-Account"] = account
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    conn = (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(
        u.hostname, u.port, timeout=TIMEOUT)
    try:
        conn.request(method, u.path + (f"?{u.query}" if u.query else ""), body, headers)
        response = conn.getresponse()
        status, raw = response.status, response.read(1_000_000)
    except (OSError, http.client.HTTPException) as e:
        raise ProviderError(f"Stripe could not be reached ({type(e).__name__})", retryable=True) from None
    finally:
        conn.close()
    try:
        answer = json.loads(raw)
    except ValueError:
        answer = {}
    if not isinstance(answer, dict):
        answer = {}
    if 200 <= status < 300:
        return answer
    error = answer.get("error") if isinstance(answer.get("error"), dict) else {}
    err = ProviderError(f"Stripe said: {str(error.get('message') or f'HTTP {status}')[:300]}",
                        code=error.get("decline_code") or error.get("code"),
                        retryable=status in (409, 429) or status >= 500)
    err.body = error  # type: ignore[attr-defined]
    raise err


def account_state(a: dict) -> AccountState:
    profile = a.get("business_profile") or {}
    settings = (a.get("settings") or {}).get("dashboard") or {}
    return AccountState(str(a.get("id")), bool(a.get("charges_enabled")), bool(a.get("payouts_enabled")),
                        bool(a.get("details_submitted")), bool(a.get("livemode", False)),
                        profile.get("name") or settings.get("display_name"))


def connect(workspace_id: str, account_id: str | None, return_url: str, refresh_url: str) -> Onboarding:
    if account_id is None:
        made = call("POST", "/v1/accounts", {"type": config.STRIPE_CONNECT_TYPE,
                                             "metadata": {"gohigh_workspace_id": workspace_id}},
                    idempotency_key=f"connect:{workspace_id}")
        account_id = str(made["id"])
    link = call("POST", "/v1/account_links", {"account": account_id, "refresh_url": refresh_url,
                                              "return_url": return_url, "type": "account_onboarding"})
    return Onboarding(account_id, link.get("url"))


def account(account_id: str) -> AccountState:
    return account_state(call("GET", f"/v1/accounts/{quote(account_id, safe='')}"))


def checkout(account_id: str, req: CheckoutRequest) -> CheckoutSession:
    meta = {"gohigh_payment_id": req.payment_id}
    data: dict = {
        "mode": "payment", "success_url": req.success_url, "cancel_url": req.cancel_url,
        "client_reference_id": req.payment_id, "metadata": meta,
        "line_items": [{"quantity": 1, "price_data": {"currency": req.currency, "unit_amount": req.amount,
                                                       "product_data": {"name": req.description[:250]}}}],
        "payment_intent_data": {"metadata": meta, "description": req.description[:250],
                                **({"setup_future_usage": "off_session"} if req.save_method else {})},
    }
    if req.customer_id:
        data["customer"] = req.customer_id
    else:
        data["customer_creation"] = "always"
        if req.customer_email:
            data["customer_email"] = req.customer_email
    session = call("POST", "/v1/checkout/sessions", data, account=account_id, idempotency_key=req.idempotency_key)
    return CheckoutSession(str(session["id"]), str(session["url"]))


def charge(account_id: str, req: ChargeRequest) -> ChargeResult:
    data = {"amount": req.amount, "currency": req.currency, "customer": req.customer_id,
            "payment_method": req.payment_method_id, "off_session": True, "confirm": True,
            "description": req.description[:250], "metadata": {"gohigh_payment_id": req.payment_id}}
    try:
        pi = call("POST", "/v1/payment_intents", data, account=account_id, idempotency_key=req.idempotency_key)
    except ProviderError as e:
        body = getattr(e, "body", {}) or {}
        if e.retryable or body.get("type") not in ("card_error", "invalid_request_error"):
            raise
        intent = body.get("payment_intent") or {}
        return ChargeResult("failed", intent.get("id"), e.code or body.get("code"), str(body.get("message") or e))
    status = pi.get("status")
    if status == "succeeded":
        return ChargeResult("succeeded", pi.get("id"))
    if status == "processing":
        return ChargeResult("pending", pi.get("id"))
    if status == "requires_action":
        return ChargeResult("failed", pi.get("id"), "authentication_required",
                            "The card needs the customer to confirm the payment.")
    error = pi.get("last_payment_error") or {}
    return ChargeResult("failed", pi.get("id"), error.get("decline_code") or error.get("code"),
                        error.get("message") or "The charge did not go through.")


def refund(account_id: str, req: RefundRequest) -> RefundResult:
    data = {"payment_intent": req.provider_payment_id, "amount": req.amount,
            "metadata": {"gohigh_refund_id": req.refund_id},
            "reason": req.reason if req.reason in REFUND_REASONS else None}
    r = call("POST", "/v1/refunds", data, account=account_id, idempotency_key=req.idempotency_key)
    status = {"succeeded": "succeeded", "failed": "failed", "canceled": "failed"}.get(r.get("status"), "pending")
    return RefundResult(status, str(r["id"]), r.get("failure_reason"))


def verify(headers: dict[str, str], body: bytes, now: float | None = None) -> bool:
    found = next((v for k, v in headers.items() if k.lower() == "stripe-signature"), None)
    return verify_signature(config.STRIPE_WEBHOOK_SECRETS, found, body, now)


def _id(value) -> str | None:
    """Stripe sends a related object as its id, or expanded as an object with one."""
    if isinstance(value, dict):
        value = value.get("id")
    return value if isinstance(value, str) else None


def parse(body: bytes) -> list[Update]:
    e = json.loads(body)
    if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not isinstance(e.get("data"), dict):
        raise ValueError("not a Stripe event")
    obj = e["data"].get("object")
    if not isinstance(obj, dict):
        raise ValueError("not a Stripe event")
    t = str(e.get("type"))
    base = {"event_id": e["id"], "event_type": t, "account_id": e.get("account")}
    meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    if t == "account.updated":
        return [Update(**base, kind="account", account=account_state(obj))]
    if t in ("checkout.session.completed", "checkout.session.async_payment_succeeded",
             "checkout.session.async_payment_failed"):
        paid = obj.get("payment_status") == "paid"
        failed = t.endswith("failed")
        if not (paid or failed):
            return []  # paid later (a bank debit): the async event follows
        return [Update(**base, kind="payment", status="failed" if failed else "succeeded",
                       payment_id=meta.get("gohigh_payment_id") or obj.get("client_reference_id"),
                       provider_payment_id=_id(obj.get("payment_intent")), amount=obj.get("amount_total"),
                       currency=obj.get("currency"), customer_id=_id(obj.get("customer")))]
    if t in ("payment_intent.succeeded", "payment_intent.payment_failed", "payment_intent.processing"):
        status = {"payment_intent.succeeded": "succeeded", "payment_intent.payment_failed": "failed",
                  "payment_intent.processing": "processing"}[t]
        error = obj.get("last_payment_error") or {}
        return [Update(**base, kind="payment", status=status, payment_id=meta.get("gohigh_payment_id"),
                       provider_payment_id=obj.get("id"),
                       amount=obj.get("amount_received") if status == "succeeded" else obj.get("amount"),
                       currency=obj.get("currency"), customer_id=_id(obj.get("customer")),
                       payment_method_id=_id(obj.get("payment_method")) if obj.get("setup_future_usage") else None,
                       failure_code=error.get("decline_code") or error.get("code"),
                       failure_message=error.get("message"))]
    if t in ("refund.created", "refund.updated", "refund.failed"):
        status = {"succeeded": "succeeded", "failed": "failed", "canceled": "failed"}.get(obj.get("status"), "pending")
        return [Update(**base, kind="refund", status=status, refund_id=meta.get("gohigh_refund_id"),
                       provider_refund_id=obj.get("id"), provider_payment_id=_id(obj.get("payment_intent")),
                       amount=obj.get("amount"), failure_message=obj.get("failure_reason"))]
    return []
