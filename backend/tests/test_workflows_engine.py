"""The engine: a run walks its graph one step per job and leaves a trace; waits park it and the queue wakes it; conditions,
splits and goals decide where it goes; the loop guard and the step slots hold it back."""
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from helpers import H
from sqlalchemy import text
from sqlalchemy.orm import Session
from workflow_helpers import (
    ROOT,
    act,
    ask,
    contact,
    detail,
    graph,
    live,
    make_tag,
    only_run,
    pause,
    pump,
    runs,
    sql,
    tag,
    tags_of,
    wake,
    walked,
)

from app import config
from app.db import engine
from app.workflows.engine import free_slot


def test_a_run_walks_its_nodes_one_step_per_job_and_leaves_a_trace(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "welcome")
    wf = live(client, ws, graph({
        "tag": tag("welcome", "set"),
        "set": act("record.update", {"values": {"lifecycle": "lead"}})}),
        name="Welcome")
    ada = contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed" and run["node_id"] is None and run["ended_at"] and run["workflow"] == "Welcome"
    assert [(s["seq"], s["node_id"], s["status"]) for s in run["steps"]] == [(1, "tag", "completed"),
                                                                            (2, "set", "completed")]
    assert run["step_count"] == len(run["steps"]) == 2 and run["record"]["id"] == ada["id"]
    assert run["steps"][0]["input"]["tag"] == "welcome" and run["steps"][0]["output"] == {"changed": True}
    assert run["steps"][1]["input"] == {"values": {"lifecycle": "lead"}} and run["steps"][1]["output"] == {
        "changed": True}
    assert all(s["started_at"] and s["finished_at"] for s in run["steps"])
    assert tags_of(client, ws, ada["id"]) == ["welcome"]
    assert get_lifecycle(client, ws, ada["id"]) == "lead"
    assert wf["id"] == run["workflow_id"]


def get_lifecycle(client, ws, record_id):
    return client.get(f"/api/v1/objects/contact/records/{record_id}", headers={H: ws}).json()["values"]["lifecycle"]


def test_what_a_workflow_changes_shows_by_the_workflow_in_the_timeline_and_the_audit_log(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "welcome")
    wf = live(client, ws, graph({"tag": tag("welcome", "set"),
                                 "set": act("record.update", {"values": {"lifecycle": "lead"}})}), name="Welcome")
    ada = contact(client, ws)
    pump(db)
    mine = {"type": "workflow", "id": wf["id"]}
    timeline = client.get(f"/api/v1/records/{ada['id']}/timeline", headers={H: ws}).json()["data"]
    by_workflow = {e["type"] for e in timeline if e["actor"] == mine}
    assert by_workflow == {"tag.added", "record.updated"}
    assert all(e["actor"]["type"] == "user" for e in timeline if e["type"] == "record.created")
    audit = client.get("/api/v1/audit", params={"actor": wf["id"], "limit": 200}, headers={H: ws}).json()["data"]
    assert {e["type"] for e in audit} >= {"tag.added", "record.updated", "workflow.run_started"}
    assert all(e["actor"] == mine for e in audit)


def test_a_duration_wait_parks_the_run_and_the_queue_wakes_it(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "one")
    make_tag(client, ws, "two")
    live(client, ws, graph({"before": tag("one", "hold"), "hold": pause({"duration": {"days": 2}}, "after"),
                            "after": tag("two")}))
    ada = contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "waiting" and run["node_id"] == "hold"
    soon = datetime.fromisoformat(run["wake_at"])
    assert timedelta(days=1, hours=23) < soon - datetime.now(UTC) < timedelta(days=2, minutes=1)
    assert walked(run) == [("before", "completed"), ("hold", "waiting")]
    assert tags_of(client, ws, ada["id"]) == ["one"]
    pump(db)  # nothing is due: the run stays parked
    assert only_run(client, ws)["status"] == "waiting"
    wake(db)
    run = only_run(client, ws)
    assert run["status"] == "completed" and tags_of(client, ws, ada["id"]) == ["one", "two"]
    assert walked(run) == [("before", "completed"), ("hold", "waiting"), ("hold", "completed"), ("after", "completed")]
    assert run["steps"][2]["output"] == {"resumed_by": "timer"} and run["wake_at"] is None


def test_a_wait_until_a_date_field_wakes_at_the_date_less_the_offset(crm, db):
    client, ws, _ = crm
    r = client.post("/api/v1/objects/contact/fields", headers={H: ws},
                    json={"key": "renewal", "label": "Renewal", "type": "date"})
    assert r.status_code == 201, r.text
    make_tag(client, ws, "renewing")
    live(client, ws, graph({"hold": pause({"until_field": {"field": "renewal", "offset": {"days": -1}}}, "after"),
                            "after": tag("renewing")}))
    day = (datetime.now(UTC) + timedelta(days=30)).date()
    ada = contact(client, ws, renewal=str(day))
    pump(db)
    run = only_run(client, ws)
    due = datetime.fromisoformat(run["wake_at"])
    assert due == datetime(day.year, day.month, day.day, 9, tzinfo=UTC) - timedelta(days=1)  # 09:00 the day before
    assert run["steps"][0]["input"] == {"until": {"field": "renewal", "offset": {"days": -1}, "at": "09:00"}}
    wake(db)
    assert only_run(client, ws)["status"] == "completed" and tags_of(client, ws, ada["id"]) == ["renewing"]


def test_a_date_that_has_passed_does_not_wait_and_an_empty_one_fails_the_step_with_a_reason(crm, db):
    client, ws, _ = crm
    client.post("/api/v1/objects/contact/fields", headers={H: ws},
                json={"key": "renewal", "label": "Renewal", "type": "date"})
    make_tag(client, ws, "done")
    live(client, ws, graph({"hold": pause({"until_field": {"field": "renewal"}}, "after"), "after": tag("done")}))
    late = contact(client, ws, renewal="2020-01-01")
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed" and walked(run) == [("hold", "completed"), ("after", "completed")]
    assert run["steps"][0]["output"]["already_past"] is True and tags_of(client, ws, late["id"]) == ["done"]
    contact(client, ws, first_name="Bob", email="bob@example.com")
    pump(db)
    failed = [r for r in runs(client, ws) if r["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["error"] == "Renewal is empty, so there is nothing to wait for"


def test_a_wait_for_an_event_goes_on_when_it_happens_or_when_the_timeout_passes(crm, db):
    client, ws, _ = crm
    for name in ("replied", "got-reply", "no-reply"):
        make_tag(client, ws, name)
    live(client, ws, graph({"hold": {"type": "wait", "config": {"event": {
        "event": "tag.added", "match": {"name": "replied"}, "timeout": {"days": 3}}},
        "branches": {"event": "yes", "timeout": "no"}},
        "yes": tag("got-reply"), "no": tag("no-reply")}))
    quick, slow = contact(client, ws), contact(client, ws, first_name="Bob", email="bob@example.com")
    pump(db)
    assert {r["status"] for r in runs(client, ws)} == {"waiting"}
    waiting = only_run(client, ws, record_id=quick["id"])
    assert waiting["waiting_for"] == [{"event_type": "tag.added", "match": {"name": "replied"}}]
    replied = [t for t in client.get("/api/v1/tags", headers={H: ws}).json()["data"] if t["name"] == "replied"][0]
    client.post(f"/api/v1/records/{quick['id']}/tags", json={"add": [replied["id"]]}, headers={H: ws})
    pump(db)
    done = only_run(client, ws, record_id=quick["id"])
    assert done["status"] == "completed" and done["waiting_for"] == []
    assert walked(done) == [("hold", "waiting"), ("hold", "completed"), ("yes", "completed")]
    assert done["steps"][1]["output"]["resumed_by"] == "event" and "got-reply" in tags_of(client, ws, quick["id"])
    wake(db)  # three days pass for the other one: its timeout branch
    timed_out = only_run(client, ws, record_id=slow["id"])
    assert walked(timed_out) == [("hold", "waiting"), ("hold", "completed"), ("no", "completed")]
    assert timed_out["steps"][1]["output"] == {"resumed_by": "timeout"} and tags_of(client, ws, slow["id"]) == [
        "no-reply"]


def test_a_condition_takes_the_branch_the_record_decides_and_says_why(crm, db):
    client, ws, _ = crm
    for name in ("vip", "regular"):
        make_tag(client, ws, name)
    live(client, ws, graph({"look": ask({"and": [{"field": "lifecycle", "op": "is", "value": "customer"},
                                                {"field": "email", "op": "contains", "value": "@vip."}]},
                                        "vip", "regular"),
                            "vip": tag("vip"), "regular": tag("regular")}))
    big = contact(client, ws, email="a@vip.example.com", lifecycle="customer")
    small = contact(client, ws, first_name="Bob", email="b@vip.example.com", lifecycle="lead")
    pump(db)
    assert tags_of(client, ws, big["id"]) == ["vip"] and tags_of(client, ws, small["id"]) == ["regular"]
    first = only_run(client, ws, record_id=big["id"])
    assert first["steps"][0]["output"] == {"matched": True, "branch": "yes"}
    second = only_run(client, ws, record_id=small["id"])
    assert second["steps"][0]["output"]["matched"] is False and second["steps"][0]["output"]["branch"] == "no"
    assert second["steps"][0]["output"]["why"] == 'Lifecycle stage is "customer" did not hold (it is "lead")'


def test_a_split_sends_a_run_down_the_path_its_id_decides(crm, db):
    client, ws, _ = crm
    for name in ("a-side", "b-side"):
        make_tag(client, ws, name)
    live(client, ws, graph({"flip": {"type": "split", "config": {"paths": [
        {"name": "a", "percent": 50}, {"name": "b", "percent": 50}]}, "branches": {"a": "ta", "b": "tb"}},
        "ta": tag("a-side"), "tb": tag("b-side")}))
    for n in range(24):
        contact(client, ws, first_name=f"P{n}", email=f"p{n}@example.com")
    pump(db)
    found = {"a": 0, "b": 0}
    for r in runs(client, ws):
        step = detail(client, ws, r["id"])["steps"][0]
        bucket = int(hashlib.sha256(f"{r['id']}:flip".encode()).hexdigest(), 16) % 100
        assert step["output"] == {"path": "a" if bucket < 50 else "b", "bucket": bucket}  # the run id decides
        assert tags_of(client, ws, r["record"]["id"]) == [f"{step['output']['path']}-side"]
        found[step["output"]["path"]] += 1
    assert found["a"] > 0 and found["b"] > 0 and sum(found.values()) == 24


def test_a_goal_takes_a_waiting_run_the_moment_its_condition_becomes_true(crm, db):
    client, ws, _ = crm
    for name in ("customer", "won", "nudged"):
        make_tag(client, ws, name)
    live(client, ws, graph({
        "hold": pause({"duration": {"days": 5}}, "nudge"), "nudge": tag("nudged"),
        "goal": {"type": "goal", "config": {"filter": {"tag": "customer"}}, "next": "won"}, "won": tag("won")},
        start="hold"))
    ada, bob = contact(client, ws), contact(client, ws, first_name="Bob", email="bob@example.com")
    pump(db)
    customer = [t for t in client.get("/api/v1/tags", headers={H: ws}).json()["data"] if t["name"] == "customer"][0]
    client.post(f"/api/v1/records/{ada['id']}/tags", json={"add": [customer["id"]]}, headers={H: ws})
    pump(db)
    jumped = only_run(client, ws, record_id=ada["id"])
    assert jumped["status"] == "completed" and walked(jumped) == [("hold", "waiting"), ("goal", "completed"),
                                                                  ("won", "completed")]
    assert jumped["steps"][1]["output"]["jumped"] is True and jumped["steps"][1]["output"]["from"] == "hold"
    assert tags_of(client, ws, ada["id"]) == ["customer", "won"]
    assert only_run(client, ws, record_id=bob["id"])["status"] == "waiting"  # nobody else was touched
    wake(db)  # and the wake-up of the run that jumped finds it gone: nothing runs twice
    assert tags_of(client, ws, ada["id"]) == ["customer", "won"]
    assert tags_of(client, ws, bob["id"]) == ["nudged"]


def test_a_run_that_walks_to_a_goal_it_has_not_met_goes_on_or_ends_as_the_goal_says(crm, db):
    client, ws, _ = crm
    for name in ("customer", "after"):
        make_tag(client, ws, name)
    for otherwise, expected in (("continue", ["after"]), ("end", [])):
        wf = live(client, ws, graph({"goal": {"type": "goal", "config": {"filter": {"tag": "customer"},
                                                                          "otherwise": otherwise}, "next": "then"},
                                     "then": tag("after")}, event="record.updated"), name=otherwise)
        person = contact(client, ws, first_name=otherwise, email=f"{otherwise}@example.com")
        client.patch(f"/api/v1/objects/contact/records/{person['id']}", json={"values": {"lifecycle": "lead"}},
                     headers={H: ws})
        pump(db)
        assert tags_of(client, ws, person["id"]) == expected
        run = only_run(client, ws, record_id=person["id"], workflow_id=wf["id"])
        assert run["status"] == "completed" and run["steps"][0]["output"]["met"] is False
        assert ("ended" in run["steps"][0]["output"]) is (otherwise == "end")
        assert client.post(f"{ROOT}/{wf['id']}/pause", headers={H: ws}).status_code == 200  # the next case alone


def test_the_loop_guard_stops_a_run_at_500_steps(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "again")
    live(client, ws, graph({"go": tag("again", "hold"), "hold": pause({"duration": {"minutes": 1}}, "go")}))
    ada = contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "waiting"
    db.execute(text("UPDATE workflow_runs SET steps = 500 WHERE id = :i"), {"i": run["id"]})
    db.execute(text("UPDATE jobs SET payload = jsonb_set(payload, '{n}', '500')"))  # the wake-up that was scheduled
    db.commit()
    wake(db)
    stopped = only_run(client, ws)
    assert stopped["status"] == "failed" and stopped["error"] == "Loop guard: the run has taken 500 steps"
    assert stopped["steps"][-1]["status"] == "failed" and stopped["node_id"] == "hold"
    assert sql(db, "SELECT count(*) FROM events WHERE type IN ('workflow.step_failed', 'workflow.run_failed')")[0][0] == 2
    assert tags_of(client, ws, ada["id"]) == ["again"]


def test_a_workspace_runs_at_most_the_configured_number_of_steps_at_once(crm, db, monkeypatch):
    """The slots are advisory locks: with every slot held by another transaction a step puts its job back instead of
    running, and runs as soon as one is free."""
    client, ws, _ = crm
    monkeypatch.setattr(config, "WORKFLOW_CONCURRENCY", 2)
    make_tag(client, ws, "ran")
    live(client, ws, graph({"go": tag("ran")}))
    ada = contact(client, ws)
    with Session(engine) as one, Session(engine) as two, Session(engine) as three:
        assert free_slot(one, uuid.UUID(ws)) and free_slot(two, uuid.UUID(ws))  # two transactions hold both slots
        assert not free_slot(three, uuid.UUID(ws))
        pump(db)  # the step finds both slots taken, and waits its turn
        assert only_run(client, ws)["status"] == "running" and tags_of(client, ws, ada["id"]) == []
        assert sql(db, "SELECT count(*) FROM jobs WHERE kind = 'workflow.step' AND status = 'queued'")[0][0] == 1
        one.rollback()  # one lets go: a slot is free
        wake(db)
    assert only_run(client, ws)["status"] == "completed" and tags_of(client, ws, ada["id"]) == ["ran"]
