"""Billing and usage API (module 06), under /api/v1/billing, and the cost preview at /api/v1/usage/preview.

Reading the wallet, the ledger, the usage summary, top-ups, prices and previews is `usage.read`. Topping up and the
workspace's own settings (alerts, auto-recharge, monthly cap, payment method) are `billing.manage`. What is the
organization's to decide (the wallet's mode, credit limit and currency, balance adjustments and rate cards) also needs
an organization owner or admin. Money is integer micros (money.py); the platform's cost of each line and the rate card
that priced it are shown to organization owners and admins only, so a client workspace never sees its agency's
margin."""
import csv
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import case, exists, func, literal_column, select
from sqlalchemy.exc import IntegrityError

from .. import events
from ..api import ApiError, Idem, idempotency, paginate
from ..inbox.models import Channel
from ..models import Brand, Workspace
from ..permissions import requires
from ..security import Ctx
from . import meters, money, payments, pricing, sending, topups, wallet
from .models import MODES, LedgerEntry, RateCard, Topup, Wallet

router = APIRouter(prefix="/api/v1/billing")
previews = APIRouter(prefix="/api/v1/usage")
read, manage, org = requires("usage.read"), requires("billing.manage"), requires("billing.manage", org=True)
EXPORT_CAP = 50_000
Meter = Literal[tuple(meters.METERS)]
Currency = Literal[money.CURRENCIES]
Money = Annotated[int, Field(ge=0, le=10**15)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- the wallet -------------------------------------------------------------------------------------------------

def hint(method: str | None) -> str | None:
    """What a person sees of a saved payment method: its last four characters."""
    return None if not method else f"…{method[-4:]}"


def status_of(w: Wallet, spent: int) -> str:
    if w.monthly_cap is not None and spent >= w.monthly_cap:
        return "capped"
    if w.balance <= 0 and w.mode == "prepaid":
        return "empty"
    if w.mode == "postpaid" and w.credit_limit is not None and w.balance <= -w.credit_limit:
        return "empty"
    if w.balance < 0 or (w.low_balance_at is not None and w.balance < w.low_balance_at):
        return "low"
    return "ok"


def wallet_json(c: Ctx, w: Wallet) -> dict:
    spent = wallet.month_spent(c.db, w.workspace_id)
    available = (w.balance if w.mode == "prepaid" else None if w.credit_limit is None else w.balance + w.credit_limit)
    return {"workspace_id": w.workspace_id, "currency": w.currency, "balance": w.balance, "mode": w.mode,
            "credit_limit": w.credit_limit, "available": available, "low_balance_at": w.low_balance_at,
            "auto_recharge": w.auto_recharge, "recharge_below": w.recharge_below,
            "recharge_amount": w.recharge_amount, "payment_method": hint(w.payment_method),
            "monthly_cap": w.monthly_cap, "cap_alert_pct": w.cap_alert_pct, "month_spent": spent,
            "month_start": wallet.month_start(), "status": status_of(w, spent),
            "minor_unit": money.minor_step(w.currency),
            "provider": payments.configured(), "updated_at": w.updated_at}


class WalletPatch(Strict):
    low_balance_at: Money | None = None
    auto_recharge: bool | None = None
    recharge_below: Money | None = None
    recharge_amount: Money | None = None
    payment_method: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=200)] | None = None
    monthly_cap: Money | None = None
    cap_alert_pct: Annotated[int, Field(ge=1, le=100)] | None = None
    # the organization's (owners and admins)
    mode: Literal[MODES] | None = None
    credit_limit: Money | None = None
    currency: Currency | None = None


ORG_FIELDS = ("mode", "credit_limit", "currency")
NULLABLE = ("low_balance_at", "recharge_below", "recharge_amount", "payment_method", "monthly_cap", "credit_limit")
AMOUNTS = ("low_balance_at", "recharge_below", "recharge_amount", "monthly_cap", "credit_limit")


@router.get("/wallet")
def get_wallet(c: Ctx = Depends(read)):
    w = wallet.wallet_of(c.db, c.workspace.id)
    c.db.commit()  # the wallet is made on first use
    return wallet_json(c, w)


@router.patch("/wallet")
def update_wallet(body: WalletPatch, c: Ctx = Depends(manage)):
    """Changes the settings it is sent; a null clears an amount (no alert, no cap, no credit limit) or the payment
    method. `mode`, `credit_limit` and `currency` are for organization owners and admins, and the currency only while
    the wallet has no ledger entries. Amounts are micros and must be whole minor units of the currency."""
    sent = body.model_fields_set
    if sent & set(ORG_FIELDS) and not c.org_admin:
        raise ApiError(403, "forbidden",
                       "Only organization owners and admins change the mode, credit limit or currency")
    w = wallet.wallet_of(c.db, c.workspace.id, lock=True)
    values = body.model_dump(include=sent)
    for key in sent - set(NULLABLE):
        if values[key] is None:
            raise ApiError(422, "validation_failed", "The settings are not valid", {key: "cannot be empty"})
    currency = values.get("currency") or w.currency
    if "currency" in sent and currency != w.currency and c.db.scalar(select(exists().where(
            LedgerEntry.workspace_id == w.workspace_id))):
        raise ApiError(409, "currency_locked", "The currency of a wallet with ledger entries cannot change")
    after = {k: values.get(k, getattr(w, k)) for k in (*AMOUNTS, "auto_recharge", "payment_method")}
    if "payment_method" in sent and not after["payment_method"] and "auto_recharge" not in sent:
        values["auto_recharge"] = after["auto_recharge"] = False  # a removed card cannot recharge
    errors = {k: f"must be a whole number of {currency} minor units" for k in AMOUNTS
              if after[k] is not None and not money.whole_minor(after[k], currency)}
    if after["auto_recharge"]:
        if after["recharge_below"] is None:
            errors["recharge_below"] = "is required for auto-recharge"
        if after["recharge_amount"] is None:
            errors["recharge_amount"] = "is required for auto-recharge"
        elif problem := topups.amount_problem(after["recharge_amount"], currency):
            errors.setdefault("recharge_amount", problem)
        if not after["payment_method"]:
            errors["payment_method"] = "is required for auto-recharge"
    if errors:
        raise ApiError(422, "validation_failed", "The settings are not valid", errors)
    changes = {}
    for key, value in values.items():
        if getattr(w, key) != value:
            changes[key] = {"old": getattr(w, key), "new": value} if key != "payment_method" else {"changed": True}
            setattr(w, key, value)
    if changes:
        w.updated_at = func.now()
        c.db.flush()
        c.db.refresh(w)
        events.emit(c.db, "wallet.updated", "wallet", w.workspace_id, {"changes": changes, "currency": w.currency},
                    actor=("user", c.user_id))
    c.db.commit()
    return wallet_json(c, w)


# --- the ledger -------------------------------------------------------------------------------------------------

def entry_json(e: LedgerEntry, margins: bool) -> dict:
    out = {"id": e.id, "kind": e.kind, "meter": e.meter, "quantity": e.quantity, "unit_price": e.unit_price,
           "price": e.price, "amount": e.amount, "balance_after": e.balance_after, "currency": e.currency,
           "source": e.source, "subject_type": e.subject_type, "subject_id": e.subject_id,
           "reverses_id": e.reverses_id, "description": e.description, "actor_type": e.actor_type,
           "actor_id": e.actor_id, "created_at": e.created_at}
    if margins:
        out |= {"unit_cost": e.unit_cost, "cost": e.cost, "rate_card_id": e.rate_card_id}
    return out


def instant(value: str | None, field: str, end: bool = False) -> datetime | None:
    """A date (the whole day, UTC) or an aware date and time."""
    if not value:
        return None
    try:
        if len(value) == 10:
            day = date.fromisoformat(value)
            return datetime.combine(day + timedelta(days=1) if end else day, time(), UTC)
        at = datetime.fromisoformat(value)
    except ValueError:
        raise ApiError(422, "validation_failed", "The filters are not valid",
                       {field: "must be a date (YYYY-MM-DD) or a date and time with a zone"}) from None
    if at.tzinfo is None:
        raise ApiError(422, "validation_failed", "The filters are not valid", {field: "needs a time zone"})
    return at


def ledger_filters(kind: Literal["usage", "reversal", "topup", "adjustment"] | None = None, meter: Meter | None = None,
                   source: Annotated[str, Query(max_length=20)] | None = None,
                   from_: Annotated[str | None, Query(alias="from", max_length=40)] = None,
                   to: Annotated[str | None, Query(max_length=40)] = None):
    """`from` and `to` are inclusive: a date covers its whole day (UTC)."""
    return {"kind": kind, "meter": meter, "source": source, "from": instant(from_, "from"),
            "to": instant(to, "to", end=True), "to_inclusive": bool(to and len(to) != 10)}


def ledger_query(f: dict):
    stmt = select(LedgerEntry)
    for key in ("kind", "meter", "source"):
        if f[key]:
            stmt = stmt.where(getattr(LedgerEntry, key) == f[key])
    if f["from"]:
        stmt = stmt.where(LedgerEntry.created_at >= f["from"])
    if f["to"]:
        stmt = stmt.where(LedgerEntry.created_at <= f["to"] if f["to_inclusive"] else LedgerEntry.created_at < f["to"])
    return stmt


@router.get("/ledger")
def list_ledger(limit: int = Query(50, ge=1, le=200), cursor: str | None = None, f: dict = Depends(ledger_filters),
                c: Ctx = Depends(read)):
    rows, next_cursor = paginate(c.db, ledger_query(f), LedgerEntry, limit, cursor)
    return {"data": [entry_json(r[0], c.org_admin) for r in rows], "next_cursor": next_cursor}


def neutral(value) -> str:
    """A cell a spreadsheet cannot run: text starting with = + - @, a tab or a line break gets a leading apostrophe."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r", "\n") else text


def major(micros: int) -> str:
    """Micros as exact decimal text in major units, for a spreadsheet ("-0.015800")."""
    sign = "-" if micros < 0 else ""
    return f"{sign}{abs(micros) // money.MICROS}.{abs(micros) % money.MICROS:06d}"


@router.get("/ledger/export")
def export_ledger(f: dict = Depends(ledger_filters), c: Ctx = Depends(read)):
    """The ledger as CSV (newest first, up to 50 000 rows, `X-Export-Truncated` when there were more), with amounts as
    exact decimals in the currency's major unit. The export is itself an event."""
    rows = list(c.db.scalars(ledger_query(f).order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
                             .limit(EXPORT_CAP + 1)))
    truncated, rows = len(rows) > EXPORT_CAP, rows[:EXPORT_CAP]
    margins, out = c.org_admin, io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["created_at", "kind", "meter", "description", "quantity", "unit_price", "price", "amount",
                     "balance_after", "currency", "source", "subject_type", "subject_id", "id"]
                    + (["unit_cost", "cost"] if margins else []))
    for e in rows:
        writer.writerow([e.created_at.isoformat(), e.kind, e.meter or "", neutral(e.description), e.quantity,
                         major(e.unit_price), major(e.price), major(e.amount), major(e.balance_after), e.currency,
                         neutral(e.source), e.subject_type or "", e.subject_id or "", e.id]
                        + ([major(e.unit_cost), major(e.cost)] if margins else []))
    events.emit(c.db, "usage.exported", "workspace", c.workspace.id,
                {"rows": len(rows), "truncated": truncated,
                 "filters": jsonable_encoder({k: v for k, v in f.items() if v and k != "to_inclusive"})},
                actor=("user", c.user_id))
    c.db.commit()
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="usage.csv"',
                             "X-Export-Truncated": "true" if truncated else "false"})


@router.get("/usage")
def usage_summary(group: Literal["day", "month"] = "day", f: dict = Depends(ledger_filters), c: Ctx = Depends(read)):
    """Usage net of refunds per meter over the range (default: this month), and per day or month: quantity, what it
    was charged and, for organization owners and admins, what it cost."""
    f = {**f, "kind": None, "from": f["from"] or wallet.month_start()}
    usage = ledger_query(f).where(LedgerEntry.kind.in_(wallet.USAGE_KINDS)).subquery()
    signed = case((usage.c.kind == "usage", 1), else_=-1)
    sums = (func.sum(usage.c.quantity * signed).label("quantity"), func.sum(-usage.c.amount).label("price"),
            func.sum(usage.c.cost * signed).label("cost"))
    period = func.date_trunc(group, usage.c.created_at, literal_column("'UTC'")).label("period")
    by_meter = c.db.execute(select(usage.c.meter, *sums).group_by(usage.c.meter).order_by(usage.c.meter)).all()
    series = c.db.execute(select(period, usage.c.meter, *sums).group_by(period, usage.c.meter).order_by(period)).all()
    margins, currency = c.org_admin, wallet.wallet_of(c.db, c.workspace.id).currency
    c.db.commit()

    def line(r) -> dict:
        out = {"meter": r.meter, "label": meters.METERS[r.meter][0], "quantity": int(r.quantity), "price": int(r.price)}
        return out | ({"cost": int(r.cost)} if margins else {})

    periods: dict = {}
    for r in series:
        p = periods.setdefault(r.period, {"period": r.period, "price": 0, "meters": {}})
        p["price"] += int(r.price)
        p["meters"][r.meter] = line(r)
    return {"currency": currency, "from": f["from"], "to": f["to"], "group": group,
            "price": sum(int(r.price) for r in by_meter),
            **({"cost": sum(int(r.cost) for r in by_meter)} if margins else {}),
            "meters": [line(r) for r in by_meter], "series": list(periods.values())}


# --- top-ups and adjustments ------------------------------------------------------------------------------------

class NewTopup(Strict):
    amount: Annotated[int, Field(gt=0, le=10**15)]


class NewAdjustment(Strict):
    amount: Annotated[int, Field(ge=-(10**15), le=10**15)]
    description: Label


@router.get("/topups")
def list_topups(status: Literal["pending", "succeeded", "failed"] | None = None,
                limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(read)):
    stmt = select(Topup) if status is None else select(Topup).where(Topup.status == status)
    rows, next_cursor = paginate(c.db, stmt, Topup, limit, cursor)
    return {"data": [topups.topup_json(r[0]) for r in rows], "next_cursor": next_cursor}


@router.post("/topups", status_code=201)
def create_topup(body: NewTopup, c: Ctx = Depends(manage), idem: Idem = Depends(idempotency)):
    """Charges the saved payment method `amount` (micros, whole minor units) and credits the wallet. Answers the
    top-up: `succeeded`, or `failed` with the provider's reason (201 either way: the attempt is recorded), or 202
    `pending` when the provider did not answer, which the same request asks again. Send an `Idempotency-Key`: a retry
    then charges once."""
    t = topups.by_hand(c.db, c.workspace.id, body.amount, c.user_id, idem.key)
    w = wallet.wallet_of(c.db, c.workspace.id)
    out = {**topups.topup_json(t), "wallet": wallet_json(c, w)}
    if t.status == "pending":  # the provider did not answer: nothing is stored under the key, so a retry asks again
        c.db.commit()
        return JSONResponse(jsonable_encoder(out), status_code=202)
    return idem.commit(201, out)


@router.post("/adjustments", status_code=201)
def create_adjustment(body: NewAdjustment, c: Ctx = Depends(org), idem: Idem = Depends(idempotency)):
    """A correction by the organization: a credit (positive) or a debit (negative), with a reason. It is not usage, so
    it does not count against the monthly cap."""
    w = wallet.wallet_of(c.db, c.workspace.id)
    if body.amount == 0 or not money.whole_minor(body.amount, w.currency):
        raise ApiError(422, "validation_failed", "The adjustment is not valid",
                       {"amount": f"must be a whole, non-zero number of {w.currency} minor units"})
    e = wallet.credit(c.db, c.workspace.id, body.amount, kind="adjustment", source="admin",
                      description=body.description, actor=("user", c.user_id),
                      key=f"adjustment:{idem.key}" if idem.key else None)
    events.emit(c.db, "wallet.adjusted", "usage", e.id, {"id": e.id, "amount": e.amount, "currency": e.currency,
                                                         "balance_after": e.balance_after,
                                                         "description": e.description},
                actor=("user", c.user_id))
    return idem.commit(201, entry_json(e, True))


# --- prices and rate cards --------------------------------------------------------------------------------------

@router.get("/meters")
def list_meters(c: Ctx = Depends(read)):
    """Every meter with what one unit costs this workspace now (and, for organization owners and admins, what it costs
    the platform and the card that prices it)."""
    w = wallet.wallet_of(c.db, c.workspace.id)
    out = []
    for key, (label, one, many) in meters.METERS.items():
        q = pricing.quote(c.db, c.workspace, w.currency, key, 1)
        row = {"meter": key, "label": label, "unit": one, "units": many, "unit_price": q.unit_price,
               "currency": w.currency}
        out.append(row | ({"unit_cost": q.unit_cost, "rate_card_id": q.rate_card_id, "basis": q.basis}
                          if c.org_admin else {}))
    c.db.commit()
    return {"data": out}


class NewCard(Strict):
    meter: Meter
    scope: Literal["organization", "brand", "workspace"] = "organization"
    brand_id: uuid.UUID | None = None  # scope brand
    workspace_id: uuid.UUID | None = None  # scope workspace (default: the current one)
    currency: Currency = "USD"
    price: Money | None = None
    markup_bp: Annotated[int, Field(ge=-10_000, le=1_000_000)] | None = None


class CardPatch(Strict):
    price: Money | None = None
    markup_bp: Annotated[int, Field(ge=-10_000, le=1_000_000)] | None = None


def card_json(card: RateCard) -> dict:
    scope = "workspace" if card.workspace_id else "brand" if card.brand_id else "organization"
    return {"id": card.id, "meter": card.meter, "scope": scope, "org_id": card.org_id, "brand_id": card.brand_id,
            "workspace_id": card.workspace_id, "currency": card.currency, "price": card.price,
            "markup_bp": card.markup_bp, "created_by": card.created_by, "created_at": card.created_at,
            "updated_at": card.updated_at}


def card_data(card: RateCard, **more) -> dict:
    return {**{k: v for k, v in card_json(card).items() if k not in ("created_by", "created_at", "updated_at")},
            **more}


def one_of(price: int | None, markup: int | None) -> None:
    if (price is None) == (markup is None):
        raise ApiError(422, "validation_failed", "The rate card is not valid",
                       {"price": "give a price per unit or a markup_bp, not both"})


def card_or_404(c: Ctx, card_id: uuid.UUID) -> RateCard:
    card = c.db.get(RateCard, card_id)  # row level security: this organization's cards
    if card is None or card.org_id != c.workspace.org_id:
        raise HTTPException(404, "Rate card not found")
    return card


@router.get("/rate-cards")
def list_rate_cards(meter: Meter | None = None, c: Ctx = Depends(org)):
    """Every rate card of the organization, most general first."""
    stmt = select(RateCard).where(RateCard.org_id == c.workspace.org_id)
    if meter:
        stmt = stmt.where(RateCard.meter == meter)
    specific = case((RateCard.workspace_id.is_not(None), 2), (RateCard.brand_id.is_not(None), 1), else_=0)
    return {"data": [card_json(r) for r in c.db.scalars(stmt.order_by(specific, RateCard.meter, RateCard.created_at))]}


@router.post("/rate-cards", status_code=201)
def create_rate_card(body: NewCard, c: Ctx = Depends(org), idem: Idem = Depends(idempotency)):
    """A price per unit (`price`, micros) or a markup over the cost (`markup_bp`, basis points: 2500 is 25 %, -10000
    is free) for one meter and currency, for the whole organization, one of its brands or one of its workspaces."""
    one_of(body.price, body.markup_bp)
    brand = workspace = None
    if body.scope == "brand":
        brand = body.brand_id or c.workspace.brand_id
        if c.db.scalar(select(Brand.id).where(Brand.id == brand, Brand.org_id == c.workspace.org_id)) is None:
            raise ApiError(422, "validation_failed", "The rate card is not valid",
                           {"brand_id": "is not a brand of this organization"})
    elif body.scope == "workspace":
        workspace = body.workspace_id or c.workspace.id
        if c.db.scalar(select(Workspace.id).where(Workspace.id == workspace,
                                                  Workspace.org_id == c.workspace.org_id)) is None:
            raise ApiError(422, "validation_failed", "The rate card is not valid",
                           {"workspace_id": "is not a workspace of this organization"})
    card = RateCard(org_id=c.workspace.org_id, brand_id=brand, workspace_id=workspace, meter=body.meter,
                    currency=body.currency, price=body.price, markup_bp=body.markup_bp, created_by=c.user_id)
    c.db.add(card)
    try:
        c.db.flush()
    except IntegrityError:
        c.db.rollback()
        raise ApiError(409, "rate_card_exists", "That meter already has a rate card at this level and currency; "
                                                "change it instead") from None
    c.db.refresh(card)
    events.emit(c.db, "rate_card.created", "rate_card", card.id, card_data(card), actor=("user", c.user_id))
    return idem.commit(201, card_json(card))


@router.patch("/rate-cards/{card_id}")
def update_rate_card(card_id: uuid.UUID, body: CardPatch, c: Ctx = Depends(org)):
    """Switches a card between a price and a markup, or changes the one it has. Charges made before keep their price."""
    card = card_or_404(c, card_id)
    sent = body.model_fields_set
    price = body.price if "price" in sent else (None if "markup_bp" in sent else card.price)
    markup = body.markup_bp if "markup_bp" in sent else (None if "price" in sent else card.markup_bp)
    one_of(price, markup)
    changes = {k: {"old": getattr(card, k), "new": v} for k, v in (("price", price), ("markup_bp", markup))
               if getattr(card, k) != v}
    if changes:
        card.price, card.markup_bp, card.updated_at = price, markup, func.now()
        c.db.flush()
        c.db.refresh(card)
        events.emit(c.db, "rate_card.updated", "rate_card", card.id, card_data(card, changes=changes),
                    actor=("user", c.user_id))
    c.db.commit()
    return card_json(card)


@router.delete("/rate-cards/{card_id}", status_code=204)
def delete_rate_card(card_id: uuid.UUID, c: Ctx = Depends(org)):
    """The next more general card (or the cost) prices that meter from now on; past charges keep their price."""
    card = card_or_404(c, card_id)
    events.emit(c.db, "rate_card.deleted", "rate_card", card.id, card_data(card), actor=("user", c.user_id))
    c.db.delete(card)
    c.db.commit()
    return Response(status_code=204)


# --- the cost preview -------------------------------------------------------------------------------------------

class PreviewItem(Strict):
    meter: Meter
    quantity: Annotated[int, Field(ge=1, le=100_000_000)]


class PreviewBody(Strict):
    items: Annotated[list[PreviewItem], Field(max_length=20)] = []
    channel_id: uuid.UUID | None = None  # a message: the channel it would go out on...
    body: Annotated[str, Field(max_length=10_000)] = ""  # ...its text (an SMS counts segments)...
    recipients: Annotated[int, Field(ge=1, le=1_000_000)] = 1  # ...and how many people it goes to (a bulk send)


@previews.post("/preview")
def preview_cost(body: PreviewBody, c: Ctx = Depends(read)):
    """What these would cost the workspace and whether the wallet would let them through now, before anything is
    sent: `lines` (meter, quantity, unit price, price), `price`, `balance`, `balance_after`, `allowed`, and when not,
    `code` (`wallet_empty`, `credit_limit`, `usage_cap`) and `reason`; `warnings` for a balance that goes low or
    negative or a cap that comes close. Give `items`, or a message (`channel_id`, `body`, `recipients`), or both."""
    items = [(i.meter, i.quantity, None) for i in body.items]
    if body.channel_id:
        channel = c.db.get(Channel, body.channel_id)
        if channel is None:
            raise HTTPException(404, "Channel not found")
        items += sending.items(channel, body.body, body.recipients)
    elif not items:
        raise ApiError(422, "validation_failed", "Nothing to price", {"items": "give items or a channel_id"})
    p = wallet.preview(c.db, c.workspace, items)
    c.db.commit()
    out = p.json()
    if not c.org_admin:
        out.pop("cost")
        for line in out["lines"]:
            for key in ("unit_cost", "cost", "rate_card_id", "basis"):
                line.pop(key)
    return out
