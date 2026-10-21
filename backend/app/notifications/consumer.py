"""Turns events into notifications, one batch of the event log at a time (an `events.consumer`, like the webhook
fan-out), and the job that says a task is due. Runs in the worker, as the owner role.

Who hears about an event is each person's own rule for its kind (`notification_prefs`): the person it concerns hears
about it unless they switched the in-app channel off, and anyone whose scope for that kind is "all" hears about every
one in the workspace they may see (`sees`: the record in their role's scope with its name readable, or tasks.read for a
task). Nobody is told about what they did themselves. Quiet hours hold a notification back until they
end (it is dated then, and not listed before). A notification is created once per event or due time (`dedupe_key`).

ponytail: email, web push and the digest are not sent; the channel and digest settings are stored for the email module.
ponytail: a mention (module 12) is one more entry in KINDS and one more branch in `drafts`."""
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .. import events, jobs, permissions
from ..compliance import quiet_until
from ..events import Event
from ..models import User, Workspace
from ..records.models import Record
from ..records.schema import Catalog
from ..records.store import scope
from ..security import Ctx
from ..tasks.models import Task
from ..tenancy import effective_role
from ..usage import notify as billing_notice
from .models import Notification, NotificationPref

# kind: what the setting is called (shown in Settings > Notifications)
KINDS = {"task_assigned": "A task is assigned to you", "task_due": "A task you own is due",
         "record_assigned": "A record is assigned to you", "workflow": "A workflow notifies you",
         "billing": "The wallet runs low, usage nears the monthly cap or a top-up fails (billing managers)"}


@dataclass
class Draft:
    """One thing to tell people: `person` is who it concerns (if anyone), the rest is the text and what it is about."""
    kind: str
    workspace_id: uuid.UUID
    person: uuid.UUID | None
    actor_id: uuid.UUID | None
    to_person: str
    to_others: str
    body: str
    link: str
    subject: tuple[str, uuid.UUID]
    key: str


def people(db: Session, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    return dict(db.execute(select(User.id, User.name).where(User.id.in_([i for i in ids if i]))).all())


def task_link(task_id: str) -> str:
    return f"/tasks?task={task_id}"


PLURALS = {"contact": "contacts", "company": "companies", "deal": "deals"}


def record_link(object_key: str, record_id: str) -> str:
    """Where the record screens open it: the system objects at /contacts, /companies and /deals, a custom one under
    /objects."""
    return f"/{PLURALS[object_key]}/{record_id}" if object_key in PLURALS else f"/objects/{object_key}/{record_id}"


def drafts(e: Event, names: dict[uuid.UUID, str]) -> list[Draft]:
    d, actor = e.data, "A workflow" if e.actor_type == "workflow" else names.get(e.actor_id, "Someone")
    if e.type in ("task.created", "task.updated"):
        new = d["assignee_id"] if e.type == "task.created" else (d["changes"].get("assignee_id") or {}).get("new")
        if not new or (e.type == "task.created" and d.get("parent_task_id")):  # a repeat's next one is no assignment
            return []
        who = uuid.UUID(new)
        return [Draft("task_assigned", e.workspace_id, who, e.actor_id, f"{actor} assigned you a task",
                      f"{actor} assigned a task to {names.get(who, 'someone')}", d["title"], task_link(d["id"]),
                      ("task", e.subject_id), f"task_assigned:{e.id}")]
    if e.type in ("record.created", "record.updated"):
        new = d["owner_id"] if e.type == "record.created" else (d["changes"].get("owner_id") or {}).get("new")
        if not new:
            return []
        who = uuid.UUID(new)
        return [Draft("record_assigned", e.workspace_id, who, e.actor_id, f"{actor} assigned you {d['display_name']}",
                      f"{actor} assigned {d['display_name']} to {names.get(who, 'someone')}",
                      f"You are now the owner of this {d['object']}.", record_link(d["object"], d["id"]),
                      ("record", e.subject_id), f"record_assigned:{e.id}")]
    return []


def preference(db: Session, cache: dict, workspace_id: uuid.UUID, user_id: uuid.UUID, kind: str) -> NotificationPref:
    """The person's rule for a kind, or the default one (in-app, only what concerns them)."""
    key = (workspace_id, user_id, kind)
    if key not in cache:
        cache[key] = db.get(NotificationPref, (user_id, workspace_id, kind)) or NotificationPref(
            user_id=user_id, workspace_id=workspace_id, kind=kind, channels=["in_app"], scope="mine", digest="off")
    return cache[key]


def watchers(db: Session, cache: dict, workspace_id: uuid.UUID, kind: str) -> list[uuid.UUID]:
    """Everyone in the workspace who asked to hear about every notification of this kind."""
    key = (workspace_id, None, kind)
    if key not in cache:
        cache[key] = list(db.scalars(select(NotificationPref.user_id).where(
            NotificationPref.workspace_id == workspace_id, NotificationPref.kind == kind,
            NotificationPref.scope == "all")))
    return cache[key]


def shows_at(pref: NotificationPref, now: datetime) -> datetime | None:
    """The end of the person's quiet hours when it is quiet now; None when it is not."""
    if pref.quiet_start is None or pref.quiet_end is None:
        return None
    return quiet_until(now, pref.tz or "UTC", pref.quiet_start.isoformat(), pref.quiet_end.isoformat())


def sees(db: Session, cache: dict, draft: Draft, user_id: uuid.UUID) -> bool:
    """Whether a watcher may see what the draft is about, decided by the functions the API runs, on a request made up
    for them: a task needs tasks.read, a record must be in their scope with its name (`display_name`) readable."""
    key = ("sees", user_id, draft.subject)
    if key not in cache:
        ws = db.get(Workspace, draft.workspace_id)
        found = effective_role(db, user_id, ws)
        ctx = found and Ctx(db, user_id, uuid.uuid4(), "", ws, None, found[0], found[1])
        if ctx is None:
            cache[key] = False
        elif draft.subject[0] == "task":
            cache[key] = "tasks.read" in permissions.grants(ctx).capabilities
        else:
            rec = db.get(Record, draft.subject[1])
            cat = Catalog(ctx)
            obj = rec and cat.by_id(rec.object_id)
            cache[key] = bool(obj and "display_name" not in permissions.hidden(ctx, obj) and db.scalar(
                select(exists().where(Record.id == rec.id, scope(cat, obj)))))
    return cache[key]


def deliver(db: Session, cache: dict, draft: Draft) -> None:
    now = datetime.now(UTC)
    wanted = {draft.person: True} if draft.person else {}
    for user_id in watchers(db, cache, draft.workspace_id, draft.kind):
        wanted.setdefault(user_id, False)
    for user_id, concerned in wanted.items():
        pref = preference(db, cache, draft.workspace_id, user_id, draft.kind)
        if user_id == draft.actor_id or "in_app" not in pref.channels or not (
                concerned or sees(db, cache, draft, user_id)):
            continue
        show_at = shows_at(pref, now)
        db.execute(pg_insert(Notification).values(
            workspace_id=draft.workspace_id, user_id=user_id, kind=draft.kind,
            title=draft.to_person if concerned else draft.to_others, body=draft.body, link=draft.link,
            subject_type=draft.subject[0], subject_id=draft.subject[1], dedupe_key=draft.key,
            created_at=show_at if show_at else func.clock_timestamp()).on_conflict_do_nothing(
                index_elements=["user_id", "dedupe_key"]))


def billing(db: Session, cache: dict, e: Event) -> None:
    """A wallet alert, for each person who manages billing in the workspace."""
    title, body = billing_notice.text(e)
    for person in billing_notice.billing_people(db, e.workspace_id):
        deliver(db, cache, Draft("billing", e.workspace_id, person, None, title, title, body, billing_notice.LINK,
                                 ("wallet", e.subject_id), f"billing:{e.id}"))


@events.consumer("notifications")
def from_events(db: Session, batch: list[Event]) -> None:
    cache: dict = {}
    for e in batch:
        if e.type in billing_notice.TYPES:
            billing(db, cache, e)
    mine = [e for e in batch if e.type in ("task.created", "task.updated", "record.created", "record.updated")]
    if not mine:
        return
    ids = {e.actor_id for e in mine} | {uuid.UUID(v) for e in mine for v in (
        e.data.get("assignee_id"), e.data.get("owner_id"),
        *((e.data.get("changes") or {}).get(k, {}).get("new") for k in ("assignee_id", "owner_id"))) if v}
    names = people(db, ids)
    for e in mine:
        for draft in drafts(e, names):
            deliver(db, cache, draft)


@jobs.handler("task.due")
def due(db: Session, payload: dict) -> None:
    """Tells the assignee that a task is due. Does nothing when the task is gone, finished, unassigned or has been
    given another due time (that one has its own job), and a second run cannot notify twice."""
    task = db.get(Task, uuid.UUID(payload["task_id"]))
    if (task is None or task.status != "open" or task.all_day or not task.assignee_id or task.due_at is None
            or task.due_at != datetime.fromisoformat(payload["due_at"]) or task.due_at > datetime.now(UTC)):
        return
    names = people(db, {task.assignee_id})
    draft = Draft("task_due", task.workspace_id, task.assignee_id, None, f"Due now: {task.title}",
                  f"Due now: {task.title}", f"Assigned to {names.get(task.assignee_id, 'someone')}",
                  task_link(str(task.id)), ("task", task.id), f"task_due:{task.id}:{task.due_at.isoformat()}")
    deliver(db, {}, draft)
