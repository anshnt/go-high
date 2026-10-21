"""The ledger behind every send (module 06 "done when"): a send shows its cost first, is charged when it is queued,
given back when the provider refuses it for good, and refused when the wallet is empty or the monthly cap is reached:
in the inbox composer, for the automatic answer to a STOP, and in workflow steps."""
from fastapi.testclient import TestClient
from helpers import H, drain, due_now, make_record
from inbox_helpers import add_channel, point, sms_in
from sqlalchemy import text
from usage_helpers import CENT, USD, balance, card, consistent, events_of, fund, ledger, settle
from workflow_helpers import ROOT, act, create, graph, live, only_run, pump

from app.main import app

anonymous = TestClient(app)
ALICE = "+14155550123"
SENT = '{"sid": "SMsent%d"}'
SEGMENT = 7_900  # the carrier's 0.79 cents


def priced_channel(client, ws) -> dict:
    return add_channel(client, ws, config={"account_sid": "AC" + "a" * 32, "segment_cost": "0.0079"})


def conversation(client, ws) -> tuple[dict, dict]:
    contact = make_record(client, ws, first_name="Alice", phone=ALICE)
    r = client.post("/api/v1/conversations", json={"contact_id": contact["id"]}, headers={H: ws})
    return contact, r.json()


def reply(client, ws, conv, channel, body="hello"):
    return client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": body,
                                                                             "channel_id": channel["id"]},
                       headers={H: ws})


def test_the_composer_sees_the_charge_and_a_reply_is_charged_once_when_queued(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = priced_channel(client, ws)
    card(client, ws, markup_bp=2_500)  # the agency's 25 %
    fund(client, ws, USD)
    point(monkeypatch, receiver, "twilio", SENT)
    _, conv = conversation(client, ws)
    est = client.post(f"/api/v1/channels/{channel['id']}/estimate", json={"body": "x" * 200}, headers={H: ws}).json()
    assert (est["segments"], est["estimated_cost"]) == (2, "0.015800")
    assert est["charge"] == {"currency": "USD", "price": 19_750, "balance": USD, "balance_after": USD - 19_750,
                             "allowed": True, "code": None, "reason": None, "warnings": []}
    sent = reply(client, ws, conv, channel, "x" * 200)
    assert sent.status_code == 201, sent.text
    [_, usage] = ledger(db, ws)
    assert (usage["kind"], usage["meter"], usage["quantity"], usage["cost"], usage["price"], usage["source"]) == (
        "usage", "sms.segment", 2, 15_800, 19_750, "inbox")
    assert (str(usage["subject_id"]), usage["idempotency_key"]) == (sent.json()["id"], f"message:{sent.json()['id']}")
    drain()
    due_now(db)
    drain()  # the send job ran (and a second run of it changes nothing)
    assert len(ledger(db, ws)) == 2 and balance(db, ws) == USD - 19_750
    assert [d["price"] for _, d in events_of(db, ws, "usage.recorded")] == [19_750]


def test_an_empty_wallet_refuses_a_paid_reply_and_keeps_nothing(crm, db):
    client, ws, _ = crm
    channel = priced_channel(client, ws)
    _, conv = conversation(client, ws)
    est = client.post(f"/api/v1/channels/{channel['id']}/estimate", json={"body": "hi"}, headers={H: ws}).json()
    assert (est["charge"]["allowed"], est["charge"]["code"]) == (False, "wallet_empty")
    r = reply(client, ws, conv, channel)
    assert r.status_code == 422, r.text
    error = r.json()["error"]
    assert error["code"] == "wallet_empty" and "$0.0079" in error["message"] and "Top up" in error["message"]
    db.rollback()
    assert db.scalar(text("SELECT count(*) FROM messages")) == 0 and ledger(db, ws) == []
    assert db.scalar(text("SELECT count(*) FROM jobs WHERE kind = 'message.send'")) == 0
    note = client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "a note", "kind": "note"},
                       headers={H: ws})
    assert note.status_code == 201  # notes are free
    settle(client, ws, mode="postpaid")
    assert reply(client, ws, conv, channel).status_code == 201  # postpaid: it goes, and the balance goes negative
    assert balance(db, ws) == -SEGMENT


def test_a_free_channel_sends_from_an_empty_wallet_and_still_records_usage(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)  # no carrier rate, no platform cost: nothing to pay
    _, conv = conversation(client, ws)
    assert reply(client, ws, conv, channel).status_code == 201
    [usage] = ledger(db, ws)
    assert (usage["quantity"], usage["price"], usage["amount"]) == (1, 0, 0)


def test_the_monthly_cap_stops_sends_when_reached(crm, db):
    client, ws, _ = crm
    channel = priced_channel(client, ws)
    fund(client, ws, 10 * USD)
    settle(client, ws, monthly_cap=2 * CENT)  # two one-segment texts at 0.79 cents fit, a third does not
    _, conv = conversation(client, ws)
    assert reply(client, ws, conv, channel).status_code == 201
    assert reply(client, ws, conv, channel).status_code == 201
    third = reply(client, ws, conv, channel)
    assert third.status_code == 422 and third.json()["error"]["code"] == "usage_cap"
    assert len([e for e in ledger(db, ws) if e["kind"] == "usage"]) == 2


def test_a_message_the_provider_refuses_for_good_is_given_back(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = priced_channel(client, ws)
    fund(client, ws, USD)
    point(monkeypatch, receiver, "twilio")
    receiver.replies = [(400, b'{"code": 21211, "message": "Invalid To number"}', {})]
    _, conv = conversation(client, ws)
    reply(client, ws, conv, channel)
    drain()
    kinds = [(e["kind"], e["amount"]) for e in ledger(db, ws)]
    assert kinds == [("adjustment", USD), ("usage", -SEGMENT), ("reversal", SEGMENT)]
    assert balance(db, ws) == USD
    [(_, back)] = events_of(db, ws, "usage.reversed")
    assert "Invalid To number" in back["reason"]
    consistent(db, ws)


def test_the_answer_to_stop_is_charged_but_never_blocked(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = priced_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    assert sms_in(anonymous, channel, ALICE, "STOP").status_code == 200
    [usage] = ledger(db, ws)
    assert (usage["kind"], usage["price"], usage["balance_after"]) == ("usage", SEGMENT, -SEGMENT)
    drain()
    assert len(receiver.requests) == 1  # it went out


def send_step(channel, **more) -> dict:
    return act("message.send", {"channel_id": channel["id"], "body": "Hi {{first_name}}", **more})


def test_a_workflow_send_is_charged_or_fails_its_step_with_the_reason(crm, db, receiver, monkeypatch):
    client, ws, _ = crm
    channel = priced_channel(client, ws)
    point(monkeypatch, receiver, "twilio", SENT)
    live(client, ws, graph({"go": send_step(channel)}))
    make_record(client, ws, first_name="Ada", phone=ALICE)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "failed" and "does not cover this" in run["error"]
    db.rollback()
    assert db.scalar(text("SELECT count(*) FROM messages WHERE kind = 'message'")) == 0 and ledger(db, ws) == []
    fund(client, ws, USD)
    r = client.post(f"{ROOT}/runs/{run['id']}/retry", headers={H: ws})
    assert r.status_code == 200, r.text
    pump(db)
    assert only_run(client, ws)["status"] == "completed"
    usage = [e for e in ledger(db, ws) if e["kind"] == "usage"]
    assert [(e["source"], e["price"], e["actor_type"]) for e in usage] == [("workflow", SEGMENT, "workflow")]


def test_a_workflow_can_skip_a_send_the_wallet_refuses(crm, db):
    client, ws, _ = crm
    channel = priced_channel(client, ws)
    skip = {"channel_id": channel["id"], "body": "Hi", "if_refused": "skip"}
    client.post("/api/v1/tags", json={"name": "nudged"}, headers={H: ws})
    live(client, ws, graph({"go": act("message.send", skip, "tag"),
                            "tag": act("tag.add", {"tag": "nudged"})}))
    make_record(client, ws, first_name="Ada", phone=ALICE)
    pump(db)
    run = only_run(client, ws)
    assert run["status"] == "completed"
    assert run["steps"][0]["output"]["code"] == "wallet_empty"


def test_a_workflow_test_run_shows_the_cost_and_whether_it_would_go(crm, db):
    client, ws, _ = crm
    channel = priced_channel(client, ws)
    wf = create(client, ws, graph({"go": send_step(channel)}))
    ada = make_record(client, ws, first_name="Ada", phone=ALICE)
    out = client.post(f"{ROOT}/{wf['id']}/test", json={"record_id": ada["id"]}, headers={H: ws}).json()
    step = out["steps"][0]["output"]
    assert (step["would_send"], step["price"], step["currency"], step["allowed"]) == (True, SEGMENT, "USD", False)
    assert "does not cover" in step["refused"]
    assert ledger(db, ws) == []  # a test run charges nothing
