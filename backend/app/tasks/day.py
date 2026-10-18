"""My Day (module 11): what one person has to do today, from every module that has something to say. Each module adds a
section with `@section("name")`; a section is a function of the request and the reader's time zone that returns JSON,
and the response holds one key per section. Tasks are the first; appointments (module 16) and assigned conversations
(module 12) add theirs when they exist."""
from collections.abc import Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import Date, cast, func, select

from ..security import Ctx, in_workspace
from . import due, store
from .models import Task
from .routes import tz_param

router = APIRouter(prefix="/api/v1")
SECTIONS: dict[str, Callable[[Ctx, ZoneInfo], dict]] = {}
LIMIT = 100  # a day with more than this overdue is a list to triage, not to read


def section(name: str):
    def register(fn):
        SECTIONS[name] = fn
        return fn
    return register


@section("tasks")
def my_tasks(c: Ctx, zone: ZoneInfo) -> dict:
    """My open tasks that are overdue (oldest first) and due today, and how many I finished today."""
    mine = (Task.workspace_id == c.workspace.id, Task.assignee_id == c.user_id)

    def open_tasks(condition):
        stmt = select(Task).where(*mine, Task.status == "open", condition(zone.key))
        return list(c.db.scalars(stmt.order_by(Task.due_at, Task.position, Task.id).limit(LIMIT)))

    late, soon = open_tasks(due.overdue), open_tasks(due.due_today)
    finished = c.db.scalar(select(func.count()).select_from(Task).where(
        *mine, Task.status == "done", cast(func.timezone(zone.key, Task.completed_at), Date) == due.today(zone.key)))
    shown = store.decorate(c.db, late + soon)
    return {"overdue": shown[:len(late)], "today": shown[len(late):],
            "counts": {"overdue": len(late), "today": len(soon), "done_today": finished}}


@router.get("/my-day")
def my_day(c: Ctx = Depends(in_workspace), zone: ZoneInfo = Depends(tz_param)):
    today = c.db.scalar(select(due.today(zone.key)))
    return {"date": today, "timezone": zone.key, **{name: fn(c, zone) for name, fn in SECTIONS.items()}}
