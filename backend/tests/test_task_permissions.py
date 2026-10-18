"""Tasks and ADR 0004: each route needs its capability, notifications are everybody's own, and a task shows the name of
its record only to someone who may see that record."""
import uuid

from helpers import H, add_member, make_record, make_role, rule, user_id_of

T = "/api/v1/tasks"
N = "/api/v1/notifications"


def make(client, ws, title="Call Ada", **body) -> dict:
    r = client.post(T, json={"title": title, **body}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def give(admin, ws, who, role: dict) -> None:
    r = admin.put(f"/api/v1/members/{user_id_of(who)}", json={"role_id": role["id"]}, headers={H: ws})
    assert r.status_code == 200, r.text


def refused(response, capability: str) -> None:
    error = response.json()["error"]
    assert response.status_code == 403 and error["code"] == "forbidden", response.text
    assert capability in error["message"], response.text


def test_a_viewer_reads_tasks_but_cannot_change_them(crm, db):
    admin, ws, ids = crm
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    task = make(admin, ws)
    one = f"{T}/{task['id']}"
    assert viewer.get(T, headers={H: ws}).json()["data"][0]["id"] == task["id"]
    assert viewer.get(one, headers={H: ws}).status_code == 200
    assert viewer.get("/api/v1/my-day", headers={H: ws}).status_code == 200
    for method, path, body in (("POST", T, {"title": "x"}), ("PATCH", one, {"title": "x"}),
                               ("POST", f"{one}/complete", None), ("POST", f"{one}/reopen", None),
                               ("POST", f"{one}/reorder", {}),
                               ("POST", f"{T}/bulk", {"ids": [task["id"]], "action": "complete"})):
        refused(viewer.request(method, path, json=body, headers={H: ws}), "tasks.write")
    refused(viewer.delete(one, headers={H: ws}), "tasks.delete")
    assert admin.get(one, headers={H: ws}).json()["status"] == "open"


def test_a_member_works_with_tasks_and_a_role_can_be_given_less(crm, db):
    admin, ws, ids = crm
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    task = make(member, ws, "Mine")
    assert member.patch(f"{T}/{task['id']}", json={"title": "Still mine"}, headers={H: ws}).status_code == 200
    assert member.post(f"{T}/{task['id']}/complete", headers={H: ws}).status_code == 200
    assert member.delete(f"{T}/{task['id']}", headers={H: ws}).status_code == 204
    keeper = make_role(admin, ws, "Writes, never deletes", copy_from="member",
                       capabilities=["schema.read", "members.read", "tasks.read", "tasks.write"])
    give(admin, ws, member, keeper)
    kept = make(member, ws, "Kept")
    refused(member.delete(f"{T}/{kept['id']}", headers={H: ws}), "tasks.delete")
    blind = make_role(admin, ws, "No tasks", copy_from="viewer", capabilities=["schema.read"])
    give(admin, ws, member, blind)
    refused(member.get(T, headers={H: ws}), "tasks.read")
    refused(member.get("/api/v1/my-day", headers={H: ws}), "tasks.read")


def test_notifications_are_everyones_own_whatever_the_role(crm, db):
    admin, ws, ids = crm
    blind = make_role(admin, ws, "Nothing at all", copy_from="viewer", capabilities=["schema.read"])
    person = add_member(db, ids["org_id"], "p@example.com", workspace_id=ws)
    give(admin, ws, person, blind)
    assert person.get(N, headers={H: ws}).json() == {"data": [], "next_cursor": None}
    assert person.get(f"{N}/unread-count", headers={H: ws}).json() == {"count": 0}
    assert person.post(f"{N}/read", json={"all": True}, headers={H: ws}).status_code == 200
    assert person.get(f"{N}/prefs", headers={H: ws}).status_code == 200


def test_a_task_names_its_record_only_to_someone_who_may_see_it(crm, db):
    admin, ws, ids = crm
    ben = add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws)
    give(admin, ws, ben, make_role(admin, ws, "Own records", copy_from="member", rules=[rule("*", scope="own")]))
    secret = make_record(admin, ws, first_name="Ada", last_name="Secret", owner_id=user_id_of(admin))
    shared = make_record(admin, ws, first_name="Grace", last_name="Shared", owner_id=user_id_of(ben))
    on_secret, on_shared = make(admin, ws, "On the secret", record_id=secret["id"]), make(
        admin, ws, "On the shared", record_id=shared["id"], assignee_id=user_id_of(ben))

    def records_of(client) -> dict[str, dict | None]:
        return {t["title"]: t["record"] for t in client.get(T, headers={H: ws}).json()["data"]}

    assert records_of(admin)["On the secret"]["display_name"] == "Ada Secret"
    seen = records_of(ben)
    assert seen["On the secret"] is None  # the task is there, the name of the record is not
    assert seen["On the shared"] == {"id": shared["id"], "object": "contact", "display_name": "Grace Shared"}
    assert ben.get(f"{T}/{on_secret['id']}", headers={H: ws}).json()["record"] is None
    assert ben.get("/api/v1/my-day", headers={H: ws}).json()["tasks"]["today"] == []
    assert "Secret" not in ben.get(T, headers={H: ws}).text and on_shared["record_id"] == shared["id"]
    # and a record out of scope cannot be linked to a task by the one who may not see it
    r = ben.post(T, json={"title": "x", "record_id": secret["id"]}, headers={H: ws})
    assert r.status_code == 422 and "record_id" in r.json()["error"]["fields"]


def test_a_task_does_not_name_a_record_by_a_hidden_field(crm, db):
    admin, ws, ids = crm
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    give(admin, ws, viewer, make_role(admin, ws, "Blind to names", copy_from="viewer",
                                      rules=[rule("*", scope="all", hidden=["first_name", "last_name"])]))
    ada = make_record(admin, ws, first_name="Ada", last_name="Lovelace", email="ada@example.com")
    make(admin, ws, "Call her", record_id=ada["id"])
    assert admin.get(T, headers={H: ws}).json()["data"][0]["record"]["display_name"] == "Ada Lovelace"
    assert viewer.get(T, headers={H: ws}).json()["data"][0]["record"] is None
    assert uuid.UUID(viewer.get(T, headers={H: ws}).json()["data"][0]["record_id"]) == uuid.UUID(ada["id"])
