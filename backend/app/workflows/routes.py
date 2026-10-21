"""Workflows API (`/api/v1/workflows`, module 18): workflows, their immutable versions, publishing over runs in flight,
pause and resume, runs with their trace, test runs, "why did it not enter", and what uses a tag, field, stage or person.
Reading is `workflows.read`, editing, testing, cancelling and retrying `workflows.write`, and what changes what runs
live (publish, pause, resume, archive, the signing secret, a live workflow's settings) `workflows.publish`. A run is
shown only while its record is in the caller's scope, and its steps (which carry what was sent and set) are left out
for a role that hides fields."""
import secrets
import uuid
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import events, permissions
from ..api import ApiError, Idem, idempotency, paginate
from ..permissions import require, requires
from ..records import store
from ..records.models import Record, Tag
from ..records.schema import Catalog
from ..security import Ctx
from . import engine, publishing, schema, testrun
from .check import check
from .models import ACTIVE, Delivery, Ref, Run, Step, Waiter, Workflow, WorkflowVersion

router = APIRouter(prefix="/api/v1/workflows")
reads, writes, publishes = requires("workflows.read"), requires("workflows.write"), requires("workflows.publish")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Folder = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
RUN_STATUSES = Literal["running", "waiting", "completed", "failed", "exited", "cancelled"]
REF_KINDS = Literal["tag", "field", "stage", "user", "channel", "form", "calendar"]


class NewWorkflow(BaseModel):
    name: Name
    folder: Folder | None = None
    settings: schema.Settings = schema.Settings()
    graph: dict | None = None  # saved as version 1
    note: Note | None = None


class PatchWorkflow(BaseModel):
    name: Name | None = None
    folder: Folder | None = None
    settings: schema.Settings | None = None
    owner_id: uuid.UUID | None = None


class SaveVersion(BaseModel):
    graph: dict
    note: Note | None = None
    base: int | None = None  # the newest version the editor started from (null: none yet); sent, it guards the save


class Publish(BaseModel):
    version: int | None = None  # the number; default: the newest
    migrate: dict[str, str] | None = None  # step id -> step id or "exit"; leave out to let runs finish where they are
    dry_run: bool = False  # only say how many runs are where


class TestRun(BaseModel):
    record_id: uuid.UUID
    version: int | None = None
    paths: dict[str, str] = {}  # node id -> the branch to take there


def workflow_or_404(c: Ctx, workflow_id: uuid.UUID, *, lock: bool = False) -> Workflow:
    stmt = select(Workflow).where(Workflow.id == workflow_id)
    wf = c.db.scalar(stmt.with_for_update() if lock else stmt)  # row level security: this workspace's workflows only
    if wf is None:
        raise HTTPException(404, "Workflow not found")
    return wf


def version_or_404(c: Ctx, wf: Workflow, number: int | None) -> WorkflowVersion:
    stmt = select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id)
    version = c.db.scalar(stmt.where(WorkflowVersion.number == number) if number else
                          stmt.order_by(WorkflowVersion.number.desc()).limit(1))
    if version is None:
        raise HTTPException(404, "Version not found" if number else "The workflow has no versions yet: save one first")
    return version


def workflow_json(db: Session, workflows: list[Workflow]) -> list[dict]:
    """The API shape of each workflow, with its version numbers and run counts read in a few queries for all of them."""
    ids = [w.id for w in workflows]
    latest = dict(db.execute(select(WorkflowVersion.workflow_id, func.max(WorkflowVersion.number))
                             .where(WorkflowVersion.workflow_id.in_(ids)).group_by(WorkflowVersion.workflow_id)).all())
    published = dict(db.execute(select(WorkflowVersion.id, WorkflowVersion.number).where(
        WorkflowVersion.id.in_([w.published_version_id for w in workflows if w.published_version_id]))).all())
    runs: dict[uuid.UUID, dict] = {}
    for wid, status, n in db.execute(select(Run.workflow_id, Run.status, func.count()).where(
            Run.workflow_id.in_(ids), Run.test.is_(False)).group_by(Run.workflow_id, Run.status)):
        runs.setdefault(wid, {})[status] = n
    return [{"id": w.id, "name": w.name, "folder": w.folder, "status": w.status, "settings": w.settings,
             "owner_id": w.owner_id, "trigger_event": w.trigger_event, "published_version_id": w.published_version_id,
             "published_version": published.get(w.published_version_id), "latest_version": latest.get(w.id),
             "has_draft_changes": latest.get(w.id) is not None and latest.get(w.id) != published.get(
                 w.published_version_id),
             "runs": runs.get(w.id, {}), "created_by": w.created_by, "created_at": w.created_at,
             "updated_at": w.updated_at} for w in workflows]


def version_json(v: WorkflowVersion, wf: Workflow, graph: bool = False) -> dict:
    return {"id": v.id, "workflow_id": v.workflow_id, "number": v.number, "note": v.note, "created_by": v.created_by,
            "created_at": v.created_at, "published_at": v.published_at,
            "published": wf.published_version_id == v.id, "nodes": len(v.graph["nodes"]),
            **({"graph": v.graph} if graph else {})}


def step_json(c: Ctx, s: Step | dict) -> dict:
    """A step of the trace. What it was asked and what it did can carry values the role may not read, so a role that
    hides fields gets neither."""
    get = (lambda k: s[k]) if isinstance(s, dict) else (lambda k: getattr(s, k))
    hide = permissions.restricted(c)
    return {"id": None if isinstance(s, dict) else s.id, "seq": get("seq"), "node_id": get("node_id"),
            "status": get("status"), "input": None if hide else get("input"), "output": None if hide else get("output"),
            "error": get("error"), "started_at": get("started_at"), "finished_at": get("finished_at")}


def runs_json(c: Ctx, runs: list[Run]) -> list[dict]:
    cat = Catalog(c)
    versions = dict(c.db.execute(select(WorkflowVersion.id, WorkflowVersion.number).where(
        WorkflowVersion.id.in_({r.version_id for r in runs}))).all())
    names = dict(c.db.execute(select(Workflow.id, Workflow.name).where(
        Workflow.id.in_({r.workflow_id for r in runs}))).all())
    records = {r.id: r for r in c.db.scalars(select(Record).where(Record.id.in_({r.record_id for r in runs})))}
    out = []
    for r in runs:
        rec = records.get(r.record_id)
        obj = rec and cat.by_id(rec.object_id)
        out.append({"id": r.id, "workflow_id": r.workflow_id, "workflow": names.get(r.workflow_id),
                    "version": versions.get(r.version_id), "record": obj and store.glance(cat, obj, rec),
                    "status": r.status, "node_id": r.node_id, "step_count": r.steps, "wake_at": r.wake_at,
                    "error": r.error,
                    "test": r.test, "trigger_event_id": r.trigger_event_id, "started_at": r.started_at,
                    "ended_at": r.ended_at})
    return out


def run_or_404(c: Ctx, run_id: uuid.UUID, *, lock: bool = False) -> Run:
    """A run whose record the caller may see: any other is a 404, so a run does not give its record away."""
    stmt = (select(Run).join(Record, Record.id == Run.record_id)
            .where(Run.id == run_id, Run.workspace_id == c.workspace.id, store.anywhere(Catalog(c))))
    run = c.db.scalar(stmt.with_for_update(of=Run) if lock else stmt)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


def run_detail(c: Ctx, run: Run) -> dict:
    steps = c.db.scalars(select(Step).where(Step.run_id == run.id).order_by(Step.seq)).all()
    waiting = c.db.scalars(select(Waiter).where(Waiter.run_id == run.id, Waiter.resolved_at.is_(None))).all()
    sent = c.db.scalars(select(Delivery).where(Delivery.run_id == run.id).order_by(Delivery.created_at)).all()
    return {**runs_json(c, [run])[0], "context": run.context, "steps": [step_json(c, s) for s in steps],
            "waiting_for": [{"event_type": w.event_type, "match": w.match} for w in waiting],
            "deliveries": [{"id": d.id, "node_id": d.node_id, "host": urlsplit(d.url).hostname, "status": d.status,
                            "attempts": d.attempts, "response_status": d.response_status, "error": d.error,
                            "created_at": d.created_at} for d in sent]}


# --- catalog and dependencies (before the routes with a workflow id, so "catalog" is not read as one) ---------------

@router.get("/catalog")
def catalog(c: Ctx = Depends(reads)):
    """What the builder is made of: the triggers (events about a record, with their data schemas), the node types and
    the actions, each with the JSON schema of its config. The API validates saved versions with the same schemas."""
    return schema.catalog()


@router.get("/refs")
def refs_of(kind: REF_KINDS, id: uuid.UUID | None = None, key: Annotated[str | None, Query(max_length=200)] = None,
            c: Ctx = Depends(reads)):
    """Which workflows use a tag, field (`contact.email`), stage, person, channel, form or calendar, and in which
    versions and nodes: one query, for "what breaks if I delete this"."""
    if (id is None) == (key is None):
        raise ApiError(422, "validation_failed", "Ask for one thing", {"id": "give an id or a key, not both and not "
                                                                            "neither"})
    match = Ref.ref_id == id if id else func.lower(Ref.ref_key) == key.lower()
    if kind == "tag":  # a tag is named by its id or its name in a graph
        tag = c.db.get(Tag, id) if id else c.db.scalar(select(Tag).where(func.lower(Tag.name) == key.lower()))
        if id and tag is None:
            raise HTTPException(404, "Tag not found")
        if tag is not None:
            match = or_(Ref.ref_id == tag.id, func.lower(Ref.ref_key) == tag.name.lower())
    rows = c.db.execute(
        select(Ref.workflow_id, Ref.node_id, WorkflowVersion.id, WorkflowVersion.number)
        .join(WorkflowVersion, WorkflowVersion.id == Ref.version_id).where(Ref.kind == kind, match)).all()
    flows = {w.id: w for w in c.db.scalars(select(Workflow).where(Workflow.id.in_({r[0] for r in rows}),
                                                                  Workflow.status != "archived"))}
    found: dict[uuid.UUID, dict] = {}
    for workflow_id, node, version_id, number in rows:
        if wf := flows.get(workflow_id):
            use = found.setdefault(workflow_id, {"workflow_id": wf.id, "name": wf.name, "status": wf.status,
                                                 "versions": set(), "nodes": set(), "in_published": False})
            use["versions"].add(number)
            use["nodes"].add(node or "trigger")
            use["in_published"] |= wf.published_version_id == version_id
    return {"data": [{**u, "versions": sorted(u["versions"]), "nodes": sorted(u["nodes"])}
                     for u in sorted(found.values(), key=lambda u: u["name"].lower())]}


# --- runs ---------------------------------------------------------------------------------------------------------

@router.get("/runs")
def list_runs(workflow_id: uuid.UUID | None = None, status: RUN_STATUSES | None = None,
              record_id: uuid.UUID | None = None, test: bool = False, limit: int = Query(50, ge=1, le=200),
              cursor: str | None = None, c: Ctx = Depends(reads)):
    """Newest first, of the records the caller may see. Test runs are left out unless `test=true`."""
    stmt = (select(Run).join(Record, Record.id == Run.record_id)
            .where(Run.test.is_(test), Run.workspace_id == c.workspace.id, store.anywhere(Catalog(c))))
    for column, value in ((Run.workflow_id, workflow_id), (Run.status, status), (Run.record_id, record_id)):
        if value is not None:
            stmt = stmt.where(column == value)
    rows, next_cursor = paginate(c.db, stmt, Run, limit, cursor, by="started_at")
    return {"data": runs_json(c, [r[0] for r in rows]) if rows else [], "next_cursor": next_cursor}


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, c: Ctx = Depends(reads)):
    """The run with its trace: every step with what it was asked and what it did, what it waits for, and the webhooks
    it queued."""
    return run_detail(c, run_or_404(c, run_id))


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: uuid.UUID, c: Ctx = Depends(writes)):
    run = run_or_404(c, run_id, lock=True)
    if run.status not in ACTIVE:
        raise ApiError(409, "conflict", f"The run is {run.status}, so there is nothing to cancel")
    publishing.cancel(c, run, c.db.get(Workflow, run.workflow_id), "cancelled by a person")
    c.db.commit()
    return run_detail(c, run)


@router.post("/runs/{run_id}/retry")
def retry_run(run_id: uuid.UUID, c: Ctx = Depends(writes)):
    """Runs the step a failed run stopped at again, now. The step is the same attempt: whatever it queued before it
    failed was rolled back with it, so nothing is sent twice."""
    run = run_or_404(c, run_id, lock=True)
    wf = c.db.get(Workflow, run.workflow_id)
    if run.status != "failed":
        raise ApiError(409, "conflict", f"The run is {run.status}: only a failed run can be retried")
    if wf.status != "published":
        raise ApiError(409, "conflict", f"The workflow is {wf.status}: publish or resume it first")
    if run.steps >= schema.MAX_STEPS:
        raise ApiError(409, "conflict", "The run hit the loop guard: cancel it and fix the workflow")
    run.status, run.error, run.ended_at = "running", None, None
    try:
        c.db.flush()
    except IntegrityError:  # the record entered the workflow again after this run failed
        c.db.rollback()
        raise ApiError(409, "conflict", "The record has entered this workflow again: cancel that run first") from None
    engine.schedule(c.db, run, run.node_id)
    c.db.commit()
    return run_detail(c, run)


# --- workflows ----------------------------------------------------------------------------------------------------

@router.get("")
def list_workflows(status: Literal["draft", "published", "paused", "archived"] | None = None,
                   folder: str | None = None, q: Annotated[str | None, Query(max_length=100)] = None,
                   limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(reads)):
    """Most recently changed first; archived workflows only when asked for with `status=archived`."""
    stmt = select(Workflow).where(Workflow.status == status if status else Workflow.status != "archived")
    if folder:
        stmt = stmt.where(Workflow.folder == folder)
    if q:
        stmt = stmt.where(Workflow.name.icontains(q, autoescape=True))
    rows, next_cursor = paginate(c.db, stmt, Workflow, limit, cursor, by="updated_at")
    return {"data": workflow_json(c.db, [r[0] for r in rows]) if rows else [], "next_cursor": next_cursor}


@router.post("", status_code=201)
def create_workflow(body: NewWorkflow, c: Ctx = Depends(writes), idem: Idem = Depends(idempotency)):
    """A draft workflow, with its first version when a graph is sent. The signing secret of its webhook action is in
    this response and nowhere else (`rotate-secret` makes a new one)."""
    wf = Workflow(workspace_id=c.workspace.id, name=body.name, folder=body.folder,
                  settings=body.settings.model_dump(mode="json"), owner_id=c.user_id, created_by=c.user_id,
                  signing_secret=f"whsec_{secrets.token_urlsafe(32)}")
    c.db.add(wf)
    c.db.flush()
    events.emit(c.db, "workflow.created", "workflow", wf.id, publishing.state(wf), actor=c.author())
    version = publishing.save_version(c, wf, body.graph, body.note)[0] if body.graph is not None else None
    return idem.commit(201, {**workflow_json(c.db, [wf])[0], "signing_secret": wf.signing_secret,
                             "version": version and version_json(version, wf, graph=True)})


@router.get("/{workflow_id}")
def get_workflow(workflow_id: uuid.UUID, c: Ctx = Depends(reads)):
    """The workflow with the graph of its newest version, which is what the builder edits."""
    wf = workflow_or_404(c, workflow_id)
    last = publishing.newest(c.db, wf.id)
    return {**workflow_json(c.db, [wf])[0], "graph": last.graph if last else None}


@router.patch("/{workflow_id}")
def update_workflow(workflow_id: uuid.UUID, body: PatchWorkflow, c: Ctx = Depends(writes)):
    wf = workflow_or_404(c, workflow_id, lock=True)
    sent = body.model_dump(exclude_unset=True, mode="json")
    if nulls := [k for k in ("name", "settings") if k in sent and sent[k] is None]:
        raise ApiError(422, "validation_failed", "The request is not valid", {k: "cannot be null" for k in nulls})
    if "settings" in sent and sent["settings"] != wf.settings and wf.status in ("published", "paused"):
        require(c, "workflows.publish")  # re-entry changes who enters a live workflow
    if sent.get("owner_id") and not store.member_ids(c, {sent["owner_id"]}):
        raise ApiError(422, "validation_failed", "The request is not valid", {"owner_id": "is not a member of this "
                                                                                          "workspace"})
    before = {k: getattr(wf, k) for k in ("name", "folder", "settings", "owner_id")}
    for key, value in sent.items():
        setattr(wf, key, uuid.UUID(value) if key == "owner_id" and value else value)
    changes = events.changes(jsonable_encoder(before), jsonable_encoder({k: getattr(wf, k) for k in before}))
    if changes:
        wf.updated_at = func.now()
        c.db.flush()
        events.emit(c.db, "workflow.updated", "workflow", wf.id, {**publishing.state(wf), "changes": changes},
                    actor=c.author())
    c.db.commit()
    return workflow_json(c.db, [wf])[0]


@router.delete("/{workflow_id}", status_code=204)
def archive_workflow(workflow_id: uuid.UUID, c: Ctx = Depends(publishes)):
    """Takes the workflow out of service and cancels its runs in flight. Its versions, runs and trace are kept."""
    wf = workflow_or_404(c, workflow_id, lock=True)
    if wf.status != "archived":
        publishing.archive(c, wf)
    c.db.commit()


@router.post("/{workflow_id}/rotate-secret")
def rotate_secret(workflow_id: uuid.UUID, c: Ctx = Depends(publishes)):
    """A new signing secret for the webhook action, returned once. Receivers verifying with the old one fail until they
    take the new one."""
    wf = workflow_or_404(c, workflow_id, lock=True)
    wf.signing_secret = f"whsec_{secrets.token_urlsafe(32)}"
    wf.updated_at = func.now()
    c.db.flush()
    events.emit(c.db, "workflow.updated", "workflow", wf.id,
                {**publishing.state(wf), "changes": {"signing_secret": {"rotated": True}}}, actor=c.author())
    c.db.commit()
    return {"signing_secret": wf.signing_secret}


# --- versions -----------------------------------------------------------------------------------------------------

@router.get("/{workflow_id}/versions")
def list_versions(workflow_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
                  c: Ctx = Depends(reads)):
    """Every version, newest first: nothing is pruned."""
    wf = workflow_or_404(c, workflow_id)
    rows, next_cursor = paginate(c.db, select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id),
                                 WorkflowVersion, limit, cursor)
    return {"data": [version_json(v, wf) for (v,) in rows], "next_cursor": next_cursor}


@router.post("/{workflow_id}/versions")
def create_version(workflow_id: uuid.UUID, body: SaveVersion, c: Ctx = Depends(writes),
                   idem: Idem = Depends(idempotency)):
    """Saves a graph as a new draft version. The graph is validated against the catalog's schemas and against this
    workspace (fields, tags, stages, channels); errors point into it (`graph.nodes.send.config.body`). Saving what the
    newest version already holds changes nothing and returns it. The published version stays until `publish`. With
    `base` (the newest version number the editor loaded, or null for none) a version saved since is a 409
    `version_conflict`, so two people editing at once never overwrite each other without knowing."""
    wf = workflow_or_404(c, workflow_id, lock=True)
    if wf.status == "archived":
        raise ApiError(409, "conflict", "The workflow is archived")
    if "base" in body.model_fields_set:  # the row lock makes the check and the save one step
        last = publishing.newest(c.db, wf.id)
        if (last.number if last else None) != body.base:
            since, now = "none" if body.base is None else body.base, last.number if last else "none"
            raise ApiError(409, "version_conflict",
                           f"Version {now} was saved after version {since}, which this edit started from")
    version, made = publishing.save_version(c, wf, body.graph, body.note)
    return idem.commit(201 if made else 200, version_json(version, wf, graph=True))


@router.get("/{workflow_id}/versions/{number}")
def get_version(workflow_id: uuid.UUID, number: int, c: Ctx = Depends(reads)):
    wf = workflow_or_404(c, workflow_id)
    return version_json(version_or_404(c, wf, number), wf, graph=True)


@router.get("/{workflow_id}/diff")
def diff_versions(workflow_id: uuid.UUID, a: Annotated[int, Query(alias="from")], b: Annotated[int, Query(alias="to")],
                  c: Ctx = Depends(reads)):
    """What changed between two versions, node by node: added, removed, and changed with the keys that differ."""
    wf = workflow_or_404(c, workflow_id)
    before, after = version_or_404(c, wf, a), version_or_404(c, wf, b)
    return {"from": before.number, "to": after.number, **publishing.diff(before.graph, after.graph)}


@router.post("/{workflow_id}/publish")
def publish_workflow(workflow_id: uuid.UUID, body: Publish | None = None, c: Ctx = Depends(publishes)):
    """Makes a version (the newest, unless `version` is given) what the workflow runs. Runs in flight finish on the
    version they started on, unless `migrate` is sent: a run at a step the new version still has stays there on the new
    version, one at a removed step goes where `migrate` says (a step of the new version, or "exit"), and a removed step
    with no answer is a 422 that counts its runs. `dry_run` only counts."""
    body = body or Publish()
    wf = workflow_or_404(c, workflow_id, lock=True)
    if wf.status == "archived":
        raise ApiError(409, "conflict", "The workflow is archived")
    result = publishing.publish(c, wf, version_or_404(c, wf, body.version), body.migrate, body.dry_run)
    c.db.commit()
    return {**workflow_json(c.db, [wf])[0], "publish": result}


@router.post("/{workflow_id}/pause")
def pause_workflow(workflow_id: uuid.UUID, c: Ctx = Depends(publishes)):
    """Stops new records entering and freezes the runs in flight where they are (nothing is sent while paused)."""
    wf = workflow_or_404(c, workflow_id, lock=True)
    if wf.status != "published":
        raise ApiError(409, "conflict", f"Only a published workflow can be paused, and this one is {wf.status}")
    publishing.set_status(c, wf, "paused")
    c.db.commit()
    return workflow_json(c.db, [wf])[0]


@router.post("/{workflow_id}/resume")
def resume_workflow(workflow_id: uuid.UUID, c: Ctx = Depends(publishes)):
    wf = workflow_or_404(c, workflow_id, lock=True)
    if wf.status != "paused":
        raise ApiError(409, "conflict", f"Only a paused workflow can be resumed, and this one is {wf.status}")
    publishing.set_status(c, wf, "published")
    publishing.resume_runs(c, wf)
    c.db.commit()
    return workflow_json(c.db, [wf])[0]


# --- test and explain ---------------------------------------------------------------------------------------------

@router.post("/{workflow_id}/test")
def test_workflow(workflow_id: uuid.UUID, body: TestRun, c: Ctx = Depends(writes)):
    """Runs a version (the newest, unless `version` is given) for one record, now, on a virtual clock: waits end at once
    and report the time they skipped, messages and webhooks are described and not sent, and nothing is written to the
    record or anything else. Answers with the run and its full trace."""
    wf = workflow_or_404(c, workflow_id)
    version = version_or_404(c, wf, body.version)
    rec, obj = store.find(Catalog(c), body.record_id)  # a 404 unless the caller may see the record
    want = version.graph["trigger"]["object"]
    if obj.key != want:
        raise ApiError(422, "validation_failed", "The record is not one this workflow runs on",
                       {"record_id": f"is a {obj.key}, and this workflow is for {want} records"})
    if errors := check(Catalog(c), version.graph):
        raise publishing.invalid(errors)
    if bad := {f"paths.{k}": "is not a step of this version" for k in body.paths if k not in version.graph["nodes"]}:
        raise ApiError(422, "validation_failed", "The request is not valid", bad)
    done = testrun.run_test(c, wf, version, rec, body.paths)
    return {"run": runs_json(c, [done["run"]])[0], "version": version.number,
            "steps": [step_json(c, s) for s in done["steps"]], "skipped_seconds": done["skipped_seconds"]}


@router.get("/{workflow_id}/explain")
def explain_entry(workflow_id: uuid.UUID, record_id: uuid.UUID, c: Ctx = Depends(reads)):
    """Why this record is not in the workflow: the log of trigger checks for it (kept 7 days: each says which event,
    hit or miss, and the clause that failed), or, when there is none, the trigger judged against the record now."""
    wf = workflow_or_404(c, workflow_id)
    rec, _ = store.find(Catalog(c), record_id, trashed=None)
    version = c.db.get(WorkflowVersion, wf.published_version_id) if wf.published_version_id else None
    return testrun.explain(c, wf, version or version_or_404(c, wf, None), rec)
