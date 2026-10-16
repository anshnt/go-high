import base64
import json
import time
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.channels import telnyx
from app.channels.base import Channel, ChannelError, Outbound, Request

KEY = Ed25519PrivateKey.generate()


def public_key(key=KEY) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


CHANNEL = Channel(address="+15550001111", config={"public_key": public_key()}, secrets={"api_key": "KEY01_secret"})


def signed(body: bytes, stamp: int | None = None, key=KEY) -> Request:
    stamp = str(int(time.time()) if stamp is None else stamp)
    signature = base64.b64encode(key.sign(stamp.encode() + b"|" + body)).decode()
    return Request("https://x.test/h", {"telnyx-signature-ed25519": signature, "telnyx-timestamp": stamp,
                                        "content-type": "application/json"}, body)


RECEIVED = json.dumps({"data": {
    "event_type": "message.received", "id": "19e10b4b-4e0f-4f66-a2cc-4e4a1a3c4f52",
    "occurred_at": "2026-10-17T11:10:19.104+00:00",
    "payload": {
        "id": "b301ed3d-7ba8-44f7-9d2a-1d21c5b9f9c1", "record_type": "message", "direction": "inbound", "type": "SMS",
        "from": {"phone_number": "+13125550001", "carrier": "T-Mobile USA", "line_type": "Wireless"},
        "to": [{"phone_number": "+15550001111", "status": "webhook_delivered", "carrier": "Telnyx",
                "line_type": "Wireless"}],
        "text": "Hello from a phone", "media": [], "received_at": "2026-10-17T11:10:18.822+00:00", "completed_at": None,
        "errors": [], "messaging_profile_id": "40017f2b-0000-0000-0000-000000000000"},
    "record_type": "event"},
    "meta": {"attempt": 1, "delivered_to": "https://app.example.com/api/hooks/telnyx/abc"}}).encode()


def finalized(status: str, errors: list | None = None) -> bytes:
    return json.dumps({"data": {
        "event_type": "message.finalized", "id": "e2a1", "occurred_at": "2026-10-17T11:12:00.000+00:00",
        "payload": {"id": "msg-out-1", "direction": "outbound", "type": "SMS", "from": {"phone_number": "+15550001111"},
                    "to": [{"phone_number": "+13125550001", "status": status, "carrier": "AT&T"}], "text": "Hi",
                    "completed_at": "2026-10-17T11:11:59.500+00:00", "errors": errors or []},
        "record_type": "event"}, "meta": {"attempt": 1}}).encode()


def test_a_correctly_signed_request_verifies():
    assert telnyx.verify(CHANNEL, signed(RECEIVED))


def test_a_changed_body_or_timestamp_or_key_is_refused():
    good = signed(RECEIVED)
    assert not telnyx.verify(CHANNEL, Request(good.url, good.headers, RECEIVED.replace(b"Hello", b"Hullo")))
    assert not telnyx.verify(CHANNEL, Request(good.url, {**good.headers, "telnyx-timestamp": str(int(time.time()) + 1)},
                                              RECEIVED))
    assert not telnyx.verify(Channel(config={"public_key": public_key(Ed25519PrivateKey.generate())}), good)
    assert not telnyx.verify(CHANNEL, signed(RECEIVED, key=Ed25519PrivateKey.generate()))


def test_old_timestamps_are_refused_even_with_a_valid_signature():
    now = 1_800_000_000
    assert telnyx.verify(CHANNEL, signed(RECEIVED, now - 299), now=now)
    assert telnyx.verify(CHANNEL, signed(RECEIVED, now - 300), now=now)
    assert not telnyx.verify(CHANNEL, signed(RECEIVED, now - 301), now=now)
    assert not telnyx.verify(CHANNEL, signed(RECEIVED, now - 3600), now=now)  # replayed an hour later
    assert not telnyx.verify(CHANNEL, signed(RECEIVED, now + 301), now=now)
    assert not telnyx.verify(CHANNEL, signed(RECEIVED, int(time.time()) - 400))  # the real clock by default


@pytest.mark.parametrize("headers", [
    {}, {"telnyx-timestamp": "1"}, {"telnyx-signature-ed25519": "AAAA"},
    {"telnyx-signature-ed25519": "!!!", "telnyx-timestamp": "1800000000"},
    {"telnyx-signature-ed25519": "AAAA", "telnyx-timestamp": "yesterday"},
    {"telnyx-signature-ed25519": "AAAA", "telnyx-timestamp": "1800000000"},
])
def test_missing_or_garbled_signature_headers_are_refused(headers):
    assert not telnyx.verify(CHANNEL, Request("u", headers, RECEIVED), now=1_800_000_000)


@pytest.mark.parametrize("config", [{}, {"public_key": ""}, {"public_key": "not base64!"}, {"public_key": "AAAA"}])
def test_a_missing_or_broken_public_key_refuses_everything(config):
    assert not telnyx.verify(Channel(config=config), signed(RECEIVED))


def test_parse_message_received():
    [m] = telnyx.parse(Request("u", {}, RECEIVED))
    assert (m.kind, m.status, m.provider_message_id) == ("message", "received", "b301ed3d-7ba8-44f7-9d2a-1d21c5b9f9c1")
    assert (m.from_, m.to, m.body, m.subject, m.attachments) == ("+13125550001", "+15550001111", "Hello from a phone",
                                                                 None, [])
    assert m.occurred_at == datetime(2026, 10, 17, 11, 10, 18, 822000, tzinfo=UTC)


def test_parse_an_mms_with_media():
    event = json.loads(RECEIVED)
    event["data"]["payload"].update(type="MMS", text="", subject="Photo", media=[
        {"url": "https://media.telnyx.com/a.jpg?sig=1", "content_type": "image/jpeg", "size": 2048, "sha256": "x"},
        {"url": "https://media.telnyx.com/b.pdf", "content_type": "application/pdf", "size": None, "sha256": None}])
    [m] = telnyx.parse(Request("u", {}, json.dumps(event).encode()))
    assert m.body == "" and m.subject == "Photo"
    assert [(a.url, a.content_type) for a in m.attachments] == [("https://media.telnyx.com/a.jpg?sig=1", "image/jpeg"),
                                                                ("https://media.telnyx.com/b.pdf", "application/pdf")]


@pytest.mark.parametrize("telnyx_status, ours", [("delivered", "delivered"), ("delivery_failed", "failed"),
                                                 ("sending_failed", "failed"), ("delivery_unconfirmed", "sent")])
def test_parse_message_finalized(telnyx_status, ours):
    [s] = telnyx.parse(Request("u", {}, finalized(telnyx_status)))
    assert (s.kind, s.provider_message_id, s.status, s.error) == ("status", "msg-out-1", ours, None)
    assert (s.from_, s.to, s.body) == ("+15550001111", "+13125550001", "")
    assert s.occurred_at == datetime(2026, 10, 17, 11, 11, 59, 500000, tzinfo=UTC)


def test_a_finalized_failure_carries_the_error():
    errors = [{"code": "40008", "title": "Message blocked", "detail": "Carrier blocked the message as spam"}]
    [s] = telnyx.parse(Request("u", {}, finalized("delivery_failed", errors)))
    assert s.error == "40008 Message blocked Carrier blocked the message as spam"


def test_other_events_and_unknown_statuses_are_ignored():
    for body in (RECEIVED.replace(b"message.received", b"message.sent"), finalized("something_new"), b"{}",
                 json.dumps({"data": {"event_type": "message.received", "payload": {}}}).encode()):
        assert telnyx.parse(Request("u", {}, body)) == []
    with pytest.raises(ValueError):
        telnyx.parse(Request("u", {}, b"<xml/>"))


def test_send_posts_json_with_a_bearer_token(receiver):
    receiver.default = (200, json.dumps({"data": {"id": "40385f64-5717-4562-b3fc-2c963f66afa6",
                                                  "record_type": "message"}}).encode(), {})
    channel = Channel(address="+15550001111", config={"messaging_profile_id": "prof-1"}, secrets={"api_key": "KEY01_x"})
    message = Outbound(to="+13125550001", body="Hi", attachments=["https://cdn.example.com/a.jpg"], subject="Photo",
                       status_callback="https://app.example.com/api/hooks/telnyx/abc")
    result = telnyx.send(channel, message, base_url=f"http://127.0.0.1:{receiver.port}")
    assert result.provider_message_id == "40385f64-5717-4562-b3fc-2c963f66afa6"
    [seen] = receiver.requests
    assert seen["path"] == "/v2/messages" and seen["headers"]["authorization"] == "Bearer KEY01_x"
    assert seen["headers"]["content-type"] == "application/json"
    assert json.loads(seen["body"]) == {
        "to": "+13125550001", "text": "Hi", "type": "MMS", "from": "+15550001111", "messaging_profile_id": "prof-1",
        "media_urls": ["https://cdn.example.com/a.jpg"], "subject": "Photo",
        "webhook_url": "https://app.example.com/api/hooks/telnyx/abc"}


def test_a_plain_sms_has_no_media_fields_and_the_message_sender_wins(receiver):
    receiver.default = (200, b'{"data": {"id": "m1"}}', {})
    telnyx.send(CHANNEL, Outbound(to="+1", from_="+1999", body="x"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert json.loads(receiver.requests[0]["body"]) == {"to": "+1", "text": "x", "type": "SMS", "from": "+1999"}


@pytest.mark.parametrize("status, retryable", [(400, False), (401, False), (403, False), (422, False), (429, True),
                                               (500, True), (502, True)])
def test_send_errors_are_classified(receiver, status, retryable):
    errors = [{"code": "40310", "title": "Invalid 'to' address", "detail": "The 'to' address is not a valid number"}]
    receiver.default = (status, json.dumps({"errors": errors}).encode(), {})
    with pytest.raises(ChannelError) as e:
        telnyx.send(CHANNEL, Outbound(to="x"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is retryable and e.value.code == "40310" and "not a valid number" in str(e.value)
    assert "KEY01_secret" not in str(e.value)


def test_send_needs_a_key_and_an_id_in_the_answer(receiver):
    with pytest.raises(ChannelError, match="api_key"):
        telnyx.send(Channel(address="+1"), Outbound(to="x"), base_url="http://127.0.0.1:9")
    receiver.default = (200, b'{"data": {}}', {})
    with pytest.raises(ChannelError) as e:
        telnyx.send(CHANNEL, Outbound(to="x"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is False
