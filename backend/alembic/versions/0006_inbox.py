"""inbox: channels, secrets, conversations, messages, read marks, consent, webchat counters; contact source and zone

Revision ID: 0006
Revises: 0007
Create Date: 2026-10-17
"""
import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0007"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
EMPTY_OBJECT = sa.text("'{}'::jsonb")
# frozen: the values this migration knew
KINDS = ("sms", "email", "webchat", "whatsapp", "messenger", "instagram", "voice")
PROVIDERS = ("twilio", "telnyx", "ses", "mailgun", "smtp", "gmail", "microsoft", "meta", "internal")
# frozen: the two fields every contact object gets (key, label, type, options, rules)
SOURCES = ("manual", "import", "form", "webchat", "sms", "email", "whatsapp", "api")
CONTACT_FIELDS = (
    ("source", "Source", "select", {"choices": [{"id": i, "label": label, "color": "gray"} for i, label in zip(
        SOURCES, ("Manual", "Import", "Form", "Webchat", "SMS", "Email", "WhatsApp", "API"), strict=True)]}, {}),
    ("timezone", "Time zone", "text", {}, {"timezone": True}))


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
    op.create_table("secrets", pk(), workspace(), col("ciphertext", sa.LargeBinary()), created(), created("updated_at"),
                    sa.UniqueConstraint("id", "workspace_id"))
    op.create_table(
        "channels", pk(), workspace(), col("kind", sa.String(20)), col("provider", sa.String(20)),
        col("name", sa.String(200)), col("address", sa.String(320), server_default=""),
        col("config", postgresql.JSONB(), server_default=EMPTY_OBJECT), col("secret_ref", sa.Uuid(), nullable=True),
        col("status", sa.String(10), server_default="pending"), col("status_detail", sa.String(300), nullable=True),
        col("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        created(), created("updated_at"),
        sa.UniqueConstraint("id", "workspace_id"),
        sa.ForeignKeyConstraint(["secret_ref", "workspace_id"], ["secrets.id", "secrets.workspace_id"]),
        sa.CheckConstraint(in_list("kind", KINDS), name="ck_channels_kind"),
        sa.CheckConstraint(in_list("provider", PROVIDERS), name="ck_channels_provider"),
        sa.CheckConstraint(in_list("status", ("active", "pending", "failing", "disabled")), name="ck_channels_status"))
    op.create_index("uq_channels_widget_key", "channels", ["address"], unique=True,
                    postgresql_where=sa.text("kind = 'webchat'"))
    op.create_index("ix_channels_workspace", "channels", ["workspace_id"])

    op.create_table(
        "conversations", pk(), workspace(), col("contact_id", sa.Uuid()),
        col("status", sa.String(10), server_default="open"),
        col("assignee_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        col("team_id", sa.Uuid(), nullable=True), col("snooze_until", TS, nullable=True),
        created("last_message_at"), col("last_inbound_at", TS, nullable=True), col("sla_due_at", TS, nullable=True),
        col("last_seq", sa.BigInteger(), server_default="0"),
        col("last_inbound_seq", sa.BigInteger(), server_default="0"),
        col("last_channel_id", sa.Uuid(), nullable=True), col("last_preview", sa.String(200), server_default=""),
        col("last_direction", sa.String(3), nullable=True), col("visitor_id", sa.Uuid(), nullable=True), created(),
        sa.UniqueConstraint("id", "workspace_id"), within("contact_id", "records"),
        sa.ForeignKeyConstraint(["last_channel_id", "workspace_id"], ["channels.id", "channels.workspace_id"]),
        sa.CheckConstraint(in_list("status", ("open", "snoozed", "closed")), name="ck_conversations_status"))
    op.create_index("uq_conversations_live", "conversations", ["workspace_id", "contact_id"], unique=True,
                    postgresql_where=sa.text("status <> 'closed'"))
    op.create_index("ix_conversations_list", "conversations",
                    ["workspace_id", "status", sa.text("last_message_at DESC"), sa.text("id DESC")])
    op.create_index("ix_conversations_assignee", "conversations", ["workspace_id", "assignee_id"],
                    postgresql_where=sa.text("assignee_id IS NOT NULL"))
    op.create_index("ix_conversations_visitor", "conversations", ["visitor_id"],
                    postgresql_where=sa.text("visitor_id IS NOT NULL"))
    op.create_index("ix_conversations_contact", "conversations", ["contact_id"])

    op.create_table(
        "conversation_reads", col("conversation_id", sa.Uuid(), primary_key=True),
        col("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True), workspace(),
        col("last_read_seq", sa.BigInteger(), server_default="0"), created("updated_at"),
        within("conversation_id", "conversations"))

    op.create_table(
        "messages", pk(), workspace(), col("conversation_id", sa.Uuid()), col("seq", sa.BigInteger()),
        col("direction", sa.String(3)), col("channel_id", sa.Uuid(), nullable=True),
        col("kind", sa.String(10), server_default="message"), col("subject", sa.String(500), nullable=True),
        col("body", sa.Text(), server_default=""), col("html", sa.Text(), nullable=True),
        col("attachments", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")), col("status", sa.String(10)),
        col("error", sa.String(500), nullable=True), col("provider_message_id", sa.String(500), nullable=True),
        col("thread_ref", sa.String(500), nullable=True),
        col("sent_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        created("occurred_at"), created(), col("attempts", sa.SmallInteger(), server_default="0"),
        col("segments", sa.SmallInteger(), nullable=True), col("cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("search", postgresql.TSVECTOR(), sa.Computed(
            "to_tsvector('simple', coalesce(subject, '') || ' ' || coalesce(body, ''))", persisted=True)),
        sa.UniqueConstraint("conversation_id", "seq"), sa.UniqueConstraint("channel_id", "provider_message_id"),
        within("conversation_id", "conversations"),
        sa.ForeignKeyConstraint(["channel_id", "workspace_id"], ["channels.id", "channels.workspace_id"]),
        sa.CheckConstraint("direction IN ('in', 'out')", name="ck_messages_direction"),
        sa.CheckConstraint(in_list("kind", ("message", "note", "call", "voicemail", "system")),
                           name="ck_messages_kind"),
        sa.CheckConstraint(in_list("status", ("queued", "sent", "delivered", "read", "failed", "received")),
                           name="ck_messages_status"))
    op.create_index("ix_messages_search", "messages", ["search"], postgresql_using="gin")
    op.create_index("ix_messages_thread", "messages", ["channel_id", "thread_ref"],
                    postgresql_where=sa.text("thread_ref IS NOT NULL"))

    op.create_table(
        "consents", col("contact_id", sa.Uuid(), primary_key=True), col("kind", sa.String(20), primary_key=True),
        workspace(), col("status", sa.String(10)), col("source", sa.String(30)),
        col("reason", sa.String(300), nullable=True), created("changed_at"), within("contact_id", "records"),
        sa.CheckConstraint(in_list("status", ("opted_in", "opted_out", "dnd")), name="ck_consents_status"))

    op.create_table(
        "chat_limits", col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                           primary_key=True),
        col("bucket", sa.String(200), primary_key=True), col("window_start", TS, primary_key=True),
        col("hits", sa.Integer(), server_default="0"))
    op.create_index("ix_chat_limits_window", "chat_limits", ["window_start"])


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"

# table: (privileges for gohigh_app, extra policies). Nothing is hard deleted by a request handler except consent
# (clearing do not disturb) and old rate counters; channels are disabled, conversations are closed.
RLS = {
    "secrets": ("INSERT, UPDATE, SELECT (id, workspace_id, created_at, updated_at)", []),
    "channels": ("SELECT, INSERT, UPDATE",
                 # a public webhook or chat page knows only the channel: it loads it in the system scope, then
                 # moves into the channel's workspace
                 [("system", "FOR SELECT USING (app_system())")]),
    "conversations": ("SELECT, INSERT, UPDATE", []),
    "conversation_reads": ("SELECT, INSERT, UPDATE", []),
    "messages": ("SELECT, INSERT, UPDATE", []),
    "consents": ("SELECT, INSERT, UPDATE, DELETE", []),
    "chat_limits": ("SELECT, INSERT, UPDATE, DELETE", []),
}


def backfill(connection) -> None:
    """The source and time zone fields for contact objects that exist already (a new workspace gets them from the
    seed). A workspace that has a field with that key keeps its own."""
    for key, label, type_, options, rules in CONTACT_FIELDS:
        connection.execute(sa.text(
            "INSERT INTO fields (id, workspace_id, object_id, key, label, type, options, rules, is_system, position) "
            "SELECT gen_random_uuid(), o.workspace_id, o.id, :key, :label, :type, CAST(:options AS jsonb), "
            "CAST(:rules AS jsonb), true, "
            "coalesce((SELECT max(f.position) FROM fields f WHERE f.object_id = o.id), -1) + 1 "
            "FROM objects o WHERE o.key = 'contact' AND o.is_system "
            "ON CONFLICT (object_id, key) DO NOTHING"),
            {"key": key, "label": label, "type": type_, "options": json.dumps(options), "rules": json.dumps(rules)})


def upgrade() -> None:
    tables()
    backfill(op.get_bind())  # the owner role writes: row level security is not switched on for the new tables yet
    for table, (privileges, policies) in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {WORKSPACE}")
        for name, body in policies:
            op.execute(f"CREATE POLICY {name} ON {table} {body}")


def downgrade() -> None:
    op.execute("DELETE FROM fields f USING objects o WHERE o.id = f.object_id AND o.key = 'contact' AND f.is_system "
               "AND f.key IN ('source', 'timezone')")
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")
