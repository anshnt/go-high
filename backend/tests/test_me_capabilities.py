"""GET /api/v1/me/capabilities: what the signed-in user's role allows in one workspace, for the web app to hide what
would be refused. It is the summary the simulator gives for any user, so the two must agree."""
from fastapi.testclient import TestClient
from helpers import H, add_member, make_record, make_role, rule, user_id_of

from app.main import app
from app.permissions import ACTIONS, CAPABILITIES

PATH = "/api/v1/me/capabilities"


def mine(client, ws) -> dict:
    r = client.get(PATH, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def test_an_owner_holds_every_capability_and_sees_every_object_in_full(crm):
    client, ws, _ = crm
    me = mine(client, ws)
    assert set(me["capabilities"]) == CAPABILITIES and me["capabilities"] == sorted(CAPABILITIES)
    assert me["role"]["key"] == "owner" and me["role"]["source"] == "organization"
    contact = me["objects"]["contact"]
    assert contact["scope"] == "all" and contact["hidden_fields"] == [] and contact["readonly_fields"] == []
    assert contact["can"] == dict.fromkeys(ACTIONS, True)
    assert {"contact", "company", "deal"} <= set(me["objects"])


def test_a_viewer_reads_and_nothing_else(crm, db):
    admin, ws, ids = crm
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    me = mine(viewer, ws)
    assert me["role"]["key"] == "viewer" and me["role"]["source"] == "workspace"
    assert me["capabilities"] and all(c.endswith(".read") for c in me["capabilities"])
    assert "conversations.read" in me["capabilities"] and "messages.send" not in me["capabilities"]
    assert me["objects"]["contact"]["can"] == {"read": True, "write": False, "delete": False, "export": False}


def test_scope_hidden_and_read_only_fields_come_from_the_role_and_teams_from_membership(crm, db):
    admin, ws, ids = crm
    make_record(admin, ws, first_name="Ada", email="ada@example.com")
    make_role(admin, ws, "Scoped", copy_from="member", rules=[
        rule(), rule("contact", "own", hidden=["email"], readonly=["first_name"])])
    user = add_member(db, ids["org_id"], "s@example.com", workspace_id=ws, workspace_role="scoped")
    team = admin.post("/api/v1/teams", json={"name": "East"}, headers={H: ws}).json()
    assert admin.put(f"/api/v1/teams/{team['id']}/members/{user_id_of(user)}", headers={H: ws}).status_code == 200
    me = mine(user, ws)
    contact = me["objects"]["contact"]
    assert (contact["scope"], contact["rule_scope"]) == ("own", "own")
    assert contact["hidden_fields"] == ["email"] and contact["readonly_fields"] == ["first_name"]
    assert me["objects"]["company"]["scope"] == "all"
    assert me["teams"] == [{"id": team["id"], "name": "East", "direct": True}]


def test_it_is_the_same_summary_the_simulator_gives_for_that_user(crm, db):
    admin, ws, ids = crm
    make_role(admin, ws, "Probe", copy_from="viewer", rules=[rule("contact", "team", hidden=["email"])])
    user = add_member(db, ids["org_id"], "p@example.com", workspace_id=ws, workspace_role="probe")
    seen = admin.get("/api/v1/permissions/explain", params={"user_id": user_id_of(user)}, headers={H: ws}).json()
    me = mine(user, ws)
    assert {k: seen[k] for k in ("role", "capabilities", "teams", "objects")} == me


def test_the_workspace_decides_and_a_stranger_gets_nothing(crm, make_user):
    client, ws, _ = crm
    _, other = make_user("o@example.com")
    assert client.get(PATH, headers={H: other["workspace_id"]}).status_code == 404  # not theirs: not even a hint
    assert client.get(PATH).status_code == 400  # the workspace header is required
    assert TestClient(app).get(PATH, headers={H: ws}).status_code == 401
