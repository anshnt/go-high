"""Webhooks (ADR 0003): endpoints, fan-out of events to deliveries, signed delivery with retries, delivery log, replay.
Routes are /api/v1/webhooks, for workspace admins. Delivery runs in the worker (see `deliver`)."""
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import AfterValidator, BaseModel, Field, StringConstraints
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    any_,
    cast,
    func,
    insert,
    literal,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import events, jobs, ssrf
from .api import ApiError, Idem, idempotency, paginate
from .db import Base
from .events import Event
from .models import created, pk
from .security import Ctx, workspace_admin

log = logging.getLogger("webhooks")
router = APIRouter(prefix="/api/v1/webhooks")

TIMEOUT = 10  # seconds for one delivery attempt, connect to last byte
MAX_ATTEMPTS = 12
GIVE_UP = timedelta(days=3)  # an endpoint that only failed for this long is disabled
STATUSES = ("pending", "retrying", "succeeded", "failed")


# ponytail: the secret is stored as is because every delivery must sign with it. Encrypt it with a managed key
# (and offer rotation) before this holds customer secrets at scale.
class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (UniqueConstraint("id", "workspace_id"),)

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    event_types: Mapped[list[str]] = mapped_column(ARRAY(String(100)))  # event type names, or "*" for all
    filter: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))  # data must contain
    secret: Mapped[str] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    disabled_reason: Mapped[str | None] = mapped_column(String(200))
    failing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # first failure since last success
    created_at: Mapped[datetime] = created()


# No foreign key to events: events are the hot table and get partitioned, which a foreign key would block.
# `deliver` checks that the event belongs to the delivery's workspace instead.
class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(["endpoint_id", "workspace_id"],
                             ["webhook_endpoints.id", "webhook_endpoints.workspace_id"], ondelete="CASCADE"),
        CheckConstraint("status IN ('pending', 'retrying', 'succeeded', 'failed')",
                        name="ck_webhook_deliveries_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID]
    endpoint_id: Mapped[uuid.UUID]
    event_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_status: Mapped[int | None]
    response_ms: Mapped[int | None]
    response_body_excerpt: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(300))  # what went wrong before any response (timeout, refused URL)
    replay_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("webhook_deliveries.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()


Index("ix_webhook_deliveries_endpoint", WebhookDelivery.endpoint_id, WebhookDelivery.created_at.desc(),
      WebhookDelivery.id.desc())


def known_type(name: str) -> str:
    if name != "*" and name not in events.TYPES:
        raise ValueError(f"unknown event type {name!r}")
    return name


Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
EventTypes = Annotated[list[Annotated[str, AfterValidator(known_type)]], Field(min_length=1, max_length=100)]


class NewWebhook(BaseModel):
    url: Url
    event_types: EventTypes = ["*"]
    filter: dict = {}


class PatchWebhook(BaseModel):
    url: Url | None = None
    event_types: EventTypes | None = None
    filter: dict | None = None
    active: bool | None = None


def endpoint_json(ep: WebhookEndpoint) -> dict:
    return {"id": ep.id, "url": ep.url, "event_types": ep.event_types, "filter": ep.filter, "active": ep.active,
            "disabled_reason": ep.disabled_reason, "created_at": ep.created_at}


def delivery_json(d: WebhookDelivery, event_type: str | None) -> dict:
    return {"id": d.id, "endpoint_id": d.endpoint_id, "event_id": d.event_id, "event_type": event_type,
            "status": d.status, "attempts": d.attempts, "next_attempt_at": d.next_attempt_at,
            "response_status": d.response_status, "response_ms": d.response_ms,
            "response_body_excerpt": d.response_body_excerpt, "error": d.error, "replay_of": d.replay_of,
            "created_at": d.created_at}


def check_url(url: str) -> None:
    try:
        ssrf.target(url)
    except ssrf.Blocked as e:
        raise ApiError(422, "validation_failed", "The request is not valid", {"url": str(e)}) from None


def endpoint_or_404(c: Ctx, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    ep = c.db.get(WebhookEndpoint, endpoint_id)  # row level security: this workspace's endpoints only
    if ep is None:
        raise HTTPException(404, "Webhook not found")
    return ep


@router.post("", status_code=201)
def create_webhook(body: NewWebhook, c: Ctx = Depends(workspace_admin), idem: Idem = Depends(idempotency)):
    check_url(body.url)
    ep = WebhookEndpoint(workspace_id=c.workspace.id, url=body.url, event_types=body.event_types, filter=body.filter,
                         secret=f"whsec_{secrets.token_urlsafe(32)}", created_by=c.user_id)
    c.db.add(ep)
    c.db.flush()
    events.emit(c.db, "webhook_endpoint.created", "webhook_endpoint", ep.id,
                {k: v for k, v in endpoint_json(ep).items() if k in ("id", "event_types", "filter", "active")},
                actor=("user", c.user_id))
    return idem.commit(201, {**endpoint_json(ep), "secret": ep.secret})  # the only time the secret is shown


@router.get("")
def list_webhooks(limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(workspace_admin)):
    rows, next_cursor = paginate(c.db, select(WebhookEndpoint), WebhookEndpoint, limit, cursor)
    return {"data": [endpoint_json(row[0]) for row in rows], "next_cursor": next_cursor}


@router.get("/{endpoint_id}")
def get_webhook(endpoint_id: uuid.UUID, c: Ctx = Depends(workspace_admin)):
    return endpoint_json(endpoint_or_404(c, endpoint_id))


@router.patch("/{endpoint_id}")
def update_webhook(endpoint_id: uuid.UUID, body: PatchWebhook, c: Ctx = Depends(workspace_admin)):
    ep = endpoint_or_404(c, endpoint_id)
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "url" in changes:
        check_url(changes["url"])
    for name, value in changes.items():
        setattr(ep, name, value)
    if "url" in changes or changes.get("active"):  # a new target or a manual re-enable starts a clean record
        ep.failing_since = None
    if changes.get("active"):
        ep.disabled_reason = None
    c.db.commit()
    return endpoint_json(ep)


@router.delete("/{endpoint_id}", status_code=204)
def delete_webhook(endpoint_id: uuid.UUID, c: Ctx = Depends(workspace_admin)):
    c.db.delete(endpoint_or_404(c, endpoint_id))
    c.db.commit()


@router.post("/{endpoint_id}/test", status_code=202)
def send_test_event(endpoint_id: uuid.UUID, c: Ctx = Depends(workspace_admin), idem: Idem = Depends(idempotency)):
    """Emits `webhook.test`, which goes to this endpoint only. Follow it in the delivery log."""
    ep = endpoint_or_404(c, endpoint_id)
    if not ep.active:
        raise ApiError(409, "endpoint_disabled", "The webhook is disabled; enable it first")
    event = events.emit(c.db, "webhook.test", "webhook_endpoint", ep.id,
                        {"endpoint_id": ep.id, "message": "This is a test event from go-high."},
                        actor=("user", c.user_id))
    return idem.commit(202, {"event_id": event.id})


@router.get("/{endpoint_id}/deliveries")
def list_deliveries(endpoint_id: uuid.UUID, status: Literal["pending", "retrying", "succeeded", "failed"] | None = None,
                    limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
                    c: Ctx = Depends(workspace_admin)):
    endpoint_or_404(c, endpoint_id)
    stmt = (select(WebhookDelivery, Event.type).outerjoin(Event, Event.id == WebhookDelivery.event_id)
            .where(WebhookDelivery.endpoint_id == endpoint_id))
    if status:
        stmt = stmt.where(WebhookDelivery.status == status)
    rows, next_cursor = paginate(c.db, stmt, WebhookDelivery, limit, cursor)
    return {"data": [delivery_json(d, event_type) for d, event_type in rows], "next_cursor": next_cursor}


@router.post("/deliveries/{delivery_id}/replay", status_code=202)
def replay_delivery(delivery_id: uuid.UUID, c: Ctx = Depends(workspace_admin), idem: Idem = Depends(idempotency)):
    """A new delivery of the same event (same GoHigh-Event-Id, so receivers can dedupe), sent now."""
    old = c.db.get(WebhookDelivery, delivery_id)
    if old is None:
        raise HTTPException(404, "Delivery not found")
    if not c.db.get(WebhookEndpoint, old.endpoint_id).active:
        raise ApiError(409, "endpoint_disabled", "The webhook is disabled; enable it first")
    new = WebhookDelivery(workspace_id=old.workspace_id, endpoint_id=old.endpoint_id, event_id=old.event_id,
                          replay_of=old.id)
    c.db.add(new)
    c.db.flush()
    jobs.enqueue(c.db, "webhook.deliver", {"delivery_id": str(new.id)}, max_attempts=MAX_ATTEMPTS)
    return idem.commit(202, delivery_json(new, c.db.scalar(select(Event.type).where(Event.id == new.event_id))))


@events.consumer("webhooks")
def fan_out(db: Session, batch: list[Event]) -> None:
    """One delivery per active endpoint of the event's workspace that subscribes to its type, existed when the
    event happened, and whose filter the event data contains. `webhook.test` goes to the endpoint it names."""
    if not batch:
        return
    ep = WebhookEndpoint
    test = Event.type == "webhook.test"
    subscribed = or_(literal("*") == any_(ep.event_types), Event.type == any_(ep.event_types))
    match = (select(Event.workspace_id, ep.id, Event.id)
             .join(ep, and_(ep.workspace_id == Event.workspace_id, ep.active, ep.created_at <= Event.occurred_at,
                            or_(and_(test, Event.data["endpoint_id"].astext == cast(ep.id, String)),
                                and_(~test, subscribed, Event.data.contains(ep.filter)))))
             .where(Event.id.in_([e.id for e in batch])))
    created_ids = db.scalars(insert(WebhookDelivery).from_select(
        ["workspace_id", "endpoint_id", "event_id"], match, include_defaults=False).returning(WebhookDelivery.id)).all()
    for delivery_id in created_ids:
        jobs.enqueue(db, "webhook.deliver", {"delivery_id": str(delivery_id)}, max_attempts=MAX_ATTEMPTS)


class DeliveryFailed(Exception):
    """Raised after a failed attempt has been recorded, so the job queue retries with its backoff."""


def signature(secret: str, timestamp: int, body: str) -> str:
    return f"t={timestamp},v1={hmac.new(secret.encode(), f'{timestamp}.{body}'.encode(), hashlib.sha256).hexdigest()}"


def describe(error: Exception) -> str:
    return str(error) if isinstance(error, (ssrf.Blocked, TimeoutError)) else f"{type(error).__name__}: {error}"[:300]


# The attempt result is committed here, before raising, because the queue rolls back what a failed job did.
# Front-loaded so a receiver that blinked catches up within minutes; the 12 attempts span about 22 hours.
RETRY_MINUTES = (1, 2, 5, 10, 30, 60, 120, 180, 240, 300, 360)


def retry_delay(attempts: int) -> timedelta:
    return timedelta(minutes=RETRY_MINUTES[min(attempts, len(RETRY_MINUTES)) - 1])


# delivery.attempts counts sends; the job's own attempt count is only a backstop (same limit).
@jobs.handler("webhook.deliver", backoff=retry_delay)
def deliver(db: Session, payload: dict) -> None:
    d = db.get(WebhookDelivery, uuid.UUID(payload["delivery_id"]))
    if d is None or d.status in ("succeeded", "failed"):
        return  # deleted with its endpoint, or already finished
    ep, ev = db.get(WebhookEndpoint, d.endpoint_id), db.get(Event, d.event_id)
    d.attempts += 1
    d.next_attempt_at = None
    if ev is None or ev.workspace_id != d.workspace_id:
        d.status, d.error = "failed", "event not found"
    elif not ep.active:
        d.status, d.error = "failed", "webhook is disabled"
    if d.status == "failed":
        db.commit()
        return
    body = json.dumps(jsonable_encoder({
        "id": ev.id, "type": ev.type, "workspace_id": ev.workspace_id, "occurred_at": ev.occurred_at,
        "subject": {"type": ev.subject_type, "id": ev.subject_id}, "actor": {"type": ev.actor_type, "id": ev.actor_id},
        "data": ev.data}), separators=(",", ":"))
    headers = {"Content-Type": "application/json", "User-Agent": "go-high-webhooks/1", "GoHigh-Event-Id": str(ev.id),
               "GoHigh-Event-Type": ev.type, "GoHigh-Delivery-Id": str(d.id),
               "GoHigh-Signature": signature(ep.secret, int(time.time()), body)}
    started = time.monotonic()
    d.response_status = d.response_body_excerpt = d.error = None
    try:
        d.response_status, excerpt = ssrf.post(ep.url, body.encode(), headers, TIMEOUT)
        d.response_body_excerpt = excerpt.decode(errors="replace").replace("\x00", "")  # Postgres text has no NUL
    except Exception as e:
        d.error = describe(e)
    d.response_ms = round((time.monotonic() - started) * 1000)
    if d.error is None and 200 <= d.response_status < 300:
        d.status, ep.failing_since = "succeeded", None
        db.commit()
        return
    now = db.scalar(select(func.now()))
    ep.failing_since = ep.failing_since or now
    if now - ep.failing_since >= GIVE_UP:
        # ponytail: the workspace admins are told in the log until the email module exists.
        ep.active, ep.disabled_reason = False, "Disabled automatically after 3 days of failed deliveries"
        log.warning("webhook %s disabled after %s of failures; workspace %s admins should be emailed",
                    ep.id, GIVE_UP, ep.workspace_id)
    if d.attempts >= MAX_ATTEMPTS or not ep.active:
        d.status = "failed"
        db.commit()
        return
    d.status, d.next_attempt_at = "retrying", now + retry_delay(d.attempts)
    db.commit()
    raise DeliveryFailed(d.error or f"HTTP {d.response_status}")
