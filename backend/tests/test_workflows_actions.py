"""The actions, one by one: what each does through the record engine's own write paths as the Automation role, what shows
in the trace, and how each fails (a step that cannot do its job says why, and the run stops there)."""
from datetime import UTC, datetime, timedelta

from helpers import H, add_member, make_deal, stage_ids, user_id_of
from sqlalchemy import text
from workflow_helpers import (
    ROOT,
    act,
    contact,
    detail,
    get_record,
    graph,
    live,
    make_tag,
    only_run,
    pump,
    runs,
    sql,
    tag,
    tags_of,
    walked,
)

P = "/api/v1/pipelines"


def one_step(client, ws, db, action, config, *, record=None, event="record.created", **trigger):
    """A workflow of one action, run for a new contact (or `record`'s object): returns (the run, the contact)."""
    live(client, ws, graph({"go": act(action, config)}, event=event, **trigger))
    made = record or contact(client, ws)
    pump(db)
    return only_run(client, ws), made


def automation_cannot(client, ws, capability: str) -> None:
    roles = client.get("/api/v1/roles", headers={H: ws}).json()["data"]
    role = next(r for r in roles if r["key"] == "automation")
    left = [c for c in role["capabilities"] if c != capability]
    assert client.patch(f"/api/v1/roles/{role['id']}", json={"capabilities": left}, headers={H: ws}).status_code == 200


def failed(run: dict, message: str) -> None:
    assert run["status"] == "failed" and run["error"] == message, run["error"]
    last = run["steps"][-1]
    assert last["status"] == "failed" and last["error"] == message and last["output"] == {}


# --- update fields ----------------------------------------------------------------------------------------------

def test_update_fields_sets_values_merges_the_records_own_fields_into_text_and_clears_with_null(crm, db):
    client, ws, _ = crm
    live(client, ws, graph({"go": act("record.update", {"values": {
        "last_name": "{{first_name}}son from {{ lifecycle }}", "phone": None}})}))
    ada = contact(client, ws, lifecycle="lead", phone="+14155550123")
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed" and run["steps"][0]["output"] == {"changed": True}
    assert run["steps"][0]["input"] == {"values": {"last_name": "Adason from Lead", "phone": None}}
    values = get_record(client, ws, ada["id"])["values"]
    assert values["last_name"] == "Adason from Lead" and "phone" not in values
    changed = sql(db, "SELECT data->'changes', actor_type FROM events WHERE type = 'record.updated'")[0]
    assert changed[1] == "workflow" and set(changed[0]) == {"last_name", "phone"}


def test_update_fields_that_changes_nothing_says_so_and_a_value_the_field_refuses_fails_the_step(crm, db):
    client, ws, _ = crm
    run, _ = one_step(client, ws, db, "record.update", {"values": {"first_name": "Ada"}})
    assert run["status"] == "completed" and run["steps"][0]["output"] == {"changed": False}  # it was Ada already
    client.post(f"{ROOT}/{run['workflow_id']}/pause", headers={H: ws})
    live(client, ws, graph({"go": act("record.update", {"values": {"lifecycle": "{{first_name}}"}})}), name="Bad")
    contact(client, ws, first_name="Bob", email="bob@example.com")
    pump(db)
    bad = next(r for r in runs(client, ws) if r["workflow"] == "Bad")
    run = detail(client, ws, bad["id"])
    assert run["status"] == "failed"
    assert run["error"].startswith("The contact is not valid: values.lifecycle: Lifecycle stage")
    assert run["steps"][0]["input"] == {"values": {"lifecycle": "{{first_name}}"}}  # what it was asked, unrendered


def test_update_fields_is_bound_by_what_the_automation_role_may_change(crm, db):
    client, ws, _ = crm
    live(client, ws, graph({"go": act("record.update", {"values": {"lifecycle": "lead"}})}))
    roles = client.get("/api/v1/roles", headers={H: ws}).json()["data"]
    automation = next(r for r in roles if r["key"] == "automation")
    rules = [{"object_key": "*", "scope": "all", "hidden_fields": [], "readonly_fields": ["lifecycle"]}]
    assert client.patch(f"/api/v1/roles/{automation['id']}", json={"object_rules": rules},
                        headers={H: ws}).status_code == 200
    contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "failed" and run["error"] == (
        "Your role cannot change these fields: values.lifecycle: is read-only for your role")


# --- tags -------------------------------------------------------------------------------------------------------

def test_tag_add_and_remove_work_by_name_or_id_and_report_whether_they_changed_anything(crm, db):
    client, ws, _ = crm
    vip, old = make_tag(client, ws, "vip"), make_tag(client, ws, "old")
    live(client, ws, graph({"a": act("tag.add", {"tag": "VIP"}, "b"), "b": act("tag.add", {"tag": vip["id"]}, "c"),
                            "c": act("tag.remove", {"tag": "old"}, "d"), "d": act("tag.remove", {"tag": old["id"]})}))
    ada = contact(client, ws)
    client.post(f"/api/v1/records/{ada['id']}/tags", json={"add": [old["id"]]}, headers={H: ws})
    pump(db)
    run = only_run(client, ws)
    assert [s["output"]["changed"] for s in run["steps"]] == [True, False, True, False]
    assert run["steps"][0]["input"] == {"tag": "vip", "tag_id": vip["id"]}
    assert tags_of(client, ws, ada["id"]) == ["vip"]
    actors = {a for (a,) in sql(db, "SELECT actor_type FROM events WHERE type IN ('tag.added', 'tag.removed')")}
    assert actors == {"user", "workflow"}  # the person's own tagging, and the workflow's


def test_a_tag_that_was_deleted_after_publishing_fails_the_step_and_the_run_waits_for_a_person(crm, db):
    client, ws, _ = crm
    gone, _ = make_tag(client, ws, "temporary"), make_tag(client, ws, "never")
    live(client, ws, graph({"go": tag("temporary", "next"), "next": tag("never")}))
    assert client.delete(f"/api/v1/tags/{gone['id']}", headers={H: ws}).status_code == 204
    ada = contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    failed(run, "There is no tag 'temporary': it was deleted or renamed")
    assert run["node_id"] == "go" and tags_of(client, ws, ada["id"]) == []
    types = [t for (t,) in sql(db, "SELECT type FROM events WHERE type LIKE 'workflow.%' ORDER BY id")]
    assert types[-2:] == ["workflow.step_failed", "workflow.run_failed"]
    step_failed = sql(db, "SELECT data FROM events WHERE type = 'workflow.step_failed'")[0][0]
    assert step_failed["node_id"] == "go" and step_failed["action"] == "tag.add" and step_failed["workflow_name"]


def test_an_action_the_automation_role_may_not_take_fails_naming_the_capability(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "vip")
    automation_cannot(client, ws, "tags.write")
    run, _ = one_step(client, ws, db, "tag.add", {"tag": "vip"})
    failed(run, "Your role does not allow this: it needs the capability tags.write")


# --- owner ------------------------------------------------------------------------------------------------------

def test_owner_assign_gives_the_record_to_a_person_or_round_robin_among_a_list(crm, db):
    client, ws, ids = crm
    ben = user_id_of(add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws))
    cara = user_id_of(add_member(db, ids["org_id"], "cara@example.com", workspace_id=ws))
    live(client, ws, graph({"go": act("owner.assign", {"round_robin": [ben, cara]})}), name="Rotation")
    owners = []
    for n in range(5):
        person = contact(client, ws, first_name=f"P{n}", email=f"p{n}@example.com")
        pump(db)
        owners.append(get_record(client, ws, person["id"])["owner_id"])
    assert owners == [ben, cara, ben, cara, ben]  # in turn, from the first
    last = detail(client, ws, runs(client, ws)[0]["id"])
    assert last["steps"][0]["input"] == {"owner_id": ben, "round_robin": True}
    assert last["steps"][0]["output"]["changed"] is True
    client.post(f"{ROOT}/{last['workflow_id']}/pause", headers={H: ws})
    live(client, ws, graph({"go": act("owner.assign", {"user_id": cara})}), name="Fixed")
    person = contact(client, ws, first_name="Fixed", email="fixed@example.com")
    pump(db)
    assert get_record(client, ws, person["id"])["owner_id"] == cara
    told = sql(db, "SELECT title FROM notifications WHERE user_id = :u ORDER BY created_at", u=cara)
    assert len(told) == 3 and told[0][0].startswith("A workflow assigned you P1")  # like any assignment


def test_owner_assign_fails_when_the_person_stopped_being_a_member(crm, db):
    client, ws, ids = crm
    ben = user_id_of(add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws))
    live(client, ws, graph({"go": act("owner.assign", {"user_id": ben})}))
    db.execute(text("DELETE FROM workspace_members WHERE user_id = :u"), {"u": ben})
    db.execute(text("DELETE FROM org_members WHERE user_id = :u"), {"u": ben})
    db.commit()
    contact(client, ws)
    pump(db)
    failed(only_run(client, ws), "The contact is not valid: owner_id: is not a member of this workspace")


# --- deal stage -------------------------------------------------------------------------------------------------

def test_move_stage_moves_a_deal_and_the_stage_event_names_the_workflow(crm, db):
    client, ws, _ = crm
    stages = stage_ids(client, ws)
    live(client, ws, graph({"go": act("deal.move_stage", {"stage_id": stages["qualified"]})},
                           event="record.created", object="deal"), name="Qualify")
    deal = make_deal(client, ws, "Big one")
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed" and run["steps"][0]["input"] == {"stage": "Qualified",
                                                                          "stage_id": stages["qualified"]}
    assert run["steps"][0]["output"] == {"changed": True, "from": "Lead"}
    assert get_record(client, ws, deal["id"], "deal")["values"]["stage"] == stages["qualified"]
    moved = sql(db, "SELECT actor_type, data->>'to_stage' FROM events WHERE type = 'deal.stage_changed'")
    assert moved[-1] == ("workflow", "Qualified")


def test_a_stage_that_refuses_to_let_the_deal_leave_fails_the_step_with_what_is_missing(crm, db):
    client, ws, _ = crm
    stages = stage_ids(client, ws)
    pipeline = client.get(P, headers={H: ws}).json()["data"][0]["id"]
    rules = {"and": [{"field": "amount", "op": "is_not_empty"}, {"field": "close_date", "op": "is_not_empty"}]}
    assert client.patch(f"{P}/{pipeline}/stages/{stages['lead']}", json={"exit_rules": rules},
                        headers={H: ws}).status_code == 200
    live(client, ws, graph({"go": act("deal.move_stage", {"stage_id": stages["qualified"]})},
                           event="record.created", object="deal"))
    deal = make_deal(client, ws, "No amount yet")
    pump(db)
    run = only_run(client, ws)
    failed(run, "The deal cannot leave Lead yet: values.amount: Amount is required to leave Lead; "
                "values.close_date: Close date is required to leave Lead")
    assert get_record(client, ws, deal["id"], "deal")["values"]["stage"] == stages["lead"]  # it stayed
    fixed = client.patch(f"/api/v1/objects/deal/records/{deal['id']}", headers={H: ws}, json={"values": {
        "amount": {"amount": 100, "currency": "USD"}, "close_date": "2030-01-01"}})
    assert fixed.status_code == 200
    r = client.post(f"{ROOT}/runs/{run['id']}/retry", headers={H: ws})  # a person fixed the deal and retries the step
    assert r.status_code == 200 and r.json()["status"] == "running"
    pump(db)
    again = detail(client, ws, run["id"])
    assert again["status"] == "completed" and walked(again) == [("go", "failed"), ("go", "completed")]
    assert get_record(client, ws, deal["id"], "deal")["values"]["stage"] == stages["qualified"]


def test_a_lost_stage_needs_its_reason_in_the_config(crm, db):
    client, ws, _ = crm
    stages = stage_ids(client, ws)
    live(client, ws, graph({"go": act("deal.move_stage", {"stage_id": stages["lost"]})},
                           event="record.created", object="deal"), name="Lose")
    make_deal(client, ws, "Doomed")
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "failed" and "values.lost_reason: Lost reason is required to move a deal to Lost" in run[
        "error"]
    client.post(f"{ROOT}/{run['workflow_id']}/pause", headers={H: ws})
    live(client, ws, graph({"go": act("deal.move_stage", {"stage_id": stages["lost"], "lost_reason": "price"})},
                           event="record.created", object="deal"), name="Lose with a reason")
    deal = make_deal(client, ws, "Doomed too")
    pump(db)
    assert get_record(client, ws, deal["id"], "deal")["values"]["lost_reason"] == "price"


# --- task -------------------------------------------------------------------------------------------------------

def test_task_create_makes_a_task_on_the_record_with_a_due_offset_and_the_owner_as_assignee(crm, db):
    client, ws, ids = crm
    ben = user_id_of(add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws))
    live(client, ws, graph({"go": act("task.create", {"title": "Call {{first_name}}", "notes": "About {{email}}",
                                                      "due": {"days": 2}, "priority": "high"})}))
    ada = contact(client, ws, owner_id=ben)
    pump(db)
    made = client.get("/api/v1/tasks", headers={H: ws}).json()["data"]
    assert len(made) == 1
    task = made[0]
    assert task["title"] == "Call Ada" and task["notes"] == "About ada@example.com" and task["priority"] == "high"
    assert task["record_id"] == ada["id"] and task["created_by"] is None and task["status"] == "open"
    assert task["assignee_id"] == ben  # whoever owns the record
    due = datetime.fromisoformat(task["due_at"])
    assert timedelta(days=1, hours=23) < due - datetime.now(UTC) < timedelta(days=2, minutes=1)
    run = only_run(client, ws)
    assert run["steps"][0]["output"] == {"task_id": task["id"]} and run["steps"][0]["input"]["title"] == "Call Ada"
    actor = sql(db, "SELECT actor_type FROM events WHERE type = 'task.created'")[0][0]
    assert actor == "workflow"


def test_task_create_can_name_the_assignee_and_fails_for_one_who_is_not_a_member(crm, db):
    client, ws, ids = crm
    ben = user_id_of(add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws))
    run, _ = one_step(client, ws, db, "task.create", {"title": "Follow up", "assignee": ben})
    assert run["status"] == "completed"
    assert client.get("/api/v1/tasks", headers={H: ws}).json()["data"][0]["assignee_id"] == ben
    db.execute(text("DELETE FROM workspace_members WHERE user_id = :u"), {"u": ben})
    db.execute(text("DELETE FROM org_members WHERE user_id = :u"), {"u": ben})
    db.commit()
    contact(client, ws, first_name="Bob", email="bob@example.com")
    pump(db)
    bad = next(r for r in runs(client, ws) if r["status"] == "failed")
    assert detail(client, ws, bad["id"])["error"] == "The task is not valid: assignee_id: is not a member of this workspace"


def test_task_create_is_bound_by_the_tasks_capability_of_the_automation_role(crm, db):
    client, ws, _ = crm
    automation_cannot(client, ws, "tasks.write")
    run, _ = one_step(client, ws, db, "task.create", {"title": "Follow up"})
    failed(run, "Your role does not allow this: it needs the capability tasks.write")
    assert client.get("/api/v1/tasks", headers={H: ws}).json()["data"] == []
