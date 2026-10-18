"""The availability engine (module 16): which start times a calendar offers, and why a time is not offered.

`load` is the one query: it reads a calendar's hosts, their hours, bookings, outside busy blocks and resources into a
`Snapshot`. Everything after it is pure, so the rules are tested without a database. All instants are UTC; a person's
or resource's own working hours are read in their own zone with zoneinfo, so daylight saving moves the hours and not
the clock. Start times sit on a grid of `slot_interval` minutes counted from midnight in the calendar's zone.

A booking occupies its host from `start - buffer_before` to `end + buffer_after`, the buffers being those of the
calendar it was made on. A candidate time is free when its own span overlaps none of those, and its own buffers fit
between it and the next booking: the gap needed between two meetings is the larger of the two buffers, not their sum."""
import uuid
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User
from .models import (
    Availability,
    Booking,
    BookingResource,
    BusyBlock,
    Calendar,
    CalendarHost,
    CalendarResource,
    Resource,
)

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_BUFFER = timedelta(minutes=240)  # the calendar check caps buffers here, which bounds where a conflict can hide
ROLLING_DAYS = 30  # round robin counts a host's bookings from this far back
MAX_RANGES = 6


# --- hours --------------------------------------------------------------------------------------------------------

def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"{name!r} is not a time zone") from None


def minutes(value: str) -> int:
    """'09:30' as minutes after midnight; '24:00' is the end of the day."""
    hh, _, mm = value.partition(":")
    if len(hh) != 2 or len(mm) != 2 or not (hh + mm).isdigit() or int(mm) > 59 or value > "24:00":
        raise ValueError(f"{value!r} is not a time of day (HH:MM)")
    return int(hh) * 60 + int(mm)


def clean_ranges(raw) -> list[list[str]]:
    """Working ranges of one day: [["09:00", "12:00"], ["13:00", "17:00"]], in order, without overlap."""
    if not isinstance(raw, list) or len(raw) > MAX_RANGES:
        raise ValueError(f"must be a list of at most {MAX_RANGES} ranges")
    out, last = [], 0
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2 or not all(isinstance(x, str) for x in item):
            raise ValueError('a range is a pair of times like ["09:00", "17:00"]')
        start, end = minutes(item[0]), minutes(item[1])
        if start >= end:
            raise ValueError(f"{item[0]} to {item[1]} ends before it starts")
        if start < last:
            raise ValueError("ranges of one day must be in order and must not overlap")
        out.append([item[0], item[1]])
        last = end
    return out


def clean_weekly(raw) -> dict[str, list[list[str]]]:
    if not isinstance(raw, dict) or not set(raw) <= set(WEEKDAYS):
        raise ValueError(f"must map {', '.join(WEEKDAYS)} to ranges")
    return {day: clean_ranges(raw.get(day, [])) for day in WEEKDAYS}


def local_time(day: date, mins: int, tz: ZoneInfo) -> datetime:
    """The instant of `mins` after midnight on `day` on the wall clock of `tz`. A time that does not exist (the hour a
    clock skips) lands after the gap, and one that happens twice is the first of them."""
    return (datetime.combine(day, time(0)) + timedelta(minutes=mins)).replace(tzinfo=tz).astimezone(UTC)


def ranges_of(weekly: dict, overrides: dict, day: date) -> list[list[str]]:
    found = overrides.get(day.isoformat())
    return weekly.get(WEEKDAYS[day.weekday()], []) if found is None else found


def windows(weekly: dict, overrides: dict, tz: ZoneInfo, lo: datetime, hi: datetime) -> list[tuple[datetime, datetime]]:
    """The working windows between lo and hi as UTC instants, in order, touching ones merged."""
    day = lo.astimezone(tz).date() - timedelta(days=1)
    last = hi.astimezone(tz).date() + timedelta(days=1)
    out: list[tuple[datetime, datetime]] = []
    while day <= last:
        for start, end in ranges_of(weekly, overrides, day):
            a, b = local_time(day, minutes(start), tz), local_time(day, minutes(end), tz)
            if a >= b:
                continue
            if out and out[-1][1] >= a:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        day += timedelta(days=1)
    return out


# --- what a snapshot holds ----------------------------------------------------------------------------------------

class Span(NamedTuple):
    """Time something is taken: a booking (with its calendar's buffers), an outside busy block, or a resource's use."""
    start: datetime
    end: datetime
    before: int = 0
    after: int = 0
    calendar_id: uuid.UUID | None = None
    quantity: int = 1
    kind: str = "booking"  # booking, busy
    booking_id: uuid.UUID | None = None


class Reason(NamedTuple):
    """Why a time is not offered. `host` is set for what concerns one host (or a resource); `a` and `b` carry what the
    sentence needs."""
    code: str
    host: uuid.UUID | None = None
    a: object = None
    b: object = None


class Busy:
    """Spans sorted by start, for 'what is near this time' without reading all of them."""

    def __init__(self, spans: list[Span] = ()):
        self.spans = sorted(spans, key=lambda s: s.start)
        self.starts = [s.start for s in self.spans]
        self.reach = max((s.end - s.start for s in self.spans), default=timedelta(0))

    def add(self, span: Span) -> None:
        i = bisect_right(self.starts, span.start)
        self.spans.insert(i, span)
        self.starts.insert(i, span.start)
        self.reach = max(self.reach, span.end - span.start)

    def near(self, start: datetime, end: datetime) -> list[Span]:
        """Spans that can matter to [start, end), buffers included."""
        lo = bisect_left(self.starts, start - MAX_BUFFER - self.reach)
        hi = bisect_left(self.starts, end + MAX_BUFFER)
        return self.spans[lo:hi]


@dataclass
class Person:
    """A host, or a resource (`user_id` then holds its id), with the hours and busy time that decide when it is free."""
    user_id: uuid.UUID
    name: str
    tz: ZoneInfo
    weekly: dict
    overrides: dict
    has_hours: bool = True
    weight: int = 1
    priority: int = 0
    daily_cap: int | None = None
    active: bool = True
    busy: Busy = field(default_factory=Busy)
    count: int = 0  # bookings of this calendar from ROLLING_DAYS back (round robin fairness)
    per_day: Counter = field(default_factory=Counter)  # this calendar's bookings by local date
    windows: list[tuple[datetime, datetime]] = field(default_factory=list)
    window_starts: list[datetime] = field(default_factory=list)

    def prepare(self, lo: datetime, hi: datetime) -> None:
        self.windows = windows(self.weekly, self.overrides, self.tz, lo, hi) if self.has_hours else []
        self.window_starts = [w[0] for w in self.windows]

    def covers(self, start: datetime, end: datetime) -> bool:
        i = bisect_right(self.window_starts, start) - 1
        return i >= 0 and end <= self.windows[i][1]


@dataclass
class Item:
    """A resource a calendar needs: what it has, how much one booking takes, and the use already booked. A resource
    without hours (`person.has_hours` False) is open all the time."""
    person: Person
    quantity: int
    need: int
    usage: Busy = field(default_factory=Busy)


@dataclass
class Snapshot:
    calendar: Calendar
    tz: ZoneInfo
    hosts: list[Person]
    resources: list[Item] = field(default_factory=list)
    per_day: Counter = field(default_factory=Counter)  # the calendar's bookings by date in its own zone
    slots: Counter = field(default_factory=Counter)  # class seats taken, by (start, end)

    def prepare(self, lo: datetime, hi: datetime) -> None:
        for person in [*self.hosts, *(i.person for i in self.resources)]:
            person.prepare(lo, hi)

    def add(self, start: datetime, end: datetime, hosts: list[uuid.UUID]) -> None:
        """Counts a booking that is not in the database (a simulated one) as if it were."""
        cal = self.calendar
        span = Span(start, end, cal.buffer_before, cal.buffer_after, cal.id)
        for host in self.hosts:
            if host.user_id in hosts:
                host.busy.add(span)
                host.count += 1
                host.per_day[start.astimezone(host.tz).date()] += 1
        for item in self.resources:
            item.usage.add(span._replace(quantity=item.need))
        self.per_day[start.astimezone(self.tz).date()] += 1
        self.slots[(start, end)] += 1


# --- the rules ----------------------------------------------------------------------------------------------------

def midnight(day: date, tz: ZoneInfo) -> datetime:
    return local_time(day, 0, tz)


def on_grid(snap: Snapshot, start: datetime) -> bool:
    day = start.astimezone(snap.tz).date()
    first = midnight(day, snap.tz)
    inside = first <= start < midnight(day + timedelta(days=1), snap.tz)
    return inside and (start - first) % timedelta(minutes=snap.calendar.slot_interval) == timedelta(0)


def clash(span: Span, start: datetime, end: datetime, before: int, after: int) -> str | None:
    """How `span` stops a booking of [start, end) whose calendar has these buffers: `booking` (or `busy`) when they
    overlap, `buffer_after` or `buffer_before` when only a buffer is in the way (the span ends just before the start,
    or begins just after the end), None when it does not matter."""
    if span.start < end and start < span.end:
        return span.kind
    if span.end <= start < span.end + timedelta(minutes=max(span.after, before)):
        return "buffer_after"
    if span.start >= end > span.start - timedelta(minutes=max(span.before, after)):
        return "buffer_before"
    return None


def host_reasons(snap: Snapshot, host: Person, start: datetime, end: datetime) -> list[Reason]:
    cal, out, uid = snap.calendar, [], host.user_id
    if not host.active:
        return [Reason("inactive", uid)]
    if host.weight == 0 and cal.kind != "collective":
        out.append(Reason("no_rotation", uid))
    if not host.has_hours:
        out.append(Reason("no_hours", uid))
    elif not host.covers(start, end):
        day = start.astimezone(host.tz).date()
        out.append(Reason("day_off" if not ranges_of(host.weekly, host.overrides, day) else "outside_hours", uid, day))
    for span in host.busy.near(start, end):
        if cal.kind == "class" and span.calendar_id == cal.id and (span.start, span.end) == (start, end):
            continue  # another seat of the same class
        if how := clash(span, start, end, cal.buffer_before, cal.buffer_after):
            out.append(Reason(how, uid, span))
    if cal.kind == "class" and snap.slots[(start, end)] >= cal.seats:
        out.append(Reason("full", uid))
    if host.daily_cap and host.per_day[start.astimezone(host.tz).date()] >= host.daily_cap:
        out.append(Reason("host_cap", uid, host.daily_cap))
    return out


def global_reasons(snap: Snapshot, start: datetime, end: datetime, now: datetime) -> list[Reason]:
    cal, out = snap.calendar, []
    if cal.status != "active":
        out.append(Reason("paused"))
    if not any(h.active for h in snap.hosts):
        out.append(Reason("no_hosts"))
    if start < now + timedelta(minutes=cal.min_notice):
        out.append(Reason("too_soon", a=cal.min_notice))
    if start > now + timedelta(days=cal.window_days):
        out.append(Reason("too_far", a=cal.window_days))
    if not on_grid(snap, start):
        out.append(Reason("off_grid", a=cal.slot_interval))
    if cal.max_per_day and snap.per_day[start.astimezone(snap.tz).date()] >= cal.max_per_day:
        out.append(Reason("calendar_cap", a=cal.max_per_day))
    for item in snap.resources:
        person = item.person
        if person.has_hours and not person.covers(start, end):
            out.append(Reason("resource_closed", person.user_id, person.name))
        used = sum(s.quantity for s in item.usage.near(start, end)
                   if clash(s, start, end, cal.buffer_before, cal.buffer_after))
        if used + item.need > item.quantity:
            out.append(Reason("resource_full", person.user_id, person.name, (used, item.quantity)))
    return out


class Verdict(NamedTuple):
    offered: bool
    reasons: list[Reason]  # about the time itself
    hosts: dict[uuid.UUID, list[Reason]]  # per host; an empty list is a host who is free
    free: list[Person]


def judge(snap: Snapshot, start: datetime, end: datetime, now: datetime) -> Verdict:
    """Whether the time can be booked, and every reason it cannot: those of the time, and per host. A collective
    calendar needs every active host free; the others need one."""
    reasons = global_reasons(snap, start, end, now)
    hosts = {h.user_id: host_reasons(snap, h, start, end) for h in snap.hosts}
    free = [h for h in snap.hosts if not hosts[h.user_id]]
    active = [h for h in snap.hosts if h.active]
    ok = bool(active) and (len(free) == len(active) if snap.calendar.kind == "collective" else bool(free))
    return Verdict(ok and not reasons, reasons, hosts, free)


def candidates(snap: Snapshot, lo: datetime, hi: datetime):
    """Grid start times from lo to hi, earliest first, in UTC. The grid restarts at midnight of each day of the
    calendar's zone and steps in real minutes, so a day with 25 hours has all 25 and one with 23 has no clock hour that
    does not exist."""
    step = timedelta(minutes=snap.calendar.slot_interval)
    day = lo.astimezone(snap.tz).date()
    while (first := midnight(day, snap.tz)) < hi:
        stop = min(midnight(day + timedelta(days=1), snap.tz), hi)
        t = first + max(0, -((first - lo) // step)) * step
        while t < stop:
            yield t
            t += step
        day += timedelta(days=1)


def open_slots(snap: Snapshot, lo: datetime, hi: datetime, now: datetime, duration: int):
    """(start, verdict) for every offered start time in [lo, hi), earliest first."""
    snap.prepare(lo - timedelta(days=1), hi + timedelta(minutes=duration))
    length = timedelta(minutes=duration)
    for start in candidates(snap, max(lo, now), hi):
        verdict = judge(snap, start, start + length, now)
        if verdict.offered:
            yield start, verdict


def check(snap: Snapshot, start: datetime, duration: int, now: datetime) -> Verdict:
    """`judge` for one chosen time, which is how a booking is checked again just before it is saved."""
    snap.prepare(start - timedelta(days=1), start + timedelta(minutes=duration, days=1))
    return judge(snap, start, start + timedelta(minutes=duration), now)


# --- saying it in words -------------------------------------------------------------------------------------------

def clock(at: datetime, tz: ZoneInfo) -> str:
    return at.astimezone(tz).strftime("%H:%M")


TEXT = {
    "paused": "The calendar is paused", "no_hosts": "The calendar has no active hosts",
    "too_far": "Too far ahead: bookings open {a} days ahead",
    "off_grid": "Not a start time: they come every {a} minutes from midnight in {zone}",
    "calendar_cap": "The calendar already has {a} bookings that day, its limit",
    "resource_closed": "{a} is closed then", "resource_full": "{a} capacity reached ({b[0]} of {b[1]} in use)",
    "inactive": "{who} is paused on this calendar", "no_rotation": "{who} has weight 0, so gets no bookings",
    "no_hours": "{who} has no working hours set", "full": "The class is full ({seats} seats)",
    "host_cap": "{who} has reached {a} bookings that day", "day_off": "{who} is off on {a:%A %d %B}",
    "too_soon": "Too soon: bookings need {a} minutes of notice",
}


def message(reason: Reason, snap: Snapshot, tz: ZoneInfo, people: dict[uuid.UUID, Person]) -> str:
    """One sentence for a reason, with times on the clock of `tz`."""
    code, host, a, b = reason
    person = people.get(host)
    who = person.name if person else ""
    if code in TEXT:
        if code == "too_soon" and a == 0:
            return "In the past"
        return TEXT[code].format(a=a, b=b, who=who, zone=snap.calendar.time_zone, seats=snap.calendar.seats)
    if code == "outside_hours":
        hours = ", ".join(f"{s} to {e}" for s, e in ranges_of(person.weekly, person.overrides, a))
        return f"Outside {who}'s hours (works {hours} on {a:%A}, {person.tz.key})"
    when = clock(a.start, tz)
    if code == "busy":
        return f"{who} is busy in a connected calendar from {when} to {clock(a.end, tz)}"
    if code in ("buffer_after", "buffer_before"):
        return f"Buffer {code.removeprefix('buffer_')} the {when} booking"
    return f"{who} has a booking from {when} to {clock(a.end, tz)}"


def explain(snap: Snapshot, start: datetime, duration: int, now: datetime, tz: ZoneInfo) -> dict:
    """Why a time is or is not offered: the reasons of the time itself and, per host, whether they are free and what
    stops them. Written for the "why is this slot hidden" screen, so every sentence is a fact the user can act on."""
    verdict = check(snap, start, duration, now)
    people = {h.user_id: h for h in snap.hosts} | {i.person.user_id: i.person for i in snap.resources}

    def say(r: Reason) -> dict:
        return {"code": r.code, "message": message(r, snap, tz, people)}

    return {"start": start, "end": start + timedelta(minutes=duration), "offered": verdict.offered,
            "reasons": [say(r) for r in verdict.reasons],
            "hosts": [{"user_id": h.user_id, "name": h.name, "free": not verdict.hosts[h.user_id],
                       "reasons": [say(r) for r in verdict.hosts[h.user_id]]} for h in snap.hosts]}


# --- the one query ------------------------------------------------------------------------------------------------

def person_from(user_id: uuid.UUID, name: str, row: Availability | None, **kw) -> Person:
    """A host or resource from its hours row, if it has one. A resource with no row is open all the time; a host with
    no row, or a row with no hours in it (one that only carries sync health), has no hours."""
    kw.setdefault("has_hours", row is not None)
    return Person(user_id, name, zone(row.time_zone) if row else UTC, row.weekly if row else {},
                  row.overrides if row else {}, **kw)


def worked(row: Availability | None) -> bool:
    return row is not None and (any(row.weekly.values()) or any(row.overrides.values()))


def load(db: Session, cal: Calendar, lo: datetime, hi: datetime, now: datetime, *,
         ignore: uuid.UUID | None = None) -> Snapshot:
    """Reads what the rules need to judge times between lo and hi: the calendar's hosts and their hours, the bookings
    and outside busy blocks around that range, the resources and their use. `ignore` leaves one booking out, the one
    being moved."""
    tz = zone(cal.time_zone)
    rows = db.execute(
        select(CalendarHost, User.name, Availability).join(User, User.id == CalendarHost.user_id)
        .outerjoin(Availability, (Availability.user_id == CalendarHost.user_id)
                   & (Availability.workspace_id == cal.workspace_id))
        .where(CalendarHost.calendar_id == cal.id).order_by(CalendarHost.created_at, CalendarHost.id)).all()
    hosts = {h.user_id: person_from(h.user_id, name, row, weight=h.weight, priority=h.priority,
                                    daily_cap=h.daily_cap, active=h.active, has_hours=worked(row))
             for h, name, row in rows}
    snap = Snapshot(cal, tz, list(hosts.values()))
    span_lo, span_hi = lo - timedelta(days=1), hi + timedelta(days=1)
    spans: dict[uuid.UUID, list[Span]] = {u: [] for u in hosts}
    since = now - timedelta(days=ROLLING_DAYS)
    bookings = db.execute(select(
        Booking.id, Booking.calendar_id, Booking.host_ids, Booking.starts_at, Booking.ends_at, Booking.buffer_before,
        Booking.buffer_after).where(
        Booking.host_ids.overlap(list(hosts)), Booking.status != "cancelled", Booking.id != ignore,
        Booking.ends_at > min(span_lo, since), Booking.starts_at < span_hi)).all()
    for id_, calendar_id, attending, start, end, before, after in bookings:
        span = Span(start, end, before, after, calendar_id, booking_id=id_)
        for user_id in attending:
            if user_id in hosts:
                spans[user_id].append(span)
                if calendar_id == cal.id:
                    host = hosts[user_id]
                    host.count += start >= since
                    host.per_day[start.astimezone(host.tz).date()] += 1
        if calendar_id == cal.id:
            snap.per_day[start.astimezone(tz).date()] += 1
            snap.slots[(start, end)] += 1
    for user_id, start, end in db.execute(select(BusyBlock.user_id, BusyBlock.starts_at, BusyBlock.ends_at).where(
            BusyBlock.user_id.in_(list(hosts)), BusyBlock.ends_at > span_lo, BusyBlock.starts_at < span_hi)):
        spans[user_id].append(Span(start, end, kind="busy"))
    for user_id, found in spans.items():
        hosts[user_id].busy = Busy(found)
    load_resources(db, snap, span_lo, span_hi, ignore)
    return snap


def load_resources(db: Session, snap: Snapshot, lo: datetime, hi: datetime, ignore: uuid.UUID | None) -> None:
    rows = db.execute(
        select(CalendarResource.quantity, Resource, Availability)
        .join(Resource, Resource.id == CalendarResource.resource_id)
        .outerjoin(Availability, Availability.resource_id == Resource.id)
        .where(CalendarResource.calendar_id == snap.calendar.id).order_by(Resource.name, Resource.id)).all()
    items = {r.id: Item(person_from(r.id, r.name, row), r.quantity, need) for need, r, row in rows}
    if not items:
        return
    used: dict[uuid.UUID, list[Span]] = {r: [] for r in items}
    for resource_id, quantity, start, end, before, after, calendar_id in db.execute(
            select(BookingResource.resource_id, BookingResource.quantity, Booking.starts_at, Booking.ends_at,
                   Booking.buffer_before, Booking.buffer_after, Booking.calendar_id)
            .join(Booking, Booking.id == BookingResource.booking_id)
            .where(BookingResource.resource_id.in_(list(items)), Booking.status != "cancelled", Booking.id != ignore,
                   Booking.ends_at > lo, Booking.starts_at < hi)):
        used[resource_id].append(Span(start, end, before, after, calendar_id, quantity))
    for resource_id, item in items.items():
        item.usage = Busy(used[resource_id])
    snap.resources = list(items.values())
