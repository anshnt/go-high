"""pipelines, stages, board layouts, a board position on records; a stage field that holds a stage id

Revision ID: 0007
Revises: 0004
Create Date: 2026-10-18
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
EMPTY_OBJECT = sa.text("'{}'::jsonb")
STAGE_KINDS = ("open", "won", "lost")
# frozen: the placeholder stages that deals held before pipelines existed, and the stage of the Sales pipeline each
# one becomes (the names are those of seed.DEFAULT_STAGES)
PLACEHOLDERS = (("new", "Lead"), ("qualified", "Qualified"), ("proposal", "Proposal"), ("negotiation", "Negotiation"),
                ("won", "Won"), ("lost", "Lost"))
OLD_CHOICES = [{"id": i, "label": label, "color": color} for i, label, color in (
    ("new", "New", "gray"), ("qualified", "Qualified", "blue"), ("proposal", "Proposal", "amber"),
    ("negotiation", "Negotiation", "amber"), ("won", "Won", "green"), ("lost", "Lost", "red"))]
LOST_REASON = {"choices": [{"id": i, "label": label, "color": "gray"} for i, label in (
    ("price", "Price"), ("timing", "Timing"), ("competitor", "Competitor"), ("no_decision", "No decision"),
    ("other", "Other"))]}


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def created(name: str = "created_at") -> sa.Column:
    return col(name, TS, server_default=sa.func.now())


def workspace() -> sa.Column:
    return col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"))


def within(column: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column, "workspace_id"], [f"{table}.id", f"{table}.workspace_id"],
                                   ondelete="CASCADE")


def tables() -> None:
    op.create_table(
        "pipelines", col("id", sa.Uuid(), **UUID_PK), workspace(),
        col("object_key", sa.String(40), server_default="deal"), col("name", sa.String(100)),
        col("position", sa.Integer(), server_default="0"), col("archived_at", TS, nullable=True), created(),
        sa.UniqueConstraint("id", "workspace_id"))
    op.create_table(
        "stages", col("id", sa.Uuid(), **UUID_PK), workspace(), col("pipeline_id", sa.Uuid()),
        col("name", sa.String(100)), col("position", sa.Integer(), server_default="0"),
        col("kind", sa.String(4), server_default="open"), col("probability", sa.Integer(), server_default="0"),
        col("rotting_days", sa.Integer(), nullable=True),
        col("exit_rules", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("color", sa.String(20), nullable=True), created(),
        sa.UniqueConstraint("id", "workspace_id"), within("pipeline_id", "pipelines"),
        sa.CheckConstraint("kind IN (" + ", ".join(f"'{k}'" for k in STAGE_KINDS) + ")", name="ck_stages_kind"),
        sa.CheckConstraint("probability BETWEEN 0 AND 100", name="ck_stages_probability"),
        sa.CheckConstraint("rotting_days > 0", name="ck_stages_rotting_days"))
    op.create_index("ix_stages_pipeline", "stages", ["pipeline_id", "position"])
    op.create_table(
        "board_layouts", col("pipeline_id", sa.Uuid(), primary_key=True),
        col("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True), workspace(),
        col("layout", postgresql.JSONB(), server_default=EMPTY_OBJECT), created("updated_at"),
        within("pipeline_id", "pipelines"))
    op.add_column("records", sa.Column("stage_id", sa.Uuid(), nullable=True))
    op.add_column("records", sa.Column("board_position", sa.Numeric(), nullable=True))


def backfill(connection) -> None:
    """Every workspace gets the Sales pipeline. Its deals hold placeholder stage ids from before pipelines: they become
    the stages of that name, newest deal on top, and the deal object gets the lost reason fields (a new database
    already has them from the seed, hence ON CONFLICT). A deal's `stage_id` column follows its value; a value that
    names no stage keeps the value and has no column."""
    from app.records import seed

    for workspace_id in connection.execute(sa.text("SELECT id FROM workspaces")).scalars().all():
        seed.add_pipeline(connection, workspace_id)
    connection.execute(sa.text(
        "UPDATE records r SET values = jsonb_set(r.values, '{stage}', to_jsonb(s.id::text)), "
        "board_position = -extract(epoch FROM r.created_at) "
        "FROM objects o, stages s, (VALUES " + ", ".join(f"('{old}', '{name}')" for old, name in PLACEHOLDERS)
        + ") AS m (old, name) "
        "WHERE o.id = r.object_id AND o.key = 'deal' AND r.values ->> 'stage' = m.old "
        "AND s.workspace_id = r.workspace_id AND s.name = m.name"))
    connection.execute(sa.text(
        "UPDATE records r SET stage_id = s.id FROM stages s, objects o WHERE o.id = r.object_id AND o.key = 'deal' "
        "AND s.workspace_id = r.workspace_id AND r.values ->> 'stage' = s.id::text"))
    connection.execute(sa.text(
        "UPDATE fields f SET options = '{}'::jsonb FROM objects o "
        "WHERE o.id = f.object_id AND o.key = 'deal' AND f.key = 'stage'"))
    for key, label, type_, options in (("lost_reason", "Lost reason", "select", LOST_REASON),
                                       ("lost_note", "Lost note", "long_text", {})):
        connection.execute(sa.text(
            "INSERT INTO fields (workspace_id, object_id, key, label, type, options, is_system, position) "
            "SELECT o.workspace_id, o.id, :key, :label, :type, CAST(:options AS jsonb), true, "
            "(SELECT coalesce(max(position), 0) + 1 FROM fields WHERE object_id = o.id) "
            "FROM objects o WHERE o.key = 'deal' ON CONFLICT (object_id, key) DO NOTHING"),
            {"key": key, "label": label, "type": type_, "options": json.dumps(options)})


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"
# a layout is its user's: the policy hides it from everyone else in the workspace
OWN = ("FOR ALL USING (workspace_id = app_workspace_id() AND user_id = app_user_id()) "
       "WITH CHECK (workspace_id = app_workspace_id() AND user_id = app_user_id())")
# table: (privileges for gohigh_app, policy). A pipeline or a stage with no deals is deleted by request.
RLS = {
    "pipelines": ("SELECT, INSERT, UPDATE, DELETE", WORKSPACE),
    "stages": ("SELECT, INSERT, UPDATE, DELETE", WORKSPACE),
    "board_layouts": ("SELECT, INSERT, UPDATE", OWN),
}


def upgrade() -> None:
    tables()
    backfill(op.get_bind())  # before row level security is switched on, so the owner role can write
    op.create_foreign_key(None, "records", "stages", ["stage_id", "workspace_id"], ["id", "workspace_id"])
    op.create_index("ix_records_stage", "records", ["workspace_id", "stage_id", "board_position", "id"],
                    postgresql_where=sa.text("deleted_at IS NULL AND stage_id IS NOT NULL"))
    for table, (privileges, policy) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {policy}")


def downgrade() -> None:
    """Deals go back to the placeholder stage of the same name; one in a stage with another name loses its stage."""
    connection = op.get_bind()
    connection.execute(sa.text(
        "UPDATE records r SET values = jsonb_set(r.values, '{stage}', to_jsonb(m.old)) "
        "FROM stages s, (VALUES " + ", ".join(f"('{old}', '{name}')" for old, name in PLACEHOLDERS)
        + ") AS m (old, name) WHERE r.values ->> 'stage' = s.id::text AND s.workspace_id = r.workspace_id "
        "AND s.name = m.name"))
    connection.execute(sa.text("UPDATE records SET values = values - 'stage' WHERE values ->> 'stage' ~ '-'"))
    connection.execute(sa.text(
        "UPDATE fields f SET options = CAST(:choices AS jsonb) FROM objects o "
        "WHERE o.id = f.object_id AND o.key = 'deal' AND f.key = 'stage'"),
        {"choices": json.dumps({"choices": OLD_CHOICES})})
    connection.execute(sa.text(
        "DELETE FROM fields f USING objects o WHERE o.id = f.object_id AND o.key = 'deal' "
        "AND f.key IN ('lost_reason', 'lost_note')"))
    op.drop_index("ix_records_stage", "records")
    op.drop_column("records", "stage_id")  # and its foreign key
    op.drop_column("records", "board_position")
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")
