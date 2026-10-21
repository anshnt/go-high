"""The signed tokens in a marketing email's links: unsubscribe and preferences, the open pixel and each click. A token
names one send (and, for a click, the number of one of the campaign's links) and is signed with HMAC-SHA256 under a
key derived from SECRET_KEY for this purpose only, so it cannot be forged, edited or moved to another send, link or
workspace. It never expires: an unsubscribe link must keep working for as long as the mail sits in someone's inbox.
Nothing in a token is secret beyond the signature; it holds no address and no workspace."""
import base64
import hashlib
import hmac
import struct
import uuid
from typing import Literal, NamedTuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .. import config

KINDS = {"unsubscribe": 1, "open": 2, "click": 3}
NAMES = {v: k for k, v in KINDS.items()}
MAC = 16  # bytes of the HMAC kept: 128 bits
Kind = Literal["unsubscribe", "open", "click"]


class Token(NamedTuple):
    kind: Kind
    send_id: uuid.UUID
    link: int  # the link's number for a click, else 0


def key() -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"go-high email links v1").derive(
        config.SECRET_KEY.encode())


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def make(kind: Kind, send_id: uuid.UUID, link: int = 0) -> str:
    body = send_id.bytes + struct.pack(">BH", KINDS[kind], link)
    return b64(body + hmac.new(key(), body, hashlib.sha256).digest()[:MAC])


def read(token: str, kind: Kind) -> Token | None:
    """The token's contents when it is genuine and of `kind`; None for anything else (never an exception)."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, TypeError):
        return None
    if len(raw) != 19 + MAC or len(token) > 64:
        return None
    body, mac = raw[:19], raw[19:]
    if not hmac.compare_digest(mac, hmac.new(key(), body, hashlib.sha256).digest()[:MAC]):
        return None
    code, link = struct.unpack(">BH", body[16:])
    if NAMES.get(code) != kind:
        return None
    return Token(kind, uuid.UUID(bytes=body[:16]), link)


def origin() -> str:
    return config.ALLOWED_ORIGINS[0]


def unsubscribe_url(send_id: uuid.UUID) -> str:
    """The List-Unsubscribe address: GET shows the preference page, POST is RFC 8058's one-click unsubscribe."""
    return f"{origin()}/api/public/email/u/{make('unsubscribe', send_id)}"


def preferences_url(send_id: uuid.UUID) -> str:
    return f"{origin()}/api/public/email/u/{make('unsubscribe', send_id)}?view=preferences"


def open_url(send_id: uuid.UUID) -> str:
    return f"{origin()}/api/public/email/o/{make('open', send_id)}.gif"


def click_url(send_id: uuid.UUID, link: int) -> str:
    return f"{origin()}/api/public/email/c/{make('click', send_id, link)}"
