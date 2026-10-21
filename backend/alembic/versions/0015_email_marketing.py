"""email marketing: settings, sending domains, templates, topics and preferences, campaigns, their links, one send per
recipient, the engagement log and the suppression list; the marketing capabilities

Revision ID: 0015
Revises: 0012
Create Date: 2026-10-20
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015"
down_revision = "0012"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
EMPTY_OBJECT = sa.text("'{}'::jsonb")
JSONB = postgresql.JSONB()
# frozen: the values this migration knew
DOMAIN_STATUSES = ("pending", "verified", "failing")
DKIM_MODES = ("managed", "provider")
CAMPAIGN_STATUSES = ("draft", "scheduled", "sending", "testing", "paused", "sent", "cancelled", "failed")
SEND_STATUSES = ("queued", "held", "sending", "sent", "delivered", "bounced", "complained", "failed", "skipped",
                 "cancelled", "uncertain")
PHASES = ("all", "test", "main")
EVENT_TYPES = ("open", "click", "delivered", "bounce", "complaint", "unsubscribe")
SUPPRESSION_REASONS = ("hard_bounce", "complaint", "unsubscribe", "manual")
# frozen: what each system role of an existing organization gains (a new organization gets them from
# app/roles_seed.py). Custom roles get nothing: an admin adds them to the roles that should have them.
CAPABILITIES = ("marketing.read", "marketing.write", "marketing.send", "marketing.manage")
GRANTS = {"owner": CAPABILITIES, "admin": CAPABILITIES, "manager": CAPABILITIES,
          "member": ("marketing.read", "marketing.write"), "viewer": ("marketing.read",)}


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def opt(name: str, type_, *args, **kw) -> sa.Column:
    return col(name, type_, *args, nullable=True, **kw)


def created(name: str = "created_at") -> sa.Column:
    return col(name, TS, server_default=sa.func.now())


def workspace(**kw) -> sa.Column:
    return col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), **kw)


def pk() -> sa.Column:
    return col("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def user(name: str) -> sa.Column:
    return opt(name, sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"))


def one_of(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")", name=name)


def within(column: str, table: str, cascade: bool = True) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column, "workspace_id"], [f"{table}.id", f"{table}.workspace_id"],
                                   **({"ondelete": "CASCADE"} if cascade else {}))


def newest(table: str, column: str = "updated_at") -> None:
    op.create_index(f"ix_{table}_list", table, ["workspace_id", sa.text(f"{column} DESC"), sa.text("id DESC")])


def tables() -> None:
    op.create_table(
        "email_settings", workspace(primary_key=True), col("company_name", sa.String(200), server_default=""),
        col("postal_address", sa.String(500), server_default=""),
        col("track_opens", sa.Boolean(), server_default=sa.text("true")),
        col("track_clicks", sa.Boolean(), server_default=sa.text("true")), created("updated_at"))
    op.create_table(
        "email_domains", pk(), workspace(), col("domain", sa.String(253)),
        col("dkim_mode", sa.String(10), server_default="managed"), col("dkim_selector", sa.String(63)),
        opt("dkim_public_key", sa.Text()), opt("dkim_secret_ref", sa.Uuid()), opt("spf_include", sa.String(253)),
        col("status", sa.String(10), server_default="pending"), col("checks", JSONB, server_default=EMPTY_OBJECT),
        opt("checked_at", TS), opt("verified_at", TS), opt("warmup_started_at", TS), opt("hourly_limit", sa.Integer()),
        user("created_by"), created(), created("updated_at"),
        sa.UniqueConstraint("id", "workspace_id"), sa.UniqueConstraint("workspace_id", "domain"),
        within("dkim_secret_ref", "secrets", cascade=False),
        one_of("status", DOMAIN_STATUSES, "ck_email_domains_status"),
        one_of("dkim_mode", DKIM_MODES, "ck_email_domains_dkim_mode"))
    op.create_table(
        "email_templates", pk(), workspace(), col("name", sa.String(200)),
        col("subject", sa.String(500), server_default=""), col("preheader", sa.String(300), server_default=""),
        col("document", JSONB, server_default=EMPTY_OBJECT), opt("archived_at", TS), user("created_by"), created(),
        created("updated_at"), sa.UniqueConstraint("id", "workspace_id"))
    newest("email_templates")
    op.create_table(
        "email_topics", pk(), workspace(), col("name", sa.String(100)),
        col("description", sa.String(300), server_default=""), opt("archived_at", TS), created(),
        sa.UniqueConstraint("id", "workspace_id"), sa.UniqueConstraint("workspace_id", "name"))
    op.create_table(
        "email_preferences", col("contact_id", sa.Uuid(), primary_key=True),
        col("topic_id", sa.Uuid(), primary_key=True), workspace(), col("subscribed", sa.Boolean()),
        col("source", sa.String(20)), created("changed_at"), within("contact_id", "records"),
        within("topic_id", "email_topics"))
    op.create_table(
        "email_campaigns", pk(), workspace(), col("name", sa.String(200)),
        col("status", sa.String(10), server_default="draft"), opt("paused_from", sa.String(10)),
        opt("channel_id", sa.Uuid()), opt("domain_id", sa.Uuid()), opt("topic_id", sa.Uuid()),
        opt("template_id", sa.Uuid()), col("from_name", sa.String(200), server_default=""),
        col("from_email", sa.String(320), server_default=""), opt("reply_to", sa.String(320)),
        col("subject", sa.String(500), server_default=""), col("preheader", sa.String(300), server_default=""),
        col("document", JSONB, server_default=EMPTY_OBJECT), col("audience", JSONB, server_default=EMPTY_OBJECT),
        col("ab", JSONB, server_default=EMPTY_OBJECT), opt("winner", sa.String(1)), opt("scheduled_at", TS),
        col("timezone", sa.String(64), server_default="UTC"), opt("started_at", TS), opt("test_ends_at", TS),
        opt("finished_at", TS), opt("audience_count", sa.Integer()), opt("error", sa.String(500)),
        user("created_by"), user("scheduled_by"), created(), created("updated_at"),
        sa.UniqueConstraint("id", "workspace_id"), within("channel_id", "channels", cascade=False),
        within("domain_id", "email_domains", cascade=False), within("topic_id", "email_topics", cascade=False),
        one_of("status", CAMPAIGN_STATUSES, "ck_email_campaigns_status"))
    newest("email_campaigns")
    op.create_table(
        "email_links", col("campaign_id", sa.Uuid(), primary_key=True), col("idx", sa.Integer(), primary_key=True),
        workspace(), col("url", sa.String(2000)), within("campaign_id", "email_campaigns"))
    op.create_table(
        "email_sends", pk(), workspace(), col("campaign_id", sa.Uuid()), col("contact_id", sa.Uuid()),
        opt("domain_id", sa.Uuid()), col("email", sa.String(320)), opt("variant", sa.String(1)),
        col("phase", sa.String(4), server_default="all"), col("status", sa.String(10), server_default="queued"),
        opt("reason", sa.String(300)), opt("provider_message_id", sa.String(500)),
        col("attempts", sa.SmallInteger(), server_default="0"), opt("next_attempt_at", TS), opt("claimed_at", TS),
        opt("sent_at", TS), opt("delivered_at", TS), opt("opened_at", TS), opt("clicked_at", TS),
        col("opens", sa.Integer(), server_default="0"), col("clicks", sa.Integer(), server_default="0"),
        opt("unsubscribed_at", TS), created(),
        sa.UniqueConstraint("id", "workspace_id"), sa.UniqueConstraint("campaign_id", "contact_id"),
        sa.UniqueConstraint("campaign_id", "email"), within("campaign_id", "email_campaigns"),
        within("contact_id", "records"), within("domain_id", "email_domains", cascade=False),
        one_of("status", SEND_STATUSES, "ck_email_sends_status"), one_of("phase", PHASES, "ck_email_sends_phase"))
    op.create_index("ix_email_sends_campaign", "email_sends", ["campaign_id", "status"])
    op.create_index("ix_email_sends_throttle", "email_sends", ["domain_id", "claimed_at"],
                    postgresql_where=sa.text("claimed_at IS NOT NULL"))
    op.create_index("ix_email_sends_provider", "email_sends", ["provider_message_id"],
                    postgresql_where=sa.text("provider_message_id IS NOT NULL"))
    op.create_index("ix_email_sends_contact", "email_sends", ["contact_id"])
    op.create_table(
        "email_events", col("id", sa.BigInteger(), primary_key=True), workspace(), col("campaign_id", sa.Uuid()),
        col("send_id", sa.Uuid()), col("type", sa.String(12)), opt("link_idx", sa.Integer()),
        col("machine", sa.Boolean(), server_default=sa.text("false")), opt("detail", sa.String(300)),
        created("occurred_at"), within("campaign_id", "email_campaigns"), within("send_id", "email_sends"),
        one_of("type", EVENT_TYPES, "ck_email_events_type"))
    op.create_index("ix_email_events_campaign", "email_events", ["campaign_id", "type"])
    op.create_index("ix_email_events_send", "email_events", ["send_id", "occurred_at"])
    op.create_table(
        "email_suppressions", pk(), workspace(), col("email", sa.String(320)), col("reason", sa.String(12)),
        opt("detail", sa.String(300)), opt("campaign_id", sa.Uuid()), user("created_by"), created(),
        sa.UniqueConstraint("workspace_id", "email"),
        one_of("reason", SUPPRESSION_REASONS, "ck_email_suppressions_reason"))
    newest("email_suppressions", "created_at")


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"
# a public link (unsubscribe, preferences, an open or a click) knows only the send it was made for: once its signature
# checks out, the send is read in the system scope, and everything after runs in the send's workspace
SYSTEM = "FOR SELECT USING (app_system())"

# table: privileges for gohigh_app, and extra policies. Sends, links and the log are written by the worker; a request
# only cancels sends and the public links count opens and clicks and record unsubscribes. Templates are archived and
# campaigns are deleted only while they are drafts with no sends.
RLS = {
    "email_settings": ("SELECT, INSERT, UPDATE", []),
    "email_domains": ("SELECT, INSERT, UPDATE, DELETE", []),
    "email_templates": ("SELECT, INSERT, UPDATE", []),
    "email_topics": ("SELECT, INSERT, UPDATE", []),
    "email_preferences": ("SELECT, INSERT, UPDATE", []),
    "email_campaigns": ("SELECT, INSERT, UPDATE, DELETE", []),
    "email_links": ("SELECT", []),
    "email_sends": ("SELECT, INSERT, UPDATE", [("system", SYSTEM)]),
    "email_events": ("SELECT, INSERT", []),
    "email_suppressions": ("SELECT, INSERT, DELETE", []),
}


def upgrade() -> None:
    tables()
    for table, (privileges, policies) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {WORKSPACE}")
        for name, body in policies:
            op.execute(f"CREATE POLICY {name} ON {table} {body}")
    op.execute("GRANT USAGE ON SEQUENCE email_events_id_seq TO gohigh_app")
    # roles have row level security forced on them, which applies to their owner too: the system setting (what sign up
    # uses) lets this migration change them
    op.execute("SELECT set_config('app.system', 'on', true)")
    connection = op.get_bind()
    for key, capabilities in GRANTS.items():
        connection.execute(sa.text("UPDATE roles SET capabilities = capabilities || array(SELECT c FROM "
                                   "unnest(CAST(:caps AS text[])) c WHERE c <> ALL(capabilities)) "
                                   "WHERE is_system AND key = :key"), {"caps": list(capabilities), "key": key})


def downgrade() -> None:
    op.execute("SELECT set_config('app.system', 'on', true)")
    op.get_bind().execute(sa.text("UPDATE roles SET capabilities = array(SELECT c FROM unnest(capabilities) c "
                                  "WHERE c <> ALL(CAST(:caps AS text[])))"), {"caps": list(CAPABILITIES)})
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")
