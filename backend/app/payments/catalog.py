"""What can be sold and how it is priced (module 21): products, their prices, tax rates and coupons, with the checks
every writer shares and the JSON the API answers with. Amounts are minor units (see money.py)."""
import uuid
from datetime import datetime

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from .. import events
from ..api import ApiError
from ..records.timeline import link
from . import money
from .models import Coupon, CouponRedemption, Price, Product, TaxRate


def invalid(fields: dict[str, str], message: str = "The request is not valid") -> ApiError:
    return ApiError(422, "validation_failed", message, fields)


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def tiers_of(price: Price) -> list[money.Tier]:
    return [money.Tier(t.get("up_to"), int(t.get("unit_amount") or 0), int(t.get("flat_amount") or 0))
            for t in price.tiers or []]


def price_amount(price: Price, quantity: int) -> int:
    """What `quantity` of this price costs for one period (or once), in minor units."""
    if price.scheme == "tiered":
        return money.tiered_amount(tiers_of(price), price.tiers_mode or "graduated", quantity)
    return quantity * int(price.unit_amount or 0)


def tax_json(t: TaxRate) -> dict:
    return {"id": t.id, "name": t.name, "percentage_bp": t.percentage_bp, "inclusive": t.inclusive,
            "region": t.region, "active": t.active, "created_at": t.created_at, "updated_at": t.updated_at}


def price_json(p: Price) -> dict:
    return {"id": p.id, "product_id": p.product_id, "nickname": p.nickname, "currency": p.currency, "type": p.type,
            "scheme": p.scheme, "unit_amount": p.unit_amount, "tiers": p.tiers or [], "tiers_mode": p.tiers_mode,
            "interval": p.interval, "interval_count": p.interval_count, "trial_days": p.trial_days,
            "tax_rate_id": p.tax_rate_id, "active": p.active, "created_at": p.created_at}


def product_json(p: Product, prices: list[Price]) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "kind": p.kind, "active": p.active,
            "prices": [price_json(x) for x in prices], "created_at": p.created_at, "updated_at": p.updated_at}


def coupon_json(c: Coupon) -> dict:
    return {"id": c.id, "name": c.name, "code": c.code, "percent_off_bp": c.percent_off_bp,
            "amount_off": c.amount_off, "currency": c.currency, "duration": c.duration,
            "duration_months": c.duration_months, "max_redemptions": c.max_redemptions,
            "times_redeemed": c.times_redeemed, "once_per_contact": c.once_per_contact, "price_ids": c.price_ids or [],
            "starts_at": c.starts_at, "expires_at": c.expires_at, "active": c.active, "created_at": c.created_at,
            "updated_at": c.updated_at}


def prices_of(db: Session, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Price]]:
    out: dict[uuid.UUID, list[Price]] = {i: [] for i in product_ids}
    for p in db.scalars(select(Price).where(Price.product_id.in_(product_ids)).order_by(Price.created_at, Price.id)):
        out[p.product_id].append(p)
    return out


def price_or_422(db: Session, price_id: uuid.UUID, field: str, *, active: bool = True) -> Price:
    """A price of this workspace (row level security), or a 422 on `field`. `active` refuses an archived price, or one
    of an archived product, for anything new."""
    price = db.get(Price, price_id)
    if price is None:
        raise invalid({field: "is not a price of this workspace"})
    if active:
        product = db.get(Product, price.product_id)
        if not price.active or product is None or not product.active:
            raise invalid({field: "is archived"})
    return price


def tax_or_422(db: Session, tax_rate_id: uuid.UUID | None, field: str) -> TaxRate | None:
    if tax_rate_id is None:
        return None
    tax = db.get(TaxRate, tax_rate_id)
    if tax is None or not tax.active:
        raise invalid({field: "is not an active tax rate of this workspace"})
    return tax


def check_tiers(raw: list[dict], field: str) -> list[dict]:
    try:
        tiers = [money.Tier(t.get("up_to"), int(t.get("unit_amount") or 0), int(t.get("flat_amount") or 0))
                 for t in raw]
        money.check_tiers(tiers)
    except (ValueError, TypeError, AttributeError) as e:
        raise invalid({field: str(e) or "are not valid"}) from None
    return [{"up_to": t.up_to, "unit_amount": t.unit_amount, "flat_amount": t.flat_amount} for t in tiers]


# --- coupons ----------------------------------------------------------------------------------------------------

def norm_code(code: str) -> str:
    return code.strip().upper()


def usable(db: Session, coupon: Coupon, *, contact_id: uuid.UUID | None, currency: str, price_ids: set[uuid.UUID],
           now: datetime) -> str | None:
    """Why this coupon cannot be used now on items of these prices, in words for the customer; None when it can."""
    if not coupon.active:
        return "This code is no longer valid."
    if coupon.starts_at and now < coupon.starts_at:
        return "This code is not valid yet."
    if coupon.expires_at and now >= coupon.expires_at:
        return "This code has expired."
    if coupon.max_redemptions is not None and coupon.times_redeemed >= coupon.max_redemptions:
        return "This code has been used up."
    if coupon.amount_off is not None and coupon.currency != currency:
        return f"This code is for payments in {str(coupon.currency).upper()}."
    if coupon.price_ids and not (set(coupon.price_ids) & price_ids):
        return "This code does not apply to these items."
    if coupon.once_per_contact and contact_id and db.scalar(select(exists().where(
            CouponRedemption.coupon_id == coupon.id, CouponRedemption.contact_id == contact_id))):
        return "This code has already been used."
    return None


def by_code(db: Session, code: str) -> Coupon | None:
    return db.scalar(select(Coupon).where(Coupon.code_norm == norm_code(code)))


def discount_of(coupon: Coupon | None) -> money.Discount | None:
    if coupon is None:
        return None
    return money.Discount(percent_bp=coupon.percent_off_bp, amount=coupon.amount_off)


def redeem(db: Session, coupon: Coupon, *, contact_id: uuid.UUID | None, invoice_id: uuid.UUID | None = None,
           subscription_id: uuid.UUID | None = None) -> bool:
    """Counts one use, atomically: False (nothing recorded) when the coupon was used up meanwhile."""
    used = db.execute(update(Coupon).where(Coupon.id == coupon.id, (Coupon.max_redemptions.is_(None))
                                           | (Coupon.times_redeemed < Coupon.max_redemptions))
                      .values(times_redeemed=Coupon.times_redeemed + 1).returning(Coupon.times_redeemed)).first()
    if used is None:
        return False
    row = CouponRedemption(workspace_id=coupon.workspace_id, coupon_id=coupon.id, contact_id=contact_id,
                           invoice_id=invoice_id, subscription_id=subscription_id)
    db.add(row)
    db.flush()
    db.refresh(coupon)
    event = events.emit(db, "coupon.redeemed", "coupon", coupon.id, {
        "id": coupon.id, "code": coupon.code, "contact_id": contact_id, "invoice_id": invoice_id,
        "subscription_id": subscription_id, "times_redeemed": coupon.times_redeemed}, workspace_id=coupon.workspace_id)
    if contact_id:
        link(db, event, [contact_id])
    return True


def release(db: Session, coupon_id: uuid.UUID, invoice_id: uuid.UUID) -> None:
    """Gives back the use an invoice made, when the invoice is voided or a checkout lapses unpaid."""
    gone = db.query(CouponRedemption).filter(CouponRedemption.coupon_id == coupon_id,
                                             CouponRedemption.invoice_id == invoice_id).delete()
    if gone:
        db.execute(update(Coupon).where(Coupon.id == coupon_id, Coupon.times_redeemed > 0)
                   .values(times_redeemed=Coupon.times_redeemed - gone))
