"""The public side of calendars (module 16): what a visitor does with no account. They read a calendar and its open
times, book one, and later cancel or move it from the link they were given; people can subscribe to their bookings
from a private feed. Nothing here is signed in: the workspace comes from the link, the database scope is that
workspace and no more, and what a visitor can reach is bounded by the secrets in the links (a booking's token, a
feed's token), whose hashes are all that is stored.

A booking request is held back by a honeypot field (a real visitor never fills it, a bot does: it gets a believable
answer and nothing is stored) and by a rate limit per calendar and visitor (a hash of their address, so the address
itself is not kept) with a ceiling for the calendar as a whole. Both count every attempt, the failed ones too."""
import hashlib
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import AwareDatetime, BaseModel, StringConstraints
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import config
from ..api import ApiError
from ..db import rescope, scoped
from ..models import User, Workspace
from ..security import client_ip, token_hash
from . import booking, contacts, days, ics, slots
from .models import Booking, BookingAttempt, Calendar, CalendarHost, FeedToken

log = logging.getLogger("calendars")
router = APIRouter(prefix="/api/public")
pages = APIRouter()
FEED_PAST = timedelta(days=30)
FEED_MAX = 1000
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


def public_db():
    """A session with no tenant yet (the pre-auth scope); `enter` narrows it to the workspace a link names."""
    with scoped(system="on") as db:
        yield db


def now() -> datetime:
    return datetime.now(UTC)


def not_found(what: str = "Not found") -> ApiError:
    return ApiError(404, "not_found", what)


def enter(db: Session, ws: Workspace | None) -> Workspace:
    """From here the session sees this workspace's rows and nothing else (row level security)."""
    if ws is None:
        raise not_found()
    rescope(db, workspace_id=ws.id, org_id=ws.org_id)
    return ws


def calendar_of(db: Session, workspace_slug: str, calendar_slug: str) -> tuple[Workspace, Calendar]:
    ws = enter(db, db.scalar(select(Workspace).where(Workspace.slug == workspace_slug)))
    cal = db.scalar(select(Calendar).where(Calendar.slug == calendar_slug, Calendar.status != "archived"))
    if cal is None:
        raise not_found("This booking page does not exist")
    return ws, cal


def booking_of(db: Session, token: str) -> tuple[Workspace, Booking, Calendar]:
    wid = booking.token_workspace(token)
    ws = enter(db, db.get(Workspace, wid) if wid else None)
    b = db.scalar(select(Booking).where(Booking.token_hash == token_hash(token)))
    if b is None:
        raise not_found("This link is not valid")
    return ws, b, db.get(Calendar, b.calendar_id)


def info(ws: Workspace, cal: Calendar, hosts: list[str]) -> dict:
    return {"name": cal.name, "description": cal.description, "kind": cal.kind, "durations": cal.durations,
            "time_zone": cal.time_zone, "locations": cal.locations, "questions": cal.questions,
            "confirmation": cal.confirmation, "color": cal.color, "business": ws.name, "window_days": cal.window_days,
            "paused": cal.status != "active", "hosts": hosts if cal.kind in ("personal", "collective", "class") else []}


def host_names(db: Session, cal: Calendar) -> list[str]:
    return list(db.scalars(select(User.name).join(CalendarHost, CalendarHost.user_id == User.id)
                           .where(CalendarHost.calendar_id == cal.id, CalendarHost.active)
                           .order_by(CalendarHost.created_at, CalendarHost.id)))


def can_change(b: Booking, cal: Calendar, at: datetime) -> bool:
    if b.status in ("cancelled", "showed", "no_show") or b.starts_at <= at:
        return False
    return cal.cutoff_hours is None or at <= b.starts_at - timedelta(hours=cal.cutoff_hours)


def booking_view(ws: Workspace, b: Booking, cal: Calendar, token: str) -> dict:
    cutoff = None if cal.cutoff_hours is None else b.starts_at - timedelta(hours=cal.cutoff_hours)
    return {"status": b.status, "starts_at": b.starts_at, "ends_at": b.ends_at, "time_zone": b.time_zone,
            "calendar": {"name": cal.name, "description": cal.description, "time_zone": cal.time_zone,
                         "color": cal.color, "business": ws.name, "durations": cal.durations},
            "location": b.location, "invitee": {"name": b.invitee_name},
            "can_change": can_change(b, cal, now()), "change_until": cutoff,
            "ics_path": f"/api/public/bookings/{token}/ics", "confirmation": cal.confirmation}


# --- a calendar -------------------------------------------------------------------------------------------------

@router.get("/calendars/{workspace_slug}/{calendar_slug}")
def get_calendar(workspace_slug: str, calendar_slug: str, db: Session = Depends(public_db)):
    ws, cal = calendar_of(db, workspace_slug, calendar_slug)
    return info(ws, cal, host_names(db, cal))


@router.get("/calendars/{workspace_slug}/{calendar_slug}/slots")
def get_slots(workspace_slug: str, calendar_slug: str, from_: Annotated[date, Query(alias="from")], to: date,
              tz: str = "UTC", duration: int | None = None, db: Session = Depends(public_db)):
    """Open start times from one day to another on the visitor's clock (`tz`), by day, as UTC instants."""
    _, cal = calendar_of(db, workspace_slug, calendar_slug)
    return days.slot_days(db, cal, from_, to, tz, duration, now())


class NewBooking(BaseModel):
    start: AwareDatetime
    duration: int | None = None
    time_zone: str
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    answers: dict[str, str] = {}
    location: str | None = None
    website: str = ""  # the honeypot: hidden on the page, so only a bot fills it


def clean_answers(cal: Calendar, body: NewBooking) -> dict:
    """The answers to the calendar's own questions, as {key: {label, value}}, or a 422 naming each that is wrong."""
    errors, out = {}, {}
    if not body.phone and next((q["required"] for q in cal.questions if q["key"] == "phone"), True):
        errors["phone"] = "is required"
    for q in cal.questions:
        if q["key"] in ("name", "email", "phone"):
            continue
        value = (body.answers.get(q["key"]) or "").strip()
        field = f"answers.{q['key']}"
        if not value:
            if q["required"]:
                errors[field] = "is required"
        elif q["type"] == "select" and value not in q["options"]:
            errors[field] = "is not one of the options"
        elif len(value) > (5000 if q["type"] == "long_text" else 1000):
            errors[field] = "is too long"
        else:
            out[q["key"]] = {"label": q["label"], "value": value}
    if errors:
        raise ApiError(422, "validation_failed", "Some details are missing or wrong", errors)
    return out


def throttle(db: Session, cal: Calendar, ip_hash: str, at: datetime) -> None:
    """Counts this request and refuses it (429) when the visitor or the calendar has made too many in the window."""
    window = timedelta(minutes=config.BOOKING_WINDOW_MINUTES)
    db.execute(delete(BookingAttempt).where(BookingAttempt.created_at < at - window))
    count = select(func.count()).select_from(BookingAttempt).where(BookingAttempt.calendar_id == cal.id)
    per_ip = db.scalar(count.where(BookingAttempt.ip_hash == ip_hash)) or 0
    total = db.scalar(count) or 0
    db.add(BookingAttempt(workspace_id=cal.workspace_id, calendar_id=cal.id, ip_hash=ip_hash, created_at=at))
    db.commit()  # the attempt counts even when the request is refused or fails
    if per_ip >= config.BOOKING_MAX_PER_IP or total >= config.BOOKING_MAX_PER_CALENDAR:
        raise ApiError(429, "rate_limited", "Too many booking requests, try again in a few minutes",
                       headers={"Retry-After": str(int(window.total_seconds()))})


def visitor(request: Request) -> str:
    return hashlib.sha256(f"{config.SECRET_KEY}|{client_ip(request)}".encode()).hexdigest()


def booked(ws: Workspace, b: Booking, cal: Calendar, token: str) -> dict:
    return {**booking_view(ws, b, cal, token), "token": token, "manage_path": f"/booking/{token}",
            "manage_url": booking.manage_url(token)}


@router.post("/calendars/{workspace_slug}/{calendar_slug}/bookings", status_code=201)
def book(workspace_slug: str, calendar_slug: str, body: NewBooking, request: Request,
         db: Session = Depends(public_db)):
    """Books a time. 409 `slot_unavailable` when it is gone (someone else took it, or it is not an open time),
    422 when a detail is missing, 429 when the visitor books too often."""
    ws, cal = calendar_of(db, workspace_slug, calendar_slug)
    at = now()
    throttle(db, cal, visitor(request), at)
    if body.website:  # a bot: say it worked, store nothing
        fake = Booking(id=uuid.uuid4(), starts_at=body.start, ends_at=body.start + timedelta(minutes=30),
                       status="booked", time_zone="UTC", invitee_name=body.name, location={}, reschedules=0)
        return booked(ws, fake, cal, f"{ws.id.hex}.{uuid.uuid4().hex}")
    try:
        slots.zone(body.time_zone)
    except ValueError:
        raise ApiError(422, "validation_failed", "The details are not valid",
                       {"time_zone": "is not a time zone"}) from None
    answers = clean_answers(cal, body)
    c = contacts.system_ctx(db, ws)
    try:
        b, token = booking.create(
            c, cal, start=body.start.astimezone(UTC), duration=days.chosen_duration(cal, body.duration),
            who=contacts.Invitee(body.name, body.email, body.phone), answers=answers, location=body.location,
            time_zone=body.time_zone, source="page", now=at)
    except ApiError as e:
        if e.status_code != 403:
            raise
        # the Automation role was edited so that it cannot write contacts: the visitor is not told which capability
        log.warning("booking refused: the Automation role of workspace %s cannot write contacts", ws.id)
        raise ApiError(503, "unavailable", "This booking page cannot take bookings right now") from None
    db.commit()
    return booked(ws, b, cal, token)


# --- a booking, by its link -------------------------------------------------------------------------------------

@router.get("/bookings/{token}")
def get_booking(token: str, db: Session = Depends(public_db)):
    ws, b, cal = booking_of(db, token)
    return booking_view(ws, b, cal, token)


@router.get("/bookings/{token}/slots")
def booking_slots(token: str, from_: Annotated[date, Query(alias="from")], to: date, tz: str = "UTC",
                  db: Session = Depends(public_db)):
    """Open times for moving this booking: the same length, its own time counted as free."""
    _, b, cal = booking_of(db, token)
    length = int((b.ends_at - b.starts_at).total_seconds() // 60)
    return days.slot_days(db, cal, from_, to, tz, length, now(), ignore=b.id)


def changeable(b: Booking, cal: Calendar) -> None:
    if b.status == "cancelled":
        raise ApiError(409, "conflict", "This booking is cancelled")
    if not can_change(b, cal, now()):
        raise ApiError(403, "change_closed", "This booking can no longer be changed online. Please get in touch.")


class Cancel(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


@router.post("/bookings/{token}/cancel")
def cancel_booking(token: str, body: Cancel, db: Session = Depends(public_db)):
    ws, b, cal = booking_of(db, token)
    if b.status != "cancelled":
        changeable(b, cal)
        booking.cancel(contacts.system_ctx(db, ws), b, cal, body.reason, now())
        db.commit()
    return booking_view(ws, b, cal, token)


class Move(BaseModel):
    start: AwareDatetime
    time_zone: str


@router.post("/bookings/{token}/reschedule")
def reschedule_booking(token: str, body: Move, db: Session = Depends(public_db)):
    ws, b, cal = booking_of(db, token)
    changeable(b, cal)
    try:
        slots.zone(body.time_zone)
    except ValueError:
        raise ApiError(422, "validation_failed", "The details are not valid",
                       {"time_zone": "is not a time zone"}) from None
    booking.reschedule(contacts.system_ctx(db, ws), b, cal, start=body.start.astimezone(UTC),
                       time_zone=body.time_zone, now=now())
    db.commit()
    return booking_view(ws, b, cal, token)


def calendar_file(events: list[list[str]], name: str, filename: str) -> Response:
    return Response(ics.calendar(events, name), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/bookings/{token}/ics")
def booking_ics(token: str, db: Session = Depends(public_db)):
    """The booking as an .ics file, for any calendar app."""
    _, b, cal = booking_of(db, token)
    return calendar_file([ics.event(b, cal, url=booking.manage_url(token))], cal.name, "booking.ics")


@router.get("/feeds/{token}.ics")
def feed(token: str, db: Session = Depends(public_db)):
    """A person's bookings as a feed any calendar app can subscribe to, found by the secret in the link: from 30 days
    ago on, cancelled ones left out."""
    wid = booking.token_workspace(token)
    enter(db, db.get(Workspace, wid) if wid else None)
    found = db.scalar(select(FeedToken.user_id).where(FeedToken.token_hash == token_hash(token)))
    if found is None:
        raise not_found("This link is not valid")
    rows = db.execute(select(Booking, Calendar).join(Calendar, Calendar.id == Booking.calendar_id)
                      .where(Booking.host_ids.contains([found]), Booking.status != "cancelled",
                             Booking.ends_at > now() - FEED_PAST).order_by(Booking.starts_at).limit(FEED_MAX))
    return calendar_file([ics.event(b, cal) for b, cal in rows], "My bookings", "bookings.ics")


# --- cross-origin use (the embed), and the pages ---------------------------------------------------------------

async def cors(request: Request, call_next):
    """The public routes carry no cookies and nothing private, so any site may call them: that is how the booking widget
    is embedded without an iframe. They are never cached by a shared cache, since open times change by the minute."""
    if not request.url.path.startswith(("/api/public/calendars/", "/api/public/bookings/", "/api/public/feeds/")):
        return await call_next(request)
    headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
               "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400"}
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=headers)
    response = await call_next(request)
    response.headers.update(headers)
    response.headers["Cache-Control"] = "no-store"
    return response


def page() -> Response:
    file = Path(config.FRONTEND_DIST) / "book" / "page.html"
    if file.is_file():
        return FileResponse(file)
    return JSONResponse({"detail": "Booking page not built; run `npm run build` in frontend/."}, status_code=404)


@pages.get("/book/{workspace_slug}/{calendar_slug}", include_in_schema=False)
def booking_page(workspace_slug: str, calendar_slug: str):
    return page()


@pages.get("/booking/{token}", include_in_schema=False)
def manage_page(token: str):
    return page()
