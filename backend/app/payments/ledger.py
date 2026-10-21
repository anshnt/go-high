"""Money that moved (module 21): the provider account, checkouts, payments, refunds and what provider webhooks report.

Rules that keep the ledger right whatever order things arrive in, and however often:
- A webhook is applied once: its event id goes into `payment_events` in the same transaction as what it changed, and
  a replay finds the row and does nothing. A payment only moves forward (`pending` < `processing` < `failed` <
  `succeeded`; a late failure never undoes a success), so events that arrive out of order cannot regress it.
- A success is fulfilled once: one conditional UPDATE sets `fulfilled_at`, and only the transaction that set it applies
  the money to the invoice. Money the invoice did not need (two checkouts both paid, or a payment after the invoice was
  voided) is refunded automatically.
- Refunds never exceed what was captured: a new refund is checked against the payment's amount less every pending and
  succeeded refund, under a row lock on the payment, and a CHECK keeps `amount_refunded <= amount` in the database.
- Every call that moves money has an idempotency key derived from our row (`checkout:<payment>`, `charge:<invoice>:<n>`,
  `refund:<refund>`), and the row of an off-session charge has an id derived from its key, so a job retried after a
  crash finds the same row and the provider answers with the same charge."""
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .. import config, events, jobs
from ..api import ApiError
from ..records.timeline import link
from ..security import Ctx
from . import invoicing, providers
from .models import Invoice, Payment, PaymentAccount, PaymentCustomer, PaymentEvent, Refund, Subscription
from .providers.base import CheckoutRequest, ProviderError, RefundRequest, Update

log = logging.getLogger("payments")
RANK = {"pending": 0, "processing": 1, "canceled": 2, "failed": 2, "succeeded": 3}
NAMESPACE = uuid.UUID("5b7c2f0e-1d7a-4c51-9a62-0b3e8d4f6a10")
CHECKOUT_REUSE = timedelta(minutes=50)  # an open checkout of the same amount is handed out again for this long


class Retry(Exception):
    """A webhook that names a payment we have not committed yet (its job is still running): the provider is told to
    send it again later, and nothing is recorded."""


# --- the account ------------------------------------------------------------------------------------------------

def account_of(db: Session) -> PaymentAccount | None:
    """The workspace's provider account (row level security picks the workspace)."""
    return db.scalar(select(PaymentAccount))


def status_of(state) -> str:
    if state.charges_enabled:
        return "active"
    return "restricted" if state.details_submitted else "pending"


def not_ready(acct: PaymentAccount | None) -> str | None:
    """Why online payments cannot be taken now, in words; None when they can."""
    if acct is None or acct.status == "disconnected":
        return "No payment provider is connected. Connect Stripe under Payments, Settings."
    reason = providers.get(acct.provider).available()
    if reason:
        return reason
    if not acct.charges_enabled:
        return "The connected account cannot take payments yet: finish its setup with the provider."
    return None


def account_json(acct: PaymentAccount | None) -> dict | None:
    if acct is None:
        return None
    return {"provider": acct.provider, "account_id": acct.account_id, "status": acct.status,
            "charges_enabled": acct.charges_enabled, "payouts_enabled": acct.payouts_enabled,
            "details_submitted": acct.details_submitted, "livemode": acct.livemode,
            "display_name": acct.display_name, "created_at": acct.created_at, "updated_at": acct.updated_at}


def capabilities(acct: PaymentAccount | None) -> dict:
    """What can be used now and, when not, the plain reason (the capability matrix, resolved at runtime)."""
    online = not_ready(acct)

    def cap(reason: str | None) -> dict:
        return {"available": reason is None, "reason": reason}

    return {"invoices": cap(None), "manual_payments": cap(None), "online_payments": cap(online),
            "payment_links": cap(online), "subscriptions": cap(online), "saved_cards": cap(online),
            "refunds": cap(online)}


def copy_state(acct: PaymentAccount, state) -> None:
    acct.charges_enabled, acct.payouts_enabled = state.charges_enabled, state.payouts_enabled
    acct.details_submitted, acct.livemode = state.details_submitted, state.livemode
    acct.display_name = state.display_name or acct.display_name
    if acct.status != "disconnected":
        acct.status = status_of(state)


def apply_account(c: Ctx, acct: PaymentAccount, state) -> None:
    before = account_json(acct)
    copy_state(acct, state)
    c.db.flush()
    after = account_json(acct)
    changes = events.changes({k: v for k, v in before.items() if k not in ("updated_at",)},
                             {k: v for k, v in after.items() if k not in ("updated_at",)})
    if changes:
        acct.updated_at = func.now()
        events.emit(c.db, "payment_account.updated", "payment_account", acct.id,
                    {"provider": acct.provider, "status": acct.status, "charges_enabled": acct.charges_enabled,
                     "changes": changes}, actor=c.author(), workspace_id=acct.workspace_id)


# --- payments ---------------------------------------------------------------------------------------------------

def payment_json(p: Payment, contact: dict | None, refunds: list[Refund] | None = None,
                 invoice_number: str | None = None) -> dict:
    out = {"id": p.id, "contact_id": p.contact_id if contact else None, "contact": contact,
           "invoice_id": p.invoice_id, "invoice_number": invoice_number, "subscription_id": p.subscription_id,
           "provider": p.provider, "provider_payment_id": p.provider_payment_id, "amount": p.amount,
           "currency": p.currency, "status": p.status, "amount_refunded": p.amount_refunded,
           "refundable": refundable(p, refunds) if refunds is not None else None, "method": p.method,
           "note": p.note, "failure_code": p.failure_code, "failure_message": p.failure_message,
           "succeeded_at": p.succeeded_at, "created_at": p.created_at, "updated_at": p.updated_at}
    if refunds is not None:
        out["refunds"] = [refund_json(r) for r in refunds]
    return out


def refund_json(r: Refund) -> dict:
    return {"id": r.id, "payment_id": r.payment_id, "amount": r.amount, "reason": r.reason, "note": r.note,
            "status": r.status, "provider_refund_id": r.provider_refund_id, "failure_message": r.failure_message,
            "created_at": r.created_at, "updated_at": r.updated_at}


def payment_event(p: Payment, extra: dict | None = None) -> dict:
    return {"id": p.id, "contact_id": p.contact_id, "invoice_id": p.invoice_id, "subscription_id": p.subscription_id,
            "amount": p.amount, "currency": p.currency, "provider": p.provider, "method": p.method,
            **(extra or {})}


def emit(c: Ctx, type_: str, subject_type: str, subject_id: uuid.UUID, data: dict, contact_id: uuid.UUID | None,
         workspace_id: uuid.UUID) -> None:
    event = events.emit(c.db, type_, subject_type, subject_id, data, actor=c.author(), workspace_id=workspace_id)
    if contact_id:
        link(c.db, event, [contact_id])


def lock_payment(db: Session, payment_id: uuid.UUID) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update()
                     .execution_options(populate_existing=True))


def customer_of(db: Session, contact_id: uuid.UUID | None, account_id: str) -> PaymentCustomer | None:
    if contact_id is None:
        return None
    return db.scalar(select(PaymentCustomer).where(PaymentCustomer.contact_id == contact_id,
                                                   PaymentCustomer.account_id == account_id))


def keep_customer(db: Session, p: Payment, u: Update) -> None:
    """Remembers the provider customer of the payment's contact, and the card when it was saved for later."""
    if not u.customer_id or p.contact_id is None or p.account_id is None:
        return
    row = customer_of(db, p.contact_id, p.account_id)
    if row is None:
        row = PaymentCustomer(workspace_id=p.workspace_id, contact_id=p.contact_id, provider=p.provider,
                              account_id=p.account_id, customer_id=u.customer_id)
        db.add(row)
    row.customer_id = u.customer_id
    if u.payment_method_id:
        row.payment_method_id, row.card_brand, row.card_last4 = u.payment_method_id, u.card_brand, u.card_last4
    row.updated_at = func.now()
    db.flush()


def prepare_checkout(c: Ctx, inv: Invoice, acct: PaymentAccount) -> Payment:
    """The payment row a hosted checkout will pay (the caller commits it before asking the provider for the page, so a
    webhook can never name a payment we do not have). An open checkout of the same amount, made recently, is reused,
    so a customer pressing Pay twice gets the same page instead of paying twice."""
    due = invoicing.amount_due(inv)
    if due <= 0:
        raise ApiError(409, "nothing_due", "There is nothing left to pay on this invoice.")
    reuse = c.db.scalar(select(Payment).where(
        Payment.invoice_id == inv.id, Payment.status == "pending", Payment.amount == due,
        Payment.provider == acct.provider, Payment.account_id == acct.account_id, Payment.checkout_url.is_not(None),
        Payment.created_at > func.now() - CHECKOUT_REUSE).order_by(Payment.created_at.desc()).limit(1))
    if reuse:
        return reuse
    pid = uuid.uuid4()
    p = Payment(id=pid, workspace_id=inv.workspace_id, contact_id=inv.contact_id, invoice_id=inv.id,
                subscription_id=inv.subscription_id, provider=acct.provider, account_id=acct.account_id,
                attempt_key=f"checkout:{pid}", amount=due, currency=inv.currency, method="card",
                created_by=c.user_id)
    c.db.add(p)
    c.db.flush()
    return p


def open_checkout(c: Ctx, p: Payment, inv: Invoice, *, email: str | None, success_url: str, cancel_url: str) -> str:
    """The provider's page for this payment (made once per payment row)."""
    if p.checkout_url:
        return p.checkout_url
    provider = providers.get(p.provider)
    sub = c.db.get(Subscription, inv.subscription_id) if inv.subscription_id else None
    known = customer_of(c.db, p.contact_id, p.account_id or "")
    label = f"Invoice {inv.number}" if inv.number else "Payment"
    session = provider.checkout(p.account_id, CheckoutRequest(
        payment_id=str(p.id), amount=p.amount, currency=p.currency, description=label, customer_email=email,
        customer_id=known.customer_id if known else None,
        save_method=bool(sub and sub.collection == "charge_automatically"), success_url=success_url,
        cancel_url=cancel_url, idempotency_key=p.attempt_key))
    p.checkout_session_id, p.checkout_url, p.updated_at = session.id, session.url, func.now()
    c.db.flush()
    return session.url


def charge_payment(c: Ctx, inv: Invoice, attempt: int, acct: PaymentAccount) -> Payment:
    """The row of off-session charge `attempt` of an invoice, found again if a crashed job already made it: its id and
    key come from the invoice and the attempt."""
    key = f"charge:{inv.id}:{attempt}"
    pid = uuid.uuid5(NAMESPACE, f"{inv.workspace_id}:{key}")
    found = c.db.get(Payment, pid)
    if found:
        return found
    c.db.execute(pg_insert(Payment).values(
        id=pid, workspace_id=inv.workspace_id, contact_id=inv.contact_id, invoice_id=inv.id,
        subscription_id=inv.subscription_id, provider=acct.provider, account_id=acct.account_id, attempt_key=key,
        amount=invoicing.amount_due(inv), currency=inv.currency, method="card").on_conflict_do_nothing())
    return c.db.get(Payment, pid)


def succeed(c: Ctx, p: Payment, now: datetime, provider_payment_id: str | None = None) -> None:
    """Marks the payment succeeded (if it was not) and fulfils it once."""
    if p.status != "succeeded":
        p.status, p.succeeded_at, p.failure_code, p.failure_message = "succeeded", now, None, None
    if provider_payment_id and not p.provider_payment_id:
        p.provider_payment_id = provider_payment_id
    p.updated_at = now
    c.db.flush()
    fulfil(c, p, now)


def fulfil(c: Ctx, p: Payment, now: datetime) -> None:
    claimed = c.db.execute(update(Payment).where(Payment.id == p.id, Payment.fulfilled_at.is_(None))
                           .values(fulfilled_at=now).returning(Payment.id)).first()
    if claimed is None:
        return  # done before, by another delivery of the same news
    c.db.refresh(p)
    emit(c, "payment.succeeded", "payment", p.id, payment_event(p), p.contact_id, p.workspace_id)
    if p.invoice_id is None:
        return
    inv = invoicing.lock(c.db, p.invoice_id)
    extra = invoicing.apply_payment(c, inv, p.amount, now) if inv else p.amount
    if extra > 0 and p.provider != "manual":
        log.warning("payment %s paid %s more than invoice %s needed: refunding it", p.id, extra, p.invoice_id)
        request_refund(c, p, extra, "duplicate", "Paid more than was due: given back automatically", lock=False)


def fail(c: Ctx, p: Payment, now: datetime, code: str | None, message: str | None) -> bool:
    """Marks a pending payment failed; False when it had already moved on (a success is never undone)."""
    if RANK[p.status] >= RANK["failed"]:
        return False
    p.status, p.failure_code = "failed", (code or "failed")[:100]
    p.failure_message, p.updated_at = (message or "The payment did not go through.")[:500], now
    c.db.flush()
    return True


def apply_payment_update(c: Ctx, acct: PaymentAccount, u: Update, now: datetime) -> None:
    from . import billing  # billing imports this module
    p = None
    if u.payment_id:
        try:
            p = lock_payment(c.db, uuid.UUID(u.payment_id))
        except ValueError:
            p = None
        if p is None:
            raise Retry(f"payment {u.payment_id} is not committed yet")
    elif u.provider_payment_id:
        found = c.db.scalar(select(Payment.id).where(Payment.provider == acct.provider,
                                                     Payment.provider_payment_id == u.provider_payment_id))
        p = lock_payment(c.db, found) if found else None
    if p is None:
        log.info("%s for a payment go-high did not start (%s): ignored", u.event_type, u.provider_payment_id)
        return
    if p.account_id != acct.account_id:
        log.warning("%s for payment %s came from another account: ignored", u.event_type, p.id)
        return
    if u.status == "succeeded":
        if (u.amount is not None and u.amount != p.amount) or (u.currency and u.currency.lower() != p.currency):
            log.error("payment %s: the provider reports %s %s, we asked for %s %s; not fulfilled", p.id, u.amount,
                      u.currency, p.amount, p.currency)
            p.failure_message = "The provider reported a different amount; check it with the provider."
            c.db.flush()
            return
        keep_customer(c.db, p, u)
        succeed(c, p, now, u.provider_payment_id)
    elif u.status == "processing":
        if p.status == "pending":
            p.status, p.updated_at = "processing", now
            if u.provider_payment_id and not p.provider_payment_id:
                p.provider_payment_id = u.provider_payment_id
            c.db.flush()
    elif u.status == "failed":
        if u.provider_payment_id and not p.provider_payment_id:
            p.provider_payment_id = u.provider_payment_id
        if fail(c, p, now, u.failure_code, u.failure_message):
            billing.payment_failed(c, p, now)


# --- refunds ----------------------------------------------------------------------------------------------------

def reserved(db: Session, payment_id: uuid.UUID) -> int:
    """What is refunded or on its way back: every pending and succeeded refund."""
    return int(db.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(
        Refund.payment_id == payment_id, Refund.status.in_(("pending", "succeeded")))) or 0)


def refundable(p: Payment, refunds: list[Refund]) -> int:
    if p.status != "succeeded":
        return 0
    return p.amount - sum(r.amount for r in refunds if r.status in ("pending", "succeeded"))


def request_refund(c: Ctx, p: Payment, amount: int, reason: str | None, note: str, *, lock: bool = True) -> Refund:
    """A refund of part or all of a succeeded payment. Manual payments are given back by hand, so theirs is recorded as
    done; a provider's goes out from a job. 422 when the amount is more than is left to refund. The caller commits."""
    if lock:
        p = lock_payment(c.db, p.id)
    if p.status != "succeeded":
        raise ApiError(409, "conflict", "Only a payment that succeeded can be refunded")
    left = p.amount - reserved(c.db, p.id)
    if amount <= 0 or amount > left:
        raise ApiError(422, "validation_failed", "The refund is more than is left to refund",
                       {"amount": f"can be at most {left}"})
    r = Refund(workspace_id=p.workspace_id, payment_id=p.id, amount=amount, reason=reason, note=note,
               created_by=c.user_id)
    c.db.add(r)
    c.db.flush()
    if p.provider == "manual":
        set_refund(c, r, p, "succeeded", None, None, None)
    else:
        jobs.enqueue(c.db, "payments.refund", {"id": str(r.id), "workspace_id": str(p.workspace_id)},
                     max_attempts=12)
    return r


def set_refund(c: Ctx, r: Refund, p: Payment, status: str, provider_refund_id: str | None, failure: str | None,
               now: datetime | None) -> None:
    """Moves a refund (and the payment's refunded total with it). Pending can become anything; a succeeded refund
    that the provider later reports failed gives the amount back to the payment."""
    if provider_refund_id and not r.provider_refund_id:
        r.provider_refund_id = provider_refund_id
    if status == r.status or (status == "pending"):
        c.db.flush()
        return
    old = r.status
    r.status, r.updated_at = status, func.now()
    if status == "failed":
        r.failure_message = (failure or "The provider could not make the refund.")[:500]
    if status == "succeeded":
        p.amount_refunded = min(p.amount, p.amount_refunded + r.amount)
    elif old == "succeeded":
        p.amount_refunded = max(0, p.amount_refunded - r.amount)
    p.updated_at = func.now()
    c.db.flush()
    data = {"id": r.id, "payment_id": p.id, "contact_id": p.contact_id, "invoice_id": p.invoice_id,
            "amount": r.amount, "currency": p.currency, "reason": r.reason}
    if status == "succeeded":
        emit(c, "payment.refunded", "refund", r.id, {**data, "amount_refunded": p.amount_refunded}, p.contact_id,
             p.workspace_id)
    else:
        emit(c, "refund.failed", "refund", r.id, {**data, "failure_message": r.failure_message}, p.contact_id,
             p.workspace_id)


def apply_refund_update(c: Ctx, acct: PaymentAccount, u: Update, now: datetime) -> None:
    r = None
    if u.refund_id:
        try:
            r = c.db.get(Refund, uuid.UUID(u.refund_id))
        except ValueError:
            r = None
    if r is None and u.provider_refund_id:
        r = c.db.scalar(select(Refund).where(Refund.provider_refund_id == u.provider_refund_id))
    if r is not None:
        p = lock_payment(c.db, r.payment_id)
        c.db.refresh(r, with_for_update=True)
    else:
        found = c.db.scalar(select(Payment.id).where(Payment.provider == acct.provider,
                                                     Payment.provider_payment_id == u.provider_payment_id))
        p = lock_payment(c.db, found) if found else None
        if p is None or not u.amount or u.status == "failed":
            return  # a refund of a payment we do not know, or one that never was
        left = p.amount - reserved(c.db, p.id)
        if left <= 0:
            return
        # made at the provider (its dashboard): recorded so the ledger matches
        r = Refund(workspace_id=p.workspace_id, payment_id=p.id, amount=min(u.amount, left), reason=None,
                   note="Refunded at the provider", provider_refund_id=u.provider_refund_id)
        c.db.add(r)
        c.db.flush()
    if p is None or p.account_id != acct.account_id:
        return
    set_refund(c, r, p, u.status or "pending", u.provider_refund_id, u.failure_message, now)


@jobs.handler("payments.refund", backoff=lambda n: min(timedelta(seconds=30 * 2 ** (n - 1)), timedelta(hours=2)))
def send_refund(db: Session, payload: dict) -> None:
    """Asks the provider for a pending refund, with the refund's own idempotency key: a retried job cannot refund
    twice. A refusal the provider will not change is recorded as failed; anything else is retried."""
    from .scope import workspace_job
    with workspace_job(db, payload["workspace_id"]) as c:
        if c is None:
            return
        r = db.scalar(select(Refund).where(Refund.id == uuid.UUID(payload["id"])).with_for_update())
        if r is None or r.status != "pending":
            return
        p = lock_payment(db, r.payment_id)
        try:
            result = providers.get(p.provider).refund(p.account_id, RefundRequest(
                refund_id=str(r.id), provider_payment_id=p.provider_payment_id or "", amount=r.amount,
                reason=r.reason, idempotency_key=f"refund:{r.id}"))
        except ProviderError as e:
            if e.retryable:
                raise
            set_refund(c, r, p, "failed", None, str(e), None)
            return
        set_refund(c, r, p, result.status, result.provider_refund_id, result.failure_message, None)


# --- webhooks ---------------------------------------------------------------------------------------------------

def record_event(db: Session, workspace_id: uuid.UUID, provider: str, u: Update) -> bool:
    """True the first time this provider event is seen (and recorded, in the caller's transaction)."""
    return db.execute(pg_insert(PaymentEvent).values(workspace_id=workspace_id, provider=provider,
                                                     event_id=u.event_id[:255], event_type=u.event_type[:100])
                      .on_conflict_do_nothing().returning(PaymentEvent.id)).first() is not None


def apply(c: Ctx, acct: PaymentAccount, u: Update, now: datetime) -> None:
    if u.kind == "account" and u.account:
        apply_account(c, acct, u.account)
    elif u.kind == "payment":
        apply_payment_update(c, acct, u, now)
    elif u.kind == "refund":
        apply_refund_update(c, acct, u, now)


def success_urls(base: str) -> tuple[str, str]:
    return f"{base}?checkout=success", f"{base}?checkout=cancelled"


def origin() -> str:
    return config.ALLOWED_ORIGINS[0]
