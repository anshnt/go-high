"""Payment links and the hosted checkout (module 21): the page, amounts worked out on the server whatever is posted,
quantity bounds, discount codes, the contact it makes, spam and rate limits, and an unpaid checkout lapsing."""
from payments_helpers import complete, events_of, queued, run_jobs, visitor
from sqlalchemy import text

from app import config
from app.db import SessionLocal
from app.payments.providers import fake


def make_link(shop, **extra):
    _, price = shop.product("Workshop seat", unit_amount=2500)
    body = {"name": "Spring workshop", "items": [{"price_id": price["id"], "quantity": 1, "adjustable": True,
                                                  "min": 1, "max": 5}], **extra}
    return shop.post("/api/v1/payment-links", body), price


def checkout(key, **form):
    data = {"name": "Grace Hopper", "email": "grace@example.com", "qty_0": "2", **form}
    return visitor().post(f"/api/public/pay/{key}/checkout", data=data)


def key_of(link):
    return link["public_path"].rsplit("/", 1)[1]


def test_the_page_shows_the_items_and_the_checkout_charges_what_the_server_works_out(shop):
    link, price = make_link(shop)
    page = visitor().get(link["public_path"])
    assert page.status_code == 200 and "Spring workshop" in page.text and "USD 25.00" in page.text
    assert "form-action 'self' https://checkout.stripe.com" in page.headers["content-security-policy"]
    # a tampered form: an amount, a price and a currency of the visitor's own are ignored
    r = checkout(key_of(link), amount="1", unit_amount="1", currency="jpy", price_id="x", total="0")
    assert r.status_code == 303
    session = fake.unseal(r.headers["location"].rsplit("/", 1)[1])
    assert (session["m"], session["c"]) == (5000, "usd")  # 2 x 25.00, from the stored price
    done = complete(visitor(), r.headers["location"])
    assert done.headers["location"].endswith(f"/pay/{key_of(link)}/done?checkout=success")
    invoice = shop.get("/api/v1/invoices")["data"][0]
    assert invoice["status"] == "paid" and invoice["number"] == "INV-0001" and invoice["total"] == 5000
    assert invoice["billing_reason"] == "payment_link" and invoice["contact"]["display_name"] == "Grace Hopper"
    contacts = shop.get("/api/v1/objects/contact/records")["data"]
    assert [c["values"]["email"] for c in contacts] == ["grace@example.com"]
    thanks = visitor().get(f"/pay/{key_of(link)}/done")
    assert thanks.status_code == 200 and "Thank you" in thanks.text


def test_quantities_outside_the_bounds_and_missing_details_are_refused_on_the_page(shop):
    link, _ = make_link(shop)
    for form, words in (({"qty_0": "9"}, "between 1 and 5"), ({"qty_0": "two"}, "whole number"),
                        ({"email": ""}, "name and email"), ({"email": "not-an-email"}, "check your email")):
        r = checkout(key_of(link), **form)
        assert r.status_code == 422 and words in r.text, (form, r.text[-500:])
    assert shop.get("/api/v1/invoices", checkouts="true")["data"] == []


def test_a_discount_code_works_on_a_link_and_is_given_back_when_the_checkout_lapses(shop):
    link, price = make_link(shop, allow_coupons=True)
    shop.post("/api/v1/coupons", {"name": "Early bird", "code": "EARLY", "amount_off": 1000, "currency": "usd",
                                  "max_redemptions": 1})
    r = checkout(key_of(link), coupon="early")
    assert fake.unseal(r.headers["location"].rsplit("/", 1)[1])["m"] == 4000
    assert shop.get("/api/v1/coupons")["data"][0]["times_redeemed"] == 1
    used_up = checkout(key_of(link), coupon="EARLY", email="other@example.com")
    assert used_up.status_code == 422 and "used up" in used_up.text
    [job] = queued("payments.expire_checkout")
    run_jobs("payments.expire_checkout")
    lapsed = shop.get("/api/v1/invoices", checkouts="true")["data"][0]
    assert lapsed["status"] == "void" and lapsed["number"] is None and job
    assert shop.get("/api/v1/coupons")["data"][0]["times_redeemed"] == 0
    assert shop.get("/api/v1/invoices")["data"] == []  # unpaid checkouts stay out of the invoice list
    assert [e["reason"] for e in events_of("invoice.voided", shop.ws)] == ["checkout_expired"]


def test_a_full_discount_skips_the_provider(shop):
    link, _ = make_link(shop, allow_coupons=True)
    shop.post("/api/v1/coupons", {"name": "Free", "code": "FREE", "percent_off_bp": 10000})
    r = checkout(key_of(link), coupon="FREE")
    assert r.status_code == 303 and r.headers["location"].endswith("/done")
    assert shop.get("/api/v1/invoices")["data"][0]["status"] == "paid"


def test_spam_and_floods_are_stopped(shop, monkeypatch):
    link, _ = make_link(shop)
    bot = checkout(key_of(link), website="http://spam.example")
    assert bot.status_code == 200 and "Thank you" in bot.text
    with SessionLocal() as db:
        assert db.scalar(text("SELECT count(*) FROM invoices")) == 0
    monkeypatch.setattr(config, "CHECKOUT_MAX_PER_IP", 2)
    checkout(key_of(link))
    r = checkout(key_of(link))
    assert r.status_code == 429


def test_a_switched_off_link_or_an_unknown_key_takes_nothing(shop):
    link, _ = make_link(shop)
    shop.patch(f"/api/v1/payment-links/{link['id']}", {"active": False})
    assert visitor().get(link["public_path"]).status_code == 410
    assert checkout(key_of(link)).status_code == 409
    assert visitor().get("/pay/unknown-key").status_code == 404
    assert visitor().post("/api/public/pay/unknown-key/checkout", data={}).status_code == 404


def test_without_a_connected_provider_the_page_says_so(shop):
    link, _ = make_link(shop)
    shop.client.delete("/api/v1/payments/account", headers=shop.h)
    page = visitor().get(link["public_path"])
    assert "cannot take payments right now" in page.text
    assert checkout(key_of(link)).status_code == 409


def test_links_are_checked_when_saved(shop):
    _, usd = shop.product("A", unit_amount=100)
    _, eur = shop.product("B", currency="eur", unit_amount=100)
    plan = shop.monthly()
    for items, field in (([{"price_id": usd["id"]}, {"price_id": eur["id"]}], "items"),
                         ([{"price_id": plan["id"]}, {"price_id": usd["id"]}], "items"),
                         ([{"price_id": usd["id"], "adjustable": True, "quantity": 9, "max": 3}], "items.0.quantity"),
                         ([{"price_id": shop.ws}], "items.0.price_id")):
        r = shop.client.post("/api/v1/payment-links", json={"name": "x", "items": items}, headers=shop.h)
        assert r.status_code == 422 and field in r.json()["error"]["fields"], (items, r.text)
    made = shop.post("/api/v1/payment-links", {"name": "Plan", "items": [{"price_id": plan["id"]}]})
    assert made["public_url"].endswith(made["public_path"]) and len(key_of(made)) >= 20
