"""record engine: objects, fields, records, tags, associations, saved views; system objects for every workspace

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
EMPTY_OBJECT = sa.text("'{}'::jsonb")
FALSE = sa.text("false")
# frozen: the types and cardinalities this migration knew
FIELD_TYPES = ("text", "long_text", "number", "money", "date", "datetime", "boolean", "select", "multi_select", "email",
               "phone", "url", "user", "record", "stage", "formula", "rollup")
CARDINALITIES = ("one_to_one", "one_to_many", "many_to_many")


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def created(name: str = "created_at") -> sa.Column:
    return col(name, TS, server_default=sa.func.now())


def workspace() -> sa.Column:
    return col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"))


def pk() -> sa.Column:
    return col("id", sa.Uuid(), **UUID_PK)


def within(column: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column, "workspace_id"], [f"{table}.id", f"{table}.workspace_id"],
                                   ondelete="CASCADE")


def in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def tables() -> None:
    op.create_table(
        "objects", pk(), workspace(), col("key", sa.String(40)), col("singular", sa.String(100)),
        col("plural", sa.String(100)), col("icon", sa.String(50), server_default="box"),
        col("is_system", sa.Boolean(), server_default=FALSE),
        col("primary_fields", postgresql.ARRAY(sa.String(63))), col("archived_at", TS, nullable=True), created(),
        sa.UniqueConstraint("workspace_id", "key"), sa.UniqueConstraint("id", "workspace_id"))
    op.create_table(
        "fields", pk(), workspace(), col("object_id", sa.Uuid()), col("key", sa.String(63)),
        col("label", sa.String(100)), col("type", sa.String(20)),
        col("options", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("rules", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("is_system", sa.Boolean(), server_default=FALSE), col("position", sa.Integer(), server_default="0"),
        col("archived_at", TS, nullable=True), created(),
        sa.UniqueConstraint("object_id", "key"), within("object_id", "objects"),
        sa.CheckConstraint(in_list("type", FIELD_TYPES), name="ck_fields_type"))
    op.create_table(
        "records", pk(), workspace(), col("object_id", sa.Uuid()),
        col("display_name", sa.String(300), server_default=""),
        col("values", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("email_norm", sa.String(254), nullable=True), col("phone_e164", sa.String(20), nullable=True),
        col("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        col("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        created(), created("updated_at"), col("deleted_at", TS, nullable=True),
        sa.Column("search", postgresql.TSVECTOR(), sa.Computed(
            "setweight(to_tsvector('simple', coalesce(display_name, '')), 'A') || "
            "setweight(to_tsvector('simple', \"values\"), 'B')", persisted=True)),
        sa.UniqueConstraint("id", "workspace_id"), within("object_id", "objects"))
    op.create_index("ix_records_list", "records", ["workspace_id", "object_id", sa.text("updated_at DESC")])
    op.create_index("ix_records_search", "records", ["search"], postgresql_using="gin")
    op.create_index("ix_records_values", "records", ["values"], postgresql_using="gin",
                    postgresql_ops={"values": "jsonb_path_ops"})
    op.create_index("ix_records_email", "records", ["workspace_id", "email_norm"])
    op.create_index("ix_records_phone", "records", ["workspace_id", "phone_e164"])
    op.create_index("ix_records_trash", "records", ["workspace_id", "object_id", sa.text("deleted_at DESC")],
                    postgresql_where=sa.text("deleted_at IS NOT NULL"))

    op.create_table(
        "tags", pk(), workspace(), col("name", sa.String(100)), col("color", sa.String(20), nullable=True),
        col("group_name", sa.String(100), nullable=True), col("description", sa.String(500), nullable=True),
        created(), sa.UniqueConstraint("id", "workspace_id"))
    op.create_index("ix_tags_name", "tags", ["workspace_id", sa.text("lower(name)")], unique=True)
    op.create_table(
        "record_tags", col("record_id", sa.Uuid(), primary_key=True), col("tag_id", sa.Uuid(), primary_key=True),
        workspace(), created(), within("record_id", "records"), within("tag_id", "tags"))
    op.create_index("ix_record_tags_tag", "record_tags", ["tag_id", "record_id"])

    op.create_table(
        "association_types", pk(), workspace(), col("from_object_id", sa.Uuid()), col("to_object_id", sa.Uuid()),
        col("label", sa.String(100)), col("inverse_label", sa.String(100)),
        col("cardinality", sa.String(12), server_default="many_to_many"),
        col("is_system", sa.Boolean(), server_default=FALSE), created(),
        sa.UniqueConstraint("id", "workspace_id"), sa.UniqueConstraint("from_object_id", "to_object_id", "label"),
        within("from_object_id", "objects"), within("to_object_id", "objects"),
        sa.CheckConstraint(in_list("cardinality", CARDINALITIES), name="ck_association_types_cardinality"))
    op.create_table(
        "associations", pk(), workspace(), col("type_id", sa.Uuid()), col("from_record_id", sa.Uuid()),
        col("to_record_id", sa.Uuid()), created(),
        sa.UniqueConstraint("type_id", "from_record_id", "to_record_id"),
        within("type_id", "association_types"), within("from_record_id", "records"), within("to_record_id", "records"),
        sa.CheckConstraint("from_record_id <> to_record_id", name="ck_associations_distinct"))
    op.create_index("ix_associations_from", "associations", ["from_record_id"])
    op.create_index("ix_associations_to", "associations", ["to_record_id"])

    op.create_table(
        "saved_views", pk(), workspace(), col("object_id", sa.Uuid()), col("name", sa.String(200)),
        col("filter", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("columns", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        col("sort", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        col("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        col("shared", sa.Boolean(), server_default=FALSE), created(), created("updated_at"),
        within("object_id", "objects"))
    op.create_index("ix_saved_views_object", "saved_views", ["workspace_id", "object_id"])

    # No foreign key to events: the log gets partitioned (ADR 0003).
    op.create_table(
        "event_records", col("event_id", sa.BigInteger(), primary_key=True),
        col("record_id", sa.Uuid(), primary_key=True), workspace(), within("record_id", "records"))
    op.create_index("ix_event_records_record", "event_records", ["record_id", sa.text("event_id DESC")])


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"
# A private view is visible to its owner only; the policy hides it from everyone else in the workspace.
VIEWS = ("FOR ALL USING (workspace_id = app_workspace_id() AND (shared OR owner_id = app_user_id())) "
         "WITH CHECK (workspace_id = app_workspace_id() AND (shared OR owner_id = app_user_id()))")

# table: (privileges for gohigh_app, policy). Nothing here is hard deleted by request handlers except tags, tag links,
# links between records, views and association types; objects, fields and records are archived or trashed instead.
RLS = {
    "objects": ("SELECT, INSERT, UPDATE", WORKSPACE),
    "fields": ("SELECT, INSERT, UPDATE", WORKSPACE),
    "records": ("SELECT, INSERT, UPDATE", WORKSPACE),
    "tags": ("SELECT, INSERT, UPDATE, DELETE", WORKSPACE),
    "record_tags": ("SELECT, INSERT, DELETE", WORKSPACE),
    "association_types": ("SELECT, INSERT, DELETE", WORKSPACE),
    "associations": ("SELECT, INSERT, DELETE", WORKSPACE),
    "saved_views": ("SELECT, INSERT, UPDATE, DELETE", VIEWS),
    "event_records": ("SELECT, INSERT", WORKSPACE),
}


def upgrade() -> None:
    from app.records import seed

    tables()
    # Before row level security is switched on, so the owner role can write: every existing workspace gets the
    # system objects a new one gets at sign up.
    connection = op.get_bind()
    for workspace_id in connection.execute(sa.text("SELECT id FROM workspaces")).scalars().all():
        seed.add(connection, workspace_id)
    for table, (privileges, policy) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {policy}")


def downgrade() -> None:
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")
