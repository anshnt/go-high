"""What "overdue", "today" and "upcoming" mean, as SQL conditions on `tasks`, for one reader's time zone. A timed task
is overdue once its time has passed; an all-day task (due_at is midnight UTC of its date) once its date has."""
from sqlalchemy import Date, and_, case, cast, func, or_

from .models import Task


def today(zone: str):
    return cast(func.timezone(zone, func.now()), Date)


def local_day(zone: str):
    """The calendar day a task is due: its date for an all-day task, else the day in `zone`."""
    return case((Task.all_day, cast(func.timezone("UTC", Task.due_at), Date)),
                else_=cast(func.timezone(zone, Task.due_at), Date))


def late(zone: str):
    return case((Task.all_day, local_day(zone) < today(zone)), else_=Task.due_at < func.now())


def overdue(zone: str):
    return and_(Task.status == "open", Task.due_at.is_not(None), late(zone))


def due_today(zone: str):
    """Due today and not overdue yet (a finished task counts whatever the time)."""
    return and_(Task.due_at.is_not(None), local_day(zone) == today(zone), or_(Task.status == "done", ~late(zone)))


def upcoming(zone: str):
    return and_(Task.due_at.is_not(None), local_day(zone) > today(zone))


def no_date(zone: str):
    return Task.due_at.is_(None)


BUCKETS = {"overdue": overdue, "today": due_today, "upcoming": upcoming, "none": no_date}
