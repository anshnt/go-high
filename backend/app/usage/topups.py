"""Top-ups: money from the workspace's payment method into its wallet, by hand (`POST /billing/topups`) or by the
auto-recharge job when a charge takes the balance below the workspace's mark.

A top-up is a row that is `pending` while the provider is asked, committed before the call so that a crash in between
leaves a trace instead of a charge nobody knows about, and then `succeeded` (with one `topup` ledger entry, keyed by the
top-up, so it can never credit twice) or `failed` (with the provider's reason, and a `wallet.topup_failed` event that
the people who manage billing hear about). The provider is asked with the top-up's id as its idempotency key, so asking
again for a pending one (a retried request, a second worker) charges the card once."""
import logging
import os
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import events, jobs
from ..api import ApiError
from ..db import acting
from ..models import Workspace
from . import money, payments, wallet
from .models import Topup, Wallet

log = logging.getLogger("usage")
MAX_MAJOR = int(os.getenv("TOPUP_MAX", "10000"))  # the largest top-up, in major units of the wallet's currency


def topup_json(t: Topup) -> dict:
    return {"id": t.id, "amount": t.amount, "currency": t.currency, "status": t.status, "trigger": t.trigger,
            "provider": t.provider, "provider_ref": t.provider_ref, "error": t.error, "ledger_id": t.ledger_id,
            "created_by": t.created_by, "created_at": t.created_at, "completed_at": t.completed_at}


def amount_problem(amount: int, currency: str) -> str | None:
    """What is wrong with a top-up amount (micros), or None."""
    if amount < money.MICROS:
        return f"must be at least {money.show(money.MICROS, currency)}"
    if amount > MAX_MAJOR * money.MICROS:
        return f"must be at most {money.show(MAX_MAJOR * money.MICROS, currency)}"
    if not money.whole_minor(amount, currency):
        return f"must be a whole number of {currency} minor units"
    return None


class Unanswered(Exception):
    """The provider did not say yes or no (a timeout, an outage): the top-up stays pending, and asking again with its
    key is safe, since the provider charges a key once."""


def settle(db: Session, topup_id: uuid.UUID, charge: payments.Charge | None, error: str | None) -> Topup:
    """Records what the provider answered, once: the first answer for a pending top-up wins. `charge` is a yes, `error`
    a no; with neither (the provider did not answer) the top-up stays pending with the reason in `error`."""
    t = db.scalar(select(Topup).where(Topup.id == topup_id).with_for_update()
                  .execution_options(populate_existing=True))
    if t.status != "pending":
        return t
    actor = ("user", t.created_by) if t.created_by else None
    if charge is not None:
        entry = wallet.credit(db, t.workspace_id, t.amount, kind="topup", source="auto_recharge" if t.trigger == "auto"
                              else "api", key=f"topup:{t.id}", subject=("topup", t.id),
                              description=f"Top-up ({'automatic' if t.trigger == 'auto' else 'by hand'})", actor=actor)
        t.status, t.provider_ref, t.ledger_id, t.error = "succeeded", charge.reference, entry.id, None
        t.completed_at = func.now()
        events.emit(db, "wallet.topped_up", "topup", t.id, {
            "id": t.id, "amount": t.amount, "currency": t.currency, "trigger": t.trigger,
            "balance_after": entry.balance_after, "provider": t.provider}, workspace_id=t.workspace_id, actor=actor)
    elif error is not None:
        t.status, t.error, t.completed_at = "failed", error[:300], func.now()
        events.emit(db, "wallet.topup_failed", "topup", t.id, {
            "id": t.id, "amount": t.amount, "currency": t.currency, "trigger": t.trigger, "error": t.error},
            workspace_id=t.workspace_id, actor=actor)
    else:
        t.error = "The payment provider has not answered yet; asking again charges the card at most once"
    db.flush()
    db.refresh(t)
    return t


def ask(t: Topup, payment_method: str) -> tuple[payments.Charge | None, str | None]:
    """(the charge, None) for a yes, (None, reason) for a no, (None, None) when the provider did not answer: a
    retryable error, or anything unexpected, after which the charge may or may not have happened."""
    try:
        return payments.provider().charge(
            amount_minor=money.to_minor(t.amount, t.currency), currency=t.currency, payment_method=payment_method,
            idempotency_key=f"topup:{t.id}", description="Wallet top-up"), None
    except payments.PaymentError as e:
        if e.retryable:
            log.warning("top-up %s: the provider did not answer: %s", t.id, e)
            return None, None
        return None, str(e) or "The payment failed"
    except Exception:
        log.exception("top-up %s: the provider call failed", t.id)
        return None, None


def by_hand(db: Session, workspace_id: uuid.UUID, amount: int, user_id: uuid.UUID, key: str | None) -> Topup:
    """A top-up asked for in a request (`db` is the request's session). Commits the pending row before calling the
    provider. A second request with the same Idempotency-Key finds the first top-up and finishes it instead of starting
    another (the provider is asked with the top-up's own key, so the card is charged once). A top-up the provider did
    not answer is returned `pending`; the same request again asks again."""
    w = wallet.wallet_of(db, workspace_id)
    if problem := amount_problem(amount, w.currency):
        raise ApiError(422, "validation_failed", "The top-up is not valid", {"amount": problem})
    if not w.payment_method:
        raise ApiError(422, "no_payment_method", "Add a payment method before topping up")
    if payments.configured() not in payments.PROVIDERS:
        raise ApiError(503, "payments_unavailable", "Top-ups are not available: no payment provider is set up")
    t = key and db.scalar(select(Topup).where(Topup.workspace_id == workspace_id, Topup.idempotency_key == key))
    if not t:
        t = Topup(workspace_id=workspace_id, amount=amount, currency=w.currency, provider=payments.provider().name,
                  idempotency_key=key, created_by=user_id)
        db.add(t)
        try:
            db.commit()
        except IntegrityError:  # a twin request with the same key got there first: finish that one
            db.rollback()
            t = db.scalar(select(Topup).where(Topup.workspace_id == workspace_id, Topup.idempotency_key == key))
    if t.amount != amount:
        raise ApiError(409, "idempotency_key_reused", "This Idempotency-Key was already used for another top-up")
    if t.status != "pending":
        return t
    charge, error = ask(t, w.payment_method)
    return settle(db, t.id, charge, error)


@jobs.handler("wallet.recharge")
def recharge(db: Session, payload: dict) -> None:
    """Tops the wallet up by its recharge amount when auto-recharge is on and the balance is still below the mark
    (a top-up by hand in between makes it do nothing). At most one automatic top-up is pending per workspace: a run
    that finds one asks the provider about it again (same key, so at most one charge) instead of starting another, and
    a provider that does not answer makes the job fail, so the queue tries again with its backoff. Runs in the worker;
    the row writes go through `acting`, so row level security holds them to the workspace."""
    ws = db.get(Workspace, uuid.UUID(payload["workspace_id"]))
    if ws is None:
        return
    with acting(db, workspace_id=ws.id, org_id=ws.org_id):
        w = db.get(Wallet, ws.id)
        pending = db.scalar(select(Topup.id).where(Topup.workspace_id == ws.id, Topup.trigger == "auto",
                                                   Topup.status == "pending"))
        if pending is None:
            if (w is None or not w.auto_recharge or w.recharge_below is None or w.balance >= w.recharge_below
                    or not w.payment_method or amount_problem(w.recharge_amount or 0, w.currency)):
                return
            pending = db.execute(pg_insert(Topup).values(
                workspace_id=ws.id, amount=w.recharge_amount, currency=w.currency, trigger="auto",
                provider=payments.provider().name).on_conflict_do_nothing().returning(Topup.id)).scalar()
            if pending is None:  # another run made one a moment ago; it asks the provider
                return
        method = w.payment_method if w else None
    db.commit()  # the pending row exists before the provider is asked
    t = db.get(Topup, pending)
    charge, error = ask(t, method) if method else (None, "The payment method was removed")
    with acting(db, workspace_id=ws.id, org_id=ws.org_id):
        t = settle(db, pending, charge, error)
    db.commit()
    if t.status == "failed":
        log.warning("automatic top-up of workspace %s failed: %s", ws.id, t.error)
    elif t.status == "pending":
        raise Unanswered(t.error)
