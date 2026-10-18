"""The write path of tasks: validate, save, emit the event in the same transaction. Routes, bulk changes and the
recurrence of a completed task all go through here. Tasks are visible to the whole workspace.
ponytail: a task is the workspace's whatever record it links to; only that record's name follows ADR 0004 (`named`)."""
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select, update

from .. import events, jobs, permissions
from ..api import ApiError
from ..records import store as records
from ..records.models import Record
from ..records.schema import Catalog
from ..security import Ctx
from . import recurrence
from .models import Task

GAP = 1024.0  # distance between neighbours when a task goes first or last
FIELDS = ("title", "notes", "due_at", "all_day", "assignee_id", "priority", "record_id", "recurrence",
          "depends_on_task_id")
STATE = ("id", "title", "notes", "due_at", "all_day", "assignee_id", "created_by", "priority", "status", "completed_at",
         "record_id", "recurrence", "parent_task_id", "depends_on_task_id", "position")
NEEDS_DUE = "a repeating task needs a due date"


def invalid(fields: dict[str, str]) -> ApiError:
    return ApiError(422, "validation_failed", "The task is not valid", fields)


def get(c: Ctx, task_id: uuid.UUID, *, lock: bool = False) -> Task:
    stmt = select(Task).where(Task.workspace_id == c.workspace.id, Task.id == task_id)
    task = c.db.scalar(stmt.with_for_update() if lock else stmt)  # and row level security: this workspace's tasks
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


def state(t: Task) -> dict:
    """The event data of a task: its full state."""
    return {k: getattr(t, k) for k in STATE}


def named(c: Ctx, record_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """The linked records the caller may see by name: in their scope, and named by fields they may read. A task on any
    other record shows none (`record` is null), as a list of that kind of record would not show it either."""
    if not record_ids:
        return {}
    cat, shown = Catalog(c), {}
    found = c.db.execute(select(Record.id, Record.object_id, Record.display_name).where(
        Record.workspace_id == c.workspace.id, Record.id.in_(record_ids))).all()
    for object_id in {r.object_id for r in found}:
        obj = cat.by_id(object_id)
        if obj is None or "display_name" in permissions.hidden(c, obj):
            continue
        mine = [r.id for r in found if r.object_id == object_id]
        seen = set(c.db.scalars(select(Record.id).where(Record.id.in_(mine), records.scope(cat, obj))))
        shown |= {r.id: {"id": r.id, "object": obj.key, "display_name": r.display_name}
                  for r in found if r.id in seen}
    return shown


def decorate(c: Ctx, tasks: list[Task]) -> list[dict]:
    """The API shape of tasks, with the linked record's name and the task they wait for."""
    db = c.db
    linked = named(c, {t.record_id for t in tasks if t.record_id})
    dep_ids = {t.depends_on_task_id for t in tasks if t.depends_on_task_id}
    waits = db.execute(select(Task.id, Task.title, Task.status).where(Task.id.in_(dep_ids))).all() if dep_ids else []
    deps = {d.id: {"id": d.id, "title": d.title, "status": d.status} for d in waits}
    return [{**state(t), "record": linked.get(t.record_id), "depends_on": deps.get(t.depends_on_task_id),
             "created_at": t.created_at, "updated_at": t.updated_at} for t in tasks]


def zone(tz: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz or "UTC")
    except (KeyError, ValueError, OSError):
        raise ApiError(422, "validation_failed", "The request is not valid", {"tz": "is not a time zone"}) from None


def normal(due_at: datetime | None, all_day: bool) -> datetime | None:
    """A due time is kept in UTC; an all-day task is due on a date, kept as midnight UTC of that date."""
    if due_at is None:
        return None
    due_at = due_at.astimezone(UTC)
    return due_at.replace(hour=0, minute=0, second=0, microsecond=0) if all_day else due_at


def waits_in_a_circle(c: Ctx, task_id: uuid.UUID | None, start: uuid.UUID) -> bool:
    """Whether `task_id` is already somewhere in the chain of tasks that `start` waits for."""
    seen: set[uuid.UUID] = set()
    while start and start not in seen:
        if start == task_id:
            return True
        seen.add(start)
        start = c.db.scalar(select(Task.depends_on_task_id).where(Task.id == start))
    return False


def check_links(c: Ctx, task: Task | None, new: dict) -> dict[str, str]:
    """Errors for the person, record and task that `new` refers to: they must be of this workspace."""
    errors: dict[str, str] = {}
    if new.get("assignee_id") and not records.member_ids(c, {str(new["assignee_id"])}):
        errors["assignee_id"] = "is not a member of this workspace"
    if new.get("record_id"):
        try:
            records.find(Catalog(c), new["record_id"])
        except HTTPException:
            errors["record_id"] = "is not a record of this workspace"
    if dep := new.get("depends_on_task_id"):
        if c.db.scalar(select(Task.id).where(Task.workspace_id == c.workspace.id, Task.id == dep)) is None:
            errors["depends_on_task_id"] = "is not a task of this workspace"
        elif waits_in_a_circle(c, task.id if task else None, dep):
            errors["depends_on_task_id"] = "would make the tasks wait for each other"
    return errors


def check_rule(text: str | None) -> str | None:
    """The canonical rule text, or a 422 for a rule that is not one of the supported ones."""
    if text is None:
        return None
    try:
        return recurrence.render(recurrence.parse(text))
    except recurrence.RuleError as e:
        raise invalid({"recurrence": str(e)}) from None


def next_position(c: Ctx) -> float:
    top = c.db.scalar(select(func.coalesce(func.max(Task.position), 0)).where(Task.workspace_id == c.workspace.id))
    return top + GAP


def schedule_due(c: Ctx, t: Task) -> None:
    """A job at the due time tells the assignee that the task is due (see notifications.consumer.due). One per due
    time: a job whose task has moved or been finished does nothing.
    ponytail: an all-day task has no time to fire at and there is no workspace time zone yet; a digest can list them."""
    if t.status == "open" and t.assignee_id and t.due_at and not t.all_day and t.due_at > datetime.now(UTC):
        jobs.enqueue(c.db, "task.due", {"task_id": str(t.id), "due_at": t.due_at.isoformat()}, run_at=t.due_at)


def create(c: Ctx, values: dict) -> Task:
    new = {k: values.get(k) for k in FIELDS}
    new["recurrence"] = check_rule(new["recurrence"])
    errors = check_links(c, None, new)
    if new["recurrence"] and new["due_at"] is None:
        errors["recurrence"] = NEEDS_DUE
    if errors:
        raise invalid(errors)
    new["due_at"] = normal(new["due_at"], new["all_day"])
    t = Task(workspace_id=c.workspace.id, created_by=c.user_id, position=next_position(c), **new)
    c.db.add(t)
    c.db.flush()
    events.emit(c.db, "task.created", "task", t.id, state(t), actor=records.actor(c))
    schedule_due(c, t)
    return t


def change(c: Ctx, t: Task, patch: dict) -> bool:
    """Applies a partial change to a locked task; returns whether anything changed (no change, no event)."""
    new = {k: v for k, v in patch.items() if k in FIELDS}
    if "recurrence" in new:
        new["recurrence"] = check_rule(new["recurrence"])
    merged = {k: new.get(k, getattr(t, k)) for k in FIELDS}
    merged["due_at"] = normal(merged["due_at"], merged["all_day"])
    errors = check_links(c, t, {k: v for k, v in merged.items() if v != getattr(t, k)})
    if merged["recurrence"] and merged["due_at"] is None:
        errors["due_at" if "due_at" in new else "recurrence"] = NEEDS_DUE
    if errors:
        raise invalid(errors)
    changes = {k: {"old": getattr(t, k), "new": v} for k, v in merged.items() if getattr(t, k) != v}
    if not changes:
        return False
    save(c, t, changes)
    return True


def save(c: Ctx, t: Task, changes: dict) -> None:
    """Writes `changes` ({field: {"old", "new"}}) to a task, emits task.updated, and re-plans the due reminder."""
    for field, pair in changes.items():
        setattr(t, field, pair["new"])
    t.updated_at = func.now()
    c.db.flush()
    c.db.refresh(t, ["updated_at"])
    events.emit(c.db, "task.updated", "task", t.id, {**state(t), "changes": changes}, actor=records.actor(c))
    if changes.keys() & {"due_at", "all_day", "assignee_id", "status"}:
        schedule_due(c, t)


def blocker(c: Ctx, t: Task) -> Task | None:
    """The task `t` waits for, when that one is not finished."""
    dep = c.db.get(Task, t.depends_on_task_id) if t.depends_on_task_id else None
    return dep if dep is not None and dep.status == "open" else None


def spawn_next(c: Ctx, done: Task, tz: ZoneInfo) -> Task | None:
    """The next occurrence of a finished recurring task, from its rule, or None when the series has ended. The tasks of
    a series point at the first one, which is how COUNT is counted (up to `done`: a task reopened and finished again
    finds its next occurrence already there, and returns that one instead of a second copy).
    ponytail: deleting the first task of a series restarts the count at the next one."""
    root = done.parent_task_id or done.id
    series = (Task.workspace_id == c.workspace.id, Task.parent_task_id == root)
    seen = 1 + c.db.scalar(select(func.count()).select_from(Task).where(*series, Task.due_at <= done.due_at))
    following = recurrence.advance(recurrence.parse(done.recurrence), done.due_at, done.all_day, tz, seen)
    if following is None:
        return None
    due_at, rule = following
    if there := c.db.scalar(select(Task).where(*series, Task.due_at == due_at).limit(1)):
        return there
    t = Task(workspace_id=c.workspace.id, created_by=done.created_by, title=done.title, notes=done.notes,
             due_at=due_at, all_day=done.all_day, assignee_id=done.assignee_id, priority=done.priority,
             record_id=done.record_id, recurrence=recurrence.render(rule), parent_task_id=root,
             position=done.position)
    c.db.add(t)
    c.db.flush()
    events.emit(c.db, "task.created", "task", t.id, state(t), actor=records.actor(c))
    schedule_due(c, t)
    return t


def complete(c: Ctx, t: Task, tz: ZoneInfo) -> Task | None:
    """Finishes a locked task, and creates the next occurrence of a recurring one in the same transaction. A task
    whose dependency is still open answers 409. Finishing a finished task does nothing. Returns the next task."""
    if t.status == "done":
        return None
    wait = blocker(c, t)
    if wait is not None:
        raise ApiError(409, "task_blocked", f"Finish \"{wait.title}\" first: this task waits for it")
    t.status, t.completed_at, t.updated_at = "done", func.now(), func.now()
    c.db.flush()
    c.db.refresh(t, ["completed_at", "updated_at"])
    following = spawn_next(c, t, tz) if t.recurrence else None
    events.emit(c.db, "task.completed", "task", t.id,
                {**state(t), "next_task_id": following.id if following else None}, actor=records.actor(c))
    return following


def reopen(c: Ctx, t: Task) -> bool:
    if t.status == "open":
        return False
    save(c, t, {"status": {"old": "done", "new": "open"}, "completed_at": {"old": t.completed_at, "new": None}})
    return True


def delete(c: Ctx, t: Task) -> None:
    """Removes a task. Tasks that waited for it no longer wait; the rest of its series carries on without its first."""
    waiting = c.db.scalars(select(Task).where(Task.depends_on_task_id == t.id)).all()
    for other in waiting:
        other.depends_on_task_id = None
    c.db.execute(update(Task).where(Task.parent_task_id == t.id).values(parent_task_id=None))
    c.db.flush()
    for other in waiting:
        events.emit(c.db, "task.updated", "task", other.id,
                    {**state(other), "changes": {"depends_on_task_id": {"old": t.id, "new": None}}},
                    actor=records.actor(c))
    c.db.delete(t)
    c.db.flush()
    events.emit(c.db, "task.deleted", "task", t.id, {"id": t.id, "title": t.title}, actor=records.actor(c))


def move(c: Ctx, t: Task, before: Task | None) -> None:
    """Puts `t` just before `before` in the manual order (last when None).
    ponytail: the new position is the midpoint of its neighbours, so about 50 moves into one gap exhaust the float
    precision; renumber the workspace's positions when that shows."""
    others = (Task.workspace_id == c.workspace.id, Task.id != t.id)
    if before is None:
        position = (c.db.scalar(select(func.max(Task.position)).where(*others)) or 0) + GAP
    else:
        before_that = c.db.scalar(select(func.max(Task.position)).where(*others, Task.position < before.position))
        position = before.position - GAP if before_that is None else (before_that + before.position) / 2
    if position != t.position:
        save(c, t, {"position": {"old": t.position, "new": position}})


def bulk(c: Ctx, ids: list[uuid.UUID], action: str, assignee_id: uuid.UUID | None, tz: ZoneInfo):
    """Completes or assigns many tasks. Returns (changed tasks, [(task, reason)] left alone). Ids that are not tasks of
    this workspace are ignored. Completing keeps going while it makes progress, so a task and the one it waits for can
    be selected together."""
    tasks = list(c.db.scalars(select(Task).where(Task.workspace_id == c.workspace.id, Task.id.in_(ids))
                              .order_by(Task.position, Task.id).with_for_update()))
    if action == "assign":
        if assignee_id and not records.member_ids(c, {str(assignee_id)}):
            raise invalid({"assignee_id": "is not a member of this workspace"})
        return [t for t in tasks if change(c, t, {"assignee_id": assignee_id})], []
    done: list[Task] = []
    waiting = [t for t in tasks if t.status == "open"]
    while waiting:
        left = [t for t in waiting if blocker(c, t) is not None]
        for t in waiting:
            if t not in left:
                complete(c, t, tz)
                done.append(t)
        if len(left) == len(waiting):
            break
        waiting = left
    return done, [(t, f"waits for \"{blocker(c, t).title}\"") for t in waiting]
