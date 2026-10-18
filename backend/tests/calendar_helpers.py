"""Builders for the availability engine's tests: a calendar, hosts and a snapshot made in memory, so the rules run
with no database. Times are written on a wall clock in a zone and turned into UTC instants."""
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.calendars import slots
from app.calendars.models import Calendar

NY, LON = ZoneInfo("America/New_York"), ZoneInfo("Europe/London")
WEEKDAYS_9_TO_5 = {d: [["09:00", "17:00"]] for d in slots.WEEKDAYS[:5]} | {"sat": [], "sun": []}
LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)  # a `now` that leaves every date of the tests open


def calendar(**kw) -> Calendar:
    values = dict(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="Call", slug="call", kind="personal",
                  durations=[30], buffer_before=0, buffer_after=0, min_notice=0, window_days=365, slot_interval=30,
                  max_per_day=None, seats=1, time_zone="America/New_York", status="active", reminders=[1440, 60])
    return Calendar(**{**values, **kw})


def host(name: str, zone: str = "America/New_York", weekly=None, overrides=None, **kw) -> slots.Person:
    return slots.Person(uuid.uuid4(), name, ZoneInfo(zone), WEEKDAYS_9_TO_5 if weekly is None else weekly,
                        overrides or {}, **kw)


def resource(name: str, quantity: int = 1, need: int = 1, weekly=None) -> slots.Item:
    open_all = weekly is None
    person = slots.Person(uuid.uuid4(), name, UTC if open_all else NY, {} if open_all else weekly, {},
                          has_hours=not open_all)
    return slots.Item(person, quantity, need)


def snapshot(cal: Calendar, *hosts: slots.Person, resources=()) -> slots.Snapshot:
    return slots.Snapshot(cal, ZoneInfo(cal.time_zone), list(hosts), list(resources))


def at(day: str, clock: str = "00:00", zone: ZoneInfo = NY) -> datetime:
    """A wall clock time ('2026-10-20', '09:30') in a zone, as a UTC instant."""
    return slots.local_time(date.fromisoformat(day), slots.minutes(clock), zone)


def book(snap: slots.Snapshot, day: str, clock: str, minutes: int = 30, *hosts: slots.Person, zone=NY) -> None:
    """Puts a booking of the snapshot's calendar in it, for these hosts (the first if none)."""
    start = at(day, clock, zone)
    snap.add(start, start + timedelta(minutes=minutes), [h.user_id for h in (hosts or snap.hosts[:1])])


def offered(snap: slots.Snapshot, day: str, duration: int = 30, now: datetime = LONG_AGO,
            zone: ZoneInfo = NY) -> list[str]:
    """The start times offered on a local day, as 'HH:MM' on the clock of `zone`."""
    first = date.fromisoformat(day)
    lo, hi = slots.midnight(first, zone), slots.midnight(first + timedelta(days=1), zone)
    return [s.astimezone(zone).strftime("%H:%M") for s, _ in slots.open_slots(snap, lo, hi, now, duration)]


def starts(snap: slots.Snapshot, day: str, duration: int = 30, now: datetime = LONG_AGO, zone=NY) -> list[datetime]:
    first = date.fromisoformat(day)
    lo, hi = slots.midnight(first, zone), slots.midnight(first + timedelta(days=1), zone)
    return [s for s, _ in slots.open_slots(snap, lo, hi, now, duration)]


def why(snap: slots.Snapshot, day: str, clock: str, duration: int = 30, now: datetime = LONG_AGO,
        zone: ZoneInfo = NY) -> dict:
    return slots.explain(snap, at(day, clock, zone), duration, now, zone)


def messages(answer: dict) -> list[str]:
    """Every sentence of an explanation, the time's and the hosts' together."""
    return [r["message"] for r in answer["reasons"]] + [r["message"] for h in answer["hosts"] for r in h["reasons"]]
