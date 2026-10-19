"""Versions and publishing (ADR 0006). Saving a graph is a new immutable version (saving what the newest already holds
changes nothing); publishing points the workflow at one. By default a run in flight finishes on the version it started
on. `migrate` moves them instead: a run whose node exists in the new version stays at it, one whose node is gone
goes to the node `migrate` names for it, or `exit`s, and a node that is gone with no answer is refused (422) so no run
is stranded. A pause freezes the runs, and a resume queues them again.

ponytail: migrating runs happens in the publish request, a run at a time; past a few thousand runs it belongs in a job.
ponytail: a run kept at a wait keeps the wake-up it was scheduled with, whatever the new version says for that wait."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import events
from ..api import ApiError
from ..records.schema import Catalog
from ..security import Ctx
from . import engine
from .check import check
from .models import ACTIVE, Ref, Run, Workflow, WorkflowVersion
from .schema import GraphError, publishable, refs, validate


def invalid(errors: dict[str, str], prefix: str = "graph") -> ApiError:
    return ApiError(422, "validation_failed", "The workflow is not valid",
                    {f"{prefix}.{k}" if k else prefix: v for k, v in errors.items()})


def newest(db: Session, workflow_id: uuid.UUID) -> WorkflowVersion | None:
    return db.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id)
                      .order_by(WorkflowVersion.number.desc()).limit(1)).first()


def state(wf: Workflow) -> dict:
    return {"id": wf.id, "name": wf.name, "folder": wf.folder, "status": wf.status, "settings": wf.settings}


def save_version(c: Ctx, wf: Workflow, graph: dict, note: str | None) -> tuple[WorkflowVersion, bool]:
    """The checked graph as the workflow's newest version (the newest one itself when nothing changed), and whether a
    version was made. The caller holds the workflow row locked, so numbers are handed out one at a time."""
    try:
        clean = validate(graph)
    except GraphError as e:
        raise invalid(e.fields) from None
    if errors := check(Catalog(c), clean):
        raise invalid(errors)
    last = newest(c.db, wf.id)
    if last is not None and last.graph == clean:
        return last, False
    version = WorkflowVersion(workspace_id=wf.workspace_id, workflow_id=wf.id, number=last.number + 1 if last else 1,
                              graph=clean, note=note, created_by=c.user_id)
    c.db.add(version)
    c.db.flush()
    c.db.add_all([Ref(workspace_id=wf.workspace_id, workflow_id=wf.id, version_id=version.id, node_id=node, kind=kind,
                      **({"ref_id": uuid.UUID(value)} if is_id(value) else {"ref_key": value[:200]}))
                  for node, kind, value in refs(clean)])
    wf.updated_at = func.now()
    events.emit(c.db, "workflow.version_created", "workflow", wf.id,
                {"id": wf.id, "name": wf.name, "version": version.number, "version_id": version.id, "note": note},
                actor=c.author())
    return version, True


def is_id(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def diff(a: dict, b: dict) -> dict:
    """What differs between two graphs, node by node. Where a node is drawn (`ui`) is not a difference."""
    an, bn = a["nodes"], b["nodes"]
    changed = []
    for nid in sorted(an.keys() & bn.keys()):
        keys = sorted(k for k in (an[nid].keys() | bn[nid].keys()) - {"ui"} if an[nid].get(k) != bn[nid].get(k))
        if keys:
            changed.append({"id": nid, "keys": keys, "before": an[nid], "after": bn[nid]})
    return {"trigger": {"changed": a["trigger"] != b["trigger"], "before": a["trigger"], "after": b["trigger"]},
            "start": {"changed": a["start"] != b["start"], "before": a["start"], "after": b["start"]},
            "nodes": {"added": [{"id": n, "node": bn[n]} for n in sorted(bn.keys() - an.keys())],
                      "removed": [{"id": n, "node": an[n]} for n in sorted(an.keys() - bn.keys())],
                      "changed": changed}}


def in_flight(db: Session, wf: Workflow, version: WorkflowVersion) -> list[Run]:
    """The runs that are not on `version` and not over, locked."""
    return list(db.scalars(select(Run).where(Run.workflow_id == wf.id, Run.status.in_(ACTIVE), Run.test.is_(False),
                                             Run.version_id != version.id).order_by(Run.id).with_for_update()))


def plan(runs: list[Run], nodes: dict, migrate: dict[str, str] | None) -> dict:
    """Where each run would go: how many stay at their node, and per removed node how many runs and where `migrate`
    sends them (None: nowhere yet)."""
    gone: dict[str, int] = {}
    for run in runs:
        if run.node_id not in nodes:
            gone[run.node_id] = gone.get(run.node_id, 0) + 1
    return {"in_flight": len(runs), "same_node": len(runs) - sum(gone.values()),
            "removed_nodes": [{"node_id": n, "runs": k, "to": (migrate or {}).get(n)} for n, k in sorted(gone.items())]}


def publish(c: Ctx, wf: Workflow, version: WorkflowVersion, migrate: dict[str, str] | None, dry_run: bool) -> dict:
    """Makes `version` what the workflow runs. Checked once more, because what it names may have changed since it was
    saved. `migrate` (node id to a node of this version, or "exit") moves the runs in flight; None leaves them be."""
    if errors := publishable(version.graph) | check(Catalog(c), version.graph):
        raise invalid(errors)
    nodes = version.graph["nodes"]
    runs = in_flight(c.db, wf, version)
    summary = plan(runs, nodes, migrate)
    if migrate is not None:
        unmapped = {n["node_id"]: f"{n['runs']} runs are at this step, which this version removed: choose one or exit"
                    for n in summary["removed_nodes"] if n["to"] is None}
        bad = {k: "is not a step of this version, or exit" for k, v in migrate.items()
               if v != "exit" and v not in nodes}
        if errors := {f"migrate.{k}": m for k, m in {**unmapped, **bad}.items()}:
            raise ApiError(422, "validation_failed", "The runs in flight need somewhere to go", errors)
    if dry_run:
        return {**summary, "dry_run": True}
    moved = exited = 0
    for run in runs if migrate is not None else []:
        target = run.node_id if run.node_id in nodes else migrate[run.node_id]
        before = {"from_version": run.version_id, "to_version": version.id}
        run.version_id = version.id
        if target == "exit":
            engine.trace(c.db, run, run.node_id, "migrated", {}, {**before, "exited": True})
            engine.finish(c.db, run, wf, "exited", f"version {version.number} removed the step it was at")
            exited += 1
        elif target != run.node_id:
            engine.trace(c.db, run, run.node_id, "migrated", {}, {**before, "to": target})
            engine.close_waiters(c.db, run)
            engine.go(c.db, run, wf, target)
            moved += 1
        else:
            run.context = {**run.context, "migrated": [*run.context.get("migrated", []), str(version.id)]}
            moved += 1
    old = wf.status, wf.published_version_id
    wf.published_version_id, wf.trigger_event = version.id, version.graph["trigger"]["event"]
    wf.status = "published" if wf.status in ("draft", "published") else wf.status  # a paused workflow stays paused
    wf.updated_at = version.published_at = func.now()
    c.db.flush()
    if old[0] != wf.status:
        events.emit(c.db, "workflow.updated", "workflow", wf.id,
                    {**state(wf), "changes": {"status": {"old": old[0], "new": wf.status}}}, actor=c.author())
    events.emit(c.db, "workflow.published", "workflow", wf.id,
                {"id": wf.id, "name": wf.name, "version": version.number, "version_id": version.id,
                 "moved": moved, "exited": exited}, actor=c.author())
    return {**summary, "moved": moved, "exited": exited, "dry_run": False}


def set_status(c: Ctx, wf: Workflow, status: str) -> None:
    before = wf.status
    wf.status, wf.updated_at = status, func.now()
    c.db.flush()
    events.emit(c.db, "workflow.updated", "workflow", wf.id,
                {**state(wf), "changes": {"status": {"old": before, "new": status}}}, actor=c.author())


def wake_of(node: dict) -> str | None:
    """The kind of wake-up a run waiting at `node` is scheduled for."""
    if node["type"] == "wait":
        return "timeout" if (node["config"] or {}).get("event") else "timer"
    return "retry"


def resume_runs(c: Ctx, wf: Workflow) -> int:
    """Queues the step of every run a pause froze (a waiting one at its wake time). A step that is queued twice runs
    once: the second finds the run has moved on."""
    runs = list(c.db.scalars(select(Run).where(Run.workflow_id == wf.id, Run.status.in_(ACTIVE), Run.test.is_(False))
                             .with_for_update()))
    for run in runs:
        graph = c.db.get(WorkflowVersion, run.version_id).graph
        waiting = run.status == "waiting"
        engine.schedule(c.db, run, run.node_id, wake=wake_of(graph["nodes"][run.node_id]) if waiting else None,
                        run_at=run.wake_at if waiting else None)
    return len(runs)


def archive(c: Ctx, wf: Workflow) -> int:
    """Takes the workflow out of service and cancels the runs in flight; returns how many."""
    runs = list(c.db.scalars(select(Run).where(Run.workflow_id == wf.id, Run.status.in_(ACTIVE)).with_for_update()))
    for run in runs:
        cancel(c, run, wf, "the workflow was archived")
    wf.trigger_event = None
    set_status(c, wf, "archived")
    return len(runs)


def cancel(c: Ctx, run: Run, wf: Workflow, reason: str) -> None:
    """Ends a live run: the trace says who and why, and its waiters close."""
    engine.trace(c.db, run, run.node_id or "", "cancelled", {}, {"reason": reason, "by": c.user_id})
    run.status, run.ended_at, run.wake_at = "cancelled", func.now(), None
    engine.close_waiters(c.db, run)
    events.emit(c.db, "workflow.run_cancelled", "workflow_run", run.id,
                {**engine.run_data(c.db, run, wf), "node_id": run.node_id, "reason": reason}, actor=c.author())
