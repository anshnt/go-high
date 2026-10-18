import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import H, drain, make_record
from inbox_helpers import add_channel, conversation, conversations_of, only_conversation, sms_in, sql
from sqlalchemy import text

from app import config
from app.api import seal
from app.inbox import chat
from app.main import app

anonymous = TestClient(app)
WIDGET = Path(chat.__file__).parent / "widget.js"


def base(key: str) -> str:
    return f"/api/public/chat/{key}"


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def session(key: str, client=anonymous) -> dict:
    r = client.post(f"{base(key)}/session")
    assert r.status_code == 200, r.text
    return r.json()


def say(key: str, token: str, body: str, client=anonymous, **more):
    return client.post(f"{base(key)}/messages", json={"body": body, **more}, headers=auth(token))


def poll(key: str, token: str, after: int = 0, client=anonymous) -> list[dict]:
    r = client.get(f"{base(key)}/messages", params={"after": after}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def count(db, table: str, where: str = "true") -> int:
    return sql(db, f"SELECT count(*) FROM {table} WHERE {where}")[0][0]


@pytest.fixture
def widget(crm):
    client, ws, ids = crm
    channel = add_channel(client, ws, "internal", config={"title": "Ask Acme", "greeting": "Hi, how can we help?",
                                                          "color": "#112233"})
    return client, ws, channel, channel["widget_key"]


def minute_has_room() -> None:
    """The limits count per clock minute: do not start a counting test just before one ends."""
    left = 60 - time.time() % 60
    if left < 8:
        time.sleep(left + 0.2)


def test_the_widget_script_is_small_vanilla_and_safe_about_storage():
    source = WIDGET.read_text(encoding="utf-8")
    assert len(source.encode()) < 30_000
    lines = [line for line in source.splitlines() if "localStorage." in line]
    assert len(lines) == 2 and all("try" in line for line in lines)  # every access is guarded
    assert source.count("innerHTML") == 1 and "eval(" not in source and "document.write" not in source
    assert "import " not in source and "require(" not in source and "http://" not in source
    node = shutil.which("node")
    if node:
        done = subprocess.run([node, "--check", str(WIDGET)], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr


def test_widget_js_is_served_to_any_page_and_cached(crm):
    r = anonymous.get("/widget.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
    assert "max-age" in r.headers["cache-control"] and r.content == WIDGET.read_bytes()
    assert "/widget.js" not in anonymous.get("/api/openapi.json").text  # a script, not an API route


def test_a_visitors_chat_end_to_end(widget, db):
    client, ws, channel, key = widget
    start = session(key)
    assert (start["title"], start["greeting"], start["color"]) == ("Ask Acme", "Hi, how can we help?", "#112233")
    assert count(db, "records") == 0 and count(db, "conversations") == 0  # a session stores nothing about them
    first = say(key, start["token"], "Hi, do you have the blue one in stock?")
    assert first.status_code == 200 and first.json() == {"ok": True, "seq": 1}
    conv = only_conversation(client, ws)
    assert conv["visitor"] is True and conv["channel_kind"] == "webchat" and conv["unread"] is True
    assert conv["contact"]["display_name"].startswith("Visitor ") and conv["contact"]["email"] is None
    assert conv["preview"] == "Hi, do you have the blue one in stock?"
    say(key, start["token"], "Hello?")
    assert len(conversations_of(client, ws)["data"]) == 1 and count(db, "records") == 1
    received = [r[0] for r in sql(db, "SELECT data FROM events WHERE type = 'message.received' ORDER BY id")]
    assert [(e["channel_kind"], e["contact_created"], e["conversation_created"]) for e in received] == [
        ("webchat", True, True), ("webchat", False, False)]
    answer = client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "Yes, two left!"},
                         headers={H: ws})
    assert answer.status_code == 201 and answer.json()["status"] == "sent"  # no provider: delivered at once
    assert sql(db, "SELECT count(*) FROM jobs WHERE kind = 'message.send'")[0][0] == 0
    assert sql(db, "SELECT type FROM events ORDER BY id DESC LIMIT 1")[0][0] == "message.sent"
    client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "internal: VIP", "kind": "note"},
                headers={H: ws})
    shown = poll(key, start["token"])
    assert [(m["seq"], m["from"], m["body"]) for m in shown] == [
        (1, "visitor", "Hi, do you have the blue one in stock?"), (2, "visitor", "Hello?"),
        (3, "agent", "Yes, two left!")]
    assert set(shown[0]) == {"seq", "from", "body", "at"}  # nothing about agents, notes or other visitors
    assert [m["seq"] for m in poll(key, start["token"], after=2)] == [3]
    assert poll(key, start["token"], after=3) == []
    assert [m["body"] for m in poll(key, session(key)["token"])] == []  # another visitor has their own chat
    assert client.post(f"/api/v1/conversations/{conv['id']}/close", headers={H: ws}).status_code == 200
    say(key, start["token"], "One more thing")
    assert conversation(client, ws, conv["id"])["status"] == "open" and len(conversations_of(client, ws)["data"]) == 1


def test_a_visitor_becomes_a_contact_when_they_leave_their_details(widget, db):
    client, ws, channel, key = widget
    token = session(key)["token"]
    early = anonymous.post(f"{base(key)}/identify", json={"email": "pat@example.com"}, headers=auth(token))
    assert early.status_code == 409  # there is no conversation yet to attach them to
    say(key, token, "Hi")
    r = anonymous.post(f"{base(key)}/identify", json={"name": "Pat Smith", "email": "Pat@Example.com",
                                                      "phone": "(415) 555-0199"}, headers=auth(token))
    assert r.status_code == 200 and r.json() == {"ok": True}
    conv = only_conversation(client, ws)
    assert conv["contact"] == {"id": conv["contact"]["id"], "display_name": "Pat Smith",
                               "email": "pat@example.com", "phone": "+14155550199"}
    record = client.get(f"/api/v1/objects/contact/records/{conv['contact']['id']}", headers={H: ws}).json()
    assert record["values"] == {"first_name": "Pat", "last_name": "Smith", "email": "pat@example.com",
                                "phone": "+14155550199"}
    assert [r[0] for r in sql(db, "SELECT actor_type FROM events WHERE type = 'record.updated'")] == ["system"]
    bad = anonymous.post(f"{base(key)}/identify", json={"email": "not an email"}, headers=auth(token))
    assert bad.status_code == 422 and "email" in str(bad.json())
    assert sql(db, "SELECT count(*) FROM records")[0][0] == 1
    # an email that belongs to an existing contact stays a separate record until the dedupe queue (module 09)
    make_record(client, ws, first_name="Lee", email="lee@example.com")
    other = session(key)["token"]
    say(key, other, "Hello")
    anonymous.post(f"{base(key)}/identify", json={"email": "lee@example.com"}, headers=auth(other))
    assert sql(db, "SELECT count(*) FROM records WHERE email_norm = 'lee@example.com'")[0][0] == 2


def test_a_token_only_works_for_its_own_widget_and_before_it_expires(widget, monkeypatch):
    client, ws, channel, key = widget
    second = add_channel(client, ws, "internal")
    token = session(key)["token"]
    wrong = [("tampered", token[:-2] + ("aa" if token[-2:] != "aa" else "bb")), ("nothing", ""), ("garbage", "x.y"),
             ("a cursor", seal(["2026-10-17T00:00:00+00:00", "00000000-0000-0000-0000-000000000000"])),
             ("another kind", seal(["other", channel["id"], "00000000-0000-0000-0000-000000000000", 9999999999]))]
    for name, bad in wrong:
        assert say(key, bad, "hi").status_code == 401, name
        assert anonymous.get(f"{base(key)}/messages", headers=auth(bad)).status_code == 401, name
        assert anonymous.post(f"{base(key)}/identify", json={}, headers=auth(bad)).status_code == 401, name
    assert say(second["widget_key"], token, "hi").status_code == 401  # a token is for one widget
    assert anonymous.post(f"{base(key)}/messages", json={"body": "hi"}).status_code == 401
    monkeypatch.setattr(chat, "TOKEN_DAYS", -1)
    expired = session(key)["token"]
    assert say(key, expired, "hi").status_code == 401


def test_an_unknown_or_disabled_widget_does_not_exist_to_visitors(widget):
    client, ws, channel, key = widget
    token = session(key)["token"]
    for path, method in ((f"{base('nope')}/session", "POST"), (f"{base('nope')}/messages", "GET")):
        assert anonymous.request(method, path, headers=auth(token)).status_code == 404
    client.patch(f"/api/v1/channels/{channel['id']}", json={"status": "disabled"}, headers={H: ws})
    assert anonymous.post(f"{base(key)}/session").status_code == 404
    assert say(key, token, "hi").status_code == 404
    assert anonymous.get(f"{base(key)}/messages", headers=auth(token)).status_code == 404
    sms = add_channel(client, ws, "twilio")  # a phone channel's address is no widget key
    assert anonymous.post(f"{base(sms['address'])}/session").status_code == 404


def test_a_hidden_field_only_a_bot_fills_in_is_dropped_silently(widget, db):
    client, ws, channel, key = widget
    token = session(key)["token"]
    r = say(key, token, "buy cheap watches", website="http://spam.example")
    assert r.status_code == 200 and r.json() == {"ok": True}  # the bot is told it worked
    assert count(db, "messages") == count(db, "conversations") == count(db, "records") == 0
    say(key, token, "a real question")
    spam = anonymous.post(f"{base(key)}/identify", json={"email": "spam@example.com", "website": "x"},
                          headers=auth(token))
    assert spam.status_code == 200 and sql(db, "SELECT count(*) FROM records WHERE email_norm IS NOT NULL")[0][0] == 0


def test_a_retried_message_with_the_same_client_id_is_stored_once(widget, db):
    client, ws, channel, key = widget
    token = session(key)["token"]
    first = say(key, token, "hello", client_id="6f1c1f0e-6f6e-4a52-8b50-0c1b8f9d2e11")
    again = say(key, token, "hello", client_id="6f1c1f0e-6f6e-4a52-8b50-0c1b8f9d2e11")
    assert first.json() == {"ok": True, "seq": 1} and again.json() == {"ok": True, "seq": None}
    assert count(db, "messages") == 1 and count(db, "events", "type = 'message.received'") == 1
    assert say(key, token, "hello", client_id="6f1c1f0e-6f6e-4a52-8b50-0c1b8f9d2e12").json()["seq"] == 2


def test_message_text_is_checked(widget):
    client, ws, channel, key = widget
    token = session(key)["token"]
    for body in ("", "   ", "x" * 2001):
        assert say(key, token, body).status_code == 422, len(body)
    assert say(key, token, "x" * 2000).status_code == 200
    assert anonymous.post(f"{base(key)}/messages", json={"body": "x", "client_id": "nope"},
                          headers=auth(token)).status_code == 422


def test_requests_are_limited_per_ip_and_per_widget_key_in_postgres(widget, db, monkeypatch):
    client, ws, channel, key = widget
    minute_has_room()
    monkeypatch.setattr(config, "CHAT_SEND_PER_IP", 3)
    monkeypatch.setattr(config, "CHAT_SEND_PER_KEY", 5)
    one = TestClient(app, client=("203.0.113.9", 50000))
    two = TestClient(app, client=("203.0.113.10", 50000))
    token = session(key, one)["token"]  # 1
    assert say(key, token, "a", client=one).status_code == 200  # 2
    assert say(key, token, "b", client=one).status_code == 200  # 3
    blocked = say(key, token, "c", client=one)  # the visitor's address is at its limit
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "60"
    assert one.post(f"{base(key)}/session").status_code == 429  # sessions count like messages
    assert session(key, two)["token"]  # another address is fine ... 4
    assert say(key, token, "d", client=two).status_code == 200  # 5
    over = say(key, token, "e", client=two)  # ... until the widget as a whole is at its limit
    assert over.status_code == 429
    rows = {r[0].split(":", 1)[1]: r[1] for r in sql(db, "SELECT bucket, hits FROM chat_limits ORDER BY bucket")
            if r[0].startswith("send:")}
    assert rows[channel["id"]] == 6 and rows[f"{channel['id']}:203.0.113.9"] == 5  # refused calls were counted
    assert [m["body"] for m in poll(key, token, client=one)] == ["a", "b", "d"]  # polling has its own budget
    assert count(db, "messages") == 3
    monkeypatch.setattr(config, "CHAT_POLL_PER_IP", 2)
    assert [anonymous.get(f"{base(key)}/messages", headers=auth(token)).status_code for _ in range(3)] == [
        200, 200, 429]


def test_old_counters_are_forgotten_when_a_new_window_starts(widget, db):
    client, ws, channel, key = widget
    db.execute(text("INSERT INTO chat_limits (workspace_id, bucket, window_start, hits) "
                    "SELECT workspace_id, 'send:old', now() - interval '3 hours', 9 FROM channels"))
    db.commit()
    assert count(db, "chat_limits", "bucket = 'send:old'") == 1
    minute_has_room()
    session(key)
    assert count(db, "chat_limits", "bucket = 'send:old'") == 0


def test_the_chat_endpoints_answer_any_origin_and_nothing_else_does(widget):
    client, ws, channel, key = widget
    pre = anonymous.options(f"{base(key)}/messages", headers={"Origin": "https://shop.example",
                                                              "Access-Control-Request-Method": "POST",
                                                              "Access-Control-Request-Headers": "authorization"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == "*"
    assert "authorization" in pre.headers["access-control-allow-headers"]
    assert "POST" in pre.headers["access-control-allow-methods"]
    ok = anonymous.post(f"{base(key)}/session", headers={"Origin": "https://shop.example"})
    assert ok.headers["access-control-allow-origin"] == "*" and "access-control-allow-credentials" not in ok.headers
    for r in (anonymous.post(f"{base('nope')}/session"), anonymous.get(f"{base(key)}/messages")):
        assert r.status_code in (401, 404) and r.headers["access-control-allow-origin"] == "*"  # errors too
    assert "access-control-allow-origin" not in client.get("/api/v1/channels", headers={H: ws}).headers
    # the public endpoints take no cookie, so a signed-in agent's cookie from a foreign page changes nothing
    r = client.post(f"{base(key)}/session", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200


def test_an_agent_cannot_reply_in_chat_to_a_contact_who_has_no_chat_session(widget):
    client, ws, channel, key = widget
    phone = add_channel(client, ws, "twilio")
    sms_in(anonymous, phone, "+14155550123", "hello by text")
    conv = only_conversation(client, ws, view="open")
    r = client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "hi", "channel_id": channel["id"]},
                    headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_address"


def test_the_chat_reply_reaches_the_visitor_even_when_the_worker_is_down(widget, db):
    client, ws, channel, key = widget
    token = session(key)["token"]
    say(key, token, "anyone there?")
    conv = only_conversation(client, ws)
    client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "yes"}, headers={H: ws})
    assert [(m["from"], m["body"]) for m in poll(key, token)] == [("visitor", "anyone there?"), ("agent", "yes")]
    drain()  # and nothing was left queued for a provider
    assert count(db, "messages", "status = 'queued'") == 0
