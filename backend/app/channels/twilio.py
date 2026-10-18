"""Twilio SMS and MMS: Messages REST API, X-Twilio-Signature, inbound messages and status callbacks.

channel.address: the sending number. config: account_sid, messaging_service_sid (optional, replaces the number).
secrets: auth_token."""
import base64
import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import quote

from . import transport
from .base import Attachment, Channel, ChannelError, Inbound, Outbound, Request, SendResult, same

API = "https://api.twilio.com"
STATUS = {"accepted": "queued", "scheduled": "queued", "queued": "queued", "sending": "queued", "sent": "sent",
          "delivered": "delivered", "read": "read", "undelivered": "failed", "failed": "failed", "canceled": "failed"}


def signature(token: str, url: str, pairs: list[tuple[str, str]]) -> str:
    """base64 HMAC-SHA1 over the full URL followed by every POST parameter, names sorted, as name then value."""
    params: dict[str, set[str]] = {}
    for name, value in pairs:
        params.setdefault(name, set()).add(value)
    data = url + "".join(name + value for name in sorted(params) for value in sorted(params[name]))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def verify(channel: Channel, request: Request, public_url: str | None = None) -> bool:
    """Twilio signs the URL it called. Behind a proxy `request.url` is the internal one, so pass the URL as it is
    configured in the Twilio console (scheme, host, port if any, path and query) as `public_url`."""
    token, given = channel.secrets.get("auth_token"), request.header("x-twilio-signature")
    if not token or not given:
        return False
    return same(given, signature(token, public_url or request.url, request.pairs()))


def parse(request: Request) -> list[Inbound]:
    f = request.form()
    sid = f.get("MessageSid") or f.get("SmsSid")
    if not sid:
        raise ValueError("no MessageSid")
    now = datetime.now(UTC)  # ponytail: Twilio sends no timestamp with either callback, so receipt time stands in
    if "MessageStatus" in f:
        status = STATUS.get(f["MessageStatus"])
        if status is None:
            return []
        error = " ".join(filter(None, (f.get("ErrorCode"), f.get("ErrorMessage")))) or None
        return [Inbound("status", sid, f.get("From", ""), f.get("To", ""), occurred_at=now, status=status, error=error)]
    media = [Attachment(url=f[f"MediaUrl{i}"], content_type=f.get(f"MediaContentType{i}", ""))
             for i in range(int(f.get("NumMedia") or 0)) if f.get(f"MediaUrl{i}")]
    return [Inbound("message", sid, f.get("From", ""), f.get("To", ""), f.get("Body", ""), attachments=media,
                    occurred_at=now, status="received")]


def check(channel: Channel, *, base_url: str = API) -> str:
    """Reads the account with the credentials: a wrong SID or token is refused by Twilio."""
    sid = channel.conf("account_sid")
    transport.get(f"{base_url}/2010-04-01/Accounts/{quote(sid, safe='')}.json",
                  headers={"Authorization": transport.basic(sid, channel.secret("auth_token"))})
    return "Twilio accepted the account SID and auth token"


def send(channel: Channel, message: Outbound, *, base_url: str = API) -> SendResult:
    sid = channel.conf("account_sid")
    form = [("To", message.to), ("Body", message.body)]
    if channel.config.get("messaging_service_sid"):
        form.append(("MessagingServiceSid", channel.config["messaging_service_sid"]))
    else:
        form.append(("From", message.from_ or channel.address))
    form += [("MediaUrl", url) for url in message.attachments]
    if message.status_callback:
        form.append(("StatusCallback", message.status_callback))
    headers = {"Authorization": transport.basic(sid, channel.secret("auth_token"))}
    if message.idempotency_key:
        headers["I-Twilio-Idempotency-Token"] = message.idempotency_key
    data = transport.post(f"{base_url}/2010-04-01/Accounts/{quote(sid, safe='')}/Messages.json", form=form,
                          headers=headers)
    if not data.get("sid"):
        raise ChannelError("Twilio answered without a message sid")
    return SendResult(data["sid"])
