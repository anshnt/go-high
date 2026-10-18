"""Tenant isolation, checked at the API (every /api route) and in SQL (as the gohigh_app role)."""
import itertools
import json
import re

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from helpers import PASSWORD, add_member, context, link, type_id
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import config
from app.db import engine
from app.main import app
from app.models import Base
from app.security import UNSAFE

TENANT_TABLES = ["organizations", "brands", "workspaces", "users", "org_members", "workspace_members",
                 "auth_sessions", "magic_links", "login_attempts", "events", "webhook_endpoints", "webhook_deliveries",
                 "idempotency_keys", "objects", "fields", "records", "tags", "record_tags", "association_types",
                 "associations", "saved_views", "event_records", "pipelines", "stages", "board_layouts", "roles",
                 "role_object_rules", "teams", "team_members", "user_credentials"]
NOT_TENANT_DATA = {"jobs", "event_cursors"}  # the queue and the consumer cursors: no tenant rows, no app role access


def fill_crm(client, ids: dict, name: str) -> None:
    """A custom object with a field, contacts (one in the trash), a company, a tag, two links, two saved views, a
    pipeline with a stage, a deal and a saved board layout, a custom role and a team; their ids, keys and names go
    into `ids`, where they count as secrets when they belong to org B."""
    ws = {"X-Workspace-Id": ids["workspace_id"]}
    title = name.title()

    def post(path, **body):
        r = client.post(path, json=body, headers=ws)
        assert r.status_code == 201, r.text
        return r.json()

    ids["object_key"], ids["field_key"] = f"{name}_vault", f"{name}_secret_field"
    post("/api/v1/objects", key=ids["object_key"], singular=f"{title} Vault", plural=f"{title} Vaults")
    post(f"/api/v1/objects/{ids['object_key']}/fields", key=ids["field_key"], label=f"{title} Secret Label",
         type="text")
    ids["record_name"], ids["company_name"] = f"{title} Secret Person", f"{title} Secret Holdings"
    person = post("/api/v1/objects/contact/records", values={
        "first_name": f"{title} Secret", "last_name": "Person", "email": f"{name}.person@secret.example"})
    company = post("/api/v1/objects/company/records", values={"name": ids["company_name"]})
    vault = post(f"/api/v1/objects/{ids['object_key']}/records", values={
        "name": f"{title} Vault Item", ids["field_key"]: f"{name} secret value"})
    trashed = post("/api/v1/objects/contact/records", values={"first_name": f"{title} Trashed Person"})
    assert client.delete(f"/api/v1/objects/contact/records/{trashed['id']}", headers=ws).status_code == 204
    ids.update(record_id=person["id"], company_id=company["id"], vault_id=vault["id"], trashed_id=trashed["id"],
               trashed_name=f"{title} Trashed Person")
    ids["tag_name"] = f"{name}-secret-tag"
    ids["tag_id"] = post("/api/v1/tags", name=ids["tag_name"])["id"]
    assert client.post(f"/api/v1/records/{person['id']}/tags", json={"add": [ids["tag_id"]]},
                       headers=ws).status_code == 200
    ids["type_label"] = f"{name} owns"
    ids["type_id"] = post("/api/v1/association-types", from_object="contact", to_object=ids["object_key"],
                          label=ids["type_label"], inverse_label=f"{name} owned by")["id"]
    ids["association_id"] = link(client, ids["workspace_id"], person["id"], company["id"],
                                 type_id(client, ids["workspace_id"], "contact", "company"))["id"]
    ids["vault_association_id"] = link(client, ids["workspace_id"], person["id"], vault["id"], ids["type_id"])["id"]
    ids["view_name"], ids["shared_view_name"] = f"{title} private view", f"{title} shared view"
    ids["view_id"] = post("/api/v1/views", object="contact", name=ids["view_name"],
                          filter={"tag": ids["tag_name"]})["id"]
    ids["shared_view_id"] = post("/api/v1/views", object="contact", name=ids["shared_view_name"], shared=True)["id"]
    ids["pipeline_name"], ids["stage_name"], ids["deal_name"] = (f"{title} Secret Pipeline", f"{title} Secret Stage",
                                                                 f"{title} Secret Deal")
    pipeline = post("/api/v1/pipelines", name=ids["pipeline_name"], stages=[
        {"name": ids["stage_name"], "probability": 40, "rotting_days": 3},
        {"name": f"{title} Secret Won", "kind": "won"}])
    ids.update(pipeline_id=pipeline["id"], stage_id=pipeline["stages"][0]["id"],
               won_stage_id=pipeline["stages"][1]["id"])
    deal = post("/api/v1/objects/deal/records", values={"name": ids["deal_name"], "stage": ids["stage_id"],
                                                         "amount": {"amount": 424242, "currency": "USD"}})
    ids["deal_id"] = deal["id"]
    r = client.put(f"/api/v1/pipelines/{pipeline['id']}/layout", json={"collapsed": [ids["won_stage_id"]],
                                                                       "card_fields": ["amount"]}, headers=ws)
    assert r.status_code == 200, r.text
    ids["role_name"] = f"{title} Secret Role"
    role = post("/api/v1/roles", name=ids["role_name"], copy_from="viewer")
    ids.update(role_id=role["id"], role_key=role["key"])
    ids["team_name"] = f"{title} Secret Team"
    ids["team_id"] = post("/api/v1/teams", name=ids["team_name"])["id"]


@pytest.fixture
def two_orgs(make_user, db):
    """Org A and org B, each with a user, a second workspace, a live session, a webhook and one delivery in its log,
    and a small CRM (see fill_crm); B's identifiers, names and secrets are what A must never see."""
    a, a_ids = make_user("alice@example.com", "Alpha Org")
    b, b_ids = make_user("bob@example.com", "Bravo Org")
    for client, ids, name in ((a, a_ids, "alpha"), (b, b_ids, "bravo")):
        r = client.post("/api/workspaces", json={"name": "Second", "brand_id": ids["brand_id"]})
        ids["second_workspace_id"] = r.json()["id"]
        r = client.post("/api/v1/webhooks", json={"url": f"https://hooks.example.com/{name}-private-path"},
                        headers={"X-Workspace-Id": ids["workspace_id"]})
        ids.update(webhook_id=r.json()["id"], webhook_secret=r.json()["secret"], webhook_url=r.json()["url"])
        ids["delivery_id"] = str(db.scalar(text(
            "INSERT INTO webhook_deliveries (workspace_id, endpoint_id, event_id) "
            "SELECT workspace_id, :e, id FROM events WHERE workspace_id = :w AND type = 'user.signed_up' "
            "RETURNING id"), {"e": ids["webhook_id"], "w": ids["workspace_id"]}))
        db.commit()
        fill_crm(client, ids, name)
    b_ids["session_id"] = b.get("/api/auth/sessions").json()[0]["id"]
    b_ids["user_id"] = b.get("/api/me").json()["user"]["id"]
    a_ids["user_id"] = a.get("/api/me").json()["user"]["id"]
    return a, a_ids, b, b_ids


def secrets_of(ids: dict) -> list[str]:
    return [str(v) for v in ids.values() if isinstance(v, str)] + ["bob@example.com", "Bravo Org"]


def signin_alice() -> TestClient:
    client = TestClient(app)
    assert client.post("/api/auth/signin", json={"email": "alice@example.com", "password": PASSWORD}).status_code == 200
    return client


def test_no_api_route_returns_org_bs_data_to_a_user_of_org_a(two_orgs, monkeypatch, db):
    _, a_ids, b, b_ids = two_orgs
    monkeypatch.setattr(config, "DEV_EXPOSE_MAGIC_LINKS", False)  # that switch deliberately hands links to anyone
    leaks = secrets_of(b_ids)
    by_name = {"workspace_id": b_ids["workspace_id"], "session_id": b_ids["session_id"],
               "endpoint_id": b_ids["webhook_id"], "delivery_id": b_ids["delivery_id"],
               "record_id": b_ids["record_id"], "tag_id": b_ids["tag_id"], "view_id": b_ids["view_id"],
               "association_id": b_ids["association_id"], "type_id": b_ids["type_id"], "role_id": b_ids["role_id"],
               "team_id": b_ids["team_id"], "user_id": b_ids["user_id"], "pipeline_id": b_ids["pipeline_id"],
               "stage_id": b_ids["stage_id"], "deal_id": b_ids["deal_id"]}
    others = {"key": [b_ids["object_key"], "contact"], "field_key": [b_ids["field_key"], "email"]}  # B's, and A's own
    body = {"name": "x", "brand_id": b_ids["brand_id"], "org_id": b_ids["org_id"], "email": "bob@example.com",
            "workspace_id": b_ids["workspace_id"], "password": "not the password", "token": "bogus",
            "url": "https://hooks.example.com/sweep", "event_types": ["*"], "active": False,
            # the record engine: B's ids in every place a body takes one
            "key": "swept", "singular": "Swept", "plural": "Sweeps", "label": "Swept", "type": "text",
            "values": {"first_name": "Swept"}, "owner_id": b_ids["user_id"], "record_ids": [b_ids["record_id"]],
            "add": [b_ids["tag_id"]], "remove": [], "other_id": b_ids["record_id"], "type_id": b_ids["type_id"],
            "from_object": "contact", "to_object": "company", "inverse_label": "swept by", "into": b_ids["tag_id"],
            "object": "contact", "shared": True, "filter": {}, "view": b_ids["view_id"],
            # pipelines: B's pipeline, stage and deal wherever a body names one
            "stage_id": b_ids["stage_id"], "stage_ids": [b_ids["stage_id"], b_ids["won_stage_id"]],
            "kind": "open", "probability": 50, "after_id": b_ids["deal_id"], "before_id": b_ids["deal_id"],
            "lost_reason": "price", "collapsed": [b_ids["stage_id"]], "card_fields": ["amount"],
            # permissions: B's role and team in every place a body takes one
            "copy_from": b_ids["role_key"], "role_id": b_ids["role_id"], "capabilities": ["contacts.read"],
            "object_rules": [], "parent_team_id": b_ids["team_id"], "description": "x",
            "ids": [b_ids["record_id"], b_ids["trashed_id"], b_ids["company_id"]]}  # bulk delete and restore
    tables_of_b = ("objects", "fields", "records", "tags", "record_tags", "association_types", "associations",
                   "saved_views", "event_records", "events", "pipelines", "stages", "board_layouts", "teams",
                   "team_members")
    snapshot = "SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) FROM {} t WHERE {} = :w"

    def rows_of_b():
        db.expire_all()
        return ([db.scalar(text(snapshot.format(t, "workspace_id")), {"w": b_ids["workspace_id"]}) for t in tables_of_b]
                + [db.scalar(text(snapshot.format(t, "org_id")), {"w": b_ids["org_id"]})
                   for t in ("roles", "role_object_rules")]
                + [db.scalar(text(snapshot.format("workspace_members", "workspace_id")), {"w": b_ids["workspace_id"]})])

    events_of_b = db.scalar(text("SELECT count(*) FROM events WHERE workspace_id = :w"), {"w": b_ids["workspace_id"]})
    before_b = rows_of_b()
    routes = [(r, m) for r in iter_route_contexts(app.routes) if (r.path or "").startswith("/api")
              for m in sorted(r.methods - {"HEAD", "OPTIONS"})]
    assert len(routes) >= 60  # every auth, me, workspace, webhook and record route plus health, openapi and docs
    assert {r.path for r, _ in routes} >= {
        "/api/v1/webhooks/{endpoint_id}/deliveries", "/api/v1/webhooks/deliveries/{delivery_id}/replay",
        "/api/v1/objects", "/api/v1/objects/{key}", "/api/v1/objects/{key}/fields",
        "/api/v1/objects/{key}/fields/{field_key}", "/api/v1/objects/{key}/records",
        "/api/v1/objects/{key}/records/query", "/api/v1/objects/{key}/records/{record_id}",
        "/api/v1/objects/{key}/records/{record_id}/restore", "/api/v1/trash", "/api/v1/records/{record_id}/timeline",
        "/api/v1/records/{record_id}/associations", "/api/v1/associations/{association_id}",
        "/api/v1/association-types", "/api/v1/association-types/{type_id}", "/api/v1/tags",
        "/api/v1/tags/{tag_id}", "/api/v1/tags/{tag_id}/merge", "/api/v1/records/{record_id}/tags",
        "/api/v1/records/tags", "/api/v1/views", "/api/v1/views/{view_id}", "/api/v1/pipelines",
        "/api/v1/pipelines/{pipeline_id}", "/api/v1/pipelines/{pipeline_id}/stages",
        "/api/v1/pipelines/{pipeline_id}/stages/{stage_id}", "/api/v1/pipelines/{pipeline_id}/stages/reorder",
        "/api/v1/pipelines/{pipeline_id}/board", "/api/v1/pipelines/{pipeline_id}/forecast",
        "/api/v1/pipelines/{pipeline_id}/layout", "/api/v1/deals/{deal_id}/move", "/api/v1/roles",
        "/api/v1/roles/{role_id}", "/api/v1/teams", "/api/v1/teams/{team_id}",
        "/api/v1/teams/{team_id}/members/{user_id}", "/api/v1/members", "/api/v1/members/{user_id}",
        "/api/v1/permissions/explain", "/api/v1/audit", "/api/v1/audit/export",
        "/api/v1/objects/{key}/records/delete", "/api/v1/objects/{key}/records/restore"}

    seen_own_data = False
    alice = signin_alice()
    for route, method in routes:
        params = re.findall(r"\{(\w+)[^}]*\}", route.path)
        for values in itertools.product(*[others.get(p, [by_name.get(p, b_ids["workspace_id"])]) for p in params]):
            chosen = dict(zip(params, values, strict=True))
            path = re.sub(r"\{(\w+)[^}]*\}", lambda m, chosen=chosen: chosen[m.group(1)], route.path)
            for headers in ({}, {"X-Workspace-Id": b_ids["workspace_id"]}, {"X-Workspace-Id": a_ids["workspace_id"]}):
                query = {"object": b_ids["object_key"]} if route.path == "/api/v1/trash" else None
                r = alice.request(method, path, params=query, headers=headers, json=body if method in UNSAFE else None)
                label = f"{method} {route.path} {values} {headers}"
                assert r.status_code < 500, label
                assert not any(leak in r.text for leak in leaks), f"{label} leaked: {r.text[:300]}"
                seen_own_data |= a_ids["workspace_id"] in r.text
                if alice.get("/api/me").status_code != 200:  # that route ended A's session (sign out)
                    alice = signin_alice()
                if headers.get("X-Workspace-Id") == b_ids["workspace_id"] and route.path.endswith("/current"):
                    assert r.status_code == 404, label
                if headers.get("X-Workspace-Id") == a_ids["workspace_id"] and r.status_code == 200:
                    assert b_ids["record_id"] not in r.text, label
    assert seen_own_data  # the sweep is not vacuous: A does get A's data
    mine = {"X-Workspace-Id": a_ids["workspace_id"]}  # A's own webhook routes work, so the 404s for B mean something
    assert alice.get(f"/api/v1/webhooks/{a_ids['webhook_id']}", headers=mine).json()["url"] == a_ids["webhook_url"]
    assert [d["id"] for d in alice.get(f"/api/v1/webhooks/{a_ids['webhook_id']}/deliveries", headers=mine
                                       ).json()["data"]] == [a_ids["delivery_id"]]
    assert alice.post(f"/api/v1/webhooks/deliveries/{a_ids['delivery_id']}/replay", headers=mine).status_code == 202

    assert b.get("/api/me").status_code == 200  # B's session survived A's attempt to revoke it
    assert len(b.get("/api/workspaces").json()) == 2  # and nothing was created in B's brand
    assert {w["name"] for w in b.get("/api/workspaces").json()} == {"Main", "Second"}

    theirs = {"X-Workspace-Id": b_ids["workspace_id"]}  # B's webhook, its log and its event stream are as they were
    kept = b.get(f"/api/v1/webhooks/{b_ids['webhook_id']}", headers=theirs).json()
    assert kept["url"] == b_ids["webhook_url"] and kept["active"] is True and kept["event_types"] == ["*"]
    assert [(d["id"], d["status"]) for d in b.get(f"/api/v1/webhooks/{b_ids['webhook_id']}/deliveries",
                                                  headers=theirs).json()["data"]] == [(b_ids["delivery_id"], "pending")]
    assert len(b.get("/api/v1/webhooks", headers=theirs).json()["data"]) == 1
    assert db.scalar(text("SELECT count(*) FROM events WHERE workspace_id = :w"),
                     {"w": b_ids["workspace_id"]}) == events_of_b
    assert rows_of_b() == before_b  # every table of the record engine: B's rows are byte for byte as they were
    # and A, with the same calls on its own ids, does reach its own records, so the 404s above mean something
    own = {"X-Workspace-Id": a_ids["workspace_id"]}
    assert alice.get(f"/api/v1/objects/contact/records/{a_ids['record_id']}", headers=own).json()[
        "display_name"] == a_ids["record_name"]
    assert alice.get(f"/api/v1/records/{a_ids['record_id']}/timeline", headers=own).json()["data"]
    assert {a_ids["shared_view_id"], a_ids["view_id"]} <= {
        v["id"] for v in alice.get("/api/v1/views", headers=own, params={"limit": 200}).json()["data"]}
    assert a_ids["tag_name"] in {t["name"] for t in alice.get("/api/v1/tags", headers=own).json()["data"]}
    # and A's own pipeline, board, forecast and layout answer for A, so the 404s for B's mean something
    mine_p = f"/api/v1/pipelines/{a_ids['pipeline_id']}"
    assert alice.get(mine_p, headers=own).json()["name"] == a_ids["pipeline_name"]
    cards = [d for st in alice.get(f"{mine_p}/board", headers=own).json()["stages"] for d in st["deals"]]
    assert [d["display_name"] for d in cards] == [a_ids["deal_name"]]
    assert alice.get(f"{mine_p}/forecast", headers=own).status_code == 200
    assert alice.get(f"{mine_p}/layout", headers=own).json()["collapsed"] == [a_ids["won_stage_id"]]


def test_a_user_of_a_cannot_target_b_with_a_valid_looking_request(two_orgs):
    a, a_ids, b, b_ids = two_orgs
    assert a.post("/api/workspaces", json={"name": "x", "brand_id": b_ids["brand_id"]}).status_code == 404
    assert a.get(f"/api/workspaces/{b_ids['second_workspace_id']}").status_code == 404
    assert a.delete(f"/api/auth/sessions/{b_ids['session_id']}").status_code == 404
    assert a.get("/api/workspaces/current", headers={"X-Workspace-Id": b_ids["second_workspace_id"]}).status_code == 404
    assert [w["id"] for w in a.get("/api/workspaces").json()] == [a_ids["workspace_id"], a_ids["second_workspace_id"]]


def rows(conn, table: str) -> list[str]:
    return conn.execute(text(f"SELECT to_jsonb(t)::text FROM {table} t")).scalars().all()  # no WHERE on purpose


def test_sql_with_workspace_a_context_sees_no_rows_of_b(two_orgs):
    _, a_ids, _, b_ids = two_orgs
    leaks = secrets_of(b_ids)
    with engine.connect() as conn:
        for ctx in ({"workspace_id": a_ids["workspace_id"]},
                    {"workspace_id": a_ids["workspace_id"], "org_id": a_ids["org_id"]}):
            with conn.begin():
                context(conn, **ctx)
                for table in TENANT_TABLES:
                    assert not any(leak in row for row in rows(conn, table) for leak in leaks), table
                assert [json.loads(w)["id"] for w in rows(conn, "workspaces")] == [a_ids["workspace_id"]]


def test_sql_as_user_a_sees_only_as_tenants(two_orgs):
    _, a_ids, _, b_ids = two_orgs
    a_user = signin_alice().get("/api/me").json()["user"]["id"]
    leaks = secrets_of(b_ids)
    with engine.connect() as conn, conn.begin():
        context(conn, user_id=a_user)
        for table in TENANT_TABLES:
            assert not any(leak in row for row in rows(conn, table) for leak in leaks), table
        assert len(rows(conn, "workspaces")) == 2 and len(rows(conn, "organizations")) == 1
        assert len(rows(conn, "brands")) == 1 and len(rows(conn, "users")) == 1
        assert all(a_user in row for row in rows(conn, "auth_sessions"))


def test_without_context_the_app_role_sees_nothing_but_the_owner_sees_everything(two_orgs):
    with engine.connect() as conn:
        with conn.begin():  # the plain connection is the owner, which bypasses row level security (a superuser here)
            assert len(rows(conn, "organizations")) == 2
        for table in TENANT_TABLES:
            with conn.begin():
                conn.execute(text("SET LOCAL ROLE gohigh_app"))
                assert rows(conn, table) == [], table
    with engine.connect() as conn, conn.begin():
        context(conn, system="on")
        assert len(rows(conn, "organizations")) == 2  # the pre-auth flows are the only broad scope


def test_the_app_role_cannot_write_into_other_tenants(two_orgs):
    _, a_ids, _, b_ids = two_orgs
    with engine.connect() as conn:
        with pytest.raises(DBAPIError, match="row-level security"), conn.begin():
            context(conn, user_id=signin_alice().get("/api/me").json()["user"]["id"])
            conn.execute(text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, 'sneaky')"),
                         {"o": b_ids["org_id"], "b": b_ids["brand_id"]})
        with conn.begin():
            context(conn, workspace_id=a_ids["workspace_id"])
            assert conn.execute(text("UPDATE users SET name = 'pwned'")).rowcount == 0
            assert conn.execute(text("UPDATE auth_sessions SET revoked_at = now()")).rowcount == 0
            assert conn.execute(text("DELETE FROM auth_sessions")).rowcount == 0


def test_app_role_is_not_privileged_and_rls_is_forced_on_every_tenant_table():
    with engine.connect() as conn:
        role = conn.execute(text("SELECT rolsuper, rolbypassrls, rolcanlogin, rolcreaterole, rolcreatedb "
                                 "FROM pg_roles WHERE rolname = 'gohigh_app'")).one()
        assert tuple(role) == (False, False, False, False, False)
        flags = conn.execute(text("SELECT relname, relrowsecurity, relforcerowsecurity, "
                                  "pg_get_userbyid(relowner) <> 'gohigh_app' FROM pg_class "
                                  "WHERE relname = ANY(:t)"), {"t": TENANT_TABLES}).all()
        assert sorted(f[0] for f in flags) == sorted(TENANT_TABLES)
        assert all(f[1:] == (True, True, True) for f in flags)
        assert set(Base.metadata.tables) - NOT_TENANT_DATA == set(TENANT_TABLES)  # queue and cursors: no tenant rows


def test_the_documented_pattern_isolates_a_new_workspace_table(two_orgs):
    """README recipe for module tables: workspace_id column, FORCE RLS, policy on app_workspace_id()."""
    _, a_ids, _, b_ids = two_orgs
    with engine.connect() as conn:  # nothing is committed: the connection rolls back on close
        conn.execute(text("CREATE TABLE scratch_items (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), "
                          "workspace_id uuid NOT NULL REFERENCES workspaces (id), title text)"))
        conn.execute(text("ALTER TABLE scratch_items ENABLE ROW LEVEL SECURITY"))
        conn.execute(text("ALTER TABLE scratch_items FORCE ROW LEVEL SECURITY"))
        conn.execute(text("CREATE POLICY workspace ON scratch_items USING (workspace_id = app_workspace_id()) "
                          "WITH CHECK (workspace_id = app_workspace_id())"))
        conn.execute(text("GRANT SELECT, INSERT ON scratch_items TO gohigh_app"))
        context(conn, workspace_id=a_ids["workspace_id"])
        conn.execute(text("INSERT INTO scratch_items (workspace_id, title) VALUES (:w, 'mine')"),
                     {"w": a_ids["workspace_id"]})
        with pytest.raises(DBAPIError, match="row-level security"), conn.begin_nested():
            conn.execute(text("INSERT INTO scratch_items (workspace_id, title) VALUES (:w, 'theirs')"),
                         {"w": b_ids["workspace_id"]})
        assert conn.execute(text("SELECT title FROM scratch_items")).scalars().all() == ["mine"]
        context(conn, workspace_id=b_ids["workspace_id"])
        assert conn.execute(text("SELECT count(*) FROM scratch_items")).scalar() == 0


def test_the_app_role_holds_only_the_grants_its_handlers_need():
    wanted = {"events": {"SELECT", "INSERT"}, "webhook_endpoints": {"SELECT", "INSERT", "UPDATE", "DELETE"},
              "webhook_deliveries": {"SELECT", "INSERT"}, "idempotency_keys": {"SELECT", "INSERT", "DELETE"},
              "event_cursors": set(), "jobs": {"INSERT"},  # jobs: add a row and read its id, nothing else
              # the record engine: objects, fields and records are archived or trashed, never deleted by a request
              "objects": {"SELECT", "INSERT", "UPDATE"}, "fields": {"SELECT", "INSERT", "UPDATE"},
              "records": {"SELECT", "INSERT", "UPDATE"}, "tags": {"SELECT", "INSERT", "UPDATE", "DELETE"},
              "record_tags": {"SELECT", "INSERT", "DELETE"}, "association_types": {"SELECT", "INSERT", "DELETE"},
              "associations": {"SELECT", "INSERT", "DELETE"}, "saved_views": {"SELECT", "INSERT", "UPDATE", "DELETE"},
              "event_records": {"SELECT", "INSERT"},
              # pipelines and stages with no deals are deleted by request; a layout is only saved over
              "pipelines": {"SELECT", "INSERT", "UPDATE", "DELETE"}, "stages": {"SELECT", "INSERT", "UPDATE", "DELETE"},
              "board_layouts": {"SELECT", "INSERT", "UPDATE"},
              # roles: UPDATE only on name, description and capabilities (below); a request may not make a system role
              "roles": {"SELECT", "INSERT", "DELETE"}, "role_object_rules": {"SELECT", "INSERT", "UPDATE", "DELETE"},
              "teams": {"SELECT", "INSERT", "UPDATE", "DELETE"}, "team_members": {"SELECT", "INSERT", "DELETE"},
              "workspace_members": {"SELECT", "INSERT"},  # and UPDATE of role_id alone
              # one policy per row of a user's own (and the pre-auth scope); the grants are what that scope needs
              "user_credentials": {"SELECT", "INSERT", "UPDATE", "DELETE"}}
    every = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
    with engine.connect() as conn:
        for table, expected in wanted.items():
            held = {p for p in every if conn.scalar(text("SELECT has_table_privilege('gohigh_app', :t, :p)"),
                                                    {"t": table, "p": p})}
            assert held == expected, table
        columns = {c: conn.scalar(text("SELECT has_column_privilege('gohigh_app', 'jobs', :c, 'SELECT')"), {"c": c})
                   for c in ("id", "kind", "payload", "status")}
        assert columns == {"id": True, "kind": False, "payload": False, "status": False}
        updatable = {(table, c): conn.scalar(text("SELECT has_column_privilege('gohigh_app', :t, :c, 'UPDATE')"),
                                             {"t": table, "c": c})
                     for table, cs in (("roles", ("name", "description", "capabilities", "key", "is_system", "org_id")),
                                       ("workspace_members", ("role_id", "user_id", "workspace_id")))
                     for c in cs}
        assert [k for k, v in updatable.items() if v] == [("roles", "name"), ("roles", "description"),
                                                          ("roles", "capabilities"), ("workspace_members", "role_id")]
        for sequence in ("jobs_id_seq", "events_id_seq"):
            assert conn.scalar(text("SELECT has_sequence_privilege('gohigh_app', :s, 'USAGE')"), {"s": sequence})


def test_the_app_role_cannot_reach_the_queue_or_rewrite_the_log(two_orgs):
    _, a_ids, _, b_ids = two_orgs
    denied = ["SELECT * FROM jobs", "SELECT payload FROM jobs", "UPDATE jobs SET status = 'done'", "DELETE FROM jobs",
              "SELECT * FROM event_cursors", "UPDATE events SET data = '{}'", "DELETE FROM events",
              "UPDATE webhook_deliveries SET status = 'succeeded'", "UPDATE idempotency_keys SET status = 200"]
    with engine.connect() as conn:
        for statement in denied:
            with pytest.raises(DBAPIError, match="permission denied"), conn.begin():
                context(conn, workspace_id=a_ids["workspace_id"])
                conn.execute(text(statement))
        with conn.begin():  # what request handlers do need: enqueue, and read back the id only
            context(conn, workspace_id=a_ids["workspace_id"])
            assert conn.scalar(text("INSERT INTO jobs (kind, payload) VALUES ('noop', '{}') RETURNING id")) > 0
            conn.rollback()


def test_the_app_role_cannot_link_a_delivery_across_workspaces_or_touch_foreign_webhooks(two_orgs):
    _, a_ids, _, b_ids = two_orgs
    insert = text("INSERT INTO webhook_deliveries (workspace_id, endpoint_id, event_id) VALUES (:w, :e, 1)")
    forged_event = text("INSERT INTO events (workspace_id, type, subject_type, subject_id, actor_type, data) "
                        "VALUES (:w, 'webhook.test', 'x', gen_random_uuid(), 'system', '{}')")
    with engine.connect() as conn:
        with pytest.raises(DBAPIError, match="foreign key"), conn.begin():  # A's delivery on B's endpoint
            context(conn, workspace_id=a_ids["workspace_id"])
            conn.execute(insert, {"w": a_ids["workspace_id"], "e": b_ids["webhook_id"]})
        with pytest.raises(DBAPIError, match="row-level security"), conn.begin():  # a delivery planted in B's log
            context(conn, workspace_id=a_ids["workspace_id"])
            conn.execute(insert, {"w": b_ids["workspace_id"], "e": b_ids["webhook_id"]})
        with pytest.raises(DBAPIError, match="row-level security"), conn.begin():  # an event forged into B's log
            context(conn, workspace_id=a_ids["workspace_id"])
            conn.execute(forged_event, {"w": b_ids["workspace_id"]})
        with conn.begin():
            context(conn, workspace_id=a_ids["workspace_id"])
            assert conn.execute(text("UPDATE webhook_endpoints SET active = false")).rowcount == 1  # only A's
            assert conn.execute(text("DELETE FROM idempotency_keys")).rowcount == 0
            assert conn.execute(text("DELETE FROM webhook_endpoints")).rowcount == 1
            conn.rollback()
        with conn.begin():
            assert conn.scalar(text("SELECT count(*) FROM webhook_endpoints WHERE id = :i AND active"),
                               {"i": b_ids["webhook_id"]}) == 1


def test_a_user_of_a_gets_404s_for_bs_objects_fields_records_tags_views_and_links(two_orgs):
    a, a_ids, b, b_ids = two_orgs
    mine = {"X-Workspace-Id": a_ids["workspace_id"]}
    key, record, tag, view = b_ids["object_key"], b_ids["record_id"], b_ids["tag_id"], b_ids["view_id"]
    pipe, stage, deals = b_ids["pipeline_id"], b_ids["stage_id"], "/api/v1/objects/deal/records"
    contact = "/api/v1/objects/contact/records"
    theirs = f"/api/v1/objects/{key}"
    attempts = [
        ("GET", theirs, None), ("PATCH", theirs, {"singular": "x"}), ("DELETE", theirs, None),
        ("GET", f"{theirs}/fields", None),
        ("POST", f"{theirs}/fields", {"key": "x", "label": "X", "type": "text"}),
        ("PATCH", f"{theirs}/fields/{b_ids['field_key']}", {"label": "x"}),
        ("DELETE", f"{theirs}/fields/{b_ids['field_key']}", None),
        ("GET", f"{theirs}/records", None), ("POST", f"{theirs}/records", {"values": {"name": "x"}}),
        ("POST", f"{theirs}/records/query", {}), ("GET", f"{theirs}/records/{b_ids['vault_id']}", None),
        ("GET", f"{contact}/{record}", None), ("PATCH", f"{contact}/{record}", {"values": {"first_name": "x"}}),
        ("DELETE", f"{contact}/{record}", None), ("POST", f"{contact}/{b_ids['trashed_id']}/restore", None),
        ("GET", f"/api/v1/trash?object={key}", None), ("GET", f"/api/v1/records/{record}/timeline", None),
        ("GET", f"/api/v1/records/{record}/associations", None),
        ("POST", f"/api/v1/records/{record}/associations", {"type_id": b_ids["type_id"], "other_id": record}),
        ("DELETE", f"/api/v1/associations/{b_ids['association_id']}", None),
        ("DELETE", f"/api/v1/associations/{b_ids['vault_association_id']}", None),
        ("DELETE", f"/api/v1/association-types/{b_ids['type_id']}", None),
        ("PATCH", f"/api/v1/tags/{tag}", {"name": "stolen"}), ("DELETE", f"/api/v1/tags/{tag}", None),
        ("POST", f"/api/v1/tags/{tag}/merge", {"into": tag}),
        ("POST", f"/api/v1/records/{record}/tags", {"add": [tag]}),
        ("POST", "/api/v1/records/tags", {"record_ids": [record], "remove": [tag]}),
        ("GET", f"/api/v1/views/{view}", None), ("PATCH", f"/api/v1/views/{view}", {"name": "stolen"}),
        ("DELETE", f"/api/v1/views/{view}", None), ("GET", f"/api/v1/views/{b_ids['shared_view_id']}", None),
        ("DELETE", f"/api/v1/views/{b_ids['shared_view_id']}", None),
        ("GET", f"{contact}?view={view}", None), ("GET", f"{contact}?view={b_ids['shared_view_id']}", None),
        # pipelines, stages, the board, the forecast, layouts and moving deals
        ("GET", f"/api/v1/pipelines/{pipe}", None), ("PATCH", f"/api/v1/pipelines/{pipe}", {"name": "stolen"}),
        ("DELETE", f"/api/v1/pipelines/{pipe}", None),
        ("POST", f"/api/v1/pipelines/{pipe}/stages", {"name": "x"}),
        ("PATCH", f"/api/v1/pipelines/{pipe}/stages/{stage}", {"name": "stolen"}),
        ("DELETE", f"/api/v1/pipelines/{pipe}/stages/{stage}", None),
        ("POST", f"/api/v1/pipelines/{pipe}/stages/reorder", {"stage_ids": [stage, b_ids["won_stage_id"]]}),
        ("GET", f"/api/v1/pipelines/{pipe}/board", None), ("GET", f"/api/v1/pipelines/{pipe}/forecast", None),
        ("GET", f"/api/v1/pipelines/{pipe}/layout", None),
        ("PUT", f"/api/v1/pipelines/{pipe}/layout", {"collapsed": [stage]}),
        ("POST", f"/api/v1/deals/{b_ids['deal_id']}/move", {"stage_id": stage}),
        ("POST", f"/api/v1/deals/{b_ids['deal_id']}/move", {"stage_id": a_ids["stage_id"]}),
        ("POST", f"/api/v1/deals/{a_ids['deal_id']}/move", {"stage_id": stage}),
        ("GET", f"/api/v1/pipelines/{a_ids['pipeline_id']}/board?stage={stage}", None),
        ("PATCH", f"/api/v1/pipelines/{a_ids['pipeline_id']}/stages/{stage}", {"name": "stolen"}),
        ("DELETE", f"/api/v1/pipelines/{a_ids['pipeline_id']}/stages/{stage}", None),
        ("GET", f"{deals}/{b_ids['deal_id']}", None),
        ("PATCH", f"{deals}/{b_ids['deal_id']}", {"values": {"name": "x"}}),
        # roles, teams, people and the simulator
        ("GET", f"/api/v1/roles/{b_ids['role_id']}", None),
        ("PATCH", f"/api/v1/roles/{b_ids['role_id']}", {"name": "x"}),
        ("DELETE", f"/api/v1/roles/{b_ids['role_id']}", None), ("GET", f"/api/v1/teams/{b_ids['team_id']}", None),
        ("PATCH", f"/api/v1/teams/{b_ids['team_id']}", {"name": "x"}),
        ("DELETE", f"/api/v1/teams/{b_ids['team_id']}", None),
        ("PUT", f"/api/v1/teams/{b_ids['team_id']}/members/{b_ids['user_id']}", None),
        ("PUT", f"/api/v1/teams/{b_ids['team_id']}/members/{a_ids['user_id']}", None),
        ("DELETE", f"/api/v1/teams/{b_ids['team_id']}/members/{b_ids['user_id']}", None),
        ("PUT", f"/api/v1/members/{b_ids['user_id']}", {"role_id": b_ids["role_id"]}),
        ("PUT", f"/api/v1/members/{b_ids['user_id']}", {"role_id": a_ids["role_id"]}),
        ("PUT", f"/api/v1/members/{a_ids['user_id']}", {"role_id": b_ids["role_id"]}),
        ("GET", f"/api/v1/permissions/explain?user_id={b_ids['user_id']}", None),
        ("GET", f"/api/v1/permissions/explain?record_id={record}", None),
        ("POST", f"{contact}/delete", {"ids": [record]}),
        ("POST", f"{contact}/restore", {"ids": [b_ids["trashed_id"]]}),
        ("POST", f"{theirs}/records/delete", {"ids": [b_ids["vault_id"]]}),
        ("POST", "/api/v1/objects/company/records/delete", {"ids": [b_ids["company_id"]]}),
        ("GET", f"{contact}/{record}?include=tags", None),
        ("PATCH", f"{contact}/{record}?include=tags", {"values": {}}),
    ]
    for method, path, body in attempts:
        r = a.request(method, path, json=body, headers=mine)
        assert r.status_code == 404, (method, path, r.status_code, r.text[:200])
    # A's own records, tags and links against B's: refused without a word about B
    a_tag = a.post("/api/v1/tags", json={"name": "mine"}, headers=mine).json()["id"]
    for method, path, body, status in [
            ("POST", f"/api/v1/records/{a_ids['record_id']}/tags", {"add": [tag]}, 404),
            ("POST", f"/api/v1/records/{record}/tags", {"add": [a_tag]}, 404),
            ("POST", f"/api/v1/tags/{a_tag}/merge", {"into": tag}, 404),
            ("POST", f"/api/v1/tags/{tag}/merge", {"into": a_tag}, 404),
            ("POST", f"/api/v1/records/{a_ids['record_id']}/associations",
             {"type_id": b_ids["type_id"], "other_id": a_ids["company_id"]}, 404),
            ("POST", f"/api/v1/records/{a_ids['record_id']}/associations",
             {"type_id": a_ids["type_id"], "other_id": b_ids["vault_id"]}, 404),
            ("POST", contact, {"values": {"first_name": "x", "company": b_ids["company_id"]}}, 422),
            ("POST", contact, {"values": {"first_name": "x"}, "owner_id": b_ids["user_id"]}, 422),
            ("PATCH", f"{contact}/{a_ids['record_id']}", {"owner_id": b_ids["user_id"]}, 422),
            ("POST", "/api/v1/views", {"object": b_ids["object_key"], "name": "x"}, 404),
            # a deal of A's cannot be put in B's stage, whatever it is called; B's neighbours are not neighbours
            ("POST", deals, {"values": {"name": "x", "stage": stage}}, 422),
            ("PATCH", f"{deals}/{a_ids['deal_id']}", {"values": {"stage": stage}}, 422),
            ("POST", f"/api/v1/deals/{a_ids['deal_id']}/move",
             {"stage_id": a_ids["stage_id"], "after_id": b_ids["deal_id"]}, 422),
            ("POST", f"/api/v1/deals/{a_ids['deal_id']}/move",
             {"stage_id": a_ids["stage_id"], "before_id": b_ids["deal_id"]}, 422),
            ("PUT", f"/api/v1/pipelines/{a_ids['pipeline_id']}/layout", {"collapsed": [stage]}, 422),
            ("POST", f"/api/v1/pipelines/{a_ids['pipeline_id']}/stages/reorder",
             {"stage_ids": [stage, a_ids["stage_id"], a_ids["won_stage_id"]]}, 422),
            ("POST", "/api/v1/teams", {"name": "x", "parent_team_id": b_ids["team_id"]}, 422),
            ("POST", "/api/v1/roles", {"name": "x", "copy_from": b_ids["role_key"]}, 422),
            # a bulk change that mixes A's own ids with B's is refused whole: A's record stays where it is
            ("POST", f"{contact}/delete", {"ids": [a_ids["record_id"], record]}, 404),
            ("POST", f"{contact}/restore", {"ids": [a_ids["trashed_id"], b_ids["trashed_id"]]}, 404),
            ("POST", f"{contact}/delete", {"ids": [b_ids["company_id"]]}, 404)]:
        r = a.request(method, path, json=body, headers=mine)
        assert r.status_code == status, (method, path, r.status_code, r.text[:200])
        assert not any(leak in r.text for leak in secrets_of(b_ids)), (method, path)
    # what A can list and search is A's: not B's names, not B's tag, not B's count
    page = a.get(contact, params={"count": "true", "include": "tags,company", "limit": 200}, headers=mine).json()
    assert {r["display_name"] for r in page["data"]} == {a_ids["record_name"]} and page["total"] == 1
    assert not any(leak in json.dumps(page) for leak in secrets_of(b_ids))
    for query in ({"q": "bravo"}, {"q": "secret"}, {"q": b_ids["record_name"]}, {"filter": json.dumps({"tag": tag})},
                  {"filter": json.dumps({"tag": b_ids["tag_name"]})},
                  {"filter": json.dumps({"field": "company.name", "op": "is", "value": b_ids["company_name"]})}):
        found = a.get(contact, params=query, headers=mine).json()["data"]
        assert not [r for r in found if "Bravo" in r["display_name"]], query
    assert a.get(contact, params={"q": "bravo"}, headers=mine).json()["data"] == []
    trash = a.get("/api/v1/trash", params={"object": "contact"}, headers=mine).json()["data"]
    assert [r["display_name"] for r in trash] == [a_ids["trashed_name"]]
    assert [t["name"] for t in a.get("/api/v1/tags", headers=mine).json()["data"] if "bravo" in t["name"]] == []
    # pipelines, boards and forecasts are A's alone, and a filter on B's pipeline or stage matches nothing
    names_a = [p["name"] for p in a.get("/api/v1/pipelines", headers=mine).json()["data"]]
    assert sorted(names_a) == sorted(["Sales", a_ids["pipeline_name"]])
    mine_pipe = f"/api/v1/pipelines/{a_ids['pipeline_id']}"
    for path in ("/api/v1/pipelines?archived=true", f"{mine_pipe}/board", f"{mine_pipe}/forecast",
                 f"{mine_pipe}/layout", f"{deals}?count=true", "/api/v1/trash?object=deal"):
        r = a.get(path, headers=mine)
        assert r.status_code == 200 and not any(leak in r.text for leak in secrets_of(b_ids)), path
    for filter_ in ({"field": "stage", "op": "is", "value": stage},
                    {"field": "stage.pipeline", "op": "is", "value": pipe},
                    {"field": "stage.pipeline", "op": "in", "value": [pipe, a_ids["pipeline_id"]]}):
        found = a.get(deals, params={"filter": json.dumps(filter_)}, headers=mine).json()["data"]
        assert b_ids["deal_name"] not in json.dumps(found) and all(
            d["display_name"] == a_ids["deal_name"] for d in found), filter_
    assert a.get(f"{contact}/{a_ids['record_id']}", headers=mine).status_code == 200  # the mixed delete did nothing
    assert [t["display_name"] for t in a.get("/api/v1/trash", params={"object": "contact"}, headers=mine).json()["data"]
            ] == [a_ids["trashed_name"]]
    # the people A can list are A's, and A cannot ask for B's workspace
    members = a.get("/api/v1/members", headers=mine).json()["data"]
    assert [m["email"] for m in members] == ["alice@example.com"]
    assert a.get("/api/v1/members", headers={"X-Workspace-Id": b_ids["workspace_id"]}).status_code == 404
    # and B still has all of it
    theirs_h = {"X-Workspace-Id": b_ids["workspace_id"]}
    assert b.get(f"{contact}/{record}", headers=theirs_h).json()["display_name"] == b_ids["record_name"]
    assert [t["name"] for t in b.get("/api/v1/tags", headers=theirs_h).json()["data"]] == [b_ids["tag_name"]]
    still = b.get(f"/api/v1/pipelines/{pipe}", headers=theirs_h).json()
    assert still["name"] == b_ids["pipeline_name"] and [s["name"] for s in still["stages"]] == [
        b_ids["stage_name"], "Bravo Secret Won"]
    deal_b = b.get(f"{deals}/{b_ids['deal_id']}", headers=theirs_h).json()
    assert deal_b["values"]["stage"] == stage and deal_b["values"]["name"] == b_ids["deal_name"]
    assert b.get(f"/api/v1/pipelines/{pipe}/layout", headers=theirs_h).json()["collapsed"] == [b_ids["won_stage_id"]]


def test_the_app_role_cannot_move_a_row_to_another_workspace_or_point_one_across(two_orgs, db):
    _, a_ids, _, b_ids = two_orgs
    a_ws, b_ws = a_ids["workspace_id"], b_ids["workspace_id"]
    b_object = db.scalar(text("SELECT id FROM objects WHERE workspace_id = :w AND key = 'contact'"), {"w": b_ws})
    a_object = db.scalar(text("SELECT id FROM objects WHERE workspace_id = :w AND key = 'contact'"), {"w": a_ws})
    alice = signin_alice().get("/api/me").json()["user"]["id"]
    with engine.connect() as conn:
        # a row cannot change its workspace: the policy checks the new row as well as the old
        for table in ("objects", "fields", "records", "tags", "saved_views", "pipelines", "stages", "board_layouts"):
            with pytest.raises(DBAPIError, match="row-level security"), conn.begin():
                context(conn, workspace_id=a_ws, user_id=alice)
                conn.execute(text(f"UPDATE {table} SET workspace_id = :b"), {"b": b_ws})
        # and cannot be inserted into another one
        for statement in ("INSERT INTO objects (workspace_id, key, singular, plural, primary_fields) "
                          "VALUES (:b, 'x', 'X', 'Xs', '{}')",
                          "INSERT INTO tags (workspace_id, name) VALUES (:b, 'x')",
                          "INSERT INTO records (workspace_id, object_id) VALUES (:b, :bo)",
                          "INSERT INTO fields (workspace_id, object_id, key, label, type) "
                          "VALUES (:b, :bo, 'x', 'X', 'text')",
                          "INSERT INTO pipelines (workspace_id, name) VALUES (:b, 'x')",
                          "INSERT INTO stages (workspace_id, pipeline_id, name) VALUES (:b, :bp, 'x')",
                          "INSERT INTO board_layouts (workspace_id, pipeline_id, user_id) VALUES (:b, :bp, :u)"):
            with pytest.raises(DBAPIError, match="row-level security"), conn.begin():
                context(conn, workspace_id=a_ws, user_id=alice)
                conn.execute(text(statement), {"b": b_ws, "bo": b_object, "bp": b_ids["pipeline_id"], "u": alice})
        # a row of A cannot reference a row of B: the foreign keys carry the workspace
        a_record = db.scalar(text("SELECT id FROM records WHERE workspace_id = :w LIMIT 1"), {"w": a_ws})
        ids = {"a": a_ws, "bo": b_object, "ao": a_object, "bt": b_ids["tag_id"], "ar": a_record,
               "br": b_ids["record_id"], "bty": b_ids["type_id"], "bp": b_ids["pipeline_id"], "u": alice,
               "bs": b_ids["stage_id"]}
        for statement in ("INSERT INTO records (workspace_id, object_id) VALUES (:a, :bo)",
                          "INSERT INTO fields (workspace_id, object_id, key, label, type) "
                          "VALUES (:a, :bo, 'x', 'X', 'text')",
                          "INSERT INTO record_tags (workspace_id, record_id, tag_id) VALUES (:a, :ar, :bt)",
                          "INSERT INTO associations (workspace_id, type_id, from_record_id, to_record_id) "
                          "SELECT :a, id, :ar, :br FROM association_types WHERE workspace_id = :a LIMIT 1",
                          "INSERT INTO associations (workspace_id, type_id, from_record_id, to_record_id) "
                          "SELECT :a, :bty, :ar, id FROM records WHERE workspace_id = :a AND id <> :ar LIMIT 1",
                          "INSERT INTO association_types (workspace_id, from_object_id, to_object_id, label, "
                          "inverse_label) VALUES (:a, :ao, :bo, 'x', 'y')",
                          "INSERT INTO saved_views (workspace_id, object_id, name, shared) VALUES (:a, :bo, 'x', true)",
                          "INSERT INTO event_records (workspace_id, event_id, record_id) VALUES (:a, 1, :br)",
                          "INSERT INTO stages (workspace_id, pipeline_id, name) VALUES (:a, :bp, 'x')",
                          "INSERT INTO board_layouts (workspace_id, pipeline_id, user_id) VALUES (:a, :bp, :u)",
                          "INSERT INTO records (workspace_id, object_id, stage_id) VALUES (:a, :ao, :bs)"):
            with pytest.raises(DBAPIError, match="foreign key"), conn.begin():
                context(conn, workspace_id=a_ws, user_id=alice)  # a layout is its user's, so the policy needs one
                conn.execute(text(statement), ids)
        for statement in ("DELETE FROM records", "DELETE FROM objects", "DELETE FROM fields"):
            with pytest.raises(DBAPIError, match="permission denied"), conn.begin():
                context(conn, workspace_id=a_ws)
                conn.execute(text(statement))
        with pytest.raises(DBAPIError, match="foreign key"), conn.begin():  # a stage that holds a deal stays
            context(conn, workspace_id=a_ws)
            conn.execute(text("DELETE FROM stages"))
        with conn.begin():  # the others can be deleted, and with them a pipeline, but only in the caller's workspace
            context(conn, workspace_id=a_ws)
            held = "SELECT stage_id FROM records WHERE stage_id IS NOT NULL"
            assert conn.execute(text(f"DELETE FROM stages WHERE id NOT IN ({held})")).rowcount == 7
            assert conn.execute(text("DELETE FROM pipelines WHERE id NOT IN (SELECT pipeline_id FROM stages)")
                                ).rowcount == 1  # Sales, which has nothing left
            conn.rollback()
    assert db.scalar(text("SELECT count(*) FROM records WHERE workspace_id = :w"), {"w": b_ws}) == 5  # as filled
    assert db.scalar(text("SELECT count(*) FROM stages WHERE workspace_id = :w"), {"w": b_ws}) == 8
    assert db.scalar(text("SELECT count(*) FROM pipelines WHERE workspace_id = :w"), {"w": b_ws}) == 2


def test_a_private_view_is_hidden_from_other_users_in_sql_too(two_orgs):
    _, a_ids, _, b_ids = two_orgs
    alice = signin_alice().get("/api/me").json()["user"]["id"]
    nobody = "00000000-0000-0000-0000-000000000001"
    names = text("SELECT name FROM saved_views")
    with engine.connect() as conn, conn.begin():
        context(conn, workspace_id=a_ids["workspace_id"], user_id=alice)
        assert {n for n in conn.execute(names).scalars()} == {a_ids["view_name"], a_ids["shared_view_name"]}
        context(conn, workspace_id=a_ids["workspace_id"], user_id=nobody)
        assert conn.execute(names).scalars().all() == [a_ids["shared_view_name"]]
        context(conn, workspace_id=a_ids["workspace_id"])
        assert conn.execute(names).scalars().all() == [a_ids["shared_view_name"]]
        assert conn.execute(text("UPDATE saved_views SET name = 'x' WHERE shared = false")).rowcount == 0
        with pytest.raises(DBAPIError, match="row-level security"):  # nor can a user plant a private view of another
            conn.execute(text("INSERT INTO saved_views (workspace_id, object_id, name, shared, owner_id) "
                              "SELECT workspace_id, object_id, 'x', false, :o FROM saved_views LIMIT 1"),
                         {"o": nobody})


def test_a_board_layout_is_hidden_from_other_users_in_sql_too(two_orgs):
    _, a_ids, _, b_ids = two_orgs
    alice = signin_alice().get("/api/me").json()["user"]["id"]
    nobody = "00000000-0000-0000-0000-000000000001"
    layouts = text("SELECT pipeline_id FROM board_layouts")
    with engine.connect() as conn, conn.begin():
        context(conn, workspace_id=a_ids["workspace_id"], user_id=alice)
        assert [str(p) for p in conn.execute(layouts).scalars()] == [a_ids["pipeline_id"]]
        context(conn, workspace_id=a_ids["workspace_id"], user_id=nobody)
        assert conn.execute(layouts).scalars().all() == []  # in the same workspace, and still not theirs
        context(conn, workspace_id=a_ids["workspace_id"])
        assert conn.execute(layouts).scalars().all() == []
        assert conn.execute(text("UPDATE board_layouts SET layout = '{}'")).rowcount == 0
        with pytest.raises(DBAPIError, match="row-level security"):  # nor can a user save a layout for another
            conn.execute(text("INSERT INTO board_layouts (workspace_id, pipeline_id, user_id) VALUES (:w, :p, :u)"),
                         {"w": a_ids["workspace_id"], "p": a_ids["pipeline_id"], "u": alice})


def test_the_app_role_cannot_reach_other_tenants_roles_teams_or_memberships(two_orgs, db):
    _, a_ids, _, b_ids = two_orgs
    a_ws, a_org, b_ws, b_org = a_ids["workspace_id"], a_ids["org_id"], b_ids["workspace_id"], b_ids["org_id"]
    alice = signin_alice().get("/api/me").json()["user"]["id"]
    ctx = {"workspace_id": a_ws, "org_id": a_org, "user_id": alice}
    add_member(db, a_org, "carol@example.com", workspace_id=a_ws)  # a member row of A's workspace to try to move
    a_role = db.scalar(text("SELECT id FROM roles WHERE org_id = :o AND key = 'viewer'"), {"o": a_org})
    b_role = db.scalar(text("SELECT id FROM roles WHERE org_id = :o AND key = 'viewer'"), {"o": b_org})
    with engine.connect() as conn:
        with conn.begin():  # reading: only the roles, teams and rules of A
            context(conn, **ctx)
            assert {json.loads(r)["org_id"] for r in rows(conn, "roles")} == {a_org}
            assert {json.loads(r)["org_id"] for r in rows(conn, "role_object_rules")} == {a_org}
            assert {json.loads(r)["workspace_id"] for r in rows(conn, "teams")} == {a_ws}
            assert b_ids["role_name"] not in " ".join(rows(conn, "roles"))
            assert conn.execute(text("UPDATE roles SET name = 'x' WHERE org_id = :b"), {"b": b_org}).rowcount == 0
            assert conn.execute(text("DELETE FROM roles WHERE org_id = :b"), {"b": b_org}).rowcount == 0
            assert conn.execute(text("UPDATE role_object_rules SET scope = 'none' WHERE org_id = :b"),
                                {"b": b_org}).rowcount == 0
            assert conn.execute(text("DELETE FROM teams WHERE workspace_id = :b"), {"b": b_ws}).rowcount == 0
            conn.rollback()
        for statement, match in [
                ("INSERT INTO roles (org_id, key, name) VALUES (:b_org, 'k', 'K')", "row-level security"),
                ("INSERT INTO role_object_rules (org_id, role_id, object_key, scope) "
                 "VALUES (:b_org, :b_role, '*', 'all')", "row-level security"),
                ("INSERT INTO teams (workspace_id, name) VALUES (:b_ws, 'x')", "row-level security"),
                # a member of A in a team of B: the foreign key carries the workspace
                ("INSERT INTO team_members (team_id, user_id, workspace_id) VALUES (:b_team, :alice, :a_ws)",
                 "foreign key"),
                # a member of A's workspace who is not in A's organization, or holds a role of another organization
                ("INSERT INTO workspace_members (user_id, workspace_id, role_id) VALUES (:b_user, :a_ws, :a_role)",
                 "row-level security"),
                ("INSERT INTO workspace_members (user_id, workspace_id, role_id) VALUES (:alice, :a_ws, :b_role)",
                 "row-level security"),
                ("UPDATE workspace_members SET role_id = :b_role WHERE workspace_id = :a_ws", "row-level security"),
                ("UPDATE workspace_members SET workspace_id = :b_ws", "permission denied")]:
            ids = {"b_org": b_org, "b_role": b_role, "b_ws": b_ws, "a_ws": a_ws, "alice": alice,
                   "b_user": b_ids["user_id"], "a_role": a_role, "b_team": b_ids["team_id"]}
            with pytest.raises(DBAPIError, match=match), conn.begin():
                context(conn, **ctx)
                conn.execute(text(statement), ids)
    assert db.scalar(text("SELECT count(*) FROM roles WHERE org_id = :o"), {"o": b_org}) == 7  # six system, one custom
    assert db.scalar(text("SELECT count(*) FROM teams WHERE workspace_id = :w"), {"w": b_ws}) == 1
