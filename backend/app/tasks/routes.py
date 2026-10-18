"""Tasks API: /api/v1/tasks. List with filters and a cursor (manual order), create, change, finish and reopen (finishing
a recurring task creates the next one), delete, bulk finish or assign, and move one in the manual order. Reading is
`tasks.read`, writing `tasks.write` and deleting `tasks.delete`; `GET /api/v1/my-day` is in `day`."""
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints
from sqlalchemy import select, tuple_

from ..api import ApiError, Idem, idempotency, seal, unseal
from ..permissions import requires
from ..security import Ctx
from . import due, store
from .models import PRIORITIES, Task

router = APIRouter(prefix="/api/v1/tasks")
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Notes = Annotated[str, StringConstraints(max_length=20000)]
Priority = Literal[PRIORITIES]
Recurrence = Annotated[str, StringConstraints(max_length=200)]


class NewTask(BaseModel):
    title: Title
    notes: Notes = ""
    due_at: AwareDatetime | None = None
    all_day: bool = False
    assignee_id: uuid.UUID | None = None
    priority: Priority = "none"
    record_id: uuid.UUID | None = None
    recurrence: Recurrence | None = None
    depends_on_task_id: uuid.UUID | None = None


class PatchTask(BaseModel):
    """Sets what is sent and leaves the rest; null clears the nullable ones."""
    title: Title | None = None
    notes: Notes | None = None
    due_at: AwareDatetime | None = None
    all_day: bool | None = None
    assignee_id: uuid.UUID | None = None
    priority: Priority | None = None
    record_id: uuid.UUID | None = None
    recurrence: Recurrence | None = None
    depends_on_task_id: uuid.UUID | None = None


class Bulk(BaseModel):
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=200)]
    action: Literal["complete", "assign"]
    assignee_id: uuid.UUID | None = None  # assign: null unassigns


class Move(BaseModel):
    before_id: uuid.UUID | None = None  # the task to go in front of; null: last


def tz_param(tz: Annotated[str | None, Query(max_length=64)] = None):
    """The reader's IANA time zone ("Europe/Paris"), which decides what today is; UTC when absent."""
    return store.zone(tz)


@router.get("")
def list_tasks(assignee: Annotated[str, Query(description="me, anyone, unassigned or a user id")] = "anyone",
               status: Literal["open", "done"] | None = None,
               due_bucket: Annotated[Literal["overdue", "today", "upcoming", "none"] | None, Query(alias="due")] = None,
               due_after: AwareDatetime | None = None, due_before: AwareDatetime | None = None,
               completed_after: AwareDatetime | None = None, record_id: uuid.UUID | None = None,
               limit: int = Query(50, ge=1, le=200), cursor: str | None = None, zone=Depends(tz_param),
               c: Ctx = Depends(requires("tasks.read"))):
    """Tasks in their manual order. `due` is the bucket in the caller's `tz`; `due_after` and `due_before` take a
    range for a calendar; `completed_after` limits finished tasks to recent ones."""
    stmt = select(Task).where(Task.workspace_id == c.workspace.id)
    if assignee == "me":
        stmt = stmt.where(Task.assignee_id == c.user_id)
    elif assignee == "unassigned":
        stmt = stmt.where(Task.assignee_id.is_(None))
    elif assignee != "anyone":
        try:
            stmt = stmt.where(Task.assignee_id == uuid.UUID(assignee))
        except ValueError:
            raise ApiError(422, "validation_failed", "The request is not valid",
                           {"assignee": "must be me, anyone, unassigned or a user id"}) from None
    if status:
        stmt = stmt.where(Task.status == status)
    if due_bucket:
        stmt = stmt.where(due.BUCKETS[due_bucket](due.today(zone)))
    if due_after:
        stmt = stmt.where(Task.due_at >= due_after)
    if due_before:
        stmt = stmt.where(Task.due_at < due_before)
    if completed_after:
        stmt = stmt.where(Task.completed_at >= completed_after)
    if record_id:
        stmt = stmt.where(Task.record_id == record_id)
    if cursor:
        try:
            position, last = unseal(cursor)
            stmt = stmt.where(tuple_(Task.position, Task.id) > tuple_(float(position), uuid.UUID(last)))
        except (ValueError, TypeError):
            raise ApiError(400, "invalid_cursor", "The cursor is not valid") from None
    rows = c.db.scalars(stmt.order_by(Task.position, Task.id).limit(limit + 1)).all()
    page = rows[:limit]
    return {"data": store.decorate(c, page),
            "next_cursor": seal([page[-1].position, str(page[-1].id)]) if len(rows) > limit else None}


@router.post("", status_code=201)
def create_task(body: NewTask, c: Ctx = Depends(requires("tasks.write")), idem: Idem = Depends(idempotency)):
    t = store.create(c, body.model_dump())
    return idem.commit(201, store.decorate(c, [t])[0])


@router.get("/{task_id}")
def get_task(task_id: uuid.UUID, c: Ctx = Depends(requires("tasks.read"))):
    return store.decorate(c, [store.get(c, task_id)])[0]


@router.patch("/{task_id}")
def update_task(task_id: uuid.UUID, body: PatchTask, c: Ctx = Depends(requires("tasks.write"))):
    sent = body.model_dump(exclude_unset=True)
    if nulls := [k for k in ("title", "notes", "all_day", "priority") if k in sent and sent[k] is None]:
        raise ApiError(422, "validation_failed", "The request is not valid", {k: "cannot be null" for k in nulls})
    t = store.get(c, task_id, lock=True)
    store.change(c, t, sent)
    c.db.commit()
    return store.decorate(c, [t])[0]


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: uuid.UUID, c: Ctx = Depends(requires("tasks.delete"))):
    store.delete(c, store.get(c, task_id, lock=True))
    c.db.commit()


@router.post("/bulk")
def bulk_tasks(body: Bulk, c: Ctx = Depends(requires("tasks.write")), zone=Depends(tz_param)):
    """Finishes or assigns up to 200 tasks. `data` are the tasks that changed, `skipped` the ones left alone and why
    (a task whose dependency is still open). Ids that are not tasks of this workspace are ignored.
    ponytail: runs in the request; past a few hundred tasks it becomes a job with progress (ADR 0003)."""
    changed, skipped = store.bulk(c, body.ids, body.action, body.assignee_id, zone)
    c.db.commit()
    return {"data": store.decorate(c, changed), "skipped": [{"id": t.id, "title": t.title, "reason": why}
                                                                for t, why in skipped]}


@router.post("/{task_id}/complete")
def complete_task(task_id: uuid.UUID, c: Ctx = Depends(requires("tasks.write")), zone=Depends(tz_param)):
    """Finishes the task; a recurring task also gets its next occurrence (`next`, null when the series has ended).
    409 `task_blocked` while the task it waits for is open. Finishing a finished task changes nothing."""
    t = store.get(c, task_id, lock=True)
    following = store.complete(c, t, zone)
    c.db.commit()
    both = store.decorate(c, [t, *([following] if following else [])])
    return {**both[0], "next": both[1] if following else None}


@router.post("/{task_id}/reopen")
def reopen_task(task_id: uuid.UUID, c: Ctx = Depends(requires("tasks.write"))):
    t = store.get(c, task_id, lock=True)
    store.reopen(c, t)
    c.db.commit()
    return store.decorate(c, [t])[0]


@router.post("/{task_id}/reorder")
def reorder_task(task_id: uuid.UUID, body: Move, c: Ctx = Depends(requires("tasks.write"))):
    t = store.get(c, task_id, lock=True)
    before = store.get(c, body.before_id) if body.before_id else None
    if before is None or before.id != t.id:
        store.move(c, t, before)
    c.db.commit()
    return store.decorate(c, [t])[0]
