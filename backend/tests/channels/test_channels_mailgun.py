import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, parse_qsl, urlencode

import pytest

from app.channels import mailgun
from app.channels.base import Channel, ChannelError, Outbound, Request

SIGNING_KEY = "test-signing-key-for-hmac-only"
CHANNEL = Channel(address="Acme <hello@mg.example.com>", config={"domain": "mg.example.com"},
                  secrets={"api_key": "key-apikey", "signing_key": SIGNING_KEY})


def sign(timestamp: str, token: str, key: str = SIGNING_KEY) -> str:
    return hmac.new(key.encode(), (timestamp + token).encode(), hashlib.sha256).hexdigest()


TOKEN = "a8ce0edb2dd8301dee6c2405235584e45aa91d1e9f979f3de0"


def event_request(event: dict, stamp: int | None = None, key: str = SIGNING_KEY,
                  signature: str | None = None) -> Request:
    stamp, token = str(int(time.time()) if stamp is None else stamp), TOKEN
    body = {"signature": {"timestamp": stamp, "token": token, "signature": signature or sign(stamp, token, key)},
            "event-data": event}
    return Request("https://x.test/h", {"Content-Type": "application/json"}, json.dumps(body).encode())


def route_request(fields: dict, stamp: int | None = None, key: str = SIGNING_KEY) -> Request:
    stamp, token = str(int(time.time()) if stamp is None else stamp), "b9de1f"
    form = {**fields, "timestamp": stamp, "token": token, "signature": sign(stamp, token, key)}
    return Request("https://x.test/h", {"Content-Type": "application/x-www-form-urlencoded"}, urlencode(form).encode())


DELIVERED = {"event": "delivered", "timestamp": 1760697000.329574, "id": "DACSsAdVSeGpLid7TN03WA", "log-level": "info",
             "recipient": "bob@example.net", "recipient-domain": "example.net",
             "message": {"headers": {"to": "bob@example.net", "message-id": "20261017100000.1.ABC@mg.example.com",
                                     "from": "Acme <hello@mg.example.com>", "subject": "Hello"},
                         "attachments": [], "size": 4096},
             "delivery-status": {"code": 250, "message": "OK", "description": "", "enhanced-code": "2.0.0",
                                 "attempt-no": 1, "mx-host": "mx.example.net"}, "user-variables": {}}

INBOUND = {
    "recipient": "hello@mg.example.com", "sender": "bob@example.net", "from": "Bob Example <bob@example.net>",
    "subject": "Re: Your invoice", "body-plain": "Thanks, paid!\n\nOn Fri, Acme wrote:\n> Your invoice is attached",
    "stripped-text": "Thanks, paid!", "stripped-signature": "-- Bob",
    "body-html": "<p>Thanks, paid!</p><blockquote>q</blockquote>",
    "stripped-html": "<p>Thanks, paid!</p>", "Message-Id": "<CAF3x9=reply@mail.example.net>",
    "In-Reply-To": "<20261017100000.1.ABC@mg.example.com>",
    "References": "<first@mg.example.com> <20261017100000.1.ABC@mg.example.com>",
    "Date": "Fri, 17 Oct 2026 10:30:00 +0000", "message-headers": json.dumps([
        ["Received", "by mail.example.net"], ["Message-Id", "<CAF3x9=reply@mail.example.net>"],
        ["From", "Bob Example <bob@example.net>"], ["Subject", "Re: Your invoice"]]),
}


def test_a_signed_event_and_a_signed_route_verify():
    assert mailgun.verify(CHANNEL, event_request(DELIVERED))
    assert mailgun.verify(CHANNEL, route_request(INBOUND))


def test_tampered_or_wrongly_keyed_requests_are_refused():
    assert not mailgun.verify(CHANNEL, event_request(DELIVERED, signature="0" * 64))
    assert not mailgun.verify(CHANNEL, event_request(DELIVERED, key="another-key"))
    assert not mailgun.verify(CHANNEL, route_request(INBOUND, key="another-key"))
    assert not mailgun.verify(Channel(secrets={"signing_key": "other"}), event_request(DELIVERED))
    forged = json.loads(event_request(DELIVERED).body)
    forged["signature"]["token"] = "f" * 50  # the signature belongs to another token
    assert not mailgun.verify(CHANNEL, Request("u", {"content-type": "application/json"}, json.dumps(forged).encode()))
    form = route_request(INBOUND)
    changed = form.body.replace(b"token=b9de1f", b"token=b9de1e")
    assert not mailgun.verify(CHANNEL, Request(form.url, form.headers, changed))


def test_the_api_key_is_not_the_signing_key():
    mixed_up = Channel(secrets={"api_key": SIGNING_KEY})
    assert not mailgun.verify(mixed_up, event_request(DELIVERED))


def test_stale_timestamps_are_refused():
    now = 1_800_000_000
    assert mailgun.verify(CHANNEL, event_request(DELIVERED, now - 300), now=now)
    assert not mailgun.verify(CHANNEL, event_request(DELIVERED, now - 301), now=now)
    assert not mailgun.verify(CHANNEL, route_request(INBOUND, now - 3600), now=now)
    assert not mailgun.verify(CHANNEL, event_request(DELIVERED, now + 301), now=now)
    assert not mailgun.verify(CHANNEL, event_request(DELIVERED, int(time.time()) - 400))


@pytest.mark.parametrize("request_", [
    Request("u", {"content-type": "application/json"}, b"not json"),
    Request("u", {"content-type": "application/json"}, b'{"signature": "text"}'),
    Request("u", {"content-type": "application/json"},
            b'{"signature": {"timestamp": "soon", "token": "t", "signature": "s"}}'),
    Request("u", {}, b""), Request("u", {}, b"timestamp=1&token=t"),
    Request("u", {}, urlencode({"timestamp": "x", "token": "t", "signature": "s"}).encode()),
])
def test_malformed_requests_are_refused_not_raised(request_):
    assert mailgun.verify(CHANNEL, request_, now=1) is False


def test_a_channel_without_a_signing_key_refuses_everything():
    assert not mailgun.verify(Channel(), event_request(DELIVERED))
    assert not mailgun.verify(Channel(secrets={"signing_key": ""}), event_request(DELIVERED, key=""))


def test_parse_an_inbound_route_reply():
    [m] = mailgun.parse(route_request(INBOUND))
    assert (m.kind, m.status) == ("message", "received")
    assert m.provider_message_id == "CAF3x9=reply@mail.example.net"  # no angle brackets
    assert m.thread_ref == "20261017100000.1.ABC@mg.example.com"
    assert (m.from_, m.to, m.subject) == ("bob@example.net", "hello@mg.example.com", "Re: Your invoice")
    assert m.body == "Thanks, paid!" and m.html == "<p>Thanks, paid!</p>"  # the quoted history is stripped
    assert m.occurred_at == datetime(2026, 10, 17, 10, 30, tzinfo=UTC)


def test_inbound_falls_back_to_the_full_body_the_headers_json_and_the_references():
    dropped = ("stripped-text", "stripped-html", "In-Reply-To", "Date", "Message-Id")
    fields = {k: v for k, v in INBOUND.items() if k not in dropped}
    fields["stripped-text"] = ""  # a reply that is nothing but the quote
    fields["message-headers"] = json.dumps([["Message-ID", "<viaheaders@mail.example.net>"]])
    [m] = mailgun.parse(route_request(fields))
    assert m.body == INBOUND["body-plain"] and m.html == INBOUND["body-html"]
    assert m.provider_message_id == "viaheaders@mail.example.net"
    assert m.thread_ref == "20261017100000.1.ABC@mg.example.com"  # the last reference
    assert abs((m.occurred_at - datetime.now(UTC)).total_seconds()) < 60  # the webhook timestamp: it was just made


def test_inbound_without_replies_or_html_has_no_thread_or_html():
    fields = {"recipient": "hello@mg.example.com", "sender": "bob@example.net", "subject": "Hi", "body-plain": "hello",
              "Message-Id": "<new@mail.example.net>"}
    [m] = mailgun.parse(route_request(fields))
    assert (m.thread_ref, m.html, m.from_, m.attachments) == (None, None, "bob@example.net", [])


def test_inbound_attachments_from_a_store_route():
    stored = json.dumps([{"url": "https://api.mailgun.net/v3/domains/mg.example.com/messages/abc/attachments/0",
                          "content-type": "application/pdf", "name": "invoice.pdf", "size": 1234}, "junk"])
    [m] = mailgun.parse(route_request({**INBOUND, "attachments": stored}))
    assert [(a.name, a.content_type, a.url[-1]) for a in m.attachments] == [("invoice.pdf", "application/pdf", "0")]
    [m] = mailgun.parse(route_request({**INBOUND, "attachments": "not json"}))
    assert m.attachments == []


def test_a_multipart_route_post_is_read_like_a_form():
    boundary = "xYz"
    fields = {**INBOUND, "timestamp": str(int(time.time())), "token": "t", "signature": "s"}
    parts = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                     for k, v in fields.items())
    parts += (f'--{boundary}\r\nContent-Disposition: form-data; name="attachment-1"; filename="a.png"\r\n'
              f"Content-Type: image/png\r\n\r\n").encode() + b"\x89PNG\r\n--" + boundary.encode() + b"--\r\n"
    [m] = mailgun.parse(Request("u", {"Content-Type": f"multipart/form-data; boundary={boundary}"}, parts))
    assert m.body == "Thanks, paid!" and m.provider_message_id == "CAF3x9=reply@mail.example.net"


def test_parse_a_delivered_event():
    [s] = mailgun.parse(event_request(DELIVERED))
    assert (s.kind, s.provider_message_id, s.status, s.error) == ("status", "20261017100000.1.ABC@mg.example.com",
                                                                   "delivered", None)
    assert (s.from_, s.to) == ("Acme <hello@mg.example.com>", "bob@example.net")
    assert s.occurred_at == datetime.fromtimestamp(1760697000.329574, UTC)


def test_parse_failed_events_by_severity():
    permanent = {**DELIVERED, "event": "failed", "severity": "permanent", "reason": "bounce",
                 "delivery-status": {"code": 550, "message": "5.1.1 mailbox unavailable",
                                     "description": "The email account does not exist"}}
    [s] = mailgun.parse(event_request(permanent))
    assert (s.status, s.error) == ("failed", "550 The email account does not exist")
    temporary = {**permanent, "severity": "temporary"}
    assert mailgun.parse(event_request(temporary)) == []  # Mailgun is still retrying


def test_parse_rejected_complained_unsubscribed_and_accepted_events():
    rejected = {**DELIVERED, "event": "rejected", "reject": {"reason": "Sandbox subdomains are for test purposes only"},
                "delivery-status": {}}
    assert [(s.status, s.error) for s in mailgun.parse(event_request(rejected))] == [
        ("failed", "Sandbox subdomains are for test purposes only")]
    for name, status in (("complained", "complained"), ("unsubscribed", "unsubscribed"), ("accepted", "sent")):
        assert [s.status for s in mailgun.parse(event_request({**DELIVERED, "event": name}))] == [status]


def test_other_events_are_ignored():
    for name in ("opened", "clicked", "stored"):
        assert mailgun.parse(event_request({**DELIVERED, "event": name})) == []
    assert mailgun.parse(event_request({"event": "delivered", "message": {"headers": {}}})) == []
    assert mailgun.parse(Request("u", {"content-type": "application/json"}, b"{}")) == []
    with pytest.raises(ValueError):
        mailgun.parse(Request("u", {}, b"recipient=a%40b.test"))  # a route post without a Message-Id


ANSWER = b'{"id": "<20261017120000.7.DEF@mg.example.com>", "message": "Queued. Thank you."}'


def test_send_posts_a_form_with_basic_auth_and_our_message_id(receiver):
    receiver.default = (200, ANSWER, {})
    message = Outbound(to="bob@example.net", subject="Re: Your invoice", body="Thanks!", html="<p>Thanks!</p>",
                       reply_to="billing@example.com", in_reply_to="<CAF3x9=reply@mail.example.net>",
                       references=["<first@mg.example.com>"], idempotency_key="0b7c6a3e-1111",
                       unsubscribe_url="https://app.example.com/u/abc")
    result = mailgun.send(CHANNEL, message, base_url=f"http://127.0.0.1:{receiver.port}")
    assert result.provider_message_id == "20261017120000.7.DEF@mg.example.com"
    [seen] = receiver.requests
    assert seen["path"] == "/v3/mg.example.com/messages"
    assert seen["headers"]["authorization"] == "Basic YXBpOmtleS1hcGlrZXk="  # api:key-apikey
    assert seen["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qsl(seen["body"].decode()) == [
        ("from", "Acme <hello@mg.example.com>"), ("to", "bob@example.net"), ("subject", "Re: Your invoice"),
        ("text", "Thanks!"), ("h:Message-Id", "<0b7c6a3e-1111@mg.example.com>"), ("html", "<p>Thanks!</p>"),
        ("h:Reply-To", "billing@example.com"), ("h:In-Reply-To", "<CAF3x9=reply@mail.example.net>"),
        ("h:References", "<first@mg.example.com> <CAF3x9=reply@mail.example.net>"),
        ("h:List-Unsubscribe", "<https://app.example.com/u/abc>"),
        ("h:List-Unsubscribe-Post", "List-Unsubscribe=One-Click")]


def test_send_with_only_html_derives_a_text_part_and_never_sends_an_empty_one(receiver):
    receiver.default = (200, ANSWER, {})
    mailgun.send(CHANNEL, Outbound(to="b@example.net", subject="S", html="<p>Hello <b>there</b></p>"),
                 base_url=f"http://127.0.0.1:{receiver.port}")
    assert parse_qs(receiver.requests[0]["body"].decode())["text"] == ["Hello there"]


def test_send_attaches_files_fetched_through_the_ssrf_guard(receiver, files):
    receiver.default = (200, ANSWER, {})
    files.files["/invoice.pdf"] = ("application/pdf", b"%PDF-1.7 data")
    message = Outbound(to="b@example.net", subject="S", body="see attached", attachments=[files.url("/invoice.pdf")])
    mailgun.send(CHANNEL, message, base_url=f"http://127.0.0.1:{receiver.port}")
    [seen] = receiver.requests
    assert seen["headers"]["content-type"].startswith("multipart/form-data; boundary=")
    assert (b'name="attachment"; filename="invoice.pdf"\r\nContent-Type: application/pdf\r\n\r\n%PDF-1.7 data\r\n'
            in seen["body"])


def test_a_private_attachment_url_is_refused_before_anything_is_sent(receiver, dns):
    dns["files.test"] = ["10.0.0.9"]
    with pytest.raises(ChannelError) as e:
        mailgun.send(CHANNEL, Outbound(to="b@example.net", attachments=["https://files.test/a.pdf"]),
                     base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is False and receiver.requests == []


def test_the_eu_region_uses_its_own_host(monkeypatch):
    seen = []
    monkeypatch.setattr(mailgun.transport, "post", lambda url, **kw: seen.append(url) or {"id": "<x@y.test>"})
    for region in ("eu", "us", None):
        config = {"domain": "mg.example.com", **({"region": region} if region else {})}
        channel = Channel(config=config, secrets={"api_key": "k"})
        mailgun.send(channel, Outbound(to="b@example.net", from_="a@mg.example.com"))
    assert seen == ["https://api.eu.mailgun.net/v3/mg.example.com/messages",
                    "https://api.mailgun.net/v3/mg.example.com/messages",
                    "https://api.mailgun.net/v3/mg.example.com/messages"]


def test_a_region_or_domain_cannot_redirect_the_call(receiver):
    with pytest.raises(ChannelError, match="region"):
        evil = Channel(config={"domain": "d.test", "region": "https://evil.example.com"}, secrets={"api_key": "k"})
        mailgun.send(evil, Outbound(to="b@example.net"))
    receiver.default = (200, ANSWER, {})
    tricky = Channel(config={"domain": "a/../b.test", "message_id_domain": "b.test"}, secrets={"api_key": "k"})
    mailgun.send(tricky, Outbound(to="b@example.net", from_="a@b.test"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert receiver.requests[0]["path"] == "/v3/a%2F..%2Fb.test/messages"


@pytest.mark.parametrize("status, retryable", [(400, False), (401, False), (402, False), (404, False), (429, True),
                                               (500, True), (503, True)])
def test_send_errors_are_classified(receiver, status, retryable):
    receiver.default = (status, b'{"message": "Domain not found: nope.example.com"}', {})
    with pytest.raises(ChannelError) as e:
        mailgun.send(CHANNEL, Outbound(to="b@example.net"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is retryable and "Domain not found" in str(e.value) and "key-apikey" not in str(e.value)


def test_send_needs_a_domain_a_key_and_an_id_in_the_answer(receiver):
    with pytest.raises(ChannelError, match="domain"):
        mailgun.send(Channel(secrets={"api_key": "k"}), Outbound(to="b@example.net"), base_url="http://127.0.0.1:9")
    with pytest.raises(ChannelError, match="api_key"):
        mailgun.send(Channel(config={"domain": "d.test"}), Outbound(to="b@example.net", from_="a@d.test"),
                     base_url="http://127.0.0.1:9")
    receiver.default = (200, b'{"message": "Queued"}', {})
    with pytest.raises(ChannelError) as e:
        mailgun.send(CHANNEL, Outbound(to="b@example.net"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is False
