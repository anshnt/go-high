"""The inbox tables (ADR 0005): channels with their encrypted secrets, conversations, messages, per-user read marks,
per-channel consent and the webchat rate counters. Policies and grants are in migration 0006. Every reference carries
the workspace id as well, so a row can never point into another workspace."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from ..records.models import EMPTY_LIST, EMPTY_OBJECT, within, workspace

KINDS = ("sms", "email", "webchat", "whatsapp", "messenger", "instagram", "voice")
PROVIDERS = ("twilio", "telnyx", "ses", "mailgun", "smtp", "gmail", "microsoft", "meta", "internal")
CHANNEL_STATUSES = ("active", "pending", "failing", "disabled")
CONVERSATION_STATUSES = ("open", "snoozed", "closed")
MESSAGE_KINDS = ("message", "note", "call", "voicemail", "system")
MESSAGE_STATUSES = ("queued", "sent", "delivered", "read", "failed", "received")
CONSENT_STATUSES = ("opted_in", "opted_out", "dnd")


def in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


# The ciphertext is not readable by request handlers (column grants in migration 0006); `vault` decrypts it.
class Secret(Base):
    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("id", "workspace_id"),)
    __mapper_args__ = {"eager_defaults": False}

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        ForeignKeyConstraint(["secret_ref", "workspace_id"], ["secrets.id", "secrets.workspace_id"]),
        CheckConstraint(in_list("kind", KINDS), name="ck_channels_kind"),
        CheckConstraint(in_list("provider", PROVIDERS), name="ck_channels_provider"),
        CheckConstraint(in_list("status", CHANNEL_STATUSES), name="ck_channels_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    kind: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(320), default="", server_default="")  # number, email, widget key
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)  # never secrets
    secret_ref: Mapped[uuid.UUID | None]
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    status_detail: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


# a widget key is how a public page finds its channel, so it is unique across workspaces
Index("uq_channels_widget_key", Channel.address, unique=True, postgresql_where=text("kind = 'webchat'"))
Index("ix_channels_workspace", Channel.workspace_id)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        within("contact_id", "records"),
        ForeignKeyConstraint(["last_channel_id", "workspace_id"], ["channels.id", "channels.workspace_id"]),
        CheckConstraint(in_list("status", CONVERSATION_STATUSES), name="ck_conversations_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    contact_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    team_id: Mapped[uuid.UUID | None]  # ponytail: no teams table until module 03; stored as given
    snooze_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime] = created()
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # the per-conversation counters: seq is handed out under this row's lock; unread is last_inbound_seq > read mark
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    last_inbound_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    last_channel_id: Mapped[uuid.UUID | None]
    last_preview: Mapped[str] = mapped_column(String(200), default="", server_default="")
    last_direction: Mapped[str | None] = mapped_column(String(3))
    visitor_id: Mapped[uuid.UUID | None]  # a webchat visitor, until they give an email or phone number
    created_at: Mapped[datetime] = created()


# a contact has at most one live conversation: a closed one is reopened by the next message
Index("uq_conversations_live", Conversation.workspace_id, Conversation.contact_id, unique=True,
      postgresql_where=text("status <> 'closed'"))
Index("ix_conversations_list", Conversation.workspace_id, Conversation.status, Conversation.last_message_at.desc(),
      Conversation.id.desc())
Index("ix_conversations_assignee", Conversation.workspace_id, Conversation.assignee_id,
      postgresql_where=text("assignee_id IS NOT NULL"))
Index("ix_conversations_visitor", Conversation.visitor_id, postgresql_where=text("visitor_id IS NOT NULL"))
Index("ix_conversations_contact", Conversation.contact_id)


class ConversationRead(Base):
    __tablename__ = "conversation_reads"
    __table_args__ = (within("conversation_id", "conversations"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()
    last_read_seq: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = created()


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq"),
        UniqueConstraint("channel_id", "provider_message_id"),  # a retried webhook is a no-op
        within("conversation_id", "conversations"),
        ForeignKeyConstraint(["channel_id", "workspace_id"], ["channels.id", "channels.workspace_id"]),
        CheckConstraint("direction IN ('in', 'out')", name="ck_messages_direction"),
        CheckConstraint(in_list("kind", MESSAGE_KINDS), name="ck_messages_kind"),
        CheckConstraint(in_list("status", MESSAGE_STATUSES), name="ck_messages_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    conversation_id: Mapped[uuid.UUID]
    seq: Mapped[int] = mapped_column(BigInteger)  # the order the server stored; occurred_at is shown, never sorted by
    direction: Mapped[str] = mapped_column(String(3))
    channel_id: Mapped[uuid.UUID | None]
    kind: Mapped[str] = mapped_column(String(10), default="message", server_default="message")
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    html: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)
    status: Mapped[str] = mapped_column(String(10))
    error: Mapped[str | None] = mapped_column(String(500))
    provider_message_id: Mapped[str | None] = mapped_column(String(500))
    thread_ref: Mapped[str | None] = mapped_column(String(500))  # email: the Message-ID this one replies to
    sent_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    occurred_at: Mapped[datetime] = created()
    created_at: Mapped[datetime] = created()
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    segments: Mapped[int | None] = mapped_column(SmallInteger)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    idempotency_key: Mapped[str | None] = mapped_column(String(120))  # a workflow step's `run:node`, queued once
    search = mapped_column(TSVECTOR, Computed(
        "to_tsvector('simple', coalesce(subject, '') || ' ' || coalesce(body, ''))", persisted=True), deferred=True)


Index("ix_messages_search", Message.search, postgresql_using="gin")
Index("ix_messages_thread", Message.channel_id, Message.thread_ref, postgresql_where=text("thread_ref IS NOT NULL"))
# a step that is retried finds its message by this key instead of queueing a second one (ADR 0006)
Index("uq_messages_idempotency", Message.workspace_id, Message.idempotency_key, unique=True,
      postgresql_where=text("idempotency_key IS NOT NULL"))


class Consent(Base):
    """Per contact and channel kind: opted out (STOP, unsubscribe, a complaint), opted back in (START), or do not
    disturb. A contact with no row may be messaged."""
    __tablename__ = "consents"
    __table_args__ = (within("contact_id", "records"), CheckConstraint(in_list("status", CONSENT_STATUSES),
                                                                        name="ck_consents_status"))

    contact_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()
    status: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(30))  # stop, start, unsubscribe, complaint, manual
    reason: Mapped[str | None] = mapped_column(String(300))
    changed_at: Mapped[datetime] = created()


class ChatLimit(Base):
    """Requests per minute per widget key and per visitor IP (fixed windows), for the public chat endpoints."""
    __tablename__ = "chat_limits"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    bucket: Mapped[str] = mapped_column(String(200), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


Index("ix_chat_limits_window", ChatLimit.window_start)
