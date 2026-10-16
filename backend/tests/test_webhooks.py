import json
import re
import time
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from helpers import H, add_member, drain, due_now, verify_signature, wait_for_quiet
from sqlalchemy import text

from app import config, jobs, webhooks
from app.db import SessionLocal
from app.events import emit
from app.jobs import run_one
from app.main import app

ROOT = "/api/v1/webhooks"
anonymous = TestClient(app)


def create(client, ws, url, **body) -> dict:
    r = client.post(ROOT, json={"url": url, **body}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def send_test(client, ws, endpoint_id) -> int:
    r = client.post(f"{ROOT}/{endpoint_id}/test", headers={H: ws})
    assert r.status_code == 202, r.text
    return r.json()["event_id"]


def log(client, ws, endpoint_id, **params) -> dict:
    r = client.get(f"{ROOT}/{endpoint_id}/deliveries", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def hook(make_user, receiver):
    """A signed-in admin, their workspace, and a webhook to the local receiver that only wants test events."""
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    return client, ws, create(client, ws, receiver.url(), event_types=["webhook.test"])


def test_the_secret_is_shown_once_and_stays_out_of_every_other_place(make_user, receiver, db):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = create(client, ws, receiver.url("/in"), event_types=["webhook.test", "user.signed_up"], filter={"a": 1})
    secret = made.pop("secret")
    assert re.fullmatch(r"whsec_[A-Za-z0-9_-]{43}", secret)
    assert made["url"] == receiver.url("/in") and made["event_types"] == ["webhook.test", "user.signed_up"]
    assert made["filter"] == {"a": 1} and made["active"] is True and made["disabled_reason"] is None
    send_test(client, ws, made["id"])
    drain()

    assert client.get(f"{ROOT}/{made['id']}", headers={H: ws}).json() == made
    assert client.get(ROOT, headers={H: ws}).json() == {"data": [made], "next_cursor": None}
    assert client.patch(f"{ROOT}/{made['id']}", json={"active": True}, headers={H: ws}).json() == made
    assert secret not in str(log(client, ws, made["id"]))
    for table in ("events", "jobs", "webhook_deliveries"):  # no copy of it in the log, the queue or the delivery log
        assert secret not in "".join(db.execute(text(f"SELECT t::text FROM {table} t")).scalars())
    assert db.scalar(text("SELECT secret FROM webhook_endpoints")) == secret  # it has to be kept to sign with
    created = db.scalar(text("SELECT data FROM events WHERE type = 'webhook_endpoint.created'"))
    assert created == {"id": made["id"], "event_types": made["event_types"], "filter": {"a": 1}, "active": True}
    assert receiver.url("/in") not in str(created)  # the URL may carry a token, and other endpoints see this event
    user_id = client.get("/api/me").json()["user"]["id"]
    assert str(db.scalar(text("SELECT created_by FROM webhook_endpoints"))) == user_id


def test_a_url_must_be_https_and_public_and_types_must_exist(make_user, receiver, monkeypatch):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    monkeypatch.setattr(config, "ALLOW_HTTP_WEBHOOKS", False)  # as in production
    for url, reason in [("http://hooks.example.com/x", "https"), ("https://10.0.0.1/x", "non-public address"),
                        ("https://169.254.169.254/latest/meta-data", "non-public address"),
                        ("https://[::1]/x", "non-public address"), ("https://hooks.test/x", "non-public address"),
                        ("https://user:pw@hooks.example.com/x", "credentials"), ("ftp://hooks.example.com", "https"),
                        ("https://nowhere.example.org/x", "does not resolve"), (receiver.url(), "https")]:
        r = client.post(ROOT, json={"url": url}, headers={H: ws})
        assert r.status_code == 422, url
        assert reason in r.json()["error"]["fields"]["url"] and r.json()["error"]["code"] == "validation_failed"
    for body, field in [({"url": "https://hooks.example.com", "event_types": ["nope.created"]}, "event_types.0"),
                        ({"url": "https://hooks.example.com", "event_types": []}, "event_types"),
                        ({"url": ""}, "url"), ({}, "url"), ({"url": "https://hooks.example.com/" + "x" * 2000}, "url")]:
        r = client.post(ROOT, json=body, headers={H: ws})
        assert r.status_code == 422 and field in r.json()["error"]["fields"], body
    assert client.get(ROOT, headers={H: ws}).json()["data"] == []
    ok = client.post(ROOT, json={"url": "https://hooks.example.com/ok"}, headers={H: ws})
    assert ok.status_code == 201 and ok.json()["event_types"] == ["*"]


def test_only_workspace_admins_manage_webhooks(make_user, receiver, db):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = create(client, ws, receiver.url())
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    org_admin = add_member(db, ids["org_id"], "ad@example.com", org_role="admin")
    mine = f"{ROOT}/{made['id']}"
    calls = [("GET", ROOT, None), ("POST", ROOT, {"url": receiver.url()}), ("GET", mine, None),
             ("PATCH", mine, {"active": False}), ("DELETE", mine, None), ("POST", f"{mine}/test", None),
             ("GET", f"{mine}/deliveries", None), ("POST", f"{ROOT}/deliveries/{uuid.uuid4()}/replay", None)]
    for method, path, body in calls:
        r = member.request(method, path, json=body, headers={H: ws})
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden", (method, path)
    assert member.get(ROOT).status_code == 400  # no workspace header
    stranger, other = make_user("b@example.com")
    for method, path, body in calls:
        assert stranger.request(method, path, json=body, headers={H: ws}).status_code == 404, (method, path)
        assert anonymous.request(method, path, json=body, headers={H: ws}).status_code == 401
    assert org_admin.get(ROOT, headers={H: ws}).json()["data"][0]["id"] == made["id"]  # org admins are admins
    assert client.get(mine, headers={H: ws}).json()["active"] is True  # nothing above changed it


def test_update_and_delete(make_user, receiver, db):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = create(client, ws, receiver.url())
    path = f"{ROOT}/{made['id']}"
    r = client.patch(path, json={"url": receiver.url("/moved"), "event_types": ["user.signed_up"], "filter": {"k": "v"},
                                 "active": False}, headers={H: ws})
    assert r.status_code == 200
    assert (r.json()["url"], r.json()["event_types"], r.json()["filter"], r.json()["active"]) == (
        receiver.url("/moved"), ["user.signed_up"], {"k": "v"}, False)
    assert client.patch(path, json={"url": "https://10.0.0.1/"}, headers={H: ws}).status_code == 422
    assert client.patch(path, json={"event_types": ["x.y"]}, headers={H: ws}).status_code == 422
    assert client.patch(path, json={}, headers={H: ws}).json()["url"] == receiver.url("/moved")
    assert client.get(path, headers={H: ws}).json()["event_types"] == ["user.signed_up"]
    assert client.patch(f"{ROOT}/{uuid.uuid4()}", json={}, headers={H: ws}).status_code == 404
    assert client.patch(f"{ROOT}/nonsense", json={}, headers={H: ws}).status_code == 422

    assert client.delete(path, headers={H: ws}).status_code == 204
    assert client.get(path, headers={H: ws}).status_code == 404
    assert client.delete(path, headers={H: ws}).status_code == 404
    assert db.scalar(text("SELECT count(*) FROM webhook_endpoints")) == 0


def test_a_test_event_arrives_signed_and_is_logged(hook, receiver, db):
    client, ws, made = hook
    event_id = send_test(client, ws, made["id"])
    assert drain() >= 2  # the dispatcher, then the delivery
    assert len(receiver.requests) == 1
    seen = receiver.requests[0]
    headers, body = seen["headers"], seen["body"]
    assert seen["path"] == "/hook"
    assert headers["content-type"] == "application/json" and headers["user-agent"].startswith("go-high-webhooks")
    assert headers["gohigh-event-id"] == str(event_id) and headers["gohigh-event-type"] == "webhook.test"
    assert re.fullmatch(r"t=\d{10},v1=[0-9a-f]{64}", headers["gohigh-signature"])
    assert verify_signature(made["secret"], headers["gohigh-signature"], body)
    assert not verify_signature(made["secret"], headers["gohigh-signature"], body + b" ")
    assert not verify_signature("whsec_wrong", headers["gohigh-signature"], body)
    assert not verify_signature(made["secret"], headers["gohigh-signature"], body, tolerance=-1)  # 5 minute window

    payload = json.loads(body)
    user_id = client.get("/api/me").json()["user"]["id"]
    assert payload["id"] == event_id and payload["type"] == "webhook.test" and payload["workspace_id"] == ws
    assert payload["subject"] == {"type": "webhook_endpoint", "id": made["id"]}
    assert payload["actor"] == {"type": "user", "id": user_id}
    assert payload["data"]["endpoint_id"] == made["id"] and datetime.fromisoformat(payload["occurred_at"])

    (delivery,) = log(client, ws, made["id"])["data"]
    assert (delivery["status"], delivery["attempts"], delivery["response_status"]) == ("succeeded", 1, 200)
    assert delivery["event_id"] == event_id and delivery["event_type"] == "webhook.test"
    assert delivery["response_body_excerpt"] == "ok" and delivery["error"] is None and delivery["replay_of"] is None
    assert isinstance(delivery["response_ms"], int) and delivery["next_attempt_at"] is None
    assert headers["gohigh-delivery-id"] == delivery["id"]


def test_the_default_subscription_gets_every_event_of_the_workspace(make_user, receiver):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = create(client, ws, receiver.url())
    send_test(client, ws, made["id"])
    drain()
    sent = sorted(r["headers"]["gohigh-event-type"] for r in receiver.requests)
    assert sent == ["webhook.test", "webhook_endpoint.created"]  # not the sign up events, which came before it


def test_fan_out_follows_subscriptions_filters_workspaces_and_time(make_user, receiver, db):
    a, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    b, other = make_user("b@example.com")
    everything = create(a, ws, receiver.url())["id"]
    signups = create(a, ws, receiver.url(), event_types=["user.signed_up"])["id"]
    workspaces = create(a, ws, receiver.url(), event_types=["workspace.created"])["id"]
    special = create(a, ws, receiver.url(), event_types=["workspace.created"], filter={"name": "Special"})["id"]
    off = create(a, ws, receiver.url())["id"]
    assert a.patch(f"{ROOT}/{off}", json={"active": False}, headers={H: ws}).status_code == 200
    foreign = create(b, other["workspace_id"], receiver.url())["id"]
    label = {everything: "everything", signups: "signups", workspaces: "workspaces", special: "special", off: "off",
             foreign: "foreign"}
    drain()  # the endpoint.created events of the lines above

    def workspace_created(s, name):
        data = {"id": str(uuid.uuid4()), "name": name, "org_id": ids["org_id"], "brand_id": ids["brand_id"]}
        return emit(s, "workspace.created", "workspace", uuid.UUID(data["id"]), data, workspace_id=ws).id

    with SessionLocal() as s:
        e_special, e_plain = workspace_created(s, "Special"), workspace_created(s, "Plain")
        e_signup = emit(s, "user.signed_up", "user", uuid.uuid4(), {
            "id": str(uuid.uuid4()), "email": "x@example.com", "name": "X", "org_id": ids["org_id"],
            "workspace_id": ws}, workspace_id=ws).id
        s.commit()
    late = create(a, ws, receiver.url(), event_types=["workspace.created"])["id"]  # born after those events
    label[late] = "late"
    drain()

    def who(event_id):
        rows = db.execute(text("SELECT endpoint_id FROM webhook_deliveries WHERE event_id = :e"), {"e": event_id})
        return sorted(label[str(r[0])] for r in rows)

    assert who(e_special) == sorted(["everything", "workspaces", "special"])
    assert who(e_plain) == sorted(["everything", "workspaces"])
    assert who(e_signup) == sorted(["everything", "signups"])

    test_event = send_test(a, ws, signups)  # a test event goes to the endpoint it names, whatever it subscribes to
    drain()
    assert who(test_event) == ["signups"]
    assert db.scalar(text("SELECT count(*) FROM webhook_deliveries d JOIN events e ON e.id = d.event_id "
                          "WHERE e.workspace_id <> d.workspace_id")) == 0


def test_failures_retry_with_the_queue_backoff_and_every_attempt_is_signed(hook, receiver, db):
    client, ws, made = hook
    receiver.replies = [(500, b"boom", {}), (503, b"busy", {"Retry-After": "5"})]
    event_id = send_test(client, ws, made["id"])
    drain()
    (delivery,) = log(client, ws, made["id"])["data"]
    assert (delivery["status"], delivery["attempts"], delivery["response_status"]) == ("retrying", 1, 500)
    assert delivery["response_body_excerpt"] == "boom" and delivery["error"] is None
    assert datetime.fromisoformat(delivery["next_attempt_at"]) > datetime.now().astimezone() + timedelta(seconds=5)
    assert drain() == 0  # waits for its backoff

    due_now(db)
    drain()
    delivery = log(client, ws, made["id"])["data"][0]
    assert (delivery["status"], delivery["attempts"], delivery["response_status"]) == ("retrying", 2, 503)
    due_now(db)
    drain()
    delivery = log(client, ws, made["id"])["data"][0]
    assert (delivery["status"], delivery["attempts"], delivery["response_status"]) == ("succeeded", 3, 200)
    assert delivery["next_attempt_at"] is None
    assert len(receiver.requests) == 3
    assert {r["headers"]["gohigh-event-id"] for r in receiver.requests} == {str(event_id)}
    assert all(verify_signature(made["secret"], r["headers"]["gohigh-signature"], r["body"]) for r in receiver.requests)
    assert db.execute(text("SELECT status, attempts FROM jobs WHERE kind = 'webhook.deliver'")).one() == ("done", 3)


def test_a_delivery_gives_up_after_twelve_attempts(hook, receiver, db):
    client, ws, made = hook
    receiver.default = (500, b"down", {})
    send_test(client, ws, made["id"])
    for _ in range(webhooks.MAX_ATTEMPTS):
        drain()
        due_now(db)
    assert drain() == 0
    (delivery,) = log(client, ws, made["id"])["data"]
    assert (delivery["status"], delivery["attempts"], delivery["next_attempt_at"]) == ("failed", 12, None)
    assert len(receiver.requests) == 12
    assert db.execute(text("SELECT status, attempts FROM jobs WHERE kind = 'webhook.deliver'")).one() == ("done", 12)
    assert db.scalar(text("SELECT count(*) FROM jobs WHERE status = 'queued'")) == 0
    assert client.get(f"{ROOT}/{made['id']}", headers={H: ws}).json()["active"] is True  # not three days yet


def test_three_days_of_only_failures_disable_the_endpoint(hook, receiver, db):
    client, ws, made = hook
    receiver.default = (500, b"down", {})
    db.execute(text("UPDATE webhook_endpoints SET failing_since = now() - interval '2 days 23 hours'"))
    db.commit()
    send_test(client, ws, made["id"])
    drain()
    assert client.get(f"{ROOT}/{made['id']}", headers={H: ws}).json()["active"] is True
    assert log(client, ws, made["id"])["data"][0]["status"] == "retrying"

    db.execute(text("UPDATE webhook_endpoints SET failing_since = now() - interval '3 days 1 minute'"))
    db.commit()
    send_test(client, ws, made["id"])
    wait_for_quiet()
    assert run_one(SessionLocal)  # the dispatcher creates a second delivery, which is in flight when one tips it over
    due_now(db)
    drain()
    shown = client.get(f"{ROOT}/{made['id']}", headers={H: ws}).json()
    assert shown["active"] is False and shown["disabled_reason"].startswith("Disabled automatically")
    statuses = [(d["status"], d["error"]) for d in log(client, ws, made["id"])["data"]]
    assert ("failed", None) in statuses and ("failed", "webhook is disabled") in statuses
    sent = len(receiver.requests)
    r = client.post(f"{ROOT}/{made['id']}/test", headers={H: ws})
    assert r.status_code == 409 and r.json()["error"]["code"] == "endpoint_disabled"
    drain()
    assert len(receiver.requests) == sent  # nothing more goes out

    r = client.patch(f"{ROOT}/{made['id']}", json={"active": True}, headers={H: ws}).json()
    assert r["active"] is True and r["disabled_reason"] is None
    assert db.scalar(text("SELECT failing_since FROM webhook_endpoints")) is None


def test_a_success_clears_the_failure_streak(hook, receiver, db):
    client, ws, made = hook
    db.execute(text("UPDATE webhook_endpoints SET failing_since = now() - interval '1 day'"))
    db.commit()
    send_test(client, ws, made["id"])
    drain()
    assert db.scalar(text("SELECT failing_since FROM webhook_endpoints")) is None


def test_replay_sends_the_same_event_again_as_a_new_delivery(hook, receiver, make_user):
    client, ws, made = hook
    event_id = send_test(client, ws, made["id"])
    drain()
    (first,) = log(client, ws, made["id"])["data"]
    r = client.post(f"{ROOT}/deliveries/{first['id']}/replay", headers={H: ws})
    assert r.status_code == 202
    again = r.json()
    assert again["id"] != first["id"] and again["replay_of"] == first["id"] and again["event_id"] == event_id
    assert (again["status"], again["attempts"], again["event_type"]) == ("pending", 0, "webhook.test")
    drain()
    assert len(receiver.requests) == 2
    one, two = (r["headers"] for r in receiver.requests)
    assert one["gohigh-event-id"] == two["gohigh-event-id"] == str(event_id)  # receivers can dedupe on this
    assert one["gohigh-delivery-id"] != two["gohigh-delivery-id"]
    assert json.loads(receiver.requests[0]["body"])["id"] == json.loads(receiver.requests[1]["body"])["id"]
    assert [d["status"] for d in log(client, ws, made["id"])["data"]] == ["succeeded", "succeeded"]

    stranger, other = make_user("b@example.com")
    foreign = stranger.post(f"{ROOT}/deliveries/{first['id']}/replay", headers={H: other["workspace_id"]})
    assert foreign.status_code == 404
    assert client.post(f"{ROOT}/deliveries/{uuid.uuid4()}/replay", headers={H: ws}).status_code == 404
    client.patch(f"{ROOT}/{made['id']}", json={"active": False}, headers={H: ws})
    r = client.post(f"{ROOT}/deliveries/{first['id']}/replay", headers={H: ws})
    assert r.status_code == 409 and r.json()["error"]["code"] == "endpoint_disabled"


def test_a_failed_delivery_can_be_replayed_once_the_receiver_is_fixed(hook, receiver, db):
    client, ws, made = hook
    receiver.default = (500, b"down", {})
    send_test(client, ws, made["id"])
    for _ in range(webhooks.MAX_ATTEMPTS):
        drain()
        due_now(db)
    (failed,) = log(client, ws, made["id"])["data"]
    assert failed["status"] == "failed"
    receiver.default = (200, b"fixed", {})
    assert client.post(f"{ROOT}/deliveries/{failed['id']}/replay", headers={H: ws}).status_code == 202
    drain()
    assert [d["status"] for d in log(client, ws, made["id"], status="succeeded")["data"]] == ["succeeded"]
    assert receiver.requests[-1]["headers"]["gohigh-event-id"] == receiver.requests[0]["headers"]["gohigh-event-id"]


def test_the_delivery_log_pages_newest_first_and_filters_by_status(hook, receiver, db):
    client, ws, made = hook
    for _ in range(5):
        send_test(client, ws, made["id"])
        drain()  # one transaction each, so they differ in time
    ids = [d["id"] for d in log(client, ws, made["id"])["data"]]
    assert len(ids) == 5
    db.execute(text("UPDATE webhook_deliveries SET status = 'failed' WHERE id = ANY(:i)"),
               {"i": [uuid.UUID(i) for i in ids[:2]]})
    db.execute(text("UPDATE webhook_deliveries SET status = 'retrying' WHERE id = :i"), {"i": uuid.UUID(ids[2])})
    db.commit()

    seen, cursor, pages = [], None, 0
    while True:
        page = log(client, ws, made["id"], limit=2, **({"cursor": cursor} if cursor else {}))
        seen += [d["id"] for d in page["data"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == ids and pages == 3  # nothing twice, nothing missed
    created = [d["created_at"] for d in log(client, ws, made["id"])["data"]]
    assert created == sorted(created, reverse=True)
    assert [d["id"] for d in log(client, ws, made["id"], status="failed")["data"]] == ids[:2]
    assert [d["id"] for d in log(client, ws, made["id"], status="retrying")["data"]] == [ids[2]]
    assert len(log(client, ws, made["id"], status="succeeded")["data"]) == 2
    assert log(client, ws, made["id"], status="pending")["data"] == []
    filtered = log(client, ws, made["id"], status="failed", limit=1)
    assert len(filtered["data"]) == 1 and filtered["next_cursor"]
    assert log(client, ws, made["id"], status="failed", limit=1, cursor=filtered["next_cursor"])["next_cursor"] is None

    bad = client.get(f"{ROOT}/{made['id']}/deliveries", params={"status": "done"}, headers={H: ws})
    assert bad.status_code == 422 and "status" in bad.json()["error"]["fields"]
    payload, signature = filtered["next_cursor"].rsplit(".", 1)
    edited = f"{payload}.{'1' if signature[0] == '0' else '0'}{signature[1:]}"
    for cursor in ("junk", edited, "a.b", payload):
        r = client.get(f"{ROOT}/{made['id']}/deliveries", params={"cursor": cursor}, headers={H: ws})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor", cursor


def test_the_excerpt_keeps_two_kilobytes_without_nul_bytes(hook, receiver):
    client, ws, made = hook
    receiver.default = (200, b"ok\x00" + b"\xff" * 5000, {})
    send_test(client, ws, made["id"])
    drain()
    excerpt = log(client, ws, made["id"])["data"][0]["response_body_excerpt"]
    assert excerpt.startswith("ok�") and "\x00" not in excerpt and len(excerpt) == 2047


def test_redirects_are_not_followed(hook, receiver):
    client, ws, made = hook
    receiver.default = (302, b"", {"Location": receiver.url("/elsewhere")})
    send_test(client, ws, made["id"])
    drain()
    (delivery,) = log(client, ws, made["id"])["data"]
    assert (delivery["status"], delivery["response_status"]) == ("retrying", 302)
    assert [r["path"] for r in receiver.requests] == ["/hook"]


def test_a_receiver_that_hangs_is_cut_off_and_the_delivery_retried(hook, receiver, monkeypatch):
    client, ws, made = hook
    monkeypatch.setattr(webhooks, "TIMEOUT", 0.5)
    receiver.delay = 3
    send_test(client, ws, made["id"])
    started = time.monotonic()
    drain()
    assert time.monotonic() - started < 3
    (delivery,) = log(client, ws, made["id"])["data"]
    assert (delivery["status"], delivery["response_status"], delivery["error"]) == (
        "retrying", None, "timed out after 0.5 s")
    assert delivery["response_ms"] >= 450


def test_a_name_that_starts_pointing_inside_after_saving_is_refused_when_sending(make_user, dns):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    dns["rebind.test"] = ["93.184.216.34"]
    made = create(client, ws, "https://rebind.test/hook", event_types=["webhook.test"])  # public when saved
    dns["rebind.test"] = ["10.0.0.5"]
    send_test(client, ws, made["id"])
    drain()
    (delivery,) = log(client, ws, made["id"])["data"]
    assert delivery["status"] == "retrying" and delivery["response_status"] is None
    assert delivery["error"] == "rebind.test resolves to a non-public address"


def test_a_delivery_never_sends_another_workspaces_event(make_user, receiver, db):
    a, ids = make_user("a@example.com")
    b, other = make_user("b@example.com")
    made = create(a, ids["workspace_id"], receiver.url(), event_types=["webhook.test"])
    foreign_event = db.scalar(text("SELECT id FROM events WHERE workspace_id = :w LIMIT 1"),
                              {"w": other["workspace_id"]})
    delivery = db.scalar(text("INSERT INTO webhook_deliveries (workspace_id, endpoint_id, event_id) "
                              "VALUES (:w, :e, :ev) RETURNING id"),
                         {"w": ids["workspace_id"], "e": made["id"], "ev": foreign_event})
    jobs.enqueue(db, "webhook.deliver", {"delivery_id": str(delivery)})
    db.commit()
    drain()
    assert receiver.requests == []
    assert log(a, ids["workspace_id"], made["id"])["data"][0]["error"] == "event not found"
    assert log(a, ids["workspace_id"], made["id"])["data"][0]["status"] == "failed"


def test_deleting_an_endpoint_drops_its_pending_deliveries(hook, receiver, db):
    client, ws, made = hook
    send_test(client, ws, made["id"])
    wait_for_quiet()
    assert run_one(SessionLocal)  # the dispatcher: creates the delivery and its job, but nothing is sent yet
    assert db.scalar(text("SELECT count(*) FROM webhook_deliveries")) == 1
    assert client.delete(f"{ROOT}/{made['id']}", headers={H: ws}).status_code == 204
    assert db.scalar(text("SELECT count(*) FROM webhook_deliveries")) == 0
    drain()  # the delivery job finds nothing to do
    assert receiver.requests == []
    assert db.scalar(text("SELECT count(*) FROM jobs WHERE status IN ('queued', 'dead')")) == 0


def test_delivery_retries_span_about_a_day():
    from app.webhooks import MAX_ATTEMPTS, retry_delay
    total = sum((retry_delay(n) for n in range(1, MAX_ATTEMPTS)), timedelta())
    assert retry_delay(1) == timedelta(minutes=1)
    assert timedelta(hours=18) < total < timedelta(hours=30)
