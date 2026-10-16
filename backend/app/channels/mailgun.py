"""Mailgun email: HTTP API sends, webhook signatures, inbound routes and delivery events.

channel.address: the From address. config: domain (the Mailgun sending domain), region ("us" or "eu"),
message_id_domain (default: the sending domain). secrets: api_key, signing_key (the webhook signing key, which is not
the API key). The route that feeds inbound mail should be store(notify=...) or forward(...); a forward() route sends
attachments as file parts, which `parse` does not read, while store() sends their list as JSON."""
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import quote

from . import mail, transport
from .base import TOLERANCE, Attachment, Channel, ChannelError, Inbound, Outbound, Request, SendResult, same

REGIONS = {"us": "https://api.mailgun.net", "eu": "https://api.eu.mailgun.net"}
STATUS = {"accepted": "sent", "delivered": "delivered", "rejected": "failed", "complained": "complained",
          "unsubscribed": "unsubscribed"}


def signed_fields(request: Request) -> tuple[str, str, str]:
    """(timestamp, token, signature): in the JSON body of an event webhook, in the form of an inbound route."""
    if "json" in request.header("content-type"):
        s = request.json_body().get("signature")
        s = s if isinstance(s, dict) else {}
    else:
        s = request.form()
    return str(s.get("timestamp", "")), str(s.get("token", "")), str(s.get("signature", ""))


def verify(channel: Channel, request: Request, now: float | None = None) -> bool:
    """HMAC-SHA256 of timestamp + token under the signing key. A timestamp more than 5 minutes off is refused.
    ponytail: tokens are not remembered, so a captured webhook can be replayed for 5 minutes; every provider id is
    unique per channel, so a replay changes nothing."""
    key = channel.secrets.get("signing_key")
    try:
        stamp, token, given = signed_fields(request)
        if not key or not stamp or not given or abs((time.time() if now is None else now) - int(stamp)) > TOLERANCE:
            return False
    except ValueError:  # not JSON, or a timestamp that is not a number
        return False
    return same(given, hmac.new(key.encode(), (stamp + token).encode(), hashlib.sha256).hexdigest())


def header(f: dict[str, str], name: str) -> str:
    """A mail header from an inbound route: a field of its own, or an entry of the message-headers JSON list."""
    for key, value in f.items():
        if key.lower() == name.lower():
            return value
    try:
        return next((v for k, v in json.loads(f.get("message-headers") or "[]") if k.lower() == name.lower()), "")
    except (ValueError, TypeError):
        return ""


def inbound_message(f: dict[str, str]) -> Inbound:
    sent = header(f, "Date")
    try:
        when = parsedate_to_datetime(sent) if sent else datetime.fromtimestamp(float(f["timestamp"]), UTC)
    except (TypeError, ValueError, KeyError):
        when = datetime.now(UTC)
    when = when if when.tzinfo else when.replace(tzinfo=UTC)
    try:
        listed = json.loads(f.get("attachments") or "[]")
    except ValueError:
        listed = []
    files = [Attachment(url=a.get("url", ""), content_type=a.get("content-type", ""), name=a.get("name", ""))
             for a in listed if isinstance(a, dict)]
    references = header(f, "References").split()
    return Inbound("message", mail.bare_id(header(f, "Message-Id")), parseaddr(f.get("from") or f.get("sender", ""))[1],
                   f.get("recipient", ""), f.get("stripped-text") or f.get("body-plain", ""), f.get("subject") or None,
                   f.get("stripped-html") or f.get("body-html") or None, files, when,
                   mail.bare_id(header(f, "In-Reply-To") or (references[-1] if references else "")) or None,
                   "received")


def event(data: dict) -> list[Inbound]:
    e = data.get("event-data") or {}
    headers = (e.get("message") or {}).get("headers") or {}
    if not headers.get("message-id"):
        return []
    status = STATUS.get(e.get("event", ""))
    if e.get("event") == "failed":
        status = "failed" if e.get("severity") == "permanent" else None  # a temporary failure is retried by Mailgun
    if status is None:
        return []
    delivery = e.get("delivery-status") or {}
    reason = (delivery.get("description") or delivery.get("message") or (e.get("reject") or {}).get("reason")
              or e.get("reason"))
    error = " ".join(filter(None, (str(delivery.get("code") or ""), reason))) if status == "failed" else None
    return [Inbound("status", mail.bare_id(headers["message-id"]), headers.get("from", ""), e.get("recipient", ""),
                    occurred_at=datetime.fromtimestamp(float(e.get("timestamp") or time.time()), UTC), status=status,
                    error=error or None)]


def parse(request: Request) -> list[Inbound]:
    if "json" in request.header("content-type"):
        return event(request.json_body())
    f = request.form()
    if not header(f, "Message-Id"):
        raise ValueError("no Message-Id")
    return [inbound_message(f)]


def send(channel: Channel, message: Outbound, *, base_url: str | None = None) -> SendResult:
    base = base_url or REGIONS.get(channel.config.get("region", "us"))
    if not base:
        raise ChannelError('region must be "us" or "eu"')
    domain = channel.conf("domain")
    mid = mail.message_id(channel.config.get("message_id_domain") or domain, message.idempotency_key)
    form = [("from", message.from_ or channel.address), ("to", message.to), ("subject", message.subject or ""),
            ("text", message.body or (mail.plain_text(message.html) if message.html else "")),
            ("h:Message-Id", f"<{mid}>")]
    if message.html:
        form.append(("html", message.html))
    if message.reply_to:
        form.append(("h:Reply-To", message.reply_to))
    parent, refs = mail.thread(message)
    if parent:
        form.append(("h:In-Reply-To", f"<{parent}>"))
    if refs:
        form.append(("h:References", " ".join(f"<{r}>" for r in refs)))
    if message.unsubscribe_url:
        form.append(("h:List-Unsubscribe", f"<{message.unsubscribe_url}>"))
        if message.unsubscribe_url.startswith("https://"):
            form.append(("h:List-Unsubscribe-Post", "List-Unsubscribe=One-Click"))
    files = [("attachment", name, ctype, data) for name, ctype, data in mail.fetch(message.attachments)]
    data = transport.post(f"{base}/v3/{quote(domain, safe='')}/messages", form=form, files=files,
                          headers={"Authorization": transport.basic("api", channel.secret("api_key"))})
    if not data.get("id"):
        raise ChannelError("Mailgun answered without a message id")
    return SendResult(mail.bare_id(data["id"]))
