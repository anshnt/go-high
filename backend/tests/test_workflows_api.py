"""The workflows API: CRUD, immutable versions and their diff, validation against the workspace, publishing over runs in
flight (stay, migrate, exit), pause and resume, archive, runs (list, cancel, retry), and what uses a tag or field."""
import uuid

from helpers import H, add_member, stage_ids, user_id_of
from inbox_helpers import add_channel
from sqlalchemy import text
from workflow_helpers import (
    ROOT,
    act,
    ask,
    contact,
    create,
    detail,
    graph,
    live,
    make_tag,
    only_run,
    pause,
    publish,
    pump,
    runs,
    sql,
    tag,
    tags_of,
    wake,
    walked,
)

END = {"type": "end", "config": {}}


def post(client, ws, path, body=None, status=200):
    r = client.post(f"{ROOT}{path}", json=body if body is not None else {}, headers={H: ws})
    assert r.status_code == status, r.text
    return r.json()


def get(client, ws, path, expect=200, **params):
    r = client.get(f"{ROOT}{path}", params=params, headers={H: ws})
    assert r.status_code == expect, r.text
    return r.json()


def fields(r) -> dict:
    assert r.status_code == 422, r.text
    return r.json()["error"]["fields"]


# --- workflows --------------------------------------------------------------------------------------------------

def test_a_workflow_is_created_edited_listed_and_archived_and_every_change_is_an_event(crm, db):
    client, ws, ids = crm
    wf = create(client, ws, name="Nurture", folder="Leads")
    assert wf["status"] == "draft" and wf["latest_version"] is None and wf["published_version"] is None
    assert wf["settings"] == {"reentry": False} and wf["runs"] == {} and wf["has_draft_changes"] is False
    assert wf["owner_id"] == wf["created_by"] and wf["version"] is None
    assert get(client, ws, f"/{wf['id']}")["graph"] is None
    ben = user_id_of(add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws))
    r = client.patch(f"{ROOT}/{wf['id']}", headers={H: ws}, json={
        "name": "Nurture v2", "folder": None, "settings": {"reentry": True}, "owner_id": ben})
    assert r.status_code == 200 and (r.json()["name"], r.json()["folder"], r.json()["owner_id"]) == (
        "Nurture v2", None, ben)
    changed = sql(db, "SELECT data->'changes' FROM events WHERE type = 'workflow.updated'")[0][0]
    assert changed["name"] == {"old": "Nurture", "new": "Nurture v2"} and changed["folder"] == {"old": "Leads",
                                                                                                "new": None}
    other = create(client, ws, name="Other", folder="Leads")
    assert [w["name"] for w in get(client, ws, "")["data"]] == ["Other", "Nurture v2"]  # newest change first
    assert [w["name"] for w in get(client, ws, "", folder="Leads")["data"]] == ["Other"]
    assert [w["name"] for w in get(client, ws, "", q="nurt")["data"]] == ["Nurture v2"]
    assert get(client, ws, "", status="published")["data"] == []
    assert client.delete(f"{ROOT}/{other['id']}", headers={H: ws}).status_code == 204
    assert [w["name"] for w in get(client, ws, "")["data"]] == ["Nurture v2"]
    assert [w["name"] for w in get(client, ws, "", status="archived")["data"]] == ["Other"]
    assert client.delete(f"{ROOT}/{other['id']}", headers={H: ws}).status_code == 204  # again: nothing more to do
    types = [t for (t,) in sql(db, "SELECT type FROM events WHERE type LIKE 'workflow.%' ORDER BY id")]
    assert types == ["workflow.created", "workflow.updated", "workflow.created", "workflow.updated"]
    r = client.patch(f"{ROOT}/{wf['id']}", json={"name": None}, headers={H: ws})
    assert fields(r) == {"name": "cannot be null"}
    r = client.patch(f"{ROOT}/{wf['id']}", json={"owner_id": str(uuid.uuid4())}, headers={H: ws})
    assert fields(r) == {"owner_id": "is not a member of this workspace"}
    assert client.get(f"{ROOT}/{uuid.uuid4()}", headers={H: ws}).status_code == 404
    assert client.get(f"{ROOT}/not-a-uuid", headers={H: ws}).status_code == 422


def test_creating_with_an_idempotency_key_creates_once(crm):
    client, ws, _ = crm
    body = {"name": "Once", "graph": graph({"go": END})}
    first = client.post(ROOT, json=body, headers={H: ws, "Idempotency-Key": "k1"})
    again = client.post(ROOT, json=body, headers={H: ws, "Idempotency-Key": "k1"})
    assert first.status_code == again.status_code == 201 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first.json() and len(get(client, ws, "")["data"]) == 1


# --- versions ---------------------------------------------------------------------------------------------------

def test_versions_are_immutable_numbered_and_saving_what_is_saved_changes_nothing(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "a")
    make_tag(client, ws, "b")
    wf = create(client, ws, graph({"go": tag("a")}), note="first")
    first = wf["version"]
    assert first["number"] == 1 and first["note"] == "first" and first["published"] is False
    assert first["graph"]["nodes"]["go"]["config"] == {"tag": "a"} and first["nodes"] == 1
    same = client.post(f"{ROOT}/{wf['id']}/versions", json={"graph": graph({"go": tag("a")})}, headers={H: ws})
    assert same.status_code == 200 and same.json()["id"] == first["id"]  # nothing changed: the same version
    second = client.post(f"{ROOT}/{wf['id']}/versions", headers={H: ws}, json={
        "graph": graph({"go": tag("b")}), "note": "tag b instead"})
    assert second.status_code == 201 and second.json()["number"] == 2 and second.json()["note"] == "tag b instead"
    listed = get(client, ws, f"/{wf['id']}/versions")["data"]
    assert [(v["number"], v["published"]) for v in listed] == [(2, False), (1, False)]
    assert "graph" not in listed[0] and get(client, ws, f"/{wf['id']}/versions/1")["graph"] == first["graph"]
    missing = get(client, ws, f"/{wf['id']}/versions/9", expect=404)["error"]
    assert (missing["code"], missing["message"]) == ("not_found", "Version not found")
    flow = get(client, ws, f"/{wf['id']}")
    assert flow["latest_version"] == 2 and flow["graph"] == second.json()["graph"]  # the builder edits the newest
    publish(client, ws, wf["id"], version=1)
    flow = get(client, ws, f"/{wf['id']}")
    assert (flow["published_version"], flow["latest_version"], flow["has_draft_changes"]) == (1, 2, True)
    assert [(v["number"], v["published"]) for v in get(client, ws, f"/{wf['id']}/versions")["data"]] == [
        (2, False), (1, True)]
    assert sql(db, "SELECT published_at IS NOT NULL FROM workflow_versions ORDER BY number") == [(True,), (False,)]
    assert [t for (t,) in sql(db, "SELECT type FROM events WHERE type = 'workflow.version_created'")] == [
        "workflow.version_created"] * 2
    r = client.post(f"{ROOT}/{wf['id']}/versions", json={"graph": "nonsense"}, headers={H: ws})
    assert r.status_code == 422 and fields(r) == {"graph": "Input should be a valid dictionary"}


def test_the_diff_between_two_versions_is_node_level_and_ignores_where_a_node_is_drawn(crm):
    client, ws, _ = crm
    for name in ("a", "b", "c"):
        make_tag(client, ws, name)
    one = graph({"x": {**tag("a", "y"), "ui": {"x": 1}}, "y": tag("b", "z"), "z": tag("c")})
    wf = create(client, ws, one)
    two = graph({"x": {**tag("a", "y"), "ui": {"x": 99}}, "y": tag("a", "w"), "w": pause({"duration": {"days": 1}})},
                filter={"field": "lifecycle", "op": "is", "value": "lead"})
    post(client, ws, f"/{wf['id']}/versions", {"graph": two}, status=201)
    d = get(client, ws, f"/{wf['id']}/diff", **{"from": 1, "to": 2})
    assert (d["from"], d["to"]) == (1, 2) and d["trigger"]["changed"] and not d["start"]["changed"]
    assert [n["id"] for n in d["nodes"]["added"]] == ["w"] and d["nodes"]["added"][0]["node"]["type"] == "wait"
    assert [n["id"] for n in d["nodes"]["removed"]] == ["z"]
    assert [(n["id"], n["keys"]) for n in d["nodes"]["changed"]] == [("y", ["config", "next"])]  # not x: only moved
    assert d["nodes"]["changed"][0]["before"]["config"] == {"tag": "b"} and d["nodes"]["changed"][0]["after"][
        "config"] == {"tag": "a"}
    same = get(client, ws, f"/{wf['id']}/diff", **{"from": 2, "to": 2})
    assert same["nodes"] == {"added": [], "removed": [], "changed": []} and not same["trigger"]["changed"]
    get(client, ws, f"/{wf['id']}/diff", expect=404, **{"from": 1, "to": 7})


def test_a_graph_is_checked_against_the_workspace_and_every_error_points_into_it(crm, db):
    client, ws, ids = crm
    stranger = add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws)
    email = add_channel(client, ws, "mailgun")
    chat = add_channel(client, ws, "internal")
    bad = graph({
        "t1": act("tag.add", {"tag": "nope"}, "t2"),
        "t2": act("record.update", {"values": {"nope": 1, "lifecycle": "nonsense", "email": "not an email",
                                              "last_name": "{{surname}}"}}, "t3"),
        "t3": act("deal.move_stage", {"stage_id": str(uuid.uuid4())}, "t4"),
        "t4": act("message.send", {"channel_id": chat["id"], "body": "x"}, "t5"),
        "t5": act("message.send", {"channel_id": str(uuid.uuid4()), "body": "x"}, "t6"),
        "t6": act("message.send", {"channel_id": email["id"], "body": "x"}, "t7"),
        "t7": act("owner.assign", {"round_robin": [user_id_of(stranger), str(uuid.uuid4())]}, "t8"),
        "t8": act("task.create", {"title": "x", "assignee": str(uuid.uuid4())}, "t9"),
        "t9": act("webhook.send", {"url": "https://hooks.example.com/{{nope}}", "payload": {"k": "{{nada}}"}}, "w"),
        "w": pause({"until_field": {"field": "lifecycle"}}, "c"),
        "c": ask({"and": [{"field": "nope", "op": "is", "value": 1}]}, "d", "d"),
        "d": ask({"field": "lifecycle", "op": "gt", "value": 1}, "g", "g"),
        "g": {"type": "goal", "config": {"filter": {"tag": ""}}, "next": None}},
        filter={"field": "ghost", "op": "is_empty"})
    found = fields(client.post(ROOT, json={"name": "Bad", "graph": bad}, headers={H: ws}))
    assert found["graph.trigger.filter.field"] == "unknown field 'ghost' on contact"
    assert found["graph.nodes.t1.config.tag"] == "there is no tag 'nope'"
    assert found["graph.nodes.t2.config.values.nope"] == "is not a field of contact"
    assert found["graph.nodes.t2.config.values.lifecycle"].startswith("Lifecycle stage ")
    assert found["graph.nodes.t2.config.values.email"].startswith("Email ")
    assert found["graph.nodes.t3.config.stage_id"] == (
        "moving a stage works on deals; this workflow's records are contacts")
    assert found["graph.nodes.t4.config.channel_id"] == (
        "workflows send on sms, email and whatsapp channels, not webchat")
    assert found["graph.nodes.t5.config.channel_id"] == "is not a channel of this workspace"
    assert found["graph.nodes.t6.config.subject"] == "is required to send an email"
    assert found["graph.nodes.t7.config.round_robin.1"] == "is not a member of this workspace"
    assert found["graph.nodes.t8.config.assignee"] == "is not a member of this workspace"
    assert found["graph.nodes.t9.config.payload.k"] == "uses {{nada}}, which is not a field of contact"
    assert found["graph.nodes.w.config.until_field.field"] == "must be a date or datetime field of contact"
    assert found["graph.nodes.c.config.filter.and.0.field"] == "unknown field 'nope' on contact"
    assert found["graph.nodes.d.config.filter.op"].startswith("'gt' does not apply to the select field")
    assert found["graph.nodes.g.config.filter.tag"] == "must be a tag name or id"
    assert get(client, ws, "")["data"] == []  # the workflow was not even created


def test_a_graph_for_another_object_is_checked_against_that_objects_fields(crm):
    client, ws, _ = crm
    stages = stage_ids(client, ws)
    ok = graph({"go": act("deal.move_stage", {"stage_id": stages["qualified"]}, "n"),
                "n": act("record.update", {"values": {"close_date": "2030-05-01"}})},
               object="deal", filter={"field": "amount", "op": "gt", "value": {"amount": 100, "currency": "USD"}})
    assert create(client, ws, ok)["version"]["number"] == 1
    wrong = graph({"go": act("record.update", {"values": {"close_date": "soon"}}, "m"),
                   "m": act("message.send", {"channel_id": add_channel(client, ws)["id"], "body": "x"})}, object="deal")
    found = fields(client.post(ROOT, json={"name": "x", "graph": wrong}, headers={H: ws}))
    assert found["graph.nodes.go.config.values.close_date"].startswith("Close date ")
    assert found["graph.nodes.m.config.channel_id"] == "messages go to contacts; this workflow's records are deals"
    r = client.post(ROOT, json={"name": "x", "graph": graph({"go": END}, object="nothing")}, headers={H: ws})
    assert fields(r) == {"graph.trigger.object": "there is no object 'nothing'"}


# --- publishing -------------------------------------------------------------------------------------------------

def test_publishing_needs_a_version_with_something_to_run_and_points_the_workflow_at_it(crm, db):
    client, ws, _ = crm
    wf = create(client, ws, name="Empty")
    assert client.post(f"{ROOT}/{wf['id']}/publish", json={}, headers={H: ws}).status_code == 404  # no version yet
    post(client, ws, f"/{wf['id']}/versions", {"graph": {"trigger": {"event": "record.created"}, "start": None,
                                                        "nodes": {}}}, status=201)
    assert fields(client.post(f"{ROOT}/{wf['id']}/publish", json={}, headers={H: ws})) == {
        "graph.nodes": "add a step first: there is nothing to run"}
    sub = {"s": {"type": "subflow", "config": {"workflow_id": wf["id"]}, "next": None}}
    post(client, ws, f"/{wf['id']}/versions", {"graph": graph(sub)}, status=201)
    assert fields(client.post(f"{ROOT}/{wf['id']}/publish", json={}, headers={H: ws})) == {
        "graph.nodes.s.type": "subflows are not built yet: they can be saved but not published"}
    post(client, ws, f"/{wf['id']}/versions", {"graph": graph({"go": END})}, status=201)
    done = post(client, ws, f"/{wf['id']}/publish")
    assert (done["status"], done["published_version"], done["trigger_event"]) == (
        "published", 3, "record.created")
    assert done["publish"] == {"in_flight": 0, "same_node": 0, "removed_nodes": [], "moved": 0, "exited": 0,
                               "dry_run": False}
    published = sql(db, "SELECT data FROM events WHERE type = 'workflow.published'")[0][0]
    assert published["version"] == 3 and published["name"] == "Empty" and published["moved"] == 0
    assert client.post(f"{ROOT}/{wf['id']}/publish", json={"version": 99}, headers={H: ws}).status_code == 404
    assert client.delete(f"{ROOT}/{wf['id']}", headers={H: ws}).status_code == 204
    assert client.post(f"{ROOT}/{wf['id']}/publish", json={}, headers={H: ws}).status_code == 409  # archived


def test_publishing_checks_the_version_again_because_what_it_names_may_have_changed(crm, db):
    client, ws, _ = crm
    gone = make_tag(client, ws, "temporary")
    wf = create(client, ws, graph({"go": tag("temporary")}))
    assert client.delete(f"/api/v1/tags/{gone['id']}", headers={H: ws}).status_code == 204
    assert fields(client.post(f"{ROOT}/{wf['id']}/publish", json={}, headers={H: ws})) == {
        "graph.nodes.go.config.tag": "there is no tag 'temporary'"}
    assert get(client, ws, f"/{wf['id']}")["status"] == "draft"


def _waiting_in_two_places(client, ws, db):
    """Version 1 is a -> b -> end (two waits). One contact is parked at a, another at b."""
    make_tag(client, ws, "done")
    one = graph({"a": pause({"duration": {"days": 1}}, "b"), "b": pause({"duration": {"days": 2}}, "end"),
                 "end": END})
    wf = live(client, ws, one, name="Two waits")
    early = contact(client, ws, first_name="Early", email="early@example.com")
    pump(db)
    wake(db)  # Early moves on from a to b...
    late = contact(client, ws, first_name="Late", email="late@example.com")
    pump(db)  # ...and Late is parked at a
    where = {r["record"]["display_name"]: r["node_id"] for r in runs(client, ws)}
    assert where == {"Early": "b", "Late": "a"}
    return wf, early, late


def test_a_run_in_flight_finishes_on_the_version_it_started_on_unless_the_publisher_moves_it(crm, db):
    client, ws, _ = crm
    wf, early, late = _waiting_in_two_places(client, ws, db)
    two = graph({"b": pause({"duration": {"days": 2}}, "mark"), "mark": tag("done")})  # a is gone
    post(client, ws, f"/{wf['id']}/versions", {"graph": two}, status=201)
    done = post(client, ws, f"/{wf['id']}/publish")  # no `migrate`: nobody moves
    assert done["published_version"] == 2 and done["publish"]["moved"] == 0
    assert {r["version"] for r in runs(client, ws)} == {1}
    wake(db)  # time passes: Late moves on to b, Early finishes, both on version 1, which has no mark
    wake(db)
    assert all(r["status"] == "completed" for r in runs(client, ws))
    assert tags_of(client, ws, early["id"]) == [] and tags_of(client, ws, late["id"]) == []  # neither saw version 2
    newcomer = contact(client, ws, first_name="New", email="new@example.com")
    pump(db)
    wake(db)
    wake(db)
    assert tags_of(client, ws, newcomer["id"]) == ["done"]  # a record that enters now runs version 2


def test_publishing_with_migrate_keeps_runs_at_steps_that_exist_and_sends_the_rest_where_told(crm, db):
    client, ws, _ = crm
    wf, early, late = _waiting_in_two_places(client, ws, db)
    two = graph({"b": pause({"duration": {"days": 2}}, "mark"), "mark": tag("done")})  # a is gone, b stays
    post(client, ws, f"/{wf['id']}/versions", {"graph": two}, status=201)
    plan = post(client, ws, f"/{wf['id']}/publish", {"migrate": {}, "dry_run": True})
    assert plan["publish"] == {"in_flight": 2, "same_node": 1, "dry_run": True,
                               "removed_nodes": [{"node_id": "a", "runs": 1, "to": None}]}
    assert get(client, ws, f"/{wf['id']}")["published_version"] == 1  # a dry run changes nothing
    refused = client.post(f"{ROOT}/{wf['id']}/publish", json={"migrate": {}}, headers={H: ws})
    assert fields(refused) == {"migrate.a": "1 runs are at this step, which this version removed: choose one or exit"}
    elsewhere = client.post(f"{ROOT}/{wf['id']}/publish", json={"migrate": {"a": "nowhere"}}, headers={H: ws})
    assert fields(elsewhere) == {"migrate.a": "is not a step of this version, or exit"}
    done = post(client, ws, f"/{wf['id']}/publish", {"migrate": {"a": "b"}})
    assert done["publish"]["moved"] == 2 and done["publish"]["exited"] == 0 and done["published_version"] == 2
    assert {r["version"] for r in runs(client, ws)} == {2} and {r["node_id"] for r in runs(client, ws)} == {"b"}
    moved = detail(client, ws, next(r["id"] for r in runs(client, ws) if r["record"]["display_name"] == "Late"))
    assert [s["status"] for s in moved["steps"]] == ["waiting", "migrated"]  # it waited at a, and was moved to b
    assert moved["steps"][1]["node_id"] == "a" and moved["steps"][1]["output"]["to"] == "b"
    wake(db)
    wake(db)
    assert tags_of(client, ws, early["id"]) == ["done"] and tags_of(client, ws, late["id"]) == ["done"]


def test_a_removed_step_can_exit_its_runs_and_a_removed_step_nobody_is_at_needs_no_answer(crm, db):
    client, ws, _ = crm
    wf, early, late = _waiting_in_two_places(client, ws, db)
    three = graph({"b": pause({"duration": {"days": 2}}, "mark"), "mark": tag("done"),
                   "extra": pause({"duration": {"days": 1}}, "mark")}, start="b")
    assert fields(client.post(f"{ROOT}/{wf['id']}/versions", json={"graph": three}, headers={H: ws})) == {
        "graph.nodes.extra": "is not reachable: nothing leads to it (remove it or connect it)"}
    two = graph({"b": pause({"duration": {"days": 2}}, "mark"), "mark": tag("done")})
    post(client, ws, f"/{wf['id']}/versions", {"graph": two}, status=201)
    done = post(client, ws, f"/{wf['id']}/publish", {"migrate": {"a": "exit"}})
    assert done["publish"]["moved"] == 1 and done["publish"]["exited"] == 1
    states = {r["record"]["display_name"]: r["status"] for r in runs(client, ws)}
    assert states == {"Early": "waiting", "Late": "exited"}
    exited = sql(db, "SELECT data->>'reason' FROM events WHERE type = 'workflow.run_completed' "
                     "AND data->>'status' = 'exited'")
    assert exited == [("version 2 removed the step it was at",)]
    wake(db)
    wake(db)
    assert tags_of(client, ws, early["id"]) == ["done"] and tags_of(client, ws, late["id"]) == []


# --- pause, resume, archive, cancel, retry ----------------------------------------------------------------------

def test_pause_freezes_the_runs_and_stops_new_ones_and_resume_picks_them_up_again(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "done")
    wf = live(client, ws, graph({"hold": pause({"duration": {"days": 1}}, "mark"), "mark": tag("done")}))
    first = contact(client, ws)
    pump(db)
    assert post(client, ws, f"/{wf['id']}/pause")["status"] == "paused"
    second = contact(client, ws, first_name="Bob", email="bob@example.com")
    wake(db)  # the wake-up comes while it is paused: nothing moves, nothing enters
    assert [r["record"]["display_name"] for r in runs(client, ws)] == ["Ada"] and tags_of(client, ws, first["id"]) == []
    assert only_run(client, ws)["status"] == "waiting"
    assert fields_or_status(client, ws, f"/{wf['id']}/pause") == 409  # only a published one can be paused
    db.execute(text("UPDATE workflow_runs SET wake_at = now() - interval '1 minute'"))  # the day is over now
    db.commit()
    assert post(client, ws, f"/{wf['id']}/resume")["status"] == "published"
    pump(db)  # the wake-up was queued again, for the run's own time
    assert only_run(client, ws, record_id=first["id"])["status"] == "completed" and tags_of(
        client, ws, first["id"]) == ["done"]
    assert fields_or_status(client, ws, f"/{wf['id']}/resume") == 409
    assert tags_of(client, ws, second["id"]) == []  # it was created while paused and never entered
    assert [t for (t,) in sql(db, "SELECT data->'changes'->'status'->>'new' FROM events "
                                   "WHERE type = 'workflow.updated' ORDER BY id")][-2:] == ["paused", "published"]


def fields_or_status(client, ws, path) -> int:
    return client.post(f"{ROOT}{path}", headers={H: ws}).status_code


def test_archiving_cancels_the_runs_in_flight_and_each_is_an_event(crm, db):
    client, ws, _ = crm
    wf = live(client, ws, graph({"hold": pause({"duration": {"days": 1}}, "end"), "end": END}))
    for n in range(3):
        contact(client, ws, first_name=f"P{n}", email=f"p{n}@example.com")
    pump(db)
    assert {r["status"] for r in runs(client, ws)} == {"waiting"} and len(runs(client, ws)) == 3
    assert client.delete(f"{ROOT}/{wf['id']}", headers={H: ws}).status_code == 204
    assert {r["status"] for r in runs(client, ws)} == {"cancelled"}
    cancelled = sql(db, "SELECT data->>'reason' FROM events WHERE type = 'workflow.run_cancelled'")
    assert cancelled == [("the workflow was archived",)] * 3
    wake(db)
    assert {r["status"] for r in runs(client, ws)} == {"cancelled"}  # the wake-ups find nothing to do
    assert sql(db, "SELECT count(*) FROM workflow_waiters WHERE resolved_at IS NULL")[0][0] == 0


def test_a_run_is_cancelled_by_a_person_and_its_wake_up_does_nothing(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "done")
    live(client, ws, graph({"hold": pause({"duration": {"days": 1}}, "mark"), "mark": tag("done")}))
    ada = contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    cancelled = post(client, ws, f"/runs/{run['id']}/cancel")
    assert cancelled["status"] == "cancelled" and cancelled["ended_at"] and cancelled["wake_at"] is None
    assert walked(cancelled)[-1] == ("hold", "cancelled") and cancelled["steps"][-1]["output"]["reason"] == (
        "cancelled by a person")
    assert client.post(f"{ROOT}/runs/{run['id']}/cancel", headers={H: ws}).status_code == 409
    wake(db)
    assert tags_of(client, ws, ada["id"]) == [] and only_run(client, ws)["status"] == "cancelled"
    assert client.post(f"{ROOT}/runs/{uuid.uuid4()}/cancel", headers={H: ws}).status_code == 404


def test_only_a_failed_run_can_be_retried_and_only_while_the_workflow_runs(crm, db):
    client, ws, _ = crm
    gone = make_tag(client, ws, "temporary")
    wf = live(client, ws, graph({"go": tag("temporary")}))
    assert client.delete(f"/api/v1/tags/{gone['id']}", headers={H: ws}).status_code == 204
    contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "failed"
    post(client, ws, f"/{wf['id']}/pause")
    assert client.post(f"{ROOT}/runs/{run['id']}/retry", headers={H: ws}).status_code == 409  # paused: resume first
    post(client, ws, f"/{wf['id']}/resume")
    again = post(client, ws, f"/runs/{run['id']}/retry")  # the tag is still gone: it fails again, and says so
    assert again["status"] == "running" and again["error"] is None
    pump(db)
    assert only_run(client, ws)["status"] == "failed" and walked(only_run(client, ws)) == [("go", "failed")] * 2
    db.execute(text("UPDATE workflow_runs SET steps = 500"))
    db.commit()
    loop = client.post(f"{ROOT}/runs/{run['id']}/retry", headers={H: ws})
    assert loop.status_code == 409 and "loop guard" in loop.json()["error"]["message"]
    done = live(client, ws, graph({"go": END}), name="Done")
    contact(client, ws, first_name="Bob", email="bob@example.com")
    pump(db)
    finished = next(r for r in runs(client, ws) if r["workflow_id"] == done["id"])
    assert client.post(f"{ROOT}/runs/{finished['id']}/retry", headers={H: ws}).status_code == 409  # not failed


def test_runs_are_listed_newest_first_with_filters_and_test_runs_only_when_asked_for(crm, db):
    client, ws, _ = crm
    first = live(client, ws, graph({"go": END}), name="First")
    second = live(client, ws, graph({"hold": pause({"duration": {"days": 1}}, "end"), "end": END}), name="Second")
    ada, bob = contact(client, ws), contact(client, ws, first_name="Bob", email="bob@example.com")
    pump(db)
    everything = runs(client, ws)
    assert len(everything) == 4 and all(r["test"] is False for r in everything)
    assert [r["started_at"] for r in everything] == sorted((r["started_at"] for r in everything), reverse=True)
    assert {r["workflow_id"] for r in runs(client, ws, workflow_id=first["id"])} == {first["id"]}
    assert {r["status"] for r in runs(client, ws, status="waiting")} == {"waiting"}
    assert len(runs(client, ws, status="completed")) == 2 and len(runs(client, ws, record_id=bob["id"])) == 2
    assert len(runs(client, ws, workflow_id=second["id"], record_id=ada["id"], status="waiting")) == 1
    page = get(client, ws, "/runs", limit=3)
    assert len(page["data"]) == 3 and page["next_cursor"]
    rest = get(client, ws, "/runs", limit=3, cursor=page["next_cursor"])
    assert len(rest["data"]) == 1 and rest["next_cursor"] is None
    r = client.get(f"{ROOT}/runs", params={"status": "bogus"}, headers={H: ws})
    assert r.status_code == 422
    posted = post(client, ws, f"/{first['id']}/test", {"record_id": ada["id"]})
    assert posted["run"]["test"] is True
    assert len(runs(client, ws)) == 4 and [r["id"] for r in runs(client, ws, test="true")] == [posted["run"]["id"]]


# --- dependencies and the catalog -------------------------------------------------------------------------------

def test_what_uses_a_tag_a_field_a_stage_a_person_or_a_channel_is_one_query(crm, db):
    client, ws, ids = crm
    vip, old = make_tag(client, ws, "vip"), make_tag(client, ws, "old")
    stages = stage_ids(client, ws)
    ben = user_id_of(add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws))
    sms = add_channel(client, ws)
    one = live(client, ws, graph({
        "q": ask({"and": [{"tag": "VIP"}, {"field": "lifecycle", "op": "is", "value": "lead"}]}, "t", "o"),
        "t": tag(vip["id"]), "o": act("owner.assign", {"user_id": ben}, "m"),
        "m": act("message.send", {"channel_id": sms["id"], "body": "Hi"})}), name="Uses many")
    post(client, ws, f"/{one['id']}/versions", {"graph": graph({"q": tag("old")})}, status=201)  # a draft, no vip
    two = live(client, ws, graph({"go": act("record.update", {"values": {"lifecycle": "lead"}})}, object="contact",
                                 filter={"tag": "old"}), name="Uses lifecycle")
    three = live(client, ws, graph({"go": act("deal.move_stage", {"stage_id": stages["won"]})}, object="deal"),
                 name="Deals")
    by_tag = get(client, ws, "/refs", kind="tag", id=vip["id"])["data"]
    assert by_tag == [{"workflow_id": one["id"], "name": "Uses many", "status": "published", "versions": [1],
                       "nodes": ["q", "t"], "in_published": True}]  # by name in one node and by id in the other
    assert get(client, ws, "/refs", kind="tag", key="Vip")["data"] == by_tag
    old_uses = get(client, ws, "/refs", kind="tag", id=old["id"])["data"]
    assert [(u["name"], u["versions"], u["in_published"]) for u in old_uses] == [("Uses lifecycle", [1], True),
                                                                                  ("Uses many", [2], False)]
    assert old_uses[1]["nodes"] == ["q"] and old_uses[0]["nodes"] == ["trigger"]
    fields_ = get(client, ws, "/refs", kind="field", key="contact.lifecycle")["data"]
    assert [u["name"] for u in fields_] == ["Uses lifecycle", "Uses many"]
    assert [u["name"] for u in get(client, ws, "/refs", kind="stage", id=stages["won"])["data"]] == ["Deals"]
    assert [u["name"] for u in get(client, ws, "/refs", kind="user", id=ben)["data"]] == ["Uses many"]
    assert [u["name"] for u in get(client, ws, "/refs", kind="channel", id=sms["id"])["data"]] == ["Uses many"]
    assert get(client, ws, "/refs", kind="stage", id=stages["lost"])["data"] == [] and two and three
    assert get(client, ws, "/refs", expect=404, kind="tag", id=str(uuid.uuid4()))
    assert client.get(f"{ROOT}/refs", params={"kind": "tag"}, headers={H: ws}).status_code == 422
    assert client.get(f"{ROOT}/refs", params={"kind": "tag", "id": vip["id"], "key": "vip"},
                      headers={H: ws}).status_code == 422
    assert client.delete(f"{ROOT}/{one['id']}", headers={H: ws}).status_code == 204
    assert get(client, ws, "/refs", kind="tag", id=vip["id"])["data"] == []  # an archived workflow uses nothing


def test_the_catalog_route_serves_what_the_builder_is_made_of(crm):
    client, ws, _ = crm
    catalog = get(client, ws, "/catalog")
    assert {t["event"] for t in catalog["triggers"]} >= {"record.created", "form.submitted", "deal.stage_changed"}
    assert {a["key"] for a in catalog["actions"]} == {
        "record.update", "tag.add", "tag.remove", "owner.assign", "deal.move_stage", "task.create", "message.send",
        "notify.user", "webhook.send"}
    assert [n["type"] for n in catalog["nodes"]][:2] == ["action", "wait"]
    assert catalog["limits"]["max_steps_per_run"] == 500
