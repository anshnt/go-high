from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app

H = "X-Workspace-Id"


def add_member(db, org_id, email, org_role="member", workspace_id=None, workspace_role="member"):
    """Creates a user directly (as the owner role) and returns a signed-in client."""
    user_id = db.execute(text("INSERT INTO users (email, name) VALUES (:e, 'M') RETURNING id"), {"e": email}).scalar()
    db.execute(text("INSERT INTO org_members (user_id, org_id, role) VALUES (:u, :o, :r)"),
               {"u": user_id, "o": org_id, "r": org_role})
    if workspace_id:
        db.execute(text("INSERT INTO workspace_members (user_id, workspace_id, role) VALUES (:u, :w, :r)"),
                   {"u": user_id, "w": workspace_id, "r": workspace_role})
    db.commit()
    client = TestClient(app)
    link = client.post("/api/auth/magic-link", json={"email": email}).json()["link"]
    assert client.post("/api/auth/magic-link/consume", json={"token": link.split("token=")[1]}).status_code == 200
    return client


def test_list_and_get_my_workspaces(make_user):
    a, ids = make_user("a@example.com")
    b, other = make_user("b@example.com")
    listed = a.get("/api/workspaces").json()
    assert [w["id"] for w in listed] == [ids["workspace_id"]]
    assert listed[0]["role"] == "admin" and listed[0]["brand_id"] == ids["brand_id"]
    assert a.get(f"/api/workspaces/{ids['workspace_id']}").status_code == 200
    assert a.get(f"/api/workspaces/{other['workspace_id']}").status_code == 404
    assert a.get("/api/workspaces/not-a-uuid").status_code == 422


def test_org_admin_creates_workspaces_in_a_brand(make_user):
    a, ids = make_user("a@example.com")
    r = a.post("/api/workspaces", json={"name": "  Client two ", "brand_id": ids["brand_id"]})
    assert r.status_code == 201 and r.json()["name"] == "Client two" and r.json()["org_id"] == ids["org_id"]
    assert len(a.get("/api/workspaces").json()) == 2
    assert a.get(f"/api/workspaces/{r.json()['id']}").status_code == 200


def test_creating_in_someone_elses_brand_or_without_admin_rights_fails(make_user, db):
    a, ids = make_user("a@example.com")
    b, other = make_user("b@example.com")
    assert b.post("/api/workspaces", json={"name": "x", "brand_id": ids["brand_id"]}).status_code == 404
    assert a.post("/api/workspaces", json={"name": "x", "brand_id": "00000000-0000-0000-0000-000000000000"}
                  ).status_code == 404
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ids["workspace_id"])
    assert member.post("/api/workspaces", json={"name": "x", "brand_id": ids["brand_id"]}).status_code == 403
    assert db.execute(text("SELECT count(*) FROM workspaces")).scalar() == 2  # one per signup, nothing added


def test_workspace_header_selects_the_active_workspace(make_user):
    a, ids = make_user("a@example.com")
    b, other = make_user("b@example.com")
    assert a.get("/api/workspaces/current", headers={H: ids["workspace_id"]}).json()["id"] == ids["workspace_id"]
    assert a.get("/api/workspaces/current").status_code == 400
    assert a.get("/api/workspaces/current", headers={H: "nope"}).status_code == 400
    assert a.get("/api/workspaces/current", headers={H: other["workspace_id"]}).status_code == 404
    assert a.get("/api/workspaces/current", headers={H: "00000000-0000-0000-0000-000000000000"}).status_code == 404


def test_members_only_reach_their_own_workspaces_in_the_org(make_user, db):
    a, ids = make_user("a@example.com")
    second = a.post("/api/workspaces", json={"name": "Second", "brand_id": ids["brand_id"]}).json()["id"]
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ids["workspace_id"])
    assert [w["id"] for w in member.get("/api/workspaces").json()] == [ids["workspace_id"]]
    assert member.get("/api/workspaces").json()[0]["role"] == "member"
    assert member.get(f"/api/workspaces/{second}").status_code == 404
    assert member.get("/api/workspaces/current", headers={H: second}).status_code == 404
    assert member.get("/api/workspaces/current", headers={H: ids["workspace_id"]}).json()["role"] == "member"
    admin = add_member(db, ids["org_id"], "ad@example.com", org_role="admin")
    assert {w["id"] for w in admin.get("/api/workspaces").json()} == {ids["workspace_id"], second}
    assert admin.get("/api/workspaces/current", headers={H: second}).json()["role"] == "admin"


def test_a_member_of_two_orgs_sees_both(make_user, db):
    a, ids = make_user("a@example.com")
    b, other = make_user("b@example.com")
    user_id = db.execute(text("SELECT id FROM users WHERE email = 'a@example.com'")).scalar()
    db.execute(text("INSERT INTO org_members (user_id, org_id, role) VALUES (:u, :o, 'admin')"),
               {"u": user_id, "o": other["org_id"]})
    db.commit()
    assert {o["name"] for o in a.get("/api/me").json()["orgs"]} == {"Org of a@example.com", "Org of b@example.com"}
    assert len(a.get("/api/workspaces").json()) == 2
    assert a.get("/api/workspaces/current", headers={H: other["workspace_id"]}).status_code == 200
