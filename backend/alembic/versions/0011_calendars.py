"""calendars, hosts, availability, resources, bookings, busy blocks, reminders, spam attempts, feeds; workspace slug

Revision ID: 0011
Revises: 0005
Create Date: 2026-10-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011"
down_revision = "0005"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)
UUID_PK = dict(primary_key=True, server_default=sa.text("gen_random_uuid()"))
EMPTY_OBJECT = sa.text("'{}'::jsonb")
EMPTY_LIST = sa.text("'[]'::jsonb")
KINDS = ("personal", "round_robin", "collective", "class", "service")
BOOKING_STATUSES = ("booked", "confirmed", "cancelled", "rescheduled", "no_show", "showed")
# capabilities the system roles gain (the catalog is in app/permissions.py); custom roles are left as they are
CAPABILITIES = {"owner": ("calendars.read", "calendars.write", "calendars.manage"),
                "admin": ("calendars.read", "calendars.write", "calendars.manage"),
                "manager": ("calendars.read", "calendars.write", "calendars.manage"),
                "member": ("calendars.read", "calendars.write"), "viewer": ("calendars.read",),
                "automation": ("calendars.read", "calendars.write")}


def col(name: str, type_, *args, **kw) -> sa.Column:
    return sa.Column(name, type_, *args, **({"nullable": False} | kw))


def created(name: str = "created_at") -> sa.Column:
    return col(name, TS, server_default=sa.func.now())


def workspace() -> sa.Column:
    return col("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"))


def user(name: str = "user_id", **kw) -> sa.Column:
    return col(name, sa.Uuid(), sa.ForeignKey("users.id", ondelete=kw.pop("ondelete", "CASCADE")), **kw)


def within(column: str, table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column, "workspace_id"], [f"{table}.id", f"{table}.workspace_id"],
                                   ondelete="CASCADE")


def one_of(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")", name=name)


def tables() -> None:
    op.add_column("workspaces", sa.Column("slug", sa.String(60), nullable=True))
    op.execute("UPDATE workspaces SET slug = left(coalesce(nullif(trim(both '-' from regexp_replace(lower(name), "
               "'[^a-z0-9]+', '-', 'g')), ''), 'workspace'), 40) || '-' || substr(md5(id::text), 1, 4)")
    op.create_unique_constraint("uq_workspaces_slug", "workspaces", ["slug"])
    op.create_table(
        "calendars", col("id", sa.Uuid(), **UUID_PK), workspace(), col("name", sa.String(100)),
        col("slug", sa.String(60)), col("description", sa.String(2000), server_default=""),
        col("kind", sa.String(12), server_default="personal"),
        col("durations", postgresql.ARRAY(sa.Integer()), server_default=sa.text("'{30}'")),
        col("buffer_before", sa.Integer(), server_default="0"), col("buffer_after", sa.Integer(), server_default="0"),
        col("min_notice", sa.Integer(), server_default="240"), col("window_days", sa.Integer(), server_default="60"),
        col("slot_interval", sa.Integer(), server_default="30"), col("max_per_day", sa.Integer(), nullable=True),
        col("seats", sa.Integer(), server_default="1"), col("time_zone", sa.String(64), server_default="UTC"),
        col("locations", postgresql.JSONB(), server_default=EMPTY_LIST),
        col("questions", postgresql.JSONB(), server_default=EMPTY_LIST),
        col("confirmation", sa.String(6), server_default="auto"), col("color", sa.String(20), server_default="indigo"),
        col("status", sa.String(10), server_default="active"),
        col("reminders", postgresql.ARRAY(sa.Integer()), server_default=sa.text("'{1440,60}'")),
        col("cutoff_hours", sa.Integer(), nullable=True), created(), created("updated_at"),
        sa.UniqueConstraint("id", "workspace_id"), sa.UniqueConstraint("workspace_id", "slug"),
        one_of("kind", KINDS, "ck_calendars_kind"), one_of("status", ("active", "paused", "archived"),
                                                          "ck_calendars_status"),
        one_of("confirmation", ("auto", "manual"), "ck_calendars_confirmation"),
        sa.CheckConstraint("buffer_before BETWEEN 0 AND 240 AND buffer_after BETWEEN 0 AND 240",
                           name="ck_calendars_buffer"),
        sa.CheckConstraint("min_notice BETWEEN 0 AND 43200 AND window_days BETWEEN 1 AND 365",
                           name="ck_calendars_rules"),
        sa.CheckConstraint("slot_interval BETWEEN 5 AND 240 AND seats BETWEEN 1 AND 1000", name="ck_calendars_slots"))
    op.create_table(
        "calendar_hosts", col("id", sa.Uuid(), **UUID_PK), workspace(), col("calendar_id", sa.Uuid()), user(),
        col("weight", sa.Integer(), server_default="1"), col("priority", sa.Integer(), server_default="0"),
        col("daily_cap", sa.Integer(), nullable=True), col("active", sa.Boolean(), server_default=sa.text("true")),
        created(), sa.UniqueConstraint("calendar_id", "user_id"), within("calendar_id", "calendars"),
        sa.CheckConstraint("weight BETWEEN 0 AND 100", name="ck_calendar_hosts_weight"),
        sa.CheckConstraint("daily_cap > 0", name="ck_calendar_hosts_cap"))
    op.create_index("ix_calendar_hosts_user", "calendar_hosts", ["user_id"])
    op.create_table(
        "resources", col("id", sa.Uuid(), **UUID_PK), workspace(), col("name", sa.String(100)),
        col("kind", sa.String(10), server_default="room"), col("quantity", sa.Integer(), server_default="1"),
        created(), sa.UniqueConstraint("id", "workspace_id"),
        one_of("kind", ("room", "equipment"), "ck_resources_kind"),
        sa.CheckConstraint("quantity BETWEEN 1 AND 1000", name="ck_resources_quantity"))
    op.create_table(
        "calendar_resources", col("calendar_id", sa.Uuid(), primary_key=True),
        col("resource_id", sa.Uuid(), primary_key=True), workspace(), col("quantity", sa.Integer(), server_default="1"),
        within("calendar_id", "calendars"), within("resource_id", "resources"),
        sa.CheckConstraint("quantity > 0", name="ck_calendar_resources_quantity"))
    op.create_table(
        "availability", col("id", sa.Uuid(), **UUID_PK), workspace(), user(nullable=True),
        col("resource_id", sa.Uuid(), nullable=True), col("time_zone", sa.String(64), server_default="UTC"),
        col("weekly", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("overrides", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("sync_status", sa.String(6), server_default="none"), col("synced_at", TS, nullable=True),
        col("sync_error", sa.String(300), nullable=True), created("updated_at"), within("resource_id", "resources"),
        sa.CheckConstraint("(user_id IS NULL) <> (resource_id IS NULL)", name="ck_availability_owner"),
        one_of("sync_status", ("none", "ok", "stale", "error"), "ck_availability_sync"))
    op.create_index("ix_availability_user", "availability", ["workspace_id", "user_id"], unique=True,
                    postgresql_where=sa.text("user_id IS NOT NULL"))
    op.create_index("ix_availability_resource", "availability", ["resource_id"], unique=True,
                    postgresql_where=sa.text("resource_id IS NOT NULL"))
    op.create_table(
        "bookings", col("id", sa.Uuid(), **UUID_PK), workspace(), col("calendar_id", sa.Uuid()),
        user("host_user_id", nullable=True, ondelete="SET NULL"),
        col("host_ids", postgresql.ARRAY(sa.Uuid())), col("contact_id", sa.Uuid(), nullable=True),
        col("starts_at", TS), col("ends_at", TS), col("buffer_before", sa.Integer(), server_default="0"),
        col("buffer_after", sa.Integer(), server_default="0"), col("time_zone", sa.String(64), server_default="UTC"),
        col("status", sa.String(12), server_default="booked"), col("invitee_name", sa.String(300), server_default=""),
        col("invitee_email", sa.String(254), nullable=True), col("invitee_phone", sa.String(40), nullable=True),
        col("location", postgresql.JSONB(), server_default=EMPTY_OBJECT),
        col("answers", postgresql.JSONB(), server_default=EMPTY_OBJECT), col("token_hash", sa.String(64)),
        col("series_id", sa.Uuid(), nullable=True), col("source", sa.String(10), server_default="page"),
        user("created_by", nullable=True, ondelete="SET NULL"), col("reschedules", sa.Integer(), server_default="0"),
        col("cancelled_at", TS, nullable=True), col("cancel_reason", sa.String(500), nullable=True), created(),
        created("updated_at"), sa.UniqueConstraint("id", "workspace_id"), sa.UniqueConstraint("token_hash"),
        within("calendar_id", "calendars"),
        sa.ForeignKeyConstraint(["contact_id", "workspace_id"], ["records.id", "records.workspace_id"],
                                ondelete="SET NULL (contact_id)"),
        one_of("status", BOOKING_STATUSES, "ck_bookings_status"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_bookings_span"))
    op.create_index("ix_bookings_start", "bookings", ["workspace_id", "starts_at"])
    op.create_index("ix_bookings_calendar", "bookings", ["calendar_id", "starts_at"])
    op.create_index("ix_bookings_contact", "bookings", ["contact_id"],
                    postgresql_where=sa.text("contact_id IS NOT NULL"))
    op.create_index("ix_bookings_hosts", "bookings", ["host_ids"], postgresql_using="gin")
    op.create_table(
        "booking_resources", col("booking_id", sa.Uuid(), primary_key=True),
        col("resource_id", sa.Uuid(), primary_key=True), workspace(), col("quantity", sa.Integer(), server_default="1"),
        within("booking_id", "bookings"),
        sa.ForeignKeyConstraint(["resource_id", "workspace_id"], ["resources.id", "resources.workspace_id"]))
    op.create_index("ix_booking_resources_resource", "booking_resources", ["resource_id"])
    op.create_table(
        "busy_blocks", col("id", sa.Uuid(), **UUID_PK), workspace(), user(), col("starts_at", TS), col("ends_at", TS),
        col("source", sa.String(30), server_default="manual"), col("external_id", sa.String(200), nullable=True),
        created(), sa.CheckConstraint("ends_at > starts_at", name="ck_busy_blocks_span"))
    op.create_index("ix_busy_blocks_user", "busy_blocks", ["user_id", "starts_at"])
    op.create_index("ix_busy_blocks_external", "busy_blocks", ["user_id", "source", "external_id"], unique=True,
                    postgresql_where=sa.text("external_id IS NOT NULL"))
    op.create_table(
        "booking_reminders", col("id", sa.Uuid(), **UUID_PK), workspace(), col("booking_id", sa.Uuid()),
        col("offset_minutes", sa.Integer()), col("due_at", TS), col("status", sa.String(9), server_default="pending"),
        col("sent_at", TS, nullable=True), sa.UniqueConstraint("booking_id", "offset_minutes"),
        within("booking_id", "bookings"), one_of("status", ("pending", "sent", "cancelled"),
                                                 "ck_booking_reminders_status"))
    op.create_table(
        "booking_attempts", col("id", sa.Uuid(), **UUID_PK), workspace(), col("calendar_id", sa.Uuid()),
        col("ip_hash", sa.String(64)), created(), within("calendar_id", "calendars"))
    op.create_index("ix_booking_attempts_who", "booking_attempts", ["calendar_id", "ip_hash", "created_at"])
    op.create_table(
        "feed_tokens", col("id", sa.Uuid(), **UUID_PK), workspace(), user(), col("token_hash", sa.String(64)),
        created(), sa.UniqueConstraint("token_hash"))
    op.create_index("ix_feed_tokens_user", "feed_tokens", ["workspace_id", "user_id"], unique=True)


WORKSPACE = "FOR ALL USING (workspace_id = app_workspace_id()) WITH CHECK (workspace_id = app_workspace_id())"
# table: privileges for gohigh_app. Bookings are cancelled, never deleted, by a request.
RLS = {
    "calendars": "SELECT, INSERT, UPDATE, DELETE", "calendar_hosts": "SELECT, INSERT, UPDATE, DELETE",
    "resources": "SELECT, INSERT, UPDATE, DELETE", "calendar_resources": "SELECT, INSERT, UPDATE, DELETE",
    "availability": "SELECT, INSERT, UPDATE, DELETE", "bookings": "SELECT, INSERT, UPDATE",
    "booking_resources": "SELECT, INSERT, DELETE", "busy_blocks": "SELECT, INSERT, UPDATE, DELETE",
    "booking_reminders": "SELECT, INSERT, UPDATE", "booking_attempts": "SELECT, INSERT, DELETE",
    "feed_tokens": "SELECT, INSERT, DELETE",
}


def capabilities(grant: bool) -> None:
    for key, caps in CAPABILITIES.items():
        wanted = "ARRAY[" + ", ".join(f"'{c}'" for c in caps) + "]::text[]"
        if grant:
            op.execute(f"UPDATE roles SET capabilities = capabilities || ARRAY(SELECT c FROM unnest({wanted}) c "
                       f"WHERE c <> ALL(capabilities)) WHERE is_system AND key = '{key}'")
        else:
            op.execute(f"UPDATE roles SET capabilities = ARRAY(SELECT c FROM unnest(capabilities) c "
                       f"WHERE c <> ALL({wanted})) WHERE is_system AND key = '{key}'")


def upgrade() -> None:
    tables()
    for table, privileges in RLS.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT {privileges} ON {table} TO gohigh_app")
        op.execute(f"CREATE POLICY workspace ON {table} {WORKSPACE}")
    capabilities(True)


def downgrade() -> None:
    capabilities(False)
    for table in reversed(RLS):
        op.execute(f"DROP TABLE {table} CASCADE")
    op.drop_constraint("uq_workspaces_slug", "workspaces")
    op.drop_column("workspaces", "slug")
