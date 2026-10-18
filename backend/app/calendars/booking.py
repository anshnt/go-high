"""Making, moving and ending bookings (module 16). A booking is made inside one transaction that first takes row locks
(the calendar, its hosts' hours, the resources) and only then reads who is free, so two requests for the same time
cannot both see it open: the second waits for the first to commit and then finds the time taken. The locks are always
taken in that order, hosts and resources by id, so two bookings cannot wait on each other.

The cancel and reschedule link holds the workspace in its first part, so the public routes know where to look without a
broad database scope, and a secret in its second, of which only the SHA-256 is stored."""
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update

from .. import config, events, jobs
from ..api import ApiError
from ..records.schema import Catalog
from ..records.timeline import link
from ..security import Ctx, token_hash
from . import contacts, routing, slots
from .models import (
    Availability,
    Booking,
    BookingReminder,
    BookingResource,
    Calendar,
    CalendarHost,
    CalendarResource,
    Resource,
)

ALLOWED = {"confirmed": ("booked", "rescheduled"), "showed": ("booked", "confirmed", "rescheduled", "no_show"),
           "no_show": ("booked", "confirmed", "rescheduled", "showed")}  # new status: the statuses it can come from


def taken() -> ApiError:
    return ApiError(409, "slot_unavailable", "That time is no longer available. Pick another.")


def new_token(workspace_id: uuid.UUID) -> tuple[str, str]:
    token = f"{workspace_id.hex}.{secrets.token_urlsafe(24)}"
    return token, token_hash(token)


def near(cal: Calendar, start: datetime, now: datetime) -> None:
    """A 409 for a time far outside the booking window, before anything is read: the rules would refuse it anyway
    (too soon, too far), and a date at either end of the calendar would overflow on the way there."""
    if not now - timedelta(days=1) <= start <= now + timedelta(days=cal.window_days + 1):
        raise taken()


def token_workspace(token: str) -> uuid.UUID | None:
    """The workspace named by the first part of a link's token (untrusted: the lookup that follows decides)."""
    head, dot, tail = token.partition(".")
    try:
        return uuid.UUID(head) if dot and tail else None
    except ValueError:
        return None


def manage_url(token: str) -> str:
    return f"{config.ALLOWED_ORIGINS[0]}/booking/{token}"


def public_path(workspace_slug: str | None, calendar_slug: str) -> str | None:
    return f"/book/{workspace_slug}/{calendar_slug}" if workspace_slug else None


def lock(c: Ctx, cal: Calendar, resources: list[uuid.UUID] | None = None) -> None:
    """Row locks for what a booking on this calendar touches, in the order that cannot deadlock: the calendar, the hours
    of its hosts, then the resources (by id)."""
    db = c.db
    db.execute(select(Calendar.id).where(Calendar.id == cal.id).with_for_update(key_share=True))
    hosts = list(db.scalars(select(CalendarHost.user_id).where(CalendarHost.calendar_id == cal.id)))
    db.execute(select(Availability.id).where(Availability.user_id.in_(hosts)).order_by(Availability.id)
               .with_for_update(key_share=True))
    if resources:
        db.execute(select(Resource.id).where(Resource.id.in_(resources)).order_by(Resource.id)
                   .with_for_update(key_share=True))


def pick_location(cal: Calendar, kind: str | None) -> dict:
    if not cal.locations:
        return {}
    chosen = next((loc for loc in cal.locations if loc["kind"] == kind), None) if kind else cal.locations[0]
    if chosen is None:
        raise ApiError(422, "validation_failed", "The details are not valid", {"location": "is not offered"})
    return {"kind": chosen["kind"], "value": chosen.get("value", "")}


def event_data(b: Booking, cal: Calendar) -> dict:
    """What the booking events say (no name, email or phone: those belong to the contact)."""
    return {"id": b.id, "calendar_id": b.calendar_id, "calendar": cal.name, "host_user_id": b.host_user_id,
            "host_ids": b.host_ids, "contact_id": b.contact_id, "starts_at": b.starts_at, "ends_at": b.ends_at,
            "time_zone": b.time_zone, "status": b.status, "source": b.source}


def emit(c: Ctx, type_: str, b: Booking, cal: Calendar, extra: dict | None = None) -> None:
    actor = ("user", c.user_id) if c.user_id else None
    event = events.emit(c.db, type_, "booking", b.id, {**event_data(b, cal), **(extra or {})}, actor=actor,
                        workspace_id=b.workspace_id)
    if b.contact_id:
        link(c.db, event, [b.contact_id])


def plan_reminders(c: Ctx, b: Booking, offsets: list[int], now: datetime) -> None:
    """One reminder per offset, due that many minutes before the start, as a job at that time. Running it again after
    the booking moved re-arms them: the row takes the new time and a job already queued for the old one finds the row
    changed and does nothing. A time already past is not scheduled."""
    found = c.db.scalars(select(BookingReminder).where(BookingReminder.booking_id == b.id))
    rows = {r.offset_minutes: r for r in found}
    for offset in sorted(set(offsets)):
        due = b.starts_at - timedelta(minutes=offset)
        row = rows.get(offset)
        if due <= now:
            if row is not None and row.status == "pending":
                row.status = "cancelled"
            continue
        if row is None:
            row = BookingReminder(workspace_id=b.workspace_id, booking_id=b.id, offset_minutes=offset, due_at=due)
            c.db.add(row)
        row.due_at, row.status, row.sent_at = due, "pending", None
        c.db.flush()
        jobs.enqueue(c.db, "calendars.reminder", {"id": str(row.id), "due": due.isoformat()}, run_at=due)


def create(c: Ctx, cal: Calendar, *, start: datetime, duration: int, who: contacts.Invitee, answers: dict,
           location: str | None, time_zone: str, source: str, now: datetime) -> tuple[Booking, str]:
    """The booking and the secret of its link, or a 409 when the time is gone. The caller commits."""
    near(cal, start, now)
    cat = Catalog(c)
    who = contacts.clean(cat, who)
    needs = dict(c.db.execute(select(CalendarResource.resource_id, CalendarResource.quantity)
                              .where(CalendarResource.calendar_id == cal.id)).all())
    lock(c, cal, list(needs))
    snap = slots.load(c.db, cal, start, start + timedelta(minutes=duration), now)
    verdict = slots.check(snap, start, duration, now)
    if not verdict.offered:
        raise taken()
    existing = contacts.find(cat, who)
    pick = routing.choose(snap, verdict, existing.owner_id if existing else None)
    contact = contacts.attach(cat, who, pick.host.user_id)
    token, digest = new_token(cal.workspace_id)
    ids = [p.user_id for p in pick.attendees]
    b = Booking(workspace_id=cal.workspace_id, calendar_id=cal.id, host_user_id=pick.host.user_id,
                host_ids=[pick.host.user_id, *[i for i in ids if i != pick.host.user_id]], contact_id=contact.id,
                starts_at=start, ends_at=start + timedelta(minutes=duration), buffer_before=cal.buffer_before,
                buffer_after=cal.buffer_after, time_zone=time_zone,
                status="confirmed" if cal.confirmation == "auto" else "booked", invitee_name=who.name,
                invitee_email=who.email, invitee_phone=who.phone, location=pick_location(cal, location),
                answers=answers, token_hash=digest, source=source, created_by=c.user_id)
    c.db.add(b)
    c.db.flush()
    c.db.add_all(BookingResource(booking_id=b.id, resource_id=r, workspace_id=b.workspace_id, quantity=n)
                 for r, n in needs.items())
    plan_reminders(c, b, cal.reminders, now)
    emit(c, "booking.created", b, cal, {"host_reason": pick.reason})
    return b, token


def reschedule(c: Ctx, b: Booking, cal: Calendar, *, start: datetime, time_zone: str, now: datetime) -> None:
    """Moves a booking to another time with the same host(s), after the same checks as a new one. The caller commits."""
    near(cal, start, now)
    duration = int((b.ends_at - b.starts_at).total_seconds() // 60)
    lock(c, cal, list(c.db.scalars(select(BookingResource.resource_id).where(BookingResource.booking_id == b.id))))
    snap = slots.load(c.db, cal, start, start + timedelta(minutes=duration), now, ignore=b.id)
    verdict = slots.check(snap, start, duration, now)
    mine = {h.user_id for h in verdict.free}
    if not verdict.offered or not set(b.host_ids) <= mine:
        raise taken()
    old = (b.starts_at, b.ends_at)
    b.starts_at, b.ends_at, b.time_zone = start, start + timedelta(minutes=duration), time_zone
    b.status, b.reschedules, b.updated_at = "rescheduled", b.reschedules + 1, now
    c.db.flush()
    # the calendar's offsets too, not only the rows there are: one that was already past when the booking was made has
    # no row, and a booking moved later must still get it
    planned = c.db.scalars(select(BookingReminder.offset_minutes).where(BookingReminder.booking_id == b.id))
    plan_reminders(c, b, [*cal.reminders, *planned], now)
    emit(c, "booking.rescheduled", b, cal, {"from_starts_at": old[0], "from_ends_at": old[1]})


def cancel(c: Ctx, b: Booking, cal: Calendar, reason: str | None, now: datetime) -> bool:
    """Cancels a booking and its pending reminders; False when it was already cancelled. The caller commits."""
    if b.status == "cancelled":
        return False
    b.status, b.cancelled_at, b.cancel_reason, b.updated_at = "cancelled", now, reason, now
    c.db.execute(update(BookingReminder).where(BookingReminder.booking_id == b.id, BookingReminder.status == "pending")
                 .values(status="cancelled"))
    c.db.flush()
    emit(c, "booking.cancelled", b, cal, {"reason": reason})
    return True


def set_status(c: Ctx, b: Booking, cal: Calendar, status: str, now: datetime) -> None:
    """Confirms a booking that waits for it, or records whether the invitee came. The caller commits."""
    if b.status not in ALLOWED[status]:
        have, want = b.status.replace("_", " "), status.replace("_", " ")
        raise ApiError(409, "conflict", f"A {have} booking cannot become {want}")
    old, b.status, b.updated_at = b.status, status, now
    c.db.flush()
    emit(c, "booking.status_changed", b, cal, {"from_status": old})
