"""What a unit costs and what a workspace pays for it. The cost is the channel's own carrier rate when the caller has
one (`segment_cost`), else the platform's (meters.COSTS). The price comes from the most specific rate card of the
workspace's organization for that meter and the wallet's currency (workspace, then brand, then organization): its
fixed price, or the cost with its markup; with no card the price is the cost. Markup hooks then get the last word: a
later module (SaaS mode and rebilling, module 30) registers one with `markup_hook` to price by plan, and the ledger
records whatever price it settles on next to the cost, so the margin of every line is visible.

ponytail: costs and prices are in the wallet's currency; there are no exchange rates, so a platform cost in USD
charged to a EUR wallet is taken as EUR. Cards are per currency for that reason."""
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from . import meters, money
from .models import RateCard


@dataclass(frozen=True)
class Quote:
    meter: str
    quantity: int
    unit_cost: int
    unit_price: int
    rate_card_id: uuid.UUID | None = None
    basis: str = "cost"  # cost (no card), price (a card's fixed price), markup (a card's markup), hook

    @property
    def cost(self) -> int:
        return self.unit_cost * self.quantity

    @property
    def price(self) -> int:
        return self.unit_price * self.quantity

    def json(self, currency: str) -> dict:
        return {"meter": self.meter, "label": meters.METERS[self.meter][0], "quantity": self.quantity,
                "unit": meters.METERS[self.meter][1 if self.quantity == 1 else 2], "unit_cost": self.unit_cost,
                "unit_price": self.unit_price, "cost": self.cost, "price": self.price, "currency": currency,
                "rate_card_id": self.rate_card_id, "basis": self.basis}


# (workspace_id, org_id, brand_id, quote) -> quote; registered in order, each sees the previous one's answer
Hook = Callable[[uuid.UUID, uuid.UUID, uuid.UUID, Quote], Quote]
HOOKS: list[Hook] = []


def markup_hook(fn: Hook) -> Hook:
    """Registers a function that may change a quote's `unit_price` (never its cost) before it is charged."""
    HOOKS.append(fn)
    return fn


def card_for(db: Session, org_id: uuid.UUID, brand_id: uuid.UUID, workspace_id: uuid.UUID, meter: str,
             currency: str) -> RateCard | None:
    specific = case((RateCard.workspace_id.is_not(None), 0), (RateCard.brand_id.is_not(None), 1), else_=2)
    return db.scalar(select(RateCard).where(
        RateCard.org_id == org_id, RateCard.meter == meter, RateCard.currency == currency,
        or_(RateCard.workspace_id == workspace_id, RateCard.brand_id == brand_id,
            (RateCard.workspace_id.is_(None) & RateCard.brand_id.is_(None)))).order_by(specific).limit(1))


def quote(db: Session, workspace, currency: str, meter: str, quantity: int, unit_cost: int | None = None) -> Quote:
    """`workspace` is a Workspace row. `unit_cost` overrides the platform's cost (a channel's carrier rate)."""
    if meter not in meters.METERS:
        raise ValueError(f"unknown meter {meter!r}")
    cost = meters.platform_cost(meter) if unit_cost is None else max(0, unit_cost)
    card = card_for(db, workspace.org_id, workspace.brand_id, workspace.id, meter, currency)
    if card is None:
        q = Quote(meter, quantity, cost, cost)
    elif card.price is not None:
        q = Quote(meter, quantity, cost, card.price, card.id, "price")
    else:
        q = Quote(meter, quantity, cost, money.with_markup(cost, card.markup_bp), card.id, "markup")
    for hook in HOOKS:
        changed = hook(workspace.id, workspace.org_id, workspace.brand_id, q)
        q = replace(q, unit_price=max(0, changed.unit_price), basis="hook") if changed.unit_price != q.unit_price else q
    return q
