"""tasks, notifications, notification preferences, the tasks capabilities of the system roles

Revision ID: 0009
Revises: 0005
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0005"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
FALSE = sa.text("false")


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def created(name: str = "created_at") -> sa.Column:
    return col(name, TS, server_default=sa.func.now())


def workspace() -> sa.Column:
    return col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"))


def user(name: str, **kw) -> sa.Column:
    return col(name, sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, **kw)


def tables() -> None:
    op.create_table(
        "tasks", col("id", sa.Uuid(), **UUID_PK), workspace(), col("title", sa.String(300)),
        col("notes", sa.Text(), server_default=""), col("due_at", TS, nullable=True),
        col("all_day", sa.Boolean(), server_default=FALSE), user("assignee_id"), user("created_by"),
        col("priority", sa.String(6), server_default="none"), col("status", sa.String(4), server_default="open"),
        col("completed_at", TS, nullable=True), col("record_id", sa.Uuid(), nullable=True),
        col("recurrence", sa.String(200), nullable=True), col("parent_task_id", sa.Uuid(), nullable=True),
        col("depends_on_task_id", sa.Uuid(), nullable=True),
        col("position", postgresql.DOUBLE_PRECISION(), server_default="0"), created(), created("updated_at"),
        sa.UniqueConstraint("id", "workspace_id"),
        sa.ForeignKeyConstraint(["record_id", "workspace_id"], ["records.id", "records.workspace_id"],
                                ondelete="CASCADE"),
        # no cascade: deleting a task first clears what points at it (the API does), so a series or a dependent
        # task is never deleted along with it
        sa.ForeignKeyConstraint(["parent_task_id", "workspace_id"], ["tasks.id", "tasks.workspace_id"]),
        sa.ForeignKeyConstraint(["depends_on_task_id", "workspace_id"], ["tasks.id", "tasks.workspace_id"]),
        sa.CheckConstraint("priority IN ('none', 'low', 'medium', 'high')", name="ck_tasks_priority"),
        sa.CheckConstraint("status IN ('open', 'done')", name="ck_tasks_status"),
        sa.CheckConstraint("(status = 'done') = (completed_at IS NOT NULL)", name="ck_tasks_completed"),
        sa.CheckConstraint("recurrence IS NULL OR due_at IS NOT NULL", name="ck_tasks_recurrence_due"),
        sa.CheckConstraint("depends_on_task_id IS DISTINCT FROM id", name="ck_tasks_depends_self"))
    op.create_index("ix_tasks_list", "tasks", ["workspace_id", "position", "id"])
    op.create_index("ix_tasks_assignee", "tasks", ["workspace_id", "assignee_id", "due_at"],
                    postgresql_where=sa.text("status = 'open'"))
    op.create_index("ix_tasks_record", "tasks", ["record_id"], postgresql_where=sa.text("record_id IS NOT NULL"))
    op.create_index("ix_tasks_parent", "tasks", ["parent_task_id"],
                    postgresql_where=sa.text("parent_task_id IS NOT NULL"))
    op.create_index("ix_tasks_depends_on", "tasks", ["depends_on_task_id"],
                    postgresql_where=sa.text("depends_on_task_id IS NOT NULL"))

    # created_at is when the notification shows up: a held one (quiet hours) is dated at the end of the quiet hours
    op.create_table(
        "notifications", col("id", sa.Uuid(), **UUID_PK), workspace(),
        col("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")), col("kind", sa.String(40)),
        col("title", sa.String(300)), col("body", sa.Text(), server_default=""),
        col("link", sa.String(300), nullable=True),
        col("subject_type", sa.String(20), nullable=True), col("subject_id", sa.Uuid(), nullable=True),
        col("dedupe_key", sa.String(200), nullable=True), created(), col("read_at", TS, nullable=True),
        sa.UniqueConstraint("user_id", "dedupe_key"))
    op.create_index("ix_notifications_user", "notifications",
                    ["workspace_id", "user_id", sa.text("created_at DESC"), sa.text("id DESC")])
    op.create_index("ix_notifications_unread", "notifications", ["workspace_id", "user_id"],
                    postgresql_where=sa.text("read_at IS NULL"))

    op.create_table(
        "notification_prefs",
        col("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        col("kind", sa.String(40), primary_key=True),
        col("channels", postgresql.ARRAY(sa.String(10)), server_default=sa.text("'{in_app}'")),
        col("scope", sa.String(4), server_default="mine"), col("quiet_start", sa.Time(), nullable=True),
        col("quiet_end", sa.Time(), nullable=True), col("tz", sa.String(64), nullable=True),
        col("digest", sa.String(5), server_default="off"),
        sa.CheckConstraint("scope IN ('all', 'mine')", name="ck_notification_prefs_scope"),
        sa.CheckConstraint("digest IN ('daily', 'off')", name="ck_notification_prefs_digest"),
        sa.CheckConstraint("channels <@ ARRAY['in_app', 'email']::varchar[]", name="ck_notification_prefs_channels"))


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"
# a notification, like a preference, is its user's alone: not even the rest of the workspace sees it
OWN = ("FOR ALL USING (workspace_id = app_workspace_id() AND user_id = app_user_id()) "
       "WITH CHECK (workspace_id = app_workspace_id() AND user_id = app_user_id())")

# table: (privileges for gohigh_app, policy). Notifications are written by the worker (the owner role); a request
# may only read its user's and mark them read, so the one column it can change is read_at.
RLS = {
    "tasks": ("SELECT, INSERT, UPDATE, DELETE", WORKSPACE),
    "notifications": ("SELECT, UPDATE (read_at)", OWN),
    "notification_prefs": ("SELECT, INSERT, UPDATE", OWN),
}

# frozen: what each system role gets (the capabilities are in permissions.CATALOG, and in roles_seed for new
# organizations). A custom role keeps what it has: an admin adds tasks to it from the role editor.
READ, WRITE, DELETE = "tasks.read", "tasks.write", "tasks.delete"
GRANTS = {("owner", "admin", "manager", "member"): (READ, WRITE, DELETE), ("viewer",): (READ,),
          ("automation",): (READ, WRITE)}

# Notifications start from the end of the log: events from before this migration never become notifications.
START_CURSOR = """
INSERT INTO event_cursors (consumer, last_txid, last_id)
SELECT 'notifications', txid, id FROM events ORDER BY txid DESC, id DESC LIMIT 1
ON CONFLICT DO NOTHING"""


def upgrade() -> None:
    tables()
    for table, (privileges, policy) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {policy}")
    for keys, capabilities in GRANTS.items():
        wanted = "ARRAY[" + ", ".join(f"'{c}'" for c in capabilities) + "]::text[]"
        op.execute(f"UPDATE roles SET capabilities = capabilities || ARRAY(SELECT c FROM unnest({wanted}) c "
                   f"WHERE c <> ALL (capabilities)) WHERE is_system AND key IN ({', '.join(repr(k) for k in keys)})")
    op.execute(START_CURSOR)


def downgrade() -> None:
    op.execute("UPDATE roles SET capabilities = ARRAY(SELECT c FROM unnest(capabilities) c WHERE c NOT LIKE 'tasks.%')")
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")
    op.execute("DELETE FROM event_cursors WHERE consumer = 'notifications'")
