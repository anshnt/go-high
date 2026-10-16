import base64
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest

from app.channels import twilio
from app.channels.base import Channel, ChannelError, Outbound, Request

TOKEN = "12345"
CHANNEL = Channel(address="+15550001111", config={"account_sid": "AC" + "a" * 32}, secrets={"auth_token": TOKEN})
# The worked example in Twilio's "Webhooks security" docs: this URL, token 12345 and these parameters
DOC_URL = "https://example.com/myapp.php?foo=1&bar=2"
DOC_PARAMS = [("CallSid", "CA1234567890ABCDE"), ("Caller", "+14158675310"), ("Digits", "1234"),
              ("From", "+14158675310"), ("To", "+18005551212")]
DOC_SIGNATURE = "L/OH5YylLD5NRKLltdqwSvS0BnU="


def signed(url, pairs, token=TOKEN):
    body = urlencode(pairs).encode()
    return Request(url, {"Content-Type": "application/x-www-form-urlencoded",
                         "X-Twilio-Signature": twilio.signature(token, url, pairs)}, body)


def test_the_documented_example_signature():
    assert twilio.signature(TOKEN, DOC_URL, DOC_PARAMS) == DOC_SIGNATURE
    assert twilio.signature(TOKEN, DOC_URL, DOC_PARAMS[::-1]) == DOC_SIGNATURE  # order on the wire does not matter
    request = Request(DOC_URL, {"x-twilio-signature": DOC_SIGNATURE}, urlencode(DOC_PARAMS).encode())
    assert twilio.verify(CHANNEL, request)


def test_repeated_parameters_are_sorted_and_deduplicated_like_twilio_does():
    base = twilio.signature(TOKEN, "https://x.test/h", [("a", "2"), ("a", "1"), ("b", "x")])
    assert base == twilio.signature(TOKEN, "https://x.test/h", [("b", "x"), ("a", "1"), ("a", "2"), ("a", "1")])
    assert base != twilio.signature(TOKEN, "https://x.test/h", [("a", "1"), ("b", "x")])


def test_a_signed_request_verifies_and_any_change_is_refused():
    pairs = [("MessageSid", "SM1"), ("From", "+15551234567"), ("Body", "Hi é & bye")]
    assert twilio.verify(CHANNEL, signed("https://app.example.com/api/hooks/twilio/abc", pairs))
    good = signed("https://app.example.com/api/hooks/twilio/abc", pairs)
    tampered_body = Request(good.url, good.headers, good.body.replace(b"Hi", b"Yo"))
    other_url = Request("https://app.example.com/api/hooks/twilio/abd", good.headers, good.body)
    other_scheme = Request("http://app.example.com/api/hooks/twilio/abc", good.headers, good.body)
    for bad in (tampered_body, other_url, other_scheme):
        assert not twilio.verify(CHANNEL, bad)
    assert not twilio.verify(Channel(secrets={"auth_token": "other"}), good)


@pytest.mark.parametrize("headers", [{}, {"X-Twilio-Signature": ""}, {"X-Twilio-Signature": "not-the-signature"},
                                     {"X-Twilio-Signature": "L/OH5YylLD5NRKLltdqwSvS0BnU=é"}])
def test_unsigned_or_wrongly_signed_requests_are_refused(headers):
    assert not twilio.verify(CHANNEL, Request(DOC_URL, headers, urlencode(DOC_PARAMS).encode()))


def test_a_channel_without_a_token_refuses_everything():
    request = signed(DOC_URL, DOC_PARAMS, token="")
    assert not twilio.verify(Channel(), request) and not twilio.verify(Channel(secrets={"auth_token": ""}), request)


def test_behind_a_proxy_the_public_url_is_what_is_signed():
    public = "https://app.example.com/api/hooks/twilio/abc"
    request = signed(public, DOC_PARAMS)
    inside = Request("http://10.0.3.7:8000/api/hooks/twilio/abc", request.headers, request.body)
    assert not twilio.verify(CHANNEL, inside)
    assert twilio.verify(CHANNEL, inside, public_url=public)
    assert not twilio.verify(CHANNEL, inside, public_url="https://evil.example.com/api/hooks/twilio/abc")


def test_a_get_request_signs_the_url_alone():
    url = "https://app.example.com/hook?Body=hi&From=%2B1555"
    request = Request(url, {"X-Twilio-Signature": twilio.signature(TOKEN, url, [])}, b"", method="GET")
    assert twilio.verify(CHANNEL, request)


INBOUND_SMS = ("ToCountry=US&ToState=CA&SmsMessageSid=SM9f0c1a2b3c4d5e6f708192a3b4c5d6e7&NumMedia=0&ToCity=&FromZip="
               "94105&SmsSid=SM9f0c1a2b3c4d5e6f708192a3b4c5d6e7&FromState=CA&SmsStatus=received&FromCity=SAN+FRANCISCO"
               "&Body=Hello+there+%F0%9F%91%8B&FromCountry=US&To=%2B15550001111&ToZip=&NumSegments=1&MessageSid="
               "SM9f0c1a2b3c4d5e6f708192a3b4c5d6e7&AccountSid=AC" + "a" * 32
               + "&From=%2B14155550123&ApiVersion=2010-04-01")


def test_parse_an_inbound_sms():
    [m] = twilio.parse(Request("https://x.test/h", {}, INBOUND_SMS.encode()))
    assert (m.kind, m.status, m.provider_message_id) == ("message", "received", "SM9f0c1a2b3c4d5e6f708192a3b4c5d6e7")
    assert (m.from_, m.to, m.body, m.attachments) == ("+14155550123", "+15550001111", "Hello there \U0001f44b", [])
    assert m.occurred_at.tzinfo is UTC and abs((datetime.now(UTC) - m.occurred_at).total_seconds()) < 5


def test_parse_an_inbound_mms_with_two_media():
    form = urlencode([("MessageSid", "SM2"), ("From", "+14155550123"), ("To", "+15550001111"), ("Body", ""),
                      ("NumMedia", "2"), ("MediaUrl0", "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages/SM2/Media/ME0"),
                      ("MediaContentType0", "image/jpeg"), ("MediaUrl1", "https://api.twilio.com/m/ME1"),
                      ("MediaContentType1", "application/pdf")])
    [m] = twilio.parse(Request("https://x.test/h", {}, form.encode()))
    assert m.body == "" and [(a.url[-3:], a.content_type) for a in m.attachments] == [("ME0", "image/jpeg"),
                                                                                       ("ME1", "application/pdf")]


@pytest.mark.parametrize("twilio_status, ours", [("queued", "queued"), ("accepted", "queued"), ("sending", "queued"),
                                                ("sent", "sent"), ("delivered", "delivered"), ("read", "read"),
                                                ("undelivered", "failed"), ("failed", "failed")])
def test_parse_status_callbacks(twilio_status, ours):
    form = urlencode([("MessageSid", "SM3"), ("MessageStatus", twilio_status), ("SmsStatus", twilio_status),
                      ("From", "+15550001111"), ("To", "+14155550123"), ("AccountSid", "AC1")])
    [s] = twilio.parse(Request("https://x.test/h", {}, form.encode()))
    assert (s.kind, s.provider_message_id, s.status, s.error) == ("status", "SM3", ours, None)
    assert (s.from_, s.to, s.body) == ("+15550001111", "+14155550123", "")


def test_a_failed_callback_carries_the_error_code():
    form = urlencode([("MessageSid", "SM4"), ("MessageStatus", "undelivered"), ("ErrorCode", "30003"),
                      ("To", "+14155550123"), ("From", "+15550001111")])
    assert twilio.parse(Request("u", {}, form.encode()))[0].error == "30003"
    form += "&ErrorMessage=Unreachable+destination+handset"
    assert twilio.parse(Request("u", {}, form.encode()))[0].error == "30003 Unreachable destination handset"


def test_unknown_statuses_are_ignored_and_a_body_without_a_sid_is_an_error():
    assert twilio.parse(Request("u", {}, b"MessageSid=SM5&MessageStatus=something_new")) == []
    with pytest.raises(ValueError):
        twilio.parse(Request("u", {}, b"Body=hi"))
    with pytest.raises(ValueError):
        twilio.parse(Request("u", {}, b"MessageSid=SM5&NumMedia=lots"))


def test_send_posts_a_form_with_basic_auth(receiver):
    receiver.default = (201, b'{"sid": "SM77", "status": "queued", "to": "+14155550123"}', {})
    message = Outbound(to="+14155550123", body="Hello é", attachments=["https://cdn.example.com/a.jpg",
                                                                         "https://cdn.example.com/b.png"],
                       status_callback="https://app.example.com/api/hooks/twilio/abc", idempotency_key="msg-1")
    result = twilio.send(CHANNEL, message, base_url=f"http://127.0.0.1:{receiver.port}")
    assert result.provider_message_id == "SM77"
    [seen] = receiver.requests
    assert seen["path"] == f"/2010-04-01/Accounts/AC{'a' * 32}/Messages.json"
    assert seen["headers"]["authorization"] == "Basic " + base64.b64encode(f"AC{'a' * 32}:{TOKEN}".encode()).decode()
    assert seen["headers"]["content-type"] == "application/x-www-form-urlencoded"
    assert seen["headers"]["i-twilio-idempotency-token"] == "msg-1"
    assert seen["body"].decode() == urlencode([
        ("To", "+14155550123"), ("Body", "Hello é"), ("From", "+15550001111"),
        ("MediaUrl", "https://cdn.example.com/a.jpg"), ("MediaUrl", "https://cdn.example.com/b.png"),
        ("StatusCallback", "https://app.example.com/api/hooks/twilio/abc")])


def test_send_through_a_messaging_service_has_no_from(receiver):
    receiver.default = (201, b'{"sid": "SM1"}', {})
    channel = Channel(config={"account_sid": "AC1", "messaging_service_sid": "MG123"}, secrets={"auth_token": TOKEN})
    twilio.send(channel, Outbound(to="+1555", from_="+1999", body="x"), base_url=f"http://127.0.0.1:{receiver.port}")
    body = receiver.requests[0]["body"].decode()
    assert "MessagingServiceSid=MG123" in body and "From=" not in body
    assert "idempotency" not in str(receiver.requests[0]["headers"])


def test_the_account_sid_cannot_change_the_path(receiver):
    receiver.default = (201, b'{"sid": "SM1"}', {})
    channel = Channel(config={"account_sid": "AC1/../../Evil"}, secrets={"auth_token": TOKEN})
    twilio.send(channel, Outbound(to="+1"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert receiver.requests[0]["path"] == "/2010-04-01/Accounts/AC1%2F..%2F..%2FEvil/Messages.json"


@pytest.mark.parametrize("status, retryable", [(400, False), (401, False), (404, False), (429, True), (500, True),
                                               (503, True)])
def test_send_errors_are_classified(receiver, status, retryable):
    receiver.default = (status, b'{"code": 21211, "message": "Invalid To number", "status": 400}', {})
    with pytest.raises(ChannelError) as e:
        twilio.send(CHANNEL, Outbound(to="x"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is retryable and e.value.code == "21211" and "Invalid To number" in str(e.value)
    assert TOKEN not in str(e.value)


def test_send_without_credentials_or_a_sid_in_the_answer_is_permanent(receiver):
    with pytest.raises(ChannelError) as e:
        twilio.send(Channel(config={"account_sid": "AC1"}), Outbound(to="x"), base_url="http://127.0.0.1:9")
    assert e.value.retryable is False and "auth_token" in str(e.value)
    receiver.default = (200, b"{}", {})
    with pytest.raises(ChannelError) as e:
        twilio.send(CHANNEL, Outbound(to="x"), base_url=f"http://127.0.0.1:{receiver.port}")
    assert e.value.retryable is False  # accepted, but no id: a retry could send twice
