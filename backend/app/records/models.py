"""The record engine's tables (ADR 0002). Objects and fields are rows, so a new object or field needs no migration, and
every record of every object lives in `records`. Policies and grants are in migration 0004. Every reference between
these tables carries the workspace id as well, so a row can never point into another workspace."""
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from ..models import created, pk
from .types import TYPES

CARDINALITIES = ("one_to_one", "one_to_many", "many_to_many")
EMPTY_OBJECT = text("'{}'::jsonb")
EMPTY_LIST = text("'[]'::jsonb")


def workspace() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))


def within(column: str, table: str) -> ForeignKeyConstraint:
    """A foreign key from (column, workspace_id) to <table>(id, workspace_id)."""
    return ForeignKeyConstraint([column, "workspace_id"], [f"{table}.id", f"{table}.workspace_id"], ondelete="CASCADE")


class ObjectDef(Base):
    __tablename__ = "objects"
    __table_args__ = (UniqueConstraint("workspace_id", "key"), UniqueConstraint("id", "workspace_id"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    key: Mapped[str] = mapped_column(String(40))
    singular: Mapped[str] = mapped_column(String(100))
    plural: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str] = mapped_column(String(50), default="box", server_default="box")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # ADR 0002 has one primary field; a list lets a contact's name be first_name + last_name
    primary_fields: Mapped[list[str]] = mapped_column(ARRAY(String(63)))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


class FieldDef(Base):
    __tablename__ = "fields"
    __table_args__ = (
        UniqueConstraint("object_id", "key"),
        within("object_id", "objects"),
        CheckConstraint("type IN (" + ", ".join(f"'{t}'" for t in TYPES) + ")", name="ck_fields_type"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    object_id: Mapped[uuid.UUID]
    key: Mapped[str] = mapped_column(String(63))
    label: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(20))
    options: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    rules: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (UniqueConstraint("id", "workspace_id"), within("object_id", "objects"))

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    object_id: Mapped[uuid.UUID]
    display_name: Mapped[str] = mapped_column(String(300), default="", server_default="")
    values: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    email_norm: Mapped[str | None] = mapped_column(String(254))
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ponytail: the search text covers archived fields' values too (archiving hides a field, the index keeps its
    # words); rebuild the column from live fields when that matters.
    search = mapped_column(TSVECTOR, Computed(
        "setweight(to_tsvector('simple', coalesce(display_name, '')), 'A') || "
        "setweight(to_tsvector('simple', \"values\"), 'B')", persisted=True), deferred=True)


Index("ix_records_list", Record.workspace_id, Record.object_id, Record.updated_at.desc())
# ponytail: one GIN over every workspace; btree_gin on (workspace_id, search) if a large workspace's search slows
Index("ix_records_search", Record.search, postgresql_using="gin")
Index("ix_records_values", Record.values, postgresql_using="gin", postgresql_ops={"values": "jsonb_path_ops"})
Index("ix_records_email", Record.workspace_id, Record.email_norm)
Index("ix_records_phone", Record.workspace_id, Record.phone_e164)
Index("ix_records_trash", Record.workspace_id, Record.object_id, Record.deleted_at.desc(),
      postgresql_where=Record.deleted_at.is_not(None))


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("id", "workspace_id"),)

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(20))
    group_name: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created()


Index("ix_tags_name", Tag.workspace_id, func.lower(Tag.name), unique=True)


class RecordTag(Base):
    __tablename__ = "record_tags"
    __table_args__ = (within("record_id", "records"), within("tag_id", "tags"))

    record_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()
    created_at: Mapped[datetime] = created()


Index("ix_record_tags_tag", RecordTag.tag_id, RecordTag.record_id)


class AssociationType(Base):
    __tablename__ = "association_types"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id"),
        UniqueConstraint("from_object_id", "to_object_id", "label"),
        within("from_object_id", "objects"),
        within("to_object_id", "objects"),
        CheckConstraint("cardinality IN (" + ", ".join(f"'{c}'" for c in CARDINALITIES) + ")",
                        name="ck_association_types_cardinality"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    from_object_id: Mapped[uuid.UUID]
    to_object_id: Mapped[uuid.UUID]
    label: Mapped[str] = mapped_column(String(100))
    inverse_label: Mapped[str] = mapped_column(String(100))
    cardinality: Mapped[str] = mapped_column(String(12), default="many_to_many", server_default="many_to_many")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = created()


class Association(Base):
    __tablename__ = "associations"
    __table_args__ = (
        UniqueConstraint("type_id", "from_record_id", "to_record_id"),
        within("type_id", "association_types"),
        within("from_record_id", "records"),
        within("to_record_id", "records"),
        CheckConstraint("from_record_id <> to_record_id", name="ck_associations_distinct"),
    )

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    type_id: Mapped[uuid.UUID]
    from_record_id: Mapped[uuid.UUID]
    to_record_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = created()


Index("ix_associations_from", Association.from_record_id)
Index("ix_associations_to", Association.to_record_id)


class SavedView(Base):
    __tablename__ = "saved_views"
    __table_args__ = (within("object_id", "objects"),)

    id: Mapped[uuid.UUID] = pk()
    workspace_id: Mapped[uuid.UUID] = workspace()
    object_id: Mapped[uuid.UUID]
    name: Mapped[str] = mapped_column(String(200))
    filter: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=EMPTY_OBJECT)
    columns: Mapped[list] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)
    sort: Mapped[list] = mapped_column(JSONB, default=list, server_default=EMPTY_LIST)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    shared: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()


Index("ix_saved_views_object", SavedView.workspace_id, SavedView.object_id)


# Events that touch several records (an association links two) are listed here, so a record's timeline is one indexed
# query. No foreign key to events: the log gets partitioned (ADR 0003), the same reason webhook_deliveries has none.
class EventRecord(Base):
    __tablename__ = "event_records"
    __table_args__ = (within("record_id", "records"),)

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    record_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID] = workspace()


Index("ix_event_records_record", EventRecord.record_id, EventRecord.event_id.desc())
