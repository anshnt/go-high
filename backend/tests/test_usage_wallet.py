"""The wallet, the ledger, top-ups, rate cards and the cost preview (module 06), through the API and in SQL."""
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from helpers import H, add_member, context, make_role
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from usage_helpers import (
    BILLING,
    CENT,
    USD,
    balance,
    card,
    consistent,
    events_of,
    fund,
    ledger,
    new_key,
    preview,
    settle,
    topup,
    wallet,
)
from workflow_helpers import pump

from app.db import SessionLocal, acting, engine
from app.main import app
from app.models import Workspace
from app.usage import payments
from app.usage import wallet as wallets


@pytest.fixture
def fake(monkeypatch):
    """A fresh fake provider for the test, so what it was asked is the test's own."""
    provider = payments.FakeProvider()
    monkeypatch.setitem(payments.PROVIDERS, "fake", provider)
    return provider


def charge(ws: str, unit_cost: int, quantity: int = 1, **kw):
    """One charge as a request would make it (the app role in the workspace), committed; None or the Blocked error."""
    with SessionLocal() as db:
        w = db.get(Workspace, uuid.UUID(ws))
        with acting(db, workspace_id=w.id, org_id=w.org_id):
            try:
                wallets.charge(db, w, "sms.segment", quantity, source="api", unit_cost=unit_cost, **kw)
            except wallets.Blocked as e:
                db.rollback()
                return e
        db.commit()
    return None


def test_a_new_workspace_has_an_empty_prepaid_wallet(crm):
    client, ws, _ = crm
    w = wallet(client, ws)
    assert (w["balance"], w["currency"], w["mode"], w["status"], w["month_spent"]) == (0, "USD", "prepaid", "empty", 0)
    assert (w["payment_method"], w["auto_recharge"], w["monthly_cap"], w["minor_unit"]) == (None, False, None, CENT)
    assert client.get(f"{BILLING}/ledger", headers={H: ws}).json() == {"data": [], "next_cursor": None}


def test_who_may_read_and_who_may_manage(crm, db):
    client, ws, ids = crm
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws, workspace_role="member")
    admin = add_member(db, ids["org_id"], "ad@example.com", org_role="admin")
    assert viewer.get(f"{BILLING}/wallet", headers={H: ws}).status_code == 403
    assert preview(viewer, ws, items=[{"meter": "sms.segment", "quantity": 1}]).status_code == 403
    assert member.get(f"{BILLING}/wallet", headers={H: ws}).status_code == 200
    assert member.get(f"{BILLING}/ledger", headers={H: ws}).status_code == 200
    for who in (member, admin):  # Admin is everything except billing (ADR 0004)
        assert who.patch(f"{BILLING}/wallet", json={"monthly_cap": USD}, headers={H: ws}).status_code == 403
        assert topup(who, ws, 5 * USD).status_code == 403
        assert who.get(f"{BILLING}/rate-cards", headers={H: ws}).status_code == 403
    assert admin.get(f"{BILLING}/wallet", headers={H: ws}).status_code == 200


def test_a_top_up_charges_the_payment_method_once_and_credits_the_wallet(crm, db, fake):
    client, ws, _ = crm
    r = topup(client, ws, 5 * USD)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_payment_method"
    settle(client, ws, payment_method="pm_fake_visa_4242")
    assert wallet(client, ws)["payment_method"] == "…4242"
    r = topup(client, ws, 25 * USD, key="k1")
    assert r.status_code == 201, r.text
    t = r.json()
    assert (t["status"], t["amount"], t["trigger"], t["provider"]) == ("succeeded", 25 * USD, "manual", "fake")
    assert t["wallet"]["balance"] == 25 * USD and t["wallet"]["status"] == "ok"
    assert fake.calls == [{"amount_minor": 2500, "currency": "USD", "payment_method": "pm_fake_visa_4242",
                           "idempotency_key": f"topup:{t['id']}"}]
    again = topup(client, ws, 25 * USD, key="k1")  # a retried request: the stored answer, no second charge
    assert again.headers.get("Idempotent-Replayed") == "true" and again.json()["id"] == t["id"]
    assert topup(client, ws, 30 * USD, key="k1").status_code == 409
    assert len(fake.calls) == 1 and balance(db, ws) == 25 * USD
    [entry] = ledger(db, ws)
    assert (entry["kind"], entry["amount"], entry["subject_id"], entry["source"]) == ("topup", 25 * USD,
                                                                                    uuid.UUID(t["id"]), "api")
    [(kind, data)] = events_of(db, ws, "wallet.topped_up")
    assert data["amount"] == 25 * USD and data["balance_after"] == 25 * USD
    assert [x["id"] for x in client.get(f"{BILLING}/topups", headers={H: ws}).json()["data"]] == [t["id"]]


@pytest.mark.parametrize("amount, problem", [
    (0, None), (-5 * USD, None), (USD - CENT, "at least $1.00"), (10_001 * USD, "at most $10000.00"),
    (USD + 5_000, "whole number of USD minor units")])
def test_top_up_amounts_are_whole_minor_units_within_limits(crm, fake, amount, problem):
    client, ws, _ = crm
    settle(client, ws, payment_method="pm_fake_visa_4242")
    r = topup(client, ws, amount)
    assert r.status_code == 422, r.text
    if problem:
        assert problem in r.json()["error"]["fields"]["amount"]
    assert fake.calls == []


def test_two_identical_top_ups_at_the_same_moment_credit_once(crm, db, fake):
    client, ws, _ = crm
    settle(client, ws, payment_method="pm_fake_visa_4242")
    barrier, answers = threading.Barrier(4), []

    def go():
        mine = TestClient(app, cookies=client.cookies)  # a client per thread, one signed-in user
        barrier.wait()
        answers.append(topup(mine, ws, 10 * USD, key="same").status_code)

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert set(answers) <= {201, 409} and 201 in answers
    assert balance(db, ws) == 10 * USD and [e["kind"] for e in ledger(db, ws)] == ["topup"]
    assert len({c["idempotency_key"] for c in fake.calls}) == 1  # the provider deduplicates a repeated ask
    consistent(db, ws)


def test_a_declined_top_up_is_recorded_and_the_billing_people_are_told(crm, db, fake):
    client, ws, ids = crm
    settle(client, ws, payment_method="pm_fake_decline_0002")
    r = topup(client, ws, 10 * USD)
    assert r.status_code == 201
    assert (r.json()["status"], r.json()["error"]) == ("failed", "The card was declined")
    assert balance(db, ws) == 0 and ledger(db, ws) == []
    assert [d["error"] for _, d in events_of(db, ws, "wallet.topup_failed")] == ["The card was declined"]
    pump(db)
    db.rollback()
    notes = db.execute(text("SELECT kind, title, link FROM notifications WHERE workspace_id = :w"), {"w": ws}).all()
    assert [tuple(n) for n in notes] == [("billing", "A top-up of $10.00 failed", "/settings/billing")]


def test_charges_racing_a_low_balance_never_spend_more_than_is_there(crm, db):
    client, ws, _ = crm
    fund(client, ws, 5 * CENT)  # room for exactly five one-cent charges
    barrier, outcomes = threading.Barrier(12), []

    def go():
        barrier.wait()
        outcomes.append(charge(ws, CENT))

    threads = [threading.Thread(target=go) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(o is None for o in outcomes) == 5
    assert {o.code for o in outcomes if o is not None} == {"wallet_empty"}
    assert balance(db, ws) == 0
    consistent(db, ws)


def test_a_charge_with_a_key_is_made_once_even_when_racing_its_twin(crm, db):
    client, ws, _ = crm
    fund(client, ws, USD)
    barrier = threading.Barrier(6)

    def go():
        barrier.wait()
        charge(ws, CENT, key="message:same")

    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert [e["kind"] for e in ledger(db, ws)] == ["adjustment", "usage"] and balance(db, ws) == USD - CENT
    assert len(events_of(db, ws, "usage.recorded")) == 1


def test_postpaid_goes_below_zero_down_to_the_credit_limit(crm, db):
    client, ws, _ = crm
    settle(client, ws, mode="postpaid", credit_limit=2 * CENT)
    assert charge(ws, CENT) is None and charge(ws, CENT) is None
    assert charge(ws, CENT).code == "credit_limit"
    w = wallet(client, ws)
    assert (w["balance"], w["available"], w["status"]) == (-2 * CENT, 0, "empty")
    settle(client, ws, credit_limit=None)  # no limit
    assert charge(ws, 100 * USD) is None and wallet(client, ws)["available"] is None
    consistent(db, ws)


def test_the_monthly_cap_is_a_hard_stop_with_an_alert_before_it(crm, db):
    client, ws, _ = crm
    fund(client, ws, 100 * USD)
    settle(client, ws, monthly_cap=10 * CENT, cap_alert_pct=50)
    for _ in range(4):
        assert charge(ws, CENT * 2) is None
    assert [d["spent"] for _, d in events_of(db, ws, "usage.cap_warning")] == [6 * CENT]  # once, on crossing 50 %
    assert charge(ws, CENT * 2) is None  # exactly at the cap
    blocked = charge(ws, 1)
    assert blocked.code == "usage_cap" and "$0.10" in blocked.message
    assert wallet(client, ws)["status"] == "capped"
    fund(client, ws, USD)  # money in does not count against the cap
    assert charge(ws, 1).code == "usage_cap"
    settle(client, ws, monthly_cap=None)
    assert charge(ws, 1) is None


def test_a_low_balance_alert_fires_once_per_crossing_and_reaches_the_billing_people(crm, db):
    client, ws, ids = crm
    clerk_role = make_role(client, ws, "Billing clerk", "member",
                           capabilities=["usage.read", "billing.manage", "conversations.read"])
    clerk = add_member(db, ids["org_id"], "clerk@example.com", workspace_id=ws, workspace_role=clerk_role["key"])
    add_member(db, ids["org_id"], "member@example.com", workspace_id=ws)
    fund(client, ws, 3 * CENT)
    settle(client, ws, low_balance_at=2 * CENT)
    assert charge(ws, CENT) is None  # 2 cents: not below
    assert charge(ws, CENT) is None  # 1 cent: crossed
    fund(client, ws, 10 * CENT)
    assert charge(ws, CENT) is None  # above again: no alert
    assert [d["balance"] for _, d in events_of(db, ws, "wallet.low_balance")] == [CENT]
    pump(db)
    db.rollback()
    told = db.execute(text("SELECT u.email, n.title FROM notifications n JOIN users u ON u.id = n.user_id "
                           "WHERE n.kind = 'billing' ORDER BY u.email")).all()
    assert [tuple(t) for t in told] == [("a@example.com", "Wallet balance is low: $0.01"),
                                        ("clerk@example.com", "Wallet balance is low: $0.01")]
    assert clerk.get(f"{BILLING}/wallet", headers={H: ws}).status_code == 200


def test_auto_recharge_tops_up_once_when_the_balance_falls_below_the_mark(crm, db, fake):
    client, ws, _ = crm
    r = client.patch(f"{BILLING}/wallet", json={"auto_recharge": True}, headers={H: ws})
    assert r.status_code == 422 and set(r.json()["error"]["fields"]) == {
        "recharge_below", "recharge_amount", "payment_method"}
    settle(client, ws, payment_method="pm_fake_visa_4242", auto_recharge=True, recharge_below=5 * USD,
           recharge_amount=20 * USD)
    fund(client, ws, 6 * USD)
    for _ in range(3):  # 6 -> 5 -> 4 -> 3: the second charge crosses the mark, the third is already below it
        assert charge(ws, USD) is None
    pump(db)
    assert balance(db, ws) == 3 * USD + 20 * USD
    db.rollback()
    autos = db.execute(text("SELECT status, trigger, amount FROM wallet_topups")).all()
    assert [tuple(a) for a in autos] == [("succeeded", "auto", 20 * USD)] and len(fake.calls) == 1
    consistent(db, ws)


def test_a_failed_auto_recharge_is_recorded_and_frees_the_next_one(crm, db, fake):
    client, ws, _ = crm
    settle(client, ws, payment_method="pm_fake_decline_1", auto_recharge=True, recharge_below=5 * USD,
           recharge_amount=20 * USD)
    fund(client, ws, 6 * USD)
    assert charge(ws, 2 * USD) is None
    pump(db)
    db.rollback()
    assert [tuple(r) for r in db.execute(text("SELECT status, error FROM wallet_topups"))] == [
        ("failed", "The card was declined")]
    assert db.scalar(text("SELECT count(*) FROM notifications WHERE kind = 'billing'")) == 1
    settle(client, ws, payment_method="pm_fake_visa_1")
    fund(client, ws, 10 * USD)
    assert charge(ws, 10 * USD) is None  # crosses again
    pump(db)
    assert balance(db, ws) == 4 * USD + 20 * USD


def test_removing_the_payment_method_switches_auto_recharge_off(crm):
    client, ws, _ = crm
    settle(client, ws, payment_method="pm_fake_visa_4242", auto_recharge=True, recharge_below=USD,
           recharge_amount=10 * USD)
    w = settle(client, ws, payment_method=None)
    assert (w["payment_method"], w["auto_recharge"]) == (None, False)


def test_wallet_settings_are_whole_minor_units_and_audited_without_the_card(crm, db):
    client, ws, _ = crm
    r = client.patch(f"{BILLING}/wallet", json={"low_balance_at": CENT + 1, "monthly_cap": -1}, headers={H: ws})
    assert r.status_code == 422
    r = client.patch(f"{BILLING}/wallet", json={"low_balance_at": CENT + 1}, headers={H: ws})
    assert r.json()["error"]["fields"] == {"low_balance_at": "must be a whole number of USD minor units"}
    assert client.patch(f"{BILLING}/wallet", json={"cap_alert_pct": None}, headers={H: ws}).status_code == 422
    assert client.patch(f"{BILLING}/wallet", json={"bogus": 1}, headers={H: ws}).status_code == 422
    settle(client, ws, low_balance_at=2 * USD, payment_method="pm_fake_secret_token")
    [(_, data)] = events_of(db, ws, "wallet.updated")
    assert data["changes"] == {"low_balance_at": {"old": None, "new": 2 * USD}, "payment_method": {"changed": True}}
    assert "pm_fake_secret_token" not in str(events_of(db, ws, ""))
    settle(client, ws, low_balance_at=2 * USD)  # no change, no event
    assert len(events_of(db, ws, "wallet.updated")) == 1


def test_the_currency_is_the_organizations_and_fixed_once_money_moved(crm, db):
    client, ws, ids = crm
    clerk_role = make_role(client, ws, "Clerk", "member", capabilities=["usage.read", "billing.manage"])
    clerk = add_member(db, ids["org_id"], "clerk@example.com", workspace_id=ws, workspace_role=clerk_role["key"])
    for body in ({"currency": "EUR"}, {"mode": "postpaid"}, {"credit_limit": USD}):
        assert clerk.patch(f"{BILLING}/wallet", json=body, headers={H: ws}).status_code == 403
    assert clerk.patch(f"{BILLING}/wallet", json={"monthly_cap": USD}, headers={H: ws}).status_code == 200
    assert settle(client, ws, currency="JPY")["minor_unit"] == USD
    r = client.patch(f"{BILLING}/wallet", json={"low_balance_at": CENT}, headers={H: ws})
    assert r.json()["error"]["fields"]["low_balance_at"] == "must be a whole number of JPY minor units"
    fund(client, ws, 500 * USD)
    r = client.patch(f"{BILLING}/wallet", json={"currency": "USD"}, headers={H: ws})
    assert r.status_code == 409 and r.json()["error"]["code"] == "currency_locked"
    assert [e["currency"] for e in ledger(db, ws)] == ["JPY"]


def test_rate_cards_price_by_the_most_specific_level(crm, db):
    client, ws, ids = crm
    other = client.post("/api/workspaces", json={"name": "Client B", "brand_id": ids["brand_id"]}).json()["id"]
    channel_cost = 7_900  # a carrier's 0.79 cents per segment
    assert card(client, ws, markup_bp=5_000).status_code == 201  # the organization: 50 % over cost
    q = lambda w: preview(client, w, items=[{"meter": "sms.segment", "quantity": 3}]).json()["lines"]  # noqa: E731
    assert q(ws) == q(other)
    assert q(ws)[0]["unit_price"] == 0  # the platform cost is 0 here: a markup of nothing is nothing
    with SessionLocal() as s:
        w = s.get(Workspace, uuid.UUID(ws))
        assert wallets.pricing.quote(s, w, "USD", "sms.segment", 3, channel_cost).unit_price == 11_850
    assert card(client, ws, scope="brand", price=2 * CENT).status_code == 201
    assert card(client, ws, scope="workspace", price=CENT, workspace_id=other).status_code == 201
    assert (q(ws)[0]["unit_price"], q(ws)[0]["basis"]) == (2 * CENT, "price")
    assert (q(other)[0]["unit_price"], q(other)[0]["price"]) == (CENT, 3 * CENT)
    assert card(client, ws, scope="brand", price=5).json()["error"]["code"] == "rate_card_exists"
    assert card(client, ws, currency="EUR", price=1).status_code == 201  # a EUR card does not price a USD wallet
    assert q(ws)[0]["unit_price"] == 2 * CENT
    cards = client.get(f"{BILLING}/rate-cards", headers={H: ws}).json()["data"]
    assert [(c["scope"], c["currency"]) for c in cards] == [("organization", "USD"), ("organization", "EUR"),
                                                             ("brand", "USD"), ("workspace", "USD")]
    brand_card = next(c for c in cards if c["scope"] == "brand")
    r = client.patch(f"{BILLING}/rate-cards/{brand_card['id']}", json={"markup_bp": 0}, headers={H: ws})
    assert (r.json()["price"], r.json()["markup_bp"]) == (None, 0)
    assert client.delete(f"{BILLING}/rate-cards/{brand_card['id']}", headers={H: ws}).status_code == 204
    assert q(ws)[0]["basis"] == "markup"  # back to the organization's card
    types = [t for t, _ in events_of(db, ws, "rate_card.")]
    assert types == ["rate_card.created"] * 4 + ["rate_card.updated", "rate_card.deleted"]


def test_rate_cards_are_checked(crm, make_user):
    client, ws, ids = crm
    _, b = make_user("b@example.com")
    for body, field in (({}, "price"), ({"price": 1, "markup_bp": 1}, "price"),
                        ({"scope": "workspace", "workspace_id": b["workspace_id"], "price": 1}, "workspace_id"),
                        ({"scope": "brand", "brand_id": b["brand_id"], "price": 1}, "brand_id")):
        r = card(client, ws, **body)
        assert r.status_code == 422 and field in r.json()["error"]["fields"], (body, r.text)
    assert card(client, ws, meter="fax.page", price=1).status_code == 422
    assert card(client, ws, markup_bp=-10_001).status_code == 422
    assert card(client, ws, price=-1).status_code == 422
    assert client.patch(f"{BILLING}/rate-cards/{uuid.uuid4()}", json={"price": 1}, headers={H: ws}).status_code == 404


def test_the_margin_is_shown_to_the_organization_only(crm, db):
    client, ws, ids = crm
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    card(client, ws, price=2 * CENT)
    fund(client, ws, USD)
    assert charge(ws, CENT) is None
    mine = client.get(f"{BILLING}/ledger", headers={H: ws}).json()["data"][0]
    theirs = member.get(f"{BILLING}/ledger", headers={H: ws}).json()["data"][0]
    assert (mine["cost"], mine["price"]) == (CENT, 2 * CENT)
    assert "cost" not in theirs and "unit_cost" not in theirs and theirs["price"] == 2 * CENT
    assert "cost" not in preview(member, ws, items=[{"meter": "sms.segment", "quantity": 1}]).json()
    assert "unit_cost" not in member.get(f"{BILLING}/meters", headers={H: ws}).json()["data"][0]
    assert "cost" not in member.get(f"{BILLING}/usage", headers={H: ws}).json()
    assert "unit_cost" not in member.get(f"{BILLING}/ledger/export", headers={H: ws}).text.splitlines()[0]
    assert member.get(f"{BILLING}/rate-cards", headers={H: ws}).status_code == 403


def test_a_bulk_sms_preview_counts_segments_for_every_recipient_before_anything_is_sent(crm, db):
    client, ws, _ = crm
    r = client.post("/api/v1/channels", headers={H: ws}, json={
        "kind": "sms", "provider": "twilio", "name": "Line", "address": "+15550001111",
        "config": {"account_sid": "AC" + "a" * 32, "segment_cost": "0.0079"}, "secrets": {"auth_token": "t"}})
    channel = r.json()
    card(client, ws, markup_bp=2_500)
    fund(client, ws, 10 * USD)
    p = preview(client, ws, channel_id=channel["id"], body="x" * 200, recipients=500).json()  # 2 segments each
    assert p["lines"][0] | {"rate_card_id": None} == {
        "meter": "sms.segment", "label": "SMS", "quantity": 1000, "unit": "segments", "unit_cost": 7_900,
        "unit_price": 9_875, "cost": 7_900_000, "price": 9_875_000, "currency": "USD", "rate_card_id": None,
        "basis": "markup"}
    assert (p["price"], p["balance"], p["balance_after"], p["allowed"]) == (9_875_000, 10 * USD, 125_000, True)
    big = preview(client, ws, channel_id=channel["id"], body="x" * 200, recipients=600).json()
    assert (big["allowed"], big["code"]) == (False, "wallet_empty") and "$11.85" in big["reason"]
    both = preview(client, ws, channel_id=channel["id"], body="hi", items=[{"meter": "ai.credit", "quantity": 4}])
    assert [line["meter"] for line in both.json()["lines"]] == ["ai.credit", "sms.segment"]
    assert preview(client, ws).status_code == 422
    assert preview(client, ws, channel_id=str(uuid.uuid4())).status_code == 404
    assert preview(client, ws, items=[{"meter": "sms.segment", "quantity": 0}]).status_code == 422
    assert ledger(db, ws)[-1]["kind"] == "adjustment"  # a preview writes nothing


def test_the_ledger_filters_pages_and_exports(crm, db):
    client, ws, _ = crm
    fund(client, ws, USD, description="=HYPERLINK(\"evil\")")
    for _ in range(3):
        assert charge(ws, CENT) is None
    page = client.get(f"{BILLING}/ledger", params={"limit": 2}, headers={H: ws}).json()
    assert [e["kind"] for e in page["data"]] == ["usage", "usage"] and page["next_cursor"]
    rest = client.get(f"{BILLING}/ledger", params={"limit": 2, "cursor": page["next_cursor"]}, headers={H: ws}).json()
    assert [e["kind"] for e in rest["data"]] == ["usage", "adjustment"] and rest["next_cursor"] is None
    assert [e["balance_after"] for e in page["data"] + rest["data"]] == [97 * CENT, 98 * CENT, 99 * CENT, USD]
    only = client.get(f"{BILLING}/ledger", params={"kind": "adjustment"}, headers={H: ws}).json()["data"]
    assert len(only) == 1
    assert client.get(f"{BILLING}/ledger", params={"from": "2001-01-01", "to": "2001-01-31"},
                      headers={H: ws}).json()["data"] == []
    assert len(client.get(f"{BILLING}/ledger", params={"meter": "sms.segment"}, headers={H: ws}).json()["data"]) == 3
    bad = client.get(f"{BILLING}/ledger", params={"from": "yesterday"}, headers={H: ws})
    assert bad.status_code == 422 and "from" in bad.json()["error"]["fields"]
    assert client.get(f"{BILLING}/ledger", params={"cursor": "forged"}, headers={H: ws}).status_code == 400
    csv = client.get(f"{BILLING}/ledger/export", headers={H: ws})
    lines = csv.text.strip().splitlines()
    assert lines[0].startswith("created_at,kind,meter,description,quantity,unit_price,price,amount,balance_after")
    assert len(lines) == 5 and csv.headers["X-Export-Truncated"] == "false"
    assert ",usage,sms.segment,SMS: 1 segment,1,0.010000,0.010000,-0.010000,0.970000,USD," in lines[1]
    assert "'=HYPERLINK" in lines[4]  # a formula is never live in a spreadsheet
    [(_, exported)] = events_of(db, ws, "usage.exported")
    assert exported["rows"] == 4


def test_the_usage_summary_nets_refunds_per_meter_and_day(crm, db):
    client, ws, _ = crm
    fund(client, ws, USD)
    assert charge(ws, CENT, quantity=3) is None
    with SessionLocal() as s:
        w = s.get(Workspace, uuid.UUID(ws))
        with acting(s, workspace_id=w.id, org_id=w.org_id):
            wallets.charge(s, w, "email.message", 2, source="api", unit_cost=100)
            first = s.scalar(text("SELECT id FROM usage_ledger WHERE meter = 'sms.segment'"))
            wallets.reverse(s, s.get(wallets.LedgerEntry, first), "test", source="api")
            wallets.reverse(s, s.get(wallets.LedgerEntry, first), "test again", source="api")  # once only
        s.commit()
    summary = client.get(f"{BILLING}/usage", headers={H: ws}).json()
    assert summary["price"] == 200 and summary["cost"] == 200
    assert [(m["meter"], m["quantity"], m["price"]) for m in summary["meters"]] == [
        ("email.message", 2, 200), ("sms.segment", 0, 0)]
    assert len(summary["series"]) == 1 and summary["series"][0]["price"] == 200
    assert [e["kind"] for e in ledger(db, ws)] == ["adjustment", "usage", "usage", "reversal"]
    assert len(events_of(db, ws, "usage.reversed")) == 1
    consistent(db, ws)


def test_adjustments_are_the_organizations_and_not_usage(crm, db):
    client, ws, ids = crm
    clerk_role = make_role(client, ws, "Clerk", "member", capabilities=["usage.read", "billing.manage"])
    clerk = add_member(db, ids["org_id"], "clerk@example.com", workspace_id=ws, workspace_role=clerk_role["key"])
    body = {"amount": USD, "description": "goodwill"}
    assert clerk.post(f"{BILLING}/adjustments", json=body, headers={H: ws}).status_code == 403
    for bad in ({"amount": 0, "description": "x"}, {"amount": 1, "description": "x"}, {"amount": USD},
                {"amount": USD, "description": " "}):
        assert client.post(f"{BILLING}/adjustments", json=bad, headers={H: ws}).status_code == 422, bad
    key = {H: ws, "Idempotency-Key": new_key()}
    first = client.post(f"{BILLING}/adjustments", json=body, headers=key)
    again = client.post(f"{BILLING}/adjustments", json=body, headers=key)
    assert first.json()["id"] == again.json()["id"] and balance(db, ws) == USD
    debit = client.post(f"{BILLING}/adjustments", json={"amount": -2 * USD, "description": "correction"},
                        headers={H: ws})
    assert debit.status_code == 201 and debit.json()["balance_after"] == -USD
    assert wallet(client, ws)["month_spent"] == 0
    assert [d["amount"] for _, d in events_of(db, ws, "wallet.adjusted")] == [USD, -2 * USD]


# --- in SQL: the ledger is append only, and money only enters the way the code makes it --------------------------

def as_app(conn, ids, user_id=None):
    context(conn, workspace_id=ids["workspace_id"], org_id=ids["org_id"], user_id=user_id or "")


def test_the_request_role_cannot_rewrite_the_ledger_or_mint_money(crm, db):
    client, ws, ids = crm
    fund(client, ws, USD)
    me = client.get("/api/me").json()["user"]["id"]
    denied = ["UPDATE usage_ledger SET amount = 0", "DELETE FROM usage_ledger", "UPDATE wallets SET balance = 1",
              "INSERT INTO wallets (workspace_id, balance) VALUES (gen_random_uuid(), 5)",
              "UPDATE usage_ledger SET balance_after = 0", "TRUNCATE usage_ledger"]
    insert = ("INSERT INTO usage_ledger (workspace_id, kind, amount, currency, source{cols}) "
              "VALUES (:w, :k, :a, 'USD', 'api'{vals})")
    with engine.connect() as conn:
        for statement in denied:
            with pytest.raises(DBAPIError, match="permission denied"), conn.begin():
                as_app(conn, ids, me)
                conn.execute(text(statement))
        forged = [({"k": "topup", "a": 100 * USD}, "", ""),  # money from no top-up
                  ({"k": "topup", "a": 100 * USD, "s": str(uuid.uuid4())}, ", subject_type, subject_id",
                   ", 'topup', :s"),
                  ({"k": "adjustment", "a": 100 * USD}, "", ""),  # an adjustment by someone who is not an org admin
                  ]
        for params, cols, vals in forged:
            with pytest.raises(DBAPIError, match="row-level security"), conn.begin():
                as_app(conn, ids, user_id=str(uuid.uuid4()))
                conn.execute(text(insert.format(cols=cols, vals=vals)), {"w": ws, **params})
        with pytest.raises(DBAPIError, match="row-level security"), conn.begin():  # a refund of nothing
            as_app(conn, ids, me)
            conn.execute(text(insert.format(cols=", meter, price, quantity", vals=", 'sms.segment', :a, 1")),
                         {"w": ws, "k": "reversal", "a": USD})
        with pytest.raises(DBAPIError, match="ck_usage_ledger_usage_amount"), conn.begin():  # usage that pays in
            as_app(conn, ids, me)
            conn.execute(text(insert.format(cols=", meter, price", vals=", 'sms.segment', 0")),
                         {"w": ws, "k": "usage", "a": USD})
        with pytest.raises(DBAPIError, match="insufficient_privilege|only organization owners"), conn.begin():
            as_app(conn, ids, user_id=str(uuid.uuid4()))
            conn.execute(text("UPDATE wallets SET mode = 'postpaid'"))
    assert balance(db, ws) == USD
    consistent(db, ws)


def test_rate_cards_are_written_by_organization_admins_only_in_sql(crm, db):
    client, ws, ids = crm
    me = client.get("/api/me").json()["user"]["id"]
    insert = text("INSERT INTO rate_cards (org_id, meter, currency, price) VALUES (:o, 'sms.segment', 'USD', 1)")
    with engine.connect() as conn:
        with pytest.raises(DBAPIError, match="row-level security"), conn.begin():
            as_app(conn, ids, user_id=str(uuid.uuid4()))
            conn.execute(insert, {"o": ids["org_id"]})
        with conn.begin():
            as_app(conn, ids, me)
            conn.execute(insert, {"o": ids["org_id"]})
            conn.rollback()


class Flaky(payments.FakeProvider):
    """A provider that does not answer the first `outages` calls (it may or may not have charged), then answers."""

    def __init__(self, outages: int, charged_anyway: bool = False):
        super().__init__()
        self.outages, self.charged_anyway = outages, charged_anyway

    def charge(self, **kw):
        if self.outages:
            self.outages -= 1
            if self.charged_anyway:  # the card was charged, but the answer was lost on the way back
                super().charge(**kw)
            raise payments.PaymentError("timed out", retryable=True)
        return super().charge(**kw)


def test_a_provider_that_does_not_answer_leaves_the_top_up_pending_and_a_retry_charges_once(crm, db, monkeypatch):
    client, ws, _ = crm
    flaky = Flaky(outages=1, charged_anyway=True)
    monkeypatch.setitem(payments.PROVIDERS, "fake", flaky)
    settle(client, ws, payment_method="pm_fake_visa_4242")
    first = topup(client, ws, 10 * USD, key="k")
    assert first.status_code == 202 and first.json()["status"] == "pending"
    assert "has not answered" in first.json()["error"] and balance(db, ws) == 0
    assert events_of(db, ws, "wallet.topup_failed") == []  # not a failure: the money may have moved
    again = topup(client, ws, 10 * USD, key="k")
    assert again.json()["status"] == "succeeded" and again.json()["id"] == first.json()["id"]
    assert len(flaky.seen) == 1 and {c["idempotency_key"] for c in flaky.calls} == {f"topup:{first.json()['id']}"}
    assert balance(db, ws) == 10 * USD and [e["kind"] for e in ledger(db, ws)] == ["topup"]


def test_an_automatic_top_up_the_provider_does_not_answer_is_asked_again_by_the_queue(crm, db, monkeypatch):
    client, ws, _ = crm
    flaky = Flaky(outages=2)
    monkeypatch.setitem(payments.PROVIDERS, "fake", flaky)
    settle(client, ws, payment_method="pm_fake_visa_4242", auto_recharge=True, recharge_below=5 * USD,
           recharge_amount=20 * USD)
    fund(client, ws, 6 * USD)
    assert charge(ws, 2 * USD) is None
    for _ in range(4):  # the job fails twice (its backoff skipped), then the provider answers
        pump(db)
        db.execute(text("UPDATE jobs SET run_at = now() WHERE status = 'queued'"))
        db.commit()
    db.rollback()
    assert [tuple(r) for r in db.execute(text("SELECT status, trigger FROM wallet_topups"))] == [("succeeded", "auto")]
    assert balance(db, ws) == 24 * USD and len(flaky.seen) == 1
    consistent(db, ws)


def test_a_provider_that_is_not_set_up_is_said_plainly(crm, db, monkeypatch):
    client, ws, _ = crm
    settle(client, ws, payment_method="pm_fake_visa_4242")
    monkeypatch.setenv("PAYMENT_PROVIDER", "stripe")  # module 21 has not registered it
    r = topup(client, ws, 10 * USD)
    assert r.status_code == 503 and r.json()["error"]["code"] == "payments_unavailable"
    assert wallet(client, ws)["provider"] == "stripe"
    db.rollback()
    assert db.scalar(text("SELECT count(*) FROM wallet_topups")) == 0
