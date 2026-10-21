"""Provider webhooks (module 21): signatures and replays are refused or ignored, every event is applied once whatever
the order, a payment that is not committed yet is asked for again, and money nobody needed goes back."""
import time

from payments_helpers import events_of, path_of, payment_event, queued, run_jobs, visitor, webhook
from sqlalchemy import text

from app.db import SessionLocal
from app.payments.providers import base, fake


def open_checkout(shop, amount=5000):
    """An issued invoice and the pending payment of a checkout started on its page: (invoice, payment id)."""
    inv = shop.invoice(shop.contact(), [{"description": "Work", "unit_amount": amount}], send=True)
    start = visitor().post(path_of(inv["public_url"]).replace("/invoice/", "/api/public/invoices/") + "/checkout")
    assert start.status_code == 303
    session = fake.unseal(start.headers["location"].rsplit("/", 1)[1])
    return inv, session["p"]


def test_unsigned_wrongly_signed_stale_and_tampered_webhooks_are_refused(shop):
    inv, pid = open_checkout(shop)
    body = payment_event(shop.account_id(), pid, 5000)
    assert webhook(body, headers={}).status_code == 401
    assert webhook(body, headers={"fake-signature": base.sign("not-the-secret", body)}).status_code == 401
    stale = {"fake-signature": base.sign(fake.secret(), body, at=int(time.time()) - 600)}
    assert webhook(body, headers=stale).status_code == 401
    tampered = body.replace(b"5000", b"9")
    assert webhook(tampered, headers=fake.signed(body)).status_code == 401
    assert webhook(b"not json", headers=fake.signed(b"not json")).status_code == 400
    assert shop.get(f"/api/v1/invoices/{inv['id']}")["status"] == "open"  # nothing was applied


def test_a_replayed_event_is_applied_once(shop):
    inv, pid = open_checkout(shop)
    body = payment_event(shop.account_id(), pid, 5000, event_id="evt_once")
    for _ in range(3):
        assert webhook(body).status_code == 200
    assert len(events_of("payment.succeeded", shop.ws)) == 1 and len(events_of("invoice.paid", shop.ws)) == 1
    # a different event with the same news (the provider sends several per payment) fulfils nothing twice either
    assert webhook(payment_event(shop.account_id(), pid, 5000, event_id="evt_other")).status_code == 200
    assert len(events_of("payment.succeeded", shop.ws)) == 1
    with SessionLocal() as db:
        assert db.scalar(text("SELECT amount_paid FROM invoices WHERE id = :i"), {"i": inv["id"]}) == 5000
        assert db.scalar(text("SELECT count(*) FROM payment_events WHERE workspace_id = :w"), {"w": shop.ws}) == 2


def test_out_of_order_a_late_failure_never_undoes_a_success(shop):
    inv, pid = open_checkout(shop)
    acct = shop.account_id()
    assert webhook(payment_event(acct, pid, 5000, event_id="evt_ok")).status_code == 200
    assert webhook(payment_event(acct, pid, 5000, status="failed", event_id="evt_late_fail",
                                 failure_code="card_declined")).status_code == 200
    tx = shop.get("/api/v1/payments/transactions")["data"][0]
    assert tx["status"] == "succeeded" and tx["failure_code"] is None
    assert shop.get(f"/api/v1/invoices/{inv['id']}")["status"] == "paid"


def test_a_failure_then_a_success_on_the_same_payment_ends_paid(shop):
    inv, pid = open_checkout(shop)
    acct = shop.account_id()
    webhook(payment_event(acct, pid, 5000, status="failed", event_id="evt_f", failure_code="card_declined"))
    assert shop.get("/api/v1/payments/transactions")["data"][0]["status"] == "failed"
    assert [e["failure_code"] for e in events_of("payment.failed", shop.ws)] == ["card_declined"]
    webhook(payment_event(acct, pid, 5000, event_id="evt_s"))  # the customer tried another card on the same page
    assert shop.get(f"/api/v1/invoices/{inv['id']}")["status"] == "paid"


def test_an_event_for_a_payment_not_committed_yet_is_asked_for_again(shop):
    body = payment_event(shop.account_id(), "8d6f1b52-0000-4000-8000-000000000000", 5000, event_id="evt_early")
    assert webhook(body).status_code == 409
    with SessionLocal() as db:  # nothing recorded, so the provider's retry is applied when it comes
        assert db.scalar(text("SELECT count(*) FROM payment_events WHERE event_id = 'evt_early'")) == 0


def test_events_for_unknown_accounts_and_payments_we_did_not_start_are_acknowledged(shop):
    body = payment_event("acct_nobody", "8d6f1b52-0000-4000-8000-000000000000", 5000)
    assert webhook(body).status_code == 200
    stray = fake.event(shop.account_id(), "payment.succeeded", {"provider_payment_id": "pi_outside", "amount": 1,
                                                                "currency": "usd"})
    assert webhook(stray).status_code == 200
    assert shop.get("/api/v1/payments/transactions")["data"] == []


def test_a_reported_amount_that_differs_is_not_fulfilled(shop):
    inv, pid = open_checkout(shop, 5000)
    assert webhook(payment_event(shop.account_id(), pid, 1)).status_code == 200
    assert shop.get(f"/api/v1/invoices/{inv['id']}")["status"] == "open"
    assert events_of("payment.succeeded", shop.ws) == []


def test_an_account_from_another_workspace_cannot_pay_this_workspaces_invoice(shop, make_user, monkeypatch):
    inv, pid = open_checkout(shop)
    other, ids = make_user("eve@example.com")
    r = other.post("/api/v1/payments/account/connect", json={"provider": "fake"},
                   headers={"X-Workspace-Id": ids["workspace_id"]})
    eve_account = r.json()["account"]["account_id"]
    assert webhook(payment_event(eve_account, pid, 5000)).status_code == 409  # not found in Eve's workspace
    assert shop.get(f"/api/v1/invoices/{inv['id']}")["status"] == "open"


def test_two_checkouts_both_paid_refund_the_second_automatically(shop):
    inv, first = open_checkout(shop)
    with SessionLocal() as db:  # the first page is older than reuse allows: a second visit opens a new checkout
        db.execute(text("UPDATE payments SET created_at = now() - interval '2 hours' WHERE id = :p"), {"p": first})
        db.commit()
    start = visitor().post(path_of(inv["public_url"]).replace("/invoice/", "/api/public/invoices/") + "/checkout")
    second = fake.unseal(start.headers["location"].rsplit("/", 1)[1])["p"]
    assert second != first
    acct = shop.account_id()
    webhook(payment_event(acct, first, 5000))
    webhook(payment_event(acct, second, 5000))
    invoice = shop.get(f"/api/v1/invoices/{inv['id']}")
    assert invoice["status"] == "paid" and invoice["amount_paid"] == 5000
    [refund_job] = queued("payments.refund")
    run_jobs("payments.refund")
    refunded = shop.get(f"/api/v1/payments/transactions/{second}")
    assert refunded["amount_refunded"] == 5000 and refunded["refunds"][0]["reason"] == "duplicate"
    assert refunded["refunds"][0]["status"] == "succeeded" and refund_job


def test_a_payment_after_the_invoice_was_voided_is_refunded(shop):
    inv, pid = open_checkout(shop)
    shop.post(f"/api/v1/invoices/{inv['id']}/void", {}, status=200)
    webhook(payment_event(shop.account_id(), pid, 5000))
    run_jobs("payments.refund")
    tx = shop.get(f"/api/v1/payments/transactions/{pid}")
    assert tx["status"] == "succeeded" and tx["amount_refunded"] == 5000
    assert shop.get(f"/api/v1/invoices/{inv['id']}")["status"] == "void"


def test_account_updates_change_what_the_workspace_can_do(shop):
    acct = shop.account_id()
    assert shop.get("/api/v1/payments/account")["capabilities"]["online_payments"]["available"]
    shop.client.delete("/api/v1/payments/account", headers=shop.h)
    caps = shop.get("/api/v1/payments/account")["capabilities"]
    assert not caps["payment_links"]["available"] and "Connect" in caps["payment_links"]["reason"]
    assert caps["invoices"]["available"] and caps["manual_payments"]["available"]
    assert webhook(fake.event(acct, "account.updated", {})).status_code == 200
    assert shop.get("/api/v1/payments/account")["account"]["status"] == "disconnected"  # stays disconnected


def test_the_test_provider_does_not_exist_where_it_is_switched_off(shop, monkeypatch):
    from app import config
    body = payment_event(shop.account_id(), "x", 1)
    monkeypatch.setattr(config, "PAYMENTS_FAKE_PROVIDER", False)
    assert webhook(body).status_code == 404
    assert visitor().get("/api/public/payments/fake/anything").status_code == 404
    assert visitor().post("/api/hooks/payments/paypal", content=b"{}").status_code == 404
