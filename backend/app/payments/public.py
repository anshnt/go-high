"""The public side of payments (module 21): a payment link's page and checkout, an invoice's page (and print view) and
its checkout, and the test provider's card page. Nothing here is signed in: the workspace comes from the link (a
payment link's public key, or an invoice token whose HMAC is checked), the database scope is that workspace and no
more, and every amount is worked out on the server from the stored prices: a visitor sends quantities (within the
link's bounds), a discount code, a name and an email, never a price or a total. Checkouts are rate limited per visitor
(a keyed hash of the address) and per link or invoice, and a filled honeypot gets a believable page and nothing else."""
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import config, jobs
from ..api import ApiError
from ..calendars import contacts
from ..db import rescope, scoped
from ..models import Workspace
from ..records.models import Record
from ..records.schema import Catalog
from ..security import client_ip
from . import billing, catalog, invoicing, ledger, money, pages
from .invoicing import LineSpec
from .models import CheckoutAttempt, Invoice, Payment, PaymentLink, Price, Refund
from .providers import fake
from .providers.base import ProviderError
from .scope import system_ctx

log = logging.getLogger("payments")
router = APIRouter()
CHECKOUT_LIFETIME = timedelta(hours=25)  # longer than a Stripe Checkout session (24 h): it lapses first


def public_db():
    with scoped(system="on") as db:
        yield db


def now() -> datetime:
    return datetime.now(UTC)


def html(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(body, status_code=status, headers=pages.HEADERS)


def gone(title: str = "Not found", text: str = "This link is not valid.") -> HTMLResponse:
    return html(pages.message(title, text, "info"), 404)


def enter(db: Session, ws: Workspace) -> None:
    rescope(db, workspace_id=ws.id, org_id=ws.org_id)


def visitor(request: Request) -> str:
    return hashlib.sha256(f"{config.SECRET_KEY}|pay|{client_ip(request)}".encode()).hexdigest()


def throttled(db: Session, ws: Workspace, target: str, ip_hash: str) -> bool:
    """Counts this attempt (committed, so refused attempts count too) and says whether it is one too many."""
    window = now() - timedelta(minutes=config.CHECKOUT_WINDOW_MINUTES)
    db.execute(delete(CheckoutAttempt).where(CheckoutAttempt.created_at < window))
    count = select(func.count()).select_from(CheckoutAttempt).where(CheckoutAttempt.target == target)
    per_ip = db.scalar(count.where(CheckoutAttempt.ip_hash == ip_hash)) or 0
    total = db.scalar(count) or 0
    db.add(CheckoutAttempt(workspace_id=ws.id, target=target, ip_hash=ip_hash))
    db.commit()
    return per_ip >= config.CHECKOUT_MAX_PER_IP or total >= config.CHECKOUT_MAX_PER_TARGET


async def form(request: Request) -> dict[str, str]:
    raw = await request.body()
    if len(raw) > 20_000:
        return {}
    return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}


def settings(db: Session, ws: Workspace):
    s = invoicing.settings_of(db, ws.id)
    return s


def business(db: Session, ws: Workspace) -> str:
    return settings(db, ws).business_name or ws.name


# --- payment links ----------------------------------------------------------------------------------------------

def find_link(db: Session, key: str) -> tuple[Workspace, PaymentLink] | None:
    """The link of a public key, found in the system scope (the `system` policy lets it read links, as a webhook reads
    channels), and the session moved into its workspace."""
    if not key or len(key) > 40:
        return None
    rescope(db, system="on")
    found = db.scalar(select(PaymentLink.workspace_id).where(PaymentLink.public_key == key))
    ws = db.get(Workspace, found) if found else None
    if ws is None:
        return None
    enter(db, ws)
    link = db.scalar(select(PaymentLink).where(PaymentLink.public_key == key))
    return (ws, link) if link else None


def link_items(db: Session, link: PaymentLink) -> list[tuple]:
    out = []
    for i, item in enumerate(link.items):
        price = db.get(Price, uuid.UUID(item["price_id"]))
        if price is None:
            continue
        unit = money.format_amount(price.unit_amount, price.currency) if price.scheme == "fixed" else "Tiered"
        if price.type == "recurring":
            every = f"{price.interval_count} {price.interval}s" if price.interval_count > 1 else price.interval
            unit += f" / {every}"
        out.append((i, price, invoicing.describe(db, price), unit, item["quantity"], item["adjustable"],
                    item["min"], item["max"]))
    return out


def link_ready(db: Session, link: PaymentLink, items: list[tuple]) -> bool:
    if not link.active or not items or len(items) != len(link.items):
        return False
    for _, price, *_ in items:
        try:
            catalog.price_or_422(db, price.id, "price")
        except ApiError:
            return False
    return ledger.not_ready(ledger.account_of(db)) is None


@router.get("/pay/print.js", include_in_schema=False)
def print_script():
    return Response(pages.PRINT_JS, media_type="text/javascript", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/pay/{key}", include_in_schema=False)
def link_page(key: str, db: Session = Depends(public_db)):
    found = find_link(db, key)
    if found is None:
        return gone("Payment link", "This payment link does not exist.")
    ws, link = found
    items = link_items(db, link)
    if not link.active:
        return html(pages.message(link.name, "This payment link is no longer active.", "info", business(db, ws)), 410)
    out = pages.link_page(link, items, business(db, ws), action=f"/api/public/pay/{key}/checkout",
                          available=link_ready(db, link, items))
    db.commit()
    return html(out)


@router.post("/api/public/pay/{key}/checkout", include_in_schema=False)
async def link_checkout(key: str, request: Request):
    values = await form(request)
    ip_hash = visitor(request)
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(start_link_checkout, key, values, ip_hash)


def start_link_checkout(key: str, values: dict[str, str], ip_hash: str):
    with scoped(system="on") as db:
        found = find_link(db, key)
        if found is None:
            return gone("Payment link", "This payment link does not exist.")
        ws, link = found
        items = link_items(db, link)
        name = business(db, ws)

        def again(error: str, status: int = 422):
            db.rollback()
            return html(pages.link_page(link, items, name, action=f"/api/public/pay/{key}/checkout", error=error,
                                        values=values, available=link_ready(db, link, items)), status)

        if not link_ready(db, link, items):
            return again("This page cannot take payments right now. Please try again later.", 409)
        if throttled(db, ws, str(link.id), ip_hash):
            return again("Too many attempts. Please wait a few minutes and try again.", 429)
        enter(db, ws)
        if values.get("website"):
            return html(pages.message("Almost done", "Thank you. We will be in touch.", "ok", name))
        who_name = (values.get("name") or "").strip()[:300]
        email = (values.get("email") or "").strip()[:254]
        phone = (values.get("phone") or "").strip()[:40] or None
        if not who_name or not email:
            return again("Please enter your name and email.")
        specs, chosen = [], []
        for i, price, _description, _unit, quantity, adjustable, low, high in items:
            qty = quantity
            if adjustable:
                try:
                    qty = int(values.get(f"qty_{i}", quantity))
                except ValueError:
                    return again("Please enter a whole number for each quantity.")
                if not low <= qty <= high:
                    return again(f"Quantities must be between {low} and {high}.")
            specs.append(LineSpec(price_id=price.id, quantity=qty))
            chosen.append((price, qty))
        currency = chosen[0][0].currency
        c = system_ctx(db, ws)
        try:
            who = contacts.clean(Catalog(c), contacts.Invitee(who_name, email, phone))
        except ApiError as e:
            return again("Please check your " + ", ".join(sorted(e.fields or {"details": ""})) + ".")
        at = now()
        coupon = None
        code = (values.get("coupon") or "").strip()
        if code and link.allow_coupons:
            coupon = catalog.by_code(db, code)
            reason = "This code does not exist." if coupon is None else None
            if coupon is not None:
                existing = contacts.find(Catalog(c), who)
                reason = catalog.usable(db, coupon, contact_id=existing.id if existing else None, currency=currency,
                                        price_ids={p.id for p, _ in chosen}, now=at)
            if reason:
                return again(reason)
        try:
            contact = contacts.attach(Catalog(c), who, None)
        except ApiError as e:
            if e.status_code == 403:
                log.warning("checkout refused: the Automation role of workspace %s cannot write contacts", ws.id)
                return again("This page cannot take payments right now. Please try again later.", 503)
            raise
        acct = ledger.account_of(db)
        price, qty = chosen[0]
        if price.type == "recurring":
            try:
                s = billing.create(c, contact_id=contact.id, price=price, quantity=qty, coupon=coupon,
                                   trial_days=None, collection="charge_automatically", now=at)
            except ApiError as e:
                return again(e.detail if isinstance(e.detail, str) else "That did not work. Please try again.")
            if s.status == "trialing":
                db.commit()
                return html(pages.message("Your trial has started",
                                          link.success_message or "Thank you. Your trial has started.", "ok", name))
            inv = db.get(Invoice, s.latest_invoice_id)
        else:
            inv = invoicing.new(c, contact_id=contact.id, currency=currency, reason="payment_link",
                                expires_at=at + CHECKOUT_LIFETIME)
            inv.payment_link_id = link.id
            try:
                invoicing.write_lines(c, inv, specs, coupon)
                invoicing.issue(c, inv, at, number=False, due_days=0)
            except ApiError as e:
                return again(e.detail if isinstance(e.detail, str) else "That did not work. Please try again.")
            invoicing.emit(c, "invoice.created", inv)
            jobs.enqueue(db, "payments.expire_checkout", {"id": str(inv.id), "workspace_id": str(ws.id)},
                         run_at=inv.expires_at)
        done = f"{ledger.origin()}/pay/{key}/done"
        if inv.status == "paid":  # nothing to pay (a full discount)
            db.commit()
            return RedirectResponse(done, status_code=303)
        return to_provider(db, c, inv, acct, email, f"{done}?checkout=success",
                           f"{ledger.origin()}/pay/{key}?checkout=cancelled", lambda m: again(m, 502))


def to_provider(db: Session, c, inv: Invoice, acct, email: str | None, success: str, cancel: str, fail):
    """Commits the payment row, then asks the provider for its page and sends the visitor there (303)."""
    p = ledger.prepare_checkout(c, inv, acct)
    pid = p.id
    db.commit()
    p = ledger.lock_payment(db, pid)
    try:
        url = ledger.open_checkout(c, p, inv, email=email, success_url=success, cancel_url=cancel)
    except ProviderError as e:
        log.warning("checkout of payment %s: the provider refused: %s", pid, e)
        return fail("The payment page could not be opened. Please try again in a moment.")
    db.commit()
    return RedirectResponse(url, status_code=303)


@router.get("/pay/{key}/done", include_in_schema=False)
def link_done(key: str, db: Session = Depends(public_db)):
    found = find_link(db, key)
    if found is None:
        return gone()
    ws, link = found
    name = business(db, ws)
    db.commit()
    if link.redirect_url:
        return RedirectResponse(link.redirect_url, status_code=303)
    return html(pages.message("Thank you", link.success_message or
                              "Your payment was received. A receipt is on its way.", "ok", name))


@jobs.handler("payments.expire_checkout")
def expire_checkout(db: Session, payload: dict) -> None:
    """A payment link's checkout that was never paid lapses: its invoice is voided (no number was given) and its
    discount code use given back. A payment that still arrives is refunded (ledger.fulfil)."""
    from .scope import workspace_job
    with workspace_job(db, payload["workspace_id"]) as c:
        if c is None:
            return
        inv = invoicing.lock(db, uuid.UUID(payload["id"]))
        if inv is None or inv.status != "open" or inv.amount_paid or inv.billing_reason != "payment_link":
            return
        invoicing.void(c, inv, now(), "checkout_expired")


# --- invoices ---------------------------------------------------------------------------------------------------

def invoice_of(db: Session, tok: str) -> tuple[Workspace, Invoice] | None:
    parsed = invoicing.parse_token(tok)
    if parsed is None:
        return None
    ws = db.get(Workspace, parsed[0])
    if ws is None:
        return None
    enter(db, ws)
    inv = db.get(Invoice, parsed[1])
    if inv is None or invoicing.public_path(inv) is None:
        return None
    return ws, inv


@router.get("/invoice/{tok}", include_in_schema=False)
def invoice_page(tok: str, checkout: str | None = None, db: Session = Depends(public_db)):
    found = invoice_of(db, tok)
    if found is None:
        return gone("Invoice", "This invoice link is not valid.")
    ws, inv = found
    s = settings(db, ws)
    c = system_ctx(db, ws)
    contact = contacts.visible(c, {inv.contact_id}).get(inv.contact_id) if inv.contact_id else None
    lines = invoicing.lines_of(db, [inv.id])[inv.id]
    online = ledger.not_ready(ledger.account_of(db)) is None
    flash = None
    if checkout == "success" and inv.status == "open":
        flash = pages.notice("Thank you. Your payment is being confirmed; this page will show it as paid shortly.",
                             "ok")
    elif checkout == "cancelled" and inv.status == "open":
        flash = pages.notice("The payment was not completed. You can try again.", "info")
    elif inv.status == "open" and not online:
        flash = pages.notice("Online payment is not available for this invoice right now.", "info")
    refunded = int(db.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).join(
        Payment, Payment.id == Refund.payment_id).where(Refund.status == "succeeded", Payment.invoice_id == inv.id))
        or 0)
    out = pages.invoice(inv, lines, s, contact, pay_action=f"/api/public/invoices/{tok}/checkout" if online else None,
                        flash=flash, refunded=refunded)
    db.commit()
    return html(out)


@router.post("/api/public/invoices/{tok}/checkout", include_in_schema=False)
async def invoice_checkout(tok: str, request: Request):
    ip_hash = visitor(request)
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(start_invoice_checkout, tok, ip_hash)


def start_invoice_checkout(tok: str, ip_hash: str):
    with scoped(system="on") as db:
        found = invoice_of(db, tok)
        if found is None:
            return gone("Invoice", "This invoice link is not valid.")
        ws, inv = found
        page = f"{ledger.origin()}/invoice/{tok}"
        if throttled(db, ws, str(inv.id), ip_hash):
            return html(pages.message("Please wait", "Too many attempts. Please try again in a few minutes.",
                                      "info", business(db, ws)), 429)
        enter(db, ws)
        inv = invoicing.lock(db, inv.id)
        acct = ledger.account_of(db)
        if inv.status != "open" or invoicing.amount_due(inv) <= 0 or ledger.not_ready(acct):
            db.rollback()
            return RedirectResponse(page, status_code=303)
        c = system_ctx(db, ws)
        email = None
        if inv.contact_id:
            rec = db.get(Record, inv.contact_id)
            email = rec.email_norm if rec else None

        def fail(message: str):
            return html(pages.message("Please try again", message, "", business(db, ws)), 502)

        return to_provider(db, c, inv, acct, email, f"{page}?checkout=success", f"{page}?checkout=cancelled", fail)


# --- the test provider ------------------------------------------------------------------------------------------

@router.get("/api/public/payments/fake/{session}", include_in_schema=False)
def fake_page(session: str):
    data = fake.unseal(session) if config.PAYMENTS_FAKE_PROVIDER else None
    if data is None:
        return gone("Checkout", "This checkout is not valid.")
    return html(pages.fake_checkout(data["d"], money.format_amount(data["m"], data["c"]),
                                    f"/api/public/payments/fake/{session}/complete", data["no"]))


@router.post("/api/public/payments/fake/{session}/complete", include_in_schema=False)
async def fake_complete(session: str, request: Request):
    """What the test provider's page does: report the payment by a signed webhook through the real webhook route's
    code, then send the visitor back. Repeating it repeats the same event id, which is applied once."""
    data = fake.unseal(session) if config.PAYMENTS_FAKE_PROVIDER else None
    if data is None:
        return gone("Checkout", "This checkout is not valid.")
    outcome = (await form(request)).get("outcome")
    ok = outcome == "succeeded"
    body = fake.event(data["a"], "payment.succeeded" if ok else "payment.failed", {
        "payment_id": data["p"], "provider_payment_id": data["pi"], "amount": data["m"], "currency": data["c"],
        "customer_id": f"cus_fake_{hashlib.sha256(data['p'].encode()).hexdigest()[:14]}",
        "payment_method_id": "pm_fake_visa" if (ok and data["s"]) else None, "card_brand": "visa" if ok else None,
        "card_last4": "4242" if ok else None, "failure_code": None if ok else "card_declined",
        "failure_message": None if ok else "Your card was declined."},
        event_id=f"evt_fake_{data['pi']}_{'ok' if ok else 'no'}")
    from starlette.concurrency import run_in_threadpool

    from .hooks import process
    try:
        await run_in_threadpool(process, "fake", fake.signed(body), body)
    except Exception:  # noqa: BLE001  (shown as a failed checkout; the cause is logged by the hook)
        log.exception("test checkout could not be applied")
    return RedirectResponse(data["ok"] if ok else data["no"], status_code=303)
