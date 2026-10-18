"""The inbox under the roles of ADR 0004: the capabilities each route needs, which conversations a role sees (the
contact is in its scope, or the conversation is assigned to the user or their team), hidden contact fields, and the
Automation role that inbound messages run as."""
from fastapi.testclient import TestClient
from helpers import H, add_member, make_record, make_role, rule, user_id_of
from inbox_helpers import add_channel, conversations_of, mailgun_in, only_conversation, sms_in

from app.main import app

anonymous = TestClient(app)
ALICE, BEA = "+14155550123", "+14155550124"


def role_of(client, ws, key) -> dict:
    return next(r for r in client.get("/api/v1/roles", headers={H: ws}).json()["data"] if r["key"] == key)


def assign(client, ws, conv: dict, **body) -> int:
    return client.post(f"/api/v1/conversations/{conv['id']}/assign", json=body, headers={H: ws}).status_code


def set_capabilities(client, ws, role: dict, capabilities: list[str]) -> int:
    return client.patch(f"/api/v1/roles/{role['id']}", json={"capabilities": capabilities}, headers={H: ws}).status_code


def denied(r, capability: str) -> None:
    assert r.status_code == 403, r.text
    assert capability in r.json()["error"]["message"], r.json()


def test_the_system_roles_hold_the_inbox_capabilities_they_should(crm):
    client, ws, _ = crm
    caps = {key: set(role_of(client, ws, key)["capabilities"]) for key in
            ("owner", "admin", "manager", "member", "viewer", "automation")}
    inbox = {"conversations.read", "conversations.write", "consents.manage", "channels.manage"}
    assert inbox <= caps["owner"] and inbox <= caps["admin"]
    for key in ("manager", "member"):
        assert caps[key] & inbox == {"conversations.read", "conversations.write", "consents.manage"}, key
    assert caps["viewer"] & inbox == {"conversations.read"} and "messages.send" not in caps["viewer"]
    assert caps["automation"] & inbox == {"conversations.read", "conversations.write"}


def test_a_viewer_reads_the_inbox_and_changes_nothing_in_it(crm, db):
    admin, ws, ids = crm
    channel = add_channel(admin, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    conv = only_conversation(admin, ws)
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    url = f"/api/v1/conversations/{conv['id']}"
    assert viewer.get("/api/v1/conversations", headers={H: ws}).json()["data"][0]["id"] == conv["id"]
    assert viewer.get(url, headers={H: ws}).status_code == 200
    assert viewer.get(f"{url}/messages", headers={H: ws}).status_code == 200
    assert viewer.post(f"{url}/read", headers={H: ws}).status_code == 200  # a read mark is the viewer's own
    seen = viewer.get(f"/api/v1/channels/{channel['id']}", headers={H: ws}).json()
    assert seen["name"] == "Main line" and not {"config", "webhook_url", "secrets_set"} & seen.keys()
    estimate = viewer.post(f"/api/v1/channels/{channel['id']}/estimate", json={"body": "x"}, headers={H: ws})
    assert estimate.status_code == 200
    assert viewer.get(f"/api/v1/contacts/{conv['contact']['id']}/consents", headers={H: ws}).status_code == 200
    for method, path, body, capability in [
            ("POST", f"{url}/assign", {"user_id": None}, "conversations.write"),
            ("POST", f"{url}/close", None, "conversations.write"),
            ("POST", f"{url}/reopen", None, "conversations.write"),
            ("POST", f"{url}/snooze", {"until": "2099-01-01T00:00:00+00:00"}, "conversations.write"),
            ("POST", "/api/v1/conversations", {"contact_id": conv["contact"]["id"]}, "conversations.write"),
            ("POST", f"{url}/messages", {"body": "hi"}, "messages.send"),
            ("POST", f"{url}/messages", {"body": "a note", "kind": "note"}, "messages.send"),
            ("PUT", f"/api/v1/contacts/{conv['contact']['id']}/consents/sms", {"dnd": True}, "consents.manage"),
            ("POST", "/api/v1/channels", {"kind": "sms"}, "channels.manage"),
            ("PATCH", f"/api/v1/channels/{channel['id']}", {"name": "x"}, "channels.manage"),
            ("POST", f"/api/v1/channels/{channel['id']}/test", None, "channels.manage")]:
        denied(viewer.request(method, path, json=body, headers={H: ws}), capability)


def test_a_member_works_the_inbox_but_does_not_manage_channels(crm, db):
    admin, ws, ids = crm
    channel = add_channel(admin, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    conv = only_conversation(admin, ws)
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    url = f"/api/v1/conversations/{conv['id']}"
    me = user_id_of(member)
    assert member.post(f"{url}/assign", json={"user_id": me}, headers={H: ws}).status_code == 200
    assert member.post(f"{url}/messages", json={"body": "a note", "kind": "note"}, headers={H: ws}).status_code == 201
    assert member.post(f"{url}/messages", json={"body": "hi"}, headers={H: ws}).status_code == 201
    assert member.put(f"/api/v1/contacts/{conv['contact']['id']}/consents/sms", json={"dnd": True},
                      headers={H: ws}).status_code == 200
    denied(member.post("/api/v1/channels", json={"kind": "sms"}, headers={H: ws}), "channels.manage")


def test_a_note_needs_conversations_write_besides_the_right_to_send(crm, db):
    admin, ws, ids = crm
    channel = add_channel(admin, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    conv = only_conversation(admin, ws)
    sender = make_role(admin, ws, "Sender", capabilities=["contacts.read", "conversations.read", "messages.send"],
                       rules=[rule()])
    client = add_member(db, ids["org_id"], "s@example.com", workspace_id=ws, workspace_role=sender["key"])
    url = f"/api/v1/conversations/{conv['id']}/messages"
    assert client.post(url, json={"body": "reply", "channel_id": channel["id"]}, headers={H: ws}).status_code == 201
    denied(client.post(url, json={"body": "note", "kind": "note"}, headers={H: ws}), "conversations.write")


def test_a_role_without_conversations_read_has_no_inbox_and_no_stream(crm, db):
    admin, ws, ids = crm
    channel = add_channel(admin, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    blind = make_role(admin, ws, "Blind", capabilities=["contacts.read", "messages.send"], rules=[rule()])
    client = add_member(db, ids["org_id"], "b@example.com", workspace_id=ws, workspace_role=blind["key"])
    for path in ("/api/v1/conversations", "/api/v1/channels", f"/api/v1/channels/{channel['id']}", "/api/v1/stream"):
        denied(client.get(path, headers={H: ws}), "conversations.read")


def test_a_conversation_shows_when_its_contact_is_in_scope_or_it_is_assigned_to_the_user_or_their_team(crm, db):
    admin, ws, ids = crm
    channel = add_channel(admin, ws)
    own = make_role(admin, ws, "Own only", rules=[rule("*", "own")])
    agent = add_member(db, ids["org_id"], "agent@example.com", workspace_id=ws, workspace_role=own["key"])
    me = user_id_of(agent)
    mine = make_record(admin, ws, first_name="Mine", phone=ALICE, owner_id=me)  # in the agent's scope
    sms_in(anonymous, channel, ALICE, "from a contact I own")
    sms_in(anonymous, channel, BEA, "from a stranger")
    sms_in(anonymous, channel, "+14155550125", "from another stranger")
    by_phone = {c["contact"]["phone"]: c for c in conversations_of(admin, ws)["data"]}
    assert by_phone[ALICE]["contact"]["id"] == mine["id"]
    bea, cat = by_phone[BEA], by_phone["+14155550125"]

    def sees(client) -> set[str]:
        page = conversations_of(client, ws)
        assert page["counts"]["open"] == len(page["data"])  # the counts follow the same rule
        return {c["contact"]["phone"] for c in page["data"]}

    assert sees(agent) == {ALICE}
    for conv in (bea, cat):
        for path in ("", "/messages"):
            assert agent.get(f"/api/v1/conversations/{conv['id']}{path}", headers={H: ws}).status_code == 404
        assert agent.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "x"},
                          headers={H: ws}).status_code == 404
    # assigned to the agent: theirs to see, whatever the scope on the contact
    assert assign(admin, ws, bea, user_id=me) == 200
    assert sees(agent) == {ALICE, BEA}
    detail = agent.get(f"/api/v1/conversations/{bea['id']}", headers={H: ws})
    assert detail.status_code == 200 and detail.json()["messages"]["data"][0]["body"] == "from a stranger"
    assert agent.get(f"/api/v1/objects/contact/records/{bea['contact']['id']}", headers={H: ws}).status_code == 404
    assert counts_of(agent, ws) == {"mine": 1, "open": 2, "unassigned": 1, "unread": 2}
    # assigned to a team the agent is in
    team = admin.post("/api/v1/teams", json={"name": "Support"}, headers={H: ws}).json()["id"]
    assert admin.put(f"/api/v1/teams/{team}/members/{me}", headers={H: ws}).status_code in (200, 204)
    assert assign(admin, ws, bea, user_id=None, team_id=None) == 200
    assert sees(agent) == {ALICE}
    assert assign(admin, ws, cat, team_id=team) == 200
    assert sees(agent) == {ALICE, "+14155550125"}
    assert agent.post(f"/api/v1/conversations/{cat['id']}/close", headers={H: ws}).status_code == 200  # theirs to work
    # and the admin sees everything throughout
    assert sees(admin) == {ALICE, BEA}  # (the closed one is not open)
    assert len(conversations_of(admin, ws, view="closed")["data"]) == 1


def counts_of(client, ws) -> dict:
    page = conversations_of(client, ws)["counts"]
    return {k: page[k] for k in ("mine", "open", "unassigned", "unread")}


def test_a_role_that_hides_contact_fields_sees_them_hidden_in_the_inbox_too(crm, db):
    admin, ws, ids = crm
    channel = add_channel(admin, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    mailgun = add_channel(admin, ws, "mailgun")
    mailgun_in(anonymous, mailgun, "bob@example.net", "Hi", "hello")
    role = make_role(admin, ws, "No phones", rules=[rule(), rule("contact", "all", hidden=["phone"])])
    client = add_member(db, ids["org_id"], "n@example.com", workspace_id=ws, workspace_role=role["key"])
    rows = {c["id"]: c["contact"] for c in conversations_of(client, ws)["data"]}
    assert len(rows) == 2
    for contact in rows.values():
        assert contact["phone"] is None and contact["display_name"] is None  # a name built from a hidden field goes too
    assert any(c["email"] == "bob@example.net" for c in rows.values())
    seen = {c["contact"]["phone"] for c in conversations_of(admin, ws)["data"]}
    assert ALICE in seen  # the admin still sees it


def test_inbound_messages_run_as_the_automation_role(crm, db):
    admin, ws, ids = crm
    channel = add_channel(admin, ws)
    automation = role_of(admin, ws, "automation")
    base = [c for c in automation["capabilities"] if c != "contacts.write"]
    assert set_capabilities(admin, ws, automation, base) == 200
    r = sms_in(anonymous, channel, ALICE, "I cannot become a contact")
    assert r.status_code == 403 and "contacts.write" in r.text  # the provider is told, and tries again later
    assert conversations_of(admin, ws)["data"] == []
    assert set_capabilities(admin, ws, automation, automation["capabilities"]) == 200
    assert sms_in(anonymous, channel, ALICE, "now I can").status_code == 200
    assert only_conversation(admin, ws)["preview"] == "now I can"
