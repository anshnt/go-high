"""Test runs: a version walked for one record on a virtual clock, the real actions inside a savepoint that is rolled
back, messages and webhooks described and never sent, and a trace like a live run's."""
import hashlib
from datetime import UTC, datetime, timedelta

from helpers import H, add_member, stage_ids, user_id_of
from inbox_helpers import add_channel, point
from workflow_helpers import (
    ROOT,
    act,
    ask,
    contact,
    create,
    graph,
    live,
    make_tag,
    pause,
    pump,
    runs,
    sql,
    tag,
    tags_of,
)

from app.inbox import consent

END = {"type": "end", "config": {}}
WORLD = ("records", "record_tags", "tasks", "messages", "conversations", "notifications", "events", "jobs",
         "workflow_deliveries", "associations", "workflow_waiters", "workflow_trigger_checks")


def world(db) -> dict:
    """A fingerprint of everything a run could touch: row counts, the records' own times and what each row says."""
    counts = {t: sql(db, f"SELECT count(*) FROM {t}")[0][0] for t in WORLD}
    counts["records"] = sql(db, "SELECT md5(string_agg(r::text, '|' ORDER BY r.id)) FROM records r")[0][0]
    return counts


def try_flow(client, ws, workflow_id: str, record_id: str, status: int = 200, **more) -> dict:
    r = client.post(f"{ROOT}/{workflow_id}/test", json={"record_id": record_id, **more}, headers={H: ws})
    assert r.status_code == status, r.text
    return r.json()


def test_a_test_run_with_a_two_day_wait_finishes_at_once_with_a_full_trace_and_changes_nothing(
        crm, db, receiver, monkeypatch):
    client, ws, ids = crm
    ben = user_id_of(add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws))
    sms = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", '{"sid": "SMx"}')
    make_tag(client, ws, "welcome")
    wf = create(client, ws, graph({
        "tag": act("tag.add", {"tag": "welcome"}, "set"),
        "set": act("record.update", {"values": {"lifecycle": "customer"}}, "owner"),
        "owner": act("owner.assign", {"user_id": ben}, "look"),
        "look": ask({"and": [{"field": "lifecycle", "op": "is", "value": "customer"}, {"tag": "welcome"}]},
                    "hold", "end"),
        "hold": pause({"duration": {"days": 2}}, "send"),
        "send": act("message.send", {"channel_id": sms["id"], "body": "Hi {{first_name}}"}, "hook"),
        "hook": act("webhook.send", {"url": receiver.url("/hook"), "payload": {"who": "{{first_name}}"}}, "task"),
        "task": act("task.create", {"title": "Call {{first_name}}", "due": {"days": 1}}, "tell"),
        "tell": act("notify.user", {"user_id": ben, "title": "Done with {{first_name}}"}, "end"),
        "end": END}), name="Welcome")
    ada = contact(client, ws, phone="+14155550123")
    before = world(db)
    done = try_flow(client, ws, wf["id"], ada["id"])
    assert world(db) == before  # nothing of the world changed: the record, its tags, tasks, messages, events...
    run = done["run"]
    assert (run["test"], run["status"], run["node_id"], run["workflow"]) == (True, "completed", None, "Welcome")
    assert [(s["seq"], s["node_id"], s["status"]) for s in done["steps"]] == [
        (1, "tag", "completed"), (2, "set", "completed"), (3, "owner", "completed"), (4, "look", "completed"),
        (5, "hold", "waiting"), (6, "hold", "completed"), (7, "send", "completed"), (8, "hook", "completed"),
        (9, "task", "completed"), (10, "tell", "completed"), (11, "end", "completed")]
    by = {(s["node_id"], s["status"]): s for s in done["steps"]}
    assert by["look", "completed"]["output"] == {"matched": True, "branch": "yes"}  # it saw its own earlier changes
    assert by["hold", "waiting"]["output"]["skipped_seconds"] == 2 * 86400 and done["skipped_seconds"] == 2 * 86400
    assert by["hold", "completed"]["output"]["resumed_by"] == "timer"
    assert by["send", "completed"]["output"] == {"would_send": True, "sent": False}
    assert by["send", "completed"]["input"] == {"channel": "Main line", "to": "+14155550123", "subject": None,
                                                 "body": "Hi Ada"}
    assert by["hook", "completed"]["output"] == {"would_post": True, "sent": False}
    assert by["hook", "completed"]["input"]["body"]["data"] == {"who": "Ada"}
    due = datetime.fromisoformat(by["task", "completed"]["input"]["due_at"])
    assert due == consent.clock() + timedelta(days=3)  # a day after the two the virtual clock skipped
    assert by["tell", "completed"]["output"] == {"notified": False}
    assert receiver.requests == [] and tags_of(client, ws, ada["id"]) == []
    values = client.get(f"/api/v1/objects/contact/records/{ada['id']}", headers={H: ws}).json()
    assert "lifecycle" not in values["values"] and values["owner_id"] is None
    saved = [r for r in runs(client, ws, test="true")]
    assert len(saved) == 1 and saved[0]["id"] == run["id"] and runs(client, ws) == []  # kept, but not among the runs
    detail = client.get(f"{ROOT}/runs/{run['id']}", headers={H: ws}).json()
    assert [s["node_id"] for s in detail["steps"]] == [s["node_id"] for s in done["steps"]]
    pump(db)
    assert world(db) == before and receiver.requests == []  # and the worker has nothing to send either


def test_a_test_run_runs_the_real_checks_so_an_exit_rule_refuses_and_a_bad_value_fails_in_the_trace(crm, db):
    client, ws, _ = crm
    stages = stage_ids(client, ws)
    pipeline = client.get("/api/v1/pipelines", headers={H: ws}).json()["data"][0]["id"]
    client.patch(f"/api/v1/pipelines/{pipeline}/stages/{stages['lead']}", headers={H: ws},
                 json={"exit_rules": {"field": "amount", "op": "is_not_empty"}})
    wf = create(client, ws, graph({"go": act("deal.move_stage", {"stage_id": stages["qualified"]})}, object="deal"))
    deal = client.post("/api/v1/objects/deal/records", json={"values": {"name": "Thin"}}, headers={H: ws}).json()
    before = world(db)
    done = try_flow(client, ws, wf["id"], deal["id"])
    assert done["run"]["status"] == "failed" and [s["status"] for s in done["steps"]] == ["failed"]
    assert done["steps"][0]["error"] == ("The deal cannot leave Lead yet: values.amount: Amount is required to leave "
                                         "Lead")
    assert done["run"]["error"] == done["steps"][0]["error"] and done["run"]["node_id"] == "go"
    assert world(db) == before


def test_a_forced_path_takes_the_other_branch_of_a_split_a_condition_or_an_event_wait(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "a-side")
    make_tag(client, ws, "b-side")
    wf = create(client, ws, graph({
        "flip": {"type": "split", "config": {"paths": [{"name": "a", "percent": 50}, {"name": "b", "percent": 50}]},
                 "branches": {"a": "hold", "b": "hold"}},
        "hold": {"type": "wait", "config": {"event": {"event": "message.received", "timeout": {"days": 1}}},
                 "branches": {"event": "yes", "timeout": "no"}},
        "yes": tag("a-side", "q"), "no": tag("b-side", "q"),
        "q": ask({"field": "lifecycle", "op": "is", "value": "lead"}, None, None)}))
    ada = contact(client, ws)
    plain = try_flow(client, ws, wf["id"], ada["id"])
    bucket = int(hashlib.sha256(f"{plain['run']['id']}:flip".encode()).hexdigest(), 16) % 100
    assert plain["steps"][0]["output"] == {"path": "a" if bucket < 50 else "b", "bucket": bucket}
    assert [(s["node_id"], s["status"]) for s in plain["steps"]][1:] == [
        ("hold", "waiting"), ("hold", "completed"), ("no", "completed"), ("q", "completed")]  # a timeout by default
    assert plain["steps"][2]["output"]["resumed_by"] == "timeout" and plain["skipped_seconds"] == 86400
    forced = try_flow(client, ws, wf["id"], ada["id"], paths={"flip": "b", "hold": "event", "q": "yes"})
    assert forced["steps"][0]["output"]["path"] == "b"
    assert [s["node_id"] for s in forced["steps"]][1:] == ["hold", "hold", "yes", "q"]
    assert forced["steps"][2]["output"]["resumed_by"] == "event" and forced["steps"][4]["output"]["branch"] == "yes"
    r = client.post(f"{ROOT}/{wf['id']}/test", json={"record_id": ada["id"], "paths": {"nowhere": "x"}},
                    headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"paths.nowhere": "is not a step of this version"}


def test_a_goal_takes_a_test_run_to_it_as_soon_as_the_runs_own_changes_make_it_true(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "customer")
    make_tag(client, ws, "won")
    make_tag(client, ws, "late")
    wf = create(client, ws, graph({
        "make": tag("customer", "hold"), "hold": pause({"duration": {"days": 5}}, "late"), "late": tag("late"),
        "goal": {"type": "goal", "config": {"filter": {"tag": "customer"}}, "next": "won"}, "won": tag("won")},
        start="make"))
    ada = contact(client, ws)
    done = try_flow(client, ws, wf["id"], ada["id"])
    assert [(s["node_id"], s["status"]) for s in done["steps"]] == [
        ("make", "completed"), ("goal", "completed"), ("won", "completed")]  # it never reached the wait
    assert done["steps"][1]["output"] == {"jumped": True, "from": "hold"} and done["skipped_seconds"] == 0


def test_a_message_in_quiet_hours_is_described_as_put_off_and_the_virtual_clock_moves_to_the_end_of_them(
        crm, db, monkeypatch):
    client, ws, _ = crm
    sms = add_channel(client, ws)
    wf = create(client, ws, graph({"go": act("message.send", {"channel_id": sms["id"], "body": "Hi"})}))
    ada = contact(client, ws, phone="+14155550123")
    when = (datetime.now(UTC) + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(consent, "clock", lambda: when)  # 01:00 in Los Angeles
    before = world(db)
    done = try_flow(client, ws, wf["id"], ada["id"])
    assert [(s["node_id"], s["status"]) for s in done["steps"]] == [("go", "waiting"), ("go", "completed")]
    assert done["steps"][0]["output"]["reason"].startswith("Quiet hours") and done["skipped_seconds"] > 3600 * 6
    assert done["steps"][1]["output"] == {"would_send": True, "sent": False} and world(db) == before


def test_a_test_run_needs_a_visible_record_of_the_workflows_object_a_real_version_and_valid_paths(crm, db):
    client, ws, _ = crm
    wf = create(client, ws, graph({"go": END}))
    deal = client.post("/api/v1/objects/deal/records", json={"values": {"name": "D"}}, headers={H: ws}).json()
    r = client.post(f"{ROOT}/{wf['id']}/test", json={"record_id": deal["id"]}, headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {
        "record_id": "is a deal, and this workflow is for contact records"}
    ada = contact(client, ws)
    assert client.post(f"{ROOT}/{wf['id']}/test", json={"record_id": ada["id"], "version": 5},
                       headers={H: ws}).status_code == 404
    other = "00000000-0000-0000-0000-000000000042"
    assert client.post(f"{ROOT}/{wf['id']}/test", json={"record_id": other}, headers={H: ws}).status_code == 404
    bare = client.post(f"{ROOT}", json={"name": "No version"}, headers={H: ws}).json()
    assert client.post(f"{ROOT}/{bare['id']}/test", json={"record_id": ada["id"]}, headers={H: ws}).status_code == 404
    old = try_flow(client, ws, wf["id"], ada["id"], version=1)
    assert old["version"] == 1 and old["run"]["version"] == 1


def test_a_draft_is_tested_without_being_published_and_a_live_workflow_is_untouched_by_it(crm, db):
    client, ws, _ = crm
    make_tag(client, ws, "one")
    make_tag(client, ws, "two")
    wf = live(client, ws, graph({"go": tag("one")}))
    client.post(f"{ROOT}/{wf['id']}/versions", json={"graph": graph({"go": tag("two")})}, headers={H: ws})
    ada = contact(client, ws)
    draft = try_flow(client, ws, wf["id"], ada["id"])  # the newest version, which is a draft
    assert draft["version"] == 2 and draft["steps"][0]["input"]["tag"] == "two"
    live_one = try_flow(client, ws, wf["id"], ada["id"], version=1)
    assert live_one["steps"][0]["input"]["tag"] == "one"
    pump(db)
    assert tags_of(client, ws, ada["id"]) == ["one"]  # the real run of the published version, none of the tests
    assert len(runs(client, ws)) == 1 and len(runs(client, ws, test="true")) == 2
