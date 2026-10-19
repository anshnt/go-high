"""The conversation write path (ADR 0005): one live conversation per contact, and messages stored in the order the
server saw them. Inbound webhooks, the webchat endpoints and the composer all append through `append`, which numbers
the message under the conversation's row lock and keeps the list's denormalized columns (last message, unread mark)
in step."""
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .. import events
from ..models import Role, Workspace
from ..security import Ctx
from .models import Conversation, Message

PREVIEW = 200
BODY_CAP, HTML_CAP = 100_000, 500_000
LISTED = ("message", "call", "voicemail")  # kinds that move a conversation up the list; notes and system lines do not


def system_ctx(db: Session, workspace: Workspace) -> Ctx:
    """A context for work done by the platform itself (an inbound message creating its contact), not by a user: it
    acts as the organization's Automation role (ADR 0004), so what it may do is visible and editable like any role."""
    role = db.scalar(select(Role).where(Role.org_id == workspace.org_id, Role.key == "automation"))
    return Ctx(db, None, None, "", workspace, workspace_role="automation", role=role)  # type: ignore[arg-type]


def clean(text: str | None, cap: int) -> str | None:
    """Postgres text cannot hold NUL, and mail can be any size."""
    return None if text is None else text.replace("\x00", "")[:cap]


def conversation_data(conv: Conversation) -> dict:
    return {"id": conv.id, "contact_id": conv.contact_id, "status": conv.status, "assignee_id": conv.assignee_id,
            "team_id": conv.team_id, "snooze_until": conv.snooze_until}


def message_data(msg: Message, contact_id: uuid.UUID, **more) -> dict:
    return {"id": msg.id, "conversation_id": msg.conversation_id, "contact_id": contact_id,
            "channel_id": msg.channel_id, "direction": msg.direction, "kind": msg.kind, "status": msg.status,
            "subject": msg.subject, "body": msg.body, "thread_ref": msg.thread_ref, **more}


def message_json(msg: Message) -> dict:
    return {"id": msg.id, "conversation_id": msg.conversation_id, "seq": msg.seq, "direction": msg.direction,
            "channel_id": msg.channel_id, "kind": msg.kind, "subject": msg.subject, "body": msg.body,
            "html": msg.html, "attachments": msg.attachments, "status": msg.status, "error": msg.error,
            "provider_message_id": msg.provider_message_id, "thread_ref": msg.thread_ref, "sent_by": msg.sent_by,
            "occurred_at": msg.occurred_at, "created_at": msg.created_at, "segments": msg.segments,
            "estimated_cost": None if msg.cost is None else str(msg.cost)}


def set_state(db: Session, conv: Conversation, *, actor: tuple[str, uuid.UUID] | None = None, **changes) -> bool:
    """Changes status, assignee_id, team_id or snooze_until, and emits `conversation.updated` if any differ."""
    diff = {k: {"old": getattr(conv, k), "new": v} for k, v in changes.items() if getattr(conv, k) != v}
    if not diff:
        return False
    for key, change in diff.items():
        setattr(conv, key, change["new"])
    db.flush()
    events.emit(db, "conversation.updated", "conversation", conv.id, {**conversation_data(conv), "changes": diff},
                actor=actor, workspace_id=conv.workspace_id)
    return True


def reopen(db: Session, conv: Conversation, actor: tuple[str, uuid.UUID] | None = None) -> bool:
    return set_state(db, conv, actor=actor, status="open", snooze_until=None)


def conversation_for(db: Session, workspace_id: uuid.UUID, contact_id: uuid.UUID) -> tuple[Conversation, bool]:
    """The contact's live (open or snoozed) conversation, else their latest closed one, else a new one. Returns it
    locked, with whether it was just created. The caller reopens a closed one when the message deserves it."""
    mine = (Conversation.workspace_id == workspace_id, Conversation.contact_id == contact_id)
    conv = db.scalar(select(Conversation).where(*mine, Conversation.status != "closed").with_for_update())
    conv = conv or db.scalar(select(Conversation).where(*mine).order_by(Conversation.last_message_at.desc())
                             .limit(1).with_for_update())
    if conv:
        return conv, False
    conv = Conversation(workspace_id=workspace_id, contact_id=contact_id)
    db.add(conv)
    db.flush()
    events.emit(db, "conversation.created", "conversation", conv.id, conversation_data(conv),
                workspace_id=workspace_id)
    return conv, True


def append(db: Session, conv: Conversation, *, direction: str, status: str, kind: str = "message",
           channel_id: uuid.UUID | None = None, body: str = "", subject: str | None = None, html: str | None = None,
           attachments: list | None = None, provider_message_id: str | None = None, thread_ref: str | None = None,
           sent_by: uuid.UUID | None = None, occurred_at: datetime | None = None, segments: int | None = None,
           cost: Decimal | None = None, idempotency_key: str | None = None) -> Message | None:
    """Stores a message as the next `seq` of the conversation. None when the channel already has this provider
    message id: a retried webhook changes nothing. The conversation row is locked first, so two writers take turns
    and the duplicate check cannot race."""
    db.refresh(conv, ["last_seq", "last_inbound_seq"], with_for_update=True)
    if provider_message_id and channel_id and db.scalar(select(exists().where(
            Message.channel_id == channel_id, Message.provider_message_id == provider_message_id))):
        return None
    body, now = clean(body, BODY_CAP) or "", datetime.now(UTC)
    msg = Message(workspace_id=conv.workspace_id, conversation_id=conv.id, seq=conv.last_seq + 1, direction=direction,
                  channel_id=channel_id, kind=kind, subject=clean(subject, 500), body=body, html=clean(html, HTML_CAP),
                  attachments=attachments or [], status=status, provider_message_id=provider_message_id,
                  thread_ref=thread_ref, sent_by=sent_by, occurred_at=occurred_at or now, segments=segments, cost=cost,
                  idempotency_key=idempotency_key)
    db.add(msg)
    conv.last_seq = msg.seq
    if kind in LISTED:
        conv.last_message_at, conv.last_channel_id, conv.last_direction = now, channel_id, direction
        conv.last_preview = (body.strip() or ("[attachment]" if attachments else ""))[:PREVIEW]
        if direction == "in":
            conv.last_inbound_at, conv.last_inbound_seq = now, msg.seq
    db.flush()
    return msg
