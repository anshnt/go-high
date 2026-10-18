"""Bookings API for the people who run the calendars (module 16): list by range, host, calendar, contact and status, and
cancel, move, confirm or mark showed and no-show. Reading is `calendars.read`, changing is `calendars.write`. Visitors
make and change bookings through the public routes (public.py), which share this logic (booking.py)."""
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select, tuple_

from ..api import ApiError, seal, unseal
from ..models import User
from ..permissions import requires
from ..security import Ctx
from . import booking, contacts
from .models import BOOKING_STATUSES, Booking, Calendar
from .routes import invalid

router = APIRouter(prefix="/api/v1/bookings")
read, write = requires("calendars.read"), requires("calendars.write")


class Cancel(BaseModel):
    reason: Annotated[str, Field(max_length=500)] | None = None


class Move(BaseModel):
    start: AwareDatetime
    time_zone: str | None = None


class Mark(BaseModel):
    status: Literal["confirmed", "showed", "no_show"]


def now() -> datetime:
    return datetime.now(UTC)


def bookings_json(c: Ctx, rows: list[tuple[Booking, Calendar]]) -> list[dict]:
    """The bookings as the caller may see them: a contact only when it is one the caller may read."""
    people = {i for b, _ in rows for i in b.host_ids}
    names = dict(c.db.execute(select(User.id, User.name).where(User.id.in_(people))).all()) if people else {}
    seen = contacts.visible(c, {b.contact_id for b, _ in rows if b.contact_id})
    return [{
        "id": b.id, "status": b.status, "starts_at": b.starts_at, "ends_at": b.ends_at, "time_zone": b.time_zone,
        "calendar": {"id": cal.id, "name": cal.name, "kind": cal.kind, "color": cal.color},
        "host": {"user_id": b.host_user_id, "name": names.get(b.host_user_id)},
        "hosts": [{"user_id": i, "name": names.get(i)} for i in b.host_ids],
        "contact": {"id": b.contact_id, "display_name": seen[b.contact_id]} if b.contact_id in seen else None,
        "invitee": {"name": b.invitee_name, "email": b.invitee_email, "phone": b.invitee_phone},
        "location": b.location, "answers": b.answers, "source": b.source, "series_id": b.series_id,
        "reschedules": b.reschedules, "cancelled_at": b.cancelled_at, "cancel_reason": b.cancel_reason,
        "created_at": b.created_at, "updated_at": b.updated_at} for b, cal in rows]


def booking_or_404(c: Ctx, booking_id: uuid.UUID, *, lock: bool = False) -> tuple[Booking, Calendar]:
    stmt = select(Booking, Calendar).join(Calendar, Calendar.id == Booking.calendar_id).where(Booking.id == booking_id)
    row = c.db.execute(stmt.with_for_update(of=Booking) if lock else stmt).first()
    if row is None:
        raise ApiError(404, "not_found", "Booking not found")
    return row[0], row[1]


@router.get("")
def list_bookings(from_: Annotated[AwareDatetime | None, Query(alias="from")] = None, to: AwareDatetime | None = None,
                  host_id: uuid.UUID | None = None, calendar_id: uuid.UUID | None = None,
                  contact_id: uuid.UUID | None = None, status: str | None = None,
                  order: Literal["asc", "desc"] = "asc", limit: int = Query(200, ge=1, le=500),
                  cursor: str | None = None, c: Ctx = Depends(read)):
    """Bookings that overlap [from, to), by start time (`order=desc` for newest first). `status` is a comma separated
    list. The cursor is signed."""
    stmt = select(Booking, Calendar).join(Calendar, Calendar.id == Booking.calendar_id)
    if from_:
        stmt = stmt.where(Booking.ends_at > from_)
    if to:
        stmt = stmt.where(Booking.starts_at < to)
    if host_id:
        stmt = stmt.where(Booking.host_ids.contains([host_id]))
    if calendar_id:
        stmt = stmt.where(Booking.calendar_id == calendar_id)
    if contact_id:
        stmt = stmt.where(Booking.contact_id == contact_id)
    if status:
        wanted = [s for s in status.split(",") if s]
        if bad := [s for s in wanted if s not in BOOKING_STATUSES]:
            raise invalid({"status": f"unknown: {', '.join(bad)}"})
        stmt = stmt.where(Booking.status.in_(wanted))
    key = tuple_(Booking.starts_at, Booking.id)
    if cursor:
        try:
            at, last = unseal(cursor)
            point = tuple_(datetime.fromisoformat(at), uuid.UUID(last))
        except (ValueError, TypeError):
            raise ApiError(400, "invalid_cursor", "The cursor is not valid") from None
        stmt = stmt.where(key > point if order == "asc" else key < point)
    stmt = stmt.order_by(*(col.asc() if order == "asc" else col.desc() for col in (Booking.starts_at, Booking.id)))
    rows = [(b, cal) for b, cal in c.db.execute(stmt.limit(limit + 1))]
    page = rows[:limit]
    more = seal([page[-1][0].starts_at.isoformat(), str(page[-1][0].id)]) if len(rows) > limit else None
    return {"data": bookings_json(c, page), "next_cursor": more}


@router.get("/{booking_id}")
def get_booking(booking_id: uuid.UUID, c: Ctx = Depends(read)):
    return bookings_json(c, [booking_or_404(c, booking_id)])[0]


@router.post("/{booking_id}/cancel")
def cancel_booking(booking_id: uuid.UUID, body: Cancel, c: Ctx = Depends(write)):
    b, cal = booking_or_404(c, booking_id, lock=True)
    booking.cancel(c, b, cal, body.reason, now())
    c.db.commit()
    return bookings_json(c, [(b, cal)])[0]


@router.post("/{booking_id}/reschedule")
def reschedule_booking(booking_id: uuid.UUID, body: Move, c: Ctx = Depends(write)):
    """Moves a booking to another open time with the same host. 409 when the time is not open."""
    b, cal = booking_or_404(c, booking_id, lock=True)
    if b.status in ("cancelled", "showed", "no_show"):
        raise ApiError(409, "conflict", f"A {b.status.replace('_', ' ')} booking cannot be moved")
    booking.reschedule(c, b, cal, start=body.start.astimezone(UTC), time_zone=body.time_zone or b.time_zone, now=now())
    c.db.commit()
    return bookings_json(c, [(b, cal)])[0]


@router.post("/{booking_id}/status")
def mark_booking(booking_id: uuid.UUID, body: Mark, c: Ctx = Depends(write)):
    """Confirms a booking that waits for it, or records whether the invitee came (showed, no_show)."""
    b, cal = booking_or_404(c, booking_id, lock=True)
    booking.set_status(c, b, cal, body.status, now())
    c.db.commit()
    return bookings_json(c, [(b, cal)])[0]
