"""Test runs and "why did this record not enter" (ADR 0006).

A test run walks a version for one record, synchronously, on a virtual clock: a wait ends at once and the trace says how
much time it skipped, a send or a webhook says what it would send and sends nothing (no message, no delivery row, no
job). It runs the real actions against the real record inside a savepoint that is always rolled back, so the record, its
tags, tasks, owner and stage are exactly as they were afterwards, while a condition after an update sees the update
and an exit rule refuses for real. What it leaves is its own trace, saved as a run with `test` set (the list of runs
hides those by default). `paths` forces the branch at a node: `{"split_node": "b", "event_wait": "event"}`.

ponytail: a test run locks the record for as long as it runs; nothing in it may commit, and a test fails if that ever
changes. An event wait takes its `timeout` branch unless `paths` says `event`."""
import logging
import uuid
from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from ..inbox import consent
from ..inbox.threads import system_ctx
from ..records.models import Record
from ..records.schema import Catalog
from ..security import Ctx
from .engine import STEP_ERRORS, Env, execute, make_env, why
from .enroll import HITS, evaluate
from .judge import judge
from .models import ACTIVE, Run, Step, TriggerCheck, Workflow, WorkflowVersion
from .schema import MAX_STEPS

log = logging.getLogger("workflows")


class Walk:
    """One test run: the run, its trace so far, and the virtual clock."""

    def __init__(self, c: Ctx, wf: Workflow, version: WorkflowVersion, run: Run, paths: dict[str, str]):
        self.c, self.wf, self.version, self.run, self.paths = c, wf, version, run, paths
        self.graph, self.node_id, self.error = version.graph, run.node_id, None
        self.clock, self.skipped, self.trail = run.started_at, 0, []

    def add(self, node: str, status: str, input_: dict, output: dict, error: str | None = None) -> None:
        self.run.steps += 1
        self.trail.append({"seq": self.run.steps, "node_id": node, "status": status, "error": error,
                           "input": jsonable_encoder(input_), "output": jsonable_encoder(output),
                           "started_at": self.clock, "finished_at": datetime.now(UTC)})

    def step(self) -> None:
        node_id, node = self.node_id, self.graph["nodes"][self.node_id]
        if self.run.steps >= MAX_STEPS:
            self.error = f"Loop guard: the run has taken {MAX_STEPS} steps"
            return
        try:
            env = make_env(self.c.db, self.c.workspace, self.wf, self.version, self.run, node_id, test=True,
                           now=self.clock, forced=self.paths)
            with self.c.db.begin_nested():  # a failed node leaves nothing behind, though the test's own savepoint stays
                result = execute(env, node_id)
        except Exception as e:
            if not isinstance(e, STEP_ERRORS):
                log.exception("test run of workflow %s failed at %s", self.wf.id, node_id)
            self.error = why(e)
            return self.add(node_id, "failed", node["config"], {}, self.error)
        if result.park:
            self.wait(node, result)
        else:
            self.add(node_id, "completed", result.input, result.output)
            self.node_id = result.next
        self.goal(env)

    def wait(self, node: dict, result) -> None:
        """A wait (or a send put off for quiet hours) on the virtual clock: the time is skipped and the trace says how
        much."""
        park, node_id = result.park, self.node_id
        gap = max(0, int((park.until - self.clock).total_seconds()))
        self.skipped += gap
        self.add(node_id, "waiting", result.input, {**result.output, "skipped_seconds": gap})
        self.clock = max(self.clock, park.until)
        if park.kind == "retry":
            return  # the node runs again, now that the quiet hours are over
        branch = "event" if park.kind == "event" and self.paths.get(node_id) == "event" else "timeout"
        how, self.node_id = ("timer", node["next"]) if park.kind == "timer" else (branch, node["branches"][branch])
        self.add(node_id, "completed", {}, {"resumed_by": how, "virtual_time": self.clock.isoformat()})

    def goal(self, env: Env) -> None:
        """After each step: a goal whose condition has become true takes the run to it (once per goal)."""
        reached = self.run.context.get("goals", [])
        for gid, goal in self.graph["nodes"].items():
            if self.node_id is None or goal["type"] != "goal" or gid in reached:
                continue
            if judge(env.cat, env.obj, env.record(), goal["config"]["filter"], f"nodes.{gid}.config.filter")[0]:
                self.run.context = {**self.run.context, "goals": [*reached, gid]}
                self.add(gid, "completed", {}, {"jumped": True, "from": self.node_id})
                self.node_id = goal["next"]
                return


def run_test(c: Ctx, wf: Workflow, version: WorkflowVersion, rec: Record, paths: dict[str, str]) -> dict:
    """Runs `version` for `rec`; the run and its steps. The caller checked that the record is one the caller may see
    and that its object is the trigger's."""
    run = Run(id=uuid.uuid4(), workspace_id=c.workspace.id, workflow_id=wf.id, version_id=version.id, record_id=rec.id,
              status="running", node_id=version.graph["start"], steps=0, test=True, context={},
              started_at=consent.clock())  # the virtual clock starts at the time the consent rules read
    walk = Walk(c, wf, version, run, paths)
    nested = c.db.begin_nested()
    try:
        while walk.node_id is not None and walk.error is None:
            walk.step()
    finally:
        nested.rollback()  # whatever the actions wrote, nothing is left of it
    run.node_id, run.ended_at, run.error = walk.node_id, datetime.now(UTC), walk.error
    run.status = "failed" if walk.error else "completed"
    c.db.add(run)
    c.db.flush()
    c.db.add_all([Step(workspace_id=run.workspace_id, run_id=run.id, **row) for row in walk.trail])
    c.db.commit()
    return {"run": run, "steps": walk.trail, "skipped_seconds": walk.skipped}


def check_json(x: TriggerCheck) -> dict:
    return {"event_id": x.event_id, "event_type": x.event_type, "matched": x.matched, "outcome": x.outcome,
            "reason": x.reason, "run_id": x.run_id, "version_id": x.version_id, "at": x.created_at}


def explain(c: Ctx, wf: Workflow, version: WorkflowVersion | None, rec: Record) -> dict:
    """Why this record is not in the workflow, from the log of trigger checks, or judged now when there is none."""
    db = c.db
    checks = list(db.scalars(select(TriggerCheck).where(TriggerCheck.workflow_id == wf.id,
                                                        TriggerCheck.record_id == rec.id)
                             .order_by(TriggerCheck.event_id.desc(), TriggerCheck.id.desc()).limit(20)))
    runs = list(db.scalars(select(Run).where(Run.workflow_id == wf.id, Run.record_id == rec.id, Run.test.is_(False))
                           .order_by(Run.started_at.desc(), Run.id.desc()).limit(5)))
    live = next((r for r in runs if r.status in ACTIVE), None)
    out = {"record_id": rec.id, "workflow_id": wf.id, "workflow_status": wf.status, "in_workflow": live is not None,
           "checks": [check_json(x) for x in checks], "evaluation": None,
           "runs": [{"id": r.id, "status": r.status, "node_id": r.node_id, "started_at": r.started_at,
                     "ended_at": r.ended_at} for r in runs]}
    if wf.status != "published":
        return {**out, "answer": f"Nothing enters a workflow that is {wf.status}: publish it first"}
    if live:
        return {**out, "answer": f"The record is in the workflow now: its run is {live.status} at {live.node_id}"}
    if checks:
        last = checks[0]
        reason = f": {last.reason}" if last.reason else ""
        return {**out, "answer": f"{'Entered' if last.outcome == 'entered' else 'Did not enter'} when "
                                 f"{last.event_type} was read at {last.created_at:%Y-%m-%d %H:%M} UTC{reason}"}
    outcome, reason = evaluate(Catalog(system_ctx(db, c.workspace)), db.get(Record, rec.id), version.graph["trigger"],
                               None, wf.id)
    if outcome == "ok" and runs and not wf.settings.get("reentry"):
        outcome, reason = "reentry", "the record was in this workflow before, and re-entry is off"
    start = f"No {version.graph['trigger']['event']} was read for this record in the last 7 days. Judged now, "
    return {**out, "evaluation": {"outcome": outcome, "reason": reason, "matched": outcome in (*HITS, "ok"),
                                  "evaluated": "now"},
            "answer": start + ("it would enter when that event happens" if outcome == "ok"
                               else f"it would not enter: {reason}")}
