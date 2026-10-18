"""roles, object rules, teams; org and workspace members get a role_id instead of the fixed role strings

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
EMPTY_ARRAY = sa.text("'{}'")
SCOPES = ("all", "team", "own", "own_and_unassigned", "none")  # frozen: the scopes this migration knew


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def created() -> sa.Column:
    return col("created_at", TS, server_default=sa.func.now())


def pk() -> sa.Column:
    return col("id", sa.Uuid(), **UUID_PK)


def tables() -> None:
    op.create_table(
        "roles", pk(), col("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE")),
        col("key", sa.String(40)), col("name", sa.String(100)), col("description", sa.String(500), server_default=""),
        col("is_system", sa.Boolean(), server_default=sa.text("false")),
        col("capabilities", postgresql.ARRAY(sa.Text()), server_default=EMPTY_ARRAY), created(),
        sa.UniqueConstraint("org_id", "key"), sa.UniqueConstraint("id", "org_id"))
    op.create_table(
        "role_object_rules", pk(), col("org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE")),
        col("role_id", sa.Uuid()), col("object_key", sa.String(40)), col("scope", sa.String(20)),
        col("hidden_fields", postgresql.ARRAY(sa.String(63)), server_default=EMPTY_ARRAY),
        col("readonly_fields", postgresql.ARRAY(sa.String(63)), server_default=EMPTY_ARRAY),
        sa.UniqueConstraint("role_id", "object_key"),
        sa.ForeignKeyConstraint(["role_id", "org_id"], ["roles.id", "roles.org_id"], ondelete="CASCADE"),
        sa.CheckConstraint("scope IN (" + ", ".join(f"'{s}'" for s in SCOPES) + ")",
                           name="ck_role_object_rules_scope"))
    op.create_table(
        "teams", pk(), col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE")),
        col("name", sa.String(100)), col("parent_team_id", sa.Uuid(), nullable=True), created(),
        sa.UniqueConstraint("id", "workspace_id"),
        sa.ForeignKeyConstraint(["parent_team_id", "workspace_id"], ["teams.id", "teams.workspace_id"]))
    op.create_index("ix_teams_name", "teams", ["workspace_id", sa.text("lower(name)")], unique=True)
    op.create_table(
        "team_members", col("team_id", sa.Uuid(), primary_key=True),
        col("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE")), created(),
        sa.ForeignKeyConstraint(["team_id", "workspace_id"], ["teams.id", "teams.workspace_id"], ondelete="CASCADE"))
    op.create_index("ix_team_members_user", "team_members", ["user_id"])


MY_WORKSPACES = "SELECT workspace_id FROM workspace_members WHERE user_id = app_user_id()"
ADMIN_ORGS = {  # the organizations the user owns or administers, as migration 0002 wrote it and as it reads now
    "strings": "SELECT org_id FROM org_members WHERE user_id = app_user_id() AND role IN ('owner', 'admin')",
    "roles": "SELECT om.org_id FROM org_members om JOIN roles r ON r.id = om.role_id "
             "WHERE om.user_id = app_user_id() AND r.key IN ('owner', 'admin')"}


def workspace_policies(kind: str) -> None:
    """The two workspace policies that look at an org member's role. They block dropping the column, so the caller
    drops them first and they come back here reading the other form."""
    op.execute(f"CREATE POLICY access_read ON workspaces FOR SELECT USING (id = app_workspace_id() OR "
               f"id IN ({MY_WORKSPACES}) OR org_id IN ({ADMIN_ORGS[kind]}))")
    op.execute(f"CREATE POLICY admin_create ON workspaces FOR INSERT WITH CHECK (org_id IN ({ADMIN_ORGS[kind]}))")


def members_to_roles() -> None:
    """The fixed role strings become references to the system roles of the same name (owner, admin, member)."""
    for table in ("org_members", "workspace_members"):
        op.add_column(table, sa.Column("role_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE org_members m SET role_id = r.id FROM roles r "
               "WHERE r.org_id = m.org_id AND r.key = m.role AND r.is_system")
    op.execute("UPDATE workspace_members m SET role_id = r.id FROM roles r JOIN workspaces w ON w.org_id = r.org_id "
               "WHERE w.id = m.workspace_id AND r.key = m.role AND r.is_system")
    op.execute("DROP POLICY access_read ON workspaces")
    op.execute("DROP POLICY admin_create ON workspaces")
    for table in ("org_members", "workspace_members"):
        op.alter_column(table, "role_id", nullable=False)
        op.drop_constraint(f"ck_{table}_role", table)
        op.drop_column(table, "role")
    op.create_foreign_key(None, "org_members", "roles", ["role_id", "org_id"], ["id", "org_id"])
    op.create_foreign_key(None, "workspace_members", "roles", ["role_id"], ["id"])
    workspace_policies("roles")


def members_to_strings() -> None:
    """Back to the fixed strings: the custom roles of a workspace member become `member`, so nothing is escalated."""
    for table in ("org_members", "workspace_members"):
        op.add_column(table, sa.Column("role", sa.String(10), nullable=True))
    op.execute("UPDATE org_members m SET role = CASE WHEN r.key IN ('owner', 'admin') AND r.is_system THEN r.key "
               "ELSE 'member' END FROM roles r WHERE r.id = m.role_id")
    op.execute("UPDATE workspace_members m SET role = CASE WHEN r.key IN ('owner', 'admin') AND r.is_system "
               "THEN 'admin' ELSE 'member' END FROM roles r WHERE r.id = m.role_id")
    op.execute("DROP POLICY access_read ON workspaces")
    op.execute("DROP POLICY admin_create ON workspaces")
    for table, allowed in (("org_members", "'owner', 'admin', 'member'"), ("workspace_members", "'admin', 'member'")):
        op.alter_column(table, "role", nullable=False)
        op.create_check_constraint(f"ck_{table}_role", table, f"role IN ({allowed})")
        op.drop_column(table, "role_id")  # takes its foreign key with it
    workspace_policies("strings")


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"
MY_ORGS = "SELECT org_id FROM org_members WHERE user_id = app_user_id()"
SEES_ROLES = f"org_id = app_org_id() OR org_id IN ({MY_ORGS})"
# Owner and Admin define what an organization owner or admin is; no request may edit them or their rules.
LOCKED = "(is_system AND key IN ('owner', 'admin'))"
LOCKED_RULES = f"role_id IN (SELECT id FROM roles WHERE {LOCKED})"
# A workspace member must be a member of the workspace's organization, and hold a role of that organization.
IN_ORG = ("EXISTS (SELECT 1 FROM workspaces w JOIN org_members om ON om.org_id = w.org_id "
          "WHERE w.id = workspace_members.workspace_id AND om.user_id = workspace_members.user_id)")
ORGS_ROLE = "workspace_members.role_id IN (SELECT id FROM roles WHERE org_id = app_org_id())"
# People of the current workspace: its members and the owners and admins of its organization.
PEERS = ("id IN (SELECT user_id FROM workspace_members WHERE workspace_id = app_workspace_id()) OR id IN ("
         "SELECT om.user_id FROM org_members om JOIN roles r ON r.id = om.role_id "
         "WHERE om.org_id = app_org_id() AND r.is_system AND r.key IN ('owner', 'admin'))")

# table: (privileges for gohigh_app, [(policy name, policy body)]); the system policy is for sign up, which seeds roles.
RLS = {
    "roles": ("SELECT, INSERT, DELETE", [
        ("system", "FOR ALL USING (app_system()) WITH CHECK (app_system())"),
        ("member_read", f"FOR SELECT USING ({SEES_ROLES})"),
        ("org_insert", "FOR INSERT WITH CHECK (org_id = app_org_id() AND NOT is_system)"),
        ("org_update", f"FOR UPDATE USING (org_id = app_org_id() AND NOT {LOCKED}) "
                       f"WITH CHECK (org_id = app_org_id() AND NOT {LOCKED})"),
        ("org_delete", "FOR DELETE USING (org_id = app_org_id() AND NOT is_system)")]),
    "role_object_rules": ("SELECT, INSERT, UPDATE, DELETE", [
        ("system", "FOR ALL USING (app_system()) WITH CHECK (app_system())"),
        ("member_read", f"FOR SELECT USING ({SEES_ROLES})"),
        ("org_write", f"FOR ALL USING (org_id = app_org_id() AND NOT ({LOCKED_RULES})) "
                      f"WITH CHECK (org_id = app_org_id() AND NOT ({LOCKED_RULES}))")]),
    "teams": ("SELECT, INSERT, UPDATE, DELETE", [("workspace", WORKSPACE)]),
    "team_members": ("SELECT, INSERT, DELETE", [("workspace", WORKSPACE)]),
}


def policies() -> None:
    for table, (privileges, policy_list) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        for name, body in policy_list:
            op.execute(f"CREATE POLICY {name} ON {table} {body}")
    op.execute("GRANT UPDATE (name, description, capabilities) ON roles TO gohigh_app")  # never key or is_system
    op.execute("GRANT INSERT, UPDATE (role_id) ON workspace_members TO gohigh_app")
    op.execute(f"CREATE POLICY assign ON workspace_members FOR INSERT WITH CHECK "
               f"(workspace_id = app_workspace_id() AND {IN_ORG} AND {ORGS_ROLE})")
    op.execute(f"CREATE POLICY reassign ON workspace_members FOR UPDATE USING (workspace_id = app_workspace_id()) "
               f"WITH CHECK (workspace_id = app_workspace_id() AND {ORGS_ROLE})")
    op.execute(f"CREATE POLICY peer_read ON users FOR SELECT USING ({PEERS})")
    # The event log is append only for request handlers: they have INSERT and SELECT on it and nothing else.
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON events FROM gohigh_app")


def upgrade() -> None:
    from app import roles_seed

    # The members tables have row level security forced on them, which applies to their owner too; the system
    # setting (what sign up uses) lets this migration rewrite them.
    op.execute("SELECT set_config('app.system', 'on', true)")
    tables()
    connection = op.get_bind()
    for org_id in connection.execute(sa.text("SELECT id FROM organizations")).scalars().all():
        roles_seed.add(connection, org_id)  # before row level security is on, so the owner role can write
    members_to_roles()
    policies()
    op.execute("SELECT set_config('app.system', '', true)")


def downgrade() -> None:
    op.execute("SELECT set_config('app.system', 'on', true)")
    op.execute("DROP POLICY peer_read ON users")
    op.execute("DROP POLICY reassign ON workspace_members")
    op.execute("DROP POLICY assign ON workspace_members")
    op.execute("REVOKE INSERT, UPDATE ON workspace_members FROM gohigh_app")
    members_to_strings()
    for table in ("team_members", "teams", "role_object_rules", "roles"):
        op.execute(f"DROP TABLE {table} CASCADE")
    op.execute("SELECT set_config('app.system', '', true)")
