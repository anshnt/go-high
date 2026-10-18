"""Tenant isolation of forms beyond the sweep in test_isolation.py: the admin routes with another tenant's ids, the
public endpoints with guessed ids and borrowed tokens, the narrow scope a public request starts in, and what the app
role may never do (move rows, point across workspaces, change a saved version)."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_isolation import context, rows, secrets_of, two_orgs  # noqa: F401  (two_orgs is a fixture)

from app.db import engine
from app.main import app


def test_a_user_of_a_gets_404s_for_bs_forms_versions_and_responses(two_orgs):  # noqa: F811
    a, a_ids, b, b_ids = two_orgs
    mine = {"X-Workspace-Id": a_ids["workspace_id"]}
    form, version, response = b_ids["form_id"], b_ids["form_version_id"], b_ids["submission_id"]
    theirs = f"/api/v1/forms/{form}"
    attempts = [
        ("GET", theirs, None), ("PATCH", theirs, {"name": "stolen"}), ("DELETE", theirs, None),
        ("POST", f"{theirs}/restore", None), ("POST", f"{theirs}/duplicate", None),
        ("GET", f"{theirs}/versions", None), ("GET", f"{theirs}/versions/{version}", None),
        ("POST", f"{theirs}/versions", {"definition": {"steps": []}}), ("POST", f"{theirs}/publish", None),
        ("GET", f"{theirs}/submissions", None), ("GET", f"{theirs}/submissions/export.csv", None),
        ("GET", f"{theirs}/submissions/{response}", None), ("GET", f"{theirs}/analytics", None),
        # A's own form with B's version or response
        ("POST", f"/api/v1/forms/{a_ids['form_id']}/publish", {"version_id": version}),
        ("GET", f"/api/v1/forms/{a_ids['form_id']}/versions/{version}", None),
        ("GET", f"/api/v1/forms/{a_ids['form_id']}/submissions/{response}", None),
    ]
    for method, path, body in attempts:
        r = a.request(method, path, json=body, headers=mine)
        assert r.status_code == 404, (method, path, r.status_code, r.text[:200])
        assert not any(leak in r.text for leak in secrets_of(b_ids)), (method, path)
    listed = a.get("/api/v1/forms", params={"limit": 200}, headers=mine).json()["data"]
    assert len(listed) == 2 and a_ids["form_id"] in {f["id"] for f in listed}  # A's published form and A's draft
    assert not any(leak in json.dumps(listed) for leak in secrets_of(b_ids))
    theirs_h = {"X-Workspace-Id": b_ids["workspace_id"]}  # and B still has all of it
    assert b.get(theirs, headers=theirs_h).json()["name"] == b_ids["form_name"]
    assert b.get(f"{theirs}/versions/{version}", headers=theirs_h).status_code == 200
    seen = b.get(f"{theirs}/submissions/{response}", headers=theirs_h).json()
    assert seen["answers"]["first_name"] == b_ids["form_answer"]
    assert b.get(theirs, headers=theirs_h).json()["status"] == "published"


def test_a_public_key_and_a_resume_token_open_only_their_own_form(two_orgs):  # noqa: F811
    a, a_ids, b, b_ids = two_orgs
    anonymous = TestClient(app)
    a_key, b_key = a_ids["form_public_key"], b_ids["form_public_key"]
    for guess in (b_ids["form_id"], b_ids["form_version_id"], b_ids["workspace_id"], b_ids["submission_id"],
                  a_ids["form_id"], a_ids["workspace_id"]):
        assert anonymous.get(f"/api/public/forms/{guess}").status_code == 404, guess
    token = anonymous.post(f"/api/public/forms/{a_key}/views").json()["view_token"]
    base = f"/api/public/forms/{a_key}"
    # B's responses and B's resume tokens against A's form, and A's response with B's token
    for sid, resume in ((b_ids["waiting_id"], b_ids["waiting_token"]), (b_ids["submission_id"], b_ids["resume_token"]),
                        (a_ids["waiting_id"], b_ids["waiting_token"])):
        r = anonymous.post(f"{base}/submissions/{sid}/complete", json={
            "resume_token": resume, "view_token": token, "answers": {"first_name": "x"}})
        assert r.status_code == 404, (sid, r.text)
    assert anonymous.post(f"{base}/resume", json={"resume_token": b_ids["waiting_token"]}).status_code == 404
    r = anonymous.post(f"{base}/submissions", json={
        "resume_token": b_ids["waiting_token"], "view_token": token, "answers": {"first_name": "overwritten"}})
    assert r.status_code == 404
    r = anonymous.post(f"/api/public/forms/{b_key}/submissions", json={
        "resume_token": a_ids["waiting_token"], "view_token": token, "answers": {"first_name": "overwritten"}})
    assert r.status_code in (400, 404)  # A's token on B's form (and a view token that is A's)
    b_headers = {"X-Workspace-Id": b_ids["workspace_id"]}
    seen = b.get(f"/api/v1/forms/{b_ids['form_id']}/submissions", headers=b_headers).json()["data"]
    assert {s["answers"].get("first_name") for s in seen} == {b_ids["form_answer"], "bravo half typed"}


def test_the_public_scope_reads_forms_and_nothing_else(two_orgs):  # noqa: F811
    _, a_ids, _, b_ids = two_orgs
    with engine.connect() as conn:
        with conn.begin():
            context(conn, system="on")  # what a public request has until it has found the form
            assert len(rows(conn, "forms")) == 4
            for table in ("form_versions", "form_submissions", "form_views", "form_rate", "records", "objects",
                          "fields", "webhook_endpoints"):
                assert rows(conn, table) == [], table
            assert conn.execute(text("UPDATE forms SET name = 'x'")).rowcount == 0
        for statement in ("INSERT INTO forms (workspace_id, public_key, kind, name, slug) "
                          "SELECT id, 'k1234567890abcde', 'form', 'x', 'x' FROM workspaces LIMIT 1",):
            with pytest.raises(DBAPIError, match="row-level security"), conn.begin():
                context(conn, system="on")
                conn.execute(text(statement))
        with conn.begin():  # then it moves to the workspace of the form and sees only that one
            context(conn, workspace_id=a_ids["workspace_id"])
            keys = {json.loads(f)["public_key"] for f in rows(conn, "forms")}
            assert a_ids["form_public_key"] in keys and len(keys) == 2
            assert b_ids["form_public_key"] not in "".join(rows(conn, "forms"))
            assert len(rows(conn, "form_submissions")) == 2 and len(rows(conn, "form_versions")) == 2


def test_forms_cannot_point_across_workspaces_and_versions_never_change(two_orgs, db):  # noqa: F811
    _, a_ids, _, b_ids = two_orgs
    a_ws = a_ids["workspace_id"]
    ids = {"a": a_ws, "af": a_ids["form_id"], "bf": b_ids["form_id"], "bv": b_ids["form_version_id"]}
    with engine.connect() as conn:
        for table in ("forms", "form_submissions", "form_views", "form_rate"):  # a row cannot change workspace
            with pytest.raises(DBAPIError, match="row-level security"), conn.begin():
                context(conn, workspace_id=a_ws)
                conn.execute(text(f"UPDATE {table} SET workspace_id = :b"), {"b": b_ids["workspace_id"]})
        for statement in (  # a row of A cannot reference a row of B, or a version of another form
                "UPDATE forms SET published_version_id = :bv WHERE id = :af",
                "INSERT INTO form_submissions (workspace_id, form_id, version_id) VALUES (:a, :af, :bv)",
                "INSERT INTO form_submissions (workspace_id, form_id, version_id) VALUES (:a, :bf, :bv)",
                "INSERT INTO form_versions (workspace_id, form_id, number, definition) VALUES (:a, :bf, 9, '{}')",
                "INSERT INTO form_views (workspace_id, form_id, day, count) VALUES (:a, :bf, '2000-01-01', 1)"):
            with pytest.raises(DBAPIError, match="foreign key"), conn.begin():
                context(conn, workspace_id=a_ws)
                conn.execute(text(statement), ids)
        for statement in ("UPDATE form_versions SET definition = '{}'", "DELETE FROM form_versions",
                          "DELETE FROM forms", "DELETE FROM form_submissions", "DELETE FROM form_views",
                          "TRUNCATE form_rate"):  # a saved version is final; nothing is deleted by a request
            with pytest.raises(DBAPIError, match="permission denied"), conn.begin():
                context(conn, workspace_id=a_ws)
                conn.execute(text(statement))
        with conn.begin():  # the counters are the one thing a request may delete, and only its own workspace's
            context(conn, workspace_id=a_ws)
            conn.execute(text("INSERT INTO form_rate (workspace_id, form_id, ip_hash, kind, bucket, count) "
                              "VALUES (:a, :af, 'h', 'write', 1, 1)"), ids)
            # A's own: the view and write counters of its form, and this one
            assert conn.execute(text("DELETE FROM form_rate")).rowcount == 3
    assert db.scalar(text("SELECT count(*) FROM form_rate WHERE workspace_id = :w"), {"w": b_ids["workspace_id"]}) == 2
    assert db.scalar(text("SELECT definition->'steps' IS NOT NULL FROM form_versions WHERE id = :v"),
                     {"v": b_ids["form_version_id"]})
