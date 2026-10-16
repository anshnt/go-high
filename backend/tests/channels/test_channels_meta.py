import hashlib
import hmac
import json
from datetime import UTC, datetime

import pytest

from app.channels import meta_whatsapp as meta
from app.channels.base import Channel, ChannelError, Outbound, Request, Template

SECRET = "app-secret-0123456789abcdef"
CHANNEL = Channel(address="+15550783881", config={"phone_number_id": "106540352242922"},
                  secrets={"access_token": "EAAG-token", "app_secret": SECRET, "verify_token": "hello-handshake"})
WAMID = "wamid.HBgLMTY1MDM4Nzk0MzkVAgASGBQzQTdCNTg4RjY1MEMwNjRDOTkwOQA="


def signed(body: bytes, secret: str = SECRET) -> Request:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"}
    return Request("https://x.test/h", headers, body)


def webhook(**value) -> bytes:
    value = {"messaging_product": "whatsapp",
             "metadata": {"display_phone_number": "15550783881", "phone_number_id": "106540352242922"},
             "contacts": [{"profile": {"name": "Sheena Nelson"}, "wa_id": "16505551234"}], **value}
    return json.dumps({"object": "whatsapp_business_account", "entry": [
        {"id": "102290129340398", "changes": [{"field": "messages", "value": value}]}]}).encode()


def message(kind: str, **fields) -> dict:
    return {"from": "16505551234", "id": WAMID, "timestamp": "1760697000", "type": kind, **fields}


def test_a_signed_body_verifies_and_changes_are_refused():
    body = webhook(messages=[message("text", text={"body": "hi"})])
    assert meta.verify(CHANNEL, signed(body))
    good = signed(body)
    assert not meta.verify(CHANNEL, Request(good.url, good.headers, body.replace(b"hi", b"ho")))
    assert not meta.verify(CHANNEL, signed(body, secret="another-secret"))
    assert not meta.verify(Channel(secrets={"app_secret": "other"}), good)


@pytest.mark.parametrize("header", ["", "sha256=", "sha256=00", "sha1=" + "0" * 40, "0" * 64, "sha256=é"])
def test_missing_or_malformed_signatures_are_refused(header):
    body = webhook(messages=[])
    assert not meta.verify(CHANNEL, Request("u", {"x-hub-signature-256": header} if header else {}, body))


def test_a_channel_without_an_app_secret_refuses_everything():
    assert not meta.verify(Channel(), signed(b"{}", secret="")) and not meta.verify(Channel(secrets={"app_secret": ""}),
                                                                                 signed(b"{}", secret=""))


def handshake(**query) -> Request:
    q = {"hub.mode": "subscribe", "hub.verify_token": "hello-handshake", "hub.challenge": "1158201444", **query}
    return Request("https://x.test/api/hooks/meta/abc?" + "&".join(f"{k}={v}" for k, v in q.items()), {}, method="GET")


def test_the_handshake_echoes_the_challenge_only_for_our_token():
    assert meta.challenge(CHANNEL, handshake()) == "1158201444"
    assert meta.challenge(CHANNEL, handshake(**{"hub.verify_token": "wrong"})) is None
    assert meta.challenge(CHANNEL, handshake(**{"hub.mode": "unsubscribe"})) is None
    assert meta.challenge(CHANNEL, Request("https://x.test/h", {}, method="GET")) is None
    assert meta.challenge(Channel(), handshake(**{"hub.verify_token": ""})) is None  # no token configured
    assert meta.challenge(Channel(secrets={"verify_token": ""}), handshake(**{"hub.verify_token": ""})) is None


def test_the_challenge_is_never_reflected_when_it_is_not_a_plain_token():
    for value in ("%3Cscript%3Ealert(1)%3C%2Fscript%3E", "a%0d%0aSet-Cookie:x", "", "x" * 300):
        assert meta.challenge(CHANNEL, handshake(**{"hub.challenge": value})) is None


def test_parse_a_text_message():
    body = webhook(messages=[message("text", text={"body": "Does it come in another color?"})])
    [m] = meta.parse(Request("u", {}, body))
    assert (m.kind, m.status, m.provider_message_id) == ("message", "received", WAMID)
    assert (m.from_, m.to, m.body, m.attachments, m.thread_ref) == ("+16505551234", "+15550783881",
                                                                    "Does it come in another color?", [], None)
    assert m.occurred_at == datetime.fromtimestamp(1760697000, UTC)


def test_parse_media_with_a_caption_and_a_document():
    image = message("image", image={"caption": "Look at this", "mime_type": "image/jpeg", "sha256": "abc",
                                    "id": "MEDIA1"})
    document = message("document", id="wamid.2", document={"mime_type": "application/pdf", "filename": "invoice.pdf",
                                                           "id": "MEDIA2"})
    m1, m2 = meta.parse(Request("u", {}, webhook(messages=[image, {**document, "id": "wamid.2"}])))
    assert (m1.body, [(a.media_id, a.content_type, a.url) for a in m1.attachments]) == (
        "Look at this", [("MEDIA1", "image/jpeg", "")])
    assert (m2.body, [(a.media_id, a.name) for a in m2.attachments]) == ("", [("MEDIA2", "invoice.pdf")])


def test_parse_replies_buttons_reactions_and_locations():
    interactive = message("interactive", id="w1", interactive={"type": "button_reply",
                                                              "button_reply": {"id": "yes", "title": "Yes, book it"}},
                          context={"from": "15550783881", "id": "wamid.ours"})
    listing = message("interactive", id="w2",
                      interactive={"type": "list_reply", "list_reply": {"id": "r1", "title": "Tuesday"}})
    button = message("button", id="w3", button={"payload": "p", "text": "Stop promotions"})
    reaction = message("reaction", id="w4", reaction={"message_id": "wamid.ours", "emoji": "\U0001f44d"})
    location = message("location", id="w5", location={"latitude": 37.4, "longitude": -122.1, "name": "Office"})
    unsupported = message("unsupported", id="w6", errors=[{"code": 131051}])
    body = webhook(messages=[interactive, listing, button, reaction, location, unsupported])
    got = meta.parse(Request("u", {}, body))
    assert [(m.provider_message_id, m.body, m.thread_ref) for m in got] == [
        ("w1", "Yes, book it", "wamid.ours"), ("w2", "Tuesday", None), ("w3", "Stop promotions", None),
        ("w4", "\U0001f44d", "wamid.ours"), ("w5", "37.4,-122.1 Office", None), ("w6", "", None)]


@pytest.mark.parametrize("wa_status, ours", [("sent", "sent"), ("delivered", "delivered"), ("read", "read")])
def test_parse_statuses(wa_status, ours):
    status = {"id": WAMID, "status": wa_status, "timestamp": "1760697060", "recipient_id": "16505551234",
              "conversation": {"id": "c1", "origin": {"type": "service"}},
              "pricing": {"billable": True, "category": "service"}}
    [s] = meta.parse(Request("u", {}, webhook(statuses=[status])))
    assert (s.kind, s.provider_message_id, s.status, s.error) == ("status", WAMID, ours, None)
    assert (s.from_, s.to, s.occurred_at) == ("+15550783881", "+16505551234", datetime.fromtimestamp(1760697060, UTC))


def test_a_failed_status_carries_the_error():
    status = {"id": WAMID, "status": "failed", "timestamp": "1760697060", "recipient_id": "16505551234", "errors": [
        {"code": 131047, "title": "Re-engagement message", "message": "Re-engagement message",
         "error_data": {"details": "More than 24 hours have passed since the customer last replied."}}]}
    [s] = meta.parse(Request("u", {}, webhook(statuses=[status])))
    assert s.status == "failed"
    assert s.error == "131047 Re-engagement message More than 24 hours have passed since the customer last replied."


def test_one_webhook_can_carry_messages_and_statuses_for_several_entries():
    first = json.loads(webhook(messages=[message("text", text={"body": "a"})], statuses=[
        {"id": "w9", "status": "delivered", "timestamp": "1", "recipient_id": "1"},
        {"id": "w10", "status": "deleted", "timestamp": "1", "recipient_id": "1"}]))
    second = json.loads(webhook(messages=[{**message("text", text={"body": "b"}), "id": "w11"}]))
    first["entry"] += second["entry"] + [{"id": "x", "changes": [{"field": "message_template_status_update",
                                                                   "value": {"event": "APPROVED"}}]}]
    got = meta.parse(Request("u", {}, json.dumps(first).encode()))
    assert [(m.kind, m.provider_message_id) for m in got] == [("message", WAMID), ("status", "w9"), ("message", "w11")]


def test_parse_ignores_other_fields_and_rejects_non_json():
    assert meta.parse(Request("u", {}, b'{"object": "whatsapp_business_account", "entry": []}')) == []
    assert meta.parse(Request("u", {}, b"{}")) == []
    with pytest.raises(ValueError):
        meta.parse(Request("u", {}, b"nope"))


GRAPH_ANSWER = (b'{"messaging_product": "whatsapp", "contacts": [{"input": "16505551234", "wa_id": "16505551234"}], '
                b'"messages": [{"id": "wamid.SENT1"}]}')


def sent(receiver, message: Outbound, channel: Channel = CHANNEL) -> dict:
    receiver.default = (200, GRAPH_ANSWER, {})
    result = meta.send(channel, message, base_url=f"http://127.0.0.1:{receiver.port}")
    assert result.provider_message_id == "wamid.SENT1"
    return json.loads(receiver.requests[-1]["body"])


def test_send_text(receiver):
    body = sent(receiver, Outbound(to="+16505551234", body="Hello é"))
    assert body == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": "+16505551234",
                    "type": "text", "text": {"body": "Hello é", "preview_url": False}}
    seen = receiver.requests[0]
    assert seen["path"] == "/106540352242922/messages" and seen["headers"]["authorization"] == "Bearer EAAG-token"


def test_send_a_template_with_body_variables(receiver):
    body = sent(receiver, Outbound(to="16505551234", template=Template("order_update", "en_US", ["Sheena", "#1043"])))
    assert body["type"] == "template" and "text" not in body
    assert body["template"] == {"name": "order_update", "language": {"code": "en_US"}, "components": [
        {"type": "body", "parameters": [{"type": "text", "text": "Sheena"}, {"type": "text", "text": "#1043"}]}]}
    assert "components" not in sent(receiver, Outbound(to="1", template=Template("hello_world")))["template"]


@pytest.mark.parametrize("url, kind", [("https://cdn.example.com/a.jpg", "image"),
                                       ("https://cdn.example.com/a.mp4", "video"),
                                       ("https://cdn.example.com/a.mp3?sig=1", "audio"),
                                       ("https://cdn.example.com/invoice.pdf", "document"),
                                       ("https://cdn.example.com/blob", "document")])
def test_send_media_by_link(receiver, url, kind):
    body = sent(receiver, Outbound(to="1", body="Caption", attachments=[url]))
    expected = {"link": url} if kind == "audio" else {"link": url, "caption": "Caption"}
    assert body["type"] == kind and body[kind] == expected and "text" not in body


def test_one_attachment_per_message(receiver):
    with pytest.raises(ChannelError) as e:
        meta.send(CHANNEL, Outbound(to="1", attachments=["https://x.test/a.jpg", "https://x.test/b.jpg"]),
                  base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is False and receiver.requests == []


@pytest.mark.parametrize("status, code, retryable", [
    (400, 100, False), (400, 131047, False), (401, 190, False), (403, 10, False), (404, 100, False),
    (400, 131026, False), (400, 80007, True), (400, 130429, True), (400, 4, True), (400, 131056, True),
    (429, 100, True), (500, 1, True), (503, 2, True)])
def test_send_errors_are_classified(receiver, status, code, retryable):
    receiver.default = (status, json.dumps({"error": {"message": "(#100) Invalid parameter", "type": "OAuthException",
                                                      "code": code, "fbtrace_id": "A1b2"}}).encode(), {})
    with pytest.raises(ChannelError) as e:
        meta.send(CHANNEL, Outbound(to="1", body="x"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is retryable and e.value.code == str(code) and "Invalid parameter" in str(e.value)
    assert "EAAG-token" not in str(e.value)


def test_send_needs_settings_and_an_id_in_the_answer(receiver):
    with pytest.raises(ChannelError, match="phone_number_id"):
        meta.send(Channel(secrets={"access_token": "t"}), Outbound(to="1", body="x"), base_url="http://127.0.0.1:9")
    with pytest.raises(ChannelError, match="access_token"):
        meta.send(Channel(config={"phone_number_id": "1"}), Outbound(to="1", body="x"), base_url="http://127.0.0.1:9")
    receiver.default = (200, b'{"messages": []}', {})
    with pytest.raises(ChannelError) as e:
        meta.send(CHANNEL, Outbound(to="1", body="x"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is False


def test_the_phone_number_id_cannot_change_the_path(receiver):
    channel = Channel(config={"phone_number_id": "1/../x"}, secrets={"access_token": "t"})
    sent(receiver, Outbound(to="1", body="x"), channel)
    assert receiver.requests[0]["path"] == "/1%2F..%2Fx/messages"
