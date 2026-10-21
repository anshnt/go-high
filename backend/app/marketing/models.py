"""The email marketing tables (module 20, migration 0015): sending domains with their DNS checks, saved templates,
subscription topics and each contact's choices, campaigns, the links of a campaign, one send per recipient, the
engagement log and the suppression list. Every reference carries the workspace id, like the rest of the schema, so a
row can never point into another workspace."""
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from ..records.models import EMPTY_OBJECT, within, workspace

DOMAIN_STATUSES = ("pending", "verified", "failing")
DKIM_MODES = ("managed", "provider")  # we sign with a key we made, or the provider signs (Mailgun, SES easy DKIM)
CAMPAIGN_STATUSES = ("draft", "scheduled", "sending", "testing", "paused", "sent", "cancelled", "failed")
# queued: waits for its batch; held: the rest of an A/B test's audience, waiting for the winner; sending: claimed by a
# batch; uncertain: the provider may or may not have taken it (a crash or a lost answer), so it is never sent again
SEND_STATUSES = ("queued", "held", "sending", "sent", "delivered", "bounced", "complained", "failed", "skipped",
                 "cancelled", "uncertain")
PHASES = ("all", "test", "main")
EVENT_TYPES = ("open", "click", "delivered", "bounce", "complaint", "unsubscribe")
SUPPRESSION_REASONS = ("hard_bounce", "complaint", "unsubscribe", "manual")


def one_of(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")", name=name)


def user_ref() -> Mapped[uuid.UUID | None]:
    return mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class EmailSettings(Base):
    """What every marketing email of the workspace carries: the sender's name and postal address in the footer (the
    law in most places asks for both), and whether opens and clicks are tracked."""
    __tablename__ = "email_settings"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    company_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    postal_address: Mapped[str] = mapped_column(String(500), default="", server_default="")
    track_opens: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    track_clicks: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    updated_at: Mapped[datetime] = created()


class EmailDomain(Base):
    """A domain the workspace sends from. `checks` keeps the last SPF, DKIM and DMARC answers; a managed DKIM key's
    private half is a vault secret (never readable by the API role)."""
    __tablename__ = "email_domains"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        UniqueConstraint("workspace_id", "domain"),
        ForeignKeyConstraint(["dkim_secret_ref", "workspace_id"], ["secrets.id", "secrets.workspace_id"]),
        one_of("status", DOMAIN_STATUSES, "ck_email_domains_status"),
        one_of("dkim_mode", DKIM_MODES, "ck_email_domains_dkim_mode"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    domain: Mapped[str] = mapped_column(String(253))
    dkim_mode: Mapped[str] = mapped_column(String(10), default="managed", server_default="managed")
    dkim_selector: Mapped[str] = mapped_column(String(63))
    dkim_public_key: Mapped[str | None] = mapped_column(Text)  # base64 DER of the managed key's public half
    dkim_secret_ref: Mapped[uuid.UUID | None]
    spf_include: Mapped[str | None] = mapped_column(String(253))  # what the SPF record must include (mailgun.org)
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    checks: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warmup_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hourly_limit: Mapped[int | None] = mapped_column(Integer)  # replaces the warm-up schedule when set
    created_by: Mapped[uuid.UUID | None] = user_ref()
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class EmailTemplate(Base):
    """A saved design: a subject, a preheader and a block document (see document.py)."""
    __tablename__ = "email_templates"
    __table_args__ = (UniqueConstraint("id", "workspace_id"),)

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(500), default="", server_default="")
    preheader: Mapped[str] = mapped_column(String(300), default="", server_default="")
    document: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = user_ref()
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_email_templates_list", EmailTemplate.workspace_id, EmailTemplate.updated_at.desc(), EmailTemplate.id.desc())


class EmailTopic(Base):
    """A kind of mail people can opt out of on its own (Newsletter, Product updates), on the preference page."""
    __tablename__ = "email_topics"
    __table_args__ = (UniqueConstraint("id", "workspace_id"), UniqueConstraint("workspace_id", "name"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300), default="", server_default="")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


class EmailPreference(Base):
    """A contact's choice for one topic. No row: subscribed."""
    __tablename__ = "email_preferences"
    __table_args__ = (within("contact_id", "records"), within("topic_id", "email_topics"))

    contact_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()
    subscribed: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(20))  # preference_center, one_click, manual
    changed_at: Mapped[datetime] = created()


class EmailCampaign(Base):
    __tablename__ = "email_campaigns"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        ForeignKeyConstraint(["channel_id", "workspace_id"], ["channels.id", "channels.workspace_id"]),
        ForeignKeyConstraint(["domain_id", "workspace_id"], ["email_domains.id", "email_domains.workspace_id"]),
        ForeignKeyConstraint(["topic_id", "workspace_id"], ["email_topics.id", "email_topics.workspace_id"]),
        one_of("status", CAMPAIGN_STATUSES, "ck_email_campaigns_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="draft", server_default="draft")
    paused_from: Mapped[str | None] = mapped_column(String(10))  # what resume goes back to
    channel_id: Mapped[uuid.UUID | None]
    domain_id: Mapped[uuid.UUID | None]
    topic_id: Mapped[uuid.UUID | None]
    template_id: Mapped[uuid.UUID | None]  # where the content was copied from; the campaign keeps its own copy
    from_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    from_email: Mapped[str] = mapped_column(String(320), default="", server_default="")
    reply_to: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500), default="", server_default="")
    preheader: Mapped[str] = mapped_column(String(300), default="", server_default="")
    document: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    audience: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    ab: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    winner: Mapped[str | None] = mapped_column(String(1))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audience_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = user_ref()
    scheduled_by: Mapped[uuid.UUID | None] = user_ref()
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_email_campaigns_list", EmailCampaign.workspace_id, EmailCampaign.updated_at.desc(), EmailCampaign.id.desc())


class EmailLink(Base):
    """A link of a campaign's content, by number. A click token names the number, never the address, so the click
    endpoint can only send people where the campaign links to (no open redirect)."""
    __tablename__ = "email_links"
    __table_args__ = (within("campaign_id", "email_campaigns"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    idx: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()
    url: Mapped[str] = mapped_column(String(2000))


class EmailSend(Base):
    """One recipient of one campaign: unique per campaign by contact and by address, which is what makes a send
    exactly once per recipient."""
    __tablename__ = "email_sends"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        UniqueConstraint("campaign_id", "contact_id"),
        UniqueConstraint("campaign_id", "email"),
        within("campaign_id", "email_campaigns"),
        within("contact_id", "records"),
        ForeignKeyConstraint(["domain_id", "workspace_id"], ["email_domains.id", "email_domains.workspace_id"]),
        one_of("status", SEND_STATUSES, "ck_email_sends_status"),
        one_of("phase", PHASES, "ck_email_sends_phase"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    campaign_id: Mapped[uuid.UUID]
    contact_id: Mapped[uuid.UUID]
    domain_id: Mapped[uuid.UUID | None]
    email: Mapped[str] = mapped_column(String(320))
    variant: Mapped[str | None] = mapped_column(String(1))
    phase: Mapped[str] = mapped_column(String(4), default="all", server_default="all")
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued")
    reason: Mapped[str | None] = mapped_column(String(300))  # why it was skipped, failed or bounced
    provider_message_id: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # first open by a person
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # first click by a person
    opens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    clicks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


Index("ix_email_sends_campaign", EmailSend.campaign_id, EmailSend.status)
Index("ix_email_sends_throttle", EmailSend.domain_id, EmailSend.claimed_at,
      postgresql_where=text("claimed_at IS NOT NULL"))
Index("ix_email_sends_provider", EmailSend.provider_message_id,
      postgresql_where=text("provider_message_id IS NOT NULL"))
Index("ix_email_sends_contact", EmailSend.contact_id)


class EmailEvent(Base):
    """What happened to a send after it left: opens, clicks, delivery, bounces, complaints and unsubscribes.
    `machine` marks what a person did not do: a security scanner's click, a privacy proxy's open."""
    __tablename__ = "email_events"
    __table_args__ = (
        within("campaign_id", "email_campaigns"),
        ForeignKeyConstraint(["send_id", "workspace_id"], ["email_sends.id", "email_sends.workspace_id"],
                             ondelete="CASCADE"),
        one_of("type", EVENT_TYPES, "ck_email_events_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()
    campaign_id: Mapped[uuid.UUID]
    send_id: Mapped[uuid.UUID]
    type: Mapped[str] = mapped_column(String(12))
    link_idx: Mapped[int | None] = mapped_column(Integer)
    machine: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    detail: Mapped[str | None] = mapped_column(String(300))
    occurred_at: Mapped[datetime] = created()


Index("ix_email_events_campaign", EmailEvent.campaign_id, EmailEvent.type)
Index("ix_email_events_send", EmailEvent.send_id, EmailEvent.occurred_at)


class EmailSuppression(Base):
    """An address the workspace never mails again: a hard bounce, a complaint, an unsubscribe or a manual entry."""
    __tablename__ = "email_suppressions"
    __table_args__ = (UniqueConstraint("workspace_id", "email"),
                      one_of("reason", SUPPRESSION_REASONS, "ck_email_suppressions_reason"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    email: Mapped[str] = mapped_column(String(320))
    reason: Mapped[str] = mapped_column(String(12))
    detail: Mapped[str | None] = mapped_column(String(300))
    campaign_id: Mapped[uuid.UUID | None]  # the campaign it came from, if any (kept when the campaign goes)
    created_by: Mapped[uuid.UUID | None] = user_ref()
    created_at: Mapped[datetime] = created()


Index("ix_email_suppressions_list", EmailSuppression.workspace_id, EmailSuppression.created_at.desc(),
      EmailSuppression.id.desc())
