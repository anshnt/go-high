"""Webchat (ADR 0005, module 12): `GET /widget.js`, the small script a customer's page embeds, and the public
endpoints it talks to under `/api/public/chat/{widget_key}`. A visitor is known by a signed token (the page keeps it
in its own storage), never by a session cookie. Their first message makes a contact named "Visitor 1a2b" with a
conversation; they become a real contact when they leave an email or phone number. Requests are counted per minute
per widget key and per IP in `chat_limits`, and a hidden `website` field that only a bot fills in is dropped silently.
ponytail: polling every few seconds while the chat is open and one counter write per request; move the counters
to memory or Redis, and polling to SSE, when a widget sees real traffic."""
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .. import config, events
from ..api import ApiError, seal, unseal
from ..db import rescope, scoped
from ..models import Workspace
from ..records import store
from ..records.schema import Catalog
from ..security import client_ip
from . import contacts, threads
from .models import Channel, ChatLimit, Conversation, Message

router = APIRouter()
WIDGET = (Path(__file__).parent / "widget.js").read_bytes()
TOKEN_DAYS = 30
PAGE = 100  # messages answered to one poll
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class ChatMessage(BaseModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    client_id: uuid.UUID | None = None  # the page's id for this message, so a retry is stored once
    website: str = ""  # the honeypot


class Identify(BaseModel):
    name: Text | None = None
    email: Text | None = None
    phone: Text | None = None
    website: str = ""


@dataclass
class Chat:
    db: Session
    channel: Channel
    workspace: Workspace


def chat_for(widget_key: str):
    """The webchat channel with this key (found in the system scope, which is how a public page can find it), then
    the request moves into its workspace. A disabled or unknown key is a 404."""
    with scoped(system="on") as db:
        channel = db.scalar(select(Channel).where(Channel.kind == "webchat", Channel.address == widget_key))
        workspace = db.get(Workspace, channel.workspace_id) if channel else None
        db.commit()
        if channel is None or channel.status == "disabled":
            raise HTTPException(404, "Not found")
        rescope(db, workspace_id=workspace.id, org_id=workspace.org_id)
        yield Chat(db, channel, workspace)


def hit(c: Chat, bucket: str, limit: int) -> None:
    """Counts a request in the current minute's window and refuses it past `limit`. The count is committed before
    refusing, or the refusal would roll it back."""
    n = c.db.scalar(pg_insert(ChatLimit).values(
        workspace_id=c.workspace.id, bucket=bucket, window_start=func.date_trunc("minute", func.now()), hits=1
    ).on_conflict_do_update(index_elements=["workspace_id", "bucket", "window_start"],
                            set_={"hits": ChatLimit.hits + 1}).returning(ChatLimit.hits))
    if n == 1:  # a new window: forget the old ones
        c.db.execute(delete(ChatLimit).where(ChatLimit.window_start < func.now() - timedelta(hours=1)))
    c.db.commit()
    if n > limit:
        raise HTTPException(429, "Too many requests", headers={"Retry-After": "60"})


def limit(c: Chat, request: Request, kind: str) -> None:
    key, ip = (config.CHAT_SEND_PER_KEY, config.CHAT_SEND_PER_IP) if kind == "send" else (
        config.CHAT_POLL_PER_KEY, config.CHAT_POLL_PER_IP)
    hit(c, f"{kind}:{c.channel.id}:{client_ip(request)}", ip)  # first: one address's refused calls must not use up
    hit(c, f"{kind}:{c.channel.id}", key)  # the budget of everyone else


def token_for(channel: Channel, visitor: uuid.UUID) -> str:
    return seal(["chat", str(channel.id), str(visitor), int(time.time()) + TOKEN_DAYS * 86400])


def visitor_of(channel: Channel, authorization: str | None) -> uuid.UUID:
    """The visitor a `Bearer` token names, if it is signed, for this channel and not expired."""
    try:
        kind, channel_id, visitor, expires = unseal((authorization or "").removeprefix("Bearer ").strip())
        if kind != "chat" or channel_id != str(channel.id) or int(expires) < time.time():
            raise ValueError("not for this chat")
        return uuid.UUID(visitor)
    except (ApiError, ValueError, TypeError):
        raise HTTPException(401, "Start a chat session first") from None


def conversation_of(db: Session, c: Chat, visitor: uuid.UUID) -> Conversation | None:
    return db.scalar(select(Conversation).where(Conversation.workspace_id == c.workspace.id,
                                                Conversation.visitor_id == visitor))


async def cors(request: Request, call_next):
    """The widget runs on other people's sites, so the chat endpoints answer any origin. They use a bearer token and
    no cookies, which is why that is safe."""
    if not request.url.path.startswith("/api/public/chat/"):
        return await call_next(request)
    response = Response(status_code=204) if request.method == "OPTIONS" else await call_next(request)
    response.headers.update({
        "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, content-type",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Max-Age": "86400",
        "Access-Control-Expose-Headers": "Retry-After"})
    return response


@router.get("/widget.js", include_in_schema=False)
def widget():
    """The chat script: `<script src=".../widget.js" data-key="WIDGET KEY" async></script>`."""
    return Response(WIDGET, media_type="application/javascript; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.post("/api/public/chat/{widget_key}/session")
def start_session(request: Request, c: Chat = Depends(chat_for)):
    """A signed visitor token for this widget, and the texts it shows. Stores nothing about the visitor yet."""
    limit(c, request, "send")
    visitor = uuid.uuid4()
    conf = c.channel.config
    return {"token": token_for(c.channel, visitor), "visitor_id": visitor, "title": conf.get("title", c.channel.name),
            "greeting": conf.get("greeting", ""), "color": conf.get("color")}


@router.post("/api/public/chat/{widget_key}/messages")
def send_message(body: ChatMessage, request: Request, c: Chat = Depends(chat_for),
                 authorization: str | None = Header(default=None)):
    """A message from the visitor: it lands in their conversation (made on the first message) and the inbox hears
    about it. A retry with the same `client_id` stores nothing new."""
    visitor = visitor_of(c.channel, authorization)
    if body.website:
        return {"ok": True}  # the honeypot: a bot is told it worked
    limit(c, request, "send")
    db, ws = c.db, c.workspace
    contacts.lock(db, ws.id, f"visitor:{visitor}")
    conv, created, conv_created = conversation_of(db, c, visitor), False, False
    if conv is None:
        cat = Catalog(threads.system_ctx(db, ws))
        contact = contacts.create(cat, cat.need("contact"), {"first_name": "Visitor", "last_name": visitor.hex[:4]},
                                  "webchat")
        conv, conv_created = threads.conversation_for(db, ws.id, contact.id)
        conv.visitor_id, created = visitor, True
    msg = threads.append(db, conv, direction="in", status="received", channel_id=c.channel.id, body=body.body,
                         provider_message_id=str(body.client_id or uuid.uuid4()))
    if msg is not None:
        if conv.status != "open":
            threads.reopen(db, conv)
        events.emit(db, "message.received", "message", msg.id,
                    threads.message_data(msg, conv.contact_id, channel_kind="webchat", contact_created=created,
                                         conversation_created=conv_created), workspace_id=ws.id)
    db.commit()
    return {"ok": True, "seq": msg.seq if msg else None}


@router.post("/api/public/chat/{widget_key}/identify")
def identify(body: Identify, request: Request, c: Chat = Depends(chat_for),
             authorization: str | None = Header(default=None)):
    """The visitor leaves a name, an email or a phone number: their contact gets them (and stops being a nameless
    "Visitor"). Needs a first message. ponytail: if the email or number already belongs to another contact the two
    stay separate, for the dedupe queue (module 09)."""
    visitor = visitor_of(c.channel, authorization)
    if body.website:
        return {"ok": True}
    limit(c, request, "send")
    conv = conversation_of(c.db, c, visitor)
    if conv is None:
        raise HTTPException(409, "Send a message first")
    cat = Catalog(threads.system_ctx(c.db, c.workspace))
    obj = cat.need("contact")
    patch = {k: v for k, v in (("email", body.email), ("phone", body.phone)) if v}
    if body.name:
        first, _, last = body.name.partition(" ")
        patch |= {"first_name": first, "last_name": last.strip() or None}
    if patch:
        try:
            store.update(cat, obj, store.get(cat, obj, conv.contact_id, lock=True), patch)
        except ApiError as e:  # the public routes have no field list: say which one in the message
            raise HTTPException(422, "; ".join(f"{k.removeprefix('values.')} {v}" for k, v in (e.fields or {}).items())
                                or str(e.detail)) from None
    c.db.commit()
    return {"ok": True}


@router.get("/api/public/chat/{widget_key}/messages")
def poll(request: Request, after: int = Query(0, ge=0), c: Chat = Depends(chat_for),
         authorization: str | None = Header(default=None)):
    """The visitor's conversation after message number `after`: what they wrote and the replies. Internal notes and
    system lines are never included, and neither is anything sent or received on another channel: the conversation
    belongs to the contact, and the email or number a visitor typed in proves nothing, so mail or texts of that
    address are not theirs to read."""
    visitor = visitor_of(c.channel, authorization)
    limit(c, request, "poll")
    conv = conversation_of(c.db, c, visitor)
    rows = [] if conv is None else c.db.scalars(
        select(Message).where(Message.conversation_id == conv.id, Message.channel_id == c.channel.id,
                              Message.kind == "message", Message.seq > after, Message.status != "failed")
        .order_by(Message.seq).limit(PAGE)).all()
    return {"data": [{"seq": m.seq, "from": "visitor" if m.direction == "in" else "agent", "body": m.body,
                      "at": m.created_at} for m in rows]}

