"""The module's "done when": a form submission workflow with a 2 day wait is tested in seconds with time travel,
published, edited live without losing the contacts already enrolled, and traced per contact."""
from datetime import UTC, datetime, timedelta

from forms_helpers import lead
from helpers import H
from workflow_helpers import (
    ROOT,
    act,
    create,
    detail,
    graph,
    make_tag,
    only_run,
    pause,
    publish,
    pump,
    runs,
    wake,
    walked,
)


def who(site, email: str) -> str:
    """The id of the contact a submission made."""
    return next(r["id"] for r in site.records() if r["values"].get("email") == email)


def test_a_form_submission_workflow_with_a_two_day_wait_is_tested_published_edited_live_and_traced(site, db):
    client, ws = site.client, site.ws
    form = site.live(lead())
    make_tag(client, ws, "web-lead")
    flow = graph({
        "tag": act("tag.add", {"tag": "web-lead"}, "hold"),
        "hold": pause({"duration": {"days": 2}}, "task"),
        "task": act("task.create", {"title": "Call {{first_name}}", "assignee": "owner"})},
        event="form.submitted", data={"form_id": form["id"]})
    wf = create(client, ws, flow, name="Web lead follow-up")
    site.submit(form, {"first_name": "Zed", "email": "zed@example.com"})  # before the workflow was live
    zed = who(site, "zed@example.com")
    # tested in seconds, on a contact, with the two days skipped
    started = datetime.now(UTC)
    tried = client.post(f"{ROOT}/{wf['id']}/test", json={"record_id": zed}, headers={H: ws}).json()
    assert datetime.now(UTC) - started < timedelta(seconds=10)
    assert [(s["node_id"], s["status"]) for s in tried["steps"]] == [
        ("tag", "completed"), ("hold", "waiting"), ("hold", "completed"), ("task", "completed")]
    assert tried["skipped_seconds"] == 2 * 86400 and client.get("/api/v1/tasks", headers={H: ws}).json()["data"] == []
    # published: the next submission enters, the earlier contact does not
    publish(client, ws, wf["id"])
    site.submit(form, {"first_name": "Ada", "email": "ada@example.com"})
    ada_id = who(site, "ada@example.com")
    pump(db)
    run = only_run(client, ws)
    assert run["record"]["id"] == ada_id and run["status"] == "waiting" and run["version"] == 1
    # edited live: the task gets a better title and a step after it; the enrolled contact is not lost
    edited = graph({
        "tag": act("tag.add", {"tag": "web-lead"}, "hold"),
        "hold": pause({"duration": {"days": 2}}, "task"),
        "task": act("task.create", {"title": "Call {{first_name}} about their enquiry", "assignee": "owner"}, "done"),
        "done": act("record.update", {"values": {"lifecycle": "lead"}})},
        event="form.submitted", data={"form_id": form["id"]})
    assert client.post(f"{ROOT}/{wf['id']}/versions", json={"graph": edited}, headers={H: ws}).status_code == 201
    plan = client.post(f"{ROOT}/{wf['id']}/publish", json={"migrate": {}, "dry_run": True}, headers={H: ws}).json()
    assert plan["publish"]["in_flight"] == 1 and plan["publish"]["removed_nodes"] == []  # every step is still there
    moved = client.post(f"{ROOT}/{wf['id']}/publish", json={"migrate": {}}, headers={H: ws}).json()
    assert moved["publish"]["moved"] == 1 and runs(client, ws)[0]["version"] == 2
    site.submit(form, {"first_name": "Bob", "email": "bob@example.com"})
    bob_id = who(site, "bob@example.com")
    pump(db)
    wake(db)  # two days pass
    done = {r["record"]["id"]: detail(client, ws, r["id"]) for r in runs(client, ws)}
    assert {r["status"] for r in done.values()} == {"completed"}
    titles = sorted(t["title"] for t in client.get("/api/v1/tasks", headers={H: ws}).json()["data"])
    assert titles == ["Call Ada about their enquiry", "Call Bob about their enquiry"]  # Ada kept her place on version 2
    # traced per contact
    ada = done[ada_id]
    assert walked(ada) == [("tag", "completed"), ("hold", "waiting"), ("hold", "completed"), ("task", "completed"),
                           ("done", "completed")]
    assert ada["steps"][2]["output"] == {"resumed_by": "timer"}
    assert ada["steps"][3]["input"]["title"] == "Call Ada about their enquiry"
    assert done[bob_id]["version"] == 2 and walked(done[bob_id]) == walked(ada)
    assert client.get(f"{ROOT}/runs", params={"record_id": zed}, headers={H: ws}).json()[
        "data"] == []  # and Zed, who submitted before it was live, never entered
