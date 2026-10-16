"""event log, consumer cursors, webhooks, idempotency keys

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))


class XID8(sa.types.UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "xid8"


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def created() -> sa.Column:
    return col("created_at", TS, server_default=sa.func.now())


def tables() -> None:
    # ponytail: a plain table; monthly partitions on occurred_at come with the 90 day retention (ADR 0003).
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        col("txid", XID8(), server_default=sa.text("pg_current_xact_id()")),
        col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE")),
        col("type", sa.String(100)), col("subject_type", sa.String(50)), col("subject_id", sa.Uuid()),
        col("actor_type", sa.String(20)), col("actor_id", sa.Uuid(), nullable=True),
        col("data", postgresql.JSONB()), col("occurred_at", TS, server_default=sa.func.now()),
    )
    op.create_index("ix_events_subject", "events", ["workspace_id", "subject_id", sa.text("occurred_at DESC")])
    op.create_index("ix_events_txid_id", "events", ["txid", "id"])
    op.create_table("event_cursors", col("consumer", sa.String(100), primary_key=True),
                    col("last_txid", XID8(), server_default=sa.text("'0'")),
                    col("last_id", sa.BigInteger(), server_default=sa.text("0")))

    op.create_table(
        "webhook_endpoints",
        col("id", sa.Uuid(), **UUID_PK),
        col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE")),
        col("url", sa.String(2000)), col("event_types", postgresql.ARRAY(sa.String(100))),
        col("filter", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
        col("secret", sa.String(100)), col("active", sa.Boolean(), server_default=sa.text("true")),
        col("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        col("disabled_reason", sa.String(200), nullable=True), col("failing_since", TS, nullable=True), created(),
        sa.UniqueConstraint("id", "workspace_id"),
    )
    op.create_index("ix_webhook_endpoints_workspace_id", "webhook_endpoints", ["workspace_id"])

    # No foreign key to events: they get partitioned, which would block it (the worker checks the workspace).
    op.create_table(
        "webhook_deliveries",
        col("id", sa.Uuid(), **UUID_PK), col("workspace_id", sa.Uuid()), col("endpoint_id", sa.Uuid()),
        col("event_id", sa.BigInteger()), col("status", sa.String(10), server_default="pending"),
        col("attempts", sa.Integer(), server_default="0"), col("next_attempt_at", TS, nullable=True),
        col("response_status", sa.Integer(), nullable=True), col("response_ms", sa.Integer(), nullable=True),
        col("response_body_excerpt", sa.Text(), nullable=True), col("error", sa.String(300), nullable=True),
        col("replay_of", sa.Uuid(), sa.ForeignKey("webhook_deliveries.id", ondelete="SET NULL"), nullable=True),
        created(),
        sa.ForeignKeyConstraint(["endpoint_id", "workspace_id"],
                                ["webhook_endpoints.id", "webhook_endpoints.workspace_id"], ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('pending', 'retrying', 'succeeded', 'failed')",
                           name="ck_webhook_deliveries_status"),
    )
    op.create_index("ix_webhook_deliveries_endpoint", "webhook_deliveries",
                    ["endpoint_id", sa.text("created_at DESC"), sa.text("id DESC")])

    op.create_table(
        "idempotency_keys",
        col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        col("key", sa.String(255), primary_key=True), col("request_hash", sa.String(64)), col("status", sa.Integer()),
        col("response", postgresql.JSONB()), created(),
    )
    op.create_index("ix_idempotency_keys_created", "idempotency_keys", ["workspace_id", "created_at"])


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"

# table: (privileges for gohigh_app, also a "system" policy). Only events gets one: sign up runs with
# app.system = 'on' and emits workspace.created and user.signed_up. Nothing else needs the broad scope.
RLS = {
    "events": ("SELECT, INSERT", True),  # SELECT: an INSERT reads its new row back (RETURNING) and the log is readable
    "webhook_endpoints": ("SELECT, INSERT, UPDATE, DELETE", False),
    "webhook_deliveries": ("SELECT, INSERT", False),  # the worker (owner role) records attempts; replay inserts
    "idempotency_keys": ("SELECT, INSERT, DELETE", False),  # DELETE: expired keys are removed on the next store
}


def upgrade() -> None:
    tables()
    for table, (privileges, system) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {WORKSPACE}")
        if system:
            op.execute(f"CREATE POLICY system ON {table} FOR ALL USING (app_system()) WITH CHECK (app_system())")
    op.execute("GRANT USAGE ON SEQUENCE events_id_seq TO gohigh_app")
    # Request handlers enqueue jobs (emit wakes the dispatcher). The queue is not tenant data and has no row level
    # security, so gohigh_app may only add rows and read back their id; the worker keeps the owner role.
    op.execute("GRANT INSERT, SELECT (id) ON jobs TO gohigh_app")
    op.execute("GRANT USAGE ON SEQUENCE jobs_id_seq TO gohigh_app")


def downgrade() -> None:
    op.execute("REVOKE USAGE ON SEQUENCE jobs_id_seq FROM gohigh_app")
    op.execute("REVOKE INSERT, SELECT (id) ON jobs FROM gohigh_app")
    for table in ("idempotency_keys", "webhook_deliveries", "webhook_endpoints", "event_cursors", "events"):
        op.execute(f"DROP TABLE {table} CASCADE")
