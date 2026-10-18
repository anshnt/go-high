"""WhatsApp Cloud API (Meta Graph API): text, template and media sends, X-Hub-Signature-256, the hub.challenge
handshake, inbound messages and delivery statuses.

channel.address: the business phone number. config: phone_number_id. secrets: access_token, app_secret, verify_token.
One Meta webhook can carry several numbers and fields; `parse` keeps the `messages` field only."""
import hashlib
import hmac
import mimetypes
import re
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

from . import transport
from .base import Attachment, Channel, ChannelError, Inbound, Outbound, Request, SendResult, same

GRAPH = "https://graph.facebook.com/v23.0"
STATUS = {"sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed"}
MEDIA = ("image", "video", "audio", "sticker", "document")
# Graph throttling answers with HTTP 400 and one of these codes: wait and retry
THROTTLED = frozenset({"4", "17", "32", "613", "80007", "130429", "131056"})


def verify(channel: Channel, request: Request) -> bool:
    secret, given = channel.secrets.get("app_secret"), request.header("x-hub-signature-256")
    if not secret or not given.startswith("sha256="):
        return False
    return same(given[7:], hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest())


def challenge(channel: Channel, request: Request) -> str | None:
    """The GET handshake when the webhook is saved in the Meta app: answer 200 with this text, or 403 on None."""
    q, token = request.query(), channel.secrets.get("verify_token")
    value = q.get("hub.challenge", "")
    if q.get("hub.mode") == "subscribe" and token and same(q.get("hub.verify_token", ""), token) \
            and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        return value
    return None


def phone(number: str) -> str:
    return "+" + re.sub(r"\D", "", number)


def when(stamp: str | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(stamp or ""), UTC)
    except ValueError:
        return datetime.now(UTC)


def content(m: dict) -> tuple[str, list[Attachment]]:
    kind = m.get("type", "")
    body = m.get(kind) if isinstance(m.get(kind), dict) else {}
    if kind == "text":
        return body.get("body", ""), []
    if kind in MEDIA:
        media = Attachment(content_type=body.get("mime_type", ""), name=body.get("filename", ""),
                           media_id=body.get("id", ""))
        return body.get("caption", ""), [media]
    if kind == "interactive":  # a tapped button or list row
        return (body.get("button_reply") or body.get("list_reply") or {}).get("title", ""), []
    if kind == "location":
        return f"{body.get('latitude', '')},{body.get('longitude', '')} {body.get('name', '')}".strip(), []
    return body.get("text") or body.get("emoji") or "", []  # a template quick reply ("button"), a reaction


def parse(request: Request) -> list[Inbound]:
    out = []
    for entry in request.json_body().get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if change.get("field") != "messages":
                continue
            me = phone((value.get("metadata") or {}).get("display_phone_number", ""))
            for m in value.get("messages") or []:
                if not m.get("id"):
                    continue
                body, files = content(m)
                reply = (m.get("context") or {}).get("id") or (m.get("reaction") or {}).get("message_id")
                out.append(Inbound("message", m["id"], phone(m.get("from", "")), me, body, attachments=files,
                                   occurred_at=when(m.get("timestamp")), thread_ref=reply, status="received"))
            for s in value.get("statuses") or []:
                if s.get("status") not in STATUS or not s.get("id"):
                    continue
                e = (s.get("errors") or [{}])[0]
                detail = " ".join(filter(None, (str(e.get("code") or ""), e.get("title"),
                                                (e.get("error_data") or {}).get("details"))))
                out.append(Inbound("status", s["id"], me, phone(s.get("recipient_id", "")),
                                   occurred_at=when(s.get("timestamp")), status=STATUS[s["status"]],
                                   error=detail or None))
    return out


def payload(message: Outbound) -> dict:
    p = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": message.to}
    if message.template:
        t = message.template
        p |= {"type": "template", "template": {"name": t.name, "language": {"code": t.language}}}
        if t.params:  # ponytail: body variables only; header, button and media components are not built
            parameters = [{"type": "text", "text": v} for v in t.params]
            p["template"]["components"] = [{"type": "body", "parameters": parameters}]
    elif message.attachments:
        if len(message.attachments) > 1:
            raise ChannelError("WhatsApp takes one attachment per message")
        kind = (mimetypes.guess_type(urlsplit(message.attachments[0]).path)[0] or "").partition("/")[0]
        kind = kind if kind in ("image", "video", "audio") else "document"
        p |= {"type": kind, kind: {"link": message.attachments[0]}}
        if message.body and kind != "audio":  # audio cannot carry a caption
            p[kind]["caption"] = message.body
    else:
        p |= {"type": "text", "text": {"body": message.body, "preview_url": False}}
    return p


def check(channel: Channel, *, base_url: str = GRAPH) -> str:
    transport.get(f"{base_url}/{quote(channel.conf('phone_number_id'), safe='')}?fields=id",
                  headers={"Authorization": f"Bearer {channel.secret('access_token')}"})
    return "WhatsApp accepted the access token and phone number id"


def send(channel: Channel, message: Outbound, *, base_url: str = GRAPH) -> SendResult:
    # ponytail: the Cloud API has no idempotency key: the send job checks for an existing provider id first
    url = f"{base_url}/{quote(channel.conf('phone_number_id'), safe='')}/messages"
    data = transport.post(url, json=payload(message), retry_codes=THROTTLED,
                          headers={"Authorization": f"Bearer {channel.secret('access_token')}"})
    sent = data.get("messages")
    if not (isinstance(sent, list) and sent and sent[0].get("id")):
        raise ChannelError("WhatsApp answered without a message id")
    return SendResult(sent[0]["id"])
