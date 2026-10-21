"""Payments API, part one (module 21): the provider account, settings, tax rates, products and prices, coupons and
payment links. Reading is `payments.read`; products, prices, coupons and links are `payments.write`; the account, the
settings and tax rates are `payments.manage`. Invoices, subscriptions and transactions are in routes_billing.py."""
import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from .. import events
from ..api import ApiError, Idem, idempotency, paginate
from ..permissions import requires
from ..security import Ctx
from . import catalog, invoicing, ledger, providers, schemas
from .catalog import invalid, not_found
from .models import Coupon, PaymentAccount, PaymentLink, Price, Product, TaxRate
from .providers.base import ProviderError

router = APIRouter(prefix="/api/v1")
read, write = requires("payments.read"), requires("payments.write")
manage = requires("payments.manage")
Limit = Annotated[int, Query(ge=1, le=200)]


def emit(c: Ctx, type_: str, subject: str, subject_id: uuid.UUID, data: dict) -> None:
    events.emit(c.db, type_, subject, subject_id, data, actor=c.author())


def provider_failed(e: ProviderError) -> ApiError:
    return ApiError(502, "provider_error", str(e))


# --- the account ------------------------------------------------------------------------------------------------

def account_view(c: Ctx) -> dict:
    acct = ledger.account_of(c.db)
    return {"account": ledger.account_json(acct), "capabilities": ledger.capabilities(acct),
            "providers": [{"key": p.key, "label": p.label, "available": p.available() is None,
                           "reason": p.available()} for p in providers.PROVIDERS.values()],
            "webhook_path": "/api/hooks/payments/stripe"}


@router.get("/payments/account")
def get_account(c: Ctx = Depends(read)):
    """The connected provider account, what can be used now and why not, and the providers this server offers."""
    return account_view(c)


@router.post("/payments/account/connect")
def connect(body: schemas.Connect, c: Ctx = Depends(manage)):
    """Connects the workspace's account at a provider. For Stripe this makes (or reuses) a Connect account and answers
    with `url`, the onboarding page to send the owner to; the account can take payments once Stripe says so (an
    `account.updated` webhook, or `POST /payments/account/refresh`)."""
    provider = providers.get(body.provider)
    reason = provider.available()
    if reason:
        raise ApiError(409, "provider_unavailable", reason)
    acct = ledger.account_of(c.db)
    keep = acct.account_id if acct and acct.provider == body.provider else None
    back = f"{ledger.origin()}/payments/settings"
    try:
        onboarding = provider.connect(str(c.workspace.id), keep, f"{back}?connected=1", f"{back}?retry=1")
        state = provider.account(onboarding.account_id)
    except ProviderError as e:
        raise provider_failed(e) from None
    if acct is None:
        acct = PaymentAccount(workspace_id=c.workspace.id, provider=body.provider, account_id=onboarding.account_id,
                              connected_by=c.user_id)
        c.db.add(acct)
    acct.provider, acct.account_id, acct.connected_by = body.provider, onboarding.account_id, c.user_id
    acct.status = "pending"
    try:
        with c.db.begin_nested():
            c.db.flush()
    except IntegrityError:
        raise ApiError(409, "conflict", "That provider account is connected to another workspace") from None
    ledger.copy_state(acct, state)
    c.db.flush()
    events.emit(c.db, "payment_account.updated", "payment_account", acct.id,
                {"provider": acct.provider, "status": acct.status, "charges_enabled": acct.charges_enabled,
                 "changes": {"account_id": {"old": keep, "new": acct.account_id}}}, actor=c.author())
    c.db.commit()
    return {**account_view(c), "url": onboarding.url}


@router.post("/payments/account/refresh")
def refresh(c: Ctx = Depends(manage)):
    acct = ledger.account_of(c.db)
    if acct is None or acct.status == "disconnected":
        raise ApiError(409, "conflict", "No provider account is connected")
    try:
        state = providers.get(acct.provider).account(acct.account_id)
    except ProviderError as e:
        raise provider_failed(e) from None
    ledger.apply_account(c, acct, state)
    c.db.commit()
    return account_view(c)


@router.delete("/payments/account")
def disconnect(c: Ctx = Depends(manage)):
    """Stops taking online payments. Payments, refunds and the provider's ids of the past are kept; webhooks for them
    still apply."""
    acct = ledger.account_of(c.db)
    if acct is None or acct.status == "disconnected":
        raise ApiError(409, "conflict", "No provider account is connected")
    acct.status, acct.updated_at = "disconnected", func.now()
    events.emit(c.db, "payment_account.updated", "payment_account", acct.id,
                {"provider": acct.provider, "status": "disconnected", "charges_enabled": acct.charges_enabled,
                 "changes": {"status": {"old": "active", "new": "disconnected"}}}, actor=c.author())
    c.db.commit()
    return account_view(c)


# --- settings ---------------------------------------------------------------------------------------------------

SETTINGS = ("default_currency", "invoice_prefix", "invoice_due_days", "retry_days", "after_retries", "business_name",
            "business_details", "invoice_footer")


def settings_json(s) -> dict:
    return {k: getattr(s, k) for k in SETTINGS} | {"next_invoice_number": s.next_invoice_number,
                                                  "updated_at": s.updated_at}


@router.get("/payments/settings")
def get_settings(c: Ctx = Depends(read)):
    s = invoicing.settings_of(c.db, c.workspace.id)
    c.db.commit()
    return settings_json(s)


@router.patch("/payments/settings")
def patch_settings(body: schemas.SettingsPatch, c: Ctx = Depends(manage)):
    s = invoicing.settings_of(c.db, c.workspace.id, lock=True)
    changes = {}
    for key in body.model_fields_set:
        value = getattr(body, key)
        if value is None:
            raise invalid({key: "cannot be null"})
        if key == "retry_days" and value != sorted(set(value)):
            raise invalid({key: "must rise, each day after the one before"})
        if getattr(s, key) != value:
            changes[key] = {"old": getattr(s, key), "new": value}
            setattr(s, key, value)
    if changes:
        s.updated_at = func.now()
        emit(c, "payment_settings.updated", "payment_settings", c.workspace.id, {"changes": changes})
    c.db.commit()
    return settings_json(s)


# --- tax rates --------------------------------------------------------------------------------------------------

@router.get("/tax-rates")
def list_tax_rates(c: Ctx = Depends(read)):
    rows = c.db.scalars(select(TaxRate).order_by(TaxRate.active.desc(), func.lower(TaxRate.name), TaxRate.id))
    return {"data": [catalog.tax_json(t) for t in rows], "next_cursor": None}


@router.post("/tax-rates", status_code=201)
def create_tax_rate(body: schemas.TaxIn, c: Ctx = Depends(manage), idem: Idem = Depends(idempotency)):
    t = TaxRate(workspace_id=c.workspace.id, **body.model_dump())
    c.db.add(t)
    c.db.flush()
    emit(c, "tax_rate.created", "tax_rate", t.id, catalog.tax_json(t))
    return idem.commit(201, catalog.tax_json(t))


@router.patch("/tax-rates/{tax_rate_id}")
def patch_tax_rate(tax_rate_id: uuid.UUID, body: schemas.TaxPatch, c: Ctx = Depends(manage)):
    """The name, region and whether it is active; the percentage of a rate never changes (invoices keep theirs)."""
    t = c.db.get(TaxRate, tax_rate_id)
    if t is None:
        raise not_found("Tax rate")
    changes = apply(t, body)
    if changes:
        t.updated_at = func.now()
        c.db.flush()
        emit(c, "tax_rate.updated", "tax_rate", t.id, {**catalog.tax_json(t), "changes": changes})
    c.db.commit()
    return catalog.tax_json(t)


def apply(row, body) -> dict:
    changes = {}
    for key in body.model_fields_set:
        value = getattr(body, key)
        if value is None and key not in ("redirect_url", "max_redemptions", "expires_at"):
            raise invalid({key: "cannot be null"})
        if getattr(row, key) != value:
            changes[key] = {"old": getattr(row, key), "new": value}
            setattr(row, key, value)
    return events.changes({k: v["old"] for k, v in changes.items()}, {k: v["new"] for k, v in changes.items()})


# --- products and prices ----------------------------------------------------------------------------------------

def new_price(c: Ctx, product: Product, body: schemas.PriceIn, field: str) -> Price:
    errors = {}
    if body.scheme == "fixed":
        if body.unit_amount is None:
            errors[f"{field}.unit_amount"] = "is required for a fixed price"
        if body.tiers:
            errors[f"{field}.tiers"] = "are only for a tiered price"
    else:
        if body.unit_amount is not None:
            errors[f"{field}.unit_amount"] = "is not used by a tiered price: set the tiers"
        if body.tiers_mode is None:
            errors[f"{field}.tiers_mode"] = "is required for a tiered price"
    if body.type == "recurring" and body.interval is None:
        errors[f"{field}.interval"] = "is required for a recurring price"
    if body.type == "one_time" and (body.interval is not None or body.trial_days):
        errors[f"{field}.interval"] = "is only for a recurring price"
    if errors:
        raise invalid(errors)
    tiers = catalog.check_tiers([t.model_dump() for t in body.tiers], f"{field}.tiers") if body.scheme == "tiered" \
        else []
    catalog.tax_or_422(c.db, body.tax_rate_id, f"{field}.tax_rate_id")
    p = Price(workspace_id=c.workspace.id, product_id=product.id, nickname=body.nickname, currency=body.currency,
              type=body.type, scheme=body.scheme, unit_amount=body.unit_amount, tiers=tiers,
              tiers_mode=body.tiers_mode if body.scheme == "tiered" else None,
              interval=body.interval if body.type == "recurring" else None,
              interval_count=body.interval_count if body.type == "recurring" else 1,
              trial_days=body.trial_days if body.type == "recurring" else 0, tax_rate_id=body.tax_rate_id,
              created_at=func.clock_timestamp())  # prices made together keep the order they were sent in
    c.db.add(p)
    c.db.flush()
    emit(c, "price.created", "price", p.id, catalog.price_json(p))
    return p


def product_detail(c: Ctx, p: Product) -> dict:
    return catalog.product_json(p, catalog.prices_of(c.db, [p.id])[p.id])


@router.get("/products")
def list_products(active: bool | None = True, q: str | None = None, limit: Limit = 50, cursor: str | None = None,
                  c: Ctx = Depends(read)):
    """Products with their prices, newest first. `active=false` lists the archived ones, no `active` both."""
    stmt = select(Product)
    if active is not None:
        stmt = stmt.where(Product.active.is_(active))
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    rows, nxt = paginate(c.db, stmt, Product, limit, cursor)
    products = [r[0] for r in rows]
    prices = catalog.prices_of(c.db, [p.id for p in products])
    return {"data": [catalog.product_json(p, prices[p.id]) for p in products], "next_cursor": nxt}


@router.post("/products", status_code=201)
def create_product(body: schemas.ProductIn, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    p = Product(workspace_id=c.workspace.id, name=body.name, description=body.description, kind=body.kind)
    c.db.add(p)
    c.db.flush()
    emit(c, "product.created", "product", p.id, {"id": p.id, "name": p.name, "kind": p.kind, "active": True})
    for i, price in enumerate(body.prices):
        new_price(c, p, price, f"prices.{i}")
    return idem.commit(201, product_detail(c, p))


def product_or_404(c: Ctx, product_id: uuid.UUID) -> Product:
    p = c.db.get(Product, product_id)
    if p is None:
        raise not_found("Product")
    return p


@router.get("/products/{product_id}")
def get_product(product_id: uuid.UUID, c: Ctx = Depends(read)):
    return product_detail(c, product_or_404(c, product_id))


@router.patch("/products/{product_id}")
def patch_product(product_id: uuid.UUID, body: schemas.ProductPatch, c: Ctx = Depends(write)):
    p = product_or_404(c, product_id)
    changes = apply(p, body)
    if changes:
        p.updated_at = func.now()
        c.db.flush()
        emit(c, "product.updated", "product", p.id, {"id": p.id, "name": p.name, "kind": p.kind,
                                                     "active": p.active, "changes": changes})
    c.db.commit()
    return product_detail(c, p)


@router.delete("/products/{product_id}")
def archive_product(product_id: uuid.UUID, c: Ctx = Depends(write)):
    """Archives the product: its prices can no longer be put on anything new; what uses them goes on as it is."""
    return patch_product(product_id, schemas.ProductPatch(active=False), c)


@router.post("/products/{product_id}/prices", status_code=201)
def create_price(product_id: uuid.UUID, body: schemas.PriceIn, c: Ctx = Depends(write),
                 idem: Idem = Depends(idempotency)):
    p = product_or_404(c, product_id)
    if not p.active:
        raise ApiError(409, "conflict", "The product is archived")
    return idem.commit(201, catalog.price_json(new_price(c, p, body, "price")))


@router.get("/prices")
def list_prices(type: str | None = None, currency: str | None = None, active: bool | None = True,
                c: Ctx = Depends(read)):
    """Every price of the workspace with its product's name, for pickers (a workspace has dozens, not thousands).
    ponytail: not paged; add the cursor when a catalog grows past a few thousand prices."""
    stmt = select(Price, Product).join(Product, Product.id == Price.product_id).order_by(
        func.lower(Product.name), Price.created_at, Price.id)
    if active is not None:
        stmt = stmt.where(Price.active.is_(active), Product.active.is_(active)) if active else \
            stmt.where(or_(Price.active.is_(False), Product.active.is_(False)))
    if type:
        stmt = stmt.where(Price.type == type)
    if currency:
        stmt = stmt.where(Price.currency == currency.lower())
    rows = c.db.execute(stmt.limit(5000)).all()
    return {"data": [{**catalog.price_json(p), "product_name": prod.name} for p, prod in rows], "next_cursor": None}


@router.patch("/prices/{price_id}")
def patch_price(price_id: uuid.UUID, body: schemas.PricePatch, c: Ctx = Depends(write)):
    """Only the nickname and whether it is active: amounts never change once saved (make a new price instead)."""
    p = c.db.get(Price, price_id)
    if p is None:
        raise not_found("Price")
    changes = apply(p, body)
    if changes:
        c.db.flush()
        emit(c, "price.updated", "price", p.id, {**catalog.price_json(p), "changes": changes})
    c.db.commit()
    return catalog.price_json(p)


# --- coupons ----------------------------------------------------------------------------------------------------

@router.get("/coupons")
def list_coupons(active: bool | None = None, limit: Limit = 50, cursor: str | None = None, c: Ctx = Depends(read)):
    stmt = select(Coupon)
    if active is not None:
        stmt = stmt.where(Coupon.active.is_(active))
    rows, nxt = paginate(c.db, stmt, Coupon, limit, cursor)
    return {"data": [catalog.coupon_json(r[0]) for r in rows], "next_cursor": nxt}


@router.post("/coupons", status_code=201)
def create_coupon(body: schemas.CouponIn, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    errors = {}
    if (body.percent_off_bp is None) == (body.amount_off is None):
        errors["percent_off_bp"] = "set either a percentage or an amount off"
    if body.amount_off is not None and body.currency is None:
        errors["currency"] = "is required with an amount off"
    if body.duration == "repeating" and body.duration_months is None:
        errors["duration_months"] = "is required for a repeating coupon"
    if body.duration != "repeating" and body.duration_months is not None:
        errors["duration_months"] = "is only for a repeating coupon"
    if body.starts_at and body.expires_at and body.expires_at <= body.starts_at:
        errors["expires_at"] = "must be after the start"
    for i, pid in enumerate(body.price_ids):
        if c.db.get(Price, pid) is None:
            errors[f"price_ids.{i}"] = "is not a price of this workspace"
    if errors:
        raise invalid(errors)
    coupon = Coupon(workspace_id=c.workspace.id, name=body.name, code=body.code, code_norm=catalog.norm_code(body.code),
                    percent_off_bp=body.percent_off_bp, amount_off=body.amount_off,
                    currency=body.currency if body.amount_off is not None else None, duration=body.duration,
                    duration_months=body.duration_months, max_redemptions=body.max_redemptions,
                    once_per_contact=body.once_per_contact, price_ids=list(dict.fromkeys(body.price_ids)),
                    starts_at=body.starts_at, expires_at=body.expires_at)
    try:
        with c.db.begin_nested():
            c.db.add(coupon)
    except IntegrityError:
        raise ApiError(409, "conflict", f"The code {body.code} is taken", {"code": "is already used"}) from None
    emit(c, "coupon.created", "coupon", coupon.id, {"id": coupon.id, "code": coupon.code, "active": True})
    return idem.commit(201, catalog.coupon_json(coupon))


def coupon_or_404(c: Ctx, coupon_id: uuid.UUID) -> Coupon:
    coupon = c.db.get(Coupon, coupon_id)
    if coupon is None:
        raise not_found("Coupon")
    return coupon


@router.get("/coupons/{coupon_id}")
def get_coupon(coupon_id: uuid.UUID, c: Ctx = Depends(read)):
    return catalog.coupon_json(coupon_or_404(c, coupon_id))


@router.patch("/coupons/{coupon_id}")
def patch_coupon(coupon_id: uuid.UUID, body: schemas.CouponPatch, c: Ctx = Depends(write)):
    """The name, the limit, the end and whether it is active; what it takes off never changes."""
    coupon = c.db.scalar(select(Coupon).where(Coupon.id == coupon_id).with_for_update())
    if coupon is None:
        raise not_found("Coupon")
    if body.max_redemptions is not None and body.max_redemptions < coupon.times_redeemed:
        raise invalid({"max_redemptions": f"cannot be below the {coupon.times_redeemed} uses so far"})
    changes = apply(coupon, body)
    if changes:
        coupon.updated_at = func.now()
        c.db.flush()
        emit(c, "coupon.updated", "coupon", coupon.id, {"id": coupon.id, "code": coupon.code, "active": coupon.active,
                                                        "changes": changes})
    c.db.commit()
    return catalog.coupon_json(coupon)


# --- payment links ----------------------------------------------------------------------------------------------

def link_json(link: PaymentLink) -> dict:
    path = f"/pay/{link.public_key}"
    return {"id": link.id, "name": link.name, "active": link.active, "items": link.items,
            "allow_coupons": link.allow_coupons, "collect_phone": link.collect_phone,
            "success_message": link.success_message, "redirect_url": link.redirect_url, "public_path": path,
            "public_url": f"{ledger.origin()}{path}", "created_at": link.created_at, "updated_at": link.updated_at}


def check_items(c: Ctx, items: list[schemas.LinkItem]) -> list[dict]:
    """The items as stored, after checking they make one checkout: active prices of one currency, at most one
    recurring price (a subscription) and the quantities within their bounds."""
    errors, currencies, recurring = {}, set(), 0
    for i, item in enumerate(items):
        try:
            price = catalog.price_or_422(c.db, item.price_id, f"items.{i}.price_id")
        except ApiError as e:
            errors.update(e.fields or {})
            continue
        currencies.add(price.currency)
        recurring += price.type == "recurring"
        if item.adjustable and not item.min <= item.quantity <= item.max:
            errors[f"items.{i}.quantity"] = "must be between min and max"
    if len(currencies) > 1:
        errors["items"] = "must all be in one currency"
    if recurring > 1 or (recurring and len(items) > 1):
        errors["items"] = "a link with a recurring price sells that one price alone"
    if errors:
        raise invalid(errors)
    return [{"price_id": str(i.price_id), "quantity": i.quantity, "adjustable": i.adjustable,
             "min": i.min if i.adjustable else i.quantity, "max": i.max if i.adjustable else i.quantity}
            for i in items]


@router.get("/payment-links")
def list_links(active: bool | None = None, limit: Limit = 50, cursor: str | None = None, c: Ctx = Depends(read)):
    stmt = select(PaymentLink)
    if active is not None:
        stmt = stmt.where(PaymentLink.active.is_(active))
    rows, nxt = paginate(c.db, stmt, PaymentLink, limit, cursor)
    return {"data": [link_json(r[0]) for r in rows], "next_cursor": nxt}


@router.post("/payment-links", status_code=201)
def create_link(body: schemas.LinkIn, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    link = PaymentLink(workspace_id=c.workspace.id, name=body.name, public_key=secrets.token_urlsafe(18),
                       items=check_items(c, body.items), allow_coupons=body.allow_coupons,
                       collect_phone=body.collect_phone, success_message=body.success_message,
                       redirect_url=body.redirect_url, created_by=c.user_id)
    c.db.add(link)
    c.db.flush()
    emit(c, "payment_link.created", "payment_link", link.id, {"id": link.id, "name": link.name, "active": True})
    return idem.commit(201, link_json(link))


def link_or_404(c: Ctx, link_id: uuid.UUID) -> PaymentLink:
    link = c.db.get(PaymentLink, link_id)
    if link is None:
        raise not_found("Payment link")
    return link


@router.get("/payment-links/{link_id}")
def get_link(link_id: uuid.UUID, c: Ctx = Depends(read)):
    return link_json(link_or_404(c, link_id))


@router.patch("/payment-links/{link_id}")
def patch_link(link_id: uuid.UUID, body: schemas.LinkPatch, c: Ctx = Depends(write)):
    link = link_or_404(c, link_id)
    if body.items is not None:
        body.items = check_items(c, body.items)  # type: ignore[assignment]
    changes = apply(link, body)
    if changes:
        link.updated_at = func.now()
        c.db.flush()
        emit(c, "payment_link.updated", "payment_link", link.id, {"id": link.id, "name": link.name,
                                                                  "active": link.active, "changes": changes})
    c.db.commit()
    return link_json(link)
