"""Open start times for a range of days as one visitor sees them: grouped by the day on their own clock. Both the public
page and the app call this, so what is offered and what is bookable are the same list."""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..api import ApiError
from . import slots
from .models import Calendar

MAX_DAYS = 62


def invitee_zone(name: str):
    try:
        return slots.zone(name)
    except ValueError:
        raise ApiError(422, "validation_failed", "The request is not valid", {"tz": "is not a time zone"}) from None


def chosen_duration(cal: Calendar, duration: int | None) -> int:
    duration = duration or cal.durations[0]
    if duration not in cal.durations:
        raise ApiError(422, "validation_failed", "The request is not valid", {"duration": "is not offered"})
    return duration


def slot_days(db: Session, cal: Calendar, first: date, last: date, tz_name: str, duration: int | None, now: datetime,
              ignore=None) -> dict:
    """Start times from `first` to `last` (both days, on the visitor's clock) as UTC instants by local day."""
    tz = invitee_zone(tz_name)
    if last < first or (last - first).days >= MAX_DAYS:
        raise ApiError(422, "validation_failed", "The request is not valid",
                       {"to": f"must be on or after from, and at most {MAX_DAYS} days after it"})
    # moving a booking keeps its length, even one the calendar no longer offers
    length = chosen_duration(cal, duration) if ignore is None else duration
    lo, hi = slots.midnight(first, tz), slots.midnight(last + timedelta(days=1), tz)
    snap = slots.load(db, cal, lo, hi, now, ignore=ignore)
    days: dict[str, list[datetime]] = {}
    for start, _ in slots.open_slots(snap, lo, hi, now, length):
        days.setdefault(start.astimezone(tz).date().isoformat(), []).append(start)
    return {"time_zone": tz_name, "duration": length, "from": first, "to": last, "days": days}
