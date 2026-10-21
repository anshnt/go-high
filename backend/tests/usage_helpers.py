"""Helpers for the usage ledger tests: money in micros, the wallet through the API, and the ledger read back as the
owner role."""
import uuid

from helpers import H
from sqlalchemy import text

USD = 1_000_000  # one dollar in micros
CENT = 10_000
BILLING = "/api/v1/billing"


def wallet(client, ws) -> dict:
    r = client.get(f"{BILLING}/wallet", headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def settle(client, ws, **settings) -> dict:
    r = client.patch(f"{BILLING}/wallet", json=settings, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def fund(client, ws, amount: int, description: str = "test money") -> dict:
    """Credits the wallet by an adjustment (the caller must be an organization owner)."""
    r = client.post(f"{BILLING}/adjustments", json={"amount": amount, "description": description}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def topup(client, ws, amount: int, key: str | None = None):
    headers = {H: ws, **({"Idempotency-Key": key} if key else {})}
    return client.post(f"{BILLING}/topups", json={"amount": amount}, headers=headers)


def card(client, ws, meter: str = "sms.segment", **body):
    return client.post(f"{BILLING}/rate-cards", json={"meter": meter, **body}, headers={H: ws})


def preview(client, ws, **body):
    return client.post("/api/v1/usage/preview", json=body, headers={H: ws})


def ledger(db, ws: str) -> list[dict]:
    """Every ledger entry of the workspace, oldest first, as the owner sees it."""
    db.rollback()
    rows = db.execute(text("SELECT * FROM usage_ledger WHERE workspace_id = :w ORDER BY created_at, id"),
                      {"w": ws}).mappings().all()
    return [dict(r) for r in rows]


def balance(db, ws: str) -> int:
    db.rollback()
    return db.scalar(text("SELECT balance FROM wallets WHERE workspace_id = :w"), {"w": ws})


def consistent(db, ws: str) -> None:
    """The balance is the sum of the ledger, and every row's balance_after is the running sum."""
    rows, running = ledger(db, ws), 0
    for r in rows:
        running += r["amount"]
        assert r["balance_after"] == running, r
    assert balance(db, ws) == running


def events_of(db, ws: str, prefix: str) -> list[tuple[str, dict]]:
    db.rollback()
    return [(r.type, r.data) for r in db.execute(text(
        "SELECT type, data FROM events WHERE workspace_id = :w AND type LIKE :p ORDER BY id"),
        {"w": ws, "p": prefix + "%"})]


def new_key() -> str:
    return uuid.uuid4().hex
