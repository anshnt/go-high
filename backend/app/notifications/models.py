"""Notifications and preferences (migration 0009). Both belong to one user in one workspace, and row level
security shows a notification to that user only."""
import uuid
from datetime import datetime, time

from sqlalchemy import ARRAY, CheckConstraint, DateTime, ForeignKey, Index, String, Text, Time, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from ..records.models import workspace

CHANNELS = ("in_app", "email")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key"),)

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="", server_default="")
    link: Mapped[str | None] = mapped_column(String(300))
    subject_type: Mapped[str | None] = mapped_column(String(20))
    subject_id: Mapped[uuid.UUID | None]
    dedupe_key: Mapped[str | None] = mapped_column(String(200))  # the same event or due time notifies once
    # when it shows up: a notification held by quiet hours is dated at their end, and is not listed before that
    created_at: Mapped[datetime] = created()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_notifications_user", Notification.workspace_id, Notification.user_id, Notification.created_at.desc(),
      Notification.id.desc())
Index("ix_notifications_unread", Notification.workspace_id, Notification.user_id,
      postgresql_where=Notification.read_at.is_(None))


class NotificationPref(Base):
    __tablename__ = "notification_prefs"
    __table_args__ = (
        CheckConstraint("scope IN ('all', 'mine')", name="ck_notification_prefs_scope"),
        CheckConstraint("digest IN ('daily', 'off')", name="ck_notification_prefs_digest"),
        CheckConstraint("channels <@ ARRAY['in_app', 'email']::varchar[]", name="ck_notification_prefs_channels"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), primary_key=True)
    channels: Mapped[list[str]] = mapped_column(ARRAY(String(10)), default=["in_app"],
                                                server_default=text("'{in_app}'"))
    scope: Mapped[str] = mapped_column(String(4), default="mine", server_default="mine")  # all: everyone's, mine: mine
    quiet_start: Mapped[time | None] = mapped_column(Time)
    quiet_end: Mapped[time | None] = mapped_column(Time)
    tz: Mapped[str | None] = mapped_column(String(64))  # the zone the quiet hours are read in
    digest: Mapped[str] = mapped_column(String(5), default="off", server_default="off")
