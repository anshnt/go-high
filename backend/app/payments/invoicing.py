"""Invoices (module 21): lines and totals, numbering, issuing, payment and voiding. Every way money is asked for (a
manual invoice, a payment link checkout, a subscription period, a plan change) is an invoice, so there is one place
where totals are worked out (money.py) and one place where a payment is applied to what it paid for (`apply_payment`).

Numbers are given when an invoice is issued (sent, or paid at a checkout), from a counter on the workspace's settings
row taken under a row lock, so two invoices can never share a number and issued numbers have no gaps; a draft has none.
The public link of an invoice is derived (an HMAC of its id under SECRET_KEY), not stored: it can be shown again any
time, and changing SECRET_KEY changes every link."""
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .. import config, events
from ..api import ApiError
from ..records.timeline import link
from ..security import Ctx
from . import catalog, money
from .models import Coupon, Invoice, InvoiceLine, Payment, PaymentSettings, Price, Product, Subscription, TaxRate

OPEN_FOR = ("open",)


@dataclass
class LineSpec:
    description: str | None = None
    price_id: uuid.UUID | None = None
    quantity: int = 1
    unit_amount: int | None = None  # a custom line; ignored when a price is given
    tax_rate_id: uuid.UUID | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    proration: bool = False
    amount: int | None = None  # a computed amount (a proration); overrides quantity times unit
    discountable: bool = True


def settings_of(db: Session, workspace_id: uuid.UUID, *, lock: bool = False) -> PaymentSettings:
    """The workspace's payment settings row, made with the defaults the first time it is needed."""
    db.execute(pg_insert(PaymentSettings).values(workspace_id=workspace_id).on_conflict_do_nothing())
    stmt = select(PaymentSettings).where(PaymentSettings.workspace_id == workspace_id)
    return db.scalar((stmt.with_for_update() if lock else stmt).execution_options(populate_existing=True))


def token(inv: Invoice) -> str:
    mac = hmac.new(config.SECRET_KEY.encode(), f"invoice:{inv.id}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{inv.workspace_id.hex}.{inv.id.hex}.{mac}"


def parse_token(raw: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(workspace id, invoice id) of a genuine link, else None. Checked in constant time."""
    try:
        ws, inv, mac = raw.split(".")
        inv_id = uuid.UUID(inv)
        expected = hmac.new(config.SECRET_KEY.encode(), f"invoice:{inv_id}".encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(mac, expected):
            return None
        return uuid.UUID(ws), inv_id
    except ValueError:
        return None


def public_path(inv: Invoice) -> str | None:
    if inv.status == "draft" or (inv.status == "void" and inv.number is None):
        return None
    return f"/invoice/{token(inv)}"


def amount_due(inv: Invoice) -> int:
    return max(inv.total - inv.amount_paid, 0) if inv.status == "open" else 0


def lines_of(db: Session, invoice_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[InvoiceLine]]:
    out: dict[uuid.UUID, list[InvoiceLine]] = {i: [] for i in invoice_ids}
    for line in db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id.in_(invoice_ids))
                           .order_by(InvoiceLine.invoice_id, InvoiceLine.position)):
        out[line.invoice_id].append(line)
    return out


def line_json(line: InvoiceLine) -> dict:
    return {"id": line.id, "description": line.description, "price_id": line.price_id, "quantity": line.quantity,
            "unit_amount": line.unit_amount, "amount": line.amount, "discount": line.discount,
            "tax_rate_id": line.tax_rate_id, "tax_name": line.tax_name, "tax_bp": line.tax_bp,
            "tax_inclusive": line.tax_inclusive, "tax": line.tax, "total": line.total,
            "period_start": line.period_start, "period_end": line.period_end, "proration": line.proration}


def invoice_json(inv: Invoice, lines: list[InvoiceLine] | None, contact: dict | None) -> dict:
    path = public_path(inv)
    out = {"id": inv.id, "number": inv.number, "status": inv.status, "billing_reason": inv.billing_reason,
           "contact_id": inv.contact_id if contact else None, "contact": contact, "currency": inv.currency,
           "subscription_id": inv.subscription_id, "payment_link_id": inv.payment_link_id, "coupon_id": inv.coupon_id,
           "subtotal": inv.subtotal, "discount": inv.discount, "tax": inv.tax, "credit_applied": inv.credit_applied,
           "total": inv.total, "amount_paid": inv.amount_paid, "amount_due": amount_due(inv), "due_at": inv.due_at,
           "issued_at": inv.issued_at, "paid_at": inv.paid_at, "voided_at": inv.voided_at, "expires_at": inv.expires_at,
           "period_start": inv.period_start, "period_end": inv.period_end, "memo": inv.memo, "footer": inv.footer,
           "attempt_count": inv.attempt_count, "next_attempt_at": inv.next_attempt_at,
           "public_path": path, "public_url": path and f"{config.ALLOWED_ORIGINS[0]}{path}",
           "created_at": inv.created_at, "updated_at": inv.updated_at}
    if lines is not None:
        out["lines"] = [line_json(x) for x in lines]
    return out


def event_data(inv: Invoice) -> dict:
    return {"id": inv.id, "number": inv.number, "status": inv.status, "billing_reason": inv.billing_reason,
            "contact_id": inv.contact_id, "currency": inv.currency, "total": inv.total, "amount_paid": inv.amount_paid,
            "amount_due": amount_due(inv), "subscription_id": inv.subscription_id, "due_at": inv.due_at}


def emit(c: Ctx, type_: str, inv: Invoice, extra: dict | None = None) -> None:
    event = events.emit(c.db, type_, "invoice", inv.id, {**event_data(inv), **(extra or {})}, actor=c.author(),
                        workspace_id=inv.workspace_id)
    if inv.contact_id:
        link(c.db, event, [inv.contact_id])


def describe(db: Session, price: Price) -> str:
    product = db.get(Product, price.product_id)
    name = product.name if product else "Item"
    return f"{name} ({price.nickname})" if price.nickname else name


def write_lines(c: Ctx, inv: Invoice, specs: list[LineSpec], coupon: Coupon | None, *, credit: int = 0) -> int:
    """Replaces the invoice's lines with these and works out its totals. `credit` (minor units owed to the customer)
    is taken off the total as far as it goes. Returns what is left owed to the customer: the credit not used, plus a
    negative total (credits that outweigh the charges) turned into credit. Prices must be in the invoice's currency."""
    db = c.db
    db.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id == inv.id))
    rows, ins = [], []
    errors: dict[str, str] = {}
    for i, spec in enumerate(specs):
        price = None
        if spec.price_id is not None:
            price = catalog.price_or_422(db, spec.price_id, f"lines.{i}.price_id", active=not spec.proration)
            if price.currency != inv.currency:
                errors[f"lines.{i}.price_id"] = f"is in {price.currency.upper()}, the invoice is in " \
                                                f"{inv.currency.upper()}"
                continue
        tax_id = spec.tax_rate_id or (price.tax_rate_id if price else None)
        tax = db.get(TaxRate, tax_id) if tax_id else None
        if spec.tax_rate_id and (tax is None or not tax.active):
            errors[f"lines.{i}.tax_rate_id"] = "is not an active tax rate of this workspace"
            continue
        if spec.amount is not None:
            amount, unit = spec.amount, spec.amount
        elif price is not None:
            amount = catalog.price_amount(price, spec.quantity)
            unit = price.unit_amount if price.scheme == "fixed" else amount
        elif spec.unit_amount is not None:
            amount, unit = spec.quantity * spec.unit_amount, spec.unit_amount
        else:
            errors[f"lines.{i}.unit_amount"] = "is required for a line without a price"
            continue
        if abs(amount) > money.MAX_AMOUNT:
            errors[f"lines.{i}.unit_amount"] = "is too large"
            continue
        description = (spec.description or "").strip() or (describe(db, price) if price else "")
        if not description:
            errors[f"lines.{i}.description"] = "is required for a line without a price"
            continue
        discountable = spec.discountable and amount > 0 and (
            coupon is None or not coupon.price_ids or (price is not None and price.id in coupon.price_ids))
        rows.append((spec, price, tax, amount, unit, description[:500]))
        ins.append(money.LineIn(amount, tax.percentage_bp if tax else 0, bool(tax and tax.inclusive), discountable))
    if errors:
        raise catalog.invalid(errors)
    t = money.totals(ins, catalog.discount_of(coupon))
    for position, ((spec, price, tax, amount, unit, description), out) in enumerate(zip(rows, t.lines, strict=True)):
        db.add(InvoiceLine(workspace_id=inv.workspace_id, invoice_id=inv.id, position=position,
                           description=description, price_id=price.id if price else None, quantity=spec.quantity,
                           unit_amount=unit, amount=amount, discount=out.discount,
                           tax_rate_id=tax.id if tax else None, tax_name=tax.name if tax else "",
                           tax_bp=tax.percentage_bp if tax else 0, tax_inclusive=bool(tax and tax.inclusive),
                           tax=out.tax, total=out.total, period_start=spec.period_start,
                           period_end=spec.period_end, proration=spec.proration))
    if t.total > money.MAX_AMOUNT:
        raise catalog.invalid({"lines": "the invoice total is too large"})
    applied = min(credit, max(t.total, 0))
    inv.subtotal, inv.discount, inv.tax = t.subtotal, t.discount, t.tax
    inv.credit_applied, inv.total = applied, max(t.total - applied, 0)
    inv.coupon_id = coupon.id if coupon else None
    inv.updated_at = func.now()
    db.flush()
    return (credit - applied) + max(-t.total, 0)


def issue(c: Ctx, inv: Invoice, now: datetime, *, number: bool = True, due_days: int | None = None) -> None:
    """Draft to open: the next number (unless `number` is False: a checkout invoice gets its number when paid), the
    issue and due dates, the coupon's use. An invoice of nothing to pay is paid at once. The caller commits."""
    s = settings_of(c.db, inv.workspace_id, lock=number)
    if number:
        inv.number = f"{s.invoice_prefix}{s.next_invoice_number:04d}"
        s.next_invoice_number += 1
    inv.status, inv.issued_at = "open", now
    if inv.due_at is None:
        inv.due_at = now + timedelta(days=s.invoice_due_days if due_days is None else due_days)
    if inv.footer == "" and s.invoice_footer:
        inv.footer = s.invoice_footer
    if inv.coupon_id and inv.subscription_id is None:  # a subscription's coupon was counted when it was made
        coupon = c.db.get(Coupon, inv.coupon_id)
        if coupon is None or not catalog.redeem(c.db, coupon, contact_id=inv.contact_id, invoice_id=inv.id):
            raise ApiError(409, "coupon_used_up", "The coupon has been used up meanwhile; remove it and try again.",
                           {"coupon_code": "has been used up"})
    c.db.flush()
    if number:
        emit(c, "invoice.sent", inv)
    if inv.total == 0:
        mark_paid(c, inv, now)


def assign_number(c: Ctx, inv: Invoice) -> None:
    if inv.number is None:
        s = settings_of(c.db, inv.workspace_id, lock=True)
        inv.number = f"{s.invoice_prefix}{s.next_invoice_number:04d}"
        s.next_invoice_number += 1


def mark_paid(c: Ctx, inv: Invoice, now: datetime) -> None:
    from . import billing  # billing imports this module
    assign_number(c, inv)
    inv.status, inv.paid_at, inv.next_attempt_at, inv.updated_at = "paid", now, None, now
    c.db.flush()
    emit(c, "invoice.paid", inv)
    billing.invoice_paid(c, inv, now)


def apply_payment(c: Ctx, inv: Invoice, amount: int, now: datetime) -> int:
    """Adds a succeeded payment to the invoice (locked by the caller) and returns the part of it the invoice did not
    need (paid twice, or paid after it was voided), which the caller gives back. Marks the invoice paid when it is."""
    if inv.status != "open":
        return amount
    take = min(amount, inv.total - inv.amount_paid)
    inv.amount_paid += take
    inv.updated_at = now
    c.db.flush()
    if inv.amount_paid >= inv.total:
        mark_paid(c, inv, now)
    return amount - take


def lock(db: Session, invoice_id: uuid.UUID) -> Invoice | None:
    return db.scalar(select(Invoice).where(Invoice.id == invoice_id).with_for_update()
                     .execution_options(populate_existing=True))


def void(c: Ctx, inv: Invoice, now: datetime, reason: str = "voided") -> None:
    """Open to void: nothing more can be paid on it, its coupon use is given back. A payment that arrives later is
    refunded. The caller commits."""
    inv.status, inv.voided_at, inv.next_attempt_at, inv.updated_at = "void", now, None, now
    if inv.coupon_id:
        catalog.release(c.db, inv.coupon_id, inv.id)
    c.db.execute(Payment.__table__.update().where(Payment.invoice_id == inv.id, Payment.status == "pending")
                 .values(status="canceled", updated_at=now))
    c.db.flush()
    emit(c, "invoice.voided", inv, {"reason": reason})


def new(c: Ctx, *, contact_id: uuid.UUID | None, currency: str, reason: str = "manual",
        subscription: Subscription | None = None, **values) -> Invoice:
    inv = Invoice(workspace_id=c.workspace.id, contact_id=contact_id, currency=currency, billing_reason=reason,
                  subscription_id=subscription.id if subscription else None, created_by=c.user_id, **values)
    c.db.add(inv)
    c.db.flush()
    return inv
