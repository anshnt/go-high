"""The catalog and settings of payments (module 21): products and their one-time, recurring and tiered prices, amounts
that never change, coupons, tax rates, settings, connecting a provider and the capability matrix."""
import json

import pytest
from helpers import H, Receiver
from payments_helpers import events_of

from app import config


def test_prices_one_time_recurring_and_tiered_are_checked(shop):
    tiered = {"currency": "usd", "scheme": "tiered", "tiers_mode": "graduated",
              "tiers": [{"up_to": 10, "unit_amount": 500}, {"up_to": None, "unit_amount": 300, "flat_amount": 1000}]}
    made = shop.post("/api/v1/products", {"name": "Seats", "kind": "digital", "prices": [
        {"currency": "usd", "unit_amount": 9900, "nickname": "one-off"},
        {"currency": "EUR", "unit_amount": 1500, "type": "recurring", "interval": "month", "trial_days": 7},
        tiered]})
    one, monthly, tiers = made["prices"]
    assert (one["type"], one["interval"], monthly["currency"], monthly["trial_days"]) == ("one_time", None, "eur", 7)
    assert tiers["unit_amount"] is None and tiers["tiers"][1] == {"up_to": None, "unit_amount": 300,
                                                                  "flat_amount": 1000}
    bad = [({"currency": "usd"}, "price.unit_amount"),
           ({"currency": "usd", "unit_amount": 1, "type": "recurring"}, "price.interval"),
           ({"currency": "usd", "unit_amount": 1, "interval": "month"}, "price.interval"),
           ({"currency": "usd", "scheme": "tiered", "tiers_mode": "volume", "tiers": [{"up_to": 5}]}, "price.tiers"),
           ({"currency": "usd", "scheme": "tiered", "tiers": [{"up_to": None}]}, "price.tiers_mode"),
           ({"currency": "xyz", "unit_amount": 1}, "currency"),
           ({"currency": "usd", "unit_amount": 1.5}, "unit_amount"),
           ({"currency": "usd", "unit_amount": -1}, "unit_amount"),
           ({"currency": "usd", "unit_amount": 1, "tax_rate_id": shop.ws}, "price.tax_rate_id")]
    for body, field in bad:
        r = shop.client.post(f"/api/v1/products/{made['id']}/prices", json=body, headers=shop.h)
        assert r.status_code == 422 and field in json.dumps(r.json()["error"].get("fields")), (body, r.text)
    # an invoice prices 15 seats on the graduated tiers: 10 x 5.00 + 5 x 3.00 + 10.00
    inv = shop.post("/api/v1/invoices/preview", {"contact_id": shop.contact(), "lines": [
        {"price_id": tiers["id"], "quantity": 15}]}, status=200)
    assert inv["total"] == 5000 + 1500 + 1000


def test_amounts_never_change_and_archived_prices_sell_nothing_new(shop):
    product, price = shop.product("Audit", unit_amount=5000)
    patched = shop.patch(f"/api/v1/prices/{price['id']}", {"nickname": "standard", "unit_amount": 1, "currency": "eur"})
    assert patched["unit_amount"] == 5000 and patched["currency"] == "usd" and patched["nickname"] == "standard"
    shop.patch(f"/api/v1/prices/{price['id']}", {"active": False})
    r = shop.client.post("/api/v1/invoices", json={"contact_id": shop.contact(), "lines": [
        {"price_id": price["id"]}]}, headers=shop.h)
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"lines.0.price_id": "is archived"}
    shop.client.delete(f"/api/v1/products/{product['id']}", headers=shop.h)
    assert shop.get("/api/v1/products")["data"] == []
    assert [p["name"] for p in shop.get("/api/v1/products", active="false")["data"]] == ["Audit"]
    r = shop.client.post(f"/api/v1/products/{product['id']}/prices", json={"currency": "usd", "unit_amount": 1},
                         headers=shop.h)
    assert r.status_code == 409
    assert [e["changes"] for e in events_of("product.updated", shop.ws)] == [{"active": {"old": True, "new": False}}]


def test_coupons_are_unique_whatever_the_case_and_say_why_they_do_not_apply(shop):
    coupon = shop.post("/api/v1/coupons", {"name": "Spring", "code": "Spring-26", "percent_off_bp": 1500,
                                           "expires_at": "2020-01-01T00:00:00Z", "starts_at": "2019-01-01T00:00:00Z"})
    r = shop.client.post("/api/v1/coupons", json={"name": "x", "code": "SPRING-26", "percent_off_bp": 1},
                         headers=shop.h)
    assert r.status_code == 409 and r.json()["error"]["fields"] == {"code": "is already used"}
    for body, field in (({"percent_off_bp": 1, "amount_off": 1, "currency": "usd"}, "percent_off_bp"),
                        ({"amount_off": 100}, "currency"), ({"percent_off_bp": 1, "duration": "repeating"},
                                                            "duration_months"),
                        ({"percent_off_bp": 10001}, "percent_off_bp"), ({}, "percent_off_bp")):
        r = shop.client.post("/api/v1/coupons", json={"name": "x", "code": "OTHER", **body}, headers=shop.h)
        assert r.status_code == 422 and field in r.json()["error"]["fields"], (body, r.text)
    ada = shop.contact()
    r = shop.client.post("/api/v1/invoices/preview", headers=shop.h, json={
        "contact_id": ada, "coupon_code": "spring-26", "lines": [{"description": "x", "unit_amount": 100}]})
    assert r.json()["error"]["fields"] == {"coupon_code": "This code has expired."}
    shop.patch(f"/api/v1/coupons/{coupon['id']}", {"expires_at": None})
    ok = shop.post("/api/v1/invoices/preview", {"contact_id": ada, "coupon_code": "spring-26",
                                                "lines": [{"description": "x", "unit_amount": 100}]}, status=200)
    assert ok["discount"] == 15
    euros = shop.post("/api/v1/coupons", {"name": "5 EUR", "code": "FIVE", "amount_off": 500, "currency": "eur"})
    r = shop.client.post("/api/v1/invoices/preview", headers=shop.h, json={
        "contact_id": ada, "coupon_code": euros["code"], "lines": [{"description": "x", "unit_amount": 100}]})
    assert r.json()["error"]["fields"] == {"coupon_code": "This code is for payments in EUR."}


def test_a_coupon_for_some_prices_discounts_only_their_lines_and_once_per_contact_holds(shop):
    _, a = shop.product("A", unit_amount=1000)
    _, b = shop.product("B", unit_amount=1000)
    shop.post("/api/v1/coupons", {"name": "A only", "code": "AONLY", "percent_off_bp": 5000, "price_ids": [a["id"]],
                                  "once_per_contact": True})
    ada = shop.contact()
    inv = shop.invoice(ada, [{"price_id": a["id"]}, {"price_id": b["id"]}], coupon_code="AONLY", send=True)
    assert [x["discount"] for x in inv["lines"]] == [500, 0] and inv["total"] == 1500
    r = shop.client.post("/api/v1/invoices", headers=shop.h, json={"contact_id": ada, "coupon_code": "AONLY",
                                                                   "lines": [{"price_id": a["id"]}]})
    assert r.json()["error"]["fields"] == {"coupon_code": "This code has already been used."}
    r = shop.client.post("/api/v1/invoices", headers=shop.h, json={"contact_id": shop.contact("b@x.co"),
                                                                   "coupon_code": "AONLY",
                                                                   "lines": [{"price_id": b["id"]}]})
    assert r.json()["error"]["fields"] == {"coupon_code": "This code does not apply to these items."}


def test_tax_rates_and_settings_are_for_managers_and_audited(shop):
    tax = shop.post("/api/v1/tax-rates", {"name": "GST", "percentage_bp": 1000, "region": "AU"})
    shop.patch(f"/api/v1/tax-rates/{tax['id']}", {"active": False, "percentage_bp": 1})
    rates = shop.get("/api/v1/tax-rates")["data"]
    assert rates[0]["percentage_bp"] == 1000 and rates[0]["active"] is False  # a rate's percentage never changes
    s = shop.patch("/api/v1/payments/settings", {"default_currency": "EUR", "retry_days": [1, 4], "invoice_due_days": 7,
                                                 "business_name": "Acme"})
    assert (s["default_currency"], s["retry_days"], s["next_invoice_number"]) == ("eur", [1, 4], 1)
    for body in ({"retry_days": [3, 1]}, {"retry_days": list(range(1, 10))}, {"after_retries": "explode"},
                 {"invoice_prefix": "bad prefix!"}, {"default_currency": None}):
        assert shop.client.patch("/api/v1/payments/settings", json=body, headers=shop.h).status_code == 422, body
    assert events_of("payment_settings.updated", shop.ws)[0]["changes"]["default_currency"] == {"old": "usd",
                                                                                                "new": "eur"}
    inv = shop.post("/api/v1/invoices", {"contact_id": shop.contact(), "lines": [{"description": "x",
                                                                                   "unit_amount": 1}]})
    assert inv["currency"] == "eur"


def test_the_capability_matrix_explains_what_is_missing(crm, monkeypatch):
    client, ws, _ = crm
    monkeypatch.setattr(config, "PAYMENTS_FAKE_PROVIDER", False)
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "")
    view = client.get("/api/v1/payments/account", headers={H: ws}).json()
    assert view["account"] is None and not view["capabilities"]["online_payments"]["available"]
    assert {p["key"]: p["available"] for p in view["providers"]} == {"stripe": False, "fake": False}
    stripe_reason = next(p["reason"] for p in view["providers"] if p["key"] == "stripe")
    assert "STRIPE_SECRET_KEY" in stripe_reason
    r = client.post("/api/v1/payments/account/connect", json={"provider": "stripe"}, headers={H: ws})
    assert r.status_code == 409 and r.json()["error"]["code"] == "provider_unavailable"


@pytest.fixture
def stripe_api(monkeypatch):
    server = Receiver()
    monkeypatch.setattr(config, "STRIPE_API_BASE", f"http://127.0.0.1:{server.port}")
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_platform")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRETS", ["whsec_x"])
    yield server
    server.close()


def test_connecting_stripe_stores_only_its_account_id_and_hands_out_the_onboarding_page(crm, stripe_api):
    client, ws, _ = crm
    for payload in ({"id": "acct_1Abc"}, {"url": "https://connect.stripe.com/setup/s/abc"},
                    {"id": "acct_1Abc", "charges_enabled": False, "details_submitted": False}):
        stripe_api.replies.append((200, json.dumps(payload).encode(), {}))
    r = client.post("/api/v1/payments/account/connect", json={"provider": "stripe"}, headers={H: ws})
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["url"] == "https://connect.stripe.com/setup/s/abc"
    assert view["account"]["account_id"] == "acct_1Abc" and view["account"]["status"] == "pending"
    assert "sk_test_platform" not in r.text and "whsec_x" not in r.text
    assert not view["capabilities"]["payment_links"]["available"]
    assert "finish its setup" in view["capabilities"]["payment_links"]["reason"]
    stripe_api.replies.append((200, json.dumps({"id": "acct_1Abc", "charges_enabled": True, "payouts_enabled": True,
                                                "details_submitted": True}).encode(), {}))
    refreshed = client.post("/api/v1/payments/account/refresh", headers={H: ws}).json()
    assert refreshed["account"]["status"] == "active" and refreshed["capabilities"]["payment_links"]["available"]
    assert stripe_api.requests[-1]["path"] == "/v1/accounts/acct_1Abc"


def test_a_stripe_webhook_signed_by_the_platform_secret_updates_the_account(crm, stripe_api):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.payments.providers import base
    client, ws, _ = crm
    for payload in ({"id": "acct_2"}, {"url": "https://connect.stripe.com/x"}, {"id": "acct_2"}):
        stripe_api.replies.append((200, json.dumps(payload).encode(), {}))
    client.post("/api/v1/payments/account/connect", json={"provider": "stripe"}, headers={H: ws})
    body = json.dumps({"id": "evt_acct", "type": "account.updated", "account": "acct_2", "data": {"object": {
        "id": "acct_2", "charges_enabled": True, "payouts_enabled": True, "details_submitted": True}}}).encode()
    hook = TestClient(app)
    assert hook.post("/api/hooks/payments/stripe", content=body).status_code == 401
    r = hook.post("/api/hooks/payments/stripe", content=body, headers={"Stripe-Signature": base.sign("whsec_x", body)})
    assert r.status_code == 200 and r.json()["applied"] == 1
    assert client.get("/api/v1/payments/account", headers={H: ws}).json()["account"]["status"] == "active"
