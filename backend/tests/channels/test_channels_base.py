import time

import pytest

from app.channels import mail, transport
from app.channels.base import Channel, ChannelError, Outbound, Request, same


def test_headers_are_case_insensitive_and_missing_ones_are_empty():
    r = Request("https://x.test/h", {"X-Twilio-Signature": "abc"})
    assert r.header("x-twilio-signature") == "abc" and r.header("X-TWILIO-SIGNATURE") == "abc"
    assert r.header("nope") == ""


def test_query_and_urlencoded_form():
    r = Request("https://x.test/h?hub.mode=subscribe&hub.challenge=123&empty=", {"content-type": "x"},
                b"Body=hi+there%21+%C3%A9&To=%2B1555&To=%2B1666&Blank=")
    assert r.query() == {"hub.mode": "subscribe", "hub.challenge": "123", "empty": ""}
    assert r.pairs() == [("Body", "hi there! é"), ("To", "+1555"), ("To", "+1666"), ("Blank", "")]
    assert r.form()["Body"] == "hi there! é" and r.form()["To"] == "+1666"


def test_multipart_form_keeps_text_fields_in_utf8_and_skips_files():
    body = (b'--B\r\nContent-Disposition: form-data; name="recipient"\r\n\r\nbob@example.com\r\n'
            b'--B\r\nContent-Disposition: form-data; name="subject"\r\n\r\nCaf\xc3\xa9\r\n'
            b'--B\r\nContent-Disposition: form-data; name="attachment-1"; filename="a.txt"\r\n'
            b'Content-Type: text/plain\r\n\r\nhello\r\n--B--\r\n')
    r = Request("https://x.test/h", {"Content-Type": "multipart/form-data; boundary=B"}, body)
    assert r.pairs() == [("recipient", "bob@example.com"), ("subject", "Café")]


def test_garbage_bodies_do_not_crash_the_form_readers():
    assert Request("u", {"content-type": "multipart/form-data; boundary=B"}, b"not multipart").pairs() == []
    assert Request("u", {}, b"\xff\xfe=%zz").pairs()  # decoded with replacement, never an exception


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'"text"', b""])
def test_json_body_must_be_an_object(body):
    with pytest.raises(ValueError):
        Request("u", {}, body).json_body()


def test_the_channel_names_what_is_missing_and_never_retries():
    channel = Channel(config={"host": "h", "empty": ""}, secrets={"password": "p"})
    assert channel.conf("host") == "h" and channel.secret("password") == "p"
    for call in (lambda: channel.conf("port"), lambda: channel.conf("empty"), lambda: channel.secret("token")):
        with pytest.raises(ChannelError) as e:
            call()
        assert e.value.retryable is False


def test_same_compares_any_text_without_raising():
    assert same("abc", "abc") and not same("abc", "abd") and not same("abc", "ab") and same("café", "café")
    assert not same("café", "cafe")


def test_bare_ids_and_domains():
    assert mail.bare_id(" <a@b.test> ") == "a@b.test" and mail.bare_id("a@b.test") == "a@b.test"
    assert mail.domain_of("Ann <Ann@Example.COM>") == "example.com" and mail.domain_of("nothing") == ""


def test_message_ids_are_on_our_domain_and_stable_for_an_idempotency_key():
    first, second = mail.message_id("mail.example.com"), mail.message_id("mail.example.com")
    assert first != second and first.endswith("@mail.example.com") and "<" not in first
    key = "0b7c6a3e-1111-2222-3333-444455556666"
    assert mail.message_id("example.com", key) == mail.message_id("example.com", key) == f"{key}@example.com"
    assert mail.message_id("example.com", "a b<c>@d") == "a-b-c--d@example.com"  # nothing that breaks a header
    assert mail.message_id("bücher.example", "k") == "k@xn--bcher-kva.example"


@pytest.mark.parametrize("domain", ["", "a b.test", "x@y.test", "-bad.test", "a\r\nBcc: x.test"])
def test_message_id_refuses_a_domain_that_cannot_be_one(domain):
    with pytest.raises(ChannelError):
        mail.message_id(domain)


def test_thread_headers_end_with_the_message_replied_to():
    m = Outbound(to="a@b.test", in_reply_to="<p@x.test>", references=["<r1@x.test>", "r2@x.test"])
    assert mail.thread(m) == ("p@x.test", ["r1@x.test", "r2@x.test", "p@x.test"])
    m.references.append("p@x.test")
    assert mail.thread(m)[1].count("p@x.test") == 1
    assert mail.thread(Outbound(to="a@b.test")) == ("", [])


def test_plain_text_from_html():
    html = ("<style>p{color:red}</style><h1>Hi &amp; welcome</h1><p>Line one<br>Line   two</p>"
            "<script>x()</script><p>Bye</p>")
    assert mail.plain_text(html) == "Hi & welcome\n\nLine one\nLine two\n\nBye"
    assert mail.plain_text("") == ""


def test_attachments_are_fetched_with_name_and_type(receiver, files):
    files.files["/docs/report%201.pdf"] = ("application/pdf; charset=binary", b"%PDF-1")
    files.files["/blob"] = ("", b"raw")
    files.files["/photo.png"] = ("", b"\x89PNG")
    got = mail.fetch([files.url("/docs/report%201.pdf"), files.url("/blob"), files.url("/photo.png")])
    assert got == [("report 1.pdf", "application/pdf", b"%PDF-1"), ("blob", "application/octet-stream", b"raw"),
                   ("photo.png", "image/png", b"\x89PNG")]
    assert files.requests[0]["headers"]["host"] == f"127.0.0.1:{files.server.server_address[1]}"


def test_attachment_urls_go_through_the_ssrf_guard(files, dns):
    dns["files.test"] = ["10.0.0.9"]
    for url in ("https://hooks.test/a.pdf", "https://files.test/a.pdf", "https://169.254.169.254/latest/meta-data",
                files.url("/a.pdf"), "ftp://x.test/a", "https://unknown.example.org/a"):
        with pytest.raises(ChannelError) as e:
            mail.fetch([url])
        assert e.value.retryable is False and "attachment" in str(e.value)
    assert files.requests == []


@pytest.mark.parametrize("status, retryable", [(404, False), (403, False), (429, True), (503, True)])
def test_attachment_failures_are_classified(receiver, files, status, retryable):
    files.fail["/a"] = status
    with pytest.raises(ChannelError) as e:
        mail.fetch([files.url("/a")])
    assert e.value.retryable is retryable and str(status) in str(e.value)


def test_attachments_are_capped_in_total(receiver, files, monkeypatch):
    monkeypatch.setattr(mail, "MAX_ATTACHMENT_BYTES", 100)
    files.files["/a"] = ("text/plain", b"a" * 60)
    files.files["/b"] = ("text/plain", b"b" * 60)
    assert len(mail.fetch([files.url("/a")])) == 1
    with pytest.raises(ChannelError, match="over the"):
        mail.fetch([files.url("/a"), files.url("/b")])


def test_a_slow_attachment_server_is_retryable(receiver, files, monkeypatch):
    monkeypatch.setattr(mail, "FETCH_TIMEOUT", 0.3)
    files.files["/a"], files.delay = ("text/plain", b"x"), 1.5
    started = time.monotonic()
    with pytest.raises(ChannelError) as e:
        mail.fetch([files.url("/a")])
    assert e.value.retryable is True and time.monotonic() - started < 1.2


# transport

@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 410, 422, 301, 302])
def test_client_errors_and_redirects_are_permanent(receiver, status):
    receiver.default = (status, b'{"message": "no"}', {})
    with pytest.raises(ChannelError) as e:
        transport.post(receiver.url(), json={})
    assert e.value.retryable is False and str(status) in str(e.value)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_throttling_and_server_errors_are_retryable(receiver, status):
    receiver.default = (status, b"", {})
    with pytest.raises(ChannelError) as e:
        transport.post(receiver.url(), json={})
    assert e.value.retryable is True


def test_a_provider_code_can_mark_a_4xx_retryable(receiver):
    receiver.default = (400, b'{"error": {"code": 80007, "message": "Rate limit"}}', {})
    with pytest.raises(ChannelError) as e:
        transport.post(receiver.url(), json={}, retry_codes=frozenset({"80007"}))
    assert (e.value.retryable, e.value.code) == (True, "80007")
    with pytest.raises(ChannelError) as e:
        transport.post(receiver.url(), json={})
    assert e.value.retryable is False


def test_a_timeout_and_a_refused_connection_are_retryable(receiver):
    receiver.delay = 2
    started = time.monotonic()
    with pytest.raises(ChannelError) as e:
        transport.post(receiver.url(), json={}, timeout=0.3)
    assert e.value.retryable is True and time.monotonic() - started < 1.5
    with pytest.raises(ChannelError) as e:
        transport.post("http://127.0.0.1:9/", json={}, timeout=1)
    assert e.value.retryable is True


def test_success_returns_the_json_object_and_junk_becomes_empty(receiver):
    receiver.replies = [(201, b'{"id": "x"}', {}), (200, b"<html>", {}), (200, b"[1]", {}), (200, b"", {})]
    assert transport.post(receiver.url(), json={}) == {"id": "x"}
    assert [transport.post(receiver.url(), json={}) for _ in range(3)] == [{}, {}, {}]


def test_the_request_encodings(receiver):
    transport.post(receiver.url("/j"), json={"a": [1, "é"]}, headers={"Authorization": "Bearer t"})
    transport.post(receiver.url("/f"), form=[("To", "+1"), ("MediaUrl", "u1"), ("MediaUrl", "u2")])
    transport.post(receiver.url("/m?x=1"), form=[("from", "a@b.test")],
                   files=[("attachment", 'a"b.txt', "text/plain", b"hi")])
    j, f, m = receiver.requests
    assert j["headers"]["content-type"] == "application/json" and j["headers"]["authorization"] == "Bearer t"
    assert j["body"] == b'{"a": [1, "\\u00e9"]}'
    assert f["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert f["body"] == b"To=%2B1&MediaUrl=u1&MediaUrl=u2"
    assert m["path"] == "/m?x=1" and m["headers"]["content-type"].startswith("multipart/form-data; boundary=")
    boundary = m["headers"]["content-type"].split("boundary=")[1].encode()
    assert (b'Content-Disposition: form-data; name="from"\r\n\r\na@b.test\r\n' in m["body"]
            and b'name="attachment"; filename="a%22b.txt"\r\nContent-Type: text/plain\r\n\r\nhi\r\n' in m["body"]
            and m["body"].endswith(b"--" + boundary + b"--\r\n"))


@pytest.mark.parametrize("body, expected", [
    ({"code": 21211, "message": "Invalid 'To'", "status": 400}, ("21211", "Invalid 'To'")),  # Twilio, Mailgun
    ({"errors": [{"code": "40310", "title": "Invalid", "detail": "bad to"}]}, ("40310", "bad to")),  # Telnyx
    ({"errors": [{"code": "40310", "title": "Invalid"}]}, ("40310", "Invalid")),
    ({"error": {"code": 190, "message": "Invalid token"}}, ("190", "Invalid token")),  # Meta
    ({"errors": []}, ("", "")), ({"error": "text"}, ("", "")), ({}, ("", "")),
])
def test_error_shapes_of_the_four_providers(body, expected):
    assert transport.explain(body) == expected


def test_basic_auth_header():
    assert transport.basic("AC1", "tok") == "Basic QUMxOnRvaw=="
