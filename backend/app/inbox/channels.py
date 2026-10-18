"""Channels API (ADR 0005): the messaging accounts of a workspace. Workspace admins create, edit, disable and test
them; any member lists them to pick a sender. Settings are public (`config`); API keys and passwords are `secrets`,
which can be written but are never returned (see `vault`). `webhook_url` is what to paste into the provider's
console."""
import re
import secrets as token
import uuid
from datetime import time
from decimal import Decimal, InvalidOperation
from email.utils import parseaddr
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select

from .. import compliance, config, events
from ..api import ApiError, Idem, idempotency, paginate
from ..channels.base import ChannelError
from ..security import Ctx, in_workspace, workspace_admin
from . import gateway, vault
from .models import Channel

router = APIRouter(prefix="/api/v1/channels")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# provider: (kind, settings, required settings, secrets, required secrets); every secret is write-only
SPECS = {
    "twilio": ("sms", ("account_sid", "messaging_service_sid"), ("account_sid",), ("auth_token",), ("auth_token",)),
    "telnyx": ("sms", ("public_key", "messaging_profile_id"), ("public_key",), ("api_key",), ("api_key",)),
    "smtp": ("email", ("host", "port", "security", "username", "message_id_domain"), ("host",), ("password",), ()),
    "ses": ("email", ("host", "port", "security", "username", "message_id_domain"), ("host",), ("password",), ()),
    "mailgun": ("email", ("domain", "region", "message_id_domain"), ("domain",), ("api_key", "signing_key"),
                ("api_key", "signing_key")),
    "meta": ("whatsapp", ("phone_number_id",), ("phone_number_id",), ("access_token", "app_secret", "verify_token"),
             ("access_token", "app_secret", "verify_token")),
    "internal": ("webchat", ("title", "greeting", "color"), (), (), ()),
}
SHARED = ("segment_cost", "quiet_start", "quiet_end", "frequency_cap", "auto_replies", "reply_to")
HOOKS = ("twilio", "telnyx", "mailgun", "meta")  # the providers that call us
PHONE = re.compile(r"\+[1-9]\d{6,14}")


class NewChannel(BaseModel):
    kind: Literal["sms", "email", "webchat", "whatsapp"]
    provider: Literal["twilio", "telnyx", "smtp", "ses", "mailgun", "meta", "internal"]
    name: Name
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] = ""
    config: dict[str, Any] = {}
    secrets: dict[Annotated[str, Field(max_length=64)], Annotated[str, Field(max_length=4000)] | None] = {}


class PatchChannel(BaseModel):
    name: Name | None = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] | None = None
    config: dict[str, Any] | None = None  # merged into the settings; a null value removes one
    secrets: dict[Annotated[str, Field(max_length=64)], Annotated[str, Field(max_length=4000)] | None] | None = None
    status: Literal["active", "disabled"] | None = None


class Estimate(BaseModel):
    body: Annotated[str, Field(max_length=10000)]


def invalid(fields: dict[str, str]) -> ApiError:
    return ApiError(422, "validation_failed", "The channel is not valid", fields)


def check_setting(key: str, value) -> str | None:
    """What is wrong with one setting's value, or None."""
    try:
        if key == "port" and not 0 < int(value) < 65536:
            return "must be a port number"
        if key == "segment_cost" and Decimal(str(value)) < 0:
            return "must not be negative"
        if key in ("quiet_start", "quiet_end"):
            time.fromisoformat(str(value))
        if key == "frequency_cap" and not (isinstance(value, dict) and set(value) == {"max", "hours"}
                                           and int(value["max"]) >= 0 and 0 < int(value["hours"]) <= 720):
            return 'must be {"max": messages, "hours": 1 to 720}'
        if key == "auto_replies" and not (isinstance(value, dict) and set(value) <= {"stop", "start", "help"}
                                          and all(isinstance(v, str) and len(v) <= 320 for v in value.values())):
            return "must map stop, start and help to texts of at most 320 characters"
    except (ValueError, TypeError, InvalidOperation, KeyError):
        return "is not a valid value"
    if key not in ("frequency_cap", "auto_replies") and not isinstance(value, str | int | float):
        return "must be text or a number"
    if isinstance(value, str) and len(value) > 500:
        return "is too long"
    return None


def validate(provider: str, kind: str, address: str, settings: dict, secret_keys: set[str] | None = None) -> None:
    """Raises a 422 naming every problem. `secret_keys` are the secrets the channel will hold (None: not checked)."""
    spec_kind, allowed, required, secret_names, required_secrets = SPECS[provider]
    errors: dict[str, str] = {}
    if kind != spec_kind:
        errors["kind"] = f"{provider} is for {spec_kind} channels"
    for key, value in settings.items():
        if key not in allowed + SHARED:
            errors[f"config.{key}"] = "is not a setting of this provider"
        elif problem := check_setting(key, value):
            errors[f"config.{key}"] = problem
    for key in required:
        if not settings.get(key):
            errors[f"config.{key}"] = "is required"
    if kind in ("sms", "whatsapp") and address and not PHONE.fullmatch(address):
        errors["address"] = "must be a phone number in E.164 form, like +14155550123"
    if kind == "sms" and not address and not settings.get("messaging_service_sid"):
        errors["address"] = "is required (or a messaging service SID)"
    if kind == "email" and "@" not in parseaddr(address)[1]:
        errors["address"] = "must be the sending email address"
    if secret_keys is not None:
        needed = set(required_secrets) | ({"password"} if settings.get("username") else set())
        errors |= {f"secrets.{k}": "is required" for k in sorted(needed - secret_keys)}
        errors |= {f"secrets.{k}": "is not a secret of this provider" for k in sorted(secret_keys - set(secret_names))}
    if errors:
        raise invalid(errors)


def estimate(channel: Channel, body: str) -> dict:
    """Segments and estimated cost of an SMS body: the channel's `segment_cost` per segment (default 0)."""
    encoding, segments, chars = compliance.sms_segments(body)
    cost = (Decimal(str(channel.config.get("segment_cost", 0))) * segments).quantize(Decimal("0.000001"))
    return {"encoding": encoding, "segments": segments, "chars": chars, "estimated_cost": str(cost)}


def channel_json(ch: Channel, admin: bool = False) -> dict:
    out = {"id": ch.id, "kind": ch.kind, "provider": ch.provider, "name": ch.name, "address": ch.address,
           "status": ch.status, "status_detail": ch.status_detail, "created_at": ch.created_at,
           "updated_at": ch.updated_at}
    if ch.kind == "webchat":
        out["widget_key"] = ch.address
    if admin:
        out["config"], out["secrets_set"] = ch.config, ch.secret_ref is not None
        out["webhook_url"] = gateway.hook_url(ch) if ch.provider in HOOKS else None
        if ch.kind == "webchat":
            origin = config.ALLOWED_ORIGINS[0]
            out["embed"] = f'<script src="{origin}/widget.js" data-key="{ch.address}" async></script>'
    return out


def event_data(ch: Channel) -> dict:
    return {"id": ch.id, "kind": ch.kind, "provider": ch.provider, "name": ch.name, "address": ch.address,
            "status": ch.status}


def channel_or_404(c: Ctx, channel_id: uuid.UUID) -> Channel:
    ch = c.db.get(Channel, channel_id)  # row level security: this workspace's channels only
    if ch is None:
        raise HTTPException(404, "Channel not found")
    return ch


@router.post("", status_code=201)
def create_channel(body: NewChannel, c: Ctx = Depends(workspace_admin), idem: Idem = Depends(idempotency)):
    given = {k: v for k, v in body.secrets.items() if v is not None}
    webchat = body.kind == "webchat"
    address = f"wk_{token.token_urlsafe(16)}" if webchat else body.address
    validate(body.provider, body.kind, address, body.config, set(given))
    ref = vault.put(c.db, c.workspace.id, given) if given else None
    ch = Channel(workspace_id=c.workspace.id, kind=body.kind, provider=body.provider, name=body.name, address=address,
                 config=body.config, secret_ref=ref, status="active" if webchat else "pending", created_by=c.user_id)
    c.db.add(ch)
    c.db.flush()
    c.db.refresh(ch, ["created_at", "updated_at"])
    events.emit(c.db, "channel.created", "channel", ch.id, event_data(ch), actor=("user", c.user_id))
    return idem.commit(201, channel_json(ch, admin=True))


@router.get("")
def list_channels(status: Literal["active", "pending", "failing", "disabled"] | None = None,
                  limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(in_workspace)):
    stmt = select(Channel)
    if status:
        stmt = stmt.where(Channel.status == status)
    rows, next_cursor = paginate(c.db, stmt, Channel, limit, cursor)
    admin = c.workspace_role == "admin"
    return {"data": [channel_json(row[0], admin) for row in rows], "next_cursor": next_cursor}


@router.get("/{channel_id}")
def get_channel(channel_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    return channel_json(channel_or_404(c, channel_id), c.workspace_role == "admin")


@router.patch("/{channel_id}")
def update_channel(channel_id: uuid.UUID, body: PatchChannel, c: Ctx = Depends(workspace_admin)):
    ch = channel_or_404(c, channel_id)
    sent = body.model_fields_set
    settings = {k: v for k, v in {**ch.config, **(body.config or {})}.items() if v is not None}
    address = ch.address if body.address is None or ch.kind == "webchat" else body.address
    held = None
    if body.secrets is not None:
        held = {k for k, v in {**vault.of(ch), **body.secrets}.items() if v is not None}
    validate(ch.provider, ch.kind, address, settings, held)
    changed = []
    if body.name is not None and body.name != ch.name:
        ch.name = body.name
        changed.append("name")
    if address != ch.address:
        ch.address = address
        changed.append("address")
    if "config" in sent and settings != ch.config:
        ch.config = settings
        changed.append("config")
    if body.secrets:
        ch.secret_ref = vault.put(c.db, c.workspace.id, body.secrets, ch.secret_ref)
        changed.append("secrets")
    if body.status and body.status != ch.status and (body.status == "disabled" or ch.status == "disabled"):
        ch.status, ch.status_detail = ("disabled", "Disabled by an admin") if body.status == "disabled" else (
            "pending" if ch.kind != "webchat" else "active", None)
        changed.append("status")
    if changed:
        ch.updated_at = func.now()
        c.db.flush()
        c.db.refresh(ch, ["updated_at"])
        events.emit(c.db, "channel.updated", "channel", ch.id, {**event_data(ch), "changed": changed},
                    actor=("user", c.user_id))
    c.db.commit()
    return channel_json(ch, admin=True)


@router.post("/{channel_id}/test")
def test_channel(channel_id: uuid.UUID, c: Ctx = Depends(workspace_admin)):
    """Asks the provider to accept the saved credentials, where its adapter can check them. A refusal marks the
    channel failing; an acceptance makes it active. The answer is `{"ok": bool, "detail": text}`."""
    ch = channel_or_404(c, channel_id)
    c.db.commit()  # the provider call must not run inside an open transaction
    try:
        detail, ok = gateway.check(ch), True
    except ChannelError as e:
        detail, ok = str(e), False
    if detail is None:
        return {"ok": True, "detail": "This channel has nothing to connect to"}
    if ch.status != "disabled":
        ch.status, ch.status_detail = ("active", None) if ok else ("failing", detail[:300])
        c.db.commit()
    return {"ok": ok, "detail": detail}


@router.post("/{channel_id}/estimate")
def estimate_message(channel_id: uuid.UUID, body: Estimate, c: Ctx = Depends(in_workspace)):
    """Segments and estimated cost of a text, for the composer while typing."""
    return estimate(channel_or_404(c, channel_id), body.body)
