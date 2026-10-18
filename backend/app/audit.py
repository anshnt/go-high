"""The audit log (ADR 0004) is the event log: every write already emits an event in its own transaction, with the actor,
the subject and what changed, and request handlers can add to `events` but never change or delete a row of it (the
grants say so). This module is the reading side: `GET /api/v1/audit` filters by actor, subject, type and time range
and pages with a cursor, and `GET /api/v1/audit/export` is the same as CSV and records itself as `audit.exported`.
Both need `audit.read`, which is an administrator's capability: it shows the events of every record of the workspace
whatever a role's scope says, but fields the role hides are taken out of the event data.
ponytail: nothing archives old events yet (13 months hot, then cold storage, comes with the monthly partitions of ADR
0003) and viewing the log is not itself an event (`audit.viewed` in the ADR); add both when a customer asks."""
import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response
from sqlalchemy import select

from . import events, permissions
from .events import Event, newest_first
from .permissions import requires
from .records.models import EventRecord
from .records.schema import Catalog
from .records.timeline import event_json
from .security import Ctx

router = APIRouter(prefix="/api/v1/audit")
EXPORT_CAP = 50_000  # ponytail: rows in one export; a background job that mails the file when it needs more
COLUMNS = ("id", "occurred_at", "type", "subject_type", "subject_id", "actor_type", "actor_id", "data")


def utc(at: datetime | None) -> datetime | None:
    return at if at is None or at.tzinfo else at.replace(tzinfo=UTC)


def filters(actor: uuid.UUID | None = None, subject: uuid.UUID | None = None,
            type: Annotated[str | None, Query(pattern=r"^[a-z_]+\.([a-z_]+|\*)$")] = None,
            since: Annotated[datetime | None, Query(alias="from")] = None,
            until: Annotated[datetime | None, Query(alias="to")] = None) -> dict:
    """actor: who did it; subject: the record (or any other id) it happened to; type: `record.updated` or `record.*`;
    from and to: the time range, inclusive."""
    return {k: v for k, v in {"actor": actor, "subject": subject, "type": type, "from": utc(since),
                              "to": utc(until)}.items() if v is not None}


def select_events(c: Ctx, f: dict):
    stmt = select(Event).where(Event.workspace_id == c.workspace.id)
    if "actor" in f:
        stmt = stmt.where(Event.actor_id == f["actor"])
    if "subject" in f:  # events about it, and events that touch it among several records (a link)
        stmt = stmt.where(Event.id.in_(select(Event.id).where(Event.subject_id == f["subject"]).union(
            select(EventRecord.event_id).where(EventRecord.record_id == f["subject"]))))
    if "type" in f:
        stmt = (stmt.where(Event.type.startswith(f["type"].removesuffix("*"), autoescape=True))
                if f["type"].endswith("*") else stmt.where(Event.type == f["type"]))
    if "from" in f:
        stmt = stmt.where(Event.occurred_at >= f["from"])
    if "to" in f:
        stmt = stmt.where(Event.occurred_at <= f["to"])
    return stmt


def shown(c: Ctx, e: Event, cat: Catalog) -> dict:
    """The event data without the fields the caller's role hides (events about records name their object)."""
    key = e.data.get("object") if permissions.restricted(c) else None
    obj = cat.object(key) if isinstance(key, str) else None
    return permissions.redact_event(c, obj, e.data) if obj else e.data


@router.get("")
def list_audit(limit: int = Query(50, ge=1, le=200), cursor: str | None = None, f: dict = Depends(filters),
               c: Ctx = Depends(requires("audit.read"))):
    page, next_cursor = newest_first(c.db, select_events(c, f), limit, cursor)
    cat = Catalog(c)
    return {"data": [event_json(e, shown(c, e, cat)) for e in page], "next_cursor": next_cursor}


@router.get("/export")
def export_audit(f: dict = Depends(filters), c: Ctx = Depends(requires("audit.read"))):
    """Newest first, up to 50 000 events, as CSV with the data as a JSON cell. The export is itself an event."""
    rows = list(c.db.scalars(select_events(c, f).order_by(Event.occurred_at.desc(), Event.id.desc())
                             .limit(EXPORT_CAP + 1)))
    truncated, rows = len(rows) > EXPORT_CAP, rows[:EXPORT_CAP]
    cat, out = Catalog(c), io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    for e in rows:
        writer.writerow([e.id, e.occurred_at.isoformat(), e.type, e.subject_type, e.subject_id, e.actor_type,
                         e.actor_id or "", json.dumps(jsonable_encoder(shown(c, e, cat)), sort_keys=True)])
    events.emit(c.db, "audit.exported", "workspace", c.workspace.id,
                {"rows": len(rows), "truncated": truncated, "filters": jsonable_encoder(f)}, actor=("user", c.user_id))
    c.db.commit()
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="audit.csv"'})
