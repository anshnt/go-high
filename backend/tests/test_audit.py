"""The audit log (ADR 0004): an event for every configuration and security write, `GET /api/v1/audit` with its filters
and cursor, the CSV export that records itself, and an event log that request handlers can only add to."""
import csv
import io
import json

import pytest
from fastapi.testclient import TestClient
from helpers import (
    PASSWORD,
    H,
    add_member,
    audit,
    context,
    link,
    make_record,
    make_role,
    role_id,
    type_id,
    user_id_of,
    v1_routes,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import audit as audit_module
from app.db import engine
from app.main import app

AUDIT = "/api/v1/audit"


def of(rows, type_):
    return [r for r in rows if r["type"] == type_]


def only(rows, type_):
    found = of(rows, type_)
    assert len(found) == 1, (type_, [r["type"] for r in rows])
    return found[0]


def test_every_configuration_write_is_an_event_with_who_and_what_changed(crm):
    client, ws, _ = crm
    me = user_id_of(client)
    h = {H: ws}

    def call(method, path, status, **kw):
        r = client.request(method, path, headers=h, **kw)
        assert r.status_code == status, (method, path, r.text)
        return r.json() if r.content else None

    obj = call("POST", "/api/v1/objects", 201, json={"key": "asset", "singular": "Asset", "plural": "Assets"})
    call("PATCH", "/api/v1/objects/asset", 200, json={"singular": "Asset!", "icon": "box"})
    call("PATCH", "/api/v1/objects/asset", 200, json={"singular": "Asset!"})  # nothing changed: nothing recorded
    field = call("POST", "/api/v1/objects/asset/fields", 201, json={"key": "serial", "label": "Serial", "type": "text"})
    call("PATCH", "/api/v1/objects/asset/fields/serial", 200, json={"label": "Number"})
    call("DELETE", "/api/v1/objects/asset/fields/serial", 204)
    call("PATCH", "/api/v1/objects/asset/fields/serial", 200, json={"archived": False})
    call("DELETE", "/api/v1/objects/asset", 204)
    call("PATCH", "/api/v1/objects/asset", 200, json={"archived": False})
    kind = call("POST", "/api/v1/association-types", 201, json={
        "from_object": "contact", "to_object": "asset", "label": "owns", "inverse_label": "owned by"})
    call("DELETE", f"/api/v1/association-types/{kind['id']}", 204)
    role = make_role(client, ws, "Auditable")
    call("PATCH", f"/api/v1/roles/{role['id']}", 200, json={"name": "Audited", "capabilities": ["contacts.read"]})
    call("DELETE", f"/api/v1/roles/{role['id']}", 204)
    team = call("POST", "/api/v1/teams", 201, json={"name": "East"})
    call("PATCH", f"/api/v1/teams/{team['id']}", 200, json={"name": "Far East"})
    call("PUT", f"/api/v1/teams/{team['id']}/members/{me}", 200)
    call("PUT", f"/api/v1/teams/{team['id']}/members/{me}", 200)  # already in: not recorded again
    call("DELETE", f"/api/v1/teams/{team['id']}/members/{me}", 204)
    call("DELETE", f"/api/v1/teams/{team['id']}", 204)
    hook = call("POST", "/api/v1/webhooks", 201, json={"url": "https://hooks.example.com/secret-path-123"})
    call("PATCH", f"/api/v1/webhooks/{hook['id']}", 200, json={"url": "https://hooks.example.com/other-path",
                                                                "active": False})
    call("DELETE", f"/api/v1/webhooks/{hook['id']}", 204)

    rows = audit(client, ws)
    kinds = [r["type"] for r in rows]
    for expected in ("object.created", "object.updated", "object.archived", "object.restored", "field.created",
                     "field.updated", "field.archived", "field.restored", "association_type.created",
                     "association_type.deleted", "role.created", "role.updated", "role.deleted", "team.created",
                     "team.updated", "team.member_added", "team.member_removed", "team.deleted",
                     "webhook_endpoint.created", "webhook_endpoint.updated", "webhook_endpoint.deleted"):
        assert expected in kinds, expected
    assert {(r["actor"]["type"], r["actor"]["id"]) for r in rows} == {("user", me)}  # all of it is this person's
    assert kinds.count("object.updated") == 1 and kinds.count("team.member_added") == 1  # no change, no event
    created = only(rows, "object.created")
    assert created["subject"] == {"type": "object", "id": obj["id"]} and created["data"]["key"] == "asset"
    assert only(rows, "object.updated")["data"]["changes"] == {"singular": {"old": "Asset", "new": "Asset!"}}
    assert only(rows, "field.created")["subject"]["id"] == field["id"]
    assert only(rows, "field.updated")["data"]["changes"] == {"label": {"old": "Serial", "new": "Number"}}
    assert only(rows, "field.archived")["data"] == {"id": field["id"], "object": "asset", "key": "serial"}
    assert only(rows, "association_type.created")["data"]["label"] == "owns"
    assert only(rows, "role.created")["data"]["copied_from"] == "member"
    changes = only(rows, "role.updated")["data"]["changes"]
    assert changes["name"] == {"old": "Auditable", "new": "Audited"} and changes["capabilities"]["new"] == [
        "contacts.read"]
    assert only(rows, "role.deleted")["subject"]["id"] == role["id"]
    assert only(rows, "team.updated")["data"]["changes"] == {"name": {"old": "East", "new": "Far East"}}
    assert only(rows, "team.member_added")["data"] == {"team_id": team["id"], "user_id": me}
    # a webhook's URL may carry a token: the log says it changed, not to what
    update = only(rows, "webhook_endpoint.updated")["data"]
    assert update["url_changed"] is True and update["changes"] == {"active": {"old": True, "new": False}}
    assert "secret-path" not in json.dumps(rows) and "other-path" not in json.dumps(rows)


def test_a_role_assignment_is_recorded_with_the_role_before_and_after(crm, db):
    client, ws, ids = crm
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    outsider = add_member(db, ids["org_id"], "o@example.com")
    viewer = role_id(db, ids["org_id"], "viewer")
    for who in (member, outsider, member):  # the same role again is not an event
        r = client.put(f"/api/v1/members/{user_id_of(who)}", json={"role_id": viewer}, headers={H: ws})
        assert r.status_code == 200
    rows = of(audit(client, ws), "member.role_changed")
    assert len(rows) == 2
    by_user = {r["subject"]["id"]: r["data"] for r in rows}
    assert by_user[user_id_of(member)]["old_role"]["key"] == "member"
    assert by_user[user_id_of(member)]["new_role"]["key"] == "viewer"
    assert by_user[user_id_of(outsider)]["old_role"] is None and by_user[user_id_of(outsider)]["workspace_id"] == ws
    assert all(r["actor"]["id"] == user_id_of(client) for r in rows)


def test_password_and_session_changes_go_to_the_audit_log_of_every_workspace_of_the_user(make_user):
    client, ids = make_user("a@example.com", verified=False)
    ws = ids["workspace_id"]
    me = user_id_of(client)
    second = client.post("/api/workspaces", json={"name": "Second", "brand_id": ids["brand_id"]}).json()["id"]
    for _ in range(2):  # two more sessions of the same user
        assert TestClient(app).post("/api/auth/signin", json={"email": "a@example.com", "password": PASSWORD}
                                    ).status_code == 200
    # ending one session by id
    mine = client.get("/api/auth/sessions").json()
    other = next(s for s in mine if not s["current"])
    assert client.delete(f"/api/auth/sessions/{other['id']}").status_code == 204
    # ending all the others
    assert client.post("/api/auth/sessions/revoke-others").json() == {"revoked": 1}
    assert client.post("/api/auth/sessions/revoke-others").json() == {"revoked": 0}  # nothing to end: nothing recorded
    # a new password ends the others too
    TestClient(app).post("/api/auth/signin", json={"email": "a@example.com", "password": PASSWORD})
    r = client.post("/api/auth/password", json={"current_password": PASSWORD, "password": "a better horse battery"})
    assert r.status_code == 204
    for workspace in (ws, second):
        rows = audit(client, workspace)
        revoked = [(r["data"]["count"], r["data"]["reason"]) for r in of(rows, "auth.sessions_revoked")]
        assert sorted(revoked) == [(1, "others_revoked"), (1, "password_changed"), (1, "revoked")], workspace
        changed = only(rows, "user.password_changed")
        assert changed["subject"] == {"type": "user", "id": me} and changed["data"] == {"id": me}
        assert changed["actor"] == {"type": "user", "id": me}
        assert "password" not in json.dumps(rows).replace("password_changed", "")  # never the password or its hash
    # the first sign-in with an emailed link proves the address and ends every older session
    fresh = TestClient(app)
    token = fresh.post("/api/auth/magic-link", json={"email": "a@example.com"}).json()["link"].split("token=")[1]
    assert fresh.post("/api/auth/magic-link/consume", json={"token": token}).status_code == 200
    verified = [r["data"] for r in of(audit(fresh, ws), "auth.sessions_revoked")
                if r["data"]["reason"] == "email_verified"]
    assert len(verified) == 1 and verified[0]["count"] >= 1 and verified[0]["user_id"] == me


def test_the_audit_log_is_for_audit_read_and_stays_inside_the_workspace(crm, make_user, db):
    admin, ws, ids = crm
    other, other_ids = make_user("b@example.com")
    make_record(other, other_ids["workspace_id"], first_name="Elsewhere")
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    assert member.get(AUDIT, headers={H: ws}).status_code == 403
    make_role(admin, ws, "Auditor", copy_from="viewer", capabilities=["audit.read"])
    auditor = add_member(db, ids["org_id"], "aud@example.com", workspace_id=ws, workspace_role="auditor")
    assert auditor.get(AUDIT, headers={H: ws}).status_code == 200
    assert auditor.get(f"{AUDIT}/export", headers={H: ws}).status_code == 200
    mine = audit(admin, ws)
    assert {r["type"] for r in mine} >= {"workspace.created", "user.signed_up"} and "Elsewhere" not in json.dumps(mine)
    assert admin.get(AUDIT, headers={H: other_ids["workspace_id"]}).status_code == 404
    assert TestClient(app).get(AUDIT, headers={H: ws}).status_code == 401


def test_filters_by_actor_subject_type_and_time_range_and_a_cursor_through_all_of_it(crm, db):
    admin, ws, ids = crm
    helper = add_member(db, ids["org_id"], "h@example.com", workspace_id=ws)
    ada = make_record(admin, ws, first_name="Ada")
    grace = make_record(helper, ws, first_name="Grace")
    acme = make_record(admin, ws, "company", name="Acme")
    assert helper.patch(f"/api/v1/objects/contact/records/{grace['id']}", json={"values": {"last_name": "Hopper"}},
                        headers={H: ws}).status_code == 200
    link(admin, ws, ada["id"], acme["id"], type_id(admin, ws, "contact", "company"))
    tag = admin.post("/api/v1/tags", json={"name": "vip"}, headers={H: ws}).json()["id"]
    assert admin.post(f"/api/v1/records/{ada['id']}/tags", json={"add": [tag]}, headers={H: ws}).status_code == 200
    everything = audit(admin, ws)
    ids = [r["id"] for r in everything]
    assert len(everything) >= 9 and ids == sorted(ids, reverse=True)
    helper_id, admin_id = user_id_of(helper), user_id_of(admin)
    assert {r["type"] for r in audit(admin, ws, actor=helper_id)} == {"record.created", "record.updated"}
    assert all(r["actor"]["id"] == helper_id for r in audit(admin, ws, actor=helper_id))
    assert len(audit(admin, ws, actor=admin_id)) + len(audit(admin, ws, actor=helper_id)) == len(everything)
    # a subject: the events about the record, and the ones that touch it among several (a link)
    about_ada = audit(admin, ws, subject=ada["id"])
    assert sorted(r["type"] for r in about_ada) == ["association.created", "record.created", "tag.added"]
    assert sorted(r["type"] for r in audit(admin, ws, subject=acme["id"])) == ["association.created", "record.created"]
    assert [r["type"] for r in audit(admin, ws, subject=grace["id"])] == ["record.updated", "record.created"]
    assert audit(admin, ws, subject="00000000-0000-0000-0000-000000000000") == []
    # a type, and a family of types
    assert {r["type"] for r in audit(admin, ws, type="record.created")} == {"record.created"}
    assert len(audit(admin, ws, type="record.created")) == 3
    family = audit(admin, ws, type="record.*")
    assert {r["type"] for r in family} == {"record.created", "record.updated"}
    assert not audit(admin, ws, type="records.*") and not audit(admin, ws, type="recor_.*")  # a prefix, not a pattern
    assert all(r["type"].startswith("tag.") for r in audit(admin, ws, type="tag.*")) and audit(admin, ws, type="tag.*")
    # a time range, inclusive at both ends
    times = sorted(r["occurred_at"] for r in everything)
    middle = times[len(times) // 2]
    since, until = audit(admin, ws, **{"from": middle}), audit(admin, ws, to=middle)
    assert all(r["occurred_at"] >= middle for r in since) and all(r["occurred_at"] <= middle for r in until)
    assert len(since) + len(until) >= len(everything)
    assert audit(admin, ws, **{"from": "2999-01-01T00:00:00Z"}) == []
    assert len(audit(admin, ws, **{"from": "2000-01-01T00:00:00Z", "to": "2999-01-01T00:00:00Z"})) == len(everything)
    assert len(audit(admin, ws, **{"from": "2000-01-01T00:00:00"})) == len(everything)  # no zone: UTC
    # together, and a cursor through the lot
    both = audit(admin, ws, actor=helper_id, type="record.*", subject=grace["id"])
    assert [r["type"] for r in both] == ["record.updated", "record.created"]
    page = admin.get(AUDIT, params={"limit": 4}, headers={H: ws}).json()
    seen = page["data"]
    while page["next_cursor"]:
        page = admin.get(AUDIT, params={"limit": 4, "cursor": page["next_cursor"]}, headers={H: ws}).json()
        assert len(page["data"]) <= 4
        seen += page["data"]
    assert [r["id"] for r in seen] == [r["id"] for r in everything]  # every event once, newest first
    # what is refused
    for params in ({"type": "Bad Type"}, {"type": "nodot"}, {"actor": "x"}, {"subject": "x"}, {"from": "yesterday"},
                   {"limit": 0}, {"limit": 201}):
        assert admin.get(AUDIT, params=params, headers={H: ws}).status_code == 422, params
    r = admin.get(AUDIT, params={"cursor": "garbage"}, headers={H: ws})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"


def test_the_csv_export_has_the_same_rows_and_is_an_event_itself(crm, monkeypatch):
    client, ws, _ = crm
    for name in ("Ada", "Grace", "Alan"):
        make_record(client, ws, first_name=name, email=f"{name.lower()}@example.com")
    r = client.get(f"{AUDIT}/export", params={"type": "record.*"}, headers={H: ws})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="audit.csv"' in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["id", "occurred_at", "type", "subject_type", "subject_id", "actor_type", "actor_id", "data"]
    api = audit(client, ws, type="record.*")
    assert [row[0] for row in rows[1:]] == [str(e["id"]) for e in api] and len(api) == 3  # newest first, same events
    assert {row[2] for row in rows[1:]} == {"record.created"} and {row[5] for row in rows[1:]} == {"user"}
    data = json.loads(rows[1][7])
    assert data["values"]["first_name"] == "Alan" and data["object"] == "contact"
    # exporting is an event, with what was exported, and the export does not contain it
    exported = only(audit(client, ws), "audit.exported")
    assert exported["data"] == {"rows": 3, "truncated": False, "filters": {"type": "record.*"}}
    assert exported["subject"] == {"type": "workspace", "id": ws} and exported["actor"]["id"] == user_id_of(client)
    assert "audit.exported" not in r.text
    # a second export is a second event, and the first one is in it
    again = client.get(f"{AUDIT}/export", headers={H: ws}).text
    assert "audit.exported" in again and len(of(audit(client, ws), "audit.exported")) == 2
    # a long log is cut at the cap, and the event says so
    monkeypatch.setattr(audit_module, "EXPORT_CAP", 2)
    cut = list(csv.reader(io.StringIO(client.get(f"{AUDIT}/export", headers={H: ws}).text)))
    assert len(cut) == 3
    assert of(audit(client, ws), "audit.exported")[0]["data"] == {"rows": 2, "truncated": True, "filters": {}}


def test_a_hidden_field_is_not_in_the_export_or_the_log_of_a_restricted_auditor(crm, db):
    admin, ws, ids = crm
    make_role(admin, ws, "Careful auditor", copy_from="viewer", capabilities=["audit.read", "contacts.read"],
              rules=[{"object_key": "*", "scope": "all", "hidden_fields": ["email"], "readonly_fields": []}])
    auditor = add_member(db, ids["org_id"], "aud@example.com", workspace_id=ws, workspace_role="careful_auditor")
    make_record(admin, ws, first_name="Ada", email="ada@private-mail.example")
    for text_ in (auditor.get(f"{AUDIT}/export", headers={H: ws}).text, json.dumps(audit(auditor, ws))):
        assert "private-mail" not in text_ and "Ada" in text_
    assert "private-mail" in json.dumps(audit(admin, ws))


def test_events_are_insert_only_for_the_app_role(crm):
    """Request handlers can add to the log and read it, and nothing else: no UPDATE, DELETE or TRUNCATE, not even in
    the broad scope sign up uses. (The owner role, which migrations and the worker use, is not restricted.)"""
    _, ws, ids = crm
    with engine.connect() as conn:
        held = {p: conn.scalar(text("SELECT has_table_privilege('gohigh_app', 'events', :p)"), {"p": p})
                for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")}
        assert held == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False,
                        "REFERENCES": False, "TRIGGER": False}
        assert not conn.scalar(text("SELECT has_column_privilege('gohigh_app', 'events', 'data', 'UPDATE')"))
        conn.rollback()
        insert = text("INSERT INTO events (workspace_id, type, subject_type, subject_id, actor_type, data) "
                      "VALUES (:w, 'webhook.test', 'x', gen_random_uuid(), 'system', '{}') RETURNING id")
        for scope in ({"workspace_id": ws}, {"system": "on"}):
            with conn.begin():
                context(conn, **scope)
                assert conn.scalar(insert, {"w": ws}) > 0  # it may add, and read back what it added
                assert conn.scalar(text("SELECT count(*) FROM events")) >= 1
                conn.rollback()
            for statement in ("UPDATE events SET data = '{\"edited\": true}'", "UPDATE events SET type = 'x.y'",
                              "DELETE FROM events", "DELETE FROM events WHERE type = 'user.signed_up'",
                              "TRUNCATE events"):
                with pytest.raises(DBAPIError, match="permission denied"), conn.begin():
                    context(conn, **scope)
                    conn.execute(text(statement))
        with conn.begin():  # and nothing was changed by any of it
            assert conn.scalar(text("SELECT count(*) FROM events WHERE data ? 'edited'")) == 0
            assert conn.scalar(text("SELECT count(*) FROM events WHERE workspace_id = :w AND type = 'user.signed_up'"),
                               {"w": ws}) == 1
    # the API has no way to rewrite it either: the routes under /audit only read, and export adds an event
    assert {m for m, p, _ in v1_routes() if p.startswith(AUDIT)} == {"GET"}
