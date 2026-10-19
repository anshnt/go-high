"""Enrollment: the events consumer judges every event against every published workflow of the trigger, logs each check
with the clause that failed, and starts runs (once: re-entry off, a live run blocks another, a race makes one)."""
import threading
import uuid

import pytest
from helpers import H, make_deal
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from workflow_helpers import (
    ROOT,
    contact,
    create,
    graph,
    live,
    make_tag,
    only_run,
    publish,
    pump,
    runs,
    sql,
    tag,
    tags_of,
)

from app.db import SessionLocal, acting
from app.models import Workspace
from app.records.models import Record
from app.workflows import enroll
from app.workflows.models import Workflow, WorkflowVersion

LEAD = {"field": "lifecycle", "op": "is", "value": "lead"}


def checks(db, workflow_id=None):
    where = "WHERE workflow_id = :w" if workflow_id else ""
    return sql(db, f"SELECT event_type, matched, outcome, reason FROM workflow_trigger_checks {where} "
                   "ORDER BY event_id, id", w=workflow_id)


def test_a_new_contact_that_passes_the_filter_enters_and_one_that_does_not_is_logged_with_the_clause_that_failed(
        crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "welcome")
    wf = live(client, ws, graph({"go": tag("welcome")}, filter={"and": [
        LEAD, {"field": "email", "op": "contains", "value": "@example.com"}]}))
    lead = contact(client, ws, lifecycle="lead")
    customer = contact(client, ws, first_name="Bob", email="bob@example.com", lifecycle="customer")
    odd = contact(client, ws, first_name="Cy", email="cy@elsewhere.org", lifecycle="lead")
    pump(db)
    assert {r["record"]["id"] for r in runs(client, ws)} == {lead["id"]}
    log = {r[3] for r in checks(db, wf["id"]) if not r[1]}
    assert log == {'Lifecycle stage is "lead" did not hold (it is "customer")',
                   'Email contains "@example.com" did not hold (it is "cy@elsewhere.org")'}
    rows = sql(db, "SELECT record_id::text, matched, outcome, event_type, run_id IS NOT NULL FROM "
                   "workflow_trigger_checks WHERE workflow_id = :w", w=wf["id"])
    assert {(r[0], r[1], r[2], r[3], r[4]) for r in rows} == {
        (lead["id"], True, "entered", "record.created", True),
        (customer["id"], False, "filter", "record.created", False),
        (odd["id"], False, "filter", "record.created", False)}
    assert tags_of(client, ws, lead["id"]) == ["welcome"] and tags_of(client, ws, customer["id"]) == []


def test_a_workflow_on_record_updated_sees_the_change_and_each_event_is_judged_once(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "now-a-lead")
    wf = live(client, ws, graph({"go": tag("now-a-lead")}, event="record.updated", filter=LEAD))
    person = contact(client, ws, lifecycle="other")
    pump(db)
    assert runs(client, ws) == [] and checks(db, wf["id"]) == []  # a creation is not an update
    patch = f"/api/v1/objects/contact/records/{person['id']}"
    client.patch(patch, json={"values": {"first_name": "Still"}}, headers={H: ws})
    pump(db)
    client.patch(patch, json={"values": {"lifecycle": "lead"}}, headers={H: ws})
    pump(db)
    got = checks(db, wf["id"])
    assert [(g[0], g[2]) for g in got] == [("record.updated", "filter"), ("record.updated", "entered")]
    assert got[0][3] == 'Lifecycle stage is "lead" did not hold (it is "other")'  # the change of name alone
    assert only_run(client, ws)["status"] == "completed" and tags_of(client, ws, person["id"]) == ["now-a-lead"]
    db.execute(text("DELETE FROM event_cursors WHERE consumer = 'workflows'"))  # every event is read again
    db.commit()
    pump(db)
    assert len(checks(db, wf["id"])) == 2 and len(runs(client, ws)) == 1  # judged once, started once


def test_the_trigger_can_name_the_object_and_the_data_the_event_must_hold(crm, db):
    client, ws, _ = crm
    vip = make_tag(client, ws, "vip")
    other = make_tag(client, ws, "other")
    make_tag(client, ws, "seen")
    for_deals = live(client, ws, graph({"go": tag("seen")}, object="deal"), name="Deals only")
    named = live(client, ws, graph({"go": tag("seen")}, event="tag.added", data={"name": "vip"}), name="VIP tag")
    person = contact(client, ws)
    make_deal(client, ws, "A deal")
    client.post(f"/api/v1/records/{person['id']}/tags", json={"add": [other["id"]]}, headers={H: ws})
    client.post(f"/api/v1/records/{person['id']}/tags", json={"add": [vip["id"]]}, headers={H: ws})
    pump(db)
    assert [(c[2], c[3]) for c in checks(db, for_deals["id"]) if not c[1]] == [
        ("object", "the record is a contact, and this workflow is for deal records")]
    assert [c[2] for c in checks(db, for_deals["id"])] == ["object", "entered"]  # the deal got in
    assert [(c[2], c[3]) for c in checks(db, named["id"]) if c[2] in ("data", "entered")] == [
        ("data", "name is 'other', and the trigger needs 'vip'"), ("entered", None)]
    assert {r["workflow"] for r in runs(client, ws)} == {"Deals only", "VIP tag"}


def test_re_entry_is_off_by_default_so_a_record_enters_once_and_on_it_may_enter_again_after_it_finished(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "touched")
    once = live(client, ws, graph({"go": tag("touched")}, event="record.updated"), name="Once")
    again = live(client, ws, graph({"go": tag("touched")}, event="record.updated"), name="Again",
                 settings={"reentry": True})
    assert once["settings"] == {"reentry": False} and again["settings"] == {"reentry": True}
    person = contact(client, ws)
    for n in range(3):
        client.patch(f"/api/v1/objects/contact/records/{person['id']}", json={"values": {"last_name": f"L{n}"}},
                     headers={H: ws})
        pump(db)
    by_workflow = {r["workflow"]: 0 for r in runs(client, ws)}
    for r in runs(client, ws):
        by_workflow[r["workflow"]] += 1
    assert by_workflow == {"Once": 1, "Again": 3}
    assert [c[2:] for c in checks(db, once["id"])] == [
        ("entered", None), ("reentry", "the record entered this workflow before, and re-entry is off"),
        ("reentry", "the record entered this workflow before, and re-entry is off")]
    assert all(c[1] for c in checks(db, once["id"]))  # the trigger matched; it was entry that re-entry refused


def test_a_record_in_a_workflow_does_not_enter_it_again_even_with_re_entry_on(crm, db):
    client, ws, _ = crm
    wf = live(client, ws, graph({"hold": {"type": "wait", "config": {"duration": {"days": 1}}, "next": None}},
                                event="record.updated"), settings={"reentry": True})
    person = contact(client, ws)
    for n in range(2):
        client.patch(f"/api/v1/objects/contact/records/{person['id']}", json={"values": {"last_name": f"L{n}"}},
                     headers={H: ws})
        pump(db)
    assert len(runs(client, ws)) == 1 and only_run(client, ws)["status"] == "waiting"
    assert [c[2] for c in checks(db, wf["id"])] == ["entered", "running"]
    assert checks(db, wf["id"])[1][3].startswith("the record is in this workflow already (run ")


def _enroll_together(ws, workflow, record, count=8):
    """`count` enrollers at once for one record, each in its own transaction (as workers would be)."""
    gate, outcomes, errors = threading.Barrier(count), [], []

    def one():
        try:
            with SessionLocal() as s:
                space, flow = s.get(Workspace, ws), s.get(Workflow, workflow)
                version = s.get(WorkflowVersion, flow.published_version_id)
                with acting(s, workspace_id=space.id, org_id=space.org_id):
                    rec = s.get(Record, record)
                    gate.wait(10)
                    outcomes.append(enroll.admit(s, flow, version, rec)[0])
                    s.commit()
        except Exception as e:  # pragma: no cover - the assertion below reports it
            errors.append(e)

    threads = [threading.Thread(target=one) for _ in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors
    return outcomes


def test_re_entry_off_makes_double_enrollment_impossible_under_concurrency(crm, db):
    client, ws, _ = crm
    wf = create(client, ws, graph({"go": {"type": "end", "config": {}}}), name="Race")
    publish(client, ws, wf["id"])
    person = contact(client, ws)
    outcomes = _enroll_together(ws, wf["id"], person["id"])
    assert sorted(outcomes) == ["entered"] + ["running"] * 7
    assert sql(db, "SELECT count(*) FROM workflow_runs WHERE record_id = :r", r=person["id"])[0][0] == 1
    pump(db)  # the run completes
    assert only_run(client, ws)["status"] == "completed"
    assert _enroll_together(ws, wf["id"], person["id"], count=4) == ["reentry"] * 4  # it is over, and re-entry is off
    assert sql(db, "SELECT count(*) FROM workflow_runs WHERE record_id = :r", r=person["id"])[0][0] == 1


def test_the_database_itself_refuses_a_second_live_run_for_a_record(crm, db):
    client, ws, _ = crm
    wf = create(client, ws, graph({"go": {"type": "end", "config": {}}}))
    publish(client, ws, wf["id"])
    person = contact(client, ws)
    version = sql(db, "SELECT published_version_id FROM workflows WHERE id = :w", w=wf["id"])[0][0]
    insert = text("INSERT INTO workflow_runs (workspace_id, workflow_id, version_id, record_id, status, node_id) "
                  "VALUES (:ws, :w, :v, :r, :s, 'go')")
    args = {"ws": ws, "w": wf["id"], "v": version, "r": person["id"]}
    db.execute(insert, {**args, "s": "running"})
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(insert, {**args, "s": "waiting"})
    db.rollback()
    db.execute(insert, {**args, "s": "completed"})  # a finished run does not count; a test run never does
    db.execute(text("INSERT INTO workflow_runs (workspace_id, workflow_id, version_id, record_id, status, node_id, "
                    "test) VALUES (:ws, :w, :v, :r, 'running', 'go', true)"), args)
    db.commit()
    assert sql(db, "SELECT count(*) FROM workflow_runs")[0][0] == 3


def test_an_event_the_same_workflow_caused_does_not_start_it_again(crm, db):
    client, ws, _ = crm
    wf = live(client, ws, graph({"go": {"type": "action", "action": "record.update",
                                        "config": {"values": {"last_name": "Touched"}}, "next": None}},
                                event="record.updated"), settings={"reentry": True})
    person = contact(client, ws)
    client.patch(f"/api/v1/objects/contact/records/{person['id']}", json={"values": {"first_name": "Bob"}},
                 headers={H: ws})
    pump(db)
    assert len(runs(client, ws)) == 1  # its own update (an event of its own) did not start another run
    last = checks(db, wf["id"])
    assert [c[2] for c in last] == ["entered", "self"]
    assert last[1][3] == "the change was made by this workflow, and a workflow never starts itself"


def test_a_workflow_that_is_paused_or_archived_or_only_a_draft_enrolls_nobody(crm, db):
    client, ws, _ = crm
    draft = create(client, ws, graph({"go": {"type": "end", "config": {}}}), name="Draft")
    paused = live(client, ws, graph({"go": {"type": "end", "config": {}}}), name="Paused")
    archived = live(client, ws, graph({"go": {"type": "end", "config": {}}}), name="Archived")
    running = live(client, ws, graph({"go": {"type": "end", "config": {}}}), name="Running")
    assert client.post(f"{ROOT}/{paused['id']}/pause", headers={H: ws}).status_code == 200
    assert client.delete(f"{ROOT}/{archived['id']}", headers={H: ws}).status_code == 204
    contact(client, ws)
    pump(db)
    assert {r["workflow"] for r in runs(client, ws)} == {"Running"}
    assert all(checks(db, w["id"]) == [] for w in (draft, paused, archived)) and len(checks(db, running["id"])) == 1


def test_a_filter_that_stopped_working_is_a_logged_miss_and_does_not_stop_the_consumer(crm, db):
    client, ws, _ = crm
    client.post("/api/v1/objects/contact/fields", headers={H: ws}, json={"key": "tier", "label": "Tier",
                                                                          "type": "text"})
    broken = live(client, ws, graph({"go": {"type": "end", "config": {}}},
                                    filter={"field": "tier", "op": "is", "value": "gold"}), name="Broken")
    fine = live(client, ws, graph({"go": {"type": "end", "config": {}}}), name="Fine")
    assert client.delete("/api/v1/objects/contact/fields/tier", headers={H: ws}).status_code in (200, 204)
    contact(client, ws)
    pump(db)
    miss = checks(db, broken["id"])[0]
    assert miss[1:3] == (False, "error")
    assert miss[3].startswith("the trigger's filter no longer works: trigger.filter.field")
    assert [c[2] for c in checks(db, fine["id"])] == ["entered"]  # and the consumer went on with the others
    assert sql(db, "SELECT count(*) FROM jobs WHERE status = 'dead'")[0][0] == 0


def test_a_deleted_record_ends_its_run_as_exited_and_workflow_events_never_start_workflows(crm, db):
    client, ws, _ = crm
    wf = live(client, ws, graph({"hold": {"type": "wait", "config": {"duration": {"days": 1}}, "next": None}}))
    person = contact(client, ws)
    pump(db)
    assert only_run(client, ws)["status"] == "waiting"
    assert client.delete(f"/api/v1/objects/contact/records/{person['id']}", headers={H: ws}).status_code == 204
    db.execute(text("UPDATE jobs SET run_at = now() WHERE status = 'queued'"))
    db.commit()
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "exited" and run["ended_at"]
    ended = sql(db, "SELECT data FROM events WHERE type = 'workflow.run_completed'")[0][0]
    assert ended["status"] == "exited" and ended["reason"] == "the record was deleted"
    started = sql(db, "SELECT count(*) FROM events WHERE type LIKE 'workflow.%'")[0][0]
    assert started >= 3 and len(checks(db, wf["id"])) == 1  # workflow.* events were read and ignored by the consumer


def test_the_check_log_is_kept_for_a_week_and_pruned_as_new_checks_are_written(crm, db):
    client, ws, _ = crm
    wf = live(client, ws, graph({"go": {"type": "end", "config": {}}}))
    contact(client, ws)
    pump(db)
    old = sql(db, "SELECT id FROM workflow_trigger_checks WHERE workflow_id = :w", w=wf["id"])[0][0]
    db.execute(text("UPDATE workflow_trigger_checks SET created_at = now() - interval '8 days' WHERE id = :i"),
               {"i": old})
    db.commit()
    contact(client, ws, first_name="Bob", email="bob@example.com")
    pump(db)
    assert len(checks(db, wf["id"])) == 1  # the old one is gone, the new one is here


def test_another_workspaces_events_do_not_enter_this_workspaces_workflows(crm, make_user, db):
    client, ws, _ = crm
    live(client, ws, graph({"go": {"type": "end", "config": {}}}))
    other, ids = make_user("other@example.com")
    contact(other, ids["workspace_id"])
    pump(db)
    assert runs(client, ws) == [] and sql(db, "SELECT count(*) FROM workflow_trigger_checks")[0][0] == 0


def test_explain_answers_why_a_record_did_not_enter_from_the_log_or_by_judging_it_now(crm, db):
    client, ws, _ = crm
    wf = create(client, ws, graph({"go": {"type": "end", "config": {}}}, filter=LEAD), name="Leads")
    early = contact(client, ws, lifecycle="lead")  # before the workflow went live: its creation is not the workflow's
    publish(client, ws, wf["id"])

    def explain(record):
        r = client.get(f"{ROOT}/{wf['id']}/explain", params={"record_id": record["id"]}, headers={H: ws})
        assert r.status_code == 200, r.text
        return r.json()

    pump(db)
    first = explain(early)
    assert first["checks"] == [] and first["in_workflow"] is False
    assert first["evaluation"] == {"outcome": "ok", "reason": None, "matched": True, "evaluated": "now"}
    assert first["answer"] == ("No record.created was read for this record in the last 7 days. Judged now, it would "
                               "enter when that event happens")
    late = contact(client, ws, first_name="Bob", email="bob@example.com", lifecycle="customer")
    pump(db)
    miss = explain(late)
    assert miss["evaluation"] is None and miss["checks"][0]["outcome"] == "filter"
    assert miss["checks"][0]["matched"] is False
    assert miss["answer"].startswith('Did not enter when record.created was read at ')
    assert miss["answer"].endswith('Lifecycle stage is "lead" did not hold (it is "customer")')
    in_flow = contact(client, ws, first_name="Cy", email="cy@example.com", lifecycle="lead")
    pump(db)
    entered = explain(in_flow)
    assert entered["checks"][0]["outcome"] == "entered" and entered["runs"][0]["status"] == "completed"
    assert entered["answer"].startswith("Entered when record.created was read at ")
    client.post(f"{ROOT}/{wf['id']}/pause", headers={H: ws})
    assert explain(in_flow)["answer"] == "Nothing enters a workflow that is paused: publish it first"
    assert client.get(f"{ROOT}/{wf['id']}/explain", params={"record_id": str(uuid.uuid4())},
                      headers={H: ws}).status_code == 404
