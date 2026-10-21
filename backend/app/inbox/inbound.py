"""Inbound webhooks (ADR 0005): `POST /api/hooks/{provider}/{channel_id}` (and Meta's GET handshake), public, with no
session. The channel is loaded in the system scope, its signature verified with the provider's adapter on the raw
body, and only then does the request move into the channel's workspace to store what the provider reported: messages
find or make their contact and land in the contact's conversation, delivery reports move messages forward, STOP,
START and HELP are handled before the inbox. A retried webhook changes nothing: a message is stored once per
(channel, provider message id)."""
import logging
import uuid
from dataclasses import asdict
from email.utils import parseaddr

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import compliance, config, events
from ..channels import ADAPTERS
from ..channels.base import Inbound
from ..channels.base import Request as Hook
from ..db import rescope, scoped
from ..models import Workspace
from ..records.models import Record
from ..records.schema import Catalog
from . import consent, contacts, gateway, outbound, threads
from .models import Channel, Conversation, Message

log = logging.getLogger("inbox")
router = APIRouter()
KEYWORD_KINDS = ("sms", "whatsapp")
# a delivery report only ever moves a message forward; failed outranks sent, delivered outranks failed
RANK = {"queued": 0, "sent": 1, "failed": 2, "delivered": 3, "read": 4}
REPLIES = {"stop": "You have been unsubscribed and will get no more messages. Reply START to subscribe again.",
           "start": "You are subscribed again. Reply STOP to unsubscribe.",
           "help": "Reply STOP to unsubscribe and START to subscribe again. Message and data rates may apply."}
CONSENT = {"stop": ("opted_out", "stop"), "start": ("opted_in", "start")}


@router.get("/api/hooks/{provider}/{channel_id}")
@router.post("/api/hooks/{provider}/{channel_id}")
async def hook(provider: str, channel_id: uuid.UUID, request: Request):
    """Where a provider reports messages and delivery. The signature is checked against the URL as it is configured
    in the provider (the first PUBLIC_URL origin), not the internal one a proxy forwards."""
    query = request.url.query
    url = f"{config.ALLOWED_ORIGINS[0]}{request.url.path}" + (f"?{query}" if query else "")
    hook_request = Hook(url, dict(request.headers), await request.body(), request.method)
    return await run_in_threadpool(handle, provider, channel_id, hook_request)


def handle(provider: str, channel_id: uuid.UUID, req: Hook):
    adapter = ADAPTERS.get(provider)
    if adapter is None or (req.method == "GET" and not hasattr(adapter, "challenge")):
        raise HTTPException(404, "Not found")
    with scoped(system="on") as db:
        channel = db.get(Channel, channel_id)
        workspace = db.get(Workspace, channel.workspace_id) if channel else None
        db.commit()
        if channel is None or channel.provider != provider or channel.status == "disabled":
            raise HTTPException(404, "Not found")
        account = gateway.account(channel)
        if req.method == "GET":
            answer = adapter.challenge(account, req)
            if answer is None:
                raise HTTPException(403, "Verification failed")
            return PlainTextResponse(answer)
        try:
            genuine = adapter.verify(account, req)
        except Exception:  # a body the verifier cannot even read is not genuine
            genuine = False
        if not genuine:
            log.warning("webhook for channel %s refused: no valid signature", channel_id)
            raise HTTPException(401, "Invalid signature")
        try:
            items = adapter.parse(req)
        except ValueError:
            raise HTTPException(400, "The webhook body is not readable") from None
        rescope(db, workspace_id=workspace.id, org_id=workspace.org_id)
        process(db, workspace, channel, items)
        db.commit()
    return {"received": len(items)}


def process(db: Session, workspace: Workspace, channel: Channel, items: list[Inbound]) -> None:
    cat = Catalog(threads.system_ctx(db, workspace))
    for item in items:
        if item.kind == "status":
            report(db, channel, item)
            continue
        try:
            receive(db, cat, workspace, channel, item)
        except contacts.Unusable as e:
            log.warning("message on channel %s from a sender that cannot be a contact: %s", channel.id, e)
    if channel.status in ("pending", "failing"):
        channel.status, channel.status_detail = "active", None  # a signed webhook proves the channel is wired up


def sender_of(channel: Channel, item: Inbound) -> tuple[str | None, str | None]:
    """(email, phone) of the sender: mail carries an address, SMS and WhatsApp an E.164 number."""
    if channel.kind == "email":
        return parseaddr(item.from_)[1].lower() or None, None
    return None, item.from_ or None


def thread_contact(db: Session, channel: Channel, ref: str | None) -> Record | None:
    """The contact of the conversation that holds the message this one replies to: a mail from an address we do not
    know (an alias) answering our message still belongs to that conversation."""
    if not ref:
        return None
    conv_id = db.scalar(select(Message.conversation_id).where(
        Message.channel_id == channel.id, or_(Message.provider_message_id == ref, Message.thread_ref == ref)).limit(1))
    conv = db.get(Conversation, conv_id) if conv_id else None
    contact = db.get(Record, conv.contact_id) if conv else None
    return contact if contact and contact.deleted_at is None else None


def receive(db: Session, cat: Catalog, workspace: Workspace, channel: Channel, item: Inbound) -> None:
    email, phone = sender_of(channel, item)
    if not (email or phone):
        log.warning("message on channel %s has no sender", channel.id)
        return
    if db.scalar(select(exists().where(Message.channel_id == channel.id,
                                       Message.provider_message_id == item.provider_message_id))):
        return  # a retried webhook
    contacts.lock(db, workspace.id, email or phone)
    obj = cat.need("contact")
    contact = contacts.find(cat, obj, email=email, phone=phone) or thread_contact(db, channel, item.thread_ref)
    created = contact is None
    if created:
        contact = contacts.create(cat, obj, {k: v for k, v in (("email", email), ("phone", phone)) if v}, channel.kind)
    conv, conversation_created = threads.conversation_for(db, workspace.id, contact.id)
    word = compliance.keyword(item.body) if channel.kind in KEYWORD_KINDS else None
    msg = threads.append(
        db, conv, direction="in", status="received", kind="system" if word else "message", channel_id=channel.id,
        body=item.body, subject=item.subject, html=item.html, attachments=[asdict(a) for a in item.attachments],
        provider_message_id=item.provider_message_id, thread_ref=item.thread_ref, occurred_at=item.occurred_at)
    if msg is None:
        return
    if word:
        keyword(db, workspace, channel, contact, conv, conversation_created, word)
        return
    if conv.status != "open":
        threads.reopen(db, conv)
    events.emit(db, "message.received", "message", msg.id,
                threads.message_data(msg, contact.id, channel_kind=channel.kind, contact_created=created,
                                     conversation_created=conversation_created), workspace_id=workspace.id)


def keyword(db: Session, workspace: Workspace, channel: Channel, contact: Record, conv: Conversation,
            conversation_created: bool, word: str) -> None:
    """STOP and START change the contact's consent for this channel kind, HELP only answers; each gets the channel's
    auto reply (`config.auto_replies`, an empty text switches it off). The message is kept in the thread as a
    system line, so it neither reopens the conversation nor counts as unread, and a stranger's STOP starts no
    open conversation."""
    if conversation_created:
        threads.set_state(db, conv, status="closed")
    if word in CONSENT:
        consent.record(db, workspace.id, contact.id, channel.kind, *CONSENT[word])
    reply = (channel.config.get("auto_replies") or {}).get(word, REPLIES[word])
    if reply:
        msg = threads.append(db, conv, direction="out", status="queued", kind="system", channel_id=channel.id,
                             body=reply)
        outbound.charge(db, msg, channel, source="inbox", enforce=False)  # the answer to a STOP goes out regardless
        outbound.queue_send(db, msg)


def report(db: Session, channel: Channel, item: Inbound) -> None:
    """A delivery report for an outbound message. A report for a message we do not know is dropped.
    ponytail: a report that beats the send job's commit of the provider id is dropped too and the message stays
    `sent`; park such reports and replay them when the id lands if that shows up in practice."""
    msg = db.scalar(select(Message).where(
        Message.channel_id == channel.id, Message.provider_message_id == item.provider_message_id,
        Message.direction == "out").with_for_update())
    if msg is None:
        log.info("delivery report on channel %s for an unknown message", channel.id)
        return
    conv = db.get(Conversation, msg.conversation_id)
    if item.status in ("complained", "unsubscribed"):  # the recipient does not want this mail: an opt-out
        source = "complaint" if item.status == "complained" else "unsubscribe"
        consent.record(db, msg.workspace_id, conv.contact_id, channel.kind, "opted_out", source)
        return
    if RANK.get(item.status or "", -1) <= RANK.get(msg.status, -1):
        return
    previous, msg.status = msg.status, item.status
    msg.error = (item.error or "")[:500] or None if item.status == "failed" else None
    db.flush()
    events.emit(db, "message.status_changed", "message", msg.id,
                threads.message_data(msg, conv.contact_id, error=msg.error, previous=previous),
                workspace_id=msg.workspace_id)
