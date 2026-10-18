"""The inbox API (ADR 0005, module 12): conversations by view with counts, one conversation with its messages,
assign, snooze, close, reopen, read marks, search and internal notes. Replies are posted in `outbound`.
Conversations belong to a contact and are shown only while the caller may see that contact (the record scope of
ADR 0004), so permissions apply here without a rule of their own."""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import and_, cast, false, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

from .. import events, jobs, permissions
from ..api import ApiError, Idem, idempotency, paginate, seal, unseal
from ..records import store
from ..records.filters import search_terms
from ..records.models import ObjectDef, Record
from ..records.schema import Catalog
from ..security import Ctx, in_workspace
from . import threads
from .models import Channel, Conversation, ConversationRead, Message

router = APIRouter(prefix="/api/v1/conversations")
Views = Literal["mine", "unassigned", "open", "snoozed", "closed", "unread"]
MAX_SNOOZE = timedelta(days=365)


class StartConversation(BaseModel):
    contact_id: uuid.UUID


class Assign(BaseModel):
    user_id: uuid.UUID | None = None  # null unassigns; leave out to keep
    team_id: uuid.UUID | None = None


class Snooze(BaseModel):
    until: datetime


class Read(BaseModel):
    seq: int | None = Field(None, ge=0)  # up to which message; default: all of them


class EditNote(BaseModel):
    body: Annotated[str, StringConstraints(min_length=1, max_length=10000)]


def conversation_json(c: Ctx, conv: Conversation, rec: Record, obj: ObjectDef, unread: bool,
                      channel_kind: str | None) -> dict:
    shown = permissions.redact(c, obj, {"email": rec.email_norm, "phone": rec.phone_e164})
    return {"id": conv.id, "contact": {"id": rec.id, "display_name": rec.display_name, "email": shown.get("email"),
                                       "phone": shown.get("phone")},
            "status": conv.status, "assignee_id": conv.assignee_id, "team_id": conv.team_id,
            "snooze_until": conv.snooze_until, "last_message_at": conv.last_message_at,
            "last_inbound_at": conv.last_inbound_at, "channel_id": conv.last_channel_id, "channel_kind": channel_kind,
            "preview": conv.last_preview, "last_direction": conv.last_direction, "unread": unread,
            "last_seq": conv.last_seq, "visitor": conv.visitor_id is not None, "created_at": conv.created_at}


def read_mark(db: Session, conv: Conversation, user_id: uuid.UUID) -> int:
    return db.scalar(select(ConversationRead.last_read_seq).where(
        ConversationRead.conversation_id == conv.id, ConversationRead.user_id == user_id)) or 0


def describe(c: Ctx, conv: Conversation, rec: Record, obj: ObjectDef) -> dict:
    channel = c.db.get(Channel, conv.last_channel_id) if conv.last_channel_id else None
    mark = read_mark(c.db, conv, c.user_id)
    return {**conversation_json(c, conv, rec, obj, conv.last_inbound_seq > mark, channel and channel.kind),
            "last_read_seq": mark}


def conversation_or_404(c: Ctx, conversation_id: uuid.UUID, *, lock: bool = False) -> tuple[Conversation, Record]:
    """The conversation and its contact, when the caller may see the contact; anything else is a 404."""
    cat = Catalog(c)
    stmt = (select(Conversation, Record).join(Record, Record.id == Conversation.contact_id)
            .where(Conversation.id == conversation_id, Conversation.workspace_id == c.workspace.id,
                   Record.deleted_at.is_(None), store.scope(cat, cat.need("contact"))))
    row = c.db.execute(stmt.with_for_update(of=Conversation) if lock else stmt).one_or_none()
    if row is None:
        raise HTTPException(404, "Conversation not found")
    return row[0], row[1]


def mark_read(db: Session, conv: Conversation, user_id: uuid.UUID, seq: int) -> None:
    """Moves the user's read mark forward to `seq` (never back)."""
    db.execute(pg_insert(ConversationRead).values(
        conversation_id=conv.id, user_id=user_id, workspace_id=conv.workspace_id, last_read_seq=seq
    ).on_conflict_do_update(index_elements=["conversation_id", "user_id"],
                            set_={"last_read_seq": func.greatest(ConversationRead.last_read_seq, seq),
                                  "updated_at": func.now()}))


def matching(terms: str | None):
    """Messages of a conversation that contain every word of the query, each as a prefix."""
    return Message.search.bool_op("@@")(cast(terms, TSQUERY)) if terms else false()


def view_condition(view: str, me: uuid.UUID, unread):
    open_ = Conversation.status == "open"
    return {"mine": and_(open_, Conversation.assignee_id == me),
            "unassigned": and_(open_, Conversation.assignee_id.is_(None)), "open": open_,
            "snoozed": Conversation.status == "snoozed", "closed": Conversation.status == "closed",
            "unread": and_(Conversation.status != "closed", unread)}[view]


def counts(c: Ctx, cat: Catalog, obj: ObjectDef) -> dict:
    """Every view's size, and the open conversations per channel, for the sidebar: two statements."""
    read = aliased(ConversationRead)
    unread = Conversation.last_inbound_seq > func.coalesce(read.last_read_seq, 0)
    mine = (Conversation.workspace_id == c.workspace.id, Record.deleted_at.is_(None), store.scope(cat, obj))
    row = c.db.execute(
        select(*[func.count().filter(view_condition(v, c.user_id, unread)).label(v) for v in Views.__args__])
        .select_from(Conversation).join(Record, Record.id == Conversation.contact_id)
        .outerjoin(read, and_(read.conversation_id == Conversation.id, read.user_id == c.user_id)).where(*mine)).one()
    per_channel = c.db.execute(select(Conversation.last_channel_id, func.count()).select_from(Conversation)
                               .join(Record, Record.id == Conversation.contact_id)
                               .where(*mine, Conversation.status == "open", Conversation.last_channel_id.is_not(None))
                               .group_by(Conversation.last_channel_id)).all()
    return {**row._asdict(), "channels": {str(ch): n for ch, n in per_channel}}


@router.get("")
def list_conversations(view: Views = "open", channel_id: uuid.UUID | None = None,
                       q: Annotated[str | None, Query(max_length=200)] = None, limit: int = Query(50, ge=1, le=200),
                       cursor: str | None = None, c: Ctx = Depends(in_workspace)):
    """Conversations of one view, most recently active first, with `counts` for every view on the first page.
    `channel_id` narrows to conversations whose last message used that channel; `q` searches message text and
    the contact's name, email and phone."""
    cat = Catalog(c)
    obj = cat.need("contact")
    read = aliased(ConversationRead)
    unread = Conversation.last_inbound_seq > func.coalesce(read.last_read_seq, 0)
    stmt = (select(Conversation, unread.label("unread"), Record, Channel.kind)
            .join(Record, Record.id == Conversation.contact_id)
            .outerjoin(Channel, Channel.id == Conversation.last_channel_id)
            .outerjoin(read, and_(read.conversation_id == Conversation.id, read.user_id == c.user_id))
            .where(Conversation.workspace_id == c.workspace.id, Record.deleted_at.is_(None), store.scope(cat, obj),
                   view_condition(view, c.user_id, unread)))
    if channel_id:
        stmt = stmt.where(Conversation.last_channel_id == channel_id)
    if q:
        terms = search_terms(q)
        words = cast(terms, TSQUERY) if terms else None
        found = select(Message.id).where(Message.conversation_id == Conversation.id, matching(terms)).exists()
        stmt = stmt.where((Record.search.bool_op("@@")(words) | found) if terms else false())
    rows, next_cursor = paginate(c.db, stmt, Conversation, limit, cursor, by="last_message_at")
    out = {"data": [conversation_json(c, conv, rec, obj, is_unread, kind) for conv, is_unread, rec, kind in rows],
           "next_cursor": next_cursor}
    if not cursor:
        out["counts"] = counts(c, cat, obj)
    return out


@router.post("", status_code=201)
def start_conversation(body: StartConversation, c: Ctx = Depends(in_workspace), idem: Idem = Depends(idempotency)):
    """The contact's conversation, made if they have none (answers 200 when it exists): the place to compose a
    first message to a contact who never wrote."""
    cat = Catalog(c)
    rec, obj = store.find(cat, body.contact_id)
    if obj.key != "contact":
        raise HTTPException(404, "Contact not found")
    conv, created = threads.conversation_for(c.db, c.workspace.id, rec.id)
    return idem.commit(201 if created else 200, describe(c, conv, rec, obj))


@router.get("/{conversation_id}")
def get_conversation(conversation_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), c: Ctx = Depends(in_workspace)):
    """The conversation and its newest messages (`messages.data`, newest first; page back with `next_cursor`)."""
    conv, rec = conversation_or_404(c, conversation_id)
    shown = describe(c, conv, rec, Catalog(c).need("contact"))
    return {**shown, "messages": message_page(c.db, conv, limit, None, None)}


def message_page(db: Session, conv: Conversation, limit: int, cursor: str | None, q: str | None) -> dict:
    stmt = select(Message).where(Message.conversation_id == conv.id)
    if q:
        stmt = stmt.where(matching(search_terms(q)))
    if cursor:
        try:
            kind, seq = unseal(cursor)
            if kind != "seq":
                raise ValueError(kind)
            stmt = stmt.where(Message.seq < int(seq))
        except (ValueError, TypeError):
            raise ApiError(400, "invalid_cursor", "The cursor is not valid") from None
    rows = db.scalars(stmt.order_by(Message.seq.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return {"data": [threads.message_json(m) for m in page],
            "next_cursor": seal(["seq", page[-1].seq]) if len(rows) > limit else None}


@router.get("/{conversation_id}/messages")
def list_messages(conversation_id: uuid.UUID, q: Annotated[str | None, Query(max_length=200)] = None,
                  limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(in_workspace)):
    """Messages by `seq`, newest first, optionally only those that contain every word of `q`."""
    conv, _ = conversation_or_404(c, conversation_id)
    return message_page(c.db, conv, limit, cursor, q)


def changed(c: Ctx, conv: Conversation, rec: Record, **changes) -> dict:
    threads.set_state(c.db, conv, actor=("user", c.user_id), **changes)
    c.db.commit()
    return describe(c, conv, rec, Catalog(c).need("contact"))


@router.post("/{conversation_id}/assign")
def assign(conversation_id: uuid.UUID, body: Assign, c: Ctx = Depends(in_workspace)):
    """Assigns to a member of the workspace and/or a team; send null to unassign. Keys left out stay as they are.
    ponytail: a team id is stored as given until teams exist (module 03)."""
    conv, rec = conversation_or_404(c, conversation_id, lock=True)
    changes = {}
    if "user_id" in body.model_fields_set:
        if body.user_id and not store.member_ids(c, {str(body.user_id)}):
            raise ApiError(422, "validation_failed", "The assignee is not valid",
                           {"user_id": "is not a member of this workspace"})
        changes["assignee_id"] = body.user_id
    if "team_id" in body.model_fields_set:
        changes["team_id"] = body.team_id
    return changed(c, conv, rec, **changes)


@router.post("/{conversation_id}/snooze")
def snooze(conversation_id: uuid.UUID, body: Snooze, c: Ctx = Depends(in_workspace)):
    """Hides the conversation until `until` (an aware time up to a year ahead); it comes back by itself, as open,
    and a message from the contact brings it back sooner."""
    if body.until.tzinfo is None:
        raise ApiError(422, "validation_failed", "The time is not valid", {"until": "needs a time zone"})
    now = datetime.now(UTC)
    if not now < body.until <= now + MAX_SNOOZE:
        raise ApiError(422, "validation_failed", "The time is not valid", {"until": "must be within the next year"})
    conv, rec = conversation_or_404(c, conversation_id, lock=True)
    jobs.enqueue(c.db, "conversation.wake", {"conversation_id": str(conv.id)}, run_at=body.until)
    return changed(c, conv, rec, status="snoozed", snooze_until=body.until)


@router.post("/{conversation_id}/close")
def close(conversation_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    conv, rec = conversation_or_404(c, conversation_id, lock=True)
    return changed(c, conv, rec, status="closed", snooze_until=None)


@router.post("/{conversation_id}/reopen")
def reopen(conversation_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    conv, rec = conversation_or_404(c, conversation_id, lock=True)
    return changed(c, conv, rec, status="open", snooze_until=None)


@router.post("/{conversation_id}/read")
def read(conversation_id: uuid.UUID, body: Read | None = None, c: Ctx = Depends(in_workspace)):
    """Marks messages up to `seq` (default: all) as read by the caller. Returns the new read mark."""
    conv, _ = conversation_or_404(c, conversation_id)
    seq = conv.last_seq if body is None or body.seq is None else min(body.seq, conv.last_seq)
    mark_read(c.db, conv, c.user_id, seq)
    c.db.commit()
    return {"last_read_seq": read_mark(c.db, conv, c.user_id)}


@router.patch("/{conversation_id}/messages/{message_id}")
def edit_note(conversation_id: uuid.UUID, message_id: uuid.UUID, body: EditNote, c: Ctx = Depends(in_workspace)):
    """An internal note's text, changed by its author only."""
    conv, _ = conversation_or_404(c, conversation_id)
    msg = c.db.scalar(select(Message).where(Message.id == message_id, Message.conversation_id == conv.id)
                      .with_for_update())
    if msg is None:
        raise HTTPException(404, "Message not found")
    if msg.kind != "note":
        raise ApiError(409, "not_a_note", "Only internal notes can be edited")
    if msg.sent_by != c.user_id:
        raise ApiError(403, "forbidden", "Only the author can edit a note")
    msg.body = threads.clean(body.body, threads.BODY_CAP)
    c.db.flush()
    events.emit(c.db, "message.updated", "message", msg.id, threads.message_data(msg, conv.contact_id),
                actor=("user", c.user_id))
    c.db.commit()
    return threads.message_json(msg)


@jobs.handler("conversation.wake")
def wake(db: Session, payload: dict) -> None:
    """Reopens a snoozed conversation once its time has come. A stale job (snoozed again for later, or already
    reopened) finds nothing due and does nothing."""
    conv = db.get(Conversation, uuid.UUID(payload["conversation_id"]))
    if conv and conv.status == "snoozed" and conv.snooze_until <= db.scalar(select(func.now())):
        threads.reopen(db, conv)
        db.commit()
