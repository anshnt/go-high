import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from helpers import H, add_member, drain, due_now
from inbox_helpers import (
    add_channel,
    bodies,
    conversation,
    conversations_of,
    mailgun_in,
    only_conversation,
    sms_in,
    sql,
)
from sqlalchemy import text

from app import permissions
from app.api import seal
from app.main import app

anonymous = TestClient(app)
NUMBERS = {name: f"+1415555{i:04d}" for i, name in enumerate(["alice", "bea", "zed", "bob", "dan", "eve"], 124)}


def act(client, ws, conv_id: str, action: str, body: dict | None = None):
    return client.post(f"/api/v1/conversations/{conv_id}/{action}", json=body, headers={H: ws})


def later(days: int = 1) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def by_phone(client, ws, phone: str, **params) -> dict:
    return next(c for c in conversations_of(client, ws, limit=200, **params)["data"] if c["contact"]["phone"] == phone)


def counts(client, ws) -> dict:
    page = conversations_of(client, ws)
    return {k: v for k, v in page["counts"].items() if k != "channels"}


class World:
    """Six conversations: Alice, Bea, Zed (SMS) and Bob (email) open, Dan closed, Eve snoozed. Alice and Bob are
    assigned to the signed-in admin, Bea to a member; Zed is unassigned."""

    def __init__(self, client, ws, ids, db):
        self.client, self.ws, self.db = client, ws, db
        self.sms, self.mail = add_channel(client, ws), add_channel(client, ws, "mailgun")
        self.member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
        self.me = client.get("/api/me").json()["user"]["id"]
        self.member_id = self.member.get("/api/me").json()["user"]["id"]
        sms_in(anonymous, self.sms, NUMBERS["alice"], "Where is my invoice 1043?")
        sms_in(anonymous, self.sms, NUMBERS["bea"], "Do you ship to Canada?")
        sms_in(anonymous, self.sms, NUMBERS["zed"], "Pricing question")
        mailgun_in(anonymous, self.mail, "bob@example.net", "Refund request", "I would like a refund")
        sms_in(anonymous, self.sms, NUMBERS["dan"], "Thanks, all sorted")
        sms_in(anonymous, self.sms, NUMBERS["eve"], "Call me next week")
        self.alice, self.bea, self.zed = (by_phone(client, ws, NUMBERS[n]) for n in ("alice", "bea", "zed"))
        self.dan, self.eve = by_phone(client, ws, NUMBERS["dan"]), by_phone(client, ws, NUMBERS["eve"])
        self.bob = next(c for c in conversations_of(client, ws)["data"] if c["contact"]["email"] == "bob@example.net")
        assert act(client, ws, self.alice["id"], "assign", {"user_id": self.me}).status_code == 200
        assert act(client, ws, self.bob["id"], "assign", {"user_id": self.me}).status_code == 200
        assert act(client, ws, self.bea["id"], "assign", {"user_id": self.member_id}).status_code == 200
        assert act(client, ws, self.dan["id"], "close").status_code == 200
        assert act(client, ws, self.eve["id"], "snooze", {"until": later(7)}).status_code == 200


def test_every_view_and_its_count_come_from_one_call(crm, db):
    client, ws, ids = crm
    w = World(client, ws, ids, db)
    page = conversations_of(client, ws)
    assert page["counts"] == {"mine": 2, "unassigned": 1, "open": 4, "snoozed": 1, "closed": 1, "unread": 5,
                              "channels": {w.sms["id"]: 3, w.mail["id"]: 1}}
    views = {v: {c["id"] for c in conversations_of(client, ws, view=v)["data"]}
             for v in ("mine", "unassigned", "open", "snoozed", "closed", "unread")}
    assert views == {"mine": {w.alice["id"], w.bob["id"]}, "unassigned": {w.zed["id"]},
                     "open": {w.alice["id"], w.bea["id"], w.zed["id"], w.bob["id"]}, "snoozed": {w.eve["id"]},
                     "closed": {w.dan["id"]},
                     "unread": {w.alice["id"], w.bea["id"], w.zed["id"], w.bob["id"], w.eve["id"]}}
    assert conversations_of(client, ws)["data"] == conversations_of(client, ws, view="open")["data"]  # the default
    assert {c["id"] for c in conversations_of(client, ws, channel_id=w.mail["id"])["data"]} == {w.bob["id"]}
    sms_open = conversations_of(client, ws, view="open", channel_id=w.sms["id"])["data"]
    assert {c["id"] for c in sms_open} == {w.alice["id"], w.bea["id"], w.zed["id"]}
    assert {c["id"] for c in conversations_of(client, ws, view="closed", channel_id=w.mail["id"])["data"]} == set()
    theirs = w.member.get("/api/v1/conversations", params={"view": "mine"}, headers={H: ws}).json()
    assert [c["id"] for c in theirs["data"]] == [w.bea["id"]] and theirs["counts"]["mine"] == 1
    assert client.get("/api/v1/conversations", params={"view": "nope"}, headers={H: ws}).status_code == 422
    assert client.get("/api/v1/conversations", params={"limit": 0}, headers={H: ws}).status_code == 422


def test_a_conversation_in_the_list_has_what_the_inbox_needs_to_draw_a_row(crm, db):
    client, ws, ids = crm
    w = World(client, ws, ids, db)
    row_ = next(c for c in conversations_of(client, ws)["data"] if c["id"] == w.alice["id"])
    assert set(row_) == {"id", "contact", "status", "assignee_id", "team_id", "snooze_until", "last_message_at",
                         "last_inbound_at", "channel_id", "channel_kind", "preview", "last_direction", "unread",
                         "last_seq", "visitor", "created_at"}
    assert row_["contact"] == {"id": row_["contact"]["id"], "display_name": NUMBERS["alice"], "email": None,
                               "phone": NUMBERS["alice"]}
    assert (row_["status"], row_["assignee_id"], row_["channel_id"], row_["channel_kind"], row_["preview"],
            row_["last_direction"], row_["unread"], row_["last_seq"], row_["visitor"]) == (
        "open", w.me, w.sms["id"], "sms", "Where is my invoice 1043?", "in", True, 1, False)
    detail = conversation(client, ws, w.alice["id"])
    assert set(detail) == set(row_) | {"last_read_seq", "messages"} and detail["last_read_seq"] == 0
    assert set(detail["messages"]) == {"data", "next_cursor"}
    assert set(detail["messages"]["data"][0]) == {
        "id", "conversation_id", "seq", "direction", "channel_id", "kind", "subject", "body", "html", "attachments",
        "status", "error", "provider_message_id", "thread_ref", "sent_by", "occurred_at", "created_at", "segments",
        "estimated_cost"}


def test_unread_is_per_user_and_a_read_mark_only_moves_forward(crm, db):
    client, ws, ids = crm
    w = World(client, ws, ids, db)
    assert counts(client, ws)["unread"] == 5 and counts(w.member, ws)["unread"] == 5
    assert act(client, ws, w.alice["id"], "read").json() == {"last_read_seq": 1}
    assert counts(client, ws)["unread"] == 4 and counts(w.member, ws)["unread"] == 5  # the member has not read it
    unread = {c["id"] for c in conversations_of(client, ws, view="unread")["data"]}
    assert w.alice["id"] not in unread and w.bea["id"] in unread
    assert conversation(client, ws, w.alice["id"])["unread"] is False
    sms_in(anonymous, w.sms, NUMBERS["alice"], "Hello? Still there?")
    assert conversation(client, ws, w.alice["id"])["unread"] is True and counts(client, ws)["unread"] == 5
    again = client.post(f"/api/v1/conversations/{w.alice['id']}/read", json={"seq": 1}, headers={H: ws})
    assert again.json() == {"last_read_seq": 1}  # up to the first message only: the second is still new
    assert conversation(client, ws, w.alice["id"])["unread"] is True
    assert client.post(f"/api/v1/conversations/{w.alice['id']}/read", json={"seq": 99}, headers={H: ws}
                       ).json() == {"last_read_seq": 2}  # capped at the last message
    assert client.post(f"/api/v1/conversations/{w.alice['id']}/read", json={"seq": 0}, headers={H: ws}
                       ).json() == {"last_read_seq": 2}  # never back
    assert client.post(f"/api/v1/conversations/{w.alice['id']}/read", json={"seq": -1}, headers={H: ws}
                       ).status_code == 422
    assert conversation(client, ws, w.alice["id"])["unread"] is False
    assert conversation(w.member, ws, w.alice["id"])["unread"] is True
    assert act(client, ws, w.dan["id"], "read").status_code == 200  # a closed conversation can be marked too
    assert [tuple(r) for r in sql(db, "SELECT count(*) FROM conversation_reads")] == [(2,)]


def test_the_list_pages_by_last_activity_with_a_signed_cursor(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    numbers = [f"+1415555{i:04d}" for i in range(300, 305)]
    for i, number in enumerate(numbers):
        sms_in(anonymous, channel, number, f"message {i}")
    first = conversations_of(client, ws, limit=2)
    assert [c["preview"] for c in first["data"]] == ["message 4", "message 3"] and "counts" in first
    second = conversations_of(client, ws, limit=2, cursor=first["next_cursor"])
    assert [c["preview"] for c in second["data"]] == ["message 2", "message 1"] and "counts" not in second
    third = conversations_of(client, ws, limit=2, cursor=second["next_cursor"])
    assert [c["preview"] for c in third["data"]] == ["message 0"] and third["next_cursor"] is None
    sms_in(anonymous, channel, numbers[0], "the oldest wrote again")  # moves to the top
    assert [c["preview"] for c in conversations_of(client, ws, limit=2)["data"]][0] == "the oldest wrote again"
    for bad in ("garbage", first["next_cursor"][:-3] + "abc", "e30.bad"):
        r = client.get("/api/v1/conversations", params={"cursor": bad}, headers={H: ws})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"


def test_search_finds_message_text_and_the_contacts_name_email_and_phone(crm, db):
    client, ws, ids = crm
    w = World(client, ws, ids, db)
    contact = client.get(f"/api/v1/conversations/{w.zed['id']}", headers={H: ws}).json()["contact"]["id"]
    client.patch(f"/api/v1/objects/contact/records/{contact}",
                 json={"values": {"first_name": "Zed", "last_name": "Quartermaine"}}, headers={H: ws})

    def find(q: str, **params) -> set[str]:
        return {c["id"] for c in conversations_of(client, ws, q=q, **params)["data"]}

    assert find("invoice 1043") == {w.alice["id"]}
    assert find("invoi 10") == {w.alice["id"]}  # every word as a prefix
    assert find("1043 invoice") == {w.alice["id"]}
    assert find("quartermaine") == {w.zed["id"]} and find("zed quar") == {w.zed["id"]}
    assert find("bob@example") == {w.bob["id"]} and find("refund") == {w.bob["id"]}
    assert find("+14155550124") == {w.alice["id"]} and find("+1415") >= {w.alice["id"], w.bea["id"]}
    assert find("canada") == {w.bea["id"]} and find("zzzz") == set() and find("!!!") == set()
    assert find("sorted", view="closed") == {w.dan["id"]} and find("sorted") == set()  # the open view only by default
    assert find("sorted", view="open") == set()
    assert find("invoice") == find("INVOICE") == find("  invoice  ")
    assert client.get("/api/v1/conversations", params={"q": "x" * 201}, headers={H: ws}).status_code == 422
    assert bodies(client, ws, w.alice["id"], q="invoice") == ["Where is my invoice 1043?"]
    assert bodies(client, ws, w.alice["id"], q="refund") == [] and bodies(client, ws, w.alice["id"], q="!!!") == []
    assert only_conversation(client, ws, q="quartermaine")["contact"]["display_name"] == "Zed Quartermaine"
    note = client.post(f"/api/v1/conversations/{w.bea['id']}/messages", json={"body": "internal: wholesale lead",
                                                                          "kind": "note"}, headers={H: ws})
    assert note.status_code == 201 and find("wholesale") == {w.bea["id"]}  # notes are searchable too


def test_assign_to_a_member_a_team_or_nobody(crm, db, make_user):
    client, ws, ids = crm
    w = World(client, ws, ids, db)
    other, other_ids = make_user("b@example.com")
    other_user = other.get("/api/me").json()["user"]["id"]
    team = "00000000-0000-0000-0000-0000000000aa"
    r = act(client, ws, w.zed["id"], "assign", {"user_id": w.member_id, "team_id": team})
    assert r.status_code == 200 and (r.json()["assignee_id"], r.json()["team_id"]) == (w.member_id, team)
    assert act(client, ws, w.zed["id"], "assign", {"team_id": None}).json()["assignee_id"] == w.member_id  # kept
    assert act(client, ws, w.zed["id"], "assign", {"user_id": None}).json()["assignee_id"] is None  # nobody
    for who in (other_user, "00000000-0000-0000-0000-000000000001"):
        bad = act(client, ws, w.zed["id"], "assign", {"user_id": who})
        assert bad.status_code == 422 and bad.json()["error"]["fields"] == {
            "user_id": "is not a member of this workspace"}
    assert act(client, ws, w.zed["id"], "assign", {"user_id": "nope"}).status_code == 422
    assert {c["id"] for c in conversations_of(client, ws, view="unassigned")["data"]} == {w.zed["id"]}
    changes = [r[0] for r in sql(db, "SELECT data FROM events WHERE type = 'conversation.updated' ORDER BY id")]
    mine = [c for c in changes if c["id"] == w.zed["id"]]
    assert [sorted(c["changes"]) for c in mine] == [["assignee_id", "team_id"], ["team_id"], ["assignee_id"]]
    assert mine[0]["changes"]["assignee_id"] == {"old": None, "new": w.member_id}
    assert act(client, ws, w.zed["id"], "assign", {"user_id": None}).status_code == 200
    assert len([e for e in sql(db, "SELECT 1 FROM events WHERE type = 'conversation.updated'")]) == len(changes)
    actor = sql(db, "SELECT actor_type, actor_id::text FROM events WHERE type = 'conversation.updated' "
                    "ORDER BY id DESC LIMIT 1")[0]
    assert tuple(actor) == ("user", w.me)


def test_close_and_reopen_are_idempotent_and_emit_one_event_each(crm, db):
    client, ws, ids = crm
    w = World(client, ws, ids, db)
    before = len(sql(db, "SELECT 1 FROM events WHERE type = 'conversation.updated'"))
    assert act(client, ws, w.zed["id"], "close").json()["status"] == "closed"
    assert act(client, ws, w.zed["id"], "close").json()["status"] == "closed"
    assert act(client, ws, w.zed["id"], "reopen").json()["status"] == "open"
    assert act(client, ws, w.zed["id"], "reopen").json()["status"] == "open"
    assert len(sql(db, "SELECT 1 FROM events WHERE type = 'conversation.updated'")) == before + 2
    assert act(client, ws, w.dan["id"], "reopen").json()["status"] == "open"
    assert w.dan["id"] in {c["id"] for c in conversations_of(client, ws)["data"]}


def test_snooze_hides_a_conversation_until_its_time_and_wakes_it_by_itself(crm, db):
    client, ws, ids = crm
    w = World(client, ws, ids, db)
    zed = w.zed["id"]
    for body in ({"until": "2026-10-20T10:00:00"}, {"until": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
                 {"until": later(400)}, {"until": "tomorrow"}, {}):
        assert act(client, ws, zed, "snooze", body).status_code == 422, body
    until = later(1)
    r = act(client, ws, zed, "snooze", {"until": until})
    assert r.status_code == 200 and (r.json()["status"], r.json()["snooze_until"][:16]) == (
        "snoozed", until.replace("+00:00", "")[:16])
    assert zed in {c["id"] for c in conversations_of(client, ws, view="snoozed")["data"]}
    assert zed not in {c["id"] for c in conversations_of(client, ws, view="open")["data"]}
    assert counts(client, ws)["snoozed"] == 2 and counts(client, ws)["open"] == 3
    assert act(client, ws, zed, "snooze", {"until": later(2)}).status_code == 200  # snoozed again, later
    due_now(db)
    drain()  # both wake-up jobs run, and neither is due yet
    assert conversation(client, ws, zed)["status"] == "snoozed"
    assert act(client, ws, zed, "snooze", {"until": later(1)}).status_code == 200
    db.execute(text("UPDATE conversations SET snooze_until = now() - interval '1 minute' WHERE id = :c"), {"c": zed})
    db.commit()
    due_now(db)
    drain()
    woken = conversation(client, ws, zed)
    assert (woken["status"], woken["snooze_until"]) == ("open", None)
    last = sql(db, "SELECT data, actor_type FROM events WHERE type = 'conversation.updated' "
                   "ORDER BY id DESC LIMIT 1")[0]
    assert last[0]["changes"]["status"] == {"old": "snoozed", "new": "open"} and last[1] == "system"
    assert act(client, ws, zed, "close").status_code == 200  # a stale job on a closed conversation does nothing
    assert act(client, ws, zed, "snooze", {"until": later(1)}).status_code == 200
    assert act(client, ws, zed, "reopen").status_code == 200
    db.execute(text("UPDATE conversations SET snooze_until = now() - interval '1 minute'"))
    db.commit()
    due_now(db)
    drain()
    assert conversation(client, ws, zed)["status"] == "open"


def test_a_conversations_messages_page_back_by_seq(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    for i in range(5):
        sms_in(anonymous, channel, NUMBERS["alice"], f"message {i}")
    conv = only_conversation(client, ws)
    url = f"/api/v1/conversations/{conv['id']}/messages"
    first = client.get(url, params={"limit": 2}, headers={H: ws}).json()
    assert [m["seq"] for m in first["data"]] == [5, 4] and first["next_cursor"]
    second = client.get(url, params={"limit": 2, "cursor": first["next_cursor"]}, headers={H: ws}).json()
    assert [m["seq"] for m in second["data"]] == [3, 2]
    third = client.get(url, params={"limit": 2, "cursor": second["next_cursor"]}, headers={H: ws}).json()
    assert [m["seq"] for m in third["data"]] == [1] and third["next_cursor"] is None
    detail = conversation(client, ws, conv["id"])
    assert [m["seq"] for m in detail["messages"]["data"]] == [5, 4, 3, 2, 1]
    short = client.get(f"/api/v1/conversations/{conv['id']}", params={"limit": 2}, headers={H: ws}).json()
    page = client.get(url, params={"limit": 2, "cursor": short["messages"]["next_cursor"]}, headers={H: ws}).json()
    assert [m["seq"] for m in page["data"]] == [3, 2]
    for bad in ("garbage", "e30.bad"):
        assert client.get(url, params={"cursor": bad}, headers={H: ws}).status_code == 400
    assert client.get(url, params={"cursor": seal(["not-seq", 3])}, headers={H: ws}).status_code == 400
    assert bodies(client, ws, conv["id"], q="message 3") == ["message 3"]
    assert client.get(url.replace(conv["id"], "00000000-0000-0000-0000-000000000000"), headers={H: ws}
                      ).status_code == 404


def test_the_inbox_follows_the_record_scope_of_the_permission_hooks(crm, db, monkeypatch):
    client, ws, ids = crm
    w = World(client, ws, ids, db)
    contact = client.get(f"/api/v1/conversations/{w.zed['id']}", headers={H: ws}).json()["contact"]["id"]
    client.patch(f"/api/v1/objects/contact/records/{contact}", json={"values": {"first_name": "Zed"}}, headers={H: ws})
    hidden = {"not": {"field": "display_name", "op": "contains", "value": "Zed"}}
    monkeypatch.setattr(permissions, "scope_filter", lambda ctx, obj: hidden)
    assert w.zed["id"] not in {c["id"] for c in conversations_of(client, ws)["data"]}
    assert counts(client, ws)["unassigned"] == 0 and counts(client, ws)["open"] == 3
    for method, path, body in [("GET", "", None), ("GET", "/messages", None), ("POST", "/read", None),
                               ("POST", "/close", None), ("POST", "/assign", {"user_id": w.me}),
                               ("POST", "/messages", {"body": "x"})]:
        r = client.request(method, f"/api/v1/conversations/{w.zed['id']}{path}", json=body, headers={H: ws})
        assert r.status_code == 404, (method, path)
    assert conversations_of(client, ws, q="pricing")["data"] == []


def test_a_trashed_contacts_conversation_leaves_the_list_and_the_counts_until_restored(crm, db):
    client, ws, ids = crm
    w = World(client, ws, ids, db)
    contact = w.zed["contact"]["id"]
    assert client.delete(f"/api/v1/objects/contact/records/{contact}", headers={H: ws}).status_code == 204
    assert w.zed["id"] not in {c["id"] for c in conversations_of(client, ws)["data"]}
    assert counts(client, ws)["open"] == 3 and counts(client, ws)["unread"] == 4
    client.post(f"/api/v1/objects/contact/records/{contact}/restore", headers={H: ws})
    assert counts(client, ws)["open"] == 4


def test_another_workspace_has_its_own_inbox(crm, db):
    client, ws, ids = crm
    World(client, ws, ids, db)
    second = client.post("/api/workspaces", json={"name": "Second", "brand_id": ids["brand_id"]}).json()["id"]
    assert conversations_of(client, second) == {"data": [], "next_cursor": None, "counts": {
        "mine": 0, "unassigned": 0, "open": 0, "snoozed": 0, "closed": 0, "unread": 0, "channels": {}}}
    assert json.dumps(conversations_of(client, ws)) != json.dumps(conversations_of(client, second))
