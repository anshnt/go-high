"""Working hours and busy time (module 16). A person's hours are a week in their own time zone plus dates that replace
the week (a day off, or short hours); rooms and equipment can have hours too. People change their own hours with
`calendars.write`; hours of someone else or of a resource are `calendars.manage`. `POST /availability/busy` is where
an outside calendar's busy times arrive: the sync that fills it later (a push from Google or Microsoft) calls it.
ponytail: no live sync yet. Busy blocks come in by this route, replaced a range at a time; the push-based sync (watch
channels, renewal and a health badge that goes red on a failed renewal) is the next slice and only needs to call it."""
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .. import events, permissions
from ..api import ApiError
from ..permissions import requires
from ..records.store import member_ids
from ..security import Ctx
from . import schemas, slots
from .models import Availability, BusyBlock, Resource
from .routes import DEFAULT_WEEKLY, invalid

router = APIRouter(prefix="/api/v1/availability")
STALE = timedelta(hours=24)  # a sync that last reported longer ago than this shows as stale
MAX_BLOCKS = 2000


class Hours(BaseModel):
    time_zone: schemas.Zone
    weekly: dict

    @field_validator("weekly")
    @classmethod
    def week(cls, value):
        return slots.clean_weekly(value)


class Day(BaseModel):
    hours: list  # [] marks the day off; otherwise the ranges that replace the weekly ones that day

    @field_validator("hours")
    @classmethod
    def ranges(cls, value):
        return slots.clean_ranges(value)


class Block(BaseModel):
    start: AwareDatetime
    end: AwareDatetime
    external_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None

    @field_validator("end")
    @classmethod
    def after(cls, end, info):
        if "start" in info.data and end <= info.data["start"]:
            raise ValueError("must be after start")
        return end


class Busy(BaseModel):
    user_id: uuid.UUID | None = None  # default: you
    source: Annotated[str, Field(min_length=1, max_length=30, pattern=r"^[a-z0-9_]+$")] = "sync"
    blocks: Annotated[list[Block], Field(max_length=MAX_BLOCKS)]
    replace_from: AwareDatetime | None = None  # delete this person's blocks of this source in the range first
    replace_to: AwareDatetime | None = None
    status: Literal["ok", "error"] = "ok"  # how the sync that sent this went
    error: Annotated[str, Field(max_length=300)] | None = None


def sync_json(row: Availability | None, now: datetime) -> dict:
    """The sync health of a person: `none` until something has been imported, `stale` when the last good report is
    old, `error` when the last one failed."""
    if row is None or row.sync_status == "none":
        return {"status": "none", "synced_at": None, "error": None}
    status = "stale" if row.sync_status == "ok" and row.synced_at and now - row.synced_at > STALE else row.sync_status
    return {"status": status, "synced_at": row.synced_at, "error": row.sync_error}


def availability_json(owner: str, owner_id: uuid.UUID, row: Availability | None, now: datetime) -> dict:
    """A row that only carries sync health (its week is empty, not seven empty days) reads like no row: the usual week
    and `saved: false`."""
    saved = row is not None and bool(row.weekly)
    return {"owner": owner, "id": owner_id, "saved": saved, "time_zone": row.time_zone if row else "UTC",
            "weekly": row.weekly if saved else DEFAULT_WEEKLY, "overrides": row.overrides if row else {},
            "sync": sync_json(row, now) if owner == "users" else None, "updated_at": row.updated_at if row else None}


def row_for(c: Ctx, owner: str, owner_id: uuid.UUID, *, lock: bool = False) -> Availability | None:
    column = Availability.user_id if owner == "users" else Availability.resource_id
    stmt = select(Availability).where(column == owner_id)
    return c.db.scalar(stmt.with_for_update() if lock else stmt)


def check_owner(c: Ctx, owner: str, owner_id: uuid.UUID, *, change: bool) -> None:
    """The person must be of this workspace and the resource exist; changing someone else's hours, or a resource's,
    needs `calendars.manage`."""
    if owner == "users":
        if str(owner_id) not in member_ids(c, {str(owner_id)}):
            raise ApiError(404, "not_found", "Member not found")
        if change and owner_id != c.user_id and "calendars.manage" not in permissions.grants(c).capabilities:
            raise ApiError(403, "forbidden", "You can change your own hours; someone else's are for calendar managers")
    else:
        if c.db.get(Resource, owner_id) is None:
            raise ApiError(404, "not_found", "Resource not found")
        if change:
            permissions.require(c, "calendars.manage")


def announce(c: Ctx, owner: str, owner_id: uuid.UUID, what: str) -> None:
    events.emit(c.db, "availability.updated", "availability", owner_id,
                {"owner": owner, "id": owner_id, "change": what}, actor=("user", c.user_id))


def now() -> datetime:
    return datetime.now(UTC)


@router.post("/busy")
def import_busy(body: Busy, c: Ctx = Depends(requires("calendars.write"))):
    """Sets a person's busy time from an outside calendar. Blocks with an `external_id` update the one already stored
    under it; with `replace_from` and `replace_to`, the person's blocks of this source in that range go first, so a
    full re-read of the range leaves exactly what it sent. The sync health of the person is updated."""
    owner_id = body.user_id or c.user_id
    check_owner(c, "users", owner_id, change=True)
    if (body.replace_from is None) != (body.replace_to is None):
        raise invalid({"replace_from": "send replace_from and replace_to together"})
    if body.replace_from:
        c.db.execute(delete(BusyBlock).where(
            BusyBlock.user_id == owner_id, BusyBlock.source == body.source, BusyBlock.starts_at < body.replace_to,
            BusyBlock.ends_at > body.replace_from))
    plain = [{"workspace_id": c.workspace.id, "user_id": owner_id, "starts_at": b.start, "ends_at": b.end,
              "source": body.source} for b in body.blocks if not b.external_id]
    known = {b.external_id: b for b in body.blocks if b.external_id}.values()  # the last of a repeated id wins
    if plain:
        c.db.execute(pg_insert(BusyBlock), plain)
    for b in known:
        insert = pg_insert(BusyBlock).values(workspace_id=c.workspace.id, user_id=owner_id, starts_at=b.start,
                                             ends_at=b.end, source=body.source, external_id=b.external_id)
        c.db.execute(insert.on_conflict_do_update(
            index_elements=[BusyBlock.user_id, BusyBlock.source, BusyBlock.external_id],
            index_where=BusyBlock.external_id.is_not(None),
            set_={"starts_at": insert.excluded.starts_at, "ends_at": insert.excluded.ends_at}))
    row = row_for(c, "users", owner_id, lock=True)
    if row is None:  # no hours yet: the row only carries the sync health
        row = Availability(workspace_id=c.workspace.id, user_id=owner_id)
        c.db.add(row)
    row.sync_status, row.synced_at = body.status, now()
    row.sync_error = body.error if body.status == "error" else None
    c.db.flush()
    announce(c, "users", owner_id, "busy")
    c.db.commit()
    return {"imported": len(body.blocks), "sync": sync_json(row, now())}


@router.get("/{owner}/{owner_id}")
def get_availability(owner: Literal["users", "resources"], owner_id: uuid.UUID,
                     c: Ctx = Depends(requires("calendars.read"))):
    """Hours as saved, or the usual week (Monday to Friday, 9 to 5, `saved: false`) for someone who has none yet."""
    check_owner(c, owner, owner_id, change=False)
    return availability_json(owner, owner_id, row_for(c, owner, owner_id), now())


@router.put("/{owner}/{owner_id}")
def put_availability(owner: Literal["users", "resources"], owner_id: uuid.UUID, body: Hours,
                     c: Ctx = Depends(requires("calendars.write"))):
    """Sets the week and the zone it is read in; the dates that replace the week are left as they are."""
    check_owner(c, owner, owner_id, change=True)
    row = row_for(c, owner, owner_id, lock=True)
    if row is None:
        row = Availability(workspace_id=c.workspace.id, user_id=owner_id if owner == "users" else None,
                           resource_id=owner_id if owner == "resources" else None)
        c.db.add(row)
    row.time_zone, row.weekly, row.updated_at = body.time_zone, body.weekly, now()
    c.db.flush()
    announce(c, owner, owner_id, "weekly")
    c.db.commit()
    return availability_json(owner, owner_id, row, now())


def day_key(day: date) -> str:
    return day.isoformat()


@router.put("/{owner}/{owner_id}/overrides/{day}")
def put_override(owner: Literal["users", "resources"], owner_id: uuid.UUID, day: date, body: Day,
                 c: Ctx = Depends(requires("calendars.write"))):
    """Replaces the hours of one date: `{"hours": []}` is a day off, `{"hours": [["09:00", "12:00"]]}` short hours."""
    check_owner(c, owner, owner_id, change=True)
    row = row_for(c, owner, owner_id, lock=True)
    if row is None:
        row = Availability(workspace_id=c.workspace.id, user_id=owner_id if owner == "users" else None,
                           resource_id=owner_id if owner == "resources" else None, weekly=DEFAULT_WEEKLY)
        c.db.add(row)
    row.overrides, row.updated_at = {**row.overrides, day_key(day): body.hours}, now()
    c.db.flush()
    announce(c, owner, owner_id, f"override {day_key(day)}")
    c.db.commit()
    return availability_json(owner, owner_id, row, now())


@router.delete("/{owner}/{owner_id}/overrides/{day}")
def delete_override(owner: Literal["users", "resources"], owner_id: uuid.UUID, day: date,
                    c: Ctx = Depends(requires("calendars.write"))):
    """Puts a date back to the week's hours."""
    check_owner(c, owner, owner_id, change=True)
    row = row_for(c, owner, owner_id, lock=True)
    if row is None or day_key(day) not in row.overrides:
        raise ApiError(404, "not_found", "No hours were set for that date")
    row.overrides = {k: v for k, v in row.overrides.items() if k != day_key(day)}
    row.updated_at = now()
    c.db.flush()
    announce(c, owner, owner_id, f"override {day_key(day)} removed")
    c.db.commit()
    return availability_json(owner, owner_id, row, now())
