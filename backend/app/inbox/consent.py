"""Consent before every send (ADR 0005, module 14): who opted out of which channel, and the verdict
`compliance.can_send` gives for one message. STOP, unsubscribes and complaints are recorded by the inbound path;
staff can switch do not disturb on and off but can never undo an opt-out: only the contact's own START does."""
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import compliance, events
from ..api import ApiError
from ..records import store
from ..records.models import Record
from ..records.schema import Catalog
from ..security import Ctx, in_workspace
from .models import KINDS, Channel, Consent, Conversation, Message

router = APIRouter(prefix="/api/v1/contacts")
DEFAULT_CAP = {"sms": (10, 24), "whatsapp": (10, 24)}  # messages per hours; email and chat have none unless set


def clock() -> datetime:
    return datetime.now(UTC)


def get(db: Session, contact_id: uuid.UUID, kind: str) -> compliance.Consent | None:
    row = db.get(Consent, (contact_id, kind))
    return compliance.Consent(row.status, row.source, row.changed_at) if row else None


def record(db: Session, workspace_id: uuid.UUID, contact_id: uuid.UUID, kind: str, status: str, source: str,
           reason: str | None = None, actor: tuple[str, uuid.UUID] | None = None) -> bool:
    """Sets the contact's consent for a channel kind; emits `consent.changed` when it differs."""
    row = db.get(Consent, (contact_id, kind), with_for_update=True)
    if row is not None and row.status == status:
        return False
    if row is None:
        row = Consent(contact_id=contact_id, kind=kind, workspace_id=workspace_id)
        db.add(row)
    row.status, row.source, row.reason, row.changed_at = status, source, reason, datetime.now(UTC)
    db.flush()
    events.emit(db, "consent.changed", "record", contact_id,
                {"contact_id": contact_id, "kind": kind, "status": status, "source": source, "reason": reason},
                actor=actor, workspace_id=workspace_id)
    return True


def zones_of(contact: Record) -> tuple[str, ...]:
    """The contact's time zone: their `timezone` value when the workspace has that field, else the zones their phone
    number can be in."""
    zone = contact.values.get("timezone")
    if isinstance(zone, str) and zone:
        return (zone,)
    return compliance.phone_zones(contact.phone_e164) if contact.phone_e164 else ()


def cap_of(channel: Channel) -> tuple[int, int] | None:
    cap = channel.config.get("frequency_cap")
    return (int(cap["max"]), int(cap["hours"])) if isinstance(cap, dict) else DEFAULT_CAP.get(channel.kind)


def verdict(db: Session, channel: Channel, contact: Record, conv: Conversation | None,
            now: datetime | None = None, *, capped: bool = True) -> compliance.Refusal | None:
    """`compliance.can_send` for one message to `contact` on `channel`, with what the database knows."""
    now = now or clock()
    config = channel.config
    cap = cap_of(channel) if capped else None
    sent = 0
    if cap and conv:
        sent = db.scalar(select(func.count()).where(
            Message.conversation_id == conv.id, Message.channel_id == channel.id, Message.direction == "out",
            Message.kind == "message", Message.status != "failed", Message.created_at > now - timedelta(hours=cap[1])))
    replying = bool(conv and conv.last_inbound_at and now - conv.last_inbound_at < compliance.REPLY_WINDOW)
    return compliance.can_send(
        channel.kind, now, consent=get(db, contact.id, channel.kind), zones=zones_of(contact),
        quiet=(config.get("quiet_start", "21:00"), config.get("quiet_end", "08:00")), replying=replying,
        sent=sent, cap=cap)


def refuse(refusal: compliance.Refusal) -> ApiError:
    retry = {"retry_at": refusal.retry_at.isoformat()} if refusal.retry_at else None
    return ApiError(422, refusal.code, refusal.reason, retry)


class Dnd(BaseModel):
    dnd: bool


def consent_json(row: Consent) -> dict:
    return {"kind": row.kind, "status": row.status, "source": row.source, "reason": row.reason,
            "changed_at": row.changed_at}


def contact_or_404(c: Ctx, contact_id: uuid.UUID) -> Record:
    rec, obj = store.find(Catalog(c), contact_id)
    if obj.key != "contact":
        raise HTTPException(404, "Contact not found")
    return rec


@router.get("/{contact_id}/consents")
def list_consents(contact_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    contact_or_404(c, contact_id)
    rows = c.db.scalars(select(Consent).where(Consent.contact_id == contact_id).order_by(Consent.kind))
    return {"data": [consent_json(r) for r in rows]}


@router.put("/{contact_id}/consents/{kind}")
def set_dnd(contact_id: uuid.UUID, kind: str, body: Dnd, c: Ctx = Depends(in_workspace)):
    """Do not disturb on or off for one channel kind. An opt-out stays until the contact opts back in."""
    contact_or_404(c, contact_id)
    if kind not in KINDS:
        raise HTTPException(404, "Unknown channel kind")
    current = c.db.get(Consent, (contact_id, kind))
    if current is not None and current.status == "opted_out":
        raise ApiError(409, "opted_out", "The contact opted out; only they can opt back in, by replying START")
    actor = ("user", c.user_id)
    if body.dnd:
        record(c.db, c.workspace.id, contact_id, kind, "dnd", "manual", actor=actor)
    elif current is not None:
        c.db.execute(delete(Consent).where(Consent.contact_id == contact_id, Consent.kind == kind))
        events.emit(c.db, "consent.changed", "record", contact_id,
                    {"contact_id": contact_id, "kind": kind, "status": "none", "source": "manual", "reason": None},
                    actor=actor, workspace_id=c.workspace.id)
    c.db.commit()
    row = c.db.get(Consent, (contact_id, kind))
    return {"kind": kind, "status": row.status if row else "none"}
