"""Refunds and transactions (module 21): full and partial refunds never exceed what was captured, even at the same
moment; a provider refund settles from a job or a webhook; refunds made in the provider's dashboard are recorded; a
refund the provider reverses gives the amount back."""
import threading

from payments_helpers import events_of, pay_on_page, run_jobs, webhook

from app.payments.providers import fake


def paid(shop, amount=10000):
    inv = shop.invoice(shop.contact(), [{"description": "Work", "unit_amount": amount}], send=True)
    pay_on_page(inv["public_url"])
    return shop.get("/api/v1/payments/transactions")["data"][0]


def refunds_path(tx):
    return f"/api/v1/payments/transactions/{tx['id']}/refunds"


def test_partial_refunds_add_up_to_the_amount_and_no_further(shop):
    tx = paid(shop)
    assert tx["status"] == "succeeded" and tx["provider"] == "fake"
    first = shop.post(refunds_path(tx), {"amount": 3000, "reason": "requested_by_customer"})
    assert first["refunds"][0]["status"] == "pending" and first["refundable"] == 7000
    r = shop.client.post(refunds_path(tx), json={"amount": 7001}, headers=shop.h)
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"amount": "can be at most 7000"}
    run_jobs("payments.refund")
    rest = shop.post(refunds_path(tx), {})  # no amount: everything left
    assert rest["refunds"][-1]["amount"] == 7000
    run_jobs("payments.refund")
    done = shop.get(f"/api/v1/payments/transactions/{tx['id']}")
    assert done["amount_refunded"] == 10000 and done["refundable"] == 0
    assert [e["amount_refunded"] for e in events_of("payment.refunded", shop.ws)] == [3000, 10000]
    assert shop.client.post(refunds_path(tx), json={"amount": 1}, headers=shop.h).status_code == 422
    invoice = shop.get(f"/api/v1/invoices/{tx['invoice_id']}")
    assert invoice["status"] == "paid"  # the invoice was paid; the money went back, which the payment records


def test_refunds_at_the_same_moment_cannot_exceed_the_payment(shop):
    tx = paid(shop, 1000)
    codes = []

    def refund():
        codes.append(shop.client.post(refunds_path(tx), json={"amount": 600}, headers=shop.h).status_code)

    threads = [threading.Thread(target=refund) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes) == [201, 422, 422, 422]
    run_jobs("payments.refund")
    assert shop.get(f"/api/v1/payments/transactions/{tx['id']}")["amount_refunded"] == 600


def test_an_idempotency_key_makes_a_retried_refund_one_refund(shop):
    tx = paid(shop)
    key = {"Idempotency-Key": "refund-attempt-1"}
    one = shop.post(refunds_path(tx), {"amount": 500}, headers=key)
    two = shop.client.post(refunds_path(tx), json={"amount": 500}, headers={**shop.h, **key})
    assert two.headers.get("Idempotent-Replayed") == "true" and two.json() == one
    assert len(shop.get(f"/api/v1/payments/transactions/{tx['id']}")["refunds"]) == 1


def test_a_payment_recorded_by_hand_is_refunded_at_once(shop):
    inv = shop.invoice(shop.contact(), [{"description": "Work", "unit_amount": 2000}], send=True)
    shop.post(f"/api/v1/invoices/{inv['id']}/payments", {"amount": 2000, "method": "cash"})
    tx = shop.get("/api/v1/payments/transactions")["data"][0]
    assert tx["provider"] == "manual" and tx["method"] == "cash"
    done = shop.post(refunds_path(tx), {"amount": 500})
    assert done["refunds"][0]["status"] == "succeeded" and done["amount_refunded"] == 500


def test_a_refund_made_in_the_providers_dashboard_is_recorded_and_a_reversed_one_given_back(shop):
    tx = paid(shop)
    acct = shop.account_id()
    pi = tx["provider_payment_id"]
    outside = fake.event(acct, "refund.updated", {"provider_refund_id": "re_dash_1", "provider_payment_id": pi,
                                                  "amount": 2500, "status": "succeeded"}, event_id="evt_dash")
    assert webhook(outside).status_code == 200 and webhook(outside).status_code == 200  # and replayed
    seen = shop.get(f"/api/v1/payments/transactions/{tx['id']}")
    assert seen["amount_refunded"] == 2500 and seen["refunds"][0]["note"] == "Refunded at the provider"
    reversed_ = fake.event(acct, "refund.updated", {"provider_refund_id": "re_dash_1", "provider_payment_id": pi,
                                                    "amount": 2500, "status": "failed"}, event_id="evt_dash_fail")
    webhook(reversed_)
    back = shop.get(f"/api/v1/payments/transactions/{tx['id']}")
    assert back["amount_refunded"] == 0 and back["refundable"] == 10000 and back["refunds"][0]["status"] == "failed"
    assert [e["failure_message"] for e in events_of("refund.failed", shop.ws)] != []


def test_only_succeeded_payments_are_refunded_and_transactions_filter(shop):
    tx = paid(shop)
    other = shop.invoice(shop.contact("b@x.co"), [{"description": "W", "unit_amount": 100}], send=True)
    pay_on_page(other["public_url"], outcome="failed")
    failed = shop.get("/api/v1/payments/transactions", status="failed")["data"]
    assert len(failed) == 1 and failed[0]["failure_code"] == "card_declined"
    r = shop.client.post(refunds_path(failed[0]), json={}, headers=shop.h)
    assert r.status_code in (409, 422)
    assert [t["id"] for t in shop.get("/api/v1/payments/transactions", invoice_id=tx["invoice_id"])["data"]] == \
        [tx["id"]]
    assert tx["invoice_number"] == "INV-0001" and tx["contact"]["display_name"] == "Ada"
    summary = shop.get("/api/v1/payments/summary")
    assert summary["currencies"][0]["gross_volume"] == 10000 and summary["currencies"][0]["outstanding"] == 100
