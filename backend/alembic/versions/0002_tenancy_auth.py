"""tenancy and auth tables, gohigh_app role, row level security

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))


def fk(target: str) -> sa.ForeignKey:
    return sa.ForeignKey(f"{target}.id", ondelete="CASCADE")


def created() -> sa.Column:
    return sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False)


def tables() -> None:
    def col(name: str, type_, *args, **kw) -> sa.Column:
        return sa.Column(name, type_, *args, **({"nullable": False} | kw))

    def pk() -> sa.Column:
        return col("id", sa.Uuid(), **UUID_PK)

    def ref(name: str, target: str, **kw) -> sa.Column:
        return col(name, sa.Uuid(), fk(target), **kw)

    str_ = sa.String
    op.create_table("organizations", pk(), col("name", str_(200)), created())
    op.create_table("brands", pk(), ref("org_id", "organizations"), col("name", str_(200)), created(),
                    sa.UniqueConstraint("id", "org_id"))
    op.create_index("ix_brands_org_id", "brands", ["org_id"])
    op.create_table("workspaces", pk(), ref("org_id", "organizations"), col("brand_id", sa.Uuid()),
                    col("name", str_(200)), created(),
                    sa.ForeignKeyConstraint(["brand_id", "org_id"], ["brands.id", "brands.org_id"], ondelete="CASCADE"))
    op.create_index("ix_workspaces_org_id", "workspaces", ["org_id"])
    op.create_index("ix_workspaces_brand_id", "workspaces", ["brand_id"])
    op.create_table("users", pk(), col("email", str_(254)), col("name", str_(200)),
                    col("password_hash", str_(300), nullable=True), created(), sa.UniqueConstraint("email"),
                    sa.CheckConstraint("email = lower(email)", name="ck_users_email_lower"))
    op.create_table("org_members", ref("user_id", "users", primary_key=True),
                    ref("org_id", "organizations", primary_key=True), col("role", str_(10)), created(),
                    sa.CheckConstraint("role IN ('owner', 'admin', 'member')", name="ck_org_members_role"))
    op.create_table("workspace_members", ref("user_id", "users", primary_key=True),
                    ref("workspace_id", "workspaces", primary_key=True), col("role", str_(10)), created(),
                    sa.CheckConstraint("role IN ('admin', 'member')", name="ck_workspace_members_role"))
    op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
    op.create_table("auth_sessions", pk(), col("token_hash", str_(64)), ref("user_id", "users"), created(),
                    col("last_seen_at", TS, server_default=sa.func.now()), col("expires_at", TS),
                    col("ip", str_(64), nullable=True), col("user_agent", str_(300), nullable=True),
                    col("revoked_at", TS, nullable=True), sa.UniqueConstraint("token_hash"))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table("magic_links", pk(), col("token_hash", str_(64)), col("email", str_(254)),
                    ref("user_id", "users", nullable=True), created(), col("expires_at", TS),
                    col("used_at", TS, nullable=True), sa.UniqueConstraint("token_hash"))
    op.create_table("login_attempts", pk(), col("email", str_(254)), col("ip", str_(64)), created())
    op.create_index("ix_login_attempts_who", "login_attempts", ["email", "ip", "created_at"])


# The request context is app.* settings that the API sets with SET LOCAL after `SET ROLE gohigh_app`.
# Unset or empty means no context, and then no tenant row is visible.
FUNCTIONS = [
    "CREATE FUNCTION app_system() RETURNS boolean LANGUAGE sql STABLE AS "
    "$$ SELECT coalesce(current_setting('app.system', true), '') = 'on' $$",
] + [
    f"CREATE FUNCTION app_{name}() RETURNS uuid LANGUAGE sql STABLE AS "
    f"$$ SELECT nullif(current_setting('app.{name}', true), '')::uuid $$"
    for name in ("user_id", "org_id", "workspace_id")
]

MY_ORGS = "SELECT org_id FROM org_members WHERE user_id = app_user_id()"
MY_ADMIN_ORGS = MY_ORGS + " AND role IN ('owner', 'admin')"
MY_WORKSPACES = "SELECT workspace_id FROM workspace_members WHERE user_id = app_user_id()"

# table: (privileges for gohigh_app, [(policy name, policy body)]). Every table also gets a "system" policy
# for the pre-auth flows (sign in, sign up, session lookup), which run as gohigh_app with app.system = 'on'.
RLS = {
    "organizations": ("SELECT, INSERT", [("member_read", f"FOR SELECT USING (id IN ({MY_ORGS}))")]),
    "brands": ("SELECT, INSERT", [("member_read", f"FOR SELECT USING (org_id IN ({MY_ORGS}))")]),
    "workspaces": ("SELECT, INSERT", [
        ("access_read", f"FOR SELECT USING (id = app_workspace_id() OR id IN ({MY_WORKSPACES}) "
                        f"OR org_id IN ({MY_ADMIN_ORGS}))"),
        ("admin_create", f"FOR INSERT WITH CHECK (org_id IN ({MY_ADMIN_ORGS}))")]),
    "users": ("SELECT, INSERT, UPDATE", [("self_read", "FOR SELECT USING (id = app_user_id())")]),
    "org_members": ("SELECT, INSERT", [
        ("read", "FOR SELECT USING (user_id = app_user_id() OR org_id = app_org_id())")]),
    "workspace_members": ("SELECT", [
        ("read", "FOR SELECT USING (user_id = app_user_id() OR workspace_id = app_workspace_id())")]),
    "auth_sessions": ("SELECT, INSERT, UPDATE, DELETE", [
        ("own_read", "FOR SELECT USING (user_id = app_user_id())"),
        ("own_revoke", "FOR UPDATE USING (user_id = app_user_id()) WITH CHECK (user_id = app_user_id())")]),
    "magic_links": ("SELECT, INSERT, UPDATE", []),
    "login_attempts": ("SELECT, INSERT, DELETE", []),
}

# Idempotent: the role is cluster wide and may exist already (another database, another run). No login,
# no superuser, no BYPASSRLS, owns nothing: only the grants below make it useful.
ROLE = [
    """DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gohigh_app') THEN
    CREATE ROLE gohigh_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
EXCEPTION WHEN duplicate_object THEN NULL;  -- lost a race with another database's migration
END $$""",
    """DO $$ BEGIN
  IF NOT pg_has_role(current_user, 'gohigh_app', 'USAGE') THEN GRANT gohigh_app TO CURRENT_USER; END IF;
END $$""",
]

# ponytail: DROP ROLE fails while another database in the cluster still has grants for it; the role is then
# left behind on purpose (it is harmless without grants) and goes with the last database that drops it.
DROP_ROLE = """DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'gohigh_app') THEN
    DROP OWNED BY gohigh_app;
    BEGIN
      DROP ROLE gohigh_app;
    EXCEPTION WHEN dependent_objects_still_exist THEN NULL;
    END;
  END IF;
END $$"""


def upgrade() -> None:
    tables()
    for statement in ROLE:
        op.execute(statement)
    for statement in FUNCTIONS:
        op.execute(statement)
    op.execute("GRANT USAGE ON SCHEMA public TO gohigh_app")
    for table, (privileges, policies) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY system ON {table} FOR ALL USING (app_system()) WITH CHECK (app_system())")
        for name, body in policies:
            op.execute(f"CREATE POLICY {name} ON {table} {body}")


def downgrade() -> None:
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")  # policies on other tables refer to these
    op.execute("DROP FUNCTION app_workspace_id(), app_org_id(), app_user_id(), app_system()")
    op.execute(DROP_ROLE)
