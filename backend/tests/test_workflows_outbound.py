"""What leaves the system: messages through the inbox with its consent checks (quiet hours put a step off instead of
failing it), webhooks through the SSRF-guarded sender with a signature, notifications in the app. Every one goes through
an outbox row with the idempotency key `run:node`, so a step that runs again never sends twice: proved by a step that
crashes after it queued its row, and by a step run a second time over a row that was already committed."""
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from helpers import H, add_member, due_now, user_id_of, verify_signature
from inbox_helpers import add_channel, point, sms_in
from sqlalchemy import text
from workflow_helpers import (
    ROOT,
    act,
    contact,
    create,
    detail,
    graph,
    live,
    make_tag,
    only_run,
    pump,
    runs,
    sql,
    value_of,
    wake,
    walked,
)

from app.inbox import consent
from app.main import app
from app.workflows import engine

anonymous = TestClient(app)

SENT = '{"sid": "SMsent%d"}'
ALICE = "+14155550123"  # Los Angeles: quiet hours are read in its time zone


def send(channel, **more) -> dict:
    return act("message.send", {"channel_id": channel["id"], "body": "Hi {{first_name}}", **more})


def messages(db):
    return sql(db, "SELECT direction, status, body, idempotency_key, sent_by, subject FROM messages "
                   "WHERE kind = 'message' ORDER BY seq")


def at(monkeypatch, hour: int) -> datetime:
    """Fakes the consent clock to `hour` UTC tomorrow: a later day, so the end of a quiet window it computes is still
    ahead of the database's clock, which decides when a job is due, at any time of day the suite runs."""
    when = (datetime.now(UTC) + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(consent, "clock", lambda: when)
    return when


class Crash(BaseException):
    """A worker that dies: not an Exception, so nothing in the engine or the queue gets to handle it."""


def rewind(db, run_id: str, node: str) -> None:
    """The run as it was just before `node` ran, with its trace row gone: what a step that is run again would see if
    its outbox row had been committed but nothing else."""
    db.execute(text("DELETE FROM workflow_steps WHERE run_id = :r"), {"r": run_id})
    db.execute(text("UPDATE workflow_runs SET status = 'running', node_id = :n, steps = 0, ended_at = NULL "
                    "WHERE id = :r"), {"n": node, "r": run_id})
    db.execute(text("INSERT INTO jobs (kind, payload) VALUES ('workflow.step', jsonb_build_object("
                    "'run_id', CAST(:r AS text), 'node_id', CAST(:n AS text), 'n', 0))"), {"n": node, "r": run_id})
    db.commit()


# --- messages ---------------------------------------------------------------------------------------------------

def test_a_message_goes_through_the_inbox_with_the_runs_idempotency_key_and_is_sent_by_the_worker(
        crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    live(client, ws, graph({"go": send(channel)}))
    ada = contact(client, ws, phone=ALICE)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed"
    assert messages(db) == [("out", "sent", "Hi Ada", f"{run['id']}:go", None, None)]  # by nobody: the system
    assert len(receiver.requests) == 1 and b"Hi+Ada" in receiver.requests[0]["body"]
    step = run["steps"][0]
    assert step["input"] == {"channel": "Main line", "to": ALICE, "subject": None, "body": "Hi Ada"}
    assert step["output"] == {"message_id": sql(db, "SELECT id::text FROM messages WHERE kind = 'message'")[0][0]}
    queued = sql(db, "SELECT actor_type, actor_id::text FROM events WHERE type = 'message.queued'")[0]
    assert queued == ("workflow", run["workflow_id"])
    conv = client.get("/api/v1/conversations", headers={H: ws}).json()["data"][0]
    assert conv["contact"]["id"] == ada["id"] and conv["preview"] == "Hi Ada" and conv["last_direction"] == "out"


def test_opt_out_do_not_disturb_and_a_missing_number_stop_a_message_with_the_reason(
        crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    live(client, ws, graph({"go": send(channel)}, event="record.updated"))
    stopped = contact(client, ws, first_name="Stop", email="stop@example.com", phone="+14155550101")
    quiet = contact(client, ws, first_name="Quiet", email="quiet@example.com", phone="+14155550102")
    nobody = contact(client, ws, first_name="Nobody", email="nobody@example.com")
    assert sms_in(anonymous, channel, "+14155550101", "STOP").status_code == 200
    assert client.put(f"/api/v1/contacts/{quiet['id']}/consents/sms", json={"dnd": True},
                      headers={H: ws}).status_code == 200
    for person in (stopped, quiet, nobody):
        client.patch(f"/api/v1/objects/contact/records/{person['id']}", json={"values": {"lifecycle": "lead"}},
                     headers={H: ws})
    pump(db)
    found = {r["record"]["display_name"]: detail(client, ws, r["id"]) for r in runs(client, ws)}
    assert found["Stop"]["error"].startswith("Opted out by STOP on ")
    assert found["Quiet"]["error"] == "Do not disturb is on for sms"
    assert found["Nobody"]["error"] == "The contact has no way to be reached on Main line"
    assert all(r["status"] == "failed" for r in found.values())
    assert messages(db) == [] and not any(b"Hi" in r["body"] for r in receiver.requests)  # only the STOP reply left


def test_a_message_the_contacts_consent_refuses_can_be_skipped_instead_of_failing_the_run(
        crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    make_tag(client, ws, "done")
    live(client, ws, graph({"go": {**send(channel, if_refused="skip"), "next": "next"},
                            "next": act("tag.add", {"tag": "done"})}))
    person = contact(client, ws, phone=ALICE)
    client.put(f"/api/v1/contacts/{person['id']}/consents/sms", json={"dnd": True}, headers={H: ws})
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed" and run["steps"][0]["output"] == {
        "skipped": "Do not disturb is on for sms", "code": "dnd"}
    assert messages(db) == [] and receiver.requests == []


def test_quiet_hours_put_a_message_off_until_the_window_opens_instead_of_failing(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    live(client, ws, graph({"go": {**send(channel), "next": "after"},
                            "after": act("record.update", {"values": {"lifecycle": "lead"}})}))
    ada = contact(client, ws, phone=ALICE)
    night = at(monkeypatch, 8)  # 01:00 in Los Angeles: quiet from 21:00 to 08:00
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "waiting" and run["node_id"] == "go" and walked(run) == [("go", "waiting")]
    opens = datetime.fromisoformat(run["steps"][0]["output"]["deferred_until"])
    assert opens == datetime.fromisoformat(run["wake_at"]) and night < opens < night + timedelta(days=1)
    assert opens.astimezone(ZoneInfo("America/Los_Angeles")).hour == 8  # the window opens at 08:00 where they are
    assert run["steps"][0]["output"]["reason"].startswith("Quiet hours for this contact (America/")
    assert messages(db) == [] and receiver.requests == []
    wake(db)  # the queue wakes the step, but the clock still says night: it waits again, it does not fail
    assert only_run(client, ws)["status"] == "waiting" and messages(db) == []
    monkeypatch.setattr(consent, "clock", lambda: opens + timedelta(minutes=5))  # the window has opened
    wake(db)
    done = only_run(client, ws)
    assert done["status"] == "completed" and walked(done) == [("go", "waiting"), ("go", "waiting"), ("go", "completed"),
                                                              ("after", "completed")]
    assert messages(db) == [("out", "sent", "Hi Ada", f"{done['id']}:go", None, None)]  # one message, the first key
    assert len(receiver.requests) == 1 and value_of(client, ws, ada["id"], "lifecycle") == "lead"  # and it went on


def test_an_email_needs_a_subject_and_goes_out_with_it_and_a_whatsapp_message_goes_the_same_way(
        crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    mail, whatsapp = add_channel(client, ws, "mailgun"), add_channel(client, ws, "meta")
    point(monkeypatch, receiver, "mailgun", '{"id": "<out%d@mg>"}')
    r = client.post(ROOT, json={"name": "Mail", "graph": graph({"go": send(mail)})}, headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {
        "graph.nodes.go.config.subject": "is required to send an email"}
    mailer = live(client, ws, graph({"go": send(mail, subject="Welcome {{first_name}}")}), name="Mail")
    contact(client, ws)
    pump(db)
    assert [m[1:3] + m[4:] for m in messages(db)] == [("sent", "Hi Ada", None, "Welcome Ada")]
    assert len(receiver.requests) == 1
    assert client.post(f"{ROOT}/{mailer['id']}/pause", headers={H: ws}).status_code == 200
    live(client, ws, graph({"go": send(whatsapp)}, event="record.updated"), name="WhatsApp")
    point(monkeypatch, receiver, "meta", '{"messages": [{"id": "wamid.%d"}]}')
    person = contact(client, ws, first_name="Wa", email="wa@example.com", phone="+14155550199")
    client.patch(f"/api/v1/objects/contact/records/{person['id']}", json={"values": {"lifecycle": "lead"}},
                 headers={H: ws})
    pump(db)
    assert [(m[2], m[5]) for m in messages(db)] == [("Hi Ada", "Welcome Ada"), ("Hi Wa", None)]


def test_a_step_that_crashes_after_queueing_its_message_is_run_again_and_sends_exactly_one(
        crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    live(client, ws, graph({"go": send(channel)}))
    real, calls = engine.trace, []

    def dies_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:  # the message is queued; the worker dies before the step is recorded
            raise Crash
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "trace", dies_once)
    contact(client, ws, phone=ALICE)
    with pytest.raises(Crash):
        pump(db)
    assert messages(db) == [] and receiver.requests == []  # nothing of the dead step was kept
    run = only_run(client, ws)
    assert run["status"] == "running" and run["steps"] == []
    db.execute(text("UPDATE jobs SET locked_at = now() - interval '20 minutes' WHERE status = 'running' "
                    "AND kind = 'workflow.step'"))  # its lease runs out
    db.commit()
    pump(db)
    done = only_run(client, ws)
    assert done["status"] == "completed" and walked(done) == [("go", "completed")]
    assert messages(db) == [("out", "sent", "Hi Ada", f"{done['id']}:go", None, None)] and len(receiver.requests) == 1


def test_a_step_run_again_over_a_message_that_was_already_queued_finds_it_and_moves_on(
        crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    live(client, ws, graph({"go": send(channel)}))
    contact(client, ws, phone=ALICE)
    pump(db)
    run = only_run(client, ws)
    queued = run["steps"][0]["output"]["message_id"]
    rewind(db, run["id"], "go")  # the same step, with the same key, once more
    pump(db)
    again = only_run(client, ws)
    assert again["status"] == "completed" and again["steps"][0]["output"] == {"message_id": queued,
                                                                               "already_queued": True}
    assert len(messages(db)) == 1 and len(receiver.requests) == 1


# --- webhooks ---------------------------------------------------------------------------------------------------

def hook(receiver, **more) -> dict:
    return act("webhook.send", {"url": receiver.url("/hook"), "payload": {"who": "{{first_name}}", "n": 3}, **more})


def test_a_webhook_is_posted_signed_with_the_workflows_secret_and_the_runs_idempotency_key(crm, db, receiver):
    client, ws, _ = crm
    wf = create(client, ws, graph({"go": hook(receiver)}), name="Notify the CRM")
    publish_ok = client.post(f"{ROOT}/{wf['id']}/publish", headers={H: ws})
    assert publish_ok.status_code == 200
    ada = contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed" and run["steps"][0]["input"]["url"] == receiver.url("/hook")
    assert len(receiver.requests) == 1
    request = receiver.requests[0]
    assert request["path"] == "/hook" and verify_signature(wf["signing_secret"], request["headers"][
        "gohigh-signature"], request["body"])
    assert request["headers"]["gohigh-idempotency-key"] == f"{run['id']}:go"
    assert request["headers"]["gohigh-run-id"] == run["id"] and request["headers"]["gohigh-delivery-id"]
    body = json.loads(request["body"])
    assert body == {"workflow": {"id": wf["id"], "name": "Notify the CRM"}, "run": {"id": run["id"], "node_id": "go"},
                    "record": {"id": ada["id"], "object": "contact", "display_name": "Ada"},
                    "data": {"who": "Ada", "n": 3}}
    assert "ada@example.com" not in request["body"].decode()  # only what the config maps leaves the system
    delivery = detail(client, ws, run["id"])["deliveries"][0]
    assert delivery["status"] == "succeeded" and delivery["attempts"] == 1 and delivery["response_status"] == 200
    assert delivery["host"] == "127.0.0.1" and delivery["node_id"] == "go"
    assert not verify_signature("whsec_wrong", request["headers"]["gohigh-signature"], request["body"])


def test_a_webhook_that_fails_is_retried_with_the_same_key_while_the_run_goes_on(crm, db, receiver):
    client, ws, _ = crm
    live(client, ws, graph({"go": hook(receiver)}))
    receiver.replies = [(500, b"down", {}), (200, b"ok", {})]
    contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed"  # the outbox decouples the run from the receiver
    assert run["deliveries"][0]["status"] == "retrying" and run["deliveries"][0]["response_status"] == 500
    due_now(db)
    pump(db)
    again = detail(client, ws, run["id"])
    assert again["deliveries"][0]["status"] == "succeeded" and again["deliveries"][0]["attempts"] == 2
    keys = {r["headers"]["gohigh-idempotency-key"] for r in receiver.requests}
    assert len(receiver.requests) == 2 and keys == {f"{run['id']}:go"}  # the receiver can drop the repeat


def test_a_webhook_step_that_crashes_or_runs_again_queues_one_delivery(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    live(client, ws, graph({"go": hook(receiver)}))
    real, calls = engine.trace, []

    def dies_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise Crash
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "trace", dies_once)
    contact(client, ws)
    with pytest.raises(Crash):
        pump(db)
    assert sql(db, "SELECT count(*) FROM workflow_deliveries")[0][0] == 0 and receiver.requests == []
    db.execute(text("UPDATE jobs SET locked_at = now() - interval '20 minutes' WHERE status = 'running' "
                    "AND kind = 'workflow.step'"))
    db.commit()
    pump(db)
    run = only_run(client, ws)
    assert len(receiver.requests) == 1 and sql(db, "SELECT count(*) FROM workflow_deliveries")[0][0] == 1
    rewind(db, run["id"], "go")
    pump(db)
    again = only_run(client, ws)
    assert again["steps"][0]["output"]["already_queued"] is True and again["status"] == "completed"
    assert len(receiver.requests) == 1 and sql(db, "SELECT count(*) FROM workflow_deliveries")[0][0] == 1


def test_a_webhook_to_a_private_address_is_refused_when_saved_and_again_when_it_runs(crm, db, dns):
    client, ws, _ = crm
    for url in ("https://169.254.169.254/latest/meta-data", "http://hooks.example.com/x", "https://localhost/x",
                "https://user:pass@hooks.example.com/x", "ftp://hooks.example.com/x"):
        r = client.post(ROOT, json={"name": "Bad", "graph": graph({"go": act("webhook.send", {"url": url})})},
                        headers={H: ws})
        assert r.status_code == 422 and "graph.nodes.go.config.url" in r.json()["error"]["fields"], url
    live(client, ws, graph({"go": act("webhook.send", {"url": "https://hooks.example.com/ok"})}))
    dns["hooks.example.com"] = ["10.0.0.5"]  # the name now points inside: rebinding after the workflow was saved
    contact(client, ws)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "failed" and run["error"] == (
        "The URL is not allowed: hooks.example.com resolves to a non-public address")
    assert sql(db, "SELECT count(*) FROM workflow_deliveries")[0][0] == 0


def test_the_signing_secret_is_shown_once_and_rotating_it_changes_what_new_deliveries_are_signed_with(
        crm, db, receiver):
    client, ws, _ = crm
    wf = create(client, ws, graph({"go": hook(receiver)}))
    assert wf["signing_secret"].startswith("whsec_")
    assert "signing_secret" not in client.get(f"{ROOT}/{wf['id']}", headers={H: ws}).json()
    assert all("signing_secret" not in w for w in client.get(ROOT, headers={H: ws}).json()["data"])
    publish_ok = client.post(f"{ROOT}/{wf['id']}/publish", headers={H: ws})
    assert publish_ok.status_code == 200
    new = client.post(f"{ROOT}/{wf['id']}/rotate-secret", headers={H: ws}).json()["signing_secret"]
    assert new != wf["signing_secret"] and new.startswith("whsec_")
    contact(client, ws)
    pump(db)
    request = receiver.requests[0]
    assert verify_signature(new, request["headers"]["gohigh-signature"], request["body"])
    assert not verify_signature(wf["signing_secret"], request["headers"]["gohigh-signature"], request["body"])
    changed = sql(db, "SELECT data FROM events WHERE type = 'workflow.updated' ORDER BY id DESC")[0][0]
    assert changed["changes"] == {"signing_secret": {"rotated": True}} and new not in json.dumps(changed)


# --- notifications ----------------------------------------------------------------------------------------------

def test_notify_user_puts_a_notification_in_the_users_app_once_per_step(crm, db):
    client, ws, ids = crm
    ben_client = add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws)
    ben = user_id_of(ben_client)
    live(client, ws, graph({"go": act("notify.user", {"user_id": "owner", "title": "New lead: {{first_name}}",
                                                        "body": "Reach out to {{email}}"})}))
    ada = contact(client, ws, owner_id=ben)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed" and run["steps"][0]["output"] == {"notified": True}
    got = [n for n in ben_client.get("/api/v1/notifications", headers={H: ws}).json()["data"]
           if n["kind"] == "workflow"]
    assert len(got) == 1 and got[0]["title"] == "New lead: Ada" and got[0]["body"] == "Reach out to ada@example.com"
    assert got[0]["link"] == f"/contacts/{ada['id']}"
    rewind(db, run["id"], "go")  # run again over the same key: still one notification
    pump(db)
    assert sql(db, "SELECT count(*) FROM notifications WHERE kind = 'workflow'")[0][0] == 1


def test_notify_user_fails_without_an_owner_and_respects_a_person_who_turned_the_app_channel_off(crm, db):
    client, ws, ids = crm
    ben_client = add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws)
    ben = user_id_of(ben_client)
    live(client, ws, graph({"go": act("notify.user", {"user_id": "owner", "title": "Hello"})}))
    contact(client, ws)
    pump(db)
    assert only_run(client, ws)["error"] == "The record has no owner to notify"
    saved = ben_client.put("/api/v1/notifications/prefs", headers={H: ws},
                           json={"prefs": [{"kind": "workflow", "channels": []}]})
    assert saved.status_code == 200, saved.text
    contact(client, ws, first_name="Bob", email="bob@example.com", owner_id=ben)
    pump(db)
    assert sql(db, "SELECT count(*) FROM notifications WHERE kind = 'workflow'")[0][0] == 0
    assert sum(r["status"] == "completed" for r in runs(client, ws)) == 1  # the step did its part


def test_notify_user_fails_for_a_person_who_is_not_a_member(crm, db, make_user):
    client, ws, _ = crm
    stranger, ids = make_user("stranger@example.com")
    outsider = user_id_of(stranger)
    r = client.post(ROOT, json={"name": "x", "graph": graph({"go": act("notify.user", {"user_id": outsider,
                                                                                         "title": "Hi"})})},
                    headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {
        "graph.nodes.go.config.user_id": "is not a member of this workspace"}
    assert ids["workspace_id"] != ws
