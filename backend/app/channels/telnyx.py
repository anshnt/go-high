"""Telnyx SMS and MMS: v2 messages API, Ed25519 webhook signatures, message.received and message.finalized events.

channel.address: the sending number. config: public_key (base64 Ed25519, from the Telnyx portal; it is public),
messaging_profile_id (optional). secrets: api_key."""
import base64
import time
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from . import transport
from .base import TOLERANCE, Attachment, Channel, ChannelError, Inbound, Outbound, Request, SendResult

API = "https://api.telnyx.com"
STATUS = {"queued": "queued", "sending": "queued", "sent": "sent", "delivered": "delivered",
          "delivery_unconfirmed": "sent", "sending_failed": "failed", "delivery_failed": "failed"}


def verify(channel: Channel, request: Request, now: float | None = None) -> bool:
    """The signature covers "<telnyx-timestamp>|<raw body>". A timestamp more than 5 minutes off is refused."""
    key = channel.config.get("public_key")
    given, stamp = request.header("telnyx-signature-ed25519"), request.header("telnyx-timestamp")
    if not key or not given or not stamp:
        return False
    try:
        if abs((time.time() if now is None else now) - int(stamp)) > TOLERANCE:
            return False
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(
            base64.b64decode(given, validate=True), stamp.encode() + b"|" + request.body)
    except (ValueError, InvalidSignature):  # not base64, a key of the wrong size, a bad timestamp or a wrong signature
        return False
    return True


def when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def parse(request: Request) -> list[Inbound]:
    event = request.json_body().get("data") or {}
    p = event.get("payload") or {}
    if not p.get("id"):
        return []
    sender = (p.get("from") or {}).get("phone_number", "")
    to = ((p.get("to") or [{}])[0]).get("phone_number", "")
    if event.get("event_type") == "message.received":
        media = [Attachment(url=m.get("url", ""), content_type=m.get("content_type", "")) for m in p.get("media") or []]
        return [Inbound("message", p["id"], sender, to, p.get("text") or "", subject=p.get("subject") or None,
                        attachments=media, occurred_at=when(p.get("received_at") or event.get("occurred_at")),
                        status="received")]
    if event.get("event_type") == "message.finalized":
        status = STATUS.get(((p.get("to") or [{}])[0]).get("status", ""))
        if status is None:
            return []
        e = (p.get("errors") or [{}])[0]
        error = " ".join(filter(None, (e.get("code"), e.get("title"), e.get("detail")))) or None
        done = when(p.get("completed_at") or event.get("occurred_at"))
        return [Inbound("status", p["id"], sender, to, occurred_at=done, status=status, error=error)]
    return []


def check(channel: Channel, *, base_url: str = API) -> str:
    transport.get(f"{base_url}/v2/messaging_profiles?page%5Bsize%5D=1",
                  headers={"Authorization": f"Bearer {channel.secret('api_key')}"})
    return "Telnyx accepted the API key"


def send(channel: Channel, message: Outbound, *, base_url: str = API) -> SendResult:
    payload: dict = {"to": message.to, "text": message.body, "type": "MMS" if message.attachments else "SMS"}
    if message.from_ or channel.address:
        payload["from"] = message.from_ or channel.address
    if channel.config.get("messaging_profile_id"):
        payload["messaging_profile_id"] = channel.config["messaging_profile_id"]
    if message.attachments:
        payload["media_urls"] = message.attachments
    if message.subject:
        payload["subject"] = message.subject
    if message.status_callback:
        payload["webhook_url"] = message.status_callback
    # ponytail: no idempotency header (Telnyx has none we rely on): the send job checks for an existing provider id
    data = transport.post(f"{base_url}/v2/messages", json=payload,
                          headers={"Authorization": f"Bearer {channel.secret('api_key')}"})
    if not (data.get("data") or {}).get("id"):
        raise ChannelError("Telnyx answered without a message id")
    return SendResult(data["data"]["id"])
