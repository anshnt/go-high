import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

from fastapi.testclient import TestClient
from helpers import H, add_member, drain, due_now, make_record
from inbox_helpers import (
    add_channel,
    bodies,
    conversation,
    conversations_of,
    mailgun_in,
    only_conversation,
    point,
    public_url,
    sms_in,
    sql,
)
from sqlalchemy import text

from app import compliance
from app.inbox import consent
from app.main import app

anonymous = TestClient(app)
ALICE = "+14155550123"  # Los Angeles
SENT = '{"sid": "SMsent%d"}'


def start(client, ws, channel: dict | None = None, **values) -> tuple[dict, dict]:
    """A contact and their (empty) conversation; replies go out on `channel` unless another is named."""
    contact = make_record(client, ws, **{"first_name": "Alice", "phone": ALICE, **values})
    r = client.post("/api/v1/conversations", json={"contact_id": contact["id"]}, headers={H: ws})
    assert r.status_code == 201, r.text
    return contact, {**r.json(), "send_on": channel["id"] if channel else None}


def reply(client, ws, conv: dict, body: str = "hello", **more):
    if conv.get("send_on"):
        more.setdefault("channel_id", conv["send_on"])
    return client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": body, **more}, headers={H: ws})


def form(request: dict) -> dict:
    return {k: v[0] for k, v in parse_qs(request["body"].decode()).items()}


def error(r) -> dict:
    assert r.status_code == 422, r.text
    return r.json()["error"]


def configure(client, ws, channel: dict, **config) -> None:
    r = client.patch(f"/api/v1/channels/{channel['id']}", json={"config": config}, headers={H: ws})
    assert r.status_code == 200, r.text


def row(db, query: str, **params):
    return tuple(sql(db, query, **params)[0])


def last_event(db) -> str:
    return sql(db, "SELECT type FROM events ORDER BY id DESC LIMIT 1")[0][0]


def at(monkeypatch, hour: int) -> datetime:
    """Fakes the compliance clock to `hour` UTC tomorrow: on a later day, so the end of a quiet window it computes is
    still ahead of the real clock that decides when a job is due, at any time of day the suite runs."""
    when = (datetime.now(UTC) + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(consent, "clock", lambda: when)
    return when


def test_a_reply_is_queued_with_the_request_and_sent_by_the_worker_with_its_idempotency_key(
        crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    _, conv = start(client, ws, channel)
    r = reply(client, ws, conv, "Hi Alice")
    assert r.status_code == 201
    message = r.json()
    assert (message["status"], message["direction"], message["seq"], message["provider_message_id"]) == (
        "queued", "out", 1, None)
    assert message["channel_id"] == channel["id"]
    assert receiver.requests == []  # nothing leaves in the request: the job does it
    assert row(db, "SELECT count(*) FROM jobs WHERE kind = 'message.send' AND status = 'queued'") == (1,)
    assert last_event(db) == "message.queued"
    drain()
    [sent] = receiver.requests
    fields = form(sent)
    assert (fields["To"], fields["Body"], fields["From"]) == (ALICE, "Hi Alice", "+15550001111")
    assert fields["StatusCallback"] == public_url(channel)
    assert sent["headers"]["i-twilio-idempotency-token"] == message["id"]
    assert row(db, "SELECT status, provider_message_id, error FROM messages") == ("sent", "SMsent0", None)
    assert row(db, "SELECT status FROM channels") == ("active",)
    assert last_event(db) == "message.sent"
    page = conversation(client, ws, conv["id"])
    assert (page["last_direction"], page["preview"], page["unread"]) == ("out", "Hi Alice", False)
    assert [m["status"] for m in page["messages"]["data"]] == ["sent"]


def test_the_channel_defaults_to_the_one_the_conversation_last_used(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    first = add_channel(client, ws)
    second = add_channel(client, ws, "telnyx")
    point(monkeypatch, receiver, "twilio", SENT)
    sms_in(anonymous, first, ALICE, "hello")
    conv = only_conversation(client, ws)
    assert reply(client, ws, conv).json()["channel_id"] == first["id"]
    drain()
    assert len(receiver.requests) == 1
    assert reply(client, ws, conv, channel_id=second["id"]).json()["channel_id"] == second["id"]
    assert conversation(client, ws, conv["id"])["channel_id"] == second["id"]  # and the next one follows


def test_segments_and_estimated_cost_come_back_with_the_message(crm):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    _, conv = start(client, ws, channel)
    free = reply(client, ws, conv, "x" * 200).json()
    assert free["segments"] == 2 and free["estimated_cost"] == "0.000000"
    assert free["estimate"] == {"encoding": "gsm7", "segments": 2, "chars": 200, "estimated_cost": "0.000000"}
    configure(client, ws, channel, segment_cost="0.0079")
    priced = reply(client, ws, conv, "x" * 200).json()
    assert (priced["segments"], priced["estimated_cost"]) == (2, "0.015800")
    emoji = reply(client, ws, conv, "hi \U0001f600").json()["estimate"]
    assert (emoji["encoding"], emoji["segments"], emoji["estimated_cost"]) == ("ucs2", 1, "0.007900")
    stored = conversation(client, ws, conv["id"])["messages"]["data"]
    assert [(m["segments"], m["estimated_cost"]) for m in reversed(stored)] == [
        (2, "0.000000"), (2, "0.015800"), (1, "0.007900")]


def test_an_idempotency_key_makes_a_retried_post_one_message_and_one_job(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    _, conv = start(client, ws, channel)
    url = f"/api/v1/conversations/{conv['id']}/messages"
    body = {"body": "once", "channel_id": channel["id"]}
    headers = {H: ws, "Idempotency-Key": "compose-1"}
    first = client.post(url, json=body, headers=headers)
    second = client.post(url, json=body, headers=headers)
    assert first.status_code == second.status_code == 201 and second.headers["Idempotent-Replayed"] == "true"
    assert first.json() == second.json()
    assert client.post(url, json={**body, "body": "different"}, headers=headers).status_code == 409
    drain()
    assert len(receiver.requests) == 1 and row(db, "SELECT count(*) FROM messages") == (1,)


def test_a_refused_reply_names_the_reason_and_queues_nothing(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    contact, conv = start(client, ws, channel)
    db.execute(text("INSERT INTO consents (workspace_id, contact_id, kind, status, source, changed_at) "
                    "SELECT workspace_id, id, 'sms', 'opted_out', 'stop', '2026-10-03T12:00:00+00:00' "
                    "FROM records WHERE id = :c"), {"c": contact["id"]})
    db.commit()
    e = error(reply(client, ws, conv))
    assert (e["code"], e["message"]) == ("opted_out", "Opted out by STOP on Oct 3") and e["trace_id"]
    assert row(db, "SELECT count(*) FROM messages") == (0,)
    assert row(db, "SELECT count(*) FROM jobs WHERE kind = 'message.send'") == (0,)
    assert conversation(client, ws, conv["id"])["messages"]["data"] == []


def test_do_not_disturb_is_per_channel_kind_and_staff_cannot_undo_an_opt_out(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    sms, mail = add_channel(client, ws), add_channel(client, ws, "mailgun")
    point(monkeypatch, receiver, "twilio", SENT)
    point(monkeypatch, receiver, "mailgun", '{"id": "<out%d@mg>"}')
    contact, conv = start(client, ws, sms, email="alice@example.com")
    url = f"/api/v1/contacts/{contact['id']}/consents"
    assert client.get(url, headers={H: ws}).json() == {"data": []}
    assert client.put(f"{url}/sms", json={"dnd": True}, headers={H: ws}).json() == {"kind": "sms", "status": "dnd"}
    e = error(reply(client, ws, conv))
    assert (e["code"], e["message"]) == ("dnd", "Do not disturb is on for sms")
    assert reply(client, ws, conv, "by mail", channel_id=mail["id"], subject="Hi").status_code == 201  # email is free
    rows = client.get(url, headers={H: ws}).json()["data"]
    assert [(r["kind"], r["status"], r["source"]) for r in rows] == [("sms", "dnd", "manual")]
    assert client.put(f"{url}/sms", json={"dnd": False}, headers={H: ws}).json() == {"kind": "sms", "status": "none"}
    assert reply(client, ws, conv).status_code == 201
    assert client.put(f"{url}/sms", json={"dnd": False}, headers={H: ws}).json()["status"] == "none"  # nothing to clear
    sms_in(anonymous, sms, ALICE, "STOP")
    refused = client.put(f"{url}/sms", json={"dnd": False}, headers={H: ws})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "opted_out"
    assert client.put(f"{url}/sms", json={"dnd": True}, headers={H: ws}).status_code == 409
    assert [r["status"] for r in client.get(url, headers={H: ws}).json()["data"]] == ["opted_out"]
    assert client.put(f"{url}/voice", json={"dnd": True}, headers={H: ws}).status_code == 200
    assert client.put(f"{url}/nope", json={"dnd": True}, headers={H: ws}).status_code == 404
    company = make_record(client, ws, "company", name="Acme")
    assert client.get(f"/api/v1/contacts/{company['id']}/consents", headers={H: ws}).status_code == 404
    changes = [r[0] for r in sql(db, "SELECT data FROM events WHERE type = 'consent.changed' ORDER BY id")]
    assert [(c["kind"], c["status"], c["source"]) for c in changes] == [
        ("sms", "dnd", "manual"), ("sms", "none", "manual"), ("sms", "opted_out", "stop"), ("voice", "dnd", "manual")]


def test_quiet_hours_follow_the_contacts_time_zone_unless_they_wrote_recently(crm, db, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    _, la = start(client, ws, channel)
    _, sydney = start(client, ws, channel, first_name="Sydney", phone="+61412345678")
    night = at(monkeypatch, 5)  # 22:00 in Los Angeles, afternoon in Australia
    e = error(reply(client, ws, la))
    assert e["code"] == "quiet_hours" and "America/Los_Angeles" in e["message"] and "08:00" in e["message"]
    assert datetime.fromisoformat(e["fields"]["retry_at"]) == compliance.quiet_until(night, "America/Los_Angeles")
    assert reply(client, ws, sydney).status_code == 201
    configure(client, ws, channel, quiet_start="00:00", quiet_end="00:00")  # this workspace has no quiet hours
    assert reply(client, ws, la).status_code == 201
    configure(client, ws, channel, quiet_start="22:30", quiet_end="23:30")  # a narrower window: 22:00 is outside
    assert reply(client, ws, la).status_code == 201
    configure(client, ws, channel, quiet_start="21:00", quiet_end="08:00")
    _, ny = start(client, ws, channel, first_name="New York", phone="+12125550123")
    assert error(reply(client, ws, ny))["code"] == "quiet_hours"  # 01:00 in New York
    sms_in(anonymous, channel, "+13105550123", "I just wrote")  # a contact who wrote within a day may be answered
    talking = [c for c in conversations_of(client, ws)["data"] if c["contact"]["phone"] == "+13105550123"][0]
    # the message is stamped with the real clock and the compliance clock is tomorrow: put it an hour before that
    db.execute(text("UPDATE conversations SET last_inbound_at = :t WHERE id = :c"),
               {"t": night - timedelta(hours=1), "c": talking["id"]})
    db.commit()
    assert reply(client, ws, talking).status_code == 201


def test_the_contacts_time_zone_field_decides_before_the_phone_number_does(crm, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    night = at(monkeypatch, 5)  # 22:00 in Los Angeles, 16:00 in Sydney
    _, here = start(client, ws, channel, first_name="LA number, Sydney zone", timezone="australia/sydney")
    _, there = start(client, ws, channel, first_name="Sydney number, LA zone", phone="+61412345678",
                     timezone="America/Los_Angeles")
    assert reply(client, ws, here).status_code == 201  # the zone field says it is the afternoon
    e = error(reply(client, ws, there))
    assert e["code"] == "quiet_hours" and "America/Los_Angeles" in e["message"]
    assert datetime.fromisoformat(e["fields"]["retry_at"]) == compliance.quiet_until(night, "America/Los_Angeles")
    r = client.post("/api/v1/objects/contact/records", json={"values": {"first_name": "X", "timezone": "Pacific"}},
                    headers={H: ws})
    assert r.status_code == 422 and "values.timezone" in r.json()["error"]["fields"]  # only a real zone is stored


def test_email_has_no_quiet_hours(crm, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws, "mailgun")
    _, conv = start(client, ws, channel, email="alice@example.com")
    at(monkeypatch, 5)
    assert reply(client, ws, conv, "good morning", subject="Hi").status_code == 201


def test_a_frequency_cap_limits_messages_per_contact_and_channel(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    configure(client, ws, channel, frequency_cap={"max": 2, "hours": 24})
    _, conv = start(client, ws, channel)
    assert [reply(client, ws, conv, f"m{i}").status_code for i in range(2)] == [201, 201]
    e = error(reply(client, ws, conv, "m3"))
    assert (e["code"], e["message"]) == ("frequency_cap", "Frequency cap reached: 2 messages in 24 hours")
    note = reply(client, ws, conv, "note", kind="note")
    assert note.status_code == 201  # notes are not messages to the contact
    _, other = start(client, ws, channel, first_name="Bob", phone="+14155550199")
    assert reply(client, ws, other).status_code == 201  # the cap is per contact
    configure(client, ws, channel, frequency_cap={"max": 0, "hours": 24})
    assert reply(client, ws, conv, "no cap").status_code == 201
    configure(client, ws, channel, frequency_cap={"max": 3, "hours": 24})
    assert error(reply(client, ws, conv, "capped again"))["code"] == "frequency_cap"  # 3 sent in the window
    db.execute(text("UPDATE messages SET status = 'failed' WHERE conversation_id = :c"), {"c": conv["id"]})
    db.commit()
    assert reply(client, ws, conv, "failed ones do not count").status_code == 201


def test_sms_has_a_default_cap_of_ten_a_day_and_email_has_none(crm):
    client, ws, _ = crm
    sms, mail = add_channel(client, ws), add_channel(client, ws, "mailgun")
    _, conv = start(client, ws, sms, email="alice@example.com")
    assert [reply(client, ws, conv, f"m{i}").status_code for i in range(10)] == [201] * 10
    assert error(reply(client, ws, conv, "eleven"))["code"] == "frequency_cap"
    assert [reply(client, ws, conv, f"m{i}", channel_id=mail["id"], subject="s").status_code
            for i in range(12)] == [201] * 12


def test_a_reply_needs_a_channel_that_can_reach_the_contact(crm, db):
    client, ws, _ = crm
    sms, mail = add_channel(client, ws), add_channel(client, ws, "mailgun")
    _, conv = start(client, ws)
    assert error(reply(client, ws, conv))["code"] == "no_channel"
    e = error(reply(client, ws, conv, channel_id=mail["id"]))
    assert e["code"] == "no_address" and "Support mail" in e["message"]  # the contact has a phone, no email
    client.patch(f"/api/v1/channels/{sms['id']}", json={"status": "disabled"}, headers={H: ws})
    assert error(reply(client, ws, conv, channel_id=sms["id"]))["code"] == "channel_disabled"
    assert error(reply(client, ws, conv, channel_id="00000000-0000-0000-0000-000000000000"))["code"] == "no_channel"
    for body in ({"body": ""}, {"body": "   "}, {"body": "x" * 10001}, {"body": "a", "attachments": ["not a url"]},
                 {"body": "a", "kind": "voice"}):
        r = client.post(f"/api/v1/conversations/{conv['id']}/messages", json=body, headers={H: ws})
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed", body
    assert row(db, "SELECT count(*) FROM messages") == (0,)


def test_a_reply_reopens_the_conversation_and_its_sender_has_read_it(crm, db):
    client, ws, ids = crm
    channel = add_channel(client, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    conv = only_conversation(client, ws)
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    client.post(f"/api/v1/conversations/{conv['id']}/close", headers={H: ws})
    assert reply(client, ws, conv, "on it").status_code == 201
    mine = conversation(client, ws, conv["id"])
    assert (mine["status"], mine["unread"], mine["last_read_seq"]) == ("open", False, 2)
    theirs = conversation(member, ws, conv["id"])
    assert (theirs["unread"], theirs["last_read_seq"]) == (True, 0)  # the customer's message is still new to them


def test_attachments_go_to_the_provider_as_media_urls(crm, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    _, conv = start(client, ws, channel)
    r = reply(client, ws, conv, "", attachments=["https://files.example.com/a.png"])
    assert r.status_code == 201 and r.json()["attachments"] == [{"url": "https://files.example.com/a.png"}]
    drain()
    assert form(receiver.requests[0])["MediaUrl"] == "https://files.example.com/a.png"
    assert conversation(client, ws, conv["id"])["preview"] == "[attachment]"


def test_internal_notes_are_never_sent_and_only_their_author_edits_them(crm, db, receiver, monkeypatch):
    client, ws, ids = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    sms_in(anonymous, channel, ALICE, "hello")
    conv = only_conversation(client, ws)
    before = conversation(client, ws, conv["id"])
    r = reply(client, ws, conv, "call back, VIP", kind="note")
    note = r.json()
    assert (r.status_code, note["kind"], note["status"], note["direction"], note["channel_id"]) == (
        201, "note", "sent", "out", None)
    drain()
    assert receiver.requests == [] and row(db, "SELECT count(*) FROM jobs WHERE kind = 'message.send'") == (0,)
    after = conversation(client, ws, conv["id"])
    assert (after["preview"], after["last_message_at"], after["last_direction"]) == (
        before["preview"], before["last_message_at"], before["last_direction"])  # a note moves nothing in the list
    assert after["last_seq"] == 2 and bodies(client, ws, conv["id"], q="VIP") == ["call back, VIP"]
    url = f"/api/v1/conversations/{conv['id']}/messages/{note['id']}"
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    assert member.patch(url, json={"body": "mine now"}, headers={H: ws}).status_code == 403
    edited = client.patch(url, json={"body": "call back soon, VIP"}, headers={H: ws})
    assert edited.status_code == 200 and edited.json()["body"] == "call back soon, VIP"
    assert bodies(client, ws, conv["id"], q="soon") == ["call back soon, VIP"]
    first = after["messages"]["data"][-1]
    other = f"/api/v1/conversations/{conv['id']}/messages/"
    assert client.patch(other + first["id"], json={"body": "x"}, headers={H: ws}).status_code == 409  # not a note
    assert client.patch(other + conv["id"], json={"body": "x"}, headers={H: ws}).status_code == 404
    assert client.patch(url, json={"body": ""}, headers={H: ws}).status_code == 422
    types = [r[0] for r in sql(db, "SELECT type FROM events ORDER BY id")]
    assert types[-2:] == ["message.note_added", "message.updated"]
    assert reply(client, ws, conv, "", kind="note").status_code == 422


def test_a_retryable_error_is_tried_again_with_the_same_idempotency_key(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio")
    receiver.replies = [(500, b'{"message": "boom"}', {}), (200, b'{"sid": "SMok"}', {})]
    _, conv = start(client, ws, channel)
    message = reply(client, ws, conv).json()
    drain()
    assert row(db, "SELECT status, error, attempts, provider_message_id FROM messages") == (
        "queued", "HTTP 500: boom", 1, None)
    assert last_event(db) == "message.queued"
    due_now(db)
    drain()
    assert row(db, "SELECT status, error, provider_message_id FROM messages") == ("sent", None, "SMok")
    assert [r["headers"]["i-twilio-idempotency-token"] for r in receiver.requests] == [message["id"]] * 2
    types = [r[0] for r in sql(db, "SELECT type FROM events WHERE type LIKE 'message.%' ORDER BY id")]
    assert types == ["message.queued", "message.sent"]
    due_now(db)
    drain()
    assert len(receiver.requests) == 2  # done: nothing runs again


def test_a_permanent_error_fails_the_message_at_once(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio")
    receiver.replies = [(400, b'{"code": 21211, "message": "Invalid To number"}', {})]
    _, conv = start(client, ws, channel)
    reply(client, ws, conv)
    drain()
    assert row(db, "SELECT status, error FROM messages") == ("failed", "HTTP 400: Invalid To number")
    failed = [r[0] for r in sql(db, "SELECT data FROM events WHERE type = 'message.failed'")]
    assert [f["error"] for f in failed] == ["HTTP 400: Invalid To number"]
    due_now(db)
    drain()
    assert len(receiver.requests) == 1
    shown = conversation(client, ws, conv["id"])["messages"]["data"][0]
    assert (shown["status"], shown["error"]) == ("failed", "HTTP 400: Invalid To number")


def test_retries_stop_after_six_attempts(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio")
    receiver.default, receiver.replies = (503, b'{"message": "down"}', {}), []
    _, conv = start(client, ws, channel)
    reply(client, ws, conv)
    for _ in range(8):
        drain()
        due_now(db)
    assert len(receiver.requests) == 6
    assert row(db, "SELECT status, error, attempts FROM messages") == ("failed", "HTTP 503: down", 6)
    assert row(db, "SELECT count(*) FROM jobs WHERE kind = 'message.send' AND status <> 'done'") == (0,)


def test_consent_is_checked_again_when_the_job_runs(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    sms_in(anonymous, channel, ALICE, "hello")
    conv = only_conversation(client, ws)
    reply(client, ws, conv, "queued before the STOP")
    sms_in(anonymous, channel, ALICE, "STOP")  # arrives before the worker gets to the reply
    drain()
    [sent] = receiver.requests  # only the auto reply to STOP
    assert form(sent)["Body"] != "queued before the STOP"
    status, text_ = row(db, "SELECT status, error FROM messages WHERE body = 'queued before the STOP'")
    assert status == "failed" and text_.startswith("Opted out by STOP on ")


def test_a_reply_that_meets_quiet_hours_in_the_worker_waits_for_the_window(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    _, conv = start(client, ws, channel)
    reply(client, ws, conv, "evening")
    night = at(monkeypatch, 5)  # the window starts before the worker runs
    drain()
    assert receiver.requests == [] and row(db, "SELECT status FROM messages") == ("queued",)
    [(run_at,)] = [tuple(r) for r in sql(db, "SELECT run_at FROM jobs WHERE kind = 'message.send' "
                                              "AND status = 'queued'")]
    assert run_at == compliance.quiet_until(night, "America/Los_Angeles")
    at(monkeypatch, 16)
    due_now(db)
    drain()
    assert len(receiver.requests) == 1 and row(db, "SELECT status FROM messages") == ("sent",)


def test_a_channel_disabled_while_a_reply_waits_fails_it_and_sends_nothing(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    _, conv = start(client, ws, channel)
    assert reply(client, ws, conv, "queued").status_code == 201
    client.patch(f"/api/v1/channels/{channel['id']}", json={"status": "disabled"}, headers={H: ws})
    drain()
    assert receiver.requests == []
    assert row(db, "SELECT status, error FROM messages") == ("failed", "The channel is disabled")
    assert last_event(db) == "message.failed"


def test_a_contact_who_lost_their_number_while_a_reply_waits_fails_it_for_good(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    contact, conv = start(client, ws, channel)
    assert reply(client, ws, conv, "queued").status_code == 201
    r = client.patch(f"/api/v1/objects/contact/records/{contact['id']}", json={"values": {"phone": None}},
                     headers={H: ws})
    assert r.status_code == 200, r.text
    drain()
    due_now(db)
    drain()
    assert receiver.requests == []
    status, error_ = row(db, "SELECT status, error FROM messages")
    assert (status, error_) == ("failed", "the contact has no address on this channel")
    assert row(db, "SELECT count(*) FROM jobs WHERE kind = 'message.send' AND status <> 'done'") == (0,)


def test_a_send_job_for_a_message_that_is_gone_or_already_done_does_nothing(crm, db, receiver, monkeypatch):
    from app import jobs

    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    _, conv = start(client, ws, channel)
    message = reply(client, ws, conv, "once").json()
    drain()
    assert len(receiver.requests) == 1
    jobs.enqueue(db, "message.send", {"message_id": message["id"]})  # a duplicate job for a sent message
    jobs.enqueue(db, "message.send", {"message_id": "00000000-0000-0000-0000-000000000000"})
    db.commit()
    drain()
    assert len(receiver.requests) == 1
    assert row(db, "SELECT status FROM messages") == ("sent",)
    assert row(db, "SELECT count(*) FROM jobs WHERE status <> 'done'") == (0,)


def test_a_message_that_already_has_a_provider_id_is_not_sent_again(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws, "telnyx")
    point(monkeypatch, receiver, "telnyx", '{"data": {"id": "tel-%d"}}')
    _, conv = start(client, ws, channel)
    reply(client, ws, conv)
    db.execute(text("UPDATE messages SET provider_message_id = 'tel-earlier'"))
    db.commit()  # the earlier attempt got an id and then died before recording the result
    drain()
    assert receiver.requests == []
    assert row(db, "SELECT status, provider_message_id FROM messages") == ("sent", "tel-earlier")
    assert last_event(db) == "message.sent"


def test_telnyx_and_whatsapp_replies_go_out_in_their_providers_format(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    telnyx, meta = add_channel(client, ws, "telnyx"), add_channel(client, ws, "meta")
    point(monkeypatch, receiver, "telnyx", '{"data": {"id": "tel-%d"}}')
    _, conv = start(client, ws, telnyx)
    reply(client, ws, conv, "by telnyx")
    drain()
    sent = json.loads(receiver.requests[0]["body"])
    assert (sent["to"], sent["text"], sent["from"], sent["type"]) == (ALICE, "by telnyx", "+15550002222", "SMS")
    assert sent["webhook_url"] == public_url(telnyx)
    assert receiver.requests[0]["headers"]["authorization"] == "Bearer test-api-key-not-real"
    point(monkeypatch, receiver, "meta", '{"messages": [{"id": "wamid.%d"}]}')
    receiver.requests.clear()
    reply(client, ws, conv, "by whatsapp", channel_id=meta["id"])
    drain()
    sent = json.loads(receiver.requests[0]["body"])
    assert (sent["to"], sent["type"], sent["text"]["body"]) == (ALICE, "text", "by whatsapp")
    assert receiver.requests[0]["path"] == "/106540352242922/messages"
    assert [tuple(r) for r in sql(db, "SELECT provider_message_id FROM messages ORDER BY seq")] == [
        ("tel-0",), ("wamid.0",)]


def test_email_replies_thread_with_the_conversation(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws, "mailgun")
    configure(client, ws, channel, reply_to="support@example.com")
    point(monkeypatch, receiver, "mailgun", '{"id": "<out%d@mg.example.com>", "message": "Queued"}')
    mailgun_in(anonymous, channel, "alice@example.com", "Order 1043", "Where is it?", message_id="in1")
    conv = only_conversation(client, ws)
    first = reply(client, ws, conv, "Shipping today", html="<p>Shipping <b>today</b></p>").json()
    assert (first["subject"], first["thread_ref"], first["html"]) == (
        "Re: Order 1043", "in1@mail.test", "<p>Shipping <b>today</b></p>")
    drain()
    one = form(receiver.requests[0])
    assert (one["from"], one["to"], one["subject"], one["text"]) == (
        "hello@mg.example.com", "alice@example.com", "Re: Order 1043", "Shipping today")
    assert one["h:Reply-To"] == "support@example.com" and one["html"] == "<p>Shipping <b>today</b></p>"
    assert one["h:In-Reply-To"] == "<in1@mail.test>"
    mailgun_in(anonymous, channel, "alice@example.com", "Re: Order 1043", "Thanks", message_id="in2",
               in_reply_to="out0@mg.example.com")
    second = reply(client, ws, conv, "Anytime", subject="A new subject").json()
    assert second["subject"] == "A new subject" and second["thread_ref"] == "in2@mail.test"
    third = reply(client, ws, conv, "One more").json()
    assert third["subject"] == "Re: A new subject"
    drain()
    two = form(receiver.requests[1])
    assert two["h:In-Reply-To"] == "<in2@mail.test>"
    assert two["h:References"] == "<in1@mail.test> <out0@mg.example.com> <in2@mail.test>"
    assert [tuple(r) for r in sql(db, "SELECT provider_message_id FROM messages WHERE direction = 'out' "
                                      "ORDER BY seq")] == [("out0@mg.example.com",), ("out1@mg.example.com",),
                                                           ("out2@mg.example.com",)]


def test_a_conversation_of_a_trashed_contact_cannot_be_replied_to(crm):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    contact, conv = start(client, ws, channel)
    assert client.delete(f"/api/v1/objects/contact/records/{contact['id']}", headers={H: ws}).status_code == 204
    assert reply(client, ws, conv).status_code == 404
    assert client.get(f"/api/v1/conversations/{conv['id']}", headers={H: ws}).status_code == 404
    client.post(f"/api/v1/objects/contact/records/{contact['id']}/restore", headers={H: ws})
    assert reply(client, ws, conv).status_code == 201


def test_starting_a_conversation_is_idempotent_and_only_for_contacts(crm):
    client, ws, _ = crm
    contact = make_record(client, ws, first_name="Alice", phone=ALICE)
    first = client.post("/api/v1/conversations", json={"contact_id": contact["id"]}, headers={H: ws})
    again = client.post("/api/v1/conversations", json={"contact_id": contact["id"]}, headers={H: ws})
    assert (first.status_code, again.status_code) == (201, 200) and first.json()["id"] == again.json()["id"]
    assert first.json()["contact"]["id"] == contact["id"] and first.json()["status"] == "open"
    company = make_record(client, ws, "company", name="Acme")
    assert client.post("/api/v1/conversations", json={"contact_id": company["id"]}, headers={H: ws}).status_code == 404
    missing = {"contact_id": "00000000-0000-0000-0000-000000000000"}
    assert client.post("/api/v1/conversations", json=missing, headers={H: ws}).status_code == 404
