"""What "overdue", "today" and "upcoming" mean, as SQL conditions on `tasks`, for one reader's time zone. A timed task
is overdue once its time has passed; an all-day task (due_at is midnight UTC of its date) once its date has.
The zone is applied here, in Python, to find where the reader's day starts and ends as instants: Postgres never sees a
zone name, so a name it does not know (an old alias such as Asia/Calcutta) cannot break a query."""
from datetime import UTC, date, datetime, time, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, or_

from .models import Task


class Today(NamedTuple):
    date: date  # the reader's calendar date
    start: datetime  # local midnight that begins it, as an instant
    end: datetime  # local midnight that ends it


def today(zone: ZoneInfo) -> Today:
    day = datetime.now(zone).date()

    def midnight(d: date) -> datetime:
        return datetime.combine(d, time.min, zone).astimezone(UTC)

    return Today(day, midnight(day), midnight(day + timedelta(days=1)))


def utc_midnight(day: date) -> datetime:
    """How an all-day task due on `day` is stored."""
    return datetime.combine(day, time.min, UTC)


def late(t: Today):
    return case((Task.all_day, Task.due_at < utc_midnight(t.date)), else_=Task.due_at < func.now())


def overdue(t: Today):
    return and_(Task.status == "open", Task.due_at.is_not(None), late(t))


def due_today(t: Today):
    """Due today and not overdue yet (a finished task counts whatever the time)."""
    midnight, next_midnight = utc_midnight(t.date), utc_midnight(t.date + timedelta(days=1))
    this_day = case((Task.all_day, and_(Task.due_at >= midnight, Task.due_at < next_midnight)),
                    else_=and_(Task.due_at >= t.start, Task.due_at < t.end))
    return and_(Task.due_at.is_not(None), this_day, or_(Task.status == "done", ~late(t)))


def upcoming(t: Today):
    return and_(Task.due_at.is_not(None), case((Task.all_day, Task.due_at >= utc_midnight(t.date + timedelta(days=1))),
                                              else_=Task.due_at >= t.end))


def no_date(t: Today):
    return Task.due_at.is_(None)


BUCKETS = {"overdue": overdue, "today": due_today, "upcoming": upcoming, "none": no_date}
