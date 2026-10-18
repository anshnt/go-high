"""A record's timeline (ADR 0002): its events, newest first. Events whose subject is the record are found by
subject; events that touch several records (an association links two) are listed in `event_records` by whoever
emits them, with `link`. Notes, calls and messages will do the same, so one indexed query serves every module."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import permissions
from ..events import Event, newest_first
from ..permissions import requires_records
from ..security import Ctx
from . import store
from .models import EventRecord
from .schema import Catalog

router = APIRouter(prefix="/api/v1")


def link(db: Session, event: Event, record_ids: list[uuid.UUID]) -> None:
    """Shows `event` on the timeline of each of these records, besides the record that is its subject."""
    db.add_all(EventRecord(event_id=event.id, record_id=r, workspace_id=event.workspace_id) for r in record_ids)
    db.flush()


def event_json(e: Event, data: dict | None = None) -> dict:
    return {"id": e.id, "type": e.type, "occurred_at": e.occurred_at,
            "subject": {"type": e.subject_type, "id": e.subject_id},
            "actor": {"type": e.actor_type, "id": e.actor_id}, "data": e.data if data is None else data}


@router.get("/records/{record_id}/timeline")
def timeline(record_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
             c: Ctx = Depends(requires_records("read"))):
    """The events carry the record's values, so a role that hides fields gets them without those fields."""
    cat = Catalog(c)
    _, obj = store.find(cat, record_id, trashed=None)  # a 404 unless the caller may see the record
    mine = select(Event.id).where(Event.workspace_id == c.workspace.id, Event.subject_id == record_id).union(
        select(EventRecord.event_id).where(EventRecord.record_id == record_id))
    stmt = select(Event).where(Event.workspace_id == c.workspace.id, Event.id.in_(mine))
    page, next_cursor = newest_first(c.db, stmt, limit, cursor)
    return {"data": [event_json(e, permissions.redact_event(c, obj, e.data)) for e in page],
            "next_cursor": next_cursor}
