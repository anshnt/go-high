"""Notifications API: /api/v1/notifications. The caller's own notifications (row level security lets nobody else's
through), the unread count, marking read, and the per-kind preferences. A notification shows from its `created_at`;
one held by quiet hours is dated at the end of them and is not listed, counted or marked before that."""
import uuid
from datetime import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..api import ApiError, paginate
from ..security import Ctx, in_workspace
from ..tasks.store import zone
from .consumer import KINDS
from .models import Notification, NotificationPref

router = APIRouter(prefix="/api/v1/notifications")
Kind = Literal[tuple(KINDS)]


class Read(BaseModel):
    ids: Annotated[list[uuid.UUID], Field(max_length=200)] = []
    all: bool = False

    @model_validator(mode="after")
    def one_of_them(self):
        if bool(self.ids) == self.all:
            raise ValueError("send ids or all=true, not both and not neither")
        return self


class PrefIn(BaseModel):
    kind: Kind
    channels: list[Literal["in_app", "email"]] = ["in_app"]
    scope: Literal["all", "mine"] = "mine"
    quiet_start: time | None = None
    quiet_end: time | None = None
    tz: Annotated[str, Field(max_length=64)] | None = None
    digest: Literal["daily", "off"] = "off"

    @model_validator(mode="after")
    def quiet_hours_are_whole(self):
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("quiet_start and quiet_end go together")
        zone(self.tz)  # quiet hours are read in the person's zone: it must exist
        return self


class Prefs(BaseModel):
    prefs: Annotated[list[PrefIn], Field(min_length=1, max_length=len(KINDS))]


def mine(c: Ctx):
    """The caller's notifications that have shown up by now."""
    return (Notification.workspace_id == c.workspace.id, Notification.user_id == c.user_id,
            Notification.created_at <= func.now())


def notification_json(n: Notification) -> dict:
    return {"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link,
            "subject": {"type": n.subject_type, "id": n.subject_id} if n.subject_type else None,
            "created_at": n.created_at, "read_at": n.read_at}


@router.get("")
def list_notifications(unread: bool = False, limit: int = Query(30, ge=1, le=200), cursor: str | None = None,
                       c: Ctx = Depends(in_workspace)):
    stmt = select(Notification).where(*mine(c))
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows, next_cursor = paginate(c.db, stmt, Notification, limit, cursor)
    return {"data": [notification_json(n) for (n,) in rows], "next_cursor": next_cursor}


@router.get("/unread-count")
def unread_count(c: Ctx = Depends(in_workspace)):
    return {"count": c.db.scalar(select(func.count()).select_from(Notification).where(
        *mine(c), Notification.read_at.is_(None)))}


@router.post("/read")
def mark_read(body: Read, c: Ctx = Depends(in_workspace)):
    """Marks some of the caller's notifications (`ids`) or all of them (`all`) read; `updated` is how many changed."""
    stmt = update(Notification).where(*mine(c), Notification.read_at.is_(None)).values(read_at=func.now())
    if body.ids:
        stmt = stmt.where(Notification.id.in_(body.ids))
    done = c.db.execute(stmt.returning(Notification.id)).all()
    c.db.commit()
    return {"updated": len(done)}


def hhmm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def prefs_json(c: Ctx) -> dict:
    saved = {p.kind: p for p in c.db.scalars(select(NotificationPref).where(
        NotificationPref.workspace_id == c.workspace.id, NotificationPref.user_id == c.user_id))}

    def one(kind: str, label: str) -> dict:
        p = saved.get(kind)
        return {"kind": kind, "label": label, "channels": p.channels if p else ["in_app"],
                "scope": p.scope if p else "mine", "quiet_start": hhmm(p and p.quiet_start),
                "quiet_end": hhmm(p and p.quiet_end), "tz": p.tz if p else None, "digest": p.digest if p else "off"}
    return {"data": [one(kind, label) for kind, label in KINDS.items()]}


@router.get("/prefs")
def get_prefs(c: Ctx = Depends(in_workspace)):
    """One entry per kind, with the default for a kind that was never saved. `email` and `digest` are kept for the
    email module; nothing is sent by email yet."""
    return prefs_json(c)


@router.put("/prefs")
def put_prefs(body: Prefs, c: Ctx = Depends(in_workspace)):
    """Saves the entries sent (each kind at most once); kinds not sent keep what they had."""
    kinds = [p.kind for p in body.prefs]
    if len(set(kinds)) != len(kinds):
        raise ApiError(422, "validation_failed", "The request is not valid", {"prefs": "each kind may appear once"})
    rows = [{"user_id": c.user_id, "workspace_id": c.workspace.id, **p.model_dump()} for p in body.prefs]
    insert = pg_insert(NotificationPref).values(rows)
    c.db.execute(insert.on_conflict_do_update(
        index_elements=["user_id", "workspace_id", "kind"],
        set_={k: insert.excluded[k] for k in ("channels", "scope", "quiet_start", "quiet_end", "tz", "digest")}))
    c.db.commit()
    return prefs_json(c)
