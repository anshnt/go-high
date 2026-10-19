"""The workflow tables (ADR 0006, migration 0012). Versions are immutable graphs; a run is one record's walk through
one version, and its steps are an append-only trace. Every reference carries the workspace id like the rest, so a row
cannot point into another workspace."""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from ..records.models import EMPTY_OBJECT, within, workspace

WORKFLOW_STATUSES = ("draft", "published", "paused", "archived")
RUN_STATUSES = ("running", "waiting", "completed", "failed", "exited", "cancelled")
ACTIVE = ("running", "waiting")  # a run that has not ended
STEP_STATUSES = ("completed", "waiting", "failed", "cancelled", "migrated")
DELIVERY_STATUSES = ("pending", "retrying", "succeeded", "failed")


def one_of(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")", name=name)


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        # the published version must be one of this workflow's own versions (added after both tables exist)
        ForeignKeyConstraint(["published_version_id", "id"], ["workflow_versions.id", "workflow_versions.workflow_id"],
                             name="fk_workflows_published_version", use_alter=True),
        one_of("status", WORKFLOW_STATUSES, "ck_workflows_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(200))
    folder: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(10), default="draft", server_default="draft")
    published_version_id: Mapped[uuid.UUID | None]
    trigger_event: Mapped[str | None] = mapped_column(String(100))  # of the published version: what enrollment looks up
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    signing_secret: Mapped[str] = mapped_column(String(100))  # signs the webhook action's requests; shown once
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_workflows_trigger", Workflow.workspace_id, Workflow.trigger_event,
      postgresql_where=text("status = 'published'"))
Index("ix_workflows_list", Workflow.workspace_id, Workflow.updated_at.desc(), Workflow.id.desc())


class WorkflowVersion(Base):
    """One saved graph. Never changed: a save is a new row, a run keeps the version it started on."""
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        UniqueConstraint("id", "workflow_id"),
        UniqueConstraint("workflow_id", "number"),
        within("workflow_id", "workflows"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    workflow_id: Mapped[uuid.UUID]
    number: Mapped[int] = mapped_column(Integer)
    graph: Mapped[dict] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the one column a request sets


class Run(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        UniqueConstraint("workflow_id", "trigger_event_id"),  # an event enrolls a record once, however often it is read
        within("workflow_id", "workflows"),
        within("record_id", "records"),
        ForeignKeyConstraint(["version_id", "workflow_id"], ["workflow_versions.id", "workflow_versions.workflow_id"]),
        one_of("status", RUN_STATUSES, "ck_workflow_runs_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    workflow_id: Mapped[uuid.UUID]
    version_id: Mapped[uuid.UUID]
    record_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(10), default="running", server_default="running")
    node_id: Mapped[str | None] = mapped_column(String(40))  # the node the run is at (the next to run, or the wait)
    context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    test: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    steps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # the loop guard counts these
    wake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when a waiting run is due
    trigger_event_id: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime] = created()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# One live run per record and workflow: the database makes double enrollment impossible, whatever the code does.
Index("uq_workflow_runs_active", Run.workflow_id, Run.record_id, unique=True,
      postgresql_where=text("status IN ('running', 'waiting') AND NOT test"))
Index("ix_workflow_runs_list", Run.workflow_id, Run.started_at.desc(), Run.id.desc())
Index("ix_workflow_runs_record", Run.record_id, Run.started_at.desc())
Index("ix_workflow_runs_active_record", Run.workspace_id, Run.record_id, postgresql_where=text(
    "status IN ('running', 'waiting') AND NOT test"))


class Step(Base):
    """What happened at one node: its input (what it was asked to do), its output and its error. Append only."""
    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "seq"),
        within("run_id", "workflow_runs"),
        one_of("status", STEP_STATUSES, "ck_workflow_steps_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    run_id: Mapped[uuid.UUID]
    seq: Mapped[int] = mapped_column(Integer)
    node_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10))
    input: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    output: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime] = created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TriggerCheck(Base):
    """One evaluation of a workflow's trigger against an event, hits and misses alike, kept for 7 days: this is what
    answers "why did this record not enter". `reason` names the clause that failed. No foreign key to events (they
    are partitioned later) or records."""
    __tablename__ = "workflow_trigger_checks"
    __table_args__ = (UniqueConstraint("workflow_id", "event_id"), within("workflow_id", "workflows"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    workflow_id: Mapped[uuid.UUID]
    version_id: Mapped[uuid.UUID | None]
    event_id: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(100))
    record_id: Mapped[uuid.UUID | None]
    matched: Mapped[bool] = mapped_column(Boolean)
    outcome: Mapped[str] = mapped_column(String(20))  # entered, filter, object, data, reentry, running, self, no_record
    reason: Mapped[str | None] = mapped_column(String(500))
    run_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = created()


Index("ix_workflow_trigger_checks_record", TriggerCheck.workflow_id, TriggerCheck.record_id,
      TriggerCheck.created_at.desc())
Index("ix_workflow_trigger_checks_age", TriggerCheck.created_at)


class Waiter(Base):
    """A run waiting for an event on its record; the consumer resolves it. `match` is what the event's data must
    contain."""
    __tablename__ = "workflow_waiters"
    __table_args__ = (within("run_id", "workflow_runs"),)

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    run_id: Mapped[uuid.UUID]
    record_id: Mapped[uuid.UUID]
    event_type: Mapped[str] = mapped_column(String(100))
    match: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    created_at: Mapped[datetime] = created()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_workflow_waiters_open", Waiter.workspace_id, Waiter.record_id, Waiter.event_type,
      postgresql_where=text("resolved_at IS NULL"))
Index("ix_workflow_waiters_run", Waiter.run_id)


class Ref(Base):
    """What a version uses, extracted when it is saved: a tag, a field (`contact.email`), a stage, a person, a channel,
    a form or a calendar, by id or by key. One query answers "what uses this tag"."""
    __tablename__ = "workflow_refs"
    __table_args__ = (
        within("workflow_id", "workflows"),
        ForeignKeyConstraint(["version_id", "workflow_id"], ["workflow_versions.id", "workflow_versions.workflow_id"],
                             ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    workflow_id: Mapped[uuid.UUID]
    version_id: Mapped[uuid.UUID]
    node_id: Mapped[str | None] = mapped_column(String(40))  # null: the trigger
    kind: Mapped[str] = mapped_column(String(20))
    ref_id: Mapped[uuid.UUID | None]
    ref_key: Mapped[str | None] = mapped_column(String(200))


Index("ix_workflow_refs_id", Ref.workspace_id, Ref.kind, Ref.ref_id)
Index("ix_workflow_refs_key", Ref.workspace_id, Ref.kind, Ref.ref_key)
Index("ix_workflow_refs_version", Ref.version_id)


class Delivery(Base):
    """The outbox of the webhook action: the step writes the row (its idempotency key is `run:node`, unique), a
    `workflow.deliver` job sends it, so a step that runs twice still sends once."""
    __tablename__ = "workflow_deliveries"
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key"),
        within("workflow_id", "workflows"),
        within("run_id", "workflow_runs"),
        one_of("status", DELIVERY_STATUSES, "ck_workflow_deliveries_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    workflow_id: Mapped[uuid.UUID]
    run_id: Mapped[uuid.UUID]
    node_id: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(2000))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_status: Mapped[int | None]
    response_ms: Mapped[int | None]
    response_body_excerpt: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = created()


Index("ix_workflow_deliveries_run", Delivery.run_id)
