"""Subscriptions (module 21): the state machine end to end on the test provider: first payment, renewals charging the
kept card, dunning retries to cancel or unpaid, trials, cancel now and at period end, reactivation, plan changes with
proration and credit, coupons over several periods, and jobs that run late or twice."""
from datetime import datetime, timedelta

import pytest
from payments_helpers import events_of, pay_on_page, queued, run_jobs
from sqlalchemy import text

from app.db import SessionLocal
from app.payments import routes_billing


def subscribe(shop, price, contact=None, **extra):
    return shop.post("/api/v1/subscriptions", {"contact_id": contact or shop.contact(), "price_id": price["id"],
                                               **extra})


def first_invoice(shop, sub):
    return shop.get(f"/api/v1/invoices/{sub['latest_invoice_id']}")


def active_with_card(shop, price=None, **extra):
    """A subscription whose first invoice was paid on its page, so the card is kept."""
    price = price or shop.monthly()
    sub = subscribe(shop, price, **extra)
    pay_on_page(first_invoice(shop, sub)["public_url"])
    return shop.get(f"/api/v1/subscriptions/{sub['id']}")


def card(number: str) -> None:
    with SessionLocal() as db:
        db.execute(text("UPDATE payment_customers SET payment_method_id = :pm"), {"pm": number})
        db.commit()


def at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def test_a_new_subscription_is_incomplete_until_its_first_invoice_is_paid_then_keeps_the_card(shop):
    price = shop.monthly(amount=2000)
    sub = subscribe(shop, price)
    assert sub["status"] == "incomplete" and sub["amount"] == 2000 and sub["card"] is None
    inv = first_invoice(shop, sub)
    assert inv["status"] == "open" and inv["number"] == "INV-0001" and inv["billing_reason"] == "subscription_create"
    assert inv["period_start"] == sub["current_period_start"] and inv["period_end"] == sub["current_period_end"]
    pay_on_page(inv["public_url"])
    sub = shop.get(f"/api/v1/subscriptions/{sub['id']}")
    assert sub["status"] == "active" and sub["card"] == {"brand": "visa", "last4": "4242"}
    assert [e["reason"] for e in events_of("subscription.updated", shop.ws)] == ["invoice_paid"]
    assert [e["status"] for e in events_of("subscription.created", shop.ws)] == ["incomplete"]


def test_a_renewal_bills_the_next_period_from_the_anchor_and_charges_the_kept_card(shop):
    sub = active_with_card(shop)
    end = sub["current_period_end"]
    run_jobs("payments.renew")
    renewed = shop.get(f"/api/v1/subscriptions/{sub['id']}")
    assert renewed["status"] == "active" and renewed["current_period_start"] == end
    latest = shop.get(f"/api/v1/invoices/{renewed['latest_invoice_id']}")
    assert latest["billing_reason"] == "subscription_cycle" and latest["status"] == "paid"
    assert latest["number"] == "INV-0002" and latest["period_start"] == end
    assert [e["amount"] for e in events_of("payment.succeeded", shop.ws)] == [2000, 2000]
    assert len(queued("payments.renew")) == 1  # the next renewal, at the end of the new period


def test_dunning_retries_on_the_retry_days_then_cancels(shop):
    sub = active_with_card(shop)
    card("pm_fake_decline")
    run_jobs("payments.renew")
    renewed = shop.get(f"/api/v1/subscriptions/{sub['id']}")
    inv = shop.get(f"/api/v1/invoices/{renewed['latest_invoice_id']}")
    assert renewed["status"] == "past_due" and inv["status"] == "open" and inv["attempt_count"] == 1
    issued = at(inv["issued_at"])
    seen = [at(inv["next_attempt_at"]) - issued]
    for _ in range(2):
        run_jobs("payments.collect")
        inv = shop.get(f"/api/v1/invoices/{inv['id']}")
        seen.append(at(inv["next_attempt_at"]) - issued)
    assert seen == [timedelta(days=1), timedelta(days=3), timedelta(days=5)]  # the default retry days
    run_jobs("payments.collect")
    inv = shop.get(f"/api/v1/invoices/{inv['id']}")
    ended = shop.get(f"/api/v1/subscriptions/{sub['id']}")
    assert inv["status"] == "uncollectible" and inv["attempt_count"] == 4 and ended["status"] == "canceled"
    failed = events_of("payment.failed", shop.ws)
    assert [(e["attempt"], e["final"]) for e in failed] == [(1, False), (2, False), (3, False), (4, True)]
    assert all(e["failure_code"] == "card_declined" for e in failed)
    assert events_of("subscription.canceled", shop.ws)[-1]["reason"] == "payment_failed"
    assert queued("payments.collect") == []


def test_after_the_retries_an_unpaid_subscription_comes_back_when_the_card_works_again(shop):
    shop.patch("/api/v1/payments/settings", {"retry_days": [2], "after_retries": "unpaid"})
    sub = active_with_card(shop)
    card("pm_fake_decline")
    run_jobs("payments.renew")
    run_jobs("payments.collect")
    unpaid = shop.get(f"/api/v1/subscriptions/{sub['id']}")
    assert unpaid["status"] == "unpaid"
    run_jobs("payments.renew")  # an unpaid subscription bills nothing more, it only moves its period on
    assert shop.get("/api/v1/invoices", subscription_id=sub["id"])["data"][0]["id"] == unpaid["latest_invoice_id"]
    r = shop.client.post(f"/api/v1/subscriptions/{sub['id']}/reactivate", headers=shop.h)
    assert r.status_code == 200  # tries the card again (still declined)
    run_jobs("payments.collect")
    assert shop.get(f"/api/v1/subscriptions/{sub['id']}")["status"] == "unpaid"
    card("pm_fake_visa")
    shop.post(f"/api/v1/subscriptions/{sub['id']}/reactivate", status=200)
    run_jobs("payments.collect")
    assert shop.get(f"/api/v1/subscriptions/{sub['id']}")["status"] == "active"


def test_a_past_due_subscription_is_active_again_when_the_customer_pays_the_link(shop):
    sub = active_with_card(shop)
    card("pm_fake_decline")
    run_jobs("payments.renew")
    past_due = shop.get(f"/api/v1/subscriptions/{sub['id']}")
    pay_on_page(shop.get(f"/api/v1/invoices/{past_due['latest_invoice_id']}")["public_url"])
    assert shop.get(f"/api/v1/subscriptions/{sub['id']}")["status"] == "active"
    run_jobs("payments.collect")  # the retry planned before finds the invoice paid and does nothing
    assert len(events_of("payment.failed", shop.ws)) == 1


def test_a_trial_bills_nothing_until_it_ends_and_an_invoice_without_a_card_goes_past_due_by_its_date(shop):
    price = shop.monthly(trial_days=14)
    sub = subscribe(shop, price)
    assert sub["status"] == "trialing" and sub["latest_invoice_id"] is None
    assert at(sub["trial_end"]) - at(sub["created_at"]) == pytest.approx(timedelta(days=14), abs=timedelta(seconds=5))
    assert shop.get("/api/v1/invoices")["data"] == []
    run_jobs("payments.renew")
    after = shop.get(f"/api/v1/subscriptions/{sub['id']}")
    inv = shop.get(f"/api/v1/invoices/{after['latest_invoice_id']}")
    assert after["status"] == "active" and after["current_period_start"] == sub["trial_end"]
    assert inv["status"] == "open" and at(inv["due_at"]) - at(inv["issued_at"]) == timedelta(days=14)
    run_jobs("payments.collect")  # its due date: no card to charge, so it counts as a failed attempt
    assert shop.get(f"/api/v1/subscriptions/{sub['id']}")["status"] == "past_due"
    assert events_of("payment.failed", shop.ws) == []  # no payment was tried


def test_cancel_at_period_end_reactivate_and_cancel_now(shop):
    sub = active_with_card(shop)
    path = f"/api/v1/subscriptions/{sub['id']}"
    assert shop.post(f"{path}/cancel", {"at_period_end": True}, status=200)["cancel_at_period_end"] is True
    assert shop.post(f"{path}/reactivate", status=200)["cancel_at_period_end"] is False
    shop.post(f"{path}/cancel", {"at_period_end": True, "reason": "moving away"}, status=200)
    run_jobs("payments.renew")
    ended = shop.get(path)
    assert ended["status"] == "canceled" and len(shop.get("/api/v1/invoices")["data"]) == 1  # no new invoice
    assert events_of("subscription.canceled", shop.ws)[-1]["reason"] == "cancel_at_period_end"
    assert shop.client.post(f"{path}/cancel", json={}, headers=shop.h).status_code == 409
    assert shop.client.post(f"{path}/reactivate", headers=shop.h).status_code == 409


def test_cancelling_now_voids_what_is_owed_and_makes_planned_jobs_harmless(shop):
    sub = subscribe(shop, shop.monthly())
    inv = first_invoice(shop, sub)
    shop.post(f"/api/v1/subscriptions/{sub['id']}/cancel", {"at_period_end": False}, status=200)
    assert shop.get(f"/api/v1/invoices/{inv['id']}")["status"] == "void"
    before = len(events_of("subscription.updated", shop.ws))
    run_jobs("payments.renew", "payments.collect")  # planned before the cancel: they find the cycle moved on
    assert shop.get(f"/api/v1/subscriptions/{sub['id']}")["status"] == "canceled"
    assert len(events_of("subscription.updated", shop.ws)) == before


def test_an_incomplete_subscription_expires_when_its_first_period_ends_unpaid(shop):
    sub = subscribe(shop, shop.monthly())
    shop.patch("/api/v1/payments/settings", {"invoice_due_days": 60})  # no collection attempt before the period ends
    run_jobs("payments.renew")
    gone = shop.get(f"/api/v1/subscriptions/{sub['id']}")
    assert gone["status"] == "incomplete_expired" and first_invoice(shop, sub)["status"] == "void"


def halfway(monkeypatch, sub):
    start, end = at(sub["current_period_start"]), at(sub["current_period_end"])
    monkeypatch.setattr(routes_billing, "now", lambda: start + (end - start) / 2)


def test_an_upgrade_halfway_charges_the_difference_for_the_rest_of_the_period(shop, monkeypatch):
    sub = active_with_card(shop, shop.monthly("Basic", 2000))
    pro = shop.monthly("Pro", 5000)
    halfway(monkeypatch, sub)
    changed = shop.patch(f"/api/v1/subscriptions/{sub['id']}", {"price_id": pro["id"]})
    inv = shop.get(f"/api/v1/invoices/{changed['invoices'][0]['id']}")  # newest first: the plan change's
    assert inv["billing_reason"] == "subscription_update"
    assert [(x["amount"], x["proration"]) for x in inv["lines"]] == [(-1000, True), (2500, True)]
    assert inv["total"] == 1500 and changed["price_id"] == pro["id"]
    run_jobs("payments.collect")
    assert shop.get(f"/api/v1/invoices/{inv['id']}")["status"] == "paid"
    assert events_of("subscription.updated", shop.ws)[-1]["reason"] == "plan_changed"


def test_a_downgrade_halfway_becomes_credit_on_the_next_invoice(shop, monkeypatch):
    sub = active_with_card(shop, shop.monthly("Pro", 5000))
    basic = shop.monthly("Basic", 2000)
    halfway(monkeypatch, sub)
    changed = shop.patch(f"/api/v1/subscriptions/{sub['id']}", {"price_id": basic["id"]})
    credit_note = shop.get(f"/api/v1/invoices/{changed['invoices'][0]['id']}")
    assert credit_note["total"] == 0 and credit_note["status"] == "paid" and changed["credit_balance"] == 1500
    run_jobs("payments.renew")
    renewed = shop.get(f"/api/v1/subscriptions/{sub['id']}")
    nxt = shop.get(f"/api/v1/invoices/{renewed['latest_invoice_id']}")
    assert (nxt["subtotal"], nxt["credit_applied"], nxt["total"]) == (2000, 1500, 500)
    assert renewed["credit_balance"] == 0 and nxt["status"] == "paid"


def test_plan_changes_are_checked(shop):
    sub = active_with_card(shop)
    yearly = shop.product("Yearly", unit_amount=20000, type="recurring", interval="year")[1]
    _, once = shop.product("Setup", unit_amount=100)
    for price in (yearly, once):
        r = shop.client.patch(f"/api/v1/subscriptions/{sub['id']}", json={"price_id": price["id"]}, headers=shop.h)
        assert r.status_code == 422, r.text
    r = shop.client.post("/api/v1/subscriptions", json={"contact_id": shop.contact("b@x.co"), "price_id": once["id"]},
                         headers=shop.h)
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"price_id": "is not a recurring price"}
    more = shop.patch(f"/api/v1/subscriptions/{sub['id']}", {"quantity": 3, "prorate": False})
    assert more["quantity"] == 3 and more["amount"] == 6000 and len(more["invoices"]) == 1  # applies next period


def test_a_repeating_coupon_discounts_the_periods_it_covers_and_no_more(shop):
    shop.post("/api/v1/coupons", {"name": "Half for two months", "code": "HALF2", "percent_off_bp": 5000,
                                  "duration": "repeating", "duration_months": 2})
    sub = active_with_card(shop, shop.monthly(amount=2000), coupon_code="half2")
    totals = [first_invoice(shop, sub)["total"]]
    for _ in range(2):
        run_jobs("payments.renew")
        latest = shop.get(f"/api/v1/subscriptions/{sub['id']}")["latest_invoice_id"]
        totals.append(shop.get(f"/api/v1/invoices/{latest}")["total"])
    assert totals == [1000, 1000, 2000]
    assert shop.get("/api/v1/coupons")["data"][0]["times_redeemed"] == 1  # once per subscription, not per invoice


def test_a_collection_job_that_runs_twice_charges_once(shop):
    sub = active_with_card(shop)
    run_jobs("payments.renew")
    with SessionLocal() as db:  # the same attempt queued again, as a crash and retry would
        db.execute(text("INSERT INTO jobs (kind, payload) SELECT kind, payload FROM jobs WHERE kind = "
                        "'payments.collect' ORDER BY id DESC LIMIT 1"))
        db.commit()
    run_jobs("payments.collect")
    assert len(events_of("payment.succeeded", shop.ws)) == 2  # the first invoice and one renewal
    with SessionLocal() as db:
        assert db.scalar(text("SELECT count(*) FROM payments WHERE subscription_id = :s"), {"s": sub["id"]}) == 2
