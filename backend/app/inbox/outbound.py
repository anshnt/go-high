"""Sending (ADR 0005): `POST /api/v1/conversations/{id}/messages` stores a reply as queued in the request's own
transaction, after the consent check, and a `message.send` job hands it to the provider with retries. Internal notes
are messages that are never sent. Webchat replies need no provider: the visitor's page reads them, so they are sent at
once."""
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import AnyHttpUrl, BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events, jobs
from ..api import ApiError, Idem, idempotency
from ..channels.base import ChannelError, Outbound
from ..permissions import require, requires
from ..records.models import Record
from ..security import Ctx
from . import channels, consent, gateway, threads
from .conversations import conversation_or_404, mark_read
from .models import Channel, Conversation, Message

router = APIRouter(prefix="/api/v1/conversations")
send_messages = requires("messages.send")
MAX_ATTEMPTS = 6  # a retryable provider error is tried this many times (10 s, 20 s, 40 s... between them)
REFERENCES = 10  # earlier ids of the thread sent along with an email reply


class NewMessage(BaseModel):
    body: Annotated[str, Field(max_length=10000)] = ""
    kind: Literal["message", "note"] = "message"
    channel_id: uuid.UUID | None = None  # default: the channel the conversation last used
    subject: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None  # email
    html: Annotated[str, Field(max_length=200_000)] | None = None  # email
    attachments: Annotated[list[AnyHttpUrl], Field(max_length=10)] = []


def queue_send(db: Session, msg: Message) -> None:
    jobs.enqueue(db, "message.send", {"message_id": str(msg.id)}, max_attempts=MAX_ATTEMPTS + 2)


def refused(code: str, message: str) -> ApiError:
    return ApiError(422, code, message)


def address_of(channel: Channel, contact: Record, conv: Conversation) -> str | None:
    """Where this channel reaches the contact: their phone number or email address, or the open chat session."""
    return {"sms": contact.phone_e164, "whatsapp": contact.phone_e164, "email": contact.email_norm,
            "webchat": conv.visitor_id and str(conv.visitor_id)}.get(channel.kind)


def thread_of(db: Session, conv: Conversation, channel: Channel) -> tuple[str | None, list[str]]:
    """(the message to reply to, the thread so far) as email ids: the contact's last email, and up to REFERENCES
    earlier ones, oldest first."""
    rows = db.execute(select(Message.provider_message_id, Message.direction).where(
        Message.conversation_id == conv.id, Message.channel_id == channel.id,
        Message.provider_message_id.is_not(None)).order_by(Message.seq.desc()).limit(REFERENCES)).all()
    inbound = next((r.provider_message_id for r in rows if r.direction == "in"), None)
    return (inbound or (rows[0].provider_message_id if rows else None)), [r.provider_message_id for r in rows][::-1]


def reply_subject(db: Session, conv: Conversation, channel: Channel) -> str:
    last = db.scalar(select(Message.subject).where(
        Message.conversation_id == conv.id, Message.channel_id == channel.id, Message.subject.is_not(None))
        .order_by(Message.seq.desc()).limit(1))
    return last if last and last.lower().startswith("re:") else f"Re: {last}" if last else "(no subject)"


def channel_for(c: Ctx, conv: Conversation, channel_id: uuid.UUID | None) -> Channel:
    channel = c.db.get(Channel, channel_id or conv.last_channel_id) if (channel_id or conv.last_channel_id) else None
    if channel is None:
        raise ApiError(422, "no_channel", "Choose a channel to send on")
    if channel.status == "disabled":
        raise ApiError(422, "channel_disabled", f"The channel {channel.name} is disabled")
    return channel


@router.post("/{conversation_id}/messages", status_code=201)
def post_message(conversation_id: uuid.UUID, body: NewMessage, c: Ctx = Depends(send_messages),
                 idem: Idem = Depends(idempotency)):
    """Adds a reply or an internal note. A reply is refused with a reason (422, the error code names it: `opted_out`,
    `dnd`, `quiet_hours`, `frequency_cap`, `no_address`; `fields.retry_at` says when waiting helps) when consent or
    the channel does not allow it; otherwise it is stored as `queued` (an SMS answers with its segment count and
    estimated cost) and delivered by the worker. Send an `Idempotency-Key` so a retry cannot double-send."""
    conv, contact = conversation_or_404(c, conversation_id, lock=True)
    urls = [str(u) for u in body.attachments]
    if not body.body.strip() and not (urls and body.kind == "message"):
        raise ApiError(422, "validation_failed", "The message is empty", {"body": "is required"})
    actor, estimate, wire = ("user", c.user_id), None, {}
    if body.kind == "note":
        require(c, "conversations.write")
        msg = threads.append(c.db, conv, direction="out", kind="note", status="sent", body=body.body, sent_by=c.user_id)
        events.emit(c.db, "message.note_added", "message", msg.id, threads.message_data(msg, contact.id), actor=actor)
    else:
        channel = channel_for(c, conv, body.channel_id)
        if address_of(channel, contact, conv) is None:
            raise refused("no_address", f"The contact has no way to be reached on {channel.name}")
        if refusal := consent.verdict(c.db, channel, contact, conv):
            raise consent.refuse(refusal)
        email = channel.kind == "email"
        if channel.kind == "sms":
            estimate = channels.estimate(channel, body.body)
            wire = {"segments": estimate["segments"], "cost": Decimal(estimate["estimated_cost"])}
        thread = thread_of(c.db, conv, channel)[0] if email else None
        webchat = channel.kind == "webchat"
        msg = threads.append(
            c.db, conv, direction="out", status="sent" if webchat else "queued", channel_id=channel.id, body=body.body,
            subject=(body.subject or reply_subject(c.db, conv, channel)) if email else None,
            html=body.html if email else None, attachments=[{"url": u} for u in urls], thread_ref=thread,
            sent_by=c.user_id, **wire)
        if conv.status != "open":
            threads.reopen(c.db, conv, actor)
        if webchat:
            events.emit(c.db, "message.sent", "message", msg.id,
                        threads.message_data(msg, contact.id, provider_message_id=None), actor=actor)
        else:
            events.emit(c.db, "message.queued", "message", msg.id, threads.message_data(msg, contact.id), actor=actor)
            queue_send(c.db, msg)
    mark_read(c.db, conv, c.user_id, msg.seq)
    return idem.commit(201, {**threads.message_json(msg), "estimate": estimate})


def fail(db: Session, msg: Message, conv: Conversation, error: str) -> None:
    msg.status, msg.error = "failed", error[:500]
    events.emit(db, "message.failed", "message", msg.id, threads.message_data(msg, conv.contact_id, error=msg.error),
                workspace_id=msg.workspace_id)
    db.commit()


def sent(db: Session, msg: Message, conv: Conversation, channel: Channel) -> None:
    msg.status, msg.error = "sent", None
    if channel.status in ("pending", "failing"):
        channel.status, channel.status_detail = "active", None  # a provider that accepts a message works
    events.emit(db, "message.sent", "message", msg.id,
                threads.message_data(msg, conv.contact_id, provider_message_id=msg.provider_message_id),
                workspace_id=msg.workspace_id)
    db.commit()


def build(db: Session, msg: Message, channel: Channel, contact: Record, conv: Conversation) -> Outbound:
    to = contact.email_norm if channel.kind == "email" else contact.phone_e164
    if not to:
        raise ChannelError("the contact has no address on this channel")
    out = Outbound(to=to, body=msg.body, subject=msg.subject, html=msg.html,
                   attachments=[a["url"] for a in msg.attachments], reply_to=channel.config.get("reply_to"),
                   idempotency_key=str(msg.id))
    if channel.provider in ("twilio", "telnyx"):
        out.status_callback = gateway.hook_url(channel)  # delivery reports come back to the same webhook
    if channel.kind == "email":
        out.in_reply_to, out.references = msg.thread_ref, thread_of(db, conv, channel)[1]
    return out


class SendRetry(Exception):
    """Raised after a retryable failure was recorded, so the job queue tries again with its backoff."""


@jobs.handler("message.send")
def send(db: Session, payload: dict) -> None:
    """Delivers a queued message through its channel's adapter. The message id is the idempotency key, and a message
    that already has a provider id is never sent again. Consent is checked once more (a STOP may have arrived since
    the reply was queued): a quiet-hours refusal waits for the window, any other refusal fails the message.
    ponytail: a crash between the provider accepting a message and the commit below can double-send on Telnyx and
    WhatsApp, which have no idempotency key; a job that raises something other than a ChannelError is retried by the
    queue and leaves the message queued if it keeps failing."""
    msg = db.get(Message, uuid.UUID(payload["message_id"]))
    if msg is None or msg.status != "queued":
        return
    channel, conv = db.get(Channel, msg.channel_id), db.get(Conversation, msg.conversation_id)
    contact = db.get(Record, conv.contact_id)
    if msg.provider_message_id:
        return sent(db, msg, conv, channel)
    if channel.status == "disabled":
        return fail(db, msg, conv, "The channel is disabled")
    if msg.kind != "system" and (refusal := consent.verdict(db, channel, contact, conv, capped=False)):
        if refusal.retry_at:
            jobs.enqueue(db, "message.send", payload, run_at=refusal.retry_at, max_attempts=MAX_ATTEMPTS + 2)
            return db.commit()
        return fail(db, msg, conv, refusal.reason)
    try:
        result = gateway.send(channel, build(db, msg, channel, contact, conv))
    except ChannelError as e:
        msg.attempts += 1
        if not e.retryable or msg.attempts >= MAX_ATTEMPTS:
            return fail(db, msg, conv, str(e))
        msg.error = str(e)[:500]
        db.commit()
        raise SendRetry(msg.error) from None
    msg.provider_message_id = result.provider_message_id
    sent(db, msg, conv, channel)
