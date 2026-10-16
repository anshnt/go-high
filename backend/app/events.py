"""The event log (ADR 0003): every state change is an event row written in the same transaction as the change,
and consumers read the log with a cursor that cannot skip a transaction that commits late."""
import json
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    cast,
    exists,
    func,
    literal,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import UserDefinedType

from . import jobs
from .db import Base
from .jobs import Job

SCHEMAS = Path(__file__).parent / "event_types"
TYPES: dict[str, dict] = {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(SCHEMAS.glob("*.json"))}
BATCH = 500
RETRY_AFTER = timedelta(seconds=2)  # how soon the dispatcher looks again while a consumer waits on an open transaction


class XID8(UserDefinedType):
    """Postgres xid8 (64-bit transaction id) as an int. It has no cast from bigint, so it travels as text."""
    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "xid8"

    def bind_processor(self, dialect):
        return lambda value: None if value is None else str(value)

    def bind_expression(self, bindvalue):
        return cast(bindvalue, self)

    def result_processor(self, dialect, coltype):
        return lambda value: None if value is None else int(value)


ischema_names["xid8"] = XID8  # so reflection (alembic check) knows the type


# ponytail: one plain table. Monthly partitions on occurred_at (and cold storage after 90 days) come when volume
# needs them; that moves the primary key to (id, occurred_at) and drops the foreign keys that point at events.
class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    txid: Mapped[int] = mapped_column(XID8, server_default=text("pg_current_xact_id()"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(100))
    subject_type: Mapped[str] = mapped_column(String(50))
    subject_id: Mapped[uuid.UUID]
    actor_type: Mapped[str] = mapped_column(String(20))  # user, system
    actor_id: Mapped[uuid.UUID | None]
    data: Mapped[dict] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("ix_events_subject", Event.workspace_id, Event.subject_id, Event.occurred_at.desc())
Index("ix_events_txid_id", Event.txid, Event.id)


class EventCursor(Base):
    """How far one consumer has read. Not tenant data: only the owner role (worker, migrations) touches it."""
    __tablename__ = "event_cursors"

    consumer: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_txid: Mapped[int] = mapped_column(XID8, server_default=text("'0'"))
    last_id: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))


class UnknownEventType(ValueError):
    pass


def emit(db: Session, type: str, subject_type: str, subject_id: uuid.UUID, data: dict, *,
         actor: tuple[str, uuid.UUID] | None = None, workspace_id: uuid.UUID | None = None) -> Event:
    """Adds the event in the caller's transaction (it exists only if the caller commits) and schedules the
    dispatcher. The workspace is the request's, unless given. `actor` is ("user", id); the default is the system."""
    schema = TYPES.get(type)
    if schema is None:
        raise UnknownEventType(f"{type!r} has no schema in app/event_types")
    workspace_id = workspace_id or db.info.get("scope", {}).get("workspace_id")
    if not workspace_id:
        raise ValueError("emit needs a workspace: use an in_workspace session or pass workspace_id")
    data = jsonable_encoder(data)
    # ponytail: checks required and unexpected keys, not value types; validate with jsonschema once the
    # catalog generator needs it.
    unexpected = data.keys() - schema["properties"].keys() if schema.get("additionalProperties") is False else set()
    missing = set(schema.get("required", [])) - data.keys()
    if missing or unexpected:
        raise ValueError(f"{type} data does not match its schema (missing {sorted(missing)}, "
                         f"unexpected {sorted(unexpected)})")
    actor_type, actor_id = actor or ("system", None)
    event = Event(workspace_id=workspace_id, type=type, subject_type=subject_type, subject_id=subject_id,
                  actor_type=actor_type, actor_id=actor_id, data=data)
    db.add(event)
    db.flush()
    jobs.enqueue(db, "events.dispatch")
    return event


def read_batch(db: Session, consumer: str, limit: int = BATCH) -> list[Event]:
    """The next events for `consumer`, in (txid, id) order, only from transactions older than every transaction
    still open. A plain `id > last_id` cursor skips an event whose transaction commits after a higher id was
    read; here a late committer holds the horizon back instead. Locks the cursor, so two runs of the same
    consumer take turns. Process the batch and call `advance` in the same transaction."""
    db.execute(pg_insert(EventCursor).values(consumer=consumer).on_conflict_do_nothing())
    cursor = db.get(EventCursor, consumer, with_for_update=True, populate_existing=True)
    return list(db.scalars(
        select(Event)
        .where(after(cursor), Event.txid < func.pg_snapshot_xmin(func.pg_current_snapshot()))
        .order_by(Event.txid, Event.id).limit(limit)))


def after(cursor: EventCursor):
    here = tuple_(literal(cursor.last_txid, XID8()), literal(cursor.last_id, BigInteger()))
    return tuple_(Event.txid, Event.id) > here


def advance(db: Session, consumer: str, batch: list[Event]) -> None:
    if batch:
        cursor = db.get(EventCursor, consumer)
        cursor.last_txid, cursor.last_id = batch[-1].txid, batch[-1].id
        db.flush()


def unread(db: Session, consumer: str) -> bool:
    """Events past the cursor exist, whether or not they are visible yet (an open transaction may hide them)."""
    return bool(db.scalar(select(exists().where(after(db.get(EventCursor, consumer))))))


CONSUMERS: dict[str, Callable[[Session, list[Event]], None]] = {}


def consumer(name: str):
    """Registers a batch processor under the name of its cursor; the dispatcher calls it with new events."""
    def register(fn):
        CONSUMERS[name] = fn
        return fn
    return register


# ponytail: emit enqueues one dispatch job per event and a run marks the other due ones done, so a burst costs
# one pass. Replace with a recurring job plus LISTEN/NOTIFY when a poll of 2 s while a transaction is open hurts.
# A consumer that raises on one event holds its cursor there until the event is handled; add a dead letter
# after N failures when a consumer processes untrusted payloads.
@jobs.handler("events.dispatch")
def dispatch(db: Session, payload: dict) -> None:
    waiting = (Job.kind == "events.dispatch", Job.status == "queued")
    db.execute(update(Job).where(*waiting, Job.run_at <= func.now()).values(status="done", finished_at=func.now()))
    delays = []
    for name, process in CONSUMERS.items():
        batch = read_batch(db, name)
        process(db, batch)
        advance(db, name, batch)
        if len(batch) == BATCH:
            delays.append(timedelta(0))
        elif unread(db, name):
            delays.append(RETRY_AFTER)
    if delays and not db.scalar(select(exists().where(*waiting))):
        jobs.enqueue(db, "events.dispatch", run_at=func.now() + min(delays))
