"""Tenant isolation, checked at the API (every /api route) and in SQL (as the gohigh_app role)."""
import json
import re

import pytest
from fastapi.routing import iter_route_contexts
from fastapi.testclient import TestClient
from helpers import PASSWORD
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import config
from app.db import engine
from app.main import app
from app.models import Base
from app.security import UNSAFE

TENANT_TABLES = ["organizations", "brands", "workspaces", "users", "org_members", "workspace_members",
                 "auth_sessions", "magic_links", "login_attempts", "events", "webhook_endpoints", "webhook_deliveries",
                 "idempotency_keys"]
NOT_TENANT_DATA = {"jobs", "event_cursors"}  # the queue and the consumer cursors: no tenant rows, no app role access


@pytest.fixture
def two_orgs(make_user, db):
    """Org A and org B, each with a user, a second workspace, a live session, a webhook and one delivery in its log;
    B's identifiers (and its webhook's secret and url) are the secrets."""
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
    b_ids["session_id"] = b.get("/api/auth/sessions").json()[0]["id"]
    b_ids["user_id"] = b.get("/api/me").json()["user"]["id"]
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
               "endpoint_id": b_ids["webhook_id"], "delivery_id": b_ids["delivery_id"]}
    body = {"name": "x", "brand_id": b_ids["brand_id"], "org_id": b_ids["org_id"], "email": "bob@example.com",
            "workspace_id": b_ids["workspace_id"], "password": "not the password", "token": "bogus",
            "url": "https://hooks.example.com/sweep", "event_types": ["*"], "active": False}
    events_of_b = db.scalar(text("SELECT count(*) FROM events WHERE workspace_id = :w"), {"w": b_ids["workspace_id"]})
    routes = [(r, m) for r in iter_route_contexts(app.routes) if (r.path or "").startswith("/api")
              for m in sorted(r.methods - {"HEAD", "OPTIONS"})]
    assert len(routes) >= 23  # every auth, me, workspace and webhook route plus health, openapi and docs
    assert {r.path for r, _ in routes} >= {"/api/v1/webhooks/{endpoint_id}/deliveries",
                                           "/api/v1/webhooks/deliveries/{delivery_id}/replay"}

    seen_own_data = False
    alice = signin_alice()
    for route, method in routes:
        path = re.sub(r"\{(\w+)[^}]*\}", lambda m: by_name.get(m.group(1), b_ids["workspace_id"]), route.path)
        for headers in ({}, {"X-Workspace-Id": b_ids["workspace_id"]}, {"X-Workspace-Id": a_ids["workspace_id"]}):
            r = alice.request(method, path, headers=headers, json=body if method in UNSAFE else None)
            label = f"{method} {route.path} {headers}"
            assert r.status_code < 500, label
            assert not any(leak in r.text for leak in leaks), f"{label} leaked: {r.text[:300]}"
            seen_own_data |= a_ids["workspace_id"] in r.text
            if alice.get("/api/me").status_code != 200:  # that route ended A's session (sign out)
                alice = signin_alice()
            if headers.get("X-Workspace-Id") == b_ids["workspace_id"] and route.path.endswith("/current"):
                assert r.status_code == 404, label
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


def test_a_user_of_a_cannot_target_b_with_a_valid_looking_request(two_orgs):
    a, a_ids, b, b_ids = two_orgs
    assert a.post("/api/workspaces", json={"name": "x", "brand_id": b_ids["brand_id"]}).status_code == 404
    assert a.get(f"/api/workspaces/{b_ids['second_workspace_id']}").status_code == 404
    assert a.delete(f"/api/auth/sessions/{b_ids['session_id']}").status_code == 404
    assert a.get("/api/workspaces/current", headers={"X-Workspace-Id": b_ids["second_workspace_id"]}).status_code == 404
    assert [w["id"] for w in a.get("/api/workspaces").json()] == [a_ids["workspace_id"], a_ids["second_workspace_id"]]


def context(conn, **ctx):
    conn.execute(text("SET LOCAL ROLE gohigh_app"))
    for key in ("user_id", "org_id", "workspace_id", "system"):
        conn.execute(text("SELECT set_config(:k, :v, true)"), {"k": f"app.{key}", "v": str(ctx.get(key, ""))})


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
              "event_cursors": set(), "jobs": {"INSERT"}}  # jobs: add a row and read its id, nothing else
    every = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
    with engine.connect() as conn:
        for table, expected in wanted.items():
            held = {p for p in every if conn.scalar(text("SELECT has_table_privilege('gohigh_app', :t, :p)"),
                                                    {"t": table, "p": p})}
            assert held == expected, table
        columns = {c: conn.scalar(text("SELECT has_column_privilege('gohigh_app', 'jobs', :c, 'SELECT')"), {"c": c})
                   for c in ("id", "kind", "payload", "status")}
        assert columns == {"id": True, "kind": False, "payload": False, "status": False}
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
