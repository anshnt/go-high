"""Enrollment (ADR 0006): an events consumer, snapshot-safe like the webhook fan-out and the notifications (`read_batch`
and `advance` in the dispatcher's transaction). For each event about a record it does three things, in this order, so a
run that starts on an event is not also judged by it:

1. resolves the event waits it satisfies (a wait for `message.received` goes on down its `event` branch),
2. jumps runs to a goal whose condition has become true,
3. finds the published workflows whose trigger is this event, judges the record against each trigger (the object, the
   event's data, the filter) and starts a run, logging every check, hits and misses alike, with the clause that failed.

The work for a workspace runs inside `acting`, so row level security confines it as for a request. A bad workflow
(its filter names a field that was archived) is a logged miss, never an exception: one poison event would stop every
consumer behind it. A workflow's own changes never start that workflow, and a paused workflow takes no part at all.
Rows of the check log older than 7 days are pruned as new ones are written.

ponytail: a record is judged by its state when the event is read, not when it happened; an event handled late sees the
later state (a run might start for `record.created` on a contact whose filter only holds since an update).
ponytail: while a workflow is paused its waiters and goals see no events, so an event in that time is not caught."""
import uuid
from datetime import timedelta

from sqlalchemy import delete, exists, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import events, jobs
from ..db import acting
from ..events import Event
from ..inbox.threads import system_ctx
from ..models import Workspace
from ..records import filters
from ..records.models import Record
from ..records.schema import Catalog
from . import engine
from .judge import judge
from .models import ACTIVE, Run, TriggerCheck, Waiter, Workflow, WorkflowVersion
from .schema import TRIGGERS

KEEP = timedelta(days=7)  # the check log: "why did this record not enter" is answerable for a week
HITS = ("entered", "running", "reentry")  # outcomes where the trigger matched


def record_of(e: Event) -> uuid.UUID | None:
    """The record an event is about (`schema.record_key` says where its id is), or None."""
    key = TRIGGERS.get(e.type)
    raw = e.subject_id if key == "subject" else (e.data.get(key) if key else None)
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


def evaluate(cat: Catalog, rec: Record | None, trigger: dict, event: Event | None,
             workflow_id: uuid.UUID) -> tuple[str, str | None]:
    """(outcome, reason): `ok`, or what stopped the record: no_record, object, self, data, filter, error. Without an
    event (an explanation of why a record would not enter) the event's own checks are left out."""
    if rec is None or rec.deleted_at is not None:
        return "no_record", "the record is deleted or gone"
    obj = cat.by_id(rec.object_id)
    if obj is None or obj.key != trigger["object"]:
        return "object", f"the record is a {obj.key if obj else 'record of an archived object'}, and this workflow " \
                         f"is for {trigger['object']} records"
    if event is not None:
        if event.actor_type == "workflow" and event.actor_id == workflow_id:
            return "self", "the change was made by this workflow, and a workflow never starts itself"
        for key, wanted in trigger["data"].items():
            if event.data.get(key) != wanted:
                return "data", f"{key} is {event.data.get(key)!r}, and the trigger needs {wanted!r}"
    try:
        ok, reason = judge(cat, obj, rec, trigger["filter"], "trigger.filter")
    except filters.FilterError as e:
        return "error", f"the trigger's filter no longer works: {e.path}: {e.message}"
    return ("ok", None) if ok else ("filter", reason)


def admit(db: Session, wf: Workflow, version: WorkflowVersion, rec: Record,
          event: Event | None = None) -> tuple[str, str | None, Run | None]:
    """Starts a run of `rec` unless it is in this workflow already, or has been and re-entry is off: (outcome, reason,
    the run). The lock on (workflow, record) makes the check and the insert one step for every enroller at once, and
    the unique index on live runs is the backstop beneath it."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"workflow-enter:{wf.id}:{rec.id}"})
    mine = (Run.workflow_id == wf.id, Run.record_id == rec.id, Run.test.is_(False))
    if live := db.scalar(select(Run.id).where(*mine, Run.status.in_(ACTIVE))):
        return "running", f"the record is in this workflow already (run {live})", None
    if not wf.settings.get("reentry") and db.scalar(select(exists().where(*mine))):
        return "reentry", "the record entered this workflow before, and re-entry is off", None
    start = version.graph["start"]
    run = Run(workspace_id=wf.workspace_id, workflow_id=wf.id, version_id=version.id, record_id=rec.id,
              status="running", node_id=start, steps=0, trigger_event_id=event.id if event else None,
              context={"event": {"id": event.id, "type": event.type}} if event else {})
    try:
        with db.begin_nested():
            db.add(run)
            db.flush()
    except IntegrityError:  # the same event read twice, or a live run that the check above could not see
        return "running", "the record is in this workflow already", None
    events.emit(db, "workflow.run_started", "workflow_run", run.id, {
        **engine.run_data(db, run, wf), "event_id": event.id if event else None}, workspace_id=wf.workspace_id,
        actor=("workflow", wf.id))
    jobs.enqueue(db, "workflow.step", {"run_id": str(run.id), "node_id": start, "n": 0})
    return "entered", None, run


def contains(data: dict, wanted: dict) -> bool:
    return all(data.get(k) == v for k, v in wanted.items())


def locked(db: Session, run: Run) -> Run:
    """The run, locked and as it is now (a step may have moved it since it was read)."""
    return db.scalar(select(Run).where(Run.id == run.id).with_for_update().execution_options(populate_existing=True))


def resolve_waiters(db: Session, e: Event, rid: uuid.UUID, waiters: list[Waiter]) -> None:
    """Each run waiting for this kind of event on this record, whose wait began before the event and whose `match` the
    event holds, goes on down its `event` branch."""
    for w in waiters:
        if w.resolved_at is not None or w.record_id != rid or w.event_type != e.type or w.created_at > e.occurred_at:
            continue
        run = locked(db, db.get(Run, w.run_id))
        wf = db.get(Workflow, run.workflow_id)
        node = db.get(WorkflowVersion, run.version_id).graph["nodes"].get(run.node_id)
        if run.status != "waiting" or wf.status != "published" or not node or not (node.get("config") or {}).get(
                "event"):
            continue
        if contains(e.data, w.match):
            engine.resume(db, run, wf, node, "event", event=e.type, event_id=e.id)
            w.resolved_at = func.now()


def jump_to_goals(db: Session, cat: Catalog, e: Event, rec: Record, runs: list[Run]) -> None:
    """Runs of this record whose goal has become true jump to it: no reversal, and a goal is met once per run."""
    obj = cat.by_id(rec.object_id)
    for run in runs:
        wf = db.get(Workflow, run.workflow_id)
        if run.status not in ACTIVE or wf.status != "published" or obj is None:
            continue
        graph = db.get(WorkflowVersion, run.version_id).graph
        for gid, goal in graph["nodes"].items():
            if goal["type"] != "goal" or gid in run.context.get("goals", []):
                continue
            try:
                met, _ = judge(cat, obj, rec, goal["config"]["filter"], f"nodes.{gid}.config.filter")
            except filters.FilterError:
                continue  # a goal that no longer compiles is a goal nobody meets
            if met:
                run = locked(db, run)
                if run.status in ACTIVE:
                    engine.trace(db, run, gid, "completed", {}, {"jumped": True, "from": run.node_id, "event": e.type,
                                                                "event_id": e.id})
                    run.context = {**run.context, "goals": [*run.context.get("goals", []), gid]}
                    engine.close_waiters(db, run)
                    engine.go(db, run, wf, goal["next"])
                break


def read(db: Session, ws: Workspace, batch: list[Event]) -> bool:
    """Handles the events of one workspace (inside `acting`); whether any check was written."""
    cat = Catalog(system_ctx(db, ws))
    rids = {r for e in batch if (r := record_of(e))}
    types = {e.type for e in batch}
    candidates = db.execute(
        select(Workflow, WorkflowVersion).join(WorkflowVersion, WorkflowVersion.id == Workflow.published_version_id)
        .where(Workflow.status == "published", Workflow.trigger_event.in_(types))
        .order_by(Workflow.created_at, Workflow.id)).all()
    live = list(db.scalars(select(Run).where(Run.record_id.in_(rids), Run.status.in_(ACTIVE), Run.test.is_(False))
                           .order_by(Run.started_at))) if rids else []
    waiters = list(db.scalars(select(Waiter).where(Waiter.record_id.in_(rids), Waiter.resolved_at.is_(None))
                              .order_by(Waiter.created_at))) if rids else []
    done = set(db.execute(select(TriggerCheck.workflow_id, TriggerCheck.event_id).where(
        TriggerCheck.event_id.in_([e.id for e in batch]))).all())  # an event read twice is judged once
    checks = []
    for e in batch:
        rid = record_of(e)
        rec = db.get(Record, rid) if rid else None
        if rec is not None and rec.deleted_at is None:
            resolve_waiters(db, e, rid, waiters)
            jump_to_goals(db, cat, e, rec, [r for r in live if r.record_id == rid])
        for wf, version in candidates:
            if wf.trigger_event != e.type or (wf.id, e.id) in done:
                continue
            outcome, reason = evaluate(cat, rec, version.graph["trigger"], e, wf.id)
            run = None
            if outcome == "ok":
                outcome, reason, run = admit(db, wf, version, rec, e)
            checks.append(TriggerCheck(
                workspace_id=ws.id, workflow_id=wf.id, version_id=version.id, event_id=e.id, event_type=e.type,
                record_id=rid, matched=outcome in HITS, outcome=outcome, reason=reason, run_id=run.id if run else None))
    db.add_all(checks)
    db.flush()
    return bool(checks)


@events.consumer("workflows")
def consume(db: Session, batch: list[Event]) -> None:
    batch = [e for e in batch if not e.type.startswith("workflow.")]  # workflows never start on workflow events
    wrote = False
    for ws_id in dict.fromkeys(e.workspace_id for e in batch):
        ws = db.get(Workspace, ws_id)
        if ws is not None:
            with acting(db, workspace_id=ws.id, org_id=ws.org_id):
                wrote |= read(db, ws, [e for e in batch if e.workspace_id == ws_id])
    if wrote:  # the owner role again: requests may not delete
        db.execute(delete(TriggerCheck).where(TriggerCheck.created_at < func.now() - KEEP))
