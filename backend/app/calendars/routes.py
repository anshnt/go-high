"""Calendars API (module 16): calendars with their hosts and resources, the open times they offer, why a time is hidden,
and the round robin preview. Reading is `calendars.read`; creating and changing calendars, hosts and resources is
`calendars.manage`. Bookings are in bookings.py, hours and busy time in availability.py."""
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .. import config, events
from ..api import ApiError, Idem, idempotency
from ..models import User
from ..permissions import requires
from ..records.models import Record
from ..records.store import member_ids
from ..security import Ctx
from . import booking, days, routing, schemas, slots
from .models import (
    Availability,
    Booking,
    Calendar,
    CalendarHost,
    CalendarResource,
    FeedToken,
    Resource,
)

router = APIRouter(prefix="/api/v1")
read, write, manage = requires("calendars.read"), requires("calendars.write"), requires("calendars.manage")
SETTINGS = ("name", "slug", "description", "kind", "durations", "buffer_before", "buffer_after", "min_notice",
            "window_days", "slot_interval", "max_per_day", "seats", "time_zone", "confirmation", "color", "status",
            "reminders", "cutoff_hours")
ONE_HOST = ("personal", "class")  # kinds with a single host
DEFAULT_WEEKLY = {day: ([["09:00", "17:00"]] if i < 5 else []) for i, day in enumerate(slots.WEEKDAYS)}


def invalid(fields: dict[str, str], message: str = "The request is not valid") -> ApiError:
    return ApiError(422, "validation_failed", message, fields)


def slug_taken(slug: str) -> ApiError:
    return ApiError(409, "conflict", f"The link name {slug!r} is taken", {"slug": "is already used"})


def calendar_or_404(c: Ctx, calendar_id: uuid.UUID, *, lock: bool = False) -> Calendar:
    stmt = select(Calendar).where(Calendar.id == calendar_id)
    cal = c.db.scalar(stmt.with_for_update() if lock else stmt)
    if cal is None:
        raise ApiError(404, "not_found", "Calendar not found")
    return cal


def hosts_of(c: Ctx, calendar_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    out: dict[uuid.UUID, list[dict]] = {i: [] for i in calendar_ids}
    rows = c.db.execute(select(CalendarHost, User.name, User.email).join(User, User.id == CalendarHost.user_id)
                        .where(CalendarHost.calendar_id.in_(calendar_ids))
                        .order_by(CalendarHost.created_at, CalendarHost.id)).all()
    for h, name, email in rows:
        out[h.calendar_id].append({"user_id": h.user_id, "name": name, "email": email, "weight": h.weight,
                                   "priority": h.priority, "daily_cap": h.daily_cap, "active": h.active})
    return out


def resources_of(c: Ctx, calendar_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    out: dict[uuid.UUID, list[dict]] = {i: [] for i in calendar_ids}
    rows = c.db.execute(select(CalendarResource, Resource).join(Resource, Resource.id == CalendarResource.resource_id)
                        .where(CalendarResource.calendar_id.in_(calendar_ids)).order_by(Resource.name))
    for link, r in rows:
        out[link.calendar_id].append({"resource_id": r.id, "name": r.name, "kind": r.kind, "quantity": link.quantity})
    return out


def calendar_json(c: Ctx, cal: Calendar, hosts: list[dict], resources: list[dict]) -> dict:
    path = booking.public_path(c.workspace.slug, cal.slug)
    return {"id": cal.id, **{k: getattr(cal, k) for k in SETTINGS if k != "reminders"}, "reminders": cal.reminders,
            "locations": cal.locations, "questions": cal.questions, "hosts": hosts, "resources": resources,
            "public_path": path, "public_url": path and f"{config.ALLOWED_ORIGINS[0]}{path}",
            "created_at": cal.created_at, "updated_at": cal.updated_at}


def detail(c: Ctx, cal: Calendar) -> dict:
    return calendar_json(c, cal, hosts_of(c, [cal.id])[cal.id], resources_of(c, [cal.id])[cal.id])


def event_data(cal: Calendar) -> dict:
    return {"id": cal.id, "name": cal.name, "slug": cal.slug, "kind": cal.kind, "status": cal.status}


def unique_slug(c: Ctx, base: str, own: uuid.UUID | None = None) -> str:
    taken = set(c.db.scalars(select(Calendar.slug).where(Calendar.slug.startswith(base), Calendar.id != own)))
    slug, n = base, 1
    while slug in taken:
        n += 1
        slug = f"{base}-{n}"
    return slug


def ensure_hours(c: Ctx, user_id: uuid.UUID, zone: str) -> None:
    """A person made a host with no hours yet gets the usual week in the calendar's zone, to be edited."""
    if c.db.scalar(select(Availability.id).where(Availability.user_id == user_id)) is None:
        c.db.add(Availability(workspace_id=c.workspace.id, user_id=user_id, time_zone=zone, weekly=DEFAULT_WEEKLY))
        c.db.flush()


def check_hosts(c: Ctx, kind: str, hosts: list[schemas.HostIn]) -> None:
    ids = [h.user_id for h in hosts]
    if len(set(ids)) != len(ids):
        raise invalid({"hosts": "a person can be a host once"})
    if kind in ONE_HOST and len(hosts) > 1:
        raise invalid({"hosts": f"a {kind} calendar has one host"})
    unknown = set(map(str, ids)) - member_ids(c, set(map(str, ids)))
    if unknown:
        raise invalid({"hosts": "everyone must be a member of this workspace"})


def set_hosts(c: Ctx, cal: Calendar, hosts: list[schemas.HostIn]) -> None:
    """Makes the calendar's hosts exactly these: new ones added with hours if they have none, the rest updated."""
    check_hosts(c, cal.kind, hosts)
    have = {h.user_id: h for h in c.db.scalars(select(CalendarHost).where(CalendarHost.calendar_id == cal.id))}
    wanted = {h.user_id: h for h in hosts}
    for user_id, h in have.items():
        if user_id not in wanted:
            c.db.delete(h)
    for user_id, new in wanted.items():
        row = have.get(user_id)
        if row is None:
            ensure_hours(c, user_id, cal.time_zone)
            # clock_timestamp, not now(): hosts added together keep the order sent, and the first is primary
            c.db.add(CalendarHost(workspace_id=cal.workspace_id, calendar_id=cal.id, user_id=user_id,
                                  created_at=func.clock_timestamp()))
            c.db.flush()
            row = c.db.scalar(select(CalendarHost).where(CalendarHost.calendar_id == cal.id,
                                                         CalendarHost.user_id == user_id))
        row.weight, row.priority, row.daily_cap, row.active = new.weight, new.priority, new.daily_cap, new.active
    c.db.flush()


def apply(cal: Calendar, body: schemas.Settings) -> dict:
    """Copies what the request sent onto the calendar; returns the changes, key to old and new value."""
    changes = {}
    sent = body.model_fields_set
    for key in (*SETTINGS, "locations", "questions"):
        if key not in sent or key == "slug":
            continue
        value = getattr(body, key)
        if key == "locations":
            value = [loc.model_dump() for loc in value or []]
        elif key == "questions":
            value = schemas.question_rows(value or [])
        elif value is None and key not in ("max_per_day", "cutoff_hours"):
            raise invalid({key: "cannot be null"})
        if getattr(cal, key) != value:
            changes[key] = {"old": getattr(cal, key), "new": value}
            setattr(cal, key, value)
    return changes


def check_kind_hosts(c: Ctx, cal: Calendar) -> None:
    count = c.db.scalar(select(func.count()).select_from(CalendarHost).where(CalendarHost.calendar_id == cal.id))
    if cal.kind in ONE_HOST and count > 1:
        raise invalid({"kind": f"a {cal.kind} calendar has one host, and this one has {count}"})


# --- calendars --------------------------------------------------------------------------------------------------

class NewCalendar(schemas.Settings):
    name: schemas.Name
    hosts: list[schemas.HostIn] | None = None  # default: the person creating it


@router.get("/calendars")
def list_calendars(archived: bool = False, c: Ctx = Depends(read)):
    """Every calendar of the workspace (archived ones too with `archived=true`), by name.
    ponytail: not paged, a workspace has dozens of calendars; add the cursor when one has thousands."""
    stmt = select(Calendar).order_by(func.lower(Calendar.name), Calendar.created_at, Calendar.id)
    if not archived:
        stmt = stmt.where(Calendar.status != "archived")
    cals = list(c.db.scalars(stmt))
    ids = [cal.id for cal in cals]
    hosts, resources = hosts_of(c, ids), resources_of(c, ids)
    return {"data": [calendar_json(c, cal, hosts[cal.id], resources[cal.id]) for cal in cals], "next_cursor": None}


@router.post("/calendars", status_code=201)
def create_calendar(body: NewCalendar, c: Ctx = Depends(manage), idem: Idem = Depends(idempotency)):
    values = {k: getattr(body, k) for k in SETTINGS if k in body.model_fields_set and k != "slug"}
    if body.max_per_day is None and "max_per_day" in values:
        del values["max_per_day"]
    cal = Calendar(workspace_id=c.workspace.id, slug=body.slug or unique_slug(c, schemas.hyphenate(body.name)),
                   **{k: v for k, v in values.items() if v is not None})
    cal.locations = [loc.model_dump() for loc in body.locations or []]
    cal.questions = schemas.question_rows(body.questions) if body.questions else schemas.DEFAULT_QUESTIONS
    try:
        with c.db.begin_nested():
            c.db.add(cal)
    except IntegrityError:
        raise slug_taken(cal.slug) from None
    hosts = body.hosts if body.hosts is not None else [schemas.HostIn(user_id=c.user_id)]
    set_hosts(c, cal, hosts)
    events.emit(c.db, "calendar.created", "calendar", cal.id, event_data(cal), actor=("user", c.user_id))
    return idem.commit(201, detail(c, cal))


@router.post("/calendars/feed")
def create_feed(c: Ctx = Depends(read)):
    """A private link to your bookings as an ICS feed, for any calendar app to subscribe to. Shown once: only a hash of
    its secret is kept, and asking again replaces the link."""
    token, digest = booking.new_token(c.workspace.id)
    c.db.execute(delete(FeedToken).where(FeedToken.user_id == c.user_id))
    c.db.add(FeedToken(workspace_id=c.workspace.id, user_id=c.user_id, token_hash=digest))
    c.db.commit()
    return {"url": f"{config.ALLOWED_ORIGINS[0]}/api/public/feeds/{token}.ics"}


@router.get("/calendars/{calendar_id}")
def get_calendar(calendar_id: uuid.UUID, c: Ctx = Depends(read)):
    return detail(c, calendar_or_404(c, calendar_id))


@router.patch("/calendars/{calendar_id}")
def update_calendar(calendar_id: uuid.UUID, body: schemas.Settings, c: Ctx = Depends(manage)):
    cal = calendar_or_404(c, calendar_id, lock=True)
    changes = apply(cal, body)
    if "slug" in body.model_fields_set and body.slug and body.slug != cal.slug:
        changes["slug"] = {"old": cal.slug, "new": body.slug}
        cal.slug = body.slug
    if changes:
        cal.updated_at = func.now()
        try:
            with c.db.begin_nested():
                c.db.flush()
        except IntegrityError:
            raise slug_taken(cal.slug) from None
        check_kind_hosts(c, cal)
        c.db.refresh(cal, ["updated_at"])
        events.emit(c.db, "calendar.updated", "calendar", cal.id, {**event_data(cal), "changes": changes},
                    actor=("user", c.user_id))
    c.db.commit()
    return detail(c, cal)


@router.delete("/calendars/{calendar_id}")
def delete_calendar(calendar_id: uuid.UUID, c: Ctx = Depends(manage)):
    """A calendar with no bookings is deleted (204); one that has any is archived (200), which takes its page down
    and keeps the history. `PATCH {"status": "active"}` brings an archived one back."""
    cal = calendar_or_404(c, calendar_id, lock=True)
    used = c.db.scalar(select(func.count()).select_from(Booking).where(Booking.calendar_id == cal.id))
    if used:
        cal.status, cal.updated_at = "archived", func.now()
        c.db.flush()
        c.db.refresh(cal, ["updated_at"])
        events.emit(c.db, "calendar.updated", "calendar", cal.id,
                    {**event_data(cal), "changes": {"status": {"old": "active", "new": "archived"}}},
                    actor=("user", c.user_id))
        result = detail(c, cal)
        c.db.commit()
        return result
    events.emit(c.db, "calendar.deleted", "calendar", cal.id, event_data(cal), actor=("user", c.user_id))
    c.db.delete(cal)
    c.db.commit()
    return Response(status_code=204)


@router.put("/calendars/{calendar_id}/hosts")
def put_hosts(calendar_id: uuid.UUID, body: list[schemas.HostIn], c: Ctx = Depends(manage)):
    """Replaces the hosts: who, their weight and priority in the rotation, an optional cap per day, and whether they
    take bookings now. A new host gets the usual working week if they have none."""
    cal = calendar_or_404(c, calendar_id, lock=True)
    before = [h["user_id"] for h in hosts_of(c, [cal.id])[cal.id]]
    set_hosts(c, cal, body)
    cal.updated_at = func.now()
    c.db.flush()
    c.db.refresh(cal, ["updated_at"])
    events.emit(c.db, "calendar.updated", "calendar", cal.id,
                {**event_data(cal), "changes": {"hosts": {"old": before, "new": [h.user_id for h in body]}}},
                actor=("user", c.user_id))
    c.db.commit()
    return detail(c, cal)


class ResourceNeed(BaseModel):
    resource_id: uuid.UUID
    quantity: Annotated[int, Field(ge=1, le=1000)] = 1


@router.put("/calendars/{calendar_id}/resources")
def put_calendar_resources(calendar_id: uuid.UUID, body: list[ResourceNeed], c: Ctx = Depends(manage)):
    """Replaces the rooms and equipment a booking on this calendar takes, and how many of each."""
    cal = calendar_or_404(c, calendar_id, lock=True)
    ids = [r.resource_id for r in body]
    found = set(c.db.scalars(select(Resource.id).where(Resource.id.in_(ids))))
    if len(set(ids)) != len(ids) or found != set(ids):
        raise invalid({"resources": "each must be a different resource of this workspace"})
    c.db.execute(delete(CalendarResource).where(CalendarResource.calendar_id == cal.id))
    c.db.add_all(CalendarResource(calendar_id=cal.id, resource_id=r.resource_id, workspace_id=cal.workspace_id,
                                  quantity=r.quantity) for r in body)
    cal.updated_at = func.now()
    c.db.flush()
    c.db.refresh(cal, ["updated_at"])
    events.emit(c.db, "calendar.updated", "calendar", cal.id,
                {**event_data(cal), "changes": {"resources": {"old": None, "new": [str(i) for i in ids]}}},
                actor=("user", c.user_id))
    c.db.commit()
    return detail(c, cal)


# --- what the calendar offers -----------------------------------------------------------------------------------

def clock_now() -> datetime:
    return datetime.now(UTC)


@router.get("/calendars/{calendar_id}/slots")
def calendar_slots(calendar_id: uuid.UUID, from_: Annotated[date, Query(alias="from")], to: date,
                   tz: str | None = None, duration: int | None = None, c: Ctx = Depends(read)):
    """Open start times from one day to another (on the clock of `tz`, default the calendar's), by day, as UTC."""
    cal = calendar_or_404(c, calendar_id)
    return days.slot_days(c.db, cal, from_, to, tz or cal.time_zone, duration, clock_now())


@router.get("/calendars/{calendar_id}/explain")
def explain(calendar_id: uuid.UUID, start: AwareDatetime, tz: str | None = None, duration: int | None = None,
            c: Ctx = Depends(read)):
    """Why a time is or is not offered: what is wrong with the time itself, and for each host whether they are free and
    what stops them. When it is offered, who would get the booking."""
    cal = calendar_or_404(c, calendar_id)
    zone = days.invitee_zone(tz or cal.time_zone)
    length = days.chosen_duration(cal, duration)
    now = clock_now()
    start = start.astimezone(UTC)
    snap = slots.load(c.db, cal, start, start + timedelta(minutes=length), now)
    answer = slots.explain(snap, start, length, now, zone)
    if answer["offered"]:
        pick = routing.choose(snap, slots.check(snap, start, length, now))
        answer["assigned"] = {"user_id": pick.host.user_id, "name": pick.host.name, "reason": pick.reason}
    return answer


@router.post("/calendars/{calendar_id}/simulate")
def simulate(calendar_id: uuid.UUID, n: Annotated[int, Query(ge=1, le=100)] = 20, duration: int | None = None,
             contact_id: uuid.UUID | None = None, c: Ctx = Depends(read)):
    """Who would get the next `n` bookings if they came now, one after another, each at the earliest open time.
    Nothing is written. With a contact, a host who owns them keeps them."""
    cal = calendar_or_404(c, calendar_id)
    length = days.chosen_duration(cal, duration)
    now = clock_now()
    owner = None
    if contact_id:
        owner = c.db.scalar(select(Record.owner_id).where(Record.id == contact_id))
    snap = slots.load(c.db, cal, now, now + timedelta(days=cal.window_days + 1), now)
    plan = routing.simulate(snap, now, length, n, owner)
    return {"calendar_id": cal.id, "kind": cal.kind, "duration": length, **plan}


# --- resources --------------------------------------------------------------------------------------------------

def resource_json(r: Resource) -> dict:
    return {"id": r.id, "name": r.name, "kind": r.kind, "quantity": r.quantity, "created_at": r.created_at}


def resource_or_404(c: Ctx, resource_id: uuid.UUID) -> Resource:
    r = c.db.get(Resource, resource_id)
    if r is None:
        raise ApiError(404, "not_found", "Resource not found")
    return r


@router.get("/resources")
def list_resources(c: Ctx = Depends(read)):
    rows = c.db.scalars(select(Resource).order_by(func.lower(Resource.name), Resource.id))
    return {"data": [resource_json(r) for r in rows], "next_cursor": None}


@router.post("/resources", status_code=201)
def create_resource(body: schemas.ResourceIn, c: Ctx = Depends(manage), idem: Idem = Depends(idempotency)):
    r = Resource(workspace_id=c.workspace.id, name=body.name, kind=body.kind, quantity=body.quantity)
    c.db.add(r)
    c.db.flush()
    events.emit(c.db, "resource.created", "resource", r.id, resource_event(r), actor=("user", c.user_id))
    return idem.commit(201, resource_json(r))


def resource_event(r: Resource) -> dict:
    return {"id": r.id, "name": r.name, "kind": r.kind, "quantity": r.quantity}


@router.patch("/resources/{resource_id}")
def update_resource(resource_id: uuid.UUID, body: schemas.ResourcePatch, c: Ctx = Depends(manage)):
    r = resource_or_404(c, resource_id)
    changes = {}
    for key in body.model_fields_set:
        value = getattr(body, key)
        if value is None:
            raise invalid({key: "cannot be null"})
        if getattr(r, key) != value:
            changes[key] = {"old": getattr(r, key), "new": value}
            setattr(r, key, value)
    if changes:
        c.db.flush()
        events.emit(c.db, "resource.updated", "resource", r.id, {**resource_event(r), "changes": changes},
                    actor=("user", c.user_id))
    c.db.commit()
    return resource_json(r)


@router.delete("/resources/{resource_id}", status_code=204)
def delete_resource(resource_id: uuid.UUID, c: Ctx = Depends(manage)):
    """A resource nothing has been booked on is deleted; one with bookings stays, because they refer to it."""
    r = resource_or_404(c, resource_id)
    try:
        with c.db.begin_nested():
            c.db.execute(delete(Availability).where(Availability.resource_id == r.id))
            c.db.delete(r)
            c.db.flush()
    except IntegrityError:
        raise ApiError(409, "conflict", "Bookings used this resource, so it cannot be deleted") from None
    events.emit(c.db, "resource.deleted", "resource", r.id, resource_event(r), actor=("user", c.user_id))
    c.db.commit()


