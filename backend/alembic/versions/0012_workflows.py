"""workflows, immutable versions, runs, steps, trigger checks, waiters, dependency index and the webhook outbox; the
idempotency key of a message; the workflow capabilities

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
EMPTY_OBJECT = sa.text("'{}'::jsonb")
# frozen: the statuses this migration knew
WORKFLOW_STATUSES = ("draft", "published", "paused", "archived")
RUN_STATUSES = ("running", "waiting", "completed", "failed", "exited", "cancelled")
STEP_STATUSES = ("completed", "waiting", "failed", "cancelled", "migrated")
DELIVERY_STATUSES = ("pending", "retrying", "succeeded", "failed")
# frozen: what each system role of an existing organization gains (a new organization gets them from
# app/roles_seed.py). Custom roles get nothing: an admin adds them to the roles that should have them.
# `workflows.publish` was in the catalog before this module, and the roles that had it keep it.
GRANTS = {"owner": ("workflows.read", "workflows.write", "workflows.publish"),
          "admin": ("workflows.read", "workflows.write", "workflows.publish"),
          "manager": ("workflows.read", "workflows.write", "workflows.publish"),
          "member": ("workflows.read", "workflows.write"), "viewer": ("workflows.read",)}
CAPABILITIES = ("workflows.read", "workflows.write")  # what the downgrade takes away (publish was there before)


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def created(name: str = "created_at") -> sa.Column:
    return col(name, TS, server_default=sa.func.now())


def workspace() -> sa.Column:
    return col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"))


def pk() -> sa.Column:
    return col("id", sa.Uuid(), **UUID_PK)


def user(name: str) -> sa.Column:
    return col(name, sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def within(column: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column, "workspace_id"], [f"{table}.id", f"{table}.workspace_id"],
                                   ondelete="CASCADE")


def own_version() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["version_id", "workflow_id"],
                                   ["workflow_versions.id", "workflow_versions.workflow_id"])


def tables() -> None:
    op.create_table(
        "workflows", pk(), workspace(), col("name", sa.String(200)), col("folder", sa.String(100), nullable=True),
        col("status", sa.String(10), server_default="draft"), col("published_version_id", sa.Uuid(), nullable=True),
        col("trigger_event", sa.String(100), nullable=True),
        col("settings", postgresql.JSONB(), server_default=EMPTY_OBJECT), user("owner_id"),
        col("signing_secret", sa.String(100)), user("created_by"), created(), created("updated_at"),
        sa.UniqueConstraint("id", "workspace_id"), sa.CheckConstraint(in_list("status", WORKFLOW_STATUSES),
                                                                      name="ck_workflows_status"))
    op.create_index("ix_workflows_trigger", "workflows", ["workspace_id", "trigger_event"],
                    postgresql_where=sa.text("status = 'published'"))
    op.create_index("ix_workflows_list", "workflows", ["workspace_id", sa.text("updated_at DESC"), sa.text("id DESC")])
    op.create_table(
        "workflow_versions", pk(), workspace(), col("workflow_id", sa.Uuid()), col("number", sa.Integer()),
        col("graph", postgresql.JSONB()), col("note", sa.String(500), nullable=True), user("created_by"), created(),
        col("published_at", TS, nullable=True), sa.UniqueConstraint("id", "workspace_id"),
        sa.UniqueConstraint("id", "workflow_id"), sa.UniqueConstraint("workflow_id", "number"),
        within("workflow_id", "workflows"))
    op.create_foreign_key("fk_workflows_published_version", "workflows", "workflow_versions",
                          ["published_version_id", "id"], ["id", "workflow_id"])
    op.create_table(
        "workflow_runs", pk(), workspace(), col("workflow_id", sa.Uuid()), col("version_id", sa.Uuid()),
        col("record_id", sa.Uuid()), col("status", sa.String(10), server_default="running"),
        col("node_id", sa.String(40), nullable=True), col("context", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("test", sa.Boolean(), server_default=sa.text("false")), col("steps", sa.Integer(), server_default="0"),
        col("wake_at", TS, nullable=True), col("trigger_event_id", sa.BigInteger(), nullable=True),
        col("error", sa.String(500), nullable=True), created("started_at"), col("ended_at", TS, nullable=True),
        sa.UniqueConstraint("id", "workspace_id"), sa.UniqueConstraint("workflow_id", "trigger_event_id"),
        within("workflow_id", "workflows"), within("record_id", "records"), own_version(),
        sa.CheckConstraint(in_list("status", RUN_STATUSES), name="ck_workflow_runs_status"))
    op.create_index("uq_workflow_runs_active", "workflow_runs", ["workflow_id", "record_id"], unique=True,
                    postgresql_where=sa.text("status IN ('running', 'waiting') AND NOT test"))
    op.create_index("ix_workflow_runs_list", "workflow_runs",
                    ["workflow_id", sa.text("started_at DESC"), sa.text("id DESC")])
    op.create_index("ix_workflow_runs_record", "workflow_runs", ["record_id", sa.text("started_at DESC")])
    op.create_index("ix_workflow_runs_active_record", "workflow_runs", ["workspace_id", "record_id"],
                    postgresql_where=sa.text("status IN ('running', 'waiting') AND NOT test"))
    op.create_table(
        "workflow_steps", pk(), workspace(), col("run_id", sa.Uuid()), col("seq", sa.Integer()),
        col("node_id", sa.String(40)), col("status", sa.String(10)),
        col("input", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("output", postgresql.JSONB(), server_default=EMPTY_OBJECT), col("error", sa.String(500), nullable=True),
        created("started_at"), col("finished_at", TS, nullable=True), sa.UniqueConstraint("run_id", "seq"),
        within("run_id", "workflow_runs"), sa.CheckConstraint(in_list("status", STEP_STATUSES),
                                                              name="ck_workflow_steps_status"))
    op.create_table(
        "workflow_trigger_checks", pk(), workspace(), col("workflow_id", sa.Uuid()),
        col("version_id", sa.Uuid(), nullable=True), col("event_id", sa.BigInteger()),
        col("event_type", sa.String(100)), col("record_id", sa.Uuid(), nullable=True), col("matched", sa.Boolean()),
        col("outcome", sa.String(20)), col("reason", sa.String(500), nullable=True),
        col("run_id", sa.Uuid(), nullable=True), created(), sa.UniqueConstraint("workflow_id", "event_id"),
        within("workflow_id", "workflows"))
    op.create_index("ix_workflow_trigger_checks_record", "workflow_trigger_checks",
                    ["workflow_id", "record_id", sa.text("created_at DESC")])
    op.create_index("ix_workflow_trigger_checks_age", "workflow_trigger_checks", ["created_at"])
    op.create_table(
        "workflow_waiters", pk(), workspace(), col("run_id", sa.Uuid()), col("record_id", sa.Uuid()),
        col("event_type", sa.String(100)), col("match", postgresql.JSONB(), server_default=EMPTY_OBJECT), created(),
        col("resolved_at", TS, nullable=True), within("run_id", "workflow_runs"))
    op.create_index("ix_workflow_waiters_open", "workflow_waiters", ["workspace_id", "record_id", "event_type"],
                    postgresql_where=sa.text("resolved_at IS NULL"))
    op.create_index("ix_workflow_waiters_run", "workflow_waiters", ["run_id"])
    op.create_table(
        "workflow_refs", pk(), workspace(), col("workflow_id", sa.Uuid()), col("version_id", sa.Uuid()),
        col("node_id", sa.String(40), nullable=True), col("kind", sa.String(20)),
        col("ref_id", sa.Uuid(), nullable=True), col("ref_key", sa.String(200), nullable=True),
        within("workflow_id", "workflows"),
        sa.ForeignKeyConstraint(["version_id", "workflow_id"],
                                ["workflow_versions.id", "workflow_versions.workflow_id"], ondelete="CASCADE"))
    op.create_index("ix_workflow_refs_id", "workflow_refs", ["workspace_id", "kind", "ref_id"])
    op.create_index("ix_workflow_refs_key", "workflow_refs", ["workspace_id", "kind", "ref_key"])
    op.create_index("ix_workflow_refs_version", "workflow_refs", ["version_id"])
    op.create_table(
        "workflow_deliveries", pk(), workspace(), col("workflow_id", sa.Uuid()), col("run_id", sa.Uuid()),
        col("node_id", sa.String(40)), col("idempotency_key", sa.String(120)), col("url", sa.String(2000)),
        col("body", sa.Text()), col("status", sa.String(10), server_default="pending"),
        col("attempts", sa.Integer(), server_default="0"), col("next_attempt_at", TS, nullable=True),
        col("response_status", sa.Integer(), nullable=True), col("response_ms", sa.Integer(), nullable=True),
        col("response_body_excerpt", sa.Text(), nullable=True), col("error", sa.String(300), nullable=True), created(),
        sa.UniqueConstraint("workspace_id", "idempotency_key"), within("workflow_id", "workflows"),
        within("run_id", "workflow_runs"), sa.CheckConstraint(in_list("status", DELIVERY_STATUSES),
                                                              name="ck_workflow_deliveries_status"))
    op.create_index("ix_workflow_deliveries_run", "workflow_deliveries", ["run_id"])
    op.add_column("messages", sa.Column("idempotency_key", sa.String(120), nullable=True))
    op.create_index("uq_messages_idempotency", "messages", ["workspace_id", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("idempotency_key IS NOT NULL"))


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"

# table: privileges for gohigh_app. Nothing is deleted by a request: a workflow is archived, a version is never
# changed (but for the time it was published), the trace is append only, and the worker prunes the trigger checks.
# The webhook outbox is written by a step and updated by the worker only.
RLS = {
    "workflows": "SELECT, INSERT, UPDATE", "workflow_versions": "SELECT, INSERT, UPDATE (published_at)",
    "workflow_runs": "SELECT, INSERT, UPDATE", "workflow_steps": "SELECT, INSERT",
    "workflow_trigger_checks": "SELECT, INSERT", "workflow_waiters": "SELECT, INSERT, UPDATE",
    "workflow_refs": "SELECT, INSERT", "workflow_deliveries": "SELECT, INSERT",
}


def upgrade() -> None:
    tables()
    for table, privileges in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {WORKSPACE}")
    # roles have row level security forced on them, which applies to their owner too: the system setting (what sign up
    # uses) lets this migration change them
    op.execute("SELECT set_config('app.system', 'on', true)")
    connection = op.get_bind()
    for key, capabilities in GRANTS.items():
        # only what a role lacks: roles seeded by an older migration may hold some of them already
        connection.execute(sa.text("UPDATE roles SET capabilities = capabilities || array(SELECT c FROM "
                                   "unnest(CAST(:caps AS text[])) c WHERE c <> ALL(capabilities)) "
                                   "WHERE is_system AND key = :key"), {"caps": list(capabilities), "key": key})


def downgrade() -> None:
    op.execute("SELECT set_config('app.system', 'on', true)")
    op.get_bind().execute(sa.text("UPDATE roles SET capabilities = array(SELECT c FROM unnest(capabilities) c "
                                  "WHERE c <> ALL(CAST(:caps AS text[])))"), {"caps": list(CAPABILITIES)})
    op.drop_index("uq_messages_idempotency", "messages")
    op.drop_column("messages", "idempotency_key")
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")
