"""Invoices (module 21): drafts, totals with tax and coupons, numbering, sending, the hosted page and print view,
voiding, payments recorded by hand, and paying online through the test provider."""
import threading

from helpers import H
from payments_helpers import events_of, path_of, pay_on_page, visitor
from sqlalchemy import text

from app.db import SessionLocal


def test_a_draft_with_tax_and_a_coupon_has_server_worked_totals(shop):
    tax = shop.post("/api/v1/tax-rates", {"name": "Sales tax", "percentage_bp": 825})
    _, price = shop.product("Consulting", unit_amount=12500, tax_rate_id=tax["id"])
    shop.post("/api/v1/coupons", {"name": "Ten off", "code": "TEN", "percent_off_bp": 1000})
    ada = shop.contact()
    inv = shop.invoice(ada, [{"price_id": price["id"], "quantity": 2},
                             {"description": "Travel", "unit_amount": 4999}], coupon_code="ten")
    assert inv["status"] == "draft" and inv["number"] is None and inv["public_url"] is None
    assert inv["subtotal"] == 25000 + 4999
    assert inv["discount"] == 3000  # 10 % of 29999 = 2999.9 -> 3000
    consulting, travel = inv["lines"]
    assert consulting["discount"] + travel["discount"] == 3000
    assert consulting["tax"] == round((25000 - consulting["discount"]) * 0.0825 + 1e-9) and travel["tax"] == 0
    assert inv["total"] == 29999 - 3000 + consulting["tax"]
    assert inv["contact"]["display_name"] == "Ada"
    preview = shop.post("/api/v1/invoices/preview", {"contact_id": ada, "lines": [{"price_id": price["id"]}]},
                        status=200)
    assert preview["total"] == 12500 + 1031  # 8.25 % of 125.00 = 10.3125 -> 10.31
    assert len(shop.get("/api/v1/invoices")["data"]) == 1  # the preview saved nothing


def test_bad_lines_coupons_and_contacts_are_refused_with_paths(shop):
    ada = shop.contact()
    _, eur = shop.product("Euro thing", currency="eur", unit_amount=100)
    r = shop.client.post("/api/v1/invoices", headers=shop.h, json={
        "contact_id": ada, "lines": [{"price_id": eur["id"]}, {"description": "x"}, {"unit_amount": 5}]})
    assert r.status_code == 422
    assert set(r.json()["error"]["fields"]) == {"lines.0.price_id", "lines.1.unit_amount", "lines.2.description"}
    r = shop.client.post("/api/v1/invoices", headers=shop.h, json={"contact_id": ada, "coupon_code": "NOPE",
                                                                   "lines": [{"description": "x", "unit_amount": 1}]})
    assert r.json()["error"]["fields"] == {"coupon_code": "This code does not exist."}
    r = shop.client.post("/api/v1/invoices", headers=shop.h, json={"contact_id": shop.ids["workspace_id"],
                                                                   "lines": []})
    assert r.json()["error"]["fields"] == {"contact_id": "is not a contact you can see"}
    r = shop.client.post("/api/v1/invoices", headers=shop.h, json={"contact_id": ada, "lines": [
        {"description": "x", "unit_amount": -5}]})
    assert r.status_code == 422  # a customer cannot be billed a negative amount


def test_numbers_are_given_on_send_in_order_without_gaps(shop):
    ada = shop.contact()
    line = [{"description": "Work", "unit_amount": 1000}]
    drafts = [shop.invoice(ada, line) for _ in range(3)]
    shop.client.delete(f"/api/v1/invoices/{drafts[1]['id']}", headers=shop.h)  # a draft never had a number
    sent = [shop.post(f"/api/v1/invoices/{d['id']}/send", status=200) for d in (drafts[2], drafts[0])]
    assert [s["number"] for s in sent] == ["INV-0001", "INV-0002"]
    assert all(s["status"] == "open" and s["public_url"] and s["due_at"] for s in sent)
    shop.patch("/api/v1/payments/settings", {"invoice_prefix": "ACME-"})
    assert shop.invoice(ada, line, send=True)["number"] == "ACME-0003"
    r = shop.client.patch(f"/api/v1/invoices/{sent[0]['id']}", json={"memo": "x"}, headers=shop.h)
    assert r.status_code == 409  # issued invoices never change
    assert [e["number"] for e in events_of("invoice.sent", shop.ws)] == ["INV-0001", "INV-0002", "ACME-0003"]


def test_two_sends_at_the_same_moment_get_different_numbers(shop):
    ada = shop.contact()
    drafts = [shop.invoice(ada, [{"description": "Work", "unit_amount": 1000}]) for _ in range(6)]
    results = []

    def send(i):
        results.append(shop.client.post(f"/api/v1/invoices/{drafts[i]['id']}/send", headers=shop.h).json()["number"])

    threads = [threading.Thread(target=send, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [f"INV-{n:04d}" for n in range(1, 7)]


def test_the_hosted_page_is_the_print_view_and_its_link_cannot_be_guessed(shop):
    tax = shop.post("/api/v1/tax-rates", {"name": "VAT", "percentage_bp": 2000, "inclusive": True})
    shop.patch("/api/v1/payments/settings", {"business_name": "Acme <Studio>", "invoice_footer": "Thanks!"})
    ada = shop.contact()
    inv = shop.invoice(ada, [{"description": "Design <b>work</b>", "unit_amount": 12000, "tax_rate_id": tax["id"]}],
                       send=True, memo="Net 14")
    page = visitor().get(path_of(inv["public_url"]))
    assert page.status_code == 200
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "no-referrer" and page.headers["cache-control"] == "no-store"
    html = page.text
    assert "Acme &lt;Studio&gt;" in html and "Design &lt;b&gt;work&lt;/b&gt;" in html  # escaped, never markup
    assert "INV-0001" in html and "USD 120.00" in html and "VAT (20%, included)" in html and "USD 20.00" in html
    assert "Thanks!" in html and "Net 14" in html and "Print or save as PDF" in html and "Pay USD 120.00" in html
    token = path_of(inv["public_url"]).split("/")[-1]
    ws, inv_id, mac = token.split(".")
    for forged in (f"{ws}.{inv_id}.{'0' * 32}", f"{ws}.{inv_id}", "nonsense", f"{ws}.{ws}.{mac}"):
        assert visitor().get(f"/invoice/{forged}").status_code == 404
    assert visitor().get("/pay/print.js").status_code == 200


def test_paying_online_marks_it_paid_once_and_tells_workflows(shop):
    ada = shop.contact()
    inv = shop.invoice(ada, [{"description": "Work", "unit_amount": 5000}], send=True)
    done = pay_on_page(inv["public_url"])
    assert path_of(done.headers["location"]).endswith("?checkout=success")
    paid = shop.get(f"/api/v1/invoices/{inv['id']}")
    assert paid["status"] == "paid" and paid["amount_paid"] == 5000 and paid["amount_due"] == 0
    assert [p["status"] for p in paid["payments"]] == ["succeeded"]
    assert [e["amount"] for e in events_of("payment.succeeded", shop.ws)] == [5000]
    assert [e["status"] for e in events_of("invoice.paid", shop.ws)] == ["paid"]
    # the paid event is on the contact's timeline, where a workflow trigger finds it
    types = [e["type"] for e in shop.get(f"/api/v1/records/{ada}/timeline")["data"]]
    assert {"invoice.paid", "payment.succeeded", "invoice.sent"} <= set(types)
    page = visitor().get(path_of(inv["public_url"]))
    assert "Paid" in page.text and "Pay USD" not in page.text
    again = visitor().post(path_of(inv["public_url"]).replace("/invoice/", "/api/public/invoices/") + "/checkout")
    assert again.status_code == 303 and "/invoice/" in again.headers["location"]  # nothing is due: back to the page


def test_pressing_pay_twice_reuses_the_open_checkout(shop):
    inv = shop.invoice(shop.contact(), [{"description": "Work", "unit_amount": 5000}], send=True)
    start = path_of(inv["public_url"]).replace("/invoice/", "/api/public/invoices/") + "/checkout"
    first, second = visitor().post(start), visitor().post(start)
    assert first.headers["location"] == second.headers["location"]
    with SessionLocal() as db:
        assert db.scalar(text("SELECT count(*) FROM payments WHERE invoice_id = :i"), {"i": inv["id"]}) == 1


def test_payments_recorded_by_hand_add_up_and_cannot_overpay(shop):
    inv = shop.invoice(shop.contact(), [{"description": "Work", "unit_amount": 10000}], send=True)
    path = f"/api/v1/invoices/{inv['id']}/payments"
    part = shop.post(path, {"amount": 4000, "method": "cash", "note": "deposit"})
    assert part["status"] == "open" and part["amount_due"] == 6000
    r = shop.client.post(path, json={"amount": 6001}, headers=shop.h)
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"amount": "can be at most the 6000 due"}
    done = shop.post(path, {"amount": 6000, "method": "check"})
    assert done["status"] == "paid" and done["amount_paid"] == 10000
    assert shop.client.post(path, json={"amount": 1}, headers=shop.h).status_code == 409


def test_void_stops_payment_and_a_partly_paid_invoice_is_refunded_first(shop):
    ada = shop.contact()
    inv = shop.invoice(ada, [{"description": "Work", "unit_amount": 10000}], send=True)
    voided = shop.post(f"/api/v1/invoices/{inv['id']}/void", {"reason": "sent by mistake"}, status=200)
    assert voided["status"] == "void"
    start = path_of(inv["public_url"]).replace("/invoice/", "/api/public/invoices/") + "/checkout"
    assert "/invoice/" in visitor().post(start).headers["location"]  # no checkout for a void invoice
    other = shop.invoice(ada, [{"description": "Work", "unit_amount": 10000}], send=True)
    shop.post(f"/api/v1/invoices/{other['id']}/payments", {"amount": 100})
    assert shop.client.post(f"/api/v1/invoices/{other['id']}/void", json={}, headers=shop.h).status_code == 409


def test_an_invoice_of_nothing_is_paid_when_sent(shop):
    shop.post("/api/v1/coupons", {"name": "Free", "code": "FREE", "percent_off_bp": 10000})
    inv = shop.invoice(shop.contact(), [{"description": "Gift", "unit_amount": 900}], coupon_code="FREE", send=True)
    assert inv["status"] == "paid" and inv["total"] == 0 and inv["number"] == "INV-0001"


def test_a_coupon_limit_holds_across_invoices(shop):
    shop.post("/api/v1/coupons", {"name": "Once", "code": "ONCE", "percent_off_bp": 500, "max_redemptions": 1})
    ada = shop.contact()
    a = shop.invoice(ada, [{"description": "x", "unit_amount": 1000}], coupon_code="ONCE")
    b = shop.invoice(ada, [{"description": "x", "unit_amount": 1000}], coupon_code="ONCE")
    shop.post(f"/api/v1/invoices/{a['id']}/send", status=200)
    r = shop.client.post(f"/api/v1/invoices/{b['id']}/send", headers=shop.h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "coupon_used_up"
    coupon = shop.get("/api/v1/coupons")["data"][0]
    assert coupon["times_redeemed"] == 1
    shop.post(f"/api/v1/invoices/{a['id']}/void", {}, status=200)  # voiding gives the use back
    assert shop.get("/api/v1/coupons")["data"][0]["times_redeemed"] == 0
    assert shop.post(f"/api/v1/invoices/{b['id']}/send", status=200)["discount"] == 50


def test_a_viewer_reads_invoices_and_a_member_cannot_refund_or_void(shop, db):
    from helpers import add_member
    inv = shop.invoice(shop.contact(), [{"description": "Work", "unit_amount": 1000}], send=True)
    viewer = add_member(db, shop.ids["org_id"], "v@example.com", workspace_id=shop.ws, workspace_role="viewer")
    member = add_member(db, shop.ids["org_id"], "m@example.com", workspace_id=shop.ws, workspace_role="member")
    assert viewer.get(f"/api/v1/invoices/{inv['id']}", headers={H: shop.ws}).status_code == 200
    r = viewer.post("/api/v1/invoices", json={}, headers={H: shop.ws})
    assert r.status_code == 403 and "payments.write" in r.json()["error"]["message"]
    r = member.post(f"/api/v1/invoices/{inv['id']}/void", json={}, headers={H: shop.ws})
    assert r.status_code == 403 and "payments.refund" in r.json()["error"]["message"]
    r = member.post("/api/v1/payments/account/connect", json={"provider": "fake"}, headers={H: shop.ws})
    assert r.status_code == 403 and "payments.manage" in r.json()["error"]["message"]
