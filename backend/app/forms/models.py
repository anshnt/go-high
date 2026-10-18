"""Forms, surveys and quizzes (module 17): the form, its immutable versions, the submissions, and two small counters
(views per day, requests per minute). Policies and grants are in migration 0010. Every reference between these tables
carries the workspace id, so a row can never point into another workspace."""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from ..records.models import EMPTY_OBJECT, workspace

KINDS = ("form", "survey", "quiz")
STATUSES = ("draft", "published", "closed")
SUBMISSION_STATUSES = ("partial", "complete")


class Form(Base):
    __tablename__ = "forms"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        UniqueConstraint("workspace_id", "slug"),
        # the published version must be one of this form's own versions (added after both tables exist)
        ForeignKeyConstraint(["published_version_id", "id"], ["form_versions.id", "form_versions.form_id"],
                             name="fk_forms_published_version", use_alter=True),
        CheckConstraint("kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")", name="ck_forms_kind"),
        CheckConstraint("status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")", name="ck_forms_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    public_key: Mapped[str] = mapped_column(String(32), unique=True)  # what embeds and links carry; never the id
    kind: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(10), default="draft", server_default="draft")
    published_version_id: Mapped[uuid.UUID | None]
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FormVersion(Base):
    """One saved definition. Never updated: a save is a new row, and a submission keeps the version it began on."""
    __tablename__ = "form_versions"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        UniqueConstraint("id", "form_id"),
        UniqueConstraint("form_id", "number"),
        ForeignKeyConstraint(["form_id", "workspace_id"], ["forms.id", "forms.workspace_id"], ondelete="CASCADE"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    form_id: Mapped[uuid.UUID]
    number: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()


class Submission(Base):
    __tablename__ = "form_submissions"
    __table_args__ = (
        ForeignKeyConstraint(["form_id", "workspace_id"], ["forms.id", "forms.workspace_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["version_id", "form_id"], ["form_versions.id", "form_versions.form_id"],
                             ondelete="CASCADE"),
        CheckConstraint("status IN (" + ", ".join(f"'{s}'" for s in SUBMISSION_STATUSES) + ")",
                        name="ck_form_submissions_status"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    form_id: Mapped[uuid.UUID]
    version_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(10), default="partial", server_default="partial")
    answers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    score: Mapped[int | None] = mapped_column(Integer)
    max_score: Mapped[int | None] = mapped_column(Integer)
    # No foreign key: a purged contact must not take its responses along (the purge job clears this column).
    contact_id: Mapped[uuid.UUID | None]
    contact_error: Mapped[str | None] = mapped_column(String(300))
    consent: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    referrer: Mapped[str | None] = mapped_column(String(2000))
    utm: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    steps_seen: Mapped[list[str]] = mapped_column(ARRAY(String(40)), default=list, server_default="{}")
    last_field: Mapped[str | None] = mapped_column(String(40))
    resume_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    started_at: Mapped[datetime] = created()  # when the page was opened (the view token), else the first save
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_form_submissions_form", Submission.form_id, Submission.created_at.desc(), Submission.id.desc())
Index("ix_form_submissions_contact", Submission.contact_id)


class FormViews(Base):
    __tablename__ = "form_views"
    __table_args__ = (ForeignKeyConstraint(["form_id", "workspace_id"], ["forms.id", "forms.workspace_id"],
                                           ondelete="CASCADE"),)

    form_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()
    count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class FormRate(Base):
    """Requests per form, visitor (a keyed hash of the IP) and minute: the rate limit's counter."""
    __tablename__ = "form_rate"
    __table_args__ = (ForeignKeyConstraint(["form_id", "workspace_id"], ["forms.id", "forms.workspace_id"],
                                           ondelete="CASCADE"),)

    form_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    ip_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    bucket: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # minutes since the epoch
    workspace_id: Mapped[uuid.UUID] = workspace()
    count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
