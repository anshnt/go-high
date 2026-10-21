"""Types shared by the channel adapters (ADR 0005). Library code: no database and no web framework, so the inbox
handler and the worker call it the same way.

A provider module exposes three functions:

    verify(channel, request) -> bool          is this webhook really from the provider (False when in doubt)
    parse(request) -> list[Inbound]           normalize its messages and status callbacks; ValueError on a bad body
    send(channel, message) -> SendResult      raises ChannelError, whose `retryable` says whether to try again

`Channel` is a `channels` row plus its decrypted secret; `Request` is the webhook as received."""
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime
from email import policy
from email.parser import BytesParser
from typing import Literal
from urllib.parse import parse_qsl, urlsplit

TOLERANCE = 300  # seconds a signed timestamp may differ from now


class ChannelError(Exception):
    """A send failed. `retryable` is True for timeouts, 429 and 5xx (try again later) and False for what a retry
    cannot fix: a rejected request, bad credentials, a refused address. `code` is the provider's own error code."""

    def __init__(self, message: str, retryable: bool = False, code: str = "", ambiguous: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.code = code
        # the request had been sent when it failed (no answer came back), so the provider may have accepted it: a
        # sender that must never send twice does not retry
        self.ambiguous = ambiguous


@dataclass
class Channel:
    """`config` is the row's public jsonb, `secrets` the decrypted `secret_ref` (never stored in `config`)."""
    address: str = ""  # sending number, email address or phone number id
    config: dict = field(default_factory=dict)
    secrets: dict = field(default_factory=dict)

    def conf(self, key: str) -> str:
        return self._need(self.config, key, "setting")

    def secret(self, key: str) -> str:
        return self._need(self.secrets, key, "secret")

    @staticmethod
    def _need(source: dict, key: str, what: str) -> str:
        value = source.get(key)
        if not value:
            raise ChannelError(f"the channel has no {what} {key!r}")
        return str(value)


@dataclass
class Request:
    """A webhook as received. `url` is the full URL the provider called, query included (behind a proxy, the public
    one). Headers are matched case-insensitively."""
    url: str
    headers: dict[str, str]
    body: bytes = b""
    method: str = "POST"

    def __post_init__(self):
        self.headers = {k.lower(): v for k, v in self.headers.items()}

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    def query(self) -> dict[str, str]:
        return dict(parse_qsl(urlsplit(self.url).query, keep_blank_values=True))

    def json_body(self) -> dict:
        data = json.loads(self.body)
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    def pairs(self) -> list[tuple[str, str]]:
        """Form fields in order, from a urlencoded or multipart body (file parts are skipped)."""
        ctype = self.header("content-type")
        if not ctype.startswith("multipart/"):
            return parse_qsl(self.body.decode("utf-8", "replace"), keep_blank_values=True)
        raw = b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + self.body  # a MIME entity for the email parser
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        out = []
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if isinstance(name, str) and part.get_filename() is None:
                out.append((name, (part.get_payload(decode=True) or b"").decode("utf-8", "replace")))
        return out

    def form(self) -> dict[str, str]:
        return dict(self.pairs())


@dataclass
class Template:
    """A WhatsApp template message: `params` fill the body variables {{1}}, {{2}}..."""
    name: str
    language: str = "en_US"
    params: list[str] = field(default_factory=list)


@dataclass
class Outbound:
    """One message to send. `from_` may be empty where the provider picks the sender (messaging service, profile).
    Email ids (`in_reply_to`, `references`) are Message-IDs with or without angle brackets."""
    to: str
    from_: str = ""
    body: str = ""
    subject: str | None = None
    html: str | None = None
    attachments: list[str] = field(default_factory=list)  # URLs
    reply_to: str | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    idempotency_key: str | None = None  # the message id: a retry must not send twice
    status_callback: str | None = None  # where the provider reports delivery (SMS)
    unsubscribe_url: str | None = None  # email: https URL for List-Unsubscribe
    headers: dict[str, str] = field(default_factory=dict)  # email: more headers (List-Id, Feedback-ID)
    dkim: tuple[str, str, str] | None = None  # email over SMTP: (domain, selector, private key PEM) to sign with
    template: Template | None = None  # WhatsApp: required outside the 24 hour window


@dataclass
class SendResult:
    provider_message_id: str  # email ids are stored without angle brackets


@dataclass
class Attachment:
    url: str = ""
    content_type: str = ""
    name: str = ""
    media_id: str = ""  # WhatsApp sends an id, not a URL: fetch it from the Graph API with the access token


@dataclass
class Inbound:
    """A received message (kind "message", status "received") or a delivery report (kind "status"). Statuses are
    queued, sent, delivered, read and failed; email also reports complained and unsubscribed, which are opt-out
    signals for the contact, not message states. Reports can arrive out of order: never move a message backwards.
    `thread_ref` is the provider id of the message this one replies to (email In-Reply-To, WhatsApp context)."""
    kind: Literal["message", "status"]
    provider_message_id: str
    from_: str = ""
    to: str = ""
    body: str = ""
    subject: str | None = None
    html: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    occurred_at: datetime | None = None
    thread_ref: str | None = None
    status: str | None = None
    error: str | None = None


def same(a: str, b: str) -> bool:
    """Constant-time comparison of two strings (any characters)."""
    return hmac.compare_digest(a.encode(), b.encode())
