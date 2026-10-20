"""Payments API, part two (module 21): invoices, subscriptions, transactions and refunds. Reading is `payments.read`;
drafting, sending and subscriptions are `payments.write`; refunds, voiding and recording money taken outside go-high
are `payments.refund`. A contact is shown only to someone who may see it (`contact` null otherwise), as everywhere."""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select

from ..api import ApiError, Idem, idempotency, paginate
from ..calendars.contacts import visible
from ..permissions import requires
from ..records import store
from ..records.schema import Catalog
from ..security import Ctx
from . import billing, catalog, invoicing, ledger, schemas
from .catalog import invalid, not_found
from .invoicing import LineSpec
from .models import Invoice, Payment, PaymentCustomer, Price, Product, Refund, Subscription

router = APIRouter(prefix="/api/v1")
read, write = requires("payments.read"), requires("payments.write")
money_out = requires("payments.refund")
Limit = Annotated[int, Query(ge=1, le=200)]


def now() -> datetime:
    return datetime.now(UTC)


def contact_or_422(c: Ctx, contact_id: uuid.UUID, field: str = "contact_id") -> uuid.UUID:
    cat = Catalog(c)
    try:
        store.get(cat, cat.need("contact"), contact_id)
    except HTTPException:
        raise invalid({field: "is not a contact you can see"}) from None
    return contact_id


def contacts_of(c: Ctx, ids) -> dict:
    names = visible(c, {i for i in ids if i})
    return {i: {"id": i, "display_name": n} for i, n in names.items()}


def coupon_from_code(c: Ctx, code: str | None, *, contact_id, currency: str, price_ids: set, at: datetime):
    if not code:
        return None
    coupon = catalog.by_code(c.db, code)
    reason = "This code does not exist." if coupon is None else catalog.usable(
        c.db, coupon, contact_id=contact_id, currency=currency, price_ids=price_ids, now=at)
    if reason:
        raise invalid({"coupon_code": reason})
    return coupon


def specs_of(lines: list[schemas.LineIn]) -> list[LineSpec]:
    return [LineSpec(description=x.description, price_id=x.price_id, quantity=x.quantity, unit_amount=x.unit_amount,
                     tax_rate_id=x.tax_rate_id) for x in lines]


# --- invoices ---------------------------------------------------------------------------------------------------

def detail(c: Ctx, inv: Invoice) -> dict:
    contact = contacts_of(c, [inv.contact_id]).get(inv.contact_id)
    out = invoicing.invoice_json(inv, invoicing.lines_of(c.db, [inv.id])[inv.id], contact)
    pays = c.db.scalars(select(Payment).where(Payment.invoice_id == inv.id).order_by(Payment.created_at.desc()))
    out["payments"] = [{"id": p.id, "amount": p.amount, "status": p.status, "provider": p.provider,
                        "method": p.method, "amount_refunded": p.amount_refunded, "created_at": p.created_at,
                        "succeeded_at": p.succeeded_at} for p in pays]
    return out


def invoice_or_404(c: Ctx, invoice_id: uuid.UUID, *, lock: bool = False) -> Invoice:
    inv = invoicing.lock(c.db, invoice_id) if lock else c.db.get(Invoice, invoice_id)
    if inv is None:
        raise not_found("Invoice")
    return inv


@router.get("/invoices")
def list_invoices(status: str | None = None, contact_id: uuid.UUID | None = None,
                  subscription_id: uuid.UUID | None = None, q: str | None = None, checkouts: bool = False,
                  limit: Limit = 50, cursor: str | None = None, c: Ctx = Depends(read)):
    """Invoices, newest first. A payment link's checkouts that were never paid are left out unless `checkouts`."""
    stmt = select(Invoice)
    if status:
        stmt = stmt.where(Invoice.status == status)
    if contact_id:
        stmt = stmt.where(Invoice.contact_id == contact_or_422(c, contact_id))
    if subscription_id:
        stmt = stmt.where(Invoice.subscription_id == subscription_id)
    if q:
        stmt = stmt.where(Invoice.number.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    if not checkouts:
        stmt = stmt.where((Invoice.billing_reason != "payment_link") | (Invoice.number.is_not(None)))
    rows, nxt = paginate(c.db, stmt, Invoice, limit, cursor)
    invs = [r[0] for r in rows]
    contacts = contacts_of(c, [i.contact_id for i in invs])
    return {"data": [invoicing.invoice_json(i, None, contacts.get(i.contact_id)) for i in invs], "next_cursor": nxt}


def draft_from(c: Ctx, body: schemas.InvoiceIn) -> Invoice:
    contact_or_422(c, body.contact_id)
    currency = body.currency or invoicing.settings_of(c.db, c.workspace.id).default_currency
    specs = specs_of(body.lines)
    coupon = coupon_from_code(c, body.coupon_code, contact_id=body.contact_id, currency=currency,
                              price_ids={s.price_id for s in specs if s.price_id}, at=now())
    inv = invoicing.new(c, contact_id=body.contact_id, currency=currency, due_at=body.due_at, memo=body.memo,
                        footer=body.footer)
    invoicing.write_lines(c, inv, specs, coupon)
    return inv


@router.post("/invoices", status_code=201)
def create_invoice(body: schemas.InvoiceIn, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    """A draft. Send it to give it a number and a link the customer pays on."""
    inv = draft_from(c, body)
    invoicing.emit(c, "invoice.created", inv)
    return idem.commit(201, detail(c, inv))


@router.post("/invoices/preview")
def preview_invoice(body: schemas.InvoiceIn, c: Ctx = Depends(write)):
    """The lines and totals an invoice with this body would have, worked out by the server and saved nowhere."""
    savepoint = c.db.begin_nested()
    try:
        inv = draft_from(c, body)
        out = invoicing.invoice_json(inv, invoicing.lines_of(c.db, [inv.id])[inv.id], None)
    finally:
        savepoint.rollback()
    return out


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: uuid.UUID, c: Ctx = Depends(read)):
    return detail(c, invoice_or_404(c, invoice_id))


def need_draft(inv: Invoice) -> None:
    if inv.status != "draft":
        raise ApiError(409, "conflict", "Only a draft can be changed; void this invoice and make a new one")


@router.patch("/invoices/{invoice_id}")
def patch_invoice(invoice_id: uuid.UUID, body: schemas.InvoicePatch, c: Ctx = Depends(write)):
    inv = invoice_or_404(c, invoice_id, lock=True)
    need_draft(inv)
    sent = body.model_fields_set
    for key in ("memo", "footer", "due_at"):
        if key in sent:
            setattr(inv, key, getattr(body, key) if key == "due_at" else (getattr(body, key) or ""))
    if "contact_id" in sent:
        if body.contact_id is None:
            raise invalid({"contact_id": "cannot be null"})
        inv.contact_id = contact_or_422(c, body.contact_id)
    if "currency" in sent and body.currency:
        inv.currency = body.currency
    if sent & {"lines", "currency", "coupon_code", "contact_id"}:
        if body.lines is not None:
            specs = specs_of(body.lines)
        else:
            specs = [LineSpec(description=x.description, price_id=x.price_id, quantity=x.quantity,
                              unit_amount=None if x.price_id else x.unit_amount, tax_rate_id=x.tax_rate_id)
                     for x in invoicing.lines_of(c.db, [inv.id])[inv.id]]
        kept = c.db.get(catalog.Coupon, inv.coupon_id) if inv.coupon_id else None
        code = body.coupon_code if "coupon_code" in sent else (kept.code if kept else None)
        coupon = coupon_from_code(c, code, contact_id=inv.contact_id, currency=inv.currency,
                                  price_ids={s.price_id for s in specs if s.price_id}, at=now())
        invoicing.write_lines(c, inv, specs, coupon)
    inv.updated_at = now()
    c.db.flush()
    invoicing.emit(c, "invoice.updated", inv)
    c.db.commit()
    return detail(c, inv)


@router.delete("/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: uuid.UUID, c: Ctx = Depends(write)):
    """Deletes a draft (it never had a number). An issued invoice is voided instead."""
    inv = invoice_or_404(c, invoice_id, lock=True)
    need_draft(inv)
    invoicing.emit(c, "invoice.deleted", inv)
    c.db.delete(inv)
    c.db.commit()
    return Response(status_code=204)


@router.post("/invoices/{invoice_id}/send")
def send_invoice(invoice_id: uuid.UUID, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    """Issues a draft: the next number, the due date, and the link the customer pays on (`public_url`). An invoice of
    nothing to pay is paid at once. Emailing it is the email module's (the `invoice.sent` event lets a workflow do it
    now)."""
    inv = invoice_or_404(c, invoice_id, lock=True)
    need_draft(inv)
    if not invoicing.lines_of(c.db, [inv.id])[inv.id]:
        raise invalid({"lines": "an invoice needs at least one line"})
    if inv.contact_id is None:
        raise invalid({"contact_id": "is required"})
    invoicing.issue(c, inv, now())
    return idem.commit(200, detail(c, inv))


@router.post("/invoices/{invoice_id}/void")
def void_invoice(invoice_id: uuid.UUID, body: schemas.Void, c: Ctx = Depends(money_out)):
    inv = invoice_or_404(c, invoice_id, lock=True)
    if inv.status != "open":
        raise ApiError(409, "conflict", "Only an open invoice can be voided" + (
            " (delete a draft instead)" if inv.status == "draft" else ""))
    if inv.amount_paid:
        raise ApiError(409, "conflict", "Part of this invoice is paid: refund the payment before voiding it")
    invoicing.void(c, inv, now(), body.reason or "voided")
    c.db.commit()
    return detail(c, inv)


@router.post("/invoices/{invoice_id}/payments", status_code=201)
def record_payment(invoice_id: uuid.UUID, body: schemas.ManualPayment, c: Ctx = Depends(money_out),
                   idem: Idem = Depends(idempotency)):
    """Records money taken outside go-high (cash, a cheque, a bank transfer) against an open invoice; partial payments
    add up. More than is due is refused."""
    inv = invoice_or_404(c, invoice_id, lock=True)
    due = invoicing.amount_due(inv)
    if inv.status != "open" or due <= 0:
        raise ApiError(409, "conflict", "Only an open invoice with something due takes a payment")
    if body.amount > due:
        raise invalid({"amount": f"can be at most the {due} due"})
    pid = uuid.uuid4()
    p = Payment(id=pid, workspace_id=inv.workspace_id, contact_id=inv.contact_id, invoice_id=inv.id,
                subscription_id=inv.subscription_id, provider="manual", attempt_key=f"manual:{pid}",
                amount=body.amount, currency=inv.currency, method=body.method, note=body.note, created_by=c.user_id)
    c.db.add(p)
    c.db.flush()
    ledger.succeed(c, p, now())
    return idem.commit(201, detail(c, inv))


# --- subscriptions ----------------------------------------------------------------------------------------------

def sub_detail(c: Ctx, s: Subscription, with_invoices: bool = False) -> dict:
    price = c.db.get(Price, s.price_id)
    product = c.db.get(Product, price.product_id) if price else None
    contact = contacts_of(c, [s.contact_id]).get(s.contact_id)
    acct = ledger.account_of(c.db)
    row = ledger.customer_of(c.db, s.contact_id, acct.account_id) if acct else None
    card = {"brand": row.card_brand, "last4": row.card_last4} if row and row.payment_method_id and contact else None
    out = billing.sub_json(s, price, product, contact, card)
    if with_invoices:
        invs = c.db.scalars(select(Invoice).where(Invoice.subscription_id == s.id)
                            .order_by(Invoice.created_at.desc()).limit(50))
        out["invoices"] = [invoicing.invoice_json(i, None, contact) for i in invs]
    return out


def sub_or_404(c: Ctx, subscription_id: uuid.UUID) -> Subscription:
    s = c.db.get(Subscription, subscription_id)
    if s is None:
        raise not_found("Subscription")
    return s


def locked_sub(c: Ctx, subscription_id: uuid.UUID) -> Subscription:
    s, _ = billing.lock(c.db, subscription_id)
    if s is None:
        raise not_found("Subscription")
    return s


@router.get("/subscriptions")
def list_subscriptions(status: str | None = None, contact_id: uuid.UUID | None = None, limit: Limit = 50,
                       cursor: str | None = None, c: Ctx = Depends(read)):
    stmt = select(Subscription)
    if status:
        stmt = stmt.where(Subscription.status == status)
    if contact_id:
        stmt = stmt.where(Subscription.contact_id == contact_or_422(c, contact_id))
    rows, nxt = paginate(c.db, stmt, Subscription, limit, cursor)
    return {"data": [sub_detail(c, r[0]) for r in rows], "next_cursor": nxt}


@router.post("/subscriptions", status_code=201)
def create_subscription(body: schemas.SubscriptionIn, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    """Starts a subscription for a contact: trialing, or incomplete until its first invoice is paid (charged at once
    when the contact has a kept card, otherwise paid on the invoice's link)."""
    contact_or_422(c, body.contact_id)
    price = catalog.price_or_422(c.db, body.price_id, "price_id")
    at = now()
    coupon = coupon_from_code(c, body.coupon_code, contact_id=body.contact_id, currency=price.currency,
                              price_ids={price.id}, at=at)
    s = billing.create(c, contact_id=body.contact_id, price=price, quantity=body.quantity, coupon=coupon,
                       trial_days=body.trial_days, collection=body.collection, now=at)
    return idem.commit(201, sub_detail(c, s, True))


@router.get("/subscriptions/{subscription_id}")
def get_subscription(subscription_id: uuid.UUID, c: Ctx = Depends(read)):
    return sub_detail(c, sub_or_404(c, subscription_id), True)


@router.patch("/subscriptions/{subscription_id}")
def change_subscription(subscription_id: uuid.UUID, body: schemas.SubscriptionPatch, c: Ctx = Depends(write)):
    """Another price or quantity, prorated by default (see billing.change)."""
    s = locked_sub(c, subscription_id)
    price = catalog.price_or_422(c.db, body.price_id, "price_id") if body.price_id else c.db.get(Price, s.price_id)
    billing.change(c, s, price, body.quantity or s.quantity, prorate=body.prorate, now=now())
    c.db.commit()
    return sub_detail(c, s, True)


@router.post("/subscriptions/{subscription_id}/cancel")
def cancel_subscription(subscription_id: uuid.UUID, body: schemas.CancelIn, c: Ctx = Depends(write)):
    """At the end of the period by default (`at_period_end: false` ends it now and voids what it still owes)."""
    s = locked_sub(c, subscription_id)
    billing.cancel(c, s, at_period_end=body.at_period_end, reason=body.reason, now=now())
    c.db.commit()
    return sub_detail(c, s, True)


@router.post("/subscriptions/{subscription_id}/reactivate")
def reactivate_subscription(subscription_id: uuid.UUID, c: Ctx = Depends(write)):
    s = locked_sub(c, subscription_id)
    billing.reactivate(c, s, now())
    c.db.commit()
    return sub_detail(c, s, True)


# --- transactions and refunds -----------------------------------------------------------------------------------

def tx_detail(c: Ctx, p: Payment) -> dict:
    refunds = list(c.db.scalars(select(Refund).where(Refund.payment_id == p.id).order_by(Refund.created_at)))
    number = c.db.scalar(select(Invoice.number).where(Invoice.id == p.invoice_id)) if p.invoice_id else None
    return ledger.payment_json(p, contacts_of(c, [p.contact_id]).get(p.contact_id), refunds, number)


@router.get("/payments/transactions")
def list_transactions(status: str | None = None, contact_id: uuid.UUID | None = None,
                      invoice_id: uuid.UUID | None = None, subscription_id: uuid.UUID | None = None,
                      provider: str | None = None, from_: Annotated[datetime | None, Query(alias="from")] = None,
                      to: datetime | None = None, limit: Limit = 50, cursor: str | None = None,
                      c: Ctx = Depends(read)):
    """Every payment, newest first: online ones of every status and those recorded by hand."""
    stmt = select(Payment)
    for column, value in ((Payment.status, status), (Payment.invoice_id, invoice_id),
                          (Payment.subscription_id, subscription_id), (Payment.provider, provider)):
        if value:
            stmt = stmt.where(column == value)
    if contact_id:
        stmt = stmt.where(Payment.contact_id == contact_or_422(c, contact_id))
    if from_:
        stmt = stmt.where(Payment.created_at >= from_)
    if to:
        stmt = stmt.where(Payment.created_at <= to)
    rows, nxt = paginate(c.db, stmt, Payment, limit, cursor)
    pays = [r[0] for r in rows]
    contacts = contacts_of(c, [p.contact_id for p in pays])
    numbers = dict(c.db.execute(select(Invoice.id, Invoice.number).where(
        Invoice.id.in_([p.invoice_id for p in pays if p.invoice_id]))).all()) if pays else {}
    return {"data": [ledger.payment_json(p, contacts.get(p.contact_id), None, numbers.get(p.invoice_id))
                     for p in pays], "next_cursor": nxt}


@router.get("/payments/transactions/{payment_id}")
def get_transaction(payment_id: uuid.UUID, c: Ctx = Depends(read)):
    p = c.db.get(Payment, payment_id)
    if p is None:
        raise not_found("Payment")
    return tx_detail(c, p)


@router.post("/payments/transactions/{payment_id}/refunds", status_code=201)
def refund(payment_id: uuid.UUID, body: schemas.RefundIn, c: Ctx = Depends(money_out),
           idem: Idem = Depends(idempotency)):
    """Refunds all (no `amount`) or part of a payment. A provider's refund is `pending` until the provider confirms;
    one of a payment recorded by hand is done at once. Never more than is left to refund (422)."""
    p = ledger.lock_payment(c.db, payment_id)
    if p is None:
        raise not_found("Payment")
    amount = body.amount if body.amount is not None else p.amount - ledger.reserved(c.db, p.id)
    ledger.request_refund(c, p, amount, body.reason, body.note, lock=False)
    return idem.commit(201, tx_detail(c, p))


@router.get("/payments/summary")
def summary(c: Ctx = Depends(read)):
    """Money in the last 30 days (succeeded payments less refunds), what is owed (open invoices) and recurring
    revenue (active subscriptions' amount per month), each per currency."""
    since = now() - timedelta(days=30)
    gross = dict(c.db.execute(select(Payment.currency, func.sum(Payment.amount)).where(
        Payment.status == "succeeded", Payment.succeeded_at >= since).group_by(Payment.currency)).all())
    refunded = dict(c.db.execute(select(Payment.currency, func.sum(Refund.amount)).join(
        Payment, Payment.id == Refund.payment_id).where(Refund.status == "succeeded", Refund.updated_at >= since)
        .group_by(Payment.currency)).all())
    owed = dict(c.db.execute(select(Invoice.currency, func.sum(Invoice.total - Invoice.amount_paid)).where(
        Invoice.status == "open", Invoice.number.is_not(None)).group_by(Invoice.currency)).all())
    mrr: dict[str, int] = {}
    per_month = {"day": (365, 12), "week": (52, 12), "month": (1, 1), "year": (1, 12)}
    for s, price in c.db.execute(select(Subscription, Price).join(Price, Price.id == Subscription.price_id).where(
            Subscription.status.in_(("active", "past_due")))).all():
        num, den = per_month[price.interval]
        amount = catalog.price_amount(price, s.quantity) * num // (den * price.interval_count)
        mrr[s.currency] = mrr.get(s.currency, 0) + amount
    active = c.db.scalar(select(func.count()).select_from(Subscription).where(Subscription.status.in_(
        ("trialing", "active", "past_due")))) or 0
    cards = c.db.scalar(select(func.count()).select_from(PaymentCustomer).where(
        PaymentCustomer.payment_method_id.is_not(None))) or 0
    currencies = sorted(set(gross) | set(refunded) | set(owed) | set(mrr))
    return {"since": since, "currencies": [{"currency": cur, "net_volume": int(gross.get(cur, 0)) - int(
        refunded.get(cur, 0)), "gross_volume": int(gross.get(cur, 0)), "refunded": int(refunded.get(cur, 0)),
        "outstanding": int(owed.get(cur, 0)), "mrr": mrr.get(cur, 0)} for cur in currencies],
        "live_subscriptions": active, "saved_cards": cards}
