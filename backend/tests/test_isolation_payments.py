"""Tenant isolation of payments beyond the sweep in test_isolation.py: every payments route with another tenant's ids,
public links that name the other tenant, provider events naming the other tenant's payment, the narrow system scope a
webhook and a payment link start in, and what the app role may never do (move rows, point across workspaces, change
an amount, delete money)."""
import json

import pytest
from payments_helpers import payment_event, webhook
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_isolation import context, rows, secrets_of, two_orgs  # noqa: F401  (two_orgs is a fixture)

from app import config
from app.db import engine


@pytest.fixture(autouse=True)
def fake_on(monkeypatch):
    monkeypatch.setattr(config, "PAYMENTS_FAKE_PROVIDER", True)


def test_a_user_of_a_gets_404s_for_bs_payments(two_orgs):  # noqa: F811
    a, a_ids, b, b_ids = two_orgs
    mine = {"X-Workspace-Id": a_ids["workspace_id"]}
    attempts = [
        ("GET", f"/api/v1/products/{b_ids['product_id']}", None),
        ("PATCH", f"/api/v1/products/{b_ids['product_id']}", {"name": "stolen"}),
        ("DELETE", f"/api/v1/products/{b_ids['product_id']}", None),
        ("POST", f"/api/v1/products/{b_ids['product_id']}/prices", {"currency": "usd", "unit_amount": 1}),
        ("PATCH", f"/api/v1/prices/{b_ids['price_id']}", {"active": False}),
        ("GET", f"/api/v1/coupons/{b_ids['coupon_id']}", None),
        ("PATCH", f"/api/v1/coupons/{b_ids['coupon_id']}", {"active": False}),
        ("PATCH", f"/api/v1/tax-rates/{b_ids['tax_rate_id']}", {"active": False}),
        ("GET", f"/api/v1/payment-links/{b_ids['link_id']}", None),
        ("PATCH", f"/api/v1/payment-links/{b_ids['link_id']}", {"active": False}),
        ("GET", f"/api/v1/invoices/{b_ids['invoice_id']}", None),
        ("PATCH", f"/api/v1/invoices/{b_ids['invoice_id']}", {"memo": "x"}),
        ("DELETE", f"/api/v1/invoices/{b_ids['invoice_id']}", None),
        ("POST", f"/api/v1/invoices/{b_ids['invoice_id']}/send", None),
        ("POST", f"/api/v1/invoices/{b_ids['invoice_id']}/void", {}),
        ("POST", f"/api/v1/invoices/{b_ids['invoice_id']}/payments", {"amount": 1}),
        ("GET", f"/api/v1/subscriptions/{b_ids['subscription_id']}", None),
        ("PATCH", f"/api/v1/subscriptions/{b_ids['subscription_id']}", {"quantity": 2}),
        ("POST", f"/api/v1/subscriptions/{b_ids['subscription_id']}/cancel", {"at_period_end": False}),
        ("POST", f"/api/v1/subscriptions/{b_ids['subscription_id']}/reactivate", None),
        ("GET", f"/api/v1/payments/transactions/{b_ids['payment_id']}", None),
        ("POST", f"/api/v1/payments/transactions/{b_ids['payment_id']}/refunds", {"amount": 1}),
    ]
    for method, path, body in attempts:
        r = a.request(method, path, json=body, headers=mine)
        assert r.status_code == 404, (method, path, r.status_code, r.text[:200])
        assert not any(leak in r.text for leak in secrets_of(b_ids)), (method, path)
    # B's ids inside A's own requests are refused as unknown, never used
    for path, body, field in (
            ("/api/v1/invoices", {"contact_id": b_ids["record_id"], "lines": []}, "contact_id"),
            ("/api/v1/invoices", {"contact_id": a_ids["record_id"], "lines": [{"price_id": b_ids["price_id"]}]},
             "lines.0.price_id"),
            ("/api/v1/invoices", {"contact_id": a_ids["record_id"], "coupon_code": b_ids["coupon_code"],
                                  "lines": [{"description": "x", "unit_amount": 1}]}, "coupon_code"),
            ("/api/v1/subscriptions", {"contact_id": a_ids["record_id"], "price_id": b_ids["price_id"]}, "price_id"),
            ("/api/v1/payment-links", {"name": "x", "items": [{"price_id": b_ids["price_id"]}]}, "items.0.price_id"),
            ("/api/v1/coupons", {"name": "x", "code": "XX", "percent_off_bp": 1, "price_ids": [b_ids["price_id"]]},
             "price_ids.0")):
        r = a.post(path, json=body, headers=mine)
        assert r.status_code == 422 and field in r.json()["error"]["fields"], (path, r.text)
    for path in ("/api/v1/invoices", "/api/v1/subscriptions", "/api/v1/payments/transactions", "/api/v1/products",
                 "/api/v1/coupons", "/api/v1/payment-links", "/api/v1/tax-rates", "/api/v1/prices",
                 "/api/v1/payments/summary", "/api/v1/payments/account"):
        r = a.get(path, headers=mine)
        assert r.status_code == 200 and not any(leak in r.text for leak in secrets_of(b_ids)), path
    theirs = {"X-Workspace-Id": b_ids["workspace_id"]}  # and B still has all of it, unchanged
    assert b.get(f"/api/v1/invoices/{b_ids['invoice_id']}", headers=theirs).json()["memo"] == b_ids["invoice_memo"]
    assert b.get(f"/api/v1/subscriptions/{b_ids['subscription_id']}", headers=theirs).json()["status"] == "incomplete"


def test_public_links_and_provider_events_reach_only_their_own_workspace(two_orgs):  # noqa: F811
    from payments_helpers import visitor
    _, a_ids, b, b_ids = two_orgs
    v = visitor()
    a_token, b_token = a_ids["invoice_token"], b_ids["invoice_token"]
    a_ws, a_inv, a_mac = a_token.split(".")
    b_ws, b_inv, b_mac = b_token.split(".")
    for forged in (f"{a_ws}.{b_inv}.{b_mac}", f"{b_ws}.{a_inv}.{a_mac}", f"{a_ws}.{b_inv}.{a_mac}"):
        assert v.get(f"/invoice/{forged}").status_code == 404, forged
        assert v.post(f"/api/public/invoices/{forged}/checkout").status_code == 404
    assert v.get(f"/invoice/{a_token}").status_code == 200  # A's own link works
    # A's provider account reporting B's payment: found nowhere in A's workspace, so nothing happens to B
    body = payment_event(a_ids["payment_account"], b_ids["payment_id"], 4242, event_id="evt_cross")
    assert webhook(body).status_code == 409
    tx = b.get(f"/api/v1/payments/transactions/{b_ids['payment_id']}",
               headers={"X-Workspace-Id": b_ids["workspace_id"]}).json()
    assert tx["status"] == "succeeded" and [r["amount"] for r in tx["refunds"]] == [100]


def test_the_system_scope_reads_accounts_and_links_and_nothing_else_of_payments(two_orgs):  # noqa: F811
    with engine.connect() as conn, conn.begin():
        context(conn, system="on")  # what a webhook or a payment link page has until it has found its workspace
        assert len(rows(conn, "payment_accounts")) == 2 and len(rows(conn, "payment_links")) == 2
        for table in ("invoices", "invoice_lines", "payments", "refunds", "subscriptions", "coupons", "prices",
                      "products", "tax_rates", "payment_customers", "payment_events", "coupon_redemptions"):
            assert rows(conn, table) == [], table


def test_the_app_role_cannot_move_point_or_rewrite_payment_rows_across_workspaces(two_orgs, db):  # noqa: F811
    _, a_ids, _, b_ids = two_orgs
    ids = {"a": a_ids["workspace_id"], "b": b_ids["workspace_id"], "bp": b_ids["price_id"], "ap": a_ids["price_id"],
           "bc": b_ids["record_id"], "ac": a_ids["record_id"], "bi": b_ids["invoice_id"], "ai": a_ids["invoice_id"],
           "bpay": b_ids["payment_id"], "apay": a_ids["payment_id"], "bcoupon": b_ids["coupon_id"]}
    denied = [  # each in its own transaction, as A
        "INSERT INTO products (workspace_id, name) VALUES (:b, 'x')",
        "INSERT INTO invoices (workspace_id, currency, contact_id) VALUES (:a, 'usd', :bc)",  # B's contact
        "INSERT INTO invoice_lines (workspace_id, invoice_id, position, description, unit_amount, amount, total, "
        "price_id) VALUES (:a, :ai, 9, 'x', 1, 1, 1, :bp)",  # B's price on A's invoice
        "INSERT INTO invoice_lines (workspace_id, invoice_id, position, description, unit_amount, amount, total) "
        "VALUES (:a, :bi, 9, 'x', 1, 1, 1)",  # a line on B's invoice
        "INSERT INTO subscriptions (workspace_id, contact_id, price_id, currency, status) "
        "VALUES (:a, :ac, :bp, 'usd', 'active')",
        "INSERT INTO refunds (workspace_id, payment_id, amount) VALUES (:a, :bpay, 1)",
        "INSERT INTO coupon_redemptions (workspace_id, coupon_id, invoice_id) VALUES (:a, :bcoupon, :ai)",
        "INSERT INTO payments (workspace_id, invoice_id, provider, attempt_key, amount, currency) "
        "VALUES (:a, :bi, 'manual', 'x', 1, 'usd')",
        "UPDATE prices SET unit_amount = 1",  # an amount never changes
        "UPDATE payments SET amount_refunded = amount + 1 WHERE id = :apay",  # never more than captured
        "DELETE FROM payments", "DELETE FROM refunds", "DELETE FROM subscriptions", "DELETE FROM payment_events",
        "UPDATE payment_events SET event_type = 'x'",
    ]
    for statement in denied:
        with engine.connect() as conn:
            with pytest.raises(DBAPIError), conn.begin():
                context(conn, workspace_id=ids["a"], org_id=a_ids["org_id"])
                result = conn.execute(text(statement), ids)
                if statement.startswith(("UPDATE", "DELETE")) and result.rowcount == 0:
                    raise DBAPIError(statement, None, Exception("touched nothing"))  # RLS hid the rows: also fine


def test_the_app_role_cannot_move_payment_rows_into_another_workspace(two_orgs):  # noqa: F811
    _, a_ids, _, b_ids = two_orgs
    for table in ("invoices", "payments", "subscriptions", "prices", "refunds", "payment_links", "payment_accounts"):
        with engine.connect() as conn:
            with pytest.raises(DBAPIError, match="row-level security|violates|permission denied"), conn.begin():
                context(conn, workspace_id=a_ids["workspace_id"], org_id=a_ids["org_id"])
                conn.execute(text(f"UPDATE {table} SET workspace_id = :b"), {"b": b_ids["workspace_id"]})
    with engine.connect() as conn:
        counts = {t: conn.scalar(text(f"SELECT count(*) FROM {t} WHERE workspace_id = :b"),
                                 {"b": b_ids["workspace_id"]}) for t in ("invoices", "payments", "subscriptions")}
    assert counts == {"invoices": 2, "payments": 1, "subscriptions": 1}, json.dumps(counts)
