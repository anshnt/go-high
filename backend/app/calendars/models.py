"""Calendars and booking tables (module 16). Policies and grants are in migration 0011. Every reference between these
tables carries the workspace id as well, so a row can never point into another workspace."""
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from ..records.models import EMPTY_LIST, EMPTY_OBJECT, within, workspace

KINDS = ("personal", "round_robin", "collective", "class", "service")
STATUSES = ("active", "paused", "archived")
CONFIRMATIONS = ("auto", "manual")
RESOURCE_KINDS = ("room", "equipment")
BOOKING_STATUSES = ("booked", "confirmed", "cancelled", "rescheduled", "no_show", "showed")
SYNC_STATUSES = ("none", "ok", "stale", "error")
REMINDER_STATUSES = ("pending", "sent", "cancelled")


def one_of(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")", name=name)


class Calendar(Base):
    __tablename__ = "calendars"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"), UniqueConstraint("workspace_id", "slug"),
        one_of("kind", KINDS, "ck_calendars_kind"), one_of("status", STATUSES, "ck_calendars_status"),
        one_of("confirmation", CONFIRMATIONS, "ck_calendars_confirmation"),
        CheckConstraint("buffer_before BETWEEN 0 AND 240 AND buffer_after BETWEEN 0 AND 240",
                        name="ck_calendars_buffer"),
        CheckConstraint("min_notice BETWEEN 0 AND 43200 AND window_days BETWEEN 1 AND 365", name="ck_calendars_rules"),
        CheckConstraint("slot_interval BETWEEN 5 AND 240 AND seats BETWEEN 1 AND 1000", name="ck_calendars_slots"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(2000), default="", server_default="")
    kind: Mapped[str] = mapped_column(String(12), default="personal", server_default="personal")
    durations: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=lambda: [30], server_default=text("'{30}'"))
    buffer_before: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    buffer_after: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    min_notice: Mapped[int] = mapped_column(Integer, default=240, server_default="240")  # minutes
    window_days: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    slot_interval: Mapped[int] = mapped_column(Integer, default=30, server_default="30")  # minutes between start times
    max_per_day: Mapped[int | None] = mapped_column(Integer)
    seats: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # attendees per slot (class)
    time_zone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    locations: Mapped[list] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)
    questions: Mapped[list] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)
    confirmation: Mapped[str] = mapped_column(String(6), default="auto", server_default="auto")
    color: Mapped[str] = mapped_column(String(20), default="indigo", server_default="indigo")
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active")
    reminders: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=lambda: [1440, 60],
                                                 server_default=text("'{1440,60}'"))  # minutes before the start
    cutoff_hours: Mapped[int | None] = mapped_column(Integer)  # cancel and reschedule links stop this long before
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


class CalendarHost(Base):
    __tablename__ = "calendar_hosts"
    __table_args__ = (
        UniqueConstraint("calendar_id", "user_id"), within("calendar_id", "calendars"),
        CheckConstraint("weight BETWEEN 0 AND 100", name="ck_calendar_hosts_weight"),
        CheckConstraint("daily_cap > 0", name="ck_calendar_hosts_cap"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    calendar_id: Mapped[uuid.UUID]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    weight: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # higher wins a tie
    daily_cap: Mapped[int | None] = mapped_column(Integer)  # this host's bookings of this calendar per day
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created()


Index("ix_calendar_hosts_user", CalendarHost.user_id)


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (UniqueConstraint("id", "workspace_id"), one_of("kind", RESOURCE_KINDS, "ck_resources_kind"),
                      CheckConstraint("quantity BETWEEN 1 AND 1000", name="ck_resources_quantity"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10), default="room", server_default="room")
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = created()


class CalendarResource(Base):
    __tablename__ = "calendar_resources"
    __table_args__ = (within("calendar_id", "calendars"), within("resource_id", "resources"),
                      CheckConstraint("quantity > 0", name="ck_calendar_resources_quantity"))

    calendar_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # needed per booking


class Availability(Base):
    """Working hours of a person or a resource: `weekly` maps mon..sun to [["09:00", "17:00"], ...] in `time_zone`,
    `overrides` maps an ISO date to its own ranges ([] = unavailable that day). The sync columns say how fresh the
    busy blocks imported from an outside calendar are (module 16 sync health)."""
    __tablename__ = "availability"
    __table_args__ = (
        within("resource_id", "resources"),
        CheckConstraint("(user_id IS NULL) <> (resource_id IS NULL)", name="ck_availability_owner"),
        one_of("sync_status", SYNC_STATUSES, "ck_availability_sync"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    resource_id: Mapped[uuid.UUID | None]
    time_zone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")
    weekly: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    overrides: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    sync_status: Mapped[str] = mapped_column(String(6), default="none", server_default="none")
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_error: Mapped[str | None] = mapped_column(String(300))
    updated_at: Mapped[datetime] = created()


Index("ix_availability_user", Availability.workspace_id, Availability.user_id, unique=True,
      postgresql_where=Availability.user_id.is_not(None))
Index("ix_availability_resource", Availability.resource_id, unique=True,
      postgresql_where=Availability.resource_id.is_not(None))


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"), within("calendar_id", "calendars"),
        ForeignKeyConstraint(["contact_id", "workspace_id"], ["records.id", "records.workspace_id"],
                             ondelete="SET NULL (contact_id)"),
        one_of("status", BOOKING_STATUSES, "ck_bookings_status"),
        CheckConstraint("ends_at > starts_at", name="ck_bookings_span"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    calendar_id: Mapped[uuid.UUID]
    host_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    host_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid()))  # everyone who attends; the host first
    contact_id: Mapped[uuid.UUID | None]
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    buffer_before: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # the calendar's, then
    buffer_after: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    time_zone: Mapped[str] = mapped_column(String(64), default="UTC", server_default="UTC")  # the invitee's
    status: Mapped[str] = mapped_column(String(10), default="booked", server_default="booked")
    invitee_name: Mapped[str] = mapped_column(String(300), default="", server_default="")
    invitee_email: Mapped[str | None] = mapped_column(String(254))
    invitee_phone: Mapped[str | None] = mapped_column(String(40))
    location: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    answers: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # the cancel and reschedule link; only its hash
    series_id: Mapped[uuid.UUID | None]
    source: Mapped[str] = mapped_column(String(10), default="page", server_default="page")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reschedules: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_bookings_start", Booking.workspace_id, Booking.starts_at)
Index("ix_bookings_calendar", Booking.calendar_id, Booking.starts_at)
Index("ix_bookings_contact", Booking.contact_id, postgresql_where=Booking.contact_id.is_not(None))
Index("ix_bookings_hosts", Booking.host_ids, postgresql_using="gin")


class BookingResource(Base):
    __tablename__ = "booking_resources"
    __table_args__ = (within("booking_id", "bookings"), ForeignKeyConstraint(
        ["resource_id", "workspace_id"], ["resources.id", "resources.workspace_id"]))

    booking_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


Index("ix_booking_resources_resource", BookingResource.resource_id)


class BusyBlock(Base):
    """Time a person is busy in an outside calendar, imported by sync (POST /api/v1/availability/busy)."""
    __tablename__ = "busy_blocks"
    __table_args__ = (CheckConstraint("ends_at > starts_at", name="ck_busy_blocks_span"),)

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(30), default="manual", server_default="manual")
    external_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created()


Index("ix_busy_blocks_user", BusyBlock.user_id, BusyBlock.starts_at)
Index("ix_busy_blocks_external", BusyBlock.user_id, BusyBlock.source, BusyBlock.external_id, unique=True,
      postgresql_where=BusyBlock.external_id.is_not(None))


class BookingReminder(Base):
    """One row per booking and offset. A job at `due_at` turns a pending row into `sent` and records the event; moving
    or cancelling the booking changes the row, so a job that finds another time or status does nothing."""
    __tablename__ = "booking_reminders"
    __table_args__ = (UniqueConstraint("booking_id", "offset_minutes"), within("booking_id", "bookings"),
                      one_of("status", REMINDER_STATUSES, "ck_booking_reminders_status"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    booking_id: Mapped[uuid.UUID]
    offset_minutes: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(9), default="pending", server_default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BookingAttempt(Base):
    """One row per public booking request, for the rate limit. Rows older than the window are deleted on write."""
    __tablename__ = "booking_attempts"
    __table_args__ = (within("calendar_id", "calendars"),)

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    calendar_id: Mapped[uuid.UUID]
    ip_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created()


Index("ix_booking_attempts_who", BookingAttempt.calendar_id, BookingAttempt.ip_hash, BookingAttempt.created_at)


class FeedToken(Base):
    """The secret in a person's private ICS feed URL. Only the hash is stored, so the URL is shown once."""
    __tablename__ = "feed_tokens"

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = created()


Index("ix_feed_tokens_user", FeedToken.workspace_id, FeedToken.user_id, unique=True)
