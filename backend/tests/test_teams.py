"""Teams through the API: names are unique per workspace, the tree stays a tree, membership is for people of the
workspace, and one workspace never reaches another's teams or people."""
from helpers import H, add_member, audit, user_id_of

TEAMS = "/api/v1/teams"


def team(client, ws, name, parent=None) -> dict:
    r = client.post(TEAMS, json={"name": name, "parent_team_id": parent}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_team_name_is_unique_in_a_workspace_when_made_and_when_renamed(crm, make_user):
    admin, ws, _ = crm
    east, west = team(admin, ws, "East"), team(admin, ws, "West")
    r = admin.post(TEAMS, json={"name": "East"}, headers={H: ws})
    assert r.status_code == 409 and r.json()["error"]["fields"] == {"name": "is already used"}
    r = admin.patch(f"{TEAMS}/{west['id']}", json={"name": "East"}, headers={H: ws})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    assert admin.get(f"{TEAMS}/{west['id']}", headers={H: ws}).json()["name"] == "West"  # the clash changed nothing
    r = admin.patch(f"{TEAMS}/{west['id']}", json={"name": None}, headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"name": "cannot be null"}
    assert admin.post(TEAMS, json={"name": "   "}, headers={H: ws}).status_code == 422
    same = admin.patch(f"{TEAMS}/{east['id']}", json={"name": "East"}, headers={H: ws})
    assert same.status_code == 200
    assert [e["type"] for e in audit(admin, ws) if e["type"].startswith("team.")] == ["team.created", "team.created"]
    other, ids = make_user("b@example.com")  # another workspace may use the same name
    assert other.post(TEAMS, json={"name": "East"}, headers={H: ids["workspace_id"]}).status_code == 201


def test_a_parent_must_be_a_team_of_this_workspace(crm, make_user):
    admin, ws, _ = crm
    other, ids = make_user("b@example.com")
    theirs = team(other, ids["workspace_id"], "Theirs")
    r = admin.post(TEAMS, json={"name": "Mine", "parent_team_id": theirs["id"]}, headers={H: ws})
    assert r.status_code == 422 and "not a team of this workspace" in r.json()["error"]["fields"]["parent_team_id"]
    mine = team(admin, ws, "Mine")
    r = admin.patch(f"{TEAMS}/{mine['id']}", json={"parent_team_id": theirs["id"]}, headers={H: ws})
    assert r.status_code == 422
    top = admin.patch(f"{TEAMS}/{mine['id']}", json={"parent_team_id": None}, headers={H: ws})
    assert top.status_code == 200 and top.json()["parent_team_id"] is None


def test_another_workspaces_team_is_not_found_whatever_is_done_to_it(crm, make_user):
    admin, ws, _ = crm
    other, ids = make_user("b@example.com")
    theirs = team(other, ids["workspace_id"], "Theirs")
    me = user_id_of(admin)
    for method, path, body in (("GET", f"{TEAMS}/{theirs['id']}", None),
                               ("PATCH", f"{TEAMS}/{theirs['id']}", {"name": "Taken over"}),
                               ("DELETE", f"{TEAMS}/{theirs['id']}", None),
                               ("PUT", f"{TEAMS}/{theirs['id']}/members/{me}", None),
                               ("DELETE", f"{TEAMS}/{theirs['id']}/members/{user_id_of(other)}", None)):
        r = admin.request(method, path, json=body, headers={H: ws})
        assert r.status_code == 404, (method, path, r.text)
    assert [t["name"] for t in admin.get(TEAMS, headers={H: ws}).json()["data"]] == []
    seen = other.get(f"{TEAMS}/{theirs['id']}", headers={H: ids["workspace_id"]}).json()
    assert seen["name"] == "Theirs" and seen["members"] == []


def test_only_people_of_the_workspace_join_a_team_and_joining_twice_is_one_membership(crm, make_user, db):
    admin, ws, ids = crm
    east = team(admin, ws, "East")
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    outsider = add_member(db, ids["org_id"], "o@example.com")  # in the organization, not in this workspace
    stranger, _ = make_user("s@example.com")  # another organization
    for person in (outsider, stranger):
        r = admin.put(f"{TEAMS}/{east['id']}/members/{user_id_of(person)}", headers={H: ws})
        assert r.status_code == 404 and r.json()["error"]["message"] == "Member not found"
    mid = user_id_of(member)
    for _ in range(2):
        r = admin.put(f"{TEAMS}/{east['id']}/members/{mid}", headers={H: ws})
        assert r.status_code == 200 and r.json() == {"team_id": east["id"], "user_id": mid}
    got = admin.get(f"{TEAMS}/{east['id']}", headers={H: ws}).json()
    assert got["member_count"] == 1 and [m["user_id"] for m in got["members"]] == [mid]
    assert [e["type"] for e in audit(admin, ws, type="team.member_added")] == ["team.member_added"]
    assert admin.delete(f"{TEAMS}/{east['id']}/members/{mid}", headers={H: ws}).status_code == 204
    r = admin.delete(f"{TEAMS}/{east['id']}/members/{mid}", headers={H: ws})
    assert r.status_code == 404  # not in it any more
    assert [e["type"] for e in audit(admin, ws, type="team.member_removed")] == ["team.member_removed"]


def test_deleting_a_team_moves_its_sub_teams_up_to_its_parent(crm):
    admin, ws, _ = crm
    top = team(admin, ws, "Top")
    middle = team(admin, ws, "Middle", top["id"])
    low = team(admin, ws, "Low", middle["id"])
    assert admin.delete(f"{TEAMS}/{middle['id']}", headers={H: ws}).status_code == 204
    assert admin.get(f"{TEAMS}/{low['id']}", headers={H: ws}).json()["parent_team_id"] == top["id"]
    assert admin.delete(f"{TEAMS}/{top['id']}", headers={H: ws}).status_code == 204
    assert admin.get(f"{TEAMS}/{low['id']}", headers={H: ws}).json()["parent_team_id"] is None
    assert admin.get(f"{TEAMS}/{middle['id']}", headers={H: ws}).status_code == 404
