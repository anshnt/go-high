"""forms, surveys and quizzes: forms, immutable versions, submissions, view counters, rate counters

Revision ID: 0010
Revises: 0004
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
EMPTY_OBJECT = sa.text("'{}'::jsonb")
# frozen: the kinds and statuses this migration knew
KINDS = ("form", "survey", "quiz")
STATUSES = ("draft", "published", "closed")
SUBMISSION_STATUSES = ("partial", "complete")


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def created(name: str = "created_at") -> sa.Column:
    return col(name, TS, server_default=sa.func.now())


def workspace() -> sa.Column:
    return col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"))


def pk() -> sa.Column:
    return col("id", sa.Uuid(), **UUID_PK)


def in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def own_form() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["form_id", "workspace_id"], ["forms.id", "forms.workspace_id"], ondelete="CASCADE")


def tables() -> None:
    op.create_table(
        "forms", pk(), workspace(), col("public_key", sa.String(32)), col("kind", sa.String(10)),
        col("name", sa.String(200)), col("slug", sa.String(80)), col("status", sa.String(10), server_default="draft"),
        col("published_version_id", sa.Uuid(), nullable=True),
        col("settings", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        created(), created("updated_at"), col("deleted_at", TS, nullable=True),
        sa.UniqueConstraint("public_key"), sa.UniqueConstraint("id", "workspace_id"),
        sa.UniqueConstraint("workspace_id", "slug"),
        sa.CheckConstraint(in_list("kind", KINDS), name="ck_forms_kind"),
        sa.CheckConstraint(in_list("status", STATUSES), name="ck_forms_status"))
    op.create_table(
        "form_versions", pk(), workspace(), col("form_id", sa.Uuid()), col("number", sa.Integer()),
        col("definition", postgresql.JSONB()),
        col("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True), created(),
        sa.UniqueConstraint("id", "workspace_id"), sa.UniqueConstraint("id", "form_id"),
        sa.UniqueConstraint("form_id", "number"), own_form())
    op.create_foreign_key("fk_forms_published_version", "forms", "form_versions", ["published_version_id", "id"],
                          ["id", "form_id"])
    op.create_table(
        "form_submissions", pk(), workspace(), col("form_id", sa.Uuid()), col("version_id", sa.Uuid()),
        col("status", sa.String(10), server_default="partial"),
        col("answers", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("score", sa.Integer(), nullable=True), col("max_score", sa.Integer(), nullable=True),
        col("contact_id", sa.Uuid(), nullable=True), col("contact_error", sa.String(300), nullable=True),
        col("consent", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("source_url", sa.String(2000), nullable=True), col("referrer", sa.String(2000), nullable=True),
        col("utm", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("ip_hash", sa.String(64), nullable=True), col("user_agent", sa.String(300), nullable=True),
        col("steps_seen", postgresql.ARRAY(sa.String(40)), server_default="{}"),
        col("last_field", sa.String(40), nullable=True), col("resume_token_hash", sa.String(64), nullable=True),
        created("started_at"), created(), created("updated_at"), col("completed_at", TS, nullable=True),
        sa.UniqueConstraint("resume_token_hash"), own_form(),
        sa.ForeignKeyConstraint(["version_id", "form_id"], ["form_versions.id", "form_versions.form_id"],
                                ondelete="CASCADE"),
        sa.CheckConstraint(in_list("status", SUBMISSION_STATUSES), name="ck_form_submissions_status"))
    op.create_index("ix_form_submissions_form", "form_submissions",
                    ["form_id", sa.text("created_at DESC"), sa.text("id DESC")])
    op.create_index("ix_form_submissions_contact", "form_submissions", ["contact_id"])
    op.create_table(
        "form_views", col("form_id", sa.Uuid(), primary_key=True), col("day", sa.Date(), primary_key=True),
        workspace(), col("count", sa.Integer(), server_default="0"), own_form())
    op.create_table(
        "form_rate", col("form_id", sa.Uuid(), primary_key=True), col("ip_hash", sa.String(64), primary_key=True),
        col("kind", sa.String(10), primary_key=True), col("bucket", sa.BigInteger(), primary_key=True), workspace(),
        col("count", sa.Integer(), server_default="0"), own_form())


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"

# table: (privileges for gohigh_app, extra policies). Versions are never changed and nothing is hard deleted by a
# request: a form goes to the trash (deleted_at). The public endpoints find a form by its public key in the system
# scope, which may only read `forms`; everything after that runs scoped to the form's workspace.
RLS = {
    "forms": ("SELECT, INSERT, UPDATE", ["CREATE POLICY system ON forms FOR SELECT USING (app_system())"]),
    "form_versions": ("SELECT, INSERT", []),
    "form_submissions": ("SELECT, INSERT, UPDATE", []),
    "form_views": ("SELECT, INSERT, UPDATE", []),
    "form_rate": ("SELECT, INSERT, UPDATE, DELETE", []),  # DELETE: old minutes are removed as new ones are counted
}


def upgrade() -> None:
    tables()
    for table, (privileges, extra) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {WORKSPACE}")
        for policy in extra:
            op.execute(policy)


def downgrade() -> None:
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")
