import base64
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from helpers import H, drain, listing, make_record
from inbox_helpers import (
    FORM,
    META_VERIFY_TOKEN,
    TELNYX_KEY,
    add_channel,
    bodies,
    conversation,
    conversations_of,
    mailgun_event,
    mailgun_in,
    message_status,
    meta_hook,
    meta_in,
    only_conversation,
    outbound_row,
    path_of,
    point,
    public_url,
    sms_in,
    sms_status,
    sql,
    telnyx_hook,
    telnyx_in,
    twilio_hook,
)

from app.channels import twilio
from app.inbox.inbound import REPLIES
from app.main import app

anonymous = TestClient(app)
ALICE = "+14155550123"


def count(db, table: str, where: str = "true") -> int:
    return sql(db, f"SELECT count(*) FROM {table} WHERE {where}")[0][0]


def act(client, ws, conv_id: str, action: str, body: dict | None = None) -> int:
    return client.post(f"/api/v1/conversations/{conv_id}/{action}", json=body, headers={H: ws}).status_code


def bob_mails(channel: dict, sender: str = "bob@example.net", **more):
    return mailgun_in(anonymous, channel, sender, "Invoice 1043", "Where is it?", **more)


def events_of(db, type_: str) -> list[dict]:
    return [r[0] for r in sql(db, "SELECT data FROM events WHERE type = :t ORDER BY id", t=type_)]


def test_a_signed_sms_creates_the_contact_and_a_conversation(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    r = sms_in(anonymous, channel, ALICE, "Hello there")
    assert r.status_code == 200 and r.json() == {"received": 1}
    conv = only_conversation(client, ws)
    assert conv["contact"]["phone"] == ALICE and conv["contact"]["display_name"] == ALICE
    assert (conv["status"], conv["unread"], conv["preview"]) == ("open", True, "Hello there")
    assert conv["channel_kind"] == "sms"
    contacts = listing(client, ws)["data"]
    assert [c["values"] for c in contacts] == [{"phone": ALICE}] and contacts[0]["id"] == conv["contact"]["id"]
    messages = conversation(client, ws, conv["id"])["messages"]["data"]
    assert [(m["direction"], m["kind"], m["status"], m["body"], m["seq"]) for m in messages] == [
        ("in", "message", "received", "Hello there", 1)]
    types = [r[0] for r in sql(db, "SELECT type FROM events ORDER BY id")]
    assert types[-3:] == ["record.created", "conversation.created", "message.received"]
    [event] = events_of(db, "message.received")
    assert (event["channel_kind"], event["contact_created"], event["conversation_created"]) == ("sms", True, True)
    assert event["contact_id"] == conv["contact"]["id"] and event["body"] == "Hello there"
    created = sql(db, "SELECT actor_type, actor_id FROM events WHERE type = 'record.created' ORDER BY id DESC LIMIT 1")
    assert tuple(created[0]) == ("system", None)  # nobody signed in: the platform made the contact
    assert [tuple(r) for r in sql(db, "SELECT status FROM channels")] == [("active",)]  # a signed hook proves it works


def test_the_next_message_joins_the_same_conversation_in_the_order_it_arrived(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    for i in range(3):
        assert sms_in(anonymous, channel, ALICE, f"message {i}").status_code == 200
    conv = only_conversation(client, ws)
    assert len(listing(client, ws)["data"]) == 1
    assert bodies(client, ws, conv["id"]) == ["message 0", "message 1", "message 2"]
    assert [r[0] for r in sql(db, "SELECT seq FROM messages ORDER BY seq")] == [1, 2, 3]
    assert conv["preview"] == "message 2" and conversation(client, ws, conv["id"])["last_seq"] == 3
    first, second, third = events_of(db, "message.received")
    assert (first["contact_created"], first["conversation_created"]) == (True, True)
    assert (second["contact_created"], second["conversation_created"]) == (False, False)
    assert count(db, "events", "type = 'conversation.created'") == 1 and third["body"] == "message 2"


def test_provider_times_are_shown_but_the_order_is_the_order_the_server_stored(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws, "telnyx")
    later = telnyx_in(ALICE, channel["address"], "sent second, arrived first")
    later["data"]["payload"]["received_at"] = "2026-10-17T12:00:00+00:00"
    earlier = telnyx_in(ALICE, channel["address"], "sent first, arrived second")
    earlier["data"]["payload"]["received_at"] = "2026-10-17T11:00:00+00:00"
    for body in (later, earlier):
        assert telnyx_hook(anonymous, channel, body).status_code == 200
    conv = only_conversation(client, ws)
    messages = conversation(client, ws, conv["id"])["messages"]["data"]
    assert [m["body"] for m in reversed(messages)] == ["sent second, arrived first", "sent first, arrived second"]
    assert [m["occurred_at"][:13] for m in reversed(messages)] == ["2026-10-17T12", "2026-10-17T11"]


def test_an_existing_contact_is_found_by_phone_or_email_in_any_spelling(crm, db):
    client, ws, _ = crm
    ada = make_record(client, ws, first_name="Ada", last_name="Lovelace", phone="(415) 555-0123")
    grace = make_record(client, ws, first_name="Grace", email="Grace@Example.com")
    sms = add_channel(client, ws)
    mail = add_channel(client, ws, "mailgun")
    sms_in(anonymous, sms, ALICE, "from Ada")
    mailgun_in(anonymous, mail, "grace@example.com", "Hi", "from Grace")
    by_contact = {c["contact"]["id"]: c for c in conversations_of(client, ws)["data"]}
    assert set(by_contact) == {ada["id"], grace["id"]}
    assert by_contact[ada["id"]]["contact"]["display_name"] == "Ada Lovelace"
    assert by_contact[grace["id"]]["channel_kind"] == "email"
    assert len(listing(client, ws)["data"]) == 2  # no contact was made
    assert count(db, "events", "type = 'record.created'") == 2
    sms_in(anonymous, sms, ALICE, "again")
    assert len(conversations_of(client, ws)["data"]) == 2


def test_a_deleted_contact_is_not_matched_and_a_new_one_is_made(crm):
    client, ws, _ = crm
    old = make_record(client, ws, first_name="Old", phone=ALICE)
    assert client.delete(f"/api/v1/objects/contact/records/{old['id']}", headers={H: ws}).status_code == 204
    sms_in(anonymous, add_channel(client, ws), ALICE, "hello")
    [fresh] = listing(client, ws)["data"]
    assert fresh["id"] != old["id"] and fresh["values"] == {"phone": ALICE}


def test_unsigned_wrongly_signed_or_tampered_webhooks_are_refused_and_store_nothing(crm, db, caplog):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    pairs = [("MessageSid", "SM1"), ("From", ALICE), ("To", channel["address"]), ("Body", "hi"), ("NumMedia", "0")]
    body = urlencode(pairs)
    signed = {**FORM, "X-Twilio-Signature": twilio.signature("test-auth-token-not-real", public_url(channel), pairs)}
    wrong = {**FORM, "X-Twilio-Signature": twilio.signature("test-other-token-not-real", public_url(channel), pairs)}
    elsewhere = {**FORM, "X-Twilio-Signature": twilio.signature("test-auth-token-not-real",
                                                                public_url(channel) + "x", pairs)}
    with caplog.at_level(logging.WARNING, logger="inbox"):
        assert anonymous.post(path_of(channel), content=body, headers=FORM).status_code == 401  # unsigned
        assert anonymous.post(path_of(channel), content=body, headers=wrong).status_code == 401
        assert anonymous.post(path_of(channel), content=body, headers=elsewhere).status_code == 401
        assert anonymous.post(path_of(channel), content=body.replace("hi", "yo"), headers=signed).status_code == 401
        assert anonymous.post(path_of(channel), content=b"\xff\xfe", headers=signed).status_code == 401
    assert sum("refused" in r.message for r in caplog.records) == 5
    assert all("SM1" not in r.message and "test-auth" not in r.message for r in caplog.records)
    assert count(db, "messages") == count(db, "conversations") == 0 and listing(client, ws)["data"] == []
    assert anonymous.post(path_of(channel), content=body, headers=signed).status_code == 200  # the genuine one works
    assert count(db, "messages") == 1


def test_a_signed_body_that_is_not_what_the_provider_sends_is_a_400(crm):
    client, ws, _ = crm
    channel = add_channel(client, ws, "telnyx")
    r = telnyx_hook(anonymous, channel, {"data": []})
    assert r.status_code == 200 and r.json() == {"received": 0}  # an event we do not read
    stamp = str(int(time.time()))
    signature = base64.b64encode(TELNYX_KEY.sign(stamp.encode() + b"|not json")).decode()
    bad = anonymous.post(path_of(channel), content=b"not json", headers={
        "Content-Type": "application/json", "Telnyx-Timestamp": stamp, "Telnyx-Signature-Ed25519": signature})
    assert bad.status_code == 400


def test_a_retried_webhook_is_a_no_op(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    assert sms_in(anonymous, channel, ALICE, "once", sid="SMretry").status_code == 200
    sms_in(anonymous, channel, ALICE, "other", sid="SMother")
    for _ in range(3):
        assert sms_in(anonymous, channel, ALICE, "once", sid="SMretry").status_code == 200
    conv = only_conversation(client, ws)
    assert bodies(client, ws, conv["id"]) == ["once", "other"]
    assert count(db, "events", "type = 'message.received'") == 2 and count(db, "messages") == 2
    assert conv["unread"] is True
    # the same provider id on another channel is another message
    second = add_channel(client, ws, "twilio", address="+15550004444", name="Second")
    sms_in(anonymous, second, ALICE, "once", sid="SMretry")
    assert count(db, "messages") == 3


def test_concurrent_deliveries_make_one_contact_and_number_every_message_once(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    results = []

    def deliver(sid: str, body: str):
        results.append(sms_in(TestClient(app), channel, "+14155550199", body, sid=sid).status_code)

    threads = [threading.Thread(target=deliver, args=(f"SM{i % 4}", f"message {i % 4}")) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == [200] * 8
    assert count(db, "records") == 1 and count(db, "conversations") == 1
    assert [tuple(r) for r in sql(db, "SELECT seq FROM messages ORDER BY seq")] == [(1,), (2,), (3,), (4,)]
    assert count(db, "events", "type = 'message.received'") == 4


def test_a_sender_that_cannot_be_a_contact_is_logged_and_acknowledged(crm, db, caplog):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    with caplog.at_level(logging.WARNING, logger="inbox"):
        assert sms_in(anonymous, channel, "ACME", "a sender id, not a number").status_code == 200
    assert any("cannot be a contact" in r.message for r in caplog.records)
    assert count(db, "records") == 0 and count(db, "messages") == 0


def test_media_and_odd_characters_are_stored_safely(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    r = twilio_hook(anonymous, channel, MessageSid="SMmedia", From=ALICE, To=channel["address"],
                    Body="pic \x00 \U0001f600", NumMedia="1", MediaUrl0="https://api.example.com/media/1",
                    MediaContentType0="image/jpeg")
    assert r.status_code == 200
    [message] = conversation(client, ws, only_conversation(client, ws)["id"])["messages"]["data"]
    assert message["body"] == "pic  \U0001f600"
    assert message["attachments"] == [{"url": "https://api.example.com/media/1", "content_type": "image/jpeg",
                                       "name": "", "media_id": ""}]
    twilio_hook(anonymous, channel, MessageSid="SMonlymedia", From=ALICE, To=channel["address"], Body="", NumMedia="1",
                MediaUrl0="https://api.example.com/media/2")
    assert only_conversation(client, ws)["preview"] == "[attachment]"


def test_a_message_reopens_a_closed_or_snoozed_conversation_and_keeps_its_assignee(crm, db):
    client, ws, ids = crm
    channel = add_channel(client, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    conv = only_conversation(client, ws)
    me = client.get("/api/me").json()["user"]["id"]
    assert act(client, ws, conv["id"], "assign", {"user_id": me}) == 200
    for action in ("close", "snooze"):
        body = {"until": (datetime.now(UTC) + timedelta(days=30)).isoformat()} if action == "snooze" else None
        assert act(client, ws, conv["id"], action, body) == 200
        assert conversation(client, ws, conv["id"])["status"] == ("closed" if action == "close" else "snoozed")
        sms_in(anonymous, channel, ALICE, f"back after {action}")
        again = conversation(client, ws, conv["id"])
        assert (again["status"], again["assignee_id"], again["snooze_until"]) == ("open", me, None)
    assert len(conversations_of(client, ws, view="closed")["data"]) == 0
    updates = events_of(db, "conversation.updated")
    assert [u["changes"].get("status", {}).get("new") for u in updates].count("open") == 2
    assert count(db, "conversations") == 1  # always the same conversation


def test_a_telnyx_message_is_checked_with_its_ed25519_signature(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws, "telnyx")
    body = telnyx_in("+13125550001", channel["address"], "Hello from Telnyx")
    assert telnyx_hook(anonymous, channel, body, key=Ed25519PrivateKey.generate()).status_code == 401
    assert telnyx_hook(anonymous, channel, body, stamp=int(time.time()) - 600).status_code == 401  # a replay
    assert anonymous.post(path_of(channel), json=body).status_code == 401
    assert count(db, "messages") == 0
    assert telnyx_hook(anonymous, channel, body).status_code == 200
    assert telnyx_hook(anonymous, channel, body).status_code == 200  # the retry
    conv = only_conversation(client, ws)
    assert conv["contact"]["phone"] == "+13125550001" and bodies(client, ws, conv["id"]) == ["Hello from Telnyx"]


def test_a_mailgun_message_is_checked_with_its_signing_key_and_keeps_subject_and_thread(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws, "mailgun")
    assert bob_mails(channel, key="wrong").status_code == 401
    assert count(db, "messages") == 0
    assert bob_mails(channel, sender="Bob@Example.net", message_id="m1").status_code == 200
    conv = only_conversation(client, ws)
    assert conv["contact"]["email"] == "bob@example.net" and conv["channel_kind"] == "email"
    [message] = conversation(client, ws, conv["id"])["messages"]["data"]
    assert (message["subject"], message["body"], message["provider_message_id"]) == (
        "Invoice 1043", "Where is it?", "m1@mail.test")
    assert bob_mails(channel, message_id="m1").status_code == 200
    assert count(db, "messages") == 1


def test_a_meta_message_is_checked_with_the_app_secret_and_the_handshake_with_the_verify_token(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws, "meta")
    body = meta_in("16505551234", "Hola")
    assert meta_hook(anonymous, channel, body, secret="test-other-secret-not-real").status_code == 401
    assert count(db, "messages") == 0
    assert meta_hook(anonymous, channel, body).status_code == 200
    conv = only_conversation(client, ws)
    assert conv["contact"]["phone"] == "+16505551234" and conv["channel_kind"] == "whatsapp"
    url = path_of(channel)
    ok = anonymous.get(url, params={"hub.mode": "subscribe", "hub.verify_token": META_VERIFY_TOKEN,
                                    "hub.challenge": "1158201444"})
    assert (ok.status_code, ok.text) == (200, "1158201444")
    for params in ({"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
                   {"hub.mode": "subscribe", "hub.verify_token": META_VERIFY_TOKEN, "hub.challenge": "<script>"}, {}):
        assert anonymous.get(url, params=params).status_code == 403
    assert count(db, "messages") == 1


def test_an_smtp_channel_has_no_webhook_so_every_call_is_refused(crm):
    client, ws, _ = crm
    smtp = {"kind": "email", "provider": "smtp", "name": "SMTP", "address": "me@example.com",
            "config": {"host": "smtp.example.com"}}
    channel = client.post("/api/v1/channels", json=smtp, headers={H: ws}).json()
    assert channel["webhook_url"] is None
    assert anonymous.post(path_of(channel), content=b"{}", headers={"X-Anything": "x"}).status_code == 401


def test_delivery_reports_only_ever_move_a_message_forward(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    conv = only_conversation(client, ws)
    message = outbound_row(db, conv["id"], channel["id"], "SMout1", status="sent")

    def report(status: str, **more):
        assert sms_status(anonymous, channel, "SMout1", status, **more).status_code == 200
        return message_status(db, message)

    assert report("queued") == ("sent", None)  # not a step forward
    assert report("delivered") == ("delivered", None)
    assert report("sent") == ("delivered", None)  # a late report from before
    assert report("failed", ErrorCode="30006", ErrorMessage="Landline") == ("delivered", None)
    assert report("delivered") == ("delivered", None)
    assert report("read") == ("read", None)
    assert report("delivered") == ("read", None)
    changes = events_of(db, "message.status_changed")
    assert [(c["previous"], c["status"]) for c in changes] == [("sent", "delivered"), ("delivered", "read")]
    assert sms_status(anonymous, channel, "SMunknown", "delivered").status_code == 200  # nothing to move

    other = outbound_row(db, conv["id"], channel["id"], "SMout2", status="sent")
    sms_status(anonymous, channel, "SMout2", "failed", ErrorCode="30006", ErrorMessage="Landline")
    assert message_status(db, other) == ("failed", "30006 Landline")
    sms_status(anonymous, channel, "SMout2", "sent")
    assert message_status(db, other)[0] == "failed"
    sms_status(anonymous, channel, "SMout2", "delivered")  # evidence that it did arrive after all
    assert message_status(db, other) == ("delivered", None)
    assert only_conversation(client, ws)["unread"] is True  # reports are not new messages
    assert conversation(client, ws, conv["id"])["last_seq"] == 3


def test_a_delivery_report_is_signed_like_any_other_webhook(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    outbound_row(db, only_conversation(client, ws)["id"], channel["id"], "SMout1", status="sent")
    pairs = [("MessageSid", "SMout1"), ("MessageStatus", "delivered")]
    assert anonymous.post(path_of(channel), content=urlencode(pairs), headers=FORM).status_code == 401
    assert sql(db, "SELECT status FROM messages WHERE provider_message_id = 'SMout1'")[0][0] == "sent"


def test_mailgun_reports_move_a_message_and_a_complaint_is_an_opt_out(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws, "mailgun")
    mailgun_in(anonymous, channel, "bob@example.net", "Hi", "hello")
    conv = only_conversation(client, ws)
    message = outbound_row(db, conv["id"], channel["id"], "out1@mg.example.com", status="sent")
    assert mailgun_event(anonymous, channel, "delivered", "<out1@mg.example.com>").status_code == 200
    assert message_status(db, message) == ("delivered", None)
    assert count(db, "consents") == 0
    mailgun_event(anonymous, channel, "complained", "<out1@mg.example.com>")
    assert [tuple(r) for r in sql(db, "SELECT kind, status, source FROM consents")] == [
        ("email", "opted_out", "complaint")]
    assert message_status(db, message) == ("delivered", None)
    [change] = events_of(db, "consent.changed")
    assert (change["kind"], change["status"], change["source"]) == ("email", "opted_out", "complaint")
    r = client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "more mail"}, headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["code"] == "opted_out"
    assert "a spam complaint" in r.json()["error"]["message"]


def test_stop_opts_the_contact_out_of_that_channel_and_answers_once(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", '{"sid": "SMsent%d"}')
    sms_in(anonymous, channel, ALICE, "hello")
    conv = only_conversation(client, ws)
    client.post(f"/api/v1/conversations/{conv['id']}/read", headers={H: ws})
    client.post(f"/api/v1/conversations/{conv['id']}/close", headers={H: ws})
    assert sms_in(anonymous, channel, ALICE, " Stop. ", sid="SMstop").status_code == 200
    assert sms_in(anonymous, channel, ALICE, " Stop. ", sid="SMstop").status_code == 200  # retried
    [row] = sql(db, "SELECT kind, status, source FROM consents")
    assert tuple(row) == ("sms", "opted_out", "stop")
    after = conversation(client, ws, conv["id"])
    assert (after["status"], after["unread"], after["preview"]) == ("closed", False, "hello")  # the inbox never saw it
    assert count(db, "events", "type = 'message.received'") == 1
    assert [(m["direction"], m["kind"], m["body"]) for m in reversed(after["messages"]["data"])] == [
        ("in", "message", "hello"), ("in", "system", " Stop. "), ("out", "system", REPLIES["stop"])]
    drain()
    [sent] = receiver.requests
    assert parse_qs(sent["body"].decode())["Body"] == [REPLIES["stop"]]
    assert sent["headers"]["i-twilio-idempotency-token"]
    refused = client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "wait"}, headers={H: ws})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "opted_out"
    assert refused.json()["error"]["message"].startswith("Opted out by STOP on ")
    assert len(receiver.requests) == 1
    # the opt-out is for texts only: email to the same contact is another consent
    changed = events_of(db, "consent.changed")
    assert [(c["kind"], c["status"]) for c in changed] == [("sms", "opted_out")]


def test_start_opts_back_in_and_help_only_answers(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", '{"sid": "SMsent%d"}')
    sms_in(anonymous, channel, ALICE, "UNSUBSCRIBE")
    conv = only_conversation(client, ws, view="closed")  # a stranger's STOP starts no open conversation
    assert conv["preview"] == "" and conversations_of(client, ws)["data"] == []
    sms_in(anonymous, channel, ALICE, "help")
    assert [tuple(r) for r in sql(db, "SELECT status FROM consents")] == [("opted_out",)]
    sms_in(anonymous, channel, ALICE, "Start")
    assert [tuple(r) for r in sql(db, "SELECT status, source FROM consents")] == [("opted_in", "start")]
    drain()
    texts = [parse_qs(r["body"].decode())["Body"][0] for r in receiver.requests]
    assert texts == [REPLIES["stop"], REPLIES["help"], REPLIES["start"]]
    reply = {"body": "welcome back", "channel_id": channel["id"]}  # keyword lines do not pick the channel for us
    ok = client.post(f"/api/v1/conversations/{conv['id']}/messages", json=reply, headers={H: ws})
    assert ok.status_code == 201
    assert count(db, "records") == 1  # one contact all along


def test_the_auto_replies_follow_the_channel_settings(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws, config={"account_sid": "AC" + "a" * 32,
                                              "auto_replies": {"stop": "Bye from Acme", "help": ""}})
    point(monkeypatch, receiver, "twilio", '{"sid": "SMsent%d"}')
    sms_in(anonymous, channel, ALICE, "stop")
    sms_in(anonymous, channel, ALICE, "help")  # switched off: no answer
    sms_in(anonymous, channel, ALICE, "start")  # not set: the default
    drain()
    assert [parse_qs(r["body"].decode())["Body"][0] for r in receiver.requests] == ["Bye from Acme",
                                                                                   REPLIES["start"]]


def test_only_a_message_that_is_the_keyword_alone_counts(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    for body in ("please stop", "stop it now", "STOP STOP", "stopping"):
        sms_in(anonymous, channel, ALICE, body)
    assert count(db, "consents") == 0 and count(db, "messages", "kind = 'message'") == 4
    email = add_channel(client, ws, "mailgun")
    mailgun_in(anonymous, email, "alice@example.com", "stop", "STOP")  # mail has no STOP keyword
    assert count(db, "consents") == 0
    other = add_channel(client, ws, "meta")
    meta_hook(anonymous, other, meta_in("14155550123", "STOP"))  # WhatsApp does
    assert [tuple(r) for r in sql(db, "SELECT kind, status FROM consents")] == [("whatsapp", "opted_out")]


def test_a_reply_from_an_unknown_address_joins_the_thread_it_answers(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws, "mailgun")
    mailgun_in(anonymous, channel, "alice@example.com", "Quote", "Can I get a quote?", message_id="in1")
    conv = only_conversation(client, ws)
    point(monkeypatch, receiver, "mailgun", '{"id": "<out%d@mg.example.com>", "message": "Queued"}')
    r = client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "Sure, here it is"}, headers={H: ws})
    assert r.status_code == 201 and r.json()["subject"] == "Re: Quote"
    drain()
    form = parse_qs(receiver.requests[0]["body"].decode())
    assert form["h:In-Reply-To"] == ["<in1@mail.test>"] and form["h:References"] == ["<in1@mail.test>"]
    assert form["subject"] == ["Re: Quote"]
    # Alice answers from her other address: the In-Reply-To names our message
    mailgun_in(anonymous, channel, "alice.work@corp.example", "Re: Quote", "Thanks!", message_id="in2",
               in_reply_to="out0@mg.example.com")
    assert len(conversations_of(client, ws)["data"]) == 1 and len(listing(client, ws)["data"]) == 1
    messages = conversation(client, ws, conv["id"])["messages"]["data"]
    assert [m["body"] for m in reversed(messages)] == ["Can I get a quote?", "Sure, here it is", "Thanks!"]
    assert messages[0]["thread_ref"] == "out0@mg.example.com"
    # a stranger who replies to nothing we know is a new contact and conversation
    mailgun_in(anonymous, channel, "carol@example.org", "Re: something", "Hi", message_id="in3", in_reply_to="unknown")
    assert len(conversations_of(client, ws)["data"]) == 2 and len(listing(client, ws)["data"]) == 2
    # a known sender replying to a thread of someone else's stays in their own conversation
    mailgun_in(anonymous, channel, "carol@example.org", "Re: Quote", "Me too", message_id="in4",
               in_reply_to="out0@mg.example.com")
    carol = [c for c in conversations_of(client, ws)["data"] if c["contact"]["email"] == "carol@example.org"]
    assert len(carol) == 1 and carol[0]["preview"] == "Me too"
