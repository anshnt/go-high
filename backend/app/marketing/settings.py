"""The workspace's email settings (footer and tracking), subscription topics and the suppression list (module 20).

The suppression list is every address the workspace never mails again: hard bounces and complaints arrive from the
provider, unsubscribes from the links in each mail, and staff add addresses by hand. Staff can take an address off
the list when they added it or when it bounced (the address may have been fixed), never when its owner complained or
unsubscribed: only the person can undo that, from the preference page."""
import uuid
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .. import events, permissions
from ..api import ApiError, Idem, idempotency, paginate
from ..permissions import requires
from ..records.schema import Catalog
from ..security import Ctx
from .models import EmailSettings, EmailSuppression, EmailTopic

router = APIRouter(prefix="/api/v1/email")
read, manage = requires("marketing.read"), requires("marketing.manage")
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
STAFF_REMOVABLE = ("manual", "hard_bounce")


class SettingsBody(BaseModel):
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    postal_address: Text = ""
    track_opens: bool = True
    track_clicks: bool = True


class NewTopic(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""


class PatchTopic(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None
    archived: bool | None = None


class NewSuppression(BaseModel):
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)]
    detail: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] | None = None


def settings_of(db: Session, workspace_id: uuid.UUID) -> EmailSettings:
    """The workspace's settings, or the defaults (not stored until someone saves them)."""
    return db.get(EmailSettings, workspace_id) or EmailSettings(workspace_id=workspace_id, company_name="",
                                                                 postal_address="", track_opens=True,
                                                                 track_clicks=True)


def settings_json(s: EmailSettings) -> dict:
    return {"company_name": s.company_name, "postal_address": s.postal_address, "track_opens": s.track_opens,
            "track_clicks": s.track_clicks}


@router.get("/settings")
def get_settings(c: Ctx = Depends(read)):
    return settings_json(settings_of(c.db, c.workspace.id))


@router.put("/settings")
def put_settings(body: SettingsBody, c: Ctx = Depends(manage)):
    row = c.db.get(EmailSettings, c.workspace.id)
    before = settings_json(row) if row else None
    if row is None:
        row = EmailSettings(workspace_id=c.workspace.id)
        c.db.add(row)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    row.updated_at = func.now()
    c.db.flush()
    after = settings_json(row)
    if after != before:
        events.emit(c.db, "email_settings.updated", "workspace", c.workspace.id,
                    {"changes": events.changes(before or {}, after)}, actor=("user", c.user_id))
    c.db.commit()
    return after


# --- topics -----------------------------------------------------------------------------------------------------

def topic_json(t: EmailTopic) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description, "archived": t.archived_at is not None,
            "created_at": t.created_at}


def topic_or_404(c: Ctx, topic_id: uuid.UUID) -> EmailTopic:
    t = c.db.get(EmailTopic, topic_id)
    if t is None:
        raise HTTPException(404, "Topic not found")
    return t


def name_taken(c: Ctx, name: str, but: uuid.UUID | None = None) -> None:
    clash = select(exists().where(func.lower(EmailTopic.name) == name.lower(), EmailTopic.id != but)) if but else \
        select(exists().where(func.lower(EmailTopic.name) == name.lower()))
    if c.db.scalar(clash):
        raise ApiError(409, "conflict", "There is already a topic of that name", {"name": "is already used"})


@router.get("/topics")
def list_topics(archived: bool = False, c: Ctx = Depends(read)):
    stmt = select(EmailTopic).order_by(EmailTopic.name)
    if not archived:
        stmt = stmt.where(EmailTopic.archived_at.is_(None))
    return {"data": [topic_json(t) for t in c.db.scalars(stmt)]}


@router.post("/topics", status_code=201)
def create_topic(body: NewTopic, c: Ctx = Depends(manage), idem: Idem = Depends(idempotency)):
    name_taken(c, body.name)
    t = EmailTopic(workspace_id=c.workspace.id, name=body.name, description=body.description)
    c.db.add(t)
    c.db.flush()
    c.db.refresh(t, ["created_at"])
    events.emit(c.db, "email_topic.created", "email_topic", t.id, {"id": t.id, "name": t.name},
                actor=("user", c.user_id))
    return idem.commit(201, topic_json(t))


@router.patch("/topics/{topic_id}")
def update_topic(topic_id: uuid.UUID, body: PatchTopic, c: Ctx = Depends(manage)):
    t = topic_or_404(c, topic_id)
    before = topic_json(t)
    if body.name is not None and body.name != t.name:
        name_taken(c, body.name, t.id)
        t.name = body.name
    if body.description is not None:
        t.description = body.description
    if body.archived is not None and body.archived != (t.archived_at is not None):
        t.archived_at = datetime.now(UTC) if body.archived else None
    after = topic_json(t)
    if changes := {k: v for k, v in events.changes(before, after).items() if k != "created_at"}:
        events.emit(c.db, "email_topic.updated", "email_topic", t.id, {"id": t.id, "name": t.name, "changes": changes},
                    actor=("user", c.user_id))
    c.db.commit()
    return after


# --- suppressions -----------------------------------------------------------------------------------------------

def normal_email(raw: str) -> str | None:
    address = parseaddr(raw)[1].strip().lower()
    return address if "@" in address and "." in address.rpartition("@")[2] and len(address) <= 320 else None


def suppress(db: Session, workspace_id: uuid.UUID, email: str, reason: str, detail: str | None = None,
             campaign_id: uuid.UUID | None = None, actor: tuple[str, uuid.UUID] | None = None) -> bool:
    """Puts an address on the list (once: an address already there keeps its first reason). True when it is new."""
    email = email.strip().lower()
    row = db.execute(insert(EmailSuppression).values(
        workspace_id=workspace_id, email=email, reason=reason, detail=(detail or "")[:300] or None,
        campaign_id=campaign_id, created_by=actor[1] if actor and actor[0] == "user" else None)
        .on_conflict_do_nothing(index_elements=["workspace_id", "email"]).returning(EmailSuppression.id)).scalar()
    if row is None:
        return False
    events.emit(db, "email_suppression.added", "email_suppression", row,
                {"id": row, "email": email, "reason": reason, "detail": detail, "campaign_id": campaign_id},
                actor=actor, workspace_id=workspace_id)
    return True


def suppressed(db: Session, email: str) -> str | None:
    """Why the address is on the list, or None."""
    return db.scalar(select(EmailSuppression.reason).where(EmailSuppression.email == email.strip().lower()))


def masked(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}\u2026@{domain}"


def hides_emails(c: Ctx) -> bool:
    """A role that may not read contacts' addresses sees the list masked (m\u2026@example.net)."""
    obj = Catalog(c).object("contact")
    return obj is not None and "email" in permissions.hidden(c, obj)


def suppression_json(s: EmailSuppression, mask: bool = False) -> dict:
    return {"id": s.id, "email": masked(s.email) if mask else s.email, "reason": s.reason, "detail": s.detail,
            "campaign_id": s.campaign_id,
            "created_by": s.created_by, "created_at": s.created_at, "removable": s.reason in STAFF_REMOVABLE}


@router.get("/suppressions")
def list_suppressions(q: Annotated[str, StringConstraints(max_length=320)] | None = None,
                      reason: Literal["hard_bounce", "complaint", "unsubscribe", "manual"] | None = None,
                      limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(read)):
    stmt = select(EmailSuppression)
    if q:
        stmt = stmt.where(EmailSuppression.email.contains(q.strip().lower(), autoescape=True))
    if reason:
        stmt = stmt.where(EmailSuppression.reason == reason)
    rows, next_cursor = paginate(c.db, stmt, EmailSuppression, limit, cursor)
    counts = dict(c.db.execute(select(EmailSuppression.reason, func.count()).group_by(EmailSuppression.reason)).all())
    mask = hides_emails(c)
    return {"data": [suppression_json(s, mask) for (s,) in rows], "next_cursor": next_cursor, "counts": counts}


@router.post("/suppressions", status_code=201)
def add_suppression(body: NewSuppression, c: Ctx = Depends(manage), idem: Idem = Depends(idempotency)):
    email = normal_email(body.email)
    if email is None:
        raise ApiError(422, "validation_failed", "The address is not valid", {"email": "must be an email address"})
    if not suppress(c.db, c.workspace.id, email, "manual", body.detail, actor=("user", c.user_id)):
        raise ApiError(409, "conflict", f"{email} is already on the list", {"email": "is already suppressed"})
    row = c.db.scalar(select(EmailSuppression).where(EmailSuppression.email == email))
    return idem.commit(201, suppression_json(row))


@router.delete("/suppressions/{suppression_id}", status_code=204)
def remove_suppression(suppression_id: uuid.UUID, c: Ctx = Depends(manage)):
    row = c.db.get(EmailSuppression, suppression_id)
    if row is None:
        raise HTTPException(404, "Suppression not found")
    if row.reason not in STAFF_REMOVABLE:
        why = "complained" if row.reason == "complaint" else "unsubscribed"
        raise ApiError(409, "not_removable", f"{row.email} {why}: only they can opt back in, from the preference page")
    events.emit(c.db, "email_suppression.removed", "email_suppression", row.id,
                {"id": row.id, "email": row.email, "reason": row.reason}, actor=("user", c.user_id))
    c.db.delete(row)
    c.db.commit()
