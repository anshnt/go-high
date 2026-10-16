"""A record's timeline (ADR 0002): its events, newest first. Events whose subject is the record are found by
subject; events that touch several records (an association links two) are listed in `event_records` by whoever
emits them, with `link`. Notes, calls and messages will do the same, so one indexed query serves every module."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from ..api import ApiError, seal, unseal
from ..events import Event
from ..security import Ctx, in_workspace
from . import store
from .models import EventRecord
from .schema import Catalog

router = APIRouter(prefix="/api/v1")


def link(db: Session, event: Event, record_ids: list[uuid.UUID]) -> None:
    """Shows `event` on the timeline of each of these records, besides the record that is its subject."""
    db.add_all(EventRecord(event_id=event.id, record_id=r, workspace_id=event.workspace_id) for r in record_ids)
    db.flush()


def event_json(e: Event) -> dict:
    return {"id": e.id, "type": e.type, "occurred_at": e.occurred_at,
            "subject": {"type": e.subject_type, "id": e.subject_id},
            "actor": {"type": e.actor_type, "id": e.actor_id}, "data": e.data}


# ponytail: event data carries the record's values, so ADR 0004 must redact hidden fields here too.
@router.get("/records/{record_id}/timeline")
def timeline(record_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
             c: Ctx = Depends(in_workspace)):
    cat = Catalog(c)
    store.find(cat, record_id, trashed=None)  # a 404 unless the caller may see the record
    mine = select(Event.id).where(Event.workspace_id == c.workspace.id, Event.subject_id == record_id).union(
        select(EventRecord.event_id).where(EventRecord.record_id == record_id))
    stmt = select(Event).where(Event.workspace_id == c.workspace.id, Event.id.in_(mine))
    if cursor:
        try:
            at, last = unseal(cursor)
            stmt = stmt.where(tuple_(Event.occurred_at, Event.id) < tuple_(datetime.fromisoformat(at), int(last)))
        except (ValueError, TypeError):
            raise ApiError(400, "invalid_cursor", "The cursor is not valid") from None
    rows = c.db.scalars(stmt.order_by(Event.occurred_at.desc(), Event.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return {"data": [event_json(e) for e in page],
            "next_cursor": seal([page[-1].occurred_at.isoformat(), page[-1].id]) if len(rows) > limit else None}
