"""The engine (ADR 0006): a run advances by `workflow.step` jobs, one step per transaction, and every step writes its
row of the trace. A job carries the run, the node it should run and `n`, the run's step count when it was scheduled;
a job whose run has moved on since (an event resolved its wait, a publish moved it, someone cancelled it) finds
another `n` and does nothing, which is also what makes a job that runs twice harmless. A wait parks the run
(`waiting`) and schedules the wake-up with `run_at`: the queue is the scheduler. A step that fails is recorded and the
run stops there (`failed`) until someone retries it; nothing is retried silently, because a retry may be a second
message.

Steps run as the workspace's Automation role, acting as the workflow, inside `acting` (row level security as for a
request), and a failed node is rolled back to a savepoint so a half-done step leaves nothing behind. Guards: 500 steps
per run, and at most `WORKFLOW_CONCURRENCY` steps at once per workspace (advisory locks as slots, so no table and no
coordination): a step that finds none free puts its job back a few seconds later.

ponytail: runs of a paused workflow freeze (their jobs find the workflow paused and end); resuming queues them again.
ponytail: a run migrated by a publish takes the new graph for the node it is at, and loops see the new node's config."""
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import config, events, jobs, permissions
from ..api import ApiError
from ..db import acting
from ..inbox.threads import system_ctx
from ..models import Workspace
from ..records import store
from ..records.models import FieldDef, ObjectDef, Record
from ..records.schema import Catalog
from ..security import Ctx
from .judge import judge
from .models import ACTIVE, Run, Step, Waiter, Workflow, WorkflowVersion
from .registry import ACTIONS, MERGE, Out, StepError, seconds
from .schema import MAX_STEPS

log = logging.getLogger("workflows")
BUSY_RETRY = timedelta(seconds=5)  # a step that found no free slot is tried again after this
STEP_ERRORS = (StepError, ApiError, HTTPException)


@dataclass
class Park:
    """A step that holds the run: until `until`, then it `timer` (the wait ends), `retry` (the node runs again) or, with
    `waiter`, `timeout` (the event did not come)."""
    until: datetime
    kind: str
    waiter: dict | None = None


@dataclass
class Result:
    next: str | None
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    park: Park | None = None


@dataclass
class Env:
    """One run at one node, as the actions see it. `test` is a test run: it runs inside a savepoint that is always
    rolled back, outbound actions only describe what they would send, and `now` is the virtual clock."""
    db: Session
    ctx: Ctx
    cat: Catalog
    wf: Workflow
    run: Run
    graph: dict
    obj: ObjectDef
    node_id: str
    now: datetime
    test: bool = False
    visit: int = 1
    forced: dict[str, str] = field(default_factory=dict)  # test runs: the branch to take at a node, by node id
    rec: Record | None = None
    locked: bool = False

    def key(self) -> str:
        """The idempotency key of this step's outbound rows: `run:node`, and `run:node:2` the second time a loop comes
        round to the node."""
        return f"{self.run.id}:{self.node_id}" + (f":{self.visit}" if self.visit > 1 else "")

    def record(self, *, lock: bool = False) -> Record:
        """The record, as the Automation role sees it (a record out of its scope is a failed step, not a leak)."""
        if self.rec is None or (lock and not self.locked):
            fresh = self.rec is not None
            self.rec = store.get(self.cat, self.obj, self.run.record_id, lock=lock)
            if fresh:
                self.db.refresh(self.rec)  # the row as it is now that it is locked, not as it was read before
            self.locked = self.locked or lock
        return self.rec

    def merged(self, key: str) -> str:
        rec = self.record()
        if key == "display_name":
            return rec.display_name
        if key in permissions.hidden(self.ctx, self.obj):
            raise StepError(f"{{{{{key}}}}} is hidden from the Automation role, so it cannot be put in text")
        return show(self.cat.fields(self.obj).get(key), rec.values.get(key))

    def render(self, text: str) -> str:
        return MERGE.sub(lambda m: self.merged(m.group(1)), text)

    def render_value(self, value):
        return self.render(value) if isinstance(value, str) else value


def show(field_def: FieldDef | None, value) -> str:
    """A field value as text for a message: choices by label, money with its currency, lists joined."""
    if value in (None, ""):
        return ""
    labels = {c["id"]: c["label"] for c in (field_def.options.get("choices", []) if field_def else [])}
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict) and "amount" in value:
        return f"{value['amount'] / 100:,.2f} {value.get('currency', '')}".strip()
    if isinstance(value, list):
        return ", ".join(labels.get(str(v), str(v)) for v in value)
    return labels.get(str(value), str(value))


def why(e: Exception) -> str:
    """A failed step's reason in words: the engine's own, the record engine's (with what is missing), or the fact."""
    if isinstance(e, ApiError):
        fields = "; ".join(f"{k}: {v}" for k, v in (e.fields or {}).items())
        return f"{e.detail}: {fields}"[:500] if fields else str(e.detail)
    if isinstance(e, HTTPException):
        return f"{e.detail}: it is gone, or out of reach of the Automation role"
    return str(e) if isinstance(e, StepError) else f"{type(e).__name__}: {e}"[:500]


def make_env(db: Session, ws: Workspace, wf: Workflow, version: WorkflowVersion, run: Run, node_id: str, *,
             test: bool = False, now: datetime | None = None, forced: dict | None = None) -> Env:
    ctx = system_ctx(db, ws)
    ctx.actor = ("workflow", wf.id)
    cat = Catalog(ctx)
    obj = cat.object(version.graph["trigger"]["object"])
    if obj is None:
        raise StepError(f"The object {version.graph['trigger']['object']!r} no longer exists")
    now = now or db.scalar(select(func.clock_timestamp()))  # the database's clock, which also decides when jobs are due
    return Env(db, ctx, cat, wf, run, version.graph, obj, node_id, now, test,
               1 if test else visits_of(db, run, node_id), forced or {})


def visits_of(db: Session, run: Run, node_id: str) -> int:
    """How often the run has been at the node, this time included: a loop's second send is a message of its own, while
    a retry of a step that failed is the same attempt (its outbox row was rolled back with it)."""
    return 1 + db.scalar(select(func.count()).select_from(Step).where(
        Step.run_id == run.id, Step.node_id == node_id, Step.status == "completed"))


# --- the node types ---------------------------------------------------------------------------------------------

def holds(env: Env, ast: dict, root: str) -> tuple[bool, str | None]:
    return judge(env.cat, env.obj, env.record(), ast, root)


def do_action(env: Env, node: dict) -> Result:
    act = ACTIONS.get(node["action"])
    if act is None:
        raise StepError(f"The action {node['action']!r} no longer exists")
    out: Out = act.run(env, act.config.model_validate(node["config"]))
    park = Park(out.until, "retry") if out.until else None
    return Result(node["next"], out.input, out.output, park)


def do_condition(env: Env, node: dict) -> Result:
    ok, reason = holds(env, node["config"]["filter"], f"nodes.{env.node_id}.config.filter")
    branch = env.forced.get(env.node_id) or ("yes" if ok else "no")
    return Result(node["branches"][branch], {"filter": node["config"]["filter"]},
                  {"matched": ok, "branch": branch, **({"why": reason} if reason else {})})


def do_split(env: Env, node: dict) -> Result:
    """The path by the run's id, so a run always takes the same one (and a retried step cannot change its mind)."""
    bucket = int(hashlib.sha256(f"{env.run.id}:{env.node_id}".encode()).hexdigest(), 16) % 100
    chosen, upto = None, 0
    for path in node["config"]["paths"]:
        upto += path["percent"]
        if chosen is None and bucket < upto:
            chosen = path["name"]
    chosen = env.forced.get(env.node_id) or chosen
    return Result(node["branches"][chosen], {"paths": node["config"]["paths"]}, {"path": chosen, "bucket": bucket})


def do_goal(env: Env, node: dict) -> Result:
    """A run that walks to the goal before it is met goes on, or ends, as the goal says."""
    ok, reason = holds(env, node["config"]["filter"], f"nodes.{env.node_id}.config.filter")
    env.run.context = {**env.run.context, "goals": [*env.run.context.get("goals", []), env.node_id]}
    go_on = ok or node["config"]["otherwise"] == "continue"
    return Result(node["next"] if go_on else None, {"filter": node["config"]["filter"]},
                  {"met": ok, **({"why": reason} if reason else {}), **({} if go_on else {"ended": "goal not met"})})


def do_end(env: Env, node: dict) -> Result:
    return Result(None)


def do_subflow(env: Env, node: dict) -> Result:
    raise StepError("Subflows are not built yet")


def field_time(env: Env, until: dict) -> datetime:
    """When a date or datetime field says (plus its offset). A date is read at `at` in the contact's time zone."""
    field_def = env.cat.fields(env.obj).get(until["field"])
    if field_def is None or field_def.type not in ("date", "datetime"):
        raise StepError(f"{until['field']} is not a date or datetime field")
    value = env.record().values.get(until["field"])
    if not value:
        raise StepError(f"{field_def.label} is empty, so there is nothing to wait for")
    if field_def.type == "datetime":
        at = datetime.fromisoformat(value)
    else:
        zone = env.record().values.get("timezone")
        try:
            tz = ZoneInfo(zone) if isinstance(zone, str) and zone else UTC
        except (KeyError, ValueError, OSError):
            tz = UTC
        day = datetime.fromisoformat(value)
        at = datetime.combine(day.date(), datetime.strptime(until["at"], "%H:%M").time(), tz)
    return at + timedelta(seconds=seconds(until["offset"]) if until.get("offset") else 0)


def do_wait(env: Env, node: dict) -> Result:
    cfg = node["config"]
    if cfg.get("event"):
        wait = cfg["event"]
        until = env.now + timedelta(seconds=seconds(wait["timeout"]))
        return Result(None, {"event": wait["event"], "match": wait["match"], "timeout": wait["timeout"]},
                      {"until": until.isoformat()}, Park(until, "event", {"event_type": wait["event"],
                                                                       "match": wait["match"]}))
    if cfg.get("until_field"):
        until, shown = field_time(env, cfg["until_field"]), cfg["until_field"]
    else:
        until, shown = env.now + timedelta(seconds=seconds(cfg["duration"])), cfg["duration"]
    if until <= env.now:  # the day has come: there is nothing to wait for
        return Result(node["next"], {"until": shown}, {"until": until.isoformat(), "already_past": True})
    return Result(node["next"], {"until": shown}, {"until": until.isoformat()}, Park(until, "timer"))


NODES = {"action": do_action, "condition": do_condition, "split": do_split, "goal": do_goal, "end": do_end,
         "subflow": do_subflow, "wait": do_wait}


def execute(env: Env, node_id: str) -> Result:
    """Runs one node: what to do next, what it was asked and what it did. Raises on a failed step."""
    return NODES[env.graph["nodes"][node_id]["type"]](env, env.graph["nodes"][node_id])


# --- state changes of a run -------------------------------------------------------------------------------------

def run_data(db: Session, run: Run, wf: Workflow) -> dict:
    return {"id": run.id, "workflow_id": wf.id, "workflow_name": wf.name,
            "version": db.get(WorkflowVersion, run.version_id).number, "record_id": run.record_id}


def trace(db: Session, run: Run, node_id: str, status: str, input_: dict, output: dict, error: str | None = None,
          started: datetime | None = None) -> Step:
    """Appends a step to the run's trace (and counts it for the loop guard)."""
    run.steps += 1
    step = Step(workspace_id=run.workspace_id, run_id=run.id, seq=run.steps, node_id=node_id, status=status,
                input=jsonable_encoder(input_), output=jsonable_encoder(output), error=error,
                started_at=started or func.clock_timestamp(), finished_at=func.clock_timestamp())
    db.add(step)
    return step


def close_waiters(db: Session, run: Run) -> None:
    db.execute(update(Waiter).where(Waiter.run_id == run.id, Waiter.resolved_at.is_(None)).values(
        resolved_at=func.now()))


def finish(db: Session, run: Run, wf: Workflow, status: str, reason: str | None = None) -> None:
    """The run ends without an error (`completed`, or `exited`: its record is gone, a publish moved it out)."""
    run.status, run.ended_at, run.wake_at = status, func.now(), None
    close_waiters(db, run)
    if not run.test:
        events.emit(db, "workflow.run_completed", "workflow_run", run.id,
                    {**run_data(db, run, wf), "status": status, "steps": run.steps, "reason": reason},
                    workspace_id=run.workspace_id, actor=("workflow", wf.id))


def go(db: Session, run: Run, wf: Workflow, node_id: str | None) -> None:
    """The run goes on at `node_id` (None: it is over), scheduling the step that runs it."""
    run.node_id, run.status, run.wake_at = node_id, "running", None
    if node_id is None:
        return finish(db, run, wf, "completed")
    schedule(db, run, node_id)


def schedule(db: Session, run: Run, node_id: str, wake: str | None = None, run_at: datetime | None = None) -> None:
    jobs.enqueue(db, "workflow.step", {"run_id": str(run.id), "node_id": node_id, "n": run.steps,
                                       **({"wake": wake} if wake else {})}, run_at=run_at)


def park(db: Session, run: Run, node_id: str, parked: Park) -> None:
    """The run waits at `node_id` until `parked.until`; an event wait also registers what it waits for."""
    run.status, run.wake_at = "waiting", parked.until
    schedule(db, run, node_id, wake="timeout" if parked.kind == "event" else parked.kind, run_at=parked.until)
    if parked.waiter:
        db.add(Waiter(workspace_id=run.workspace_id, run_id=run.id, record_id=run.record_id,
                      event_type=parked.waiter["event_type"], match=parked.waiter["match"]))


def resume(db: Session, run: Run, wf: Workflow, node: dict, how: str, **more) -> None:
    """A wait ends (`timer`, `event`, `timeout`): the trace says how, and the run goes on down the branch it took."""
    branches = node.get("branches")
    target = branches["event" if how == "event" else "timeout"] if branches else node["next"]
    trace(db, run, run.node_id, "completed", {}, {"resumed_by": how, **more})
    close_waiters(db, run)
    go(db, run, wf, target)


def fail(db: Session, run: Run, wf: Workflow, node_id: str, action: str | None, message: str, input_: dict,
         started: datetime) -> None:
    """The run stops at `node_id` with the reason; retrying it (or cancelling it) is a person's call."""
    trace(db, run, node_id, "failed", input_, {}, message, started)
    run.status, run.error, run.ended_at = "failed", message[:500], func.now()
    data = run_data(db, run, wf)
    for kind, more in (("step_failed", {"action": action}), ("run_failed", {})):
        events.emit(db, f"workflow.{kind}", "workflow_run", run.id, {**data, "node_id": node_id, "error": message[:500],
                                                                     **more},
                    workspace_id=run.workspace_id, actor=("workflow", wf.id))


def free_slot(db: Session, workspace_id: uuid.UUID) -> bool:
    """Takes one of the workspace's step slots for this transaction (an advisory lock each), or says none is free."""
    for slot in range(config.WORKFLOW_CONCURRENCY):
        digest = hashlib.blake2b(f"workflow-slot:{workspace_id}:{slot}".encode(), digest_size=8).digest()
        if db.scalar(select(func.pg_try_advisory_xact_lock(int.from_bytes(digest, "big", signed=True)))):
            return True
    return False


# --- the job ----------------------------------------------------------------------------------------------------

@jobs.handler("workflow.step")
def step(db: Session, payload: dict) -> None:
    run = db.scalar(select(Run).where(Run.id == uuid.UUID(payload["run_id"])).with_for_update())
    if run is None or run.status not in ACTIVE or run.node_id != payload["node_id"] or run.steps != payload["n"]:
        return  # a stale job: the run has moved on, and this is not its step
    wf = db.get(Workflow, run.workflow_id)
    if wf.status != "published":
        return  # paused or archived: the run is frozen, resuming queues it again
    if not free_slot(db, run.workspace_id):
        jobs.enqueue(db, "workflow.step", payload, run_at=func.now() + BUSY_RETRY)
        return
    ws = db.get(Workspace, run.workspace_id)
    with acting(db, workspace_id=ws.id, org_id=ws.org_id):
        advance(db, ws, wf, run, payload.get("wake"))


def advance(db: Session, ws: Workspace, wf: Workflow, run: Run, wake: str | None) -> None:
    """One step of a live run: the node it is at, or the end of its wait."""
    version = db.get(WorkflowVersion, run.version_id)
    node, started = version.graph["nodes"][run.node_id], db.scalar(select(func.clock_timestamp()))
    gone = db.execute(select(Record.deleted_at).where(Record.id == run.record_id)).one_or_none()
    if gone is None or gone.deleted_at is not None:
        return finish(db, run, wf, "exited", "the record was deleted")
    if run.steps >= MAX_STEPS:
        return fail(db, run, wf, run.node_id, None, f"Loop guard: the run has taken {MAX_STEPS} steps", {}, started)
    if run.status == "waiting" and wake in ("timer", "timeout"):
        return resume(db, run, wf, node, wake)  # the wait ended on its own
    run.status = "running"
    try:
        env = make_env(db, ws, wf, version, run, run.node_id)
        with db.begin_nested():
            result = execute(env, run.node_id)
    except Exception as e:  # a failed step is data, not a crash: the trace says what went wrong
        if not isinstance(e, STEP_ERRORS):
            log.exception("workflow %s run %s node %s failed", wf.id, run.id, run.node_id)
        return fail(db, run, wf, run.node_id, node.get("action"), why(e), node["config"], started)
    status = "waiting" if result.park else "completed"
    trace(db, run, run.node_id, status, result.input, result.output, None, started)
    if result.park:
        return park(db, run, run.node_id, result.park)
    go(db, run, wf, result.next)
