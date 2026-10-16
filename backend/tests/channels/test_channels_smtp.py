import socket
from datetime import UTC, datetime
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime

import pytest

from app import ssrf
from app.channels import ADAPTERS, smtp
from app.channels.base import Channel, ChannelError, Outbound, Request


@pytest.fixture(autouse=True)
def names(dns):
    dns["smtp.test"] = ["127.0.0.1"]  # allowed past the SSRF guard only by the `receiver` fixture
    dns["other.test"] = ["127.0.0.1"]


def channel(server, host="smtp.test", **config) -> Channel:
    return Channel(address="Acme <hello@example.com>",
                   config={"host": host, "port": server.port, "username": "user", **config},
                   secrets={"password": "secret"})


def parsed(server, index=-1):
    return message_from_bytes(server.messages[index]["data"], policy=policy.default)


def text_of(msg) -> str:
    return msg.get_body(("plain",)).get_content().replace("\r\n", "\n").strip()


def plain(**kw) -> Outbound:
    return Outbound(to="bob@example.net", subject="Hello", body="Hi Bob", **kw)


def test_starttls_send_verifies_the_certificate_for_the_name_while_connecting_to_the_checked_address(
        receiver, tls, smtp_server):
    server = smtp_server(context=tls("smtp.test"))
    result = smtp.send(channel(server), plain(html="<p>Hi <b>Bob</b></p>", idempotency_key="msg-1"))
    [sent] = server.messages
    assert sent["secure"] is True and sent["user"] == "user"  # encrypted before the password was sent
    assert (sent["from"], sent["to"], sent["helo"]) == ("hello@example.com", ["bob@example.net"], "example.com")
    assert server.commands.index("STARTTLS") < server.commands.index("AUTH") < server.commands.index("MAIL")
    msg = parsed(server)
    assert result.provider_message_id == "msg-1@example.com" and msg["Message-ID"] == "<msg-1@example.com>"
    assert (msg["From"], msg["To"], msg["Subject"]) == ("Acme <hello@example.com>", "bob@example.net", "Hello")
    assert msg.get_content_type() == "multipart/alternative"
    assert text_of(msg) == "Hi Bob" and "<b>Bob</b>" in msg.get_body(("html",)).get_content()
    assert abs((datetime.now(UTC) - parsedate_to_datetime(msg["Date"])).total_seconds()) < 60
    for absent in ("Reply-To", "In-Reply-To", "References", "List-Unsubscribe", "List-Unsubscribe-Post"):
        assert msg[absent] is None


def test_implicit_tls_send(receiver, tls, smtp_server):
    server = smtp_server(context=tls("smtp.test"), implicit=True)
    smtp.send(channel(server, security="tls"), plain())
    assert server.messages[0]["secure"] is True and "STARTTLS" not in server.commands


def test_a_plain_text_only_message_is_not_multipart(receiver, tls, smtp_server):
    server = smtp_server(context=tls())
    smtp.send(channel(server), plain())
    assert parsed(server).get_content_type() == "text/plain"


def test_html_only_gets_a_text_alternative(receiver, tls, smtp_server):
    server = smtp_server(context=tls())
    html = "<h1>Welcome</h1><p>Glad you are here</p>"
    smtp.send(channel(server), Outbound(to="bob@example.net", subject="S", html=html))
    assert text_of(parsed(server)) == "Welcome\n\nGlad you are here"


def test_threading_and_reply_headers(receiver, tls, smtp_server):
    server = smtp_server(context=tls())
    smtp.send(channel(server), plain(reply_to="Billing <billing@example.com>",
                                     in_reply_to="<CAF3x9=reply@mail.example.net>",
                                     references=["first@mg.example.com", "<second@mg.example.com>"]))
    msg = parsed(server)
    assert msg["In-Reply-To"] == "<CAF3x9=reply@mail.example.net>"
    assert msg["References"] == "<first@mg.example.com> <second@mg.example.com> <CAF3x9=reply@mail.example.net>"
    assert msg["Reply-To"] == "Billing <billing@example.com>"
    smtp.send(channel(server), plain(in_reply_to="parent@x.test"))  # brackets are optional on the way in
    assert parsed(server)["In-Reply-To"] == "<parent@x.test>" and parsed(server)["References"] == "<parent@x.test>"


def test_message_ids_are_unique_and_on_our_domain(receiver, tls, smtp_server):
    server = smtp_server(context=tls())
    ids = [smtp.send(channel(server), plain()).provider_message_id for _ in range(2)]
    assert ids[0] != ids[1] and all(i.endswith("@example.com") and "<" not in i for i in ids)
    assert parsed(server, 0)["Message-ID"] == f"<{ids[0]}>"
    smtp.send(channel(server, message_id_domain="mail.example.org"), plain())
    assert parsed(server)["Message-ID"].endswith("@mail.example.org>")


def test_a_retried_send_carries_the_same_message_id(receiver, tls, smtp_server):
    server = smtp_server(context=tls())
    first = smtp.send(channel(server), plain(idempotency_key="0b7c6a3e-1111-2222-3333-444455556666"))
    second = smtp.send(channel(server), plain(idempotency_key="0b7c6a3e-1111-2222-3333-444455556666"))
    assert first == second and parsed(server, 0)["Message-ID"] == parsed(server, 1)["Message-ID"]


def test_list_unsubscribe(receiver, tls, smtp_server):
    server = smtp_server(context=tls())
    smtp.send(channel(server), plain(unsubscribe_url="https://app.example.com/u/abc"))
    msg = parsed(server)
    assert msg["List-Unsubscribe"] == "<https://app.example.com/u/abc>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    smtp.send(channel(server), plain(unsubscribe_url="mailto:unsub@example.com?subject=stop"))
    msg = parsed(server)
    assert msg["List-Unsubscribe"] == "<mailto:unsub@example.com?subject=stop>" and msg["List-Unsubscribe-Post"] is None


def test_attachments_are_fetched_and_attached(receiver, files, tls, smtp_server):
    files.files["/docs/invoice.pdf"] = ("application/pdf", b"%PDF-1.7 bytes")
    files.files["/logo.png"] = ("image/png", b"\x89PNG\r\n")
    server = smtp_server(context=tls())
    smtp.send(channel(server), plain(html="<p>See attached</p>",
                                     attachments=[files.url("/docs/invoice.pdf"), files.url("/logo.png")]))
    msg = parsed(server)
    assert msg.get_content_type() == "multipart/mixed"
    assert text_of(msg) == "Hi Bob" and msg.get_body(("html",)) is not None
    got = [(a.get_filename(), a.get_content_type(), a.get_content()) for a in msg.iter_attachments()]
    assert got == [("invoice.pdf", "application/pdf", b"%PDF-1.7 bytes"), ("logo.png", "image/png", b"\x89PNG\r\n")]


def test_unicode_survives(receiver, tls, smtp_server):
    server = smtp_server(context=tls())
    smtp.send(channel(server), Outbound(to="bob@example.net", subject="Café ✓ 日本",
                                        body="Grüße \U0001f44b", html="<p>Grüße</p>"))
    msg = parsed(server)
    assert msg["Subject"] == "Caf\u00e9 \u2713 \u65e5\u672c" and text_of(msg) == "Gr\u00fc\u00dfe \U0001f44b"


@pytest.mark.parametrize("field", ["subject", "to", "reply_to", "in_reply_to", "unsubscribe_url"])
def test_line_breaks_in_header_values_are_refused_before_any_connection(receiver, tls, smtp_server, field):
    server = smtp_server(context=tls())
    kw = {"to": "bob@example.net", "subject": "x", "body": "b", field: "evil\r\nBcc: victim@example.net"}
    with pytest.raises(ChannelError) as e:
        smtp.send(channel(server), Outbound(**kw))
    assert e.value.retryable is False and server.connections == 0 and server.messages == []


def test_no_login_when_no_username_is_configured(receiver, tls, smtp_server):
    server = smtp_server(context=tls(), login=None)
    smtp.send(Channel(address="hello@example.com", config={"host": "smtp.test", "port": server.port}), plain())
    assert "AUTH" not in server.commands and server.messages[0]["user"] is None


def test_a_refused_login_is_permanent(receiver, tls, smtp_server):
    server = smtp_server(context=tls())
    bad = channel(server)
    bad.secrets["password"] = "wrong"
    with pytest.raises(ChannelError) as e:
        smtp.send(bad, plain())
    assert (e.value.retryable, e.value.code) == (False, "535") and "wrong" not in str(e.value) and server.messages == []


def test_a_missing_password_is_a_config_error_not_a_connection(receiver, tls, smtp_server):
    server = smtp_server(context=tls())
    with pytest.raises(ChannelError, match="password") as e:
        config = {"host": "smtp.test", "port": server.port, "username": "u"}
        smtp.send(Channel(address="hello@example.com", config=config), plain())
    assert e.value.retryable is False and server.connections == 0


def test_a_server_without_starttls_is_refused_and_no_credentials_or_mail_are_sent(receiver, smtp_server):
    server = smtp_server()  # no TLS at all
    with pytest.raises(ChannelError, match="STARTTLS") as e:
        smtp.send(channel(server), plain())
    assert e.value.retryable is False
    assert not {"AUTH", "MAIL", "RCPT", "DATA"} & set(server.commands) and server.messages == []


def test_a_certificate_that_is_not_trusted_is_refused(receiver, tls, smtp_server):
    server = smtp_server(context=tls("smtp.test", trust=False))
    with pytest.raises(ChannelError, match="certificate") as e:
        smtp.send(channel(server), plain())
    assert e.value.retryable is False and not {"AUTH", "MAIL"} & set(server.commands)


def test_a_certificate_for_another_name_is_refused_even_when_trusted(receiver, tls, smtp_server):
    server = smtp_server(context=tls("other.test"))  # trusted, but the host we asked for is smtp.test
    with pytest.raises(ChannelError, match="certificate") as e:
        smtp.send(channel(server), plain())
    assert e.value.retryable is False and not {"AUTH", "MAIL"} & set(server.commands)
    tls_server = smtp_server(context=tls("other.test"), implicit=True)
    with pytest.raises(ChannelError, match="certificate"):
        smtp.send(channel(tls_server, security="tls"), plain())


@pytest.mark.parametrize("verb, reply, retryable, code", [
    ("RCPT", "550 5.1.1 no such user", False, "550"), ("RCPT", "451 4.7.1 greylisted, try later", True, "451"),
    ("RCPT", "554 5.7.1 relay denied", False, "554"), ("MAIL", "553 5.1.8 sender domain not allowed", False, "553"),
    ("MAIL", "452 4.5.3 too many", True, "452"), ("END", "554 5.7.1 message rejected as spam", False, "554"),
    ("END", "421 4.4.2 timeout waiting for data", True, "421"), ("GREETING", "421 too busy", True, "421"),
    ("GREETING", "554 no SMTP service here", False, "554")])
def test_smtp_replies_are_classified_by_their_first_digit(receiver, tls, smtp_server, verb, reply, retryable, code):
    server = smtp_server(context=tls())
    server.replies[verb] = reply
    with pytest.raises(ChannelError) as e:
        smtp.send(channel(server), plain())
    assert (e.value.retryable, e.value.code) == (retryable, code) and reply.split(" ", 1)[1] in str(e.value)
    assert server.messages == []


def test_a_silent_server_times_out_as_retryable(receiver, tls, smtp_server, monkeypatch):
    monkeypatch.setattr(smtp, "TIMEOUT", 0.3)
    silent = smtp_server(context=tls())
    silent.replies["GREETING"] = "HANG"
    with pytest.raises(ChannelError) as e:
        smtp.send(channel(silent), plain())
    assert e.value.retryable is True


@pytest.mark.parametrize("host", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1", "100.64.0.1", "0.0.0.0",
                                  "::1", "::ffff:127.0.0.1", "fe80::1", "localhost", "internal.test", "mixed.test",
                                  "unknown.example.org"])
def test_private_and_unresolvable_hosts_are_refused_without_a_connection(dns, host, monkeypatch):
    dns["internal.test"] = ["10.0.0.7"]
    dns["mixed.test"] = ["93.184.216.34", "10.0.0.7"]  # one private answer is enough
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("connected to a refused host"))
    with pytest.raises(ChannelError) as e:
        smtp.send(Channel(address="a@example.com", config={"host": host, "port": 25, "username": "u"},
                          secrets={"password": "p"}), plain())
    assert e.value.retryable is False and "SMTP host" in str(e.value)


@pytest.mark.parametrize("host", ["", "a b.test", "host/path", "user@smtp.test", "evil.test#@127.0.0.1", "smtp.test:25",
                                  "smtp.test\r\nRCPT TO:<x@y.test>", "exämple.test"])
def test_malformed_hosts_are_refused(host):
    with pytest.raises(ChannelError) as e:
        smtp.send(Channel(address="a@example.com", config={"host": host}), plain())
    assert e.value.retryable is False


def test_the_checked_address_is_the_one_connected_to_so_rebinding_cannot_swap_it(
        receiver, tls, smtp_server, monkeypatch):
    server = smtp_server(context=tls())
    answers, calls = iter([["127.0.0.1"], ["10.0.0.5"], ["10.0.0.5"]]), []
    monkeypatch.setattr(ssrf, "resolve", lambda host, port: calls.append(host) or next(answers))
    smtp.send(channel(server), plain())
    assert calls == ["smtp.test"] and len(server.messages) == 1  # resolved once, then no second lookup by smtplib
    with pytest.raises(ChannelError):  # the next send sees the new answer and is refused
        smtp.send(channel(server), plain())
    assert len(server.messages) == 1


def test_a_private_attachment_url_stops_the_send_before_connecting(tls, smtp_server, receiver, dns):
    dns["files.test"] = ["10.0.0.9"]
    server = smtp_server(context=tls())
    with pytest.raises(ChannelError) as e:
        smtp.send(channel(server), plain(attachments=["https://files.test/a.pdf"]))
    assert e.value.retryable is False and server.connections == 0


@pytest.mark.parametrize("config, message", [
    ({"host": "smtp.test", "security": "none"}, "security"), ({"host": "smtp.test", "security": "ssl"}, "security"),
    ({"host": "smtp.test", "port": "abc"}, "port"), ({}, "host")])
def test_bad_configuration_is_permanent(config, message):
    with pytest.raises(ChannelError, match=message) as e:
        smtp.send(Channel(address="a@example.com", config=config), plain())
    assert e.value.retryable is False


def test_ports_default_to_587_for_starttls_and_465_for_tls(monkeypatch):
    seen = []

    def fake_pin(host, port, tls):
        seen.append((port, tls))
        raise ChannelError("stop here")

    monkeypatch.setattr(smtp, "pin", fake_pin)
    for config in ({"host": "h"}, {"host": "h", "security": "tls"}, {"host": "h", "port": 2525}):
        with pytest.raises(ChannelError):
            smtp.send(Channel(address="a@example.com", config=config), plain())
    assert seen == [(587, False), (465, True), (2525, False)]


def test_smtp_has_no_webhooks_and_ses_uses_this_adapter():
    assert smtp.verify(Channel(), Request("u", {}, b"{}")) is False and smtp.parse(Request("u", {}, b"{}")) == []
    assert ADAPTERS["ses"] is ADAPTERS["smtp"] is smtp
