"""Helpers for the inbox tests: channels through the API, webhooks signed the way each provider signs them (the
signatures are generated here, from the same documented rules the adapters verify), and message queries."""
import base64
import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlencode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from helpers import H
from sqlalchemy import text

from app import config
from app.channels import twilio
from app.inbox import gateway

TWILIO_TOKEN = "test-auth-token-not-real"
TELNYX_KEY = Ed25519PrivateKey.generate()
MAILGUN_SIGNING_KEY = "test-signing-key-not-real"
META_SECRET = "test-app-secret-not-real"
META_VERIFY_TOKEN = "test-verify-token-not-real"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def raw_public_key(key=TELNYX_KEY) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


CHANNELS = {
    "twilio": dict(kind="sms", provider="twilio", name="Main line", address="+15550001111",
                   config={"account_sid": "AC" + "a" * 32}, secrets={"auth_token": TWILIO_TOKEN}),
    "telnyx": dict(kind="sms", provider="telnyx", name="Telnyx line", address="+15550002222",
                   config={"public_key": raw_public_key()}, secrets={"api_key": "test-api-key-not-real"}),
    "mailgun": dict(kind="email", provider="mailgun", name="Support mail", address="hello@mg.example.com",
                    config={"domain": "mg.example.com"},
                    secrets={"api_key": "test-api-key-not-real", "signing_key": MAILGUN_SIGNING_KEY}),
    "meta": dict(kind="whatsapp", provider="meta", name="WhatsApp", address="+15550003333",
                 config={"phone_number_id": "106540352242922"},
                 secrets={"access_token": "test-access-token-not-real", "app_secret": META_SECRET,
                          "verify_token": META_VERIFY_TOKEN}),
    "internal": dict(kind="webchat", provider="internal", name="Website chat"),
}


def add_channel(client, ws, provider: str = "twilio", **over) -> dict:
    r = client.post("/api/v1/channels", json={**CHANNELS[provider], **over}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def path_of(channel: dict) -> str:
    return f"/api/hooks/{channel['provider']}/{channel['id']}"


def public_url(channel: dict) -> str:
    return config.ALLOWED_ORIGINS[0] + path_of(channel)


def twilio_hook(client, channel: dict, token: str = TWILIO_TOKEN, **fields):
    pairs = list(fields.items())
    headers = {**FORM, "X-Twilio-Signature": twilio.signature(token, public_url(channel), pairs)}
    return client.post(path_of(channel), content=urlencode(pairs), headers=headers)


def sms_in(client, channel: dict, sender: str, body: str, sid: str | None = None, **more):
    return twilio_hook(client, channel, MessageSid=sid or f"SM{uuid.uuid4().hex}", From=sender, To=channel["address"],
                       Body=body, NumMedia="0", **more)


def sms_status(client, channel: dict, sid: str, status: str, **more):
    return twilio_hook(client, channel, MessageSid=sid, MessageStatus=status, From=channel["address"],
                       To="+14155550123", **more)


def telnyx_hook(client, channel: dict, body: dict, key=TELNYX_KEY, stamp: int | None = None):
    raw = json.dumps(body).encode()
    stamp = str(int(time.time()) if stamp is None else stamp)
    headers = {"Content-Type": "application/json", "Telnyx-Timestamp": stamp,
               "Telnyx-Signature-Ed25519": base64.b64encode(key.sign(stamp.encode() + b"|" + raw)).decode()}
    return client.post(path_of(channel), content=raw, headers=headers)


def telnyx_in(sender: str, to: str, text_: str, msg_id: str | None = None) -> dict:
    return {"data": {"event_type": "message.received", "occurred_at": "2026-10-17T11:10:19.104+00:00", "payload": {
        "id": msg_id or str(uuid.uuid4()), "direction": "inbound", "type": "SMS", "from": {"phone_number": sender},
        "to": [{"phone_number": to}], "text": text_, "media": [], "received_at": "2026-10-17T11:10:18.822+00:00"}}}


def mailgun_sig(stamp: str, token: str, key: str = MAILGUN_SIGNING_KEY) -> str:
    return hmac.new(key.encode(), (stamp + token).encode(), hashlib.sha256).hexdigest()


def mailgun_in(client, channel: dict, sender: str, subject: str, body: str, message_id: str | None = None,
               in_reply_to: str | None = None, key: str = MAILGUN_SIGNING_KEY):
    stamp, token = str(int(time.time())), uuid.uuid4().hex
    fields = {"recipient": channel["address"], "sender": sender, "from": f"Someone <{sender}>", "subject": subject,
              "body-plain": body, "stripped-text": body, "Message-Id": f"<{message_id or uuid.uuid4().hex}@mail.test>",
              "Date": "Fri, 17 Oct 2026 10:30:00 +0000", "timestamp": stamp, "token": token,
              "signature": mailgun_sig(stamp, token, key)}
    if in_reply_to:
        fields["In-Reply-To"] = f"<{in_reply_to}>"
    return client.post(path_of(channel), content=urlencode(fields), headers=FORM)


def mailgun_event(client, channel: dict, event: str, message_id: str, **more):
    stamp, token = str(int(time.time())), uuid.uuid4().hex
    data = {"signature": {"timestamp": stamp, "token": token, "signature": mailgun_sig(stamp, token)},
            "event-data": {"event": event, "timestamp": time.time(), "recipient": "bob@example.net",
                           "message": {"headers": {"message-id": message_id}}, **more}}
    return client.post(path_of(channel), json=data)


def meta_hook(client, channel: dict, body: dict, secret: str = META_SECRET):
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json",
               "X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()}
    return client.post(path_of(channel), content=raw, headers=headers)


def meta_in(sender: str, body: str, wamid: str | None = None) -> dict:
    message = {"from": sender, "id": wamid or f"wamid.{uuid.uuid4().hex}", "timestamp": "1760697000", "type": "text",
               "text": {"body": body}}
    value = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550003333"},
             "messages": [message]}
    changes = [{"field": "messages", "value": value}]
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": changes}]}


def conversations_of(client, ws, **params) -> dict:
    r = client.get("/api/v1/conversations", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def conversation(client, ws, conv_id: str) -> dict:
    r = client.get(f"/api/v1/conversations/{conv_id}", headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def only_conversation(client, ws, **params) -> dict:
    page = conversations_of(client, ws, **params)
    assert len(page["data"]) == 1, page
    return page["data"][0]


def bodies(client, ws, conv_id: str, **params) -> list[str]:
    """Message bodies of a conversation, oldest first."""
    r = client.get(f"/api/v1/conversations/{conv_id}/messages", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return [m["body"] for m in reversed(r.json()["data"])]


def sql(db, query: str, **params):
    db.rollback()  # see what the application committed
    return db.execute(text(query), params).all()


def point(monkeypatch, receiver, provider: str, reply: str = "{}") -> None:
    """Sends through `provider` to the local receiver, which answers each request with `reply`; a `%d` in it is
    the request's number, so every message gets a provider id of its own."""
    monkeypatch.setitem(gateway.BASE_URLS, provider, receiver.url(""))
    receiver.replies = [(200, (reply % i if "%d" in reply else reply).encode(), {}) for i in range(60)]


def outbound_row(db, conv_id: str, channel_id: str, provider_id: str, status: str = "sent", body: str = "reply") -> str:
    """A reply the provider already accepted, put in the conversation as the send job would leave it."""
    db.rollback()
    message = db.scalar(text(
        "INSERT INTO messages (workspace_id, conversation_id, seq, direction, channel_id, kind, body, status, "
        "provider_message_id) SELECT workspace_id, id, last_seq + 1, 'out', :ch, 'message', :body, :st, :pid "
        "FROM conversations WHERE id = :c RETURNING id"), {"ch": channel_id, "body": body, "st": status,
                                                            "pid": provider_id, "c": conv_id})
    db.execute(text("UPDATE conversations SET last_seq = last_seq + 1 WHERE id = :c"), {"c": conv_id})
    db.commit()
    return str(message)


def message_status(db, message_id: str) -> tuple[str, str | None]:
    return tuple(sql(db, "SELECT status, error FROM messages WHERE id = :m", m=message_id)[0])
