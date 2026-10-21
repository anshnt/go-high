"""Email marketing without a database (module 20): the block document and its renderer, merge fields, the signed link
tokens, DKIM, the DNS checks, the deliverability lint, the warm-up schedule and the machine open and click rules."""
import re
import uuid
from datetime import UTC, datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from types import SimpleNamespace

import dkim as dkimpy
import pytest

from app import config
from app.channels import dkim, smtp
from app.channels.base import Channel, ChannelError, Outbound
from app.marketing import dnscheck, document, domains, lint, public, tokens

DOC = {"blocks": [
    {"type": "heading", "text": "Hi {{first_name|there}}"},
    {"type": "text", "text": "Read **this** and [our _notes_](https://ex.com/a_b_c?x=1&y=2).\n\nSecond paragraph."},
    {"type": "button", "label": "Shop {{first_name}}", "url": "https://ex.com/shop"},
    {"type": "image", "src": "https://ex.com/i.png", "alt": "A photo", "href": "https://ex.com/photo"},
    {"type": "columns", "columns": [{"blocks": [{"type": "text", "text": "Left [x](https://ex.com/left)"}]},
                                    {"blocks": [{"type": "button", "label": "Right", "url": "https://ex.com/shop"}]}]},
    {"type": "divider"}, {"type": "spacer", "height": 16},
    {"type": "text", "text": "[Unsubscribe here]({{unsubscribe_url}}) or [mail us](mailto:hi@ex.com)"}]}


def render(doc=DOC, subject="Hello {{first_name|friend}}", preheader="Preview", **recipient):
    return document.render(document.parse(doc), subject, preheader, document.Recipient(**recipient))


# --- the document --------------------------------------------------------------------------------------------

def test_the_html_is_built_for_mail_clients_responsive_and_dark_mode_safe():
    out = render(values={"first_name": "Ada"}, company="Acme", address="1 Main St")
    html = out.html
    assert html.startswith("<!DOCTYPE html>") and '<meta charset="utf-8">' in html
    assert '<meta name="viewport" content="width=device-width,initial-scale=1">' in html
    # dark mode: declared, honored with prefers-color-scheme and Outlook.com's [data-ogsc], with colors for it
    assert '<meta name="color-scheme" content="light dark">' in html and "supported-color-schemes" in html
    assert "@media (prefers-color-scheme:dark)" in html and "[data-ogsc] .gh-card" in html
    assert ".gh-text{color:#e4e4e7!important}" in html and ".gh-bg{background-color:#0b0b0e!important}" in html
    # responsive: a fluid 600 px container, an MSO ghost table for Outlook, columns that stack on a phone
    assert "max-width:600px" in html and '<!--[if mso]><table role="presentation" width="600"' in html
    assert "@media screen and (max-width:620px)" in html and ".gh-col{display:block!important" in html
    assert html.count('class="gh-col"') == 2
    # layout tables are presentational for screen readers; images carry alt text and a width
    assert 'role="article"' in html and html.count('role="presentation"') >= 3
    assert '<img src="https://ex.com/i.png" alt="A photo" width="536"' in html
    # the preheader is hidden and padded so clients do not pull body text into the preview
    assert re.search(r'<div style="display:none;[^"]*">Preview(&#847;&zwnj;&nbsp;)+</div>', html)
    # the footer: who sent it, unsubscribe and preferences
    assert "Acme &middot; 1 Main St" in html and ">Unsubscribe</a>" in html and ">Email preferences</a>" in html


def test_the_plain_text_part_has_every_link_and_the_footer():
    out = render(values={"first_name": "Ada"}, company="Acme", address="1 Main St",
                 unsubscribe_url="https://u.test/x", preferences_url="https://u.test/p")
    assert out.subject == "Hello Ada"
    text = out.text
    assert text.startswith("Hi Ada\n\nRead this and our notes (https://ex.com/a_b_c?x=1&y=2).")
    assert "Shop Ada: https://ex.com/shop" in text and "[A photo] (https://ex.com/photo)" in text
    assert "Unsubscribe here (https://u.test/x)" in text and "mail us (mailto:hi@ex.com)" in text
    assert text.endswith("--\n\nAcme | 1 Main St\n\nUnsubscribe: https://u.test/x\nEmail preferences: https://u.test/p")
    assert "<" not in text.replace("<", "", 0) or "**" not in text


def test_merge_values_are_escaped_and_cannot_add_markup_or_links():
    hostile = '**bold** [x](https://evil.test) <script>alert(1)</script> _i_ " onload='
    out = render(values={"first_name": hostile})
    assert "<script>" not in out.html and "https://evil.test" not in re.findall(r'href="([^"]+)"', out.html)
    assert "&lt;script&gt;" in out.html and "**bold** [x](https://evil.test)" in out.html.replace("&quot;", '"')
    assert "<strong>bold</strong>" not in out.html
    assert hostile in out.text  # the text part is not HTML: the value as it is
    # the fallback applies when the value is empty, quoted or not
    assert render(doc={"blocks": [{"type": "text", "text": "Hi {{first_name|\"dear friend\"}}"}]}).text.startswith(
        "Hi dear friend")


def test_emphasis_never_reaches_into_a_link_address():
    out = render(doc={"blocks": [{"type": "text", "text": "[a](https://ex.com/_x_/y) _real_"}]})
    assert 'href="https://ex.com/_x_/y"' in out.html and "<em>real</em>" in out.html


def test_links_are_numbered_once_in_reading_order_and_system_links_are_not_tracked():
    doc = document.parse(DOC)
    assert document.links(doc) == ["https://ex.com/a_b_c?x=1&y=2", "https://ex.com/shop", "https://ex.com/photo",
                                   "https://ex.com/left"]
    seen = []
    out = document.render(doc, "s", "", document.Recipient(link=lambda u: seen.append(u) or f"https://t.test/{len(seen)}",
                                                           unsubscribe_url="https://u.test/x"))
    assert "https://ex.com/shop" not in out.html and 'href="https://u.test/x"' in out.html
    assert 'href="mailto:hi@ex.com"' in out.html  # mailto is left alone


@pytest.mark.parametrize("block, path, message", [
    ({"type": "button", "label": "x", "url": "javascript:alert(1)"}, "document.blocks.0.url", "http or https"),
    ({"type": "button", "label": "x", "url": "https://ex.com/{{first_name}}"}, "document.blocks.0.url", "merge"),
    ({"type": "image", "src": "http://ex.com/i.png"}, "document.blocks.0.src", "https"),
    ({"type": "text", "text": "[x](data:text/html,hi)"}, "document.blocks.0.text", "http or https"),
    ({"type": "heading", "text": ""}, "document.blocks.0.text", "at least 1"),
    ({"type": "spacer", "height": 500}, "document.blocks.0.height", "less than or equal"),
    ({"type": "marquee"}, "document.blocks.0", "tag"),
    ({"type": "columns", "columns": [{"blocks": []}]}, "document.blocks.0.columns", "at least 2"),
])
def test_a_document_that_cannot_be_sent_is_refused_with_a_path(block, path, message):
    with pytest.raises(document.Invalid) as e:
        document.parse({"blocks": [block]})
    assert path in e.value.fields, e.value.fields
    assert message in e.value.fields[path].lower() or message in e.value.fields[path], e.value.fields


def test_unknown_merge_fields_are_named():
    doc = document.parse({"blocks": [{"type": "text", "text": "Hi {{nickname}}"}]})
    with pytest.raises(document.Invalid) as e:
        document.check_merge(doc, "For {{first_name}}", "{{oops", {"first_name"})
    assert e.value.fields == {"preheader": "has a merge field that is not written {{field}} or {{field|fallback}}",
                              "document.blocks.0.text": "unknown merge field {{nickname}}"}
    document.check_merge(doc, "x", "", {"nickname"})  # known: fine


# --- tokens --------------------------------------------------------------------------------------------------

def test_tokens_are_signed_bound_to_their_kind_send_and_link_and_never_raise():
    send = uuid.uuid4()
    token = tokens.make("click", send, 7)
    assert tokens.read(token, "click") == tokens.Token("click", send, 7)
    assert tokens.read(token, "unsubscribe") is None and tokens.read(token, "open") is None  # another kind
    raw = bytearray(tokens.base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    for i in (0, 15, 17, 18, 20, len(raw) - 1):  # flip any byte: the send, the kind, the link or the signature
        forged = bytearray(raw)
        forged[i] ^= 1
        assert tokens.read(tokens.b64(bytes(forged)), "click") is None, i
    for junk in ("", "x", "!!!!", "a" * 47, token + "A", token[:-1], "é" * 40):
        assert tokens.read(junk, "click") is None


def test_tokens_depend_on_the_secret_key(monkeypatch):
    token = tokens.make("unsubscribe", uuid.uuid4())
    monkeypatch.setattr(config, "SECRET_KEY", "another-key")
    assert tokens.read(token, "unsubscribe") is None


# --- DKIM ----------------------------------------------------------------------------------------------------

def message() -> bytes:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "Acme <news@ex.com>", "bob@x.org", "Hi   there " + "long " * 30
    m["List-Unsubscribe"], m["List-Unsubscribe-Post"] = "<https://ex.com/u/t>", "List-Unsubscribe=One-Click"
    m.set_content("hello  \nworld\n\n")
    m.add_alternative("<p>hi</p>", subtype="html")
    return m.as_bytes(policy=policy.SMTP)


def test_a_dkim_signature_verifies_with_an_independent_implementation():
    private, public_key = dkim.generate()
    signed = dkim.sign(message(), "ex.com", "gh1", private)
    lookup = {b"gh1._domainkey.ex.com.": dkim.record(public_key).encode()}
    assert dkimpy.verify(signed, dnsfunc=lambda name, timeout=5: lookup.get(name))
    header = message_from_bytes(signed, policy=policy.default)["DKIM-Signature"]
    assert "c=relaxed/relaxed" in header and "a=rsa-sha256" in header and "d=ex.com" in header
    assert "list-unsubscribe:list-unsubscribe-post" in header  # RFC 8058 asks for both to be signed
    tampered = signed.replace(b"world", b"w0rld")
    assert not dkimpy.verify(tampered, dnsfunc=lambda name, timeout=5: lookup.get(name))


# --- DNS checks ----------------------------------------------------------------------------------------------

@pytest.fixture
def zone(monkeypatch):
    records: dict[str, list[str]] = {}
    monkeypatch.setattr(dnscheck, "txt", lambda name: records.get(name, []))
    return records


def test_spf_rules(zone):
    assert dnscheck.spf("ex.com", "mailgun.org")["status"] == "fail"
    zone["ex.com"] = ["v=spf1 include:mailgun.org ~all", "google-site-verification=x"]
    assert dnscheck.spf("ex.com", "mailgun.org")["status"] == "pass"
    assert "does not include amazonses.com" in dnscheck.spf("ex.com", "amazonses.com")["message"]
    zone["ex.com"] = ["v=spf1 include:mailgun.org +all"]
    assert "+all" in dnscheck.spf("ex.com", "mailgun.org")["message"]
    zone["ex.com"] = ["v=spf1 include:a.com ~all", "v=spf1 include:b.com ~all"]
    assert "more than one" in dnscheck.spf("ex.com", None)["message"]
    zone["ex.com"] = ["v=spf1 " + " ".join(f"include:{i}.com" for i in range(11)) + " ~all"]
    assert "11 DNS lookups" in dnscheck.spf("ex.com", None)["message"]
    zone["ex.com"] = ["v=spf1 include:mailgun.org"]
    assert dnscheck.spf("ex.com", "mailgun.org")["status"] == "warn"


def test_dkim_and_dmarc_rules(zone):
    _, key = dkim.generate()
    assert dnscheck.dkim_check("ex.com", "gh1", key)["status"] == "fail"
    zone["gh1._domainkey.ex.com"] = ["v=DKIM1; k=rsa; p=SOMEOTHERKEY"]
    assert "not the one shown" in dnscheck.dkim_check("ex.com", "gh1", key)["message"]
    zone["gh1._domainkey.ex.com"] = [dkim.record(key)]
    assert dnscheck.dkim_check("ex.com", "gh1", key)["status"] == "pass"
    zone["k1._domainkey.ex.com"] = ["k=rsa; p="]
    assert "revoked" in dnscheck.dkim_check("ex.com", "k1", None)["message"]
    assert "Gmail and Yahoo" in dnscheck.dmarc("news.ex.com")["message"]
    zone["_dmarc.ex.com"] = ["v=DMARC1; p=none; rua=mailto:d@ex.com"]
    assert dnscheck.dmarc("news.ex.com")["status"] == "warn"  # the organizational domain's record applies
    zone["_dmarc.news.ex.com"] = ["v=DMARC1; p=reject"]
    assert dnscheck.dmarc("news.ex.com")["status"] == "pass"
    zone["_dmarc.news.ex.com"] = ["v=DMARC1; rua=mailto:x@ex.com"]
    assert "no policy" in dnscheck.dmarc("news.ex.com")["message"]


def test_a_dns_that_does_not_answer_is_an_error_not_a_missing_record(monkeypatch):
    def down(name):
        raise dnscheck.Unreachable(f"DNS did not answer for {name}: Timeout")
    monkeypatch.setattr(dnscheck, "txt", down)
    found = dnscheck.check("ex.com", "gh1", None, None)
    assert {found[k]["status"] for k in ("spf", "dkim", "dmarc")} == {"error"} and found["verified"] is False


# --- the lint ------------------------------------------------------------------------------------------------

def codes(doc, subject="Our news"):
    d = document.parse(doc)
    return {i.code: i for i in lint.content(d, subject, document.render(d, subject, "", document.Recipient()))}


def test_the_lint_catches_what_filters_punish():
    found = codes({"blocks": [
        {"type": "text", "text": "ACT NOW: 100% free, guaranteed! [paypal.com](https://evil.test/login) "
                                 "[ip](http://203.0.113.9/x) [short](https://bit.ly/abc)"},
        {"type": "image", "src": "https://ex.com/a.png"}, {"type": "image", "src": "https://ex.com/b.png"}]},
        subject="FREE MONEY!!! Re: your account")
    assert {"spam_words", "missing_alt", "image_ratio", "mismatched_link", "ip_link", "insecure_link",
            "url_shortener", "subject_punctuation", "link_domains"} <= found.keys()
    assert '"act now"' in found["spam_words"].message and '"100% free"' in found["spam_words"].message
    assert found["mismatched_link"].message.startswith("The link text names paypal.com but it goes to evil.test")
    assert "2 images have no alt text" in found["missing_alt"].message
    assert all(i.level != "error" for i in found.values())


def test_the_lint_errors_and_quiet_content():
    assert codes({"blocks": []}, subject="")["missing_subject"].level == "error"
    assert codes({"blocks": []})["empty"].level == "error"
    assert codes({"blocks": [{"type": "image", "src": "https://ex.com/a.png", "alt": "x"}]})["image_only"]
    assert "fake_reply" in codes(DOC, subject="Fwd: hello")
    assert "long_subject" in codes(DOC, subject="x" * 90)
    big = {"blocks": [{"type": "text", "text": "word " * 990} for _ in range(25)]}
    assert "clipped" in codes(big)
    quiet = codes({"blocks": [{"type": "text", "text": "A calm update about our product, with notes and plans for "
                                                       "the season. [Read it](https://ex.com/notes)"}]})
    assert set(quiet) == {"link_domains"}  # nothing to fix; it only names where links go


# --- warm-up -------------------------------------------------------------------------------------------------

def test_the_warm_up_schedule(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_MAX_PER_HOUR", 20000)
    now = datetime(2026, 10, 20, 12, tzinfo=UTC)
    d = SimpleNamespace(hourly_limit=None, warmup_started_at=None)
    assert domains.limits(d, now)["stage"] == "not_verified" and domains.limits(d, now)["hourly"] == 0
    d.warmup_started_at = now - timedelta(hours=1)
    first = domains.limits(d, now)
    assert (first["day"], first["daily"], first["hourly"], first["stage"]) == (1, 200, 20, "warming")
    d.warmup_started_at = now - timedelta(days=8)
    assert domains.limits(d, now)["daily"] == 20000 and domains.limits(d, now)["hourly"] == 2000
    d.warmup_started_at = now - timedelta(days=40)
    assert domains.limits(d, now) | {"schedule": None} == {"hourly": 20000, "daily": None, "day": None,
                                                           "stage": "warm", "schedule": None}
    d.hourly_limit = 50
    assert domains.limits(d, now)["hourly"] == 50 and domains.limits(d, now)["stage"] == "custom"


# --- machines ------------------------------------------------------------------------------------------------

def test_machine_opens_and_clicks():
    sent, now = datetime(2026, 10, 20, 12, tzinfo=UTC), datetime(2026, 10, 20, 13, tzinfo=UTC)
    person = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko)"
    assert public.machine_open(person, sent, now) is None
    assert public.machine_open("Mozilla/5.0", sent, now) == "privacy_proxy"
    assert public.machine_open("Mozilla/5.0 (compatible; Googlebot/2.1)", sent, now) == "bot"
    assert public.machine_open("", sent, now) == "bot"
    assert public.machine_open(person, sent, sent + timedelta(seconds=1)) == "prefetch"
    gmail = "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0 (via ggpht.com GoogleImageProxy)"
    assert public.machine_open(gmail, sent, now) is None  # Gmail's proxy fetches when a person opens
    assert public.machine_click(person, "GET", sent, now, set()) is None
    assert public.machine_click(person, "HEAD", sent, now, set()) == "head"
    assert public.machine_click("Proofpoint URL Defense", "GET", sent, now, set()) == "bot"
    assert public.machine_click(person, "GET", sent, sent + timedelta(seconds=3), set()) == "too_fast"
    assert public.machine_click(person, "GET", sent, now, {1, 2}) == "burst"


# --- the SMTP adapter with what campaigns add ----------------------------------------------------------------

def test_smtp_signs_with_dkim_and_adds_campaign_headers(receiver, tls, smtp_server, dns):
    dns["smtp.test"] = ["127.0.0.1"]
    server = smtp_server(context=tls("smtp.test"))
    private, public_key = dkim.generate()
    channel = Channel(address="news@ex.com", config={"host": "smtp.test", "port": server.port, "username": "user"},
                      secrets={"password": "secret"})
    smtp.send(channel, Outbound(to="bob@x.org", from_="Acme <news@ex.com>", subject="Hi", body="text", html="<p>h</p>",
                                unsubscribe_url="https://ex.com/u/t", idempotency_key="send-1",
                                headers={"Feedback-ID": "a:b:campaign:gohigh"}, dkim=("ex.com", "gh1", private)))
    data = server.messages[0]["data"]
    lookup = {b"gh1._domainkey.ex.com.": dkim.record(public_key).encode()}
    assert dkimpy.verify(data, dnsfunc=lambda name, timeout=5: lookup.get(name))
    msg = message_from_bytes(data, policy=policy.default)
    assert msg["Feedback-ID"] == "a:b:campaign:gohigh" and msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert msg.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]


def test_a_lost_connection_while_handing_over_is_ambiguous_but_a_refusal_is_not(receiver, tls, smtp_server, dns):
    dns["smtp.test"] = ["127.0.0.1"]
    server = smtp_server(context=tls("smtp.test"))
    channel = Channel(address="news@ex.com", config={"host": "smtp.test", "port": server.port, "username": "user"},
                      secrets={"password": "secret"})
    server.replies["RCPT"] = "550 5.1.1 no such user"
    with pytest.raises(ChannelError) as e:
        smtp.send(channel, Outbound(to="bob@x.org", subject="Hi", body="x"))
    assert (e.value.code, e.value.retryable, e.value.ambiguous) == ("550", False, False)
    server.replies = {"END": "HANG"}
    assert smtp.classify(ConnectionResetError("reset"), sending=True).ambiguous is True
    assert smtp.classify(ConnectionResetError("reset"), sending=False).ambiguous is False
