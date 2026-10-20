"""Helpers for the payments tests: a workspace with the test provider connected (`Shop`, from the `shop` fixture), a
visitor with no session, the test provider's checkout page, signed webhooks and jobs run before their time."""
import json
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from helpers import H, drain, make_record
from sqlalchemy import text

from app.db import SessionLocal
from app.main import app
from app.payments.providers import fake


def path_of(url: str) -> str:
    u = urlsplit(url)
    return u.path + (f"?{u.query}" if u.query else "")


def visitor() -> TestClient:
    return TestClient(app, follow_redirects=False)


class Shop:
    def __init__(self, client, ws, ids):
        self.client, self.ws, self.ids, self.h = client, ws, ids, {H: ws}

    def get(self, path, expect=200, **params):
        r = self.client.get(path, params=params, headers=self.h)
        assert r.status_code == expect, r.text
        return r.json()

    def post(self, path, body=None, status=201, headers=None):
        r = self.client.post(path, json=body, headers={**self.h, **(headers or {})})
        assert r.status_code == status, r.text
        return r.json()

    def patch(self, path, body, status=200):
        r = self.client.patch(path, json=body, headers=self.h)
        assert r.status_code == status, r.text
        return r.json()

    def product(self, name="Consulting", **price):
        body = {"currency": "usd", "unit_amount": 10000, **price}
        made = self.post("/api/v1/products", {"name": name, "prices": [body]})
        return made, made["prices"][0]

    def monthly(self, name="Pro plan", amount=2000, **extra):
        return self.product(name, unit_amount=amount, type="recurring", interval="month", **extra)[1]

    def contact(self, email="ada@example.com", first_name="Ada"):
        return make_record(self.client, self.ws, first_name=first_name, email=email)["id"]

    def invoice(self, contact_id, lines, send=False, **extra):
        inv = self.post("/api/v1/invoices", {"contact_id": contact_id, "lines": lines, **extra})
        if send:
            inv = self.post(f"/api/v1/invoices/{inv['id']}/send", status=200)
        return inv

    def account_id(self):
        return self.get("/api/v1/payments/account")["account"]["account_id"]


def pay_on_page(page_url: str, outcome: str = "succeeded", client: TestClient | None = None):
    """Presses Pay (or Decline) on a public invoice page: the checkout POST, then the test provider's page. Returns
    the final redirect response."""
    v = client or visitor()
    start = v.post(path_of(page_url).replace("/invoice/", "/api/public/invoices/", 1) + "/checkout")
    assert start.status_code == 303, start.text
    return complete(v, start.headers["location"], outcome)


def complete(v: TestClient, provider_url: str, outcome: str = "succeeded"):
    page = v.get(path_of(provider_url))
    assert page.status_code == 200, page.text
    done = v.post(path_of(provider_url) + "/complete", data={"outcome": outcome})
    assert done.status_code == 303, done.text
    return done


def webhook(body: bytes, headers: dict | None = None, client: TestClient | None = None):
    return (client or visitor()).post("/api/hooks/payments/fake", content=body,
                                      headers=headers if headers is not None else fake.signed(body))


def payment_event(account: str, payment_id: str, amount: int, status: str = "succeeded", event_id: str | None = None,
                  **data) -> bytes:
    return fake.event(account, f"payment.{status}", {"payment_id": payment_id, "amount": amount, "currency": "usd",
                                                     "provider_payment_id": data.pop("pi", f"pi_{payment_id[:8]}"),
                                                     **data}, event_id=event_id)


def run_jobs(*kinds: str) -> int:
    """Runs the queued jobs of these kinds now (their run_at moved to now), then everything due."""
    with SessionLocal() as db:
        db.execute(text("UPDATE jobs SET run_at = now() WHERE status = 'queued' AND kind = ANY(:k)"),
                   {"k": list(kinds)})
        db.commit()
    return drain()


def queued(kind: str) -> list[dict]:
    with SessionLocal() as db:
        return [dict(r._mapping) for r in db.execute(text(
            "SELECT payload, run_at FROM jobs WHERE status = 'queued' AND kind = :k ORDER BY run_at"), {"k": kind})]


def events_of(type_: str, workspace: str) -> list[dict]:
    with SessionLocal() as db:
        return [r[0] for r in db.execute(text("SELECT data FROM events WHERE type = :t AND workspace_id = :w "
                                              "ORDER BY id"), {"t": type_, "w": workspace})]


def dumps(value) -> str:
    return json.dumps(value)
