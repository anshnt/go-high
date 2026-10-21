"""The wallet and its ledger: the one write path for money (module 06). Every paid action calls `charge` in its own
transaction before it happens; a refund of an action that did not happen is `reverse`; money in is `credit`.

Each of them takes the wallet's row lock first (`SELECT ... FOR UPDATE`), so the charges of one workspace take turns:
the balance a charge is judged against is the balance after every charge before it, and two sends racing a low balance
cannot both spend the last cent. The ledger insert then moves the balance through a trigger (migration 0013), so the
balance is always the sum of the ledger and every row records the balance it left behind. Nothing here commits; the
caller's transaction does, together with the action it paid for, so a rolled back send leaves no charge behind.

A charge is judged (`judge`) against the monthly cap, then the mode: a prepaid wallet refuses what its balance does not
cover, a postpaid one lets the balance go below zero (down to its credit limit, when it has one) with a warning. A
charge of nothing is never refused. Crossing the low balance mark, or the cap's alert level, emits an event (the
notifications consumer tells the people who manage billing), and falling below the auto-recharge mark queues a top-up.
`preview` answers the same question without the lock and without writing: what a send would cost, and whether it
would go through now."""
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .. import events, jobs
from ..models import Workspace
from . import meters, money, pricing
from .models import LedgerEntry, Wallet
from .pricing import Quote

USAGE_KINDS = ("usage", "reversal")


class Blocked(Exception):
    """A charge the wallet refuses: `code` is `wallet_empty`, `credit_limit` or `usage_cap`, and the message is a
    sentence to show."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Verdict:
    allowed: bool = True
    code: str | None = None
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def wallet_of(db: Session, workspace_id: uuid.UUID, lock: bool = False) -> Wallet:
    """The workspace's wallet, made on first use. `lock` takes its row lock until the transaction ends."""
    db.execute(pg_insert(Wallet).values(workspace_id=workspace_id).on_conflict_do_nothing())
    stmt = select(Wallet).where(Wallet.workspace_id == workspace_id).execution_options(populate_existing=True)
    return db.scalar(stmt.with_for_update() if lock else stmt)


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_spent(db: Session, workspace_id: uuid.UUID) -> int:
    """What this calendar month's usage has cost the workspace so far (UTC), refunds taken off."""
    return -int(db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
        LedgerEntry.workspace_id == workspace_id, LedgerEntry.kind.in_(USAGE_KINDS),
        LedgerEntry.created_at >= month_start())) or 0)


def judge(w: Wallet, price: int, spent: int) -> Verdict:
    """Whether the wallet `w`, with `spent` used this month, may be charged `price` now."""
    v, c = Verdict(), w.currency
    if price <= 0:
        return v
    after = w.balance - price
    if w.monthly_cap is not None and spent + price > w.monthly_cap:
        return Verdict(False, "usage_cap", f"This month's usage cap of {money.show(w.monthly_cap, c)} is reached "
                                           f"({money.show(spent, c)} used, this needs {money.show(price, c)}). "
                                           "Raise the cap under Settings > Billing and usage, or wait for next month.")
    if w.mode == "prepaid" and after < 0:
        return Verdict(False, "wallet_empty", f"The wallet balance ({money.show(w.balance, c)}) does not cover this "
                                              f"({money.show(price, c)}). Top up under Settings > Billing and usage.")
    if w.mode == "postpaid" and w.credit_limit is not None and after < -w.credit_limit:
        return Verdict(False, "credit_limit", f"This ({money.show(price, c)}) would take the balance past the credit "
                                              f"limit of {money.show(w.credit_limit, c)}. Settle the balance under "
                                              "Settings > Billing and usage.")
    if after < 0:
        v.warnings.append(f"The wallet balance will be {money.show(after, c)}.")
    elif w.low_balance_at is not None and after < w.low_balance_at:
        v.warnings.append(f"The wallet balance will be {money.show(after, c)}, below the alert at "
                          f"{money.show(w.low_balance_at, c)}.")
    if w.monthly_cap and (spent + price) * 100 >= w.monthly_cap * w.cap_alert_pct:
        v.warnings.append(f"This month's usage will be {money.show(spent + price, c)} of the "
                          f"{money.show(w.monthly_cap, c)} cap.")
    return v


@dataclass
class Preview:
    currency: str
    lines: list[Quote]
    balance: int
    spent: int
    verdict: Verdict

    @property
    def cost(self) -> int:
        return sum(q.cost for q in self.lines)

    @property
    def price(self) -> int:
        return sum(q.price for q in self.lines)

    def json(self) -> dict:
        return {"currency": self.currency, "lines": [q.json(self.currency) for q in self.lines], "cost": self.cost,
                "price": self.price, "balance": self.balance, "balance_after": self.balance - self.price,
                "month_spent": self.spent, "allowed": self.verdict.allowed, "code": self.verdict.code,
                "reason": self.verdict.reason, "warnings": self.verdict.warnings}


def preview(db: Session, workspace: Workspace, items: list[tuple[str, int, int | None]]) -> Preview:
    """The price of `items` (meter, quantity, unit cost or None for the platform's) and whether the wallet would
    accept them now. Writes nothing but the wallet row on first use."""
    w = wallet_of(db, workspace.id)
    lines = [pricing.quote(db, workspace, w.currency, m, q, cost) for m, q, cost in items if q > 0]
    spent = month_spent(db, workspace.id)
    return Preview(w.currency, lines, w.balance, spent, judge(w, sum(q.price for q in lines), spent))


def by_key(db: Session, workspace_id: uuid.UUID, key: str | None) -> LedgerEntry | None:
    return key and db.scalar(select(LedgerEntry).where(LedgerEntry.workspace_id == workspace_id,
                                                       LedgerEntry.idempotency_key == key))


def actor_cols(actor: tuple[str, uuid.UUID] | None) -> dict:
    return {"actor_type": actor[0], "actor_id": actor[1]} if actor else {"actor_type": "system", "actor_id": None}


def insert(db: Session, w: Wallet, **values) -> LedgerEntry:
    entry = LedgerEntry(workspace_id=w.workspace_id, currency=w.currency, **values)
    db.add(entry)
    db.flush()
    db.refresh(entry, ["balance_after", "created_at"])
    db.refresh(w, ["balance"])
    return entry


def entry_data(e: LedgerEntry) -> dict:
    return {"id": e.id, "kind": e.kind, "meter": e.meter, "quantity": e.quantity, "cost": e.cost, "price": e.price,
            "amount": e.amount, "balance_after": e.balance_after, "currency": e.currency, "source": e.source,
            "subject_type": e.subject_type, "subject_id": e.subject_id}


def after_debit(db: Session, w: Wallet, before: int, spent_before: int, price: int) -> None:
    """The alerts and the auto top-up a debit can set off, each once per crossing."""
    c = w.currency
    if w.low_balance_at is not None and before >= w.low_balance_at > w.balance:
        events.emit(db, "wallet.low_balance", "wallet", w.workspace_id,
                    {"balance": w.balance, "threshold": w.low_balance_at, "currency": c}, workspace_id=w.workspace_id)
    if w.monthly_cap:
        level = w.monthly_cap * w.cap_alert_pct
        if spent_before * 100 < level <= (spent_before + price) * 100:
            events.emit(db, "usage.cap_warning", "wallet", w.workspace_id,
                        {"spent": spent_before + price, "cap": w.monthly_cap, "alert_pct": w.cap_alert_pct,
                         "currency": c, "month": month_start().date().isoformat()}, workspace_id=w.workspace_id)
    if w.auto_recharge and w.recharge_below is not None and w.balance < w.recharge_below <= before:
        jobs.enqueue(db, "wallet.recharge", {"workspace_id": str(w.workspace_id)}, max_attempts=8)


def charge(db: Session, workspace: Workspace, meter: str, quantity: int, *, source: str, key: str | None = None,
           unit_cost: int | None = None, subject: tuple[str, uuid.UUID] | None = None,
           actor: tuple[str, uuid.UUID] | None = None, enforce: bool = True,
           description: str = "") -> LedgerEntry | None:
    """Records `quantity` units of `meter` against the workspace's wallet, or raises Blocked (with `enforce`) when the
    wallet may not pay for it; the caller then does not do the action. A charge with a `key` is made once: the same key
    again answers the first entry. Nothing (None) for a quantity of 0. `enforce=False` records what must happen anyway
    (the automatic answer to a STOP, which the law requires)."""
    if quantity <= 0:
        return None
    w = wallet_of(db, workspace.id, lock=True)
    if found := by_key(db, workspace.id, key):  # read under the lock: a racing twin has committed or not started
        return found
    q = pricing.quote(db, workspace, w.currency, meter, quantity, unit_cost)
    spent = month_spent(db, workspace.id)
    verdict = judge(w, q.price, spent)
    if enforce and not verdict.allowed:
        raise Blocked(verdict.code, verdict.reason)
    before = w.balance
    entry = insert(db, w, kind="usage", meter=meter, quantity=quantity, unit_cost=q.unit_cost,
                   unit_price=q.unit_price, cost=q.cost, price=q.price, amount=-q.price, rate_card_id=q.rate_card_id,
                   source=source, subject_type=subject and subject[0], subject_id=subject and subject[1],
                   idempotency_key=key, description=(description or meters.describe(meter, quantity))[:300],
                   **actor_cols(actor))
    events.emit(db, "usage.recorded", "usage", entry.id, entry_data(entry), actor=actor, workspace_id=workspace.id)
    after_debit(db, w, before, spent, q.price)
    return entry


def reverse(db: Session, entry: LedgerEntry, reason: str, *, source: str,
            actor: tuple[str, uuid.UUID] | None = None) -> LedgerEntry:
    """Gives back a usage charge for an action that did not happen (a message the provider refused). Once per entry."""
    w = wallet_of(db, entry.workspace_id, lock=True)
    key = f"reversal:{entry.id}"
    if found := by_key(db, entry.workspace_id, key):
        return found
    back = insert(db, w, kind="reversal", meter=entry.meter, quantity=entry.quantity, unit_cost=entry.unit_cost,
                  unit_price=entry.unit_price, cost=entry.cost, price=entry.price, amount=entry.price,
                  rate_card_id=entry.rate_card_id, source=source, subject_type=entry.subject_type,
                  subject_id=entry.subject_id, reverses_id=entry.id, idempotency_key=key,
                  description=f"Refund: {reason}"[:300], **actor_cols(actor))
    events.emit(db, "usage.reversed", "usage", back.id, {**entry_data(back), "reverses_id": entry.id,
                                                         "reason": reason[:300]},
                actor=actor, workspace_id=entry.workspace_id)
    return back


def credit(db: Session, workspace_id: uuid.UUID, amount: int, *, kind: str, source: str, key: str | None = None,
           description: str = "", subject: tuple[str, uuid.UUID] | None = None,
           actor: tuple[str, uuid.UUID] | None = None) -> LedgerEntry:
    """Money in (a top-up, positive) or a correction by the organization (an adjustment, either sign). Once per key."""
    w = wallet_of(db, workspace_id, lock=True)
    if found := by_key(db, workspace_id, key):
        return found
    return insert(db, w, kind=kind, amount=amount, source=source, idempotency_key=key, description=description[:300],
                  subject_type=subject and subject[0], subject_id=subject and subject[1], **actor_cols(actor))


def usage_of(db: Session, workspace_id: uuid.UUID, subject_id: uuid.UUID) -> LedgerEntry | None:
    """The usage charge for a subject (a message); `reverse` gives it back at most once."""
    return db.scalar(select(LedgerEntry).where(
        LedgerEntry.workspace_id == workspace_id, LedgerEntry.subject_id == subject_id, LedgerEntry.kind == "usage")
        .order_by(LedgerEntry.created_at).limit(1))
