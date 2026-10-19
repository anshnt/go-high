"""Who may do what with workflows: reading, editing drafts, and what changes what runs live; that a run shows only for a
record the caller may see, that a role with hidden fields gets no trace values, and that a workflow cannot be used to
read what its author may not."""
import uuid

from helpers import H, add_member, make_role, rule, user_id_of
from workflow_helpers import ROOT, act, contact, create, graph, live, make_tag, only_run, publish, pump, runs, tag

END = {"type": "end", "config": {}}


def refused(r, capability: str) -> None:
    assert r.status_code == 403, r.text
    error = r.json()["error"]
    assert error["code"] == "forbidden" and capability in error["message"], error


def test_a_viewer_reads_workflows_runs_and_the_catalog_but_changes_nothing(crm, db):
    admin, ws, ids = crm
    wf = live(admin, ws, graph({"hold": {"type": "wait", "config": {"duration": {"days": 1}}, "next": None}}))
    contact(admin, ws)
    pump(db)
    run = only_run(admin, ws)
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    for path in ("", f"/{wf['id']}", f"/{wf['id']}/versions", f"/{wf['id']}/versions/1", "/catalog", "/runs",
                 f"/runs/{run['id']}", "/refs?kind=tag&key=x"):
        assert viewer.get(f"{ROOT}{path}", headers={H: ws}).status_code == 200, path
    diff = viewer.get(f"{ROOT}/{wf['id']}/diff", params={"from": 1, "to": 1}, headers={H: ws})
    assert diff.status_code == 200
    explain = viewer.get(f"{ROOT}/{wf['id']}/explain", params={"record_id": run["record"]["id"]}, headers={H: ws})
    assert explain.status_code == 200
    body = {"graph": graph({"go": END})}
    for method, path, payload, capability in [
            ("POST", "", {"name": "x"}, "workflows.write"), ("PATCH", f"/{wf['id']}", {"name": "x"}, "workflows.write"),
            ("POST", f"/{wf['id']}/versions", body, "workflows.write"),
            ("POST", f"/{wf['id']}/test", {"record_id": run["record"]["id"]}, "workflows.write"),
            ("POST", f"/runs/{run['id']}/cancel", None, "workflows.write"),
            ("POST", f"/runs/{run['id']}/retry", None, "workflows.write"),
            ("POST", f"/{wf['id']}/publish", None, "workflows.publish"),
            ("POST", f"/{wf['id']}/pause", None, "workflows.publish"),
            ("POST", f"/{wf['id']}/resume", None, "workflows.publish"),
            ("POST", f"/{wf['id']}/rotate-secret", None, "workflows.publish"),
            ("DELETE", f"/{wf['id']}", None, "workflows.publish")]:
        refused(viewer.request(method, f"{ROOT}{path}", json=payload, headers={H: ws}), capability)
    assert only_run(admin, ws)["status"] == "waiting" and admin.get(f"{ROOT}/{wf['id']}", headers={H: ws}).json()[
        "status"] == "published"


def test_a_member_edits_and_tests_drafts_but_going_live_is_for_those_who_may_publish(crm, db):
    admin, ws, ids = crm
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws, workspace_role="member")
    manager = add_member(db, ids["org_id"], "boss@example.com", workspace_id=ws, workspace_role="manager")
    make_tag(admin, ws, "x")
    made = member.post(ROOT, json={"name": "Mine", "graph": graph({"go": tag("x")})}, headers={H: ws})
    assert made.status_code == 201, made.text
    wf = made.json()
    assert member.patch(f"{ROOT}/{wf['id']}", json={"settings": {"reentry": True}}, headers={H: ws}).status_code == 200
    saved = member.post(f"{ROOT}/{wf['id']}/versions", json={"graph": graph({"go": tag("x", None)}), "note": "n"},
                        headers={H: ws})
    assert saved.status_code == 200  # nothing to change: the same version
    ada = contact(admin, ws)
    tried = member.post(f"{ROOT}/{wf['id']}/test", json={"record_id": ada["id"]}, headers={H: ws})
    assert tried.status_code == 200 and tried.json()["run"]["status"] == "completed"
    for path in ("publish", "pause", "resume", "rotate-secret"):
        refused(member.post(f"{ROOT}/{wf['id']}/{path}", headers={H: ws}), "workflows.publish")
    refused(member.delete(f"{ROOT}/{wf['id']}", headers={H: ws}), "workflows.publish")
    assert manager.post(f"{ROOT}/{wf['id']}/publish", headers={H: ws}).status_code == 200
    # a live workflow's settings change who enters it, which is publishing
    refused(member.patch(f"{ROOT}/{wf['id']}", json={"settings": {"reentry": False}}, headers={H: ws}),
            "workflows.publish")
    assert member.patch(f"{ROOT}/{wf['id']}", json={"name": "Renamed"}, headers={H: ws}).status_code == 200
    off = manager.patch(f"{ROOT}/{wf['id']}", json={"settings": {"reentry": False}}, headers={H: ws})
    assert off.status_code == 200
    assert manager.post(f"{ROOT}/{wf['id']}/pause", headers={H: ws}).status_code == 200
    assert manager.post(f"{ROOT}/{wf['id']}/resume", headers={H: ws}).status_code == 200


def test_a_run_shows_only_for_a_record_in_the_callers_scope_and_everything_else_is_a_404(crm, db):
    admin, ws, ids = crm
    own = make_role(admin, ws, "Own records", copy_from="member", rules=[rule("*", "own")])
    mine = add_member(db, ids["org_id"], "own@example.com", workspace_id=ws, workspace_role=own["key"])
    me = user_id_of(mine)
    wf = live(admin, ws, graph({"hold": {"type": "wait", "config": {"duration": {"days": 1}}, "next": None}}))
    hers = contact(admin, ws, owner_id=me)
    theirs = contact(admin, ws, first_name="Bob", email="bob@example.com")
    pump(db)
    assert {r["record"]["display_name"] for r in runs(admin, ws)} == {"Ada", "Bob"}
    seen = mine.get(f"{ROOT}/runs", headers={H: ws}).json()["data"]
    assert [r["record"]["id"] for r in seen] == [hers["id"]]
    hidden_run = next(r for r in runs(admin, ws) if r["record"]["id"] == theirs["id"])
    for method, path, body in [("GET", f"/runs/{hidden_run['id']}", None),
                               ("POST", f"/runs/{hidden_run['id']}/cancel", None),
                               ("POST", f"/runs/{hidden_run['id']}/retry", None),
                               ("GET", f"/{wf['id']}/explain?record_id={theirs['id']}", None),
                               ("POST", f"/{wf['id']}/test", {"record_id": theirs["id"]})]:
        assert mine.request(method, f"{ROOT}{path}", json=body, headers={H: ws}).status_code == 404, path
    assert mine.get(f"{ROOT}/runs", params={"record_id": theirs["id"]}, headers={H: ws}).json()["data"] == []
    mine_run = seen[0]
    assert mine.get(f"{ROOT}/runs/{mine_run['id']}", headers={H: ws}).status_code == 200
    explained = mine.get(f"{ROOT}/{wf['id']}/explain", params={"record_id": hers["id"]}, headers={H: ws})
    assert explained.status_code == 200 and explained.json()["in_workflow"] is True
    assert admin.get(f"{ROOT}/runs/{hidden_run['id']}", headers={H: ws}).status_code == 200  # the admin still sees it


def test_a_role_that_hides_a_field_gets_the_trace_without_what_was_set_or_sent(crm, db):
    admin, ws, ids = crm
    cautious = make_role(admin, ws, "Cautious", copy_from="member", rules=[rule("*", "all", hidden=["phone"])])
    person = add_member(db, ids["org_id"], "c@example.com", workspace_id=ws, workspace_role=cautious["key"])
    live(admin, ws, graph({"go": act("record.update", {"values": {"lifecycle": "lead"}})}))
    contact(admin, ws, phone="+14155550123")
    pump(db)
    run = only_run(admin, ws)
    assert run["steps"][0]["input"] == {"values": {"lifecycle": "lead"}}
    seen = person.get(f"{ROOT}/runs/{run['id']}", headers={H: ws}).json()
    assert seen["status"] == "completed" and seen["steps"][0]["node_id"] == "go"
    assert seen["steps"][0]["input"] is None and seen["steps"][0]["output"] is None  # values may be ones it hides


def test_a_workflow_cannot_be_used_to_read_or_write_what_its_author_may_not(crm, db):
    admin, ws, ids = crm
    cautious = make_role(admin, ws, "Cautious", copy_from="member", rules=[rule("*", "all", hidden=["phone"])])
    person = add_member(db, ids["org_id"], "c@example.com", workspace_id=ws, workspace_role=cautious["key"])
    make_tag(admin, ws, "x")
    for node, field in (
            (act("webhook.send", {"url": "https://hooks.example.com/x", "payload": {"p": "{{phone}}"}}),
             "graph.nodes.go.config.payload.p"),
            (act("task.create", {"title": "Call {{phone}}"}), "graph.nodes.go.config.title"),
            (act("record.update", {"values": {"phone": "+14155550199"}}), "graph.nodes.go.config.values.phone")):
        r = person.post(ROOT, json={"name": "Sneaky", "graph": graph({"go": node})}, headers={H: ws})
        assert r.status_code == 422 and field in r.json()["error"]["fields"], (node, r.text)
    r = person.post(ROOT, json={"name": "Sneaky", "graph": graph({"go": END}, filter={
        "field": "phone", "op": "is_not_empty"})}, headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {
        "graph.trigger.filter.field": "unknown field 'phone' on contact"}
    r = person.post(ROOT, json={"name": "Fine", "graph": graph({"go": tag("x")})}, headers={H: ws})
    assert r.status_code == 201  # what the author may see, the workflow may use


def test_the_automation_roles_own_limits_bind_what_a_workflow_does(crm, db):
    """The workflow acts as Automation: take its write away and the step fails, naming it, while a person with the same
    rights as the workflow's author could still do the thing by hand."""
    admin, ws, _ = crm
    roles = admin.get("/api/v1/roles", headers={H: ws}).json()["data"]
    automation = next(r for r in roles if r["key"] == "automation")
    left = [c for c in automation["capabilities"] if c != "contacts.write"]
    edited = admin.patch(f"/api/v1/roles/{automation['id']}", json={"capabilities": left}, headers={H: ws})
    assert edited.status_code == 200
    live(admin, ws, graph({"go": act("record.update", {"values": {"lifecycle": "lead"}})}))
    contact(admin, ws)
    pump(db)
    run = only_run(admin, ws)
    assert run["status"] == "failed" and run["error"] == (
        "Your role does not allow this: it needs the capability contacts.write")


def test_another_organizations_workflow_ids_are_404_for_every_workflow_route(crm, make_user):
    admin, ws, _ = crm
    other, other_ids = make_user("other@example.com")
    foreign = create(other, other_ids["workspace_id"], graph({"go": END}))
    publish(other, other_ids["workspace_id"], foreign["id"])
    for method, path, body in [("GET", f"/{foreign['id']}", None), ("PATCH", f"/{foreign['id']}", {"name": "x"}),
                               ("DELETE", f"/{foreign['id']}", None), ("GET", f"/{foreign['id']}/versions", None),
                               ("GET", f"/{foreign['id']}/versions/1", None),
                               ("POST", f"/{foreign['id']}/versions", {"graph": graph({"go": END})}),
                               ("POST", f"/{foreign['id']}/publish", None), ("POST", f"/{foreign['id']}/pause", None),
                               ("POST", f"/{foreign['id']}/resume", None),
                               ("POST", f"/{foreign['id']}/rotate-secret", None),
                               ("POST", f"/{foreign['id']}/test", {"record_id": str(uuid.uuid4())}),
                               ("GET", f"/{foreign['id']}/explain?record_id={uuid.uuid4()}", None),
                               ("GET", f"/{foreign['id']}/diff?from=1&to=1", None)]:
        r = admin.request(method, f"{ROOT}{path}", json=body, headers={H: ws})
        assert r.status_code == 404, (method, path, r.status_code)
    assert admin.get(ROOT, headers={H: ws}).json()["data"] == []
