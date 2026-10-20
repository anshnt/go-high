"""Subscriptions (module 21): the state machine, renewals, dunning and plan changes. We run billing ourselves, so it
works the same on any provider: the provider only takes a checkout or charges a kept card.

States and how they move:

    (new, no trial) incomplete --first invoice paid--> active
    incomplete --period ends unpaid--> incomplete_expired (its invoice is voided)
    (new, trial)    trialing --trial ends--> active, with the first period's invoice
    active --a renewal charge fails or the invoice goes unpaid past its due date--> past_due
    past_due --the open invoice is paid--> active
    past_due --the last retry fails--> canceled (settings.after_retries = cancel) or unpaid (= unpaid)
    unpaid --the open invoice is paid (reactivate retries the card)--> active
    any live state --cancel now--> canceled;  cancel at period end --period ends--> canceled
    cancel_at_period_end --reactivate--> stays as it is, renews again

A period starts at `period_boundary(anchor, interval, count, n)`, always counted from the anchor (the start, or the end
of the trial), so the 31st stays the 31st. Every job about a subscription carries the subscription's `cycle` (renewals)
or the invoice's attempt number (collection) it was planned for, and does nothing when that has moved on, so a job that
runs late or twice changes nothing. Locks are taken invoice first, then subscription, everywhere, so a webhook paying
an invoice and a renewal or cancel cannot deadlock.

Dunning: `settings.retry_days` (default 1, 3 and 5) are the days after the invoice was issued on which a failed charge
is tried again; after the last one, `after_retries` decides. An invoice collected by sending it (no kept card, or
`collection = send_invoice`) is due after `invoice_due_days`; unpaid by then it makes the subscription past due and
the same retry days count from the due date, with no charge attempted."""
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import events, jobs
from ..api import ApiError
from ..records.timeline import link
from ..security import Ctx
from . import catalog, invoicing, ledger, money, providers
from .invoicing import LineSpec
from .models import Coupon, Invoice, Payment, Price, Product, Subscription
from .providers.base import ChargeRequest, ProviderError

log = logging.getLogger("payments")
LIVE = ("incomplete", "trialing", "active", "past_due", "unpaid")
ENDED = ("canceled", "incomplete_expired")


def now_utc() -> datetime:
    from datetime import UTC
    return datetime.now(UTC)


# --- json and events --------------------------------------------------------------------------------------------

def sub_json(s: Subscription, price: Price | None, product: Product | None, contact: dict | None,
             card: dict | None = None) -> dict:
    return {"id": s.id, "contact_id": s.contact_id if contact else None, "contact": contact, "price_id": s.price_id,
            "price": catalog.price_json(price) if price else None, "product_name": product.name if product else None,
            "quantity": s.quantity, "currency": s.currency, "status": s.status, "collection": s.collection,
            "cancel_at_period_end": s.cancel_at_period_end, "canceled_at": s.canceled_at,
            "cancel_reason": s.cancel_reason, "trial_end": s.trial_end, "current_period_start": s.current_period_start,
            "current_period_end": s.current_period_end, "coupon_id": s.coupon_id, "coupon_ends_at": s.coupon_ends_at,
            "credit_balance": s.credit_balance, "latest_invoice_id": s.latest_invoice_id,
            "amount": catalog.price_amount(price, s.quantity) if price else None, "card": card,
            "created_at": s.created_at, "updated_at": s.updated_at}


def event_data(db: Session, s: Subscription) -> dict:
    price = db.get(Price, s.price_id)
    return {"id": s.id, "contact_id": s.contact_id, "price_id": s.price_id,
            "product_id": price.product_id if price else None, "status": s.status, "quantity": s.quantity,
            "currency": s.currency, "current_period_start": s.current_period_start,
            "current_period_end": s.current_period_end, "trial_end": s.trial_end,
            "cancel_at_period_end": s.cancel_at_period_end}


def emit(c: Ctx, type_: str, s: Subscription, extra: dict | None = None) -> None:
    event = events.emit(c.db, type_, "subscription", s.id, {**event_data(c.db, s), **(extra or {})},
                        actor=c.author(), workspace_id=s.workspace_id)
    if s.contact_id:
        link(c.db, event, [s.contact_id])


def changed(c: Ctx, s: Subscription, before: dict, reason: str) -> None:
    after = event_data(c.db, s)
    diff = events.changes(before, after)
    if diff:
        s.updated_at = func.now()
        c.db.flush()
        emit(c, "subscription.updated", s, {"changes": diff, "reason": reason})


# --- locks --------------------------------------------------------------------------------------------------------

def open_invoices(db: Session, s: Subscription) -> list[Invoice]:
    return list(db.scalars(select(Invoice).where(Invoice.subscription_id == s.id, Invoice.status == "open")
                           .order_by(Invoice.id)))


def lock(db: Session, subscription_id: uuid.UUID) -> tuple[Subscription | None, list[Invoice]]:
    """The subscription and its open invoices, locked in the one order every writer uses (invoices, then it)."""
    invoices = list(db.scalars(select(Invoice).where(Invoice.subscription_id == subscription_id,
                                                     Invoice.status == "open").order_by(Invoice.id)
                               .with_for_update().execution_options(populate_existing=True)))
    s = db.scalar(select(Subscription).where(Subscription.id == subscription_id).with_for_update()
                  .execution_options(populate_existing=True))
    return s, invoices


# --- periods and invoices -----------------------------------------------------------------------------------------

def card_for(c: Ctx, s: Subscription):
    """The kept card to charge for this subscription, with the account, or (None, account)."""
    acct = ledger.account_of(c.db)
    if s.collection != "charge_automatically" or ledger.not_ready(acct):
        return None, acct
    row = ledger.customer_of(c.db, s.contact_id, acct.account_id)
    return (row if row and row.payment_method_id else None), acct


def period_coupon(c: Ctx, s: Subscription, start: datetime) -> Coupon | None:
    if s.coupon_id is None:
        return None
    coupon = c.db.get(Coupon, s.coupon_id)
    if coupon is None:
        return None
    if coupon.duration == "forever":
        return coupon
    if coupon.duration == "once":
        used = c.db.scalar(select(func.count()).select_from(Invoice).where(
            Invoice.subscription_id == s.id, Invoice.coupon_id == coupon.id))
        return None if used else coupon
    if s.coupon_ends_at is None:
        s.coupon_ends_at = money.add_months(start, coupon.duration_months or 1)
    return coupon if start < s.coupon_ends_at else None


def start_period(c: Ctx, s: Subscription, price: Price, now: datetime, reason: str) -> Invoice:
    """Bills the next period (number `s.periods` from the anchor): its invoice, issued; the renewal job at its end;
    and its collection, a charge now when there is a kept card, else the invoice is sent and collected by its date."""
    n = s.periods
    start = money.period_boundary(s.anchor, price.interval, price.interval_count, n)
    end = money.period_boundary(s.anchor, price.interval, price.interval_count, n + 1)
    s.periods, s.current_period_start, s.current_period_end = n + 1, start, end
    s.cycle += 1
    card, _ = card_for(c, s)
    inv = invoicing.new(c, contact_id=s.contact_id, currency=s.currency, reason=reason, subscription=s,
                        period_start=start, period_end=end)
    s.credit_balance = invoicing.write_lines(
        c, inv, [LineSpec(price_id=price.id, quantity=s.quantity, period_start=start, period_end=end)],
        period_coupon(c, s, start), credit=s.credit_balance)
    invoicing.emit(c, "invoice.created", inv)
    invoicing.issue(c, inv, now, due_days=0 if card else None)
    s.latest_invoice_id, s.updated_at = inv.id, now
    c.db.flush()
    jobs.enqueue(c.db, "payments.renew", {"id": str(s.id), "workspace_id": str(s.workspace_id), "cycle": s.cycle},
                 run_at=end)
    if inv.status == "open":
        plan_collection(c, inv, 1, now if card else inv.due_at)
    return inv


def plan_collection(c: Ctx, inv: Invoice, attempt: int, at: datetime) -> None:
    inv.next_attempt_at = at
    c.db.flush()
    jobs.enqueue(c.db, "payments.collect", {"id": str(inv.id), "workspace_id": str(inv.workspace_id),
                                            "attempt": attempt}, run_at=at, max_attempts=8)


# --- creating -----------------------------------------------------------------------------------------------------

def create(c: Ctx, *, contact_id: uuid.UUID, price: Price, quantity: int, coupon: Coupon | None, trial_days: int | None,
           collection: str, now: datetime) -> Subscription:
    """A new subscription: trialing (no charge until the trial ends) or incomplete with its first invoice, which is
    charged at once when the contact has a kept card and otherwise waits to be paid by its link. The caller commits."""
    if price.type != "recurring":
        raise catalog.invalid({"price_id": "is not a recurring price"})
    trial = price.trial_days if trial_days is None else trial_days
    s = Subscription(workspace_id=c.workspace.id, contact_id=contact_id, price_id=price.id, quantity=quantity,
                     currency=price.currency, status="trialing" if trial else "incomplete", collection=collection,
                     coupon_id=coupon.id if coupon else None, created_by=c.user_id)
    c.db.add(s)
    c.db.flush()
    if coupon is not None and not catalog.redeem(c.db, coupon, contact_id=contact_id, subscription_id=s.id):
        raise ApiError(409, "coupon_used_up", "The coupon has been used up meanwhile.", {"coupon_code": "is used up"})
    if trial:
        s.trial_end = now + timedelta(days=trial)
        s.anchor, s.current_period_start, s.current_period_end = s.trial_end, now, s.trial_end
        s.cycle = 1
        c.db.flush()
        jobs.enqueue(c.db, "payments.renew", {"id": str(s.id), "workspace_id": str(s.workspace_id), "cycle": 1},
                     run_at=s.trial_end)
        emit(c, "subscription.created", s)
    else:
        s.anchor = now
        emit(c, "subscription.created", s)
        start_period(c, s, price, now, "subscription_create")
    return s


# --- what money does to a subscription ----------------------------------------------------------------------------

def invoice_paid(c: Ctx, inv: Invoice, now: datetime) -> None:
    """An invoice of a subscription was paid (the invoice is locked): the subscription is active again unless another
    of its invoices is still owed."""
    if inv.subscription_id is None:
        return
    s = c.db.scalar(select(Subscription).where(Subscription.id == inv.subscription_id).with_for_update()
                    .execution_options(populate_existing=True))
    if s is None or s.status not in ("incomplete", "past_due", "unpaid"):
        return
    owed = c.db.scalar(select(func.count()).select_from(Invoice).where(
        Invoice.subscription_id == s.id, Invoice.status == "open", Invoice.id != inv.id))
    if owed:
        return
    before = event_data(c.db, s)
    s.status = "active"
    changed(c, s, before, "invoice_paid")


def payment_failed(c: Ctx, p: Payment, now: datetime) -> None:
    """A payment failed: an off-session charge of a subscription invoice moves dunning on; any failure is an event."""
    extra = {"failure_code": p.failure_code, "failure_message": p.failure_message, "attempt": None,
             "next_attempt_at": None, "final": False}
    if p.attempt_key.startswith("charge:") and p.invoice_id:
        inv = invoicing.lock(c.db, p.invoice_id)
        if inv is not None and inv.status == "open" and inv.subscription_id:
            extra["attempt"] = inv.attempt_count
            nxt, final = attempt_failed(c, inv, now)
            extra.update(next_attempt_at=nxt, final=final)
    ledger.emit(c, "payment.failed", "payment", p.id, ledger.payment_event(p, extra), p.contact_id, p.workspace_id)


def attempt_failed(c: Ctx, inv: Invoice, now: datetime) -> tuple[datetime | None, bool]:
    """Collection attempt `inv.attempt_count` of a subscription invoice did not get the money: past due, and the next
    attempt on the next retry day, or the final step once the retries are used up. Returns (next attempt, final)."""
    s = c.db.scalar(select(Subscription).where(Subscription.id == inv.subscription_id).with_for_update()
                    .execution_options(populate_existing=True))
    if s is None or s.status in ENDED:
        return None, False
    settings = invoicing.settings_of(c.db, inv.workspace_id)
    before = event_data(c.db, s)
    if s.status in ("active", "trialing", "incomplete"):
        s.status = "past_due" if s.status != "incomplete" else s.status
    k, days = inv.attempt_count, list(settings.retry_days or [])
    base = inv.due_at if inv.due_at and inv.due_at > (inv.issued_at or now) else (inv.issued_at or now)
    if k <= len(days):
        nxt = max(base + timedelta(days=days[k - 1]), now + timedelta(minutes=1))
        plan_collection(c, inv, k + 1, nxt)
        changed(c, s, before, "payment_failed")
        return nxt, False
    inv.next_attempt_at = None
    if settings.after_retries == "cancel":
        inv.status, inv.updated_at = "uncollectible", now
        c.db.flush()
        invoicing.emit(c, "invoice.uncollectible", inv)
        end(c, s, now, "payment_failed")
    else:
        s.status = "unpaid"
        changed(c, s, before, "retries_exhausted")
    return None, True


@jobs.handler("payments.collect", backoff=lambda n: min(timedelta(minutes=5 * 2 ** (n - 1)), timedelta(hours=6)))
def collect(db: Session, payload: dict) -> None:
    """Collection attempt `attempt` of an open subscription invoice: an off-session charge of the kept card, or, for an
    invoice sent to be paid by link, the check that it is paid by now. A provider error that may pass (a timeout, 5xx)
    retries this job with the same idempotency key; anything else counts as a failed attempt."""
    from .scope import workspace_job
    with workspace_job(db, payload["workspace_id"]) as c:
        if c is None:
            return
        inv = invoicing.lock(db, uuid.UUID(payload["id"]))
        attempt = int(payload["attempt"])
        if inv is None or inv.status != "open" or inv.subscription_id is None or inv.attempt_count != attempt - 1:
            return  # paid, voided, or this attempt already ran
        s = db.scalar(select(Subscription).where(Subscription.id == inv.subscription_id).with_for_update())
        if s is None or s.status in ENDED:
            return
        now = now_utc()
        inv.attempt_count = attempt
        card, acct = card_for(c, s)
        if card is None:
            attempt_failed(c, inv, now)
            return
        p = ledger.charge_payment(c, inv, attempt, acct)
        if p.status in ("succeeded", "failed"):
            return  # a crashed run already got the answer
        try:
            result = providers.get(acct.provider).charge(acct.account_id, ChargeRequest(
                payment_id=str(p.id), amount=p.amount, currency=p.currency, customer_id=card.customer_id,
                payment_method_id=card.payment_method_id, description=f"Invoice {inv.number}",
                idempotency_key=p.attempt_key))
        except ProviderError as e:
            if e.retryable:
                raise
            result = None
            err = (e.code, str(e))
        if result is not None and result.provider_payment_id and not p.provider_payment_id:
            p.provider_payment_id = result.provider_payment_id
        if result is not None and result.status == "succeeded":
            ledger.succeed(c, p, now)
        elif result is not None and result.status == "pending":
            p.status = "processing"
            db.flush()
        else:
            code, message = (result.failure_code, result.failure_message) if result else err
            if ledger.fail(c, p, now, code, message):
                payment_failed(c, p, now)


@jobs.handler("payments.renew")
def renew(db: Session, payload: dict) -> None:
    """The end of a period (or of the trial): the next period is billed, or the subscription ends (cancel at period
    end, an incomplete one never paid). An unpaid subscription bills nothing and only moves its period on."""
    from .scope import workspace_job
    with workspace_job(db, payload["workspace_id"]) as c:
        if c is None:
            return
        s, _ = lock(db, uuid.UUID(payload["id"]))
        if s is None or s.cycle != int(payload["cycle"]) or s.status in ENDED:
            return
        now = now_utc()
        price = db.get(Price, s.price_id)
        if s.status == "incomplete":
            end(c, s, now, "incomplete_expired", status="incomplete_expired")
        elif s.cancel_at_period_end:
            end(c, s, now, "cancel_at_period_end")
        elif s.status == "unpaid":
            n = s.periods
            s.periods, s.cycle = n + 1, s.cycle + 1
            s.current_period_start = money.period_boundary(s.anchor, price.interval, price.interval_count, n)
            s.current_period_end = money.period_boundary(s.anchor, price.interval, price.interval_count, n + 1)
            db.flush()
            jobs.enqueue(db, "payments.renew", {"id": str(s.id), "workspace_id": str(s.workspace_id),
                                                "cycle": s.cycle}, run_at=s.current_period_end)
        else:
            before = event_data(db, s)
            if s.status == "trialing":
                s.status = "active"
            start_period(c, s, price, now, "subscription_cycle")
            changed(c, s, before, "renewed")


# --- what staff do ------------------------------------------------------------------------------------------------

def end(c: Ctx, s: Subscription, now: datetime, reason: str, status: str = "canceled") -> None:
    """Ends the subscription now: no more invoices, its open ones voided (a late payment on one is refunded)."""
    for inv in open_invoices(c.db, s):
        invoicing.void(c, invoicing.lock(c.db, inv.id), now, reason)
    s.status, s.cancel_at_period_end, s.canceled_at, s.cancel_reason = status, False, now, reason[:500]
    s.cycle += 1
    s.updated_at = now
    c.db.flush()
    emit(c, "subscription.canceled", s, {"reason": reason})


def cancel(c: Ctx, s: Subscription, *, at_period_end: bool, reason: str | None, now: datetime) -> None:
    if s.status in ENDED:
        raise ApiError(409, "conflict", "This subscription has already ended")
    if at_period_end:
        if s.status not in ("trialing", "active", "past_due"):
            raise ApiError(409, "conflict", f"A subscription that is {s.status.replace('_', ' ')} is cancelled now, "
                                            "not at the end of its period")
        if not s.cancel_at_period_end:
            before = event_data(c.db, s)
            s.cancel_at_period_end, s.cancel_reason = True, (reason or "")[:500] or None
            changed(c, s, before, "cancel_scheduled")
        return
    end(c, s, now, reason or "canceled")


def reactivate(c: Ctx, s: Subscription, now: datetime) -> None:
    """Undoes a cancel at the end of the period, or tries the card again on the invoice of an unpaid subscription."""
    if s.cancel_at_period_end and s.status in ("trialing", "active", "past_due"):
        before = event_data(c.db, s)
        s.cancel_at_period_end, s.cancel_reason = False, None
        changed(c, s, before, "reactivated")
        return
    if s.status in ("unpaid", "past_due"):
        owed = open_invoices(c.db, s)
        card, _ = card_for(c, s)
        if not owed:
            raise ApiError(409, "conflict", "Nothing is owed on this subscription")
        if card is None:
            raise ApiError(409, "no_payment_method",
                           "There is no card to charge: send the customer the invoice link to pay it.")
        inv = invoicing.lock(c.db, owed[0].id)
        plan_collection(c, inv, inv.attempt_count + 1, now)
        return
    raise ApiError(409, "conflict", "There is nothing to reactivate: the subscription is " + s.status.replace("_", " "))


def change(c: Ctx, s: Subscription, price: Price, quantity: int, *, prorate: bool, now: datetime) -> Invoice | None:
    """Moves the subscription to another price or quantity. With `prorate`, an invoice now charges the new price for
    the rest of the period and credits the unused time of the old one (each line taxed like its price); if the credit
    is larger, the difference becomes credit for the next invoice. Without it (and during a trial) the change applies
    from the next period. The caller commits."""
    if s.status not in ("trialing", "active", "past_due"):
        raise ApiError(409, "conflict", "Only a trialing, active or past due subscription can be changed")
    old = c.db.get(Price, s.price_id)
    if price.type != "recurring" or price.currency != s.currency:
        raise catalog.invalid({"price_id": f"must be a recurring price in {s.currency.upper()}"})
    if (price.interval, price.interval_count) != (old.interval, old.interval_count):
        raise catalog.invalid({"price_id": "must bill on the same interval as the current price"})
    if price.id == old.id and quantity == s.quantity:
        return None
    before = event_data(c.db, s)
    old_amount, new_amount = catalog.price_amount(old, s.quantity), catalog.price_amount(price, quantity)
    inv = None
    if prorate and s.status != "trialing" and s.current_period_end and now < s.current_period_end:
        start, end_ = s.current_period_start, s.current_period_end
        credit = money.prorate(old_amount, start, end_, now)
        charge = money.prorate(new_amount, start, end_, now)
        specs = []
        if credit:
            specs.append(LineSpec(description=f"Unused time on {invoicing.describe(c.db, old)} x {s.quantity}",
                                  price_id=old.id, quantity=s.quantity, amount=-credit, proration=True,
                                  period_start=now, period_end=end_, discountable=False))
        if charge:
            specs.append(LineSpec(description=f"Remaining time on {invoicing.describe(c.db, price)} x {quantity}",
                                  price_id=price.id, quantity=quantity, amount=charge, proration=True,
                                  period_start=now, period_end=end_, discountable=False))
        if specs:
            inv = invoicing.new(c, contact_id=s.contact_id, currency=s.currency, reason="subscription_update",
                                subscription=s, period_start=now, period_end=end_)
            s.credit_balance = invoicing.write_lines(c, inv, specs, None, credit=s.credit_balance)
            invoicing.emit(c, "invoice.created", inv)
            card, _ = card_for(c, s)
            invoicing.issue(c, inv, now, due_days=0 if card else None)
            if inv.status == "open":
                plan_collection(c, inv, 1, now if card else inv.due_at)
    s.price_id, s.quantity, s.updated_at = price.id, quantity, now
    c.db.flush()
    changed(c, s, before, "plan_changed")
    return inv
