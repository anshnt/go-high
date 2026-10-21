"""The provider layer (app/payments/providers): webhook signatures (tolerance, rotation, tampering), the Stripe adapter
against a local stand-in for api.stripe.com (no test ever calls the real Stripe), and the test provider."""
import json
import time
from urllib.parse import parse_qsl

import pytest
from helpers import Receiver

from app import config
from app.payments.providers import base, fake, stripe
from app.payments.providers.base import ChargeRequest, CheckoutRequest, ProviderError, RefundRequest

SECRET = "whsec_test_secret"


def test_a_signature_is_checked_on_the_raw_body_within_five_minutes():
    body = b'{"id":"evt_1"}'
    header = base.sign(SECRET, body)
    assert base.verify_signature([SECRET], header, body)
    assert not base.verify_signature([SECRET], header, body + b" ")  # one byte changed
    assert not base.verify_signature(["whsec_other"], header, body)
    assert not base.verify_signature([SECRET], None, body) and not base.verify_signature([], header, body)
    old = base.sign(SECRET, body, at=int(time.time()) - 301)
    assert not base.verify_signature([SECRET], old, body)  # a captured request replayed later
    future = base.sign(SECRET, body, at=int(time.time()) + 301)
    assert not base.verify_signature([SECRET], future, body)
    assert base.verify_signature([SECRET], base.sign(SECRET, body, at=int(time.time()) - 299), body)
    for broken in ("t=abc,v1=00", "v1=00", "t=1", "", "t=,v1=", "garbage"):
        assert not base.verify_signature([SECRET], broken, body)


def test_any_of_several_signatures_and_secrets_may_match_while_one_is_rotated():
    body = b"{}"
    t = int(time.time())
    good = base.sign("new", body, at=t).split("v1=")[1]
    header = f"t={t},v1=deadbeef,v0=ignored,v1={good}"
    assert base.verify_signature(["old", "new"], header, body)
    assert not base.verify_signature(["old"], header, body)


def test_stripe_verify_reads_its_header_with_the_configured_secrets(monkeypatch):
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRETS", [SECRET])
    body = b'{"id": "evt"}'
    assert stripe.verify({"Stripe-Signature": base.sign(SECRET, body)}, body)
    assert not stripe.verify({"stripe-signature": base.sign("nope", body)}, body)
    assert not stripe.verify({}, body)


def test_stripe_encodes_nested_values_as_stripe_expects():
    pairs = stripe.flatten({"a": 1, "b": {"c": "x", "d": None}, "items": [{"q": 1}], "ok": True, "tags": ["p", "q"]})
    assert pairs == [("a", "1"), ("b[c]", "x"), ("items[0][q]", "1"), ("ok", "true"), ("tags[0]", "p"),
                     ("tags[1]", "q")]


@pytest.fixture
def api(monkeypatch):
    server = Receiver()
    monkeypatch.setattr(config, "STRIPE_API_BASE", f"http://127.0.0.1:{server.port}")
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_platform_key")
    yield server
    server.close()


def reply(server, status: int, payload: dict) -> None:
    server.replies.append((status, json.dumps(payload).encode(), {"Content-Type": "application/json"}))


def form(request) -> dict:
    return dict(parse_qsl(request["body"].decode()))


def test_checkout_is_a_direct_charge_on_the_connected_account_with_our_ids(api):
    reply(api, 200, {"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"})
    session = stripe.checkout("acct_123", CheckoutRequest(
        payment_id="pay-1", amount=2599, currency="usd", description="Invoice INV-0001", customer_email="a@b.co",
        customer_id=None, save_method=True, success_url="https://x/ok", cancel_url="https://x/no",
        idempotency_key="checkout:pay-1"))
    assert session.id == "cs_1" and session.url.startswith("https://checkout.stripe.com/")
    sent = api.requests[0]
    assert sent["path"] == "/v1/checkout/sessions" and sent["headers"]["stripe-account"] == "acct_123"
    assert sent["headers"]["idempotency-key"] == "checkout:pay-1"
    assert sent["headers"]["authorization"].startswith("Basic ") and "stripe-version" in sent["headers"]
    f = form(sent)
    assert f["line_items[0][price_data][unit_amount]"] == "2599" and f["line_items[0][price_data][currency]"] == "usd"
    assert f["metadata[gohigh_payment_id]"] == "pay-1" == f["payment_intent_data[metadata][gohigh_payment_id]"]
    assert f["payment_intent_data[setup_future_usage]"] == "off_session" and f["customer_creation"] == "always"
    assert f["mode"] == "payment" and f["customer_email"] == "a@b.co"


def test_a_declined_off_session_charge_is_a_failure_with_its_payment_intent_not_an_error(api):
    reply(api, 402, {"error": {"type": "card_error", "code": "card_declined", "decline_code": "insufficient_funds",
                               "message": "Your card has insufficient funds.", "payment_intent": {"id": "pi_9"}}})
    result = stripe.charge("acct_1", ChargeRequest("pay-2", 1000, "usd", "cus_1", "pm_1", "Invoice 2", "charge:x:1"))
    assert (result.status, result.provider_payment_id, result.failure_code) == ("failed", "pi_9", "insufficient_funds")
    f = form(api.requests[0])
    assert f["off_session"] == "true" and f["confirm"] == "true" and f["customer"] == "cus_1"
    assert api.requests[0]["headers"]["idempotency-key"] == "charge:x:1"
    reply(api, 200, {"id": "pi_10", "status": "requires_action"})
    assert stripe.charge("acct_1", ChargeRequest("p", 1, "usd", "c", "m", "d", "k")).failure_code == \
        "authentication_required"
    reply(api, 200, {"id": "pi_11", "status": "succeeded"})
    assert stripe.charge("acct_1", ChargeRequest("p", 1, "usd", "c", "m", "d", "k2")).status == "succeeded"


def test_provider_errors_say_whether_to_retry_and_never_carry_the_key(api):
    reply(api, 500, {"error": {"message": "boom"}})
    with pytest.raises(ProviderError) as e:
        stripe.account("acct_1")
    assert e.value.retryable and "sk_test_platform_key" not in str(e.value)
    reply(api, 400, {"error": {"type": "invalid_request_error", "message": "No such account"}})
    with pytest.raises(ProviderError) as e:
        stripe.account("acct_1")
    assert not e.value.retryable and "No such account" in str(e.value)
    api.close()
    with pytest.raises(ProviderError) as e:
        stripe.account("acct_1")
    assert e.value.retryable


def test_refund_and_connect_send_what_stripe_needs(api):
    reply(api, 200, {"id": "re_1", "status": "succeeded"})
    r = stripe.refund("acct_1", RefundRequest("ref-1", "pi_1", 500, "requested_by_customer", "refund:ref-1"))
    assert (r.status, r.provider_refund_id) == ("succeeded", "re_1")
    f = form(api.requests[0])
    assert f["payment_intent"] == "pi_1" and f["amount"] == "500" and f["metadata[gohigh_refund_id]"] == "ref-1"
    reply(api, 200, {"id": "acct_new"})
    reply(api, 200, {"url": "https://connect.stripe.com/setup/x"})
    onboarding = stripe.connect("ws-1", None, "https://x/back", "https://x/retry")
    assert (onboarding.account_id, onboarding.url) == ("acct_new", "https://connect.stripe.com/setup/x")
    assert api.requests[1]["headers"]["idempotency-key"] == "connect:ws-1"
    assert form(api.requests[2])["account"] == "acct_new"


def event(type_: str, obj: dict, account: str = "acct_1") -> bytes:
    return json.dumps({"id": f"evt_{type_}", "type": type_, "account": account, "data": {"object": obj}}).encode()


def test_stripe_events_become_updates_in_our_words():
    [u] = stripe.parse(event("payment_intent.succeeded", {
        "id": "pi_1", "amount_received": 2599, "currency": "usd", "customer": "cus_1", "payment_method": "pm_1",
        "setup_future_usage": "off_session", "metadata": {"gohigh_payment_id": "pay-1"}}))
    assert (u.kind, u.status, u.payment_id, u.amount, u.payment_method_id) == ("payment", "succeeded", "pay-1", 2599,
                                                                               "pm_1")
    [u] = stripe.parse(event("payment_intent.payment_failed", {
        "id": "pi_1", "amount": 10, "currency": "usd", "last_payment_error": {"code": "card_declined",
                                                                            "message": "no"}, "metadata": {}}))
    assert (u.status, u.failure_code, u.payment_id) == ("failed", "card_declined", None)
    assert stripe.parse(event("checkout.session.completed", {"payment_status": "unpaid", "metadata": {}})) == []
    [u] = stripe.parse(event("refund.updated", {"id": "re_1", "amount": 5, "status": "succeeded",
                                                "payment_intent": "pi_1", "metadata": {"gohigh_refund_id": "r-1"}}))
    assert (u.kind, u.status, u.refund_id, u.provider_payment_id) == ("refund", "succeeded", "r-1", "pi_1")
    [u] = stripe.parse(event("account.updated", {"id": "acct_1", "charges_enabled": True, "details_submitted": True}))
    assert u.kind == "account" and u.account.charges_enabled
    assert stripe.parse(event("charge.refunded", {"amount_refunded": 5})) == []  # refund.* events carry refunds
    assert stripe.parse(event("customer.created", {})) == []
    for bad in (b"[]", b'{"id": 1}', b'{"id": "e", "data": {"object": 3}}'):
        with pytest.raises(ValueError):
            stripe.parse(bad)


def test_the_test_provider_is_off_unless_switched_on_and_its_sessions_cannot_be_forged(monkeypatch):
    monkeypatch.setattr(config, "PAYMENTS_FAKE_PROVIDER", False)
    assert fake.available() is not None
    monkeypatch.setattr(config, "PAYMENTS_FAKE_PROVIDER", True)
    assert fake.available() is None
    session = fake.checkout("acct_fake_1", CheckoutRequest("p1", 100, "usd", "x", None, None, False, "ok", "no", "k"))
    token = session.url.rsplit("/", 1)[1]
    assert fake.unseal(token)["m"] == 100
    raw, mac = token.rsplit(".", 1)
    assert fake.unseal(raw + "." + "0" * len(mac)) is None
    tampered = raw[:-2] + ("A" if raw[-2] != "A" else "B") + raw[-1] + "." + mac
    assert fake.unseal(tampered) is None
    assert fake.charge("a", ChargeRequest("p", 1, "usd", "c", "pm_fake_decline", "d", "k")).status == "failed"
    first = fake.charge("a", ChargeRequest("p", 1, "usd", "c", "pm_fake_visa", "d", "same"))
    assert first == fake.charge("a", ChargeRequest("p", 1, "usd", "c", "pm_fake_visa", "d", "same"))  # idempotent
