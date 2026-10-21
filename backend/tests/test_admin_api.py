"""What the admin screens need beyond the module APIs: the capability and event type catalogs, a webhook's secret
revealed and rotated, the delivery log filtered by event type and date, one delivery with its payload, and the fields
of an object put in a new order."""
import json
import uuid
from datetime import UTC, datetime, timedelta

from helpers import H, add_member, audit, drain, make_record, make_role, rule, verify_signature
from sqlalchemy import text

from app import events
from app.models import SCOPES
from app.permissions import CATALOG

WEBHOOKS = "/api/v1/webhooks"


def hook(client, ws, url, **body) -> dict:
    r = client.post(WEBHOOKS, json={"url": url, **body}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def deliveries(client, ws, endpoint_id, **params) -> list[dict]:
    r = client.get(f"{WEBHOOKS}/{endpoint_id}/deliveries", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_the_capability_catalog_lists_every_capability_by_module_and_the_scopes(crm, db):
    client, ws, ids = crm
    r = client.get("/api/v1/permissions/catalog", headers={H: ws})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(c["module"], c["capability"], c["description"]) for c in body["capabilities"]] == list(CATALOG)
    assert body["scopes"] == list(SCOPES)
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    assert viewer.get("/api/v1/permissions/catalog", headers={H: ws}).status_code == 200  # members.read is enough


def test_both_event_type_catalogs_list_every_registered_type(crm, db):
    client, ws, ids = crm
    for path in (f"{WEBHOOKS}/event-types", "/api/v1/audit/event-types"):
        r = client.get(path, headers={H: ws})
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert [t["type"] for t in data] == sorted(events.TYPES) and "webhook.test" in {t["type"] for t in data}
        test = next(t for t in data if t["type"] == "webhook.test")
        assert test["description"].startswith("A test event") and test["schema"]["required"] == ["endpoint_id",
                                                                                                    "message"]
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    for path, capability in ((f"{WEBHOOKS}/event-types", "webhooks.manage"), ("/api/v1/audit/event-types",
                                                                              "audit.read")):
        r = member.get(path, headers={H: ws})
        assert r.status_code == 403 and capability in r.json()["error"]["message"]


def test_the_secret_can_be_revealed_and_rotated_and_both_are_audited(make_user, receiver, db):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = hook(client, ws, receiver.url(), event_types=["webhook.test"])
    first = made["secret"]

    r = client.post(f"{WEBHOOKS}/{made['id']}/reveal-secret", headers={H: ws})
    assert r.status_code == 200 and r.json() == {"secret": first}

    r = client.post(f"{WEBHOOKS}/{made['id']}/rotate-secret", headers={H: ws})
    assert r.status_code == 200, r.text
    rotated = r.json()
    second = rotated.pop("secret")
    assert second != first and second.startswith("whsec_")
    assert rotated == client.get(f"{WEBHOOKS}/{made['id']}", headers={H: ws}).json()
    assert client.post(f"{WEBHOOKS}/{made['id']}/reveal-secret", headers={H: ws}).json() == {"secret": second}

    # deliveries are signed with the new secret, and the old one no longer verifies
    assert client.post(f"{WEBHOOKS}/{made['id']}/test", headers={H: ws}).status_code == 202
    drain()
    sent = receiver.requests[-1]
    assert verify_signature(second, sent["headers"]["gohigh-signature"], sent["body"])
    assert not verify_signature(first, sent["headers"]["gohigh-signature"], sent["body"])

    logged = audit(client, ws, type="webhook_endpoint.*")
    assert [e["type"] for e in logged if e["type"] != "webhook_endpoint.created"] == [
        "webhook_endpoint.secret_revealed", "webhook_endpoint.secret_rotated", "webhook_endpoint.secret_revealed"]
    assert first not in json.dumps(logged) and second not in json.dumps(logged)
    assert all(e["data"] == {"id": made["id"]} for e in logged if "secret" in e["type"])


def test_revealing_and_rotating_need_a_proved_address_and_the_capability(make_user, receiver, db):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = hook(client, ws, receiver.url())
    db.execute(text("UPDATE users SET email_verified_at = NULL WHERE email = 'a@example.com'"))
    db.commit()
    for action in ("reveal-secret", "rotate-secret"):
        r = client.post(f"{WEBHOOKS}/{made['id']}/{action}", headers={H: ws})
        assert r.status_code == 403 and r.json()["error"]["code"] == "email_unverified", r.text
    db.execute(text("UPDATE users SET email_verified_at = now() WHERE email = 'a@example.com'"))
    db.commit()
    for action in ("reveal-secret", "rotate-secret"):
        assert client.post(f"{WEBHOOKS}/{uuid.uuid4()}/{action}", headers={H: ws}).status_code == 404
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    assert member.post(f"{WEBHOOKS}/{made['id']}/reveal-secret", headers={H: ws}).status_code == 403
    other, other_ids = make_user("b@example.com")
    r = other.post(f"{WEBHOOKS}/{made['id']}/reveal-secret", headers={H: other_ids["workspace_id"]})
    assert r.status_code == 404  # another workspace's endpoint does not exist for them


def test_the_delivery_log_filters_by_event_type_and_date(make_user, receiver):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = hook(client, ws, receiver.url())  # every event
    make_record(client, ws, first_name="Ada")
    client.post("/api/v1/tags", json={"name": "vip"}, headers={H: ws})
    client.post(f"{WEBHOOKS}/{made['id']}/test", headers={H: ws})
    drain()

    every = deliveries(client, ws, made["id"])
    assert {d["event_type"] for d in every} >= {"record.created", "tag.created", "webhook.test"}
    assert [d["event_type"] for d in deliveries(client, ws, made["id"], type="record.created")] == ["record.created"]
    assert {d["event_type"] for d in deliveries(client, ws, made["id"], type="tag.*")} == {"tag.created"}
    assert deliveries(client, ws, made["id"], type="workspace.created") == []
    assert len(deliveries(client, ws, made["id"], type="webhook.test", status="succeeded")) == 1

    now = datetime.now(UTC)
    assert len(deliveries(client, ws, made["id"], **{"from": (now - timedelta(hours=1)).isoformat()})) == len(every)
    assert deliveries(client, ws, made["id"], **{"from": (now + timedelta(hours=1)).isoformat()}) == []
    assert deliveries(client, ws, made["id"], to=(now - timedelta(hours=1)).isoformat()) == []
    naive = (now + timedelta(hours=1)).replace(tzinfo=None).isoformat()  # read as UTC
    assert len(deliveries(client, ws, made["id"], to=naive)) == len(every)

    for bad in ({"type": "Record"}, {"type": "record.*.x"}, {"from": "yesterday"}):
        r = client.get(f"{WEBHOOKS}/{made['id']}/deliveries", params=bad, headers={H: ws})
        assert r.status_code == 422, bad


def test_one_delivery_shows_the_payload_and_headers_it_sends(make_user, receiver, db):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = hook(client, ws, receiver.url(), event_types=["webhook.test"])
    client.post(f"{WEBHOOKS}/{made['id']}/test", headers={H: ws})
    drain()
    listed = deliveries(client, ws, made["id"])[0]
    r = client.get(f"{WEBHOOKS}/deliveries/{listed['id']}", headers={H: ws})
    assert r.status_code == 200, r.text
    one = r.json()
    assert {k: v for k, v in one.items() if k not in ("payload", "request_headers")} == listed
    sent = receiver.requests[-1]
    assert one["payload"] == json.loads(sent["body"])  # exactly what went out
    assert one["payload"]["type"] == "webhook.test" and one["payload"]["data"]["endpoint_id"] == made["id"]
    headers = one["request_headers"]
    assert headers["GoHigh-Event-Id"] == sent["headers"]["gohigh-event-id"]
    assert headers["GoHigh-Delivery-Id"] == listed["id"] and headers["GoHigh-Event-Type"] == "webhook.test"
    assert headers["GoHigh-Signature"].startswith("t=<") and made["secret"] not in json.dumps(one)

    assert client.get(f"{WEBHOOKS}/deliveries/{uuid.uuid4()}", headers={H: ws}).status_code == 404
    other, other_ids = make_user("b@example.com")
    assert other.get(f"{WEBHOOKS}/deliveries/{listed['id']}", headers={H: other_ids["workspace_id"]}).status_code == 404
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    assert member.get(f"{WEBHOOKS}/deliveries/{listed['id']}", headers={H: ws}).status_code == 403


def test_an_endpoint_says_since_when_it_fails(make_user, receiver):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = hook(client, ws, receiver.url(), event_types=["webhook.test"])
    assert made["failing_since"] is None
    receiver.default = (500, b"down", {})
    client.post(f"{WEBHOOKS}/{made['id']}/test", headers={H: ws})
    drain()
    assert client.get(f"{WEBHOOKS}/{made['id']}", headers={H: ws}).json()["failing_since"] is not None


def fields_of(client, ws, key="contact") -> list[str]:
    return [f["key"] for f in client.get(f"/api/v1/objects/{key}/fields", headers={H: ws}).json()["data"]]


def test_fields_are_put_in_a_new_order_in_one_call(crm):
    client, ws, _ = crm
    before = fields_of(client, ws)
    order = [before[-1], *before[:-1]]
    r = client.post("/api/v1/objects/contact/fields/reorder", json={"keys": order}, headers={H: ws})
    assert r.status_code == 200, r.text
    assert [f["key"] for f in r.json()["data"]] == order == fields_of(client, ws)
    moved = [e for e in audit(client, ws, type="field.updated")]
    assert moved and all(set(e["data"]["changes"]) == {"position"} for e in moved)
    assert len(moved) == len(before)  # the last field went first, so every field moved

    count = len(audit(client, ws, type="field.updated"))
    assert client.post("/api/v1/objects/contact/fields/reorder", json={"keys": order},
                       headers={H: ws}).status_code == 200
    assert len(audit(client, ws, type="field.updated")) == count  # the same order changes nothing

    for bad in ([*order, order[0]], order[1:], [*order[:-1], "nope"]):
        r = client.post("/api/v1/objects/contact/fields/reorder", json={"keys": bad}, headers={H: ws})
        assert r.status_code == 422 and "keys" in r.json()["error"]["fields"], bad
    assert fields_of(client, ws) == order
    assert client.post("/api/v1/objects/nope/fields/reorder", json={"keys": ["a"]},
                       headers={H: ws}).status_code == 404


def test_reordering_fields_needs_fields_manage_and_leaves_hidden_fields_in_place(crm, db):
    client, ws, ids = crm
    role = make_role(client, ws, "Fielder", copy_from="manager",
                     rules=[rule("contact", hidden=["phone"]), rule()])
    r = client.patch(f"/api/v1/roles/{role['id']}", json={"capabilities": [*role["capabilities"], "fields.manage"]},
                     headers={H: ws})
    assert r.status_code == 200, r.text
    fielder = add_member(db, ids["org_id"], "f@example.com", workspace_id=ws)
    assert client.put(f"/api/v1/members/{fielder.get('/api/me').json()['user']['id']}", json={"role_id": role["id"]},
                      headers={H: ws}).status_code == 200
    everything = fields_of(client, ws)
    seen = fields_of(fielder, ws)
    assert "phone" in everything and "phone" not in seen
    r = fielder.post("/api/v1/objects/contact/fields/reorder", json={"keys": everything}, headers={H: ws})
    assert r.status_code == 422  # names a field the role does not have
    reversed_seen = list(reversed(seen))
    assert fielder.post("/api/v1/objects/contact/fields/reorder", json={"keys": reversed_seen},
                        headers={H: ws}).status_code == 200
    after = fields_of(client, ws)
    assert [k for k in after if k != "phone"] == reversed_seen
    assert after.index("phone") == everything.index("phone")  # it kept its slot

    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    r = viewer.post("/api/v1/objects/contact/fields/reorder", json={"keys": after}, headers={H: ws})
    assert r.status_code == 403 and "fields.manage" in r.json()["error"]["message"]
