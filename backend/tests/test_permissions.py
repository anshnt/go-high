"""Roles and capabilities (ADR 0004): the system roles, what a Viewer and a Member may do, roles and member roles
through the API, and that every /api/v1 route declares the capability it needs."""
import re
import uuid

import pytest
from helpers import H, add_member, context, declared, make_record, make_role, role_id, rule, user_id_of, v1_routes
from sqlalchemy import text

from app import permissions
from app.permissions import ACTIONS, CAPABILITIES, CATALOG

ROLES = "/api/v1/roles"
MEMBERS = "/api/v1/members"
# (method, path) of the /api/v1 routes anyone signed in to a workspace may call. None: even reading the schema is a
# capability, so a new public route has to be listed here on purpose.
PUBLIC: set[tuple[str, str]] = set()


def role_of(client, ws, key):
    return next(r for r in client.get(ROLES, headers={H: ws}).json()["data"] if r["key"] == key)


def test_the_catalog_is_one_list_of_unique_capabilities_grouped_by_module():
    assert len(CAPABILITIES) == len(CATALOG) and all(len(entry) == 3 and all(entry) for entry in CATALOG)
    assert {m for m, _, _ in CATALOG} >= {"Records", "Data model", "Tags and views", "People", "Audit", "Developer"}
    assert {"contacts.read", "contacts.write", "contacts.delete", "contacts.export", "deals.write", "pipelines.manage",
            "fields.manage", "workflows.publish", "messages.send", "billing.manage", "members.manage",
            "webhooks.manage", "audit.read"} <= CAPABILITIES  # what ADR 0004 lists
    assert all(re.fullmatch(r"[a-z]+\.[a-z]+", cap) for cap in CAPABILITIES)
    with pytest.raises(ValueError, match="unknown capability"):
        permissions.known("contacts.reed")


def test_signing_up_seeds_the_system_roles_of_the_organization(crm):
    client, ws, _ = crm
    roles = client.get(ROLES, headers={H: ws}).json()["data"]
    assert sorted(r["key"] for r in roles) == ["admin", "automation", "manager", "member", "owner", "viewer"]
    assert all(r["is_system"] for r in roles) and {r["key"] for r in roles if r["locked"]} == {"owner", "admin"}
    by = {r["key"]: r for r in roles}
    assert set(by["owner"]["capabilities"]) == CAPABILITIES
    assert set(by["admin"]["capabilities"]) == CAPABILITIES - {"billing.manage"}
    assert set(by["viewer"]["capabilities"]) <= {c for c in CAPABILITIES if c.endswith(".read")}
    assert all(set(r["capabilities"]) <= CAPABILITIES for r in roles)
    assert "contacts.export" in by["manager"]["capabilities"] and "contacts.export" not in by["member"]["capabilities"]
    assert all(r["object_rules"] == [rule()] for r in roles)  # every role starts with "all records of any object"
    automation = by["automation"]["capabilities"]
    assert "records.write" in automation and "records.delete" not in automation


def test_every_organization_has_its_own_roles(make_user):
    a, a_ids = make_user("a@example.com")
    b, b_ids = make_user("b@example.com")
    ids_a = {r["id"] for r in a.get(ROLES, headers={H: a_ids["workspace_id"]}).json()["data"]}
    ids_b = {r["id"] for r in b.get(ROLES, headers={H: b_ids["workspace_id"]}).json()["data"]}
    assert len(ids_a) == len(ids_b) == 6 and not ids_a & ids_b
    assert a.get(f"{ROLES}/{next(iter(ids_b))}", headers={H: a_ids["workspace_id"]}).status_code == 404


def test_a_viewer_can_read_but_not_write(crm, db):
    admin, ws, ids = crm
    ada = make_record(admin, ws, first_name="Ada", email="ada@example.com")
    acme = make_record(admin, ws, "company", name="Acme")
    tag = admin.post("/api/v1/tags", json={"name": "vip"}, headers={H: ws}).json()
    view = admin.post("/api/v1/views", json={"object": "contact", "name": "All", "shared": True},
                      headers={H: ws}).json()
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    contact = f"/api/v1/objects/contact/records/{ada['id']}"

    for path in ("/api/v1/objects", "/api/v1/objects/contact", "/api/v1/objects/contact/fields",
                 "/api/v1/objects/contact/records", contact, f"/api/v1/records/{ada['id']}/timeline",
                 f"/api/v1/records/{ada['id']}/associations", "/api/v1/association-types", "/api/v1/tags",
                 "/api/v1/views", f"/api/v1/views/{view['id']}", ROLES, MEMBERS, "/api/v1/teams"):
        assert viewer.get(path, headers={H: ws}).status_code == 200, path
    assert viewer.get(contact, headers={H: ws}).json()["values"]["email"] == "ada@example.com"
    assert viewer.post("/api/v1/objects/contact/records/query", json={}, headers={H: ws}).status_code == 200

    def denied(response, capability):
        assert response.status_code == 403, response.text
        error = response.json()["error"]
        assert error["code"] == "forbidden" and capability in error["message"], error  # it names what is missing
        assert "fields" not in error

    cases = [
        (viewer.post("/api/v1/objects/contact/records", json={"values": {"first_name": "X"}}, headers={H: ws}),
         "contacts.write"),
        (viewer.post("/api/v1/objects/company/records", json={"values": {"name": "X"}}, headers={H: ws}),
         "companies.write"),
        (viewer.patch(contact, json={"values": {"first_name": "X"}}, headers={H: ws}), "contacts.write"),
        (viewer.delete(contact, headers={H: ws}), "contacts.delete"),
        (viewer.post(f"{contact}/restore", headers={H: ws}), "contacts.delete"),
        (viewer.get("/api/v1/trash", params={"object": "contact"}, headers={H: ws}), "contacts.delete"),
        (viewer.post("/api/v1/objects", json={"key": "x", "singular": "X", "plural": "Xs"}, headers={H: ws}),
         "objects.manage"),
        (viewer.post("/api/v1/objects/contact/fields", json={"key": "x", "label": "X", "type": "text"},
                     headers={H: ws}), "fields.manage"),
        (viewer.patch("/api/v1/objects/contact/fields/email", json={"label": "X"}, headers={H: ws}), "fields.manage"),
        (viewer.post("/api/v1/association-types", json={"from_object": "contact", "to_object": "company",
                                                         "label": "x", "inverse_label": "y"}, headers={H: ws}),
         "objects.manage"),
        (viewer.post("/api/v1/tags", json={"name": "new"}, headers={H: ws}), "tags.write"),
        (viewer.post(f"/api/v1/records/{ada['id']}/tags", json={"add": [tag["id"]]}, headers={H: ws}), "tags.write"),
        (viewer.patch(f"/api/v1/tags/{tag['id']}", json={"name": "x"}, headers={H: ws}), "tags.manage"),
        (viewer.delete(f"/api/v1/tags/{tag['id']}", headers={H: ws}), "tags.manage"),
        (viewer.post("/api/v1/views", json={"object": "contact", "name": "Mine"}, headers={H: ws}), "views.write"),
        (viewer.delete(f"/api/v1/views/{view['id']}", headers={H: ws}), "views.write"),
        (viewer.post(f"/api/v1/records/{ada['id']}/associations",
                     json={"type_id": str(uuid.uuid4()), "other_id": acme["id"]}, headers={H: ws}), "write"),
        (viewer.get("/api/v1/webhooks", headers={H: ws}), "webhooks.manage"),
        (viewer.post("/api/v1/webhooks", json={"url": "https://hooks.example.com/x"}, headers={H: ws}),
         "webhooks.manage"),
        (viewer.get("/api/v1/audit", headers={H: ws}), "audit.read"),
        (viewer.get("/api/v1/audit/export", headers={H: ws}), "audit.read"),
        (viewer.post("/api/v1/teams", json={"name": "East"}, headers={H: ws}), "members.manage"),
        (viewer.put(f"{MEMBERS}/{user_id_of(admin)}", json={"role_id": role_id(db, ids["org_id"], "viewer")},
                    headers={H: ws}), "members.manage"),
        (viewer.get("/api/v1/permissions/explain", headers={H: ws}), "members.manage"),
        (viewer.post(ROLES, json={"name": "Mine", "copy_from": "viewer"}, headers={H: ws}), "roles.manage"),
    ]
    for response, capability in cases:
        denied(response, capability)
    # nothing was changed
    assert admin.get(contact, headers={H: ws}).json()["values"] == {"first_name": "Ada", "email": "ada@example.com"}
    assert db.scalar(text("SELECT count(*) FROM records")) == 2 and db.scalar(text("SELECT count(*) FROM tags")) == 1


def test_a_member_keeps_what_a_member_could_always_do(crm, db):
    admin, ws, ids = crm
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    ada = make_record(member, ws, first_name="Ada")
    assert member.patch(f"/api/v1/objects/contact/records/{ada['id']}", json={"values": {"last_name": "L"}},
                        headers={H: ws}).status_code == 200
    tag = member.post("/api/v1/tags", json={"name": "vip"}, headers={H: ws}).json()
    r = member.post(f"/api/v1/records/{ada['id']}/tags", json={"add": [tag["id"]]}, headers={H: ws})
    assert r.status_code == 200
    assert member.post("/api/v1/views", json={"object": "contact", "name": "Mine"}, headers={H: ws}).status_code == 201
    assert member.delete(f"/api/v1/objects/contact/records/{ada['id']}", headers={H: ws}).status_code == 204
    for response in (member.patch(f"/api/v1/tags/{tag['id']}", json={"name": "x"}, headers={H: ws}),
                     member.post("/api/v1/objects", json={"key": "x", "singular": "X", "plural": "Xs"},
                                 headers={H: ws}),
                     member.get("/api/v1/webhooks", headers={H: ws}), member.get("/api/v1/audit", headers={H: ws})):
        assert response.status_code == 403


def test_every_v1_route_declares_a_capability():
    routes = v1_routes()
    assert len(routes) >= 60
    undeclared = [(m, p) for m, p, r in routes if not declared(r.dependant) and (m, p) not in PUBLIC]
    assert not undeclared, undeclared
    assert PUBLIC <= {(m, p) for m, p, _ in routes}  # the allowlist names routes that exist
    for _, path, r in routes:
        for cap in declared(r.dependant):
            assert cap in CAPABILITIES or re.fullmatch(rf"<family>\.({'|'.join(ACTIONS)})", cap), (path, cap)
    # the new routes are among them
    paths = {p for _, p, _ in routes}
    assert paths >= {"/api/v1/roles", "/api/v1/roles/{role_id}", "/api/v1/teams", "/api/v1/teams/{team_id}",
                     "/api/v1/teams/{team_id}/members/{user_id}", "/api/v1/members", "/api/v1/members/{user_id}",
                     "/api/v1/permissions/explain", "/api/v1/audit", "/api/v1/audit/export"}


def test_a_viewer_is_refused_exactly_where_the_routes_say(crm, db):
    """Calls every /api/v1 route as a Viewer with made-up ids: a route whose capability the Viewer lacks answers 403,
    naming it, before it looks at anything; the others get past the permission check."""
    admin, ws, ids = crm
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    held = set(role_of(admin, ws, "viewer")["capabilities"])
    seen = set()
    for method, path, route in v1_routes():
        url = re.sub(r"\{key\}", "contact", path)
        url = re.sub(r"\{(\w+)\}", lambda m: "swept" if m.group(1) == "field_key" else str(uuid.uuid4()), url)
        r = viewer.request(method, url, params={"object": "contact"} if path == "/api/v1/trash" else None,
                           json={} if method in ("POST", "PATCH", "PUT") else None, headers={H: ws})
        for cap in declared(route.dependant):
            wanted = f"contacts.{cap.split('.')[1]}" if cap.startswith("<family>") else cap  # a Viewer has no write
            refused = r.status_code == 403 and "needs" in r.json().get("error", {}).get("message", "")
            assert refused == (wanted not in held), (method, path, cap, r.status_code, r.text[:160])
            if refused and not cap.startswith("<family>"):
                assert wanted in r.json()["error"]["message"], (method, path)
            seen.add(cap)
    assert {"audit.read", "webhooks.manage", "roles.manage", "schema.read", "<family>.write"} <= seen


def test_a_custom_role_starts_as_a_copy_and_is_edited_freely(crm):
    client, ws, _ = crm
    source = role_of(client, ws, "manager")
    role = make_role(client, ws, "Account manager", copy_from="manager")
    assert role["key"] == "account_manager" and role["name"] == "Account manager" and not role["is_system"]
    assert not role["locked"] and role["capabilities"] == source["capabilities"] and role["id"] != source["id"]
    assert role["object_rules"] == source["object_rules"]
    r = client.patch(f"{ROLES}/{role['id']}", headers={H: ws}, json={
        "name": "Account lead", "description": "Looks after accounts", "capabilities": ["contacts.read", "deals.read"],
        "object_rules": [rule(), rule("deal", "team", hidden=["amount"], readonly=["stage"])]})
    assert r.status_code == 200, r.text
    edited = r.json()
    assert edited["name"] == "Account lead" and edited["key"] == "account_manager"  # the key stays
    assert edited["capabilities"] == ["contacts.read", "deals.read"] and edited["description"] == "Looks after accounts"
    assert edited["object_rules"] == [rule(), rule("deal", "team", hidden=["amount"], readonly=["stage"])]
    assert client.get(f"{ROLES}/{role['id']}", headers={H: ws}).json() == edited
    assert role_of(client, ws, "manager") == source  # the role it was copied from is as it was
    r = client.post(ROLES, json={"name": "Account manager!", "copy_from": "viewer"}, headers={H: ws})
    assert r.status_code == 409 and r.json()["error"]["fields"] == {"name": "is already used"}
    assert client.post(ROLES, json={"name": "Admin", "copy_from": "viewer"}, headers={H: ws}).status_code == 409
    r = client.post(ROLES, json={"name": "New", "copy_from": "nobody"}, headers={H: ws})
    assert r.status_code == 422 and "copy_from" in r.json()["error"]["fields"]


def test_unknown_capabilities_scopes_and_fields_are_validation_errors(crm):
    client, ws, _ = crm
    role = make_role(client, ws, "Probe")

    def patch(**body):
        r = client.patch(f"{ROLES}/{role['id']}", json=body, headers={H: ws})
        assert r.status_code == 422, r.text
        return r.json()["error"]["fields"]

    assert patch(capabilities=["contacts.read", "contacts.reed"]) == {
        "capabilities.1": "unknown capability 'contacts.reed'"}
    assert list(patch(object_rules=[rule(scope="everyone")])) == ["object_rules.0.scope"]
    assert list(patch(object_rules=[{"object_key": "Bad Key", "scope": "all"}])) == ["object_rules.0.object_key"]
    assert list(patch(object_rules=[rule(hidden=["owner_id"])])) == ["object_rules.0.hidden_fields.0"]
    assert list(patch(object_rules=[rule(readonly=["Not A Key"])])) == ["object_rules.0.readonly_fields.0"]
    assert patch(object_rules=[rule("deal"), rule("deal", "own")]) == {"object_rules.1.object_key": "is listed twice"}
    assert list(patch(name=None)) == ["name"]
    assert client.get(f"{ROLES}/{role['id']}", headers={H: ws}).json() == role  # nothing was saved


def test_system_roles_cannot_be_deleted_and_owner_and_admin_cannot_be_changed(crm):
    client, ws, _ = crm
    for key in ("owner", "admin", "manager", "member", "viewer", "automation"):
        r = client.delete(f"{ROLES}/{role_of(client, ws, key)['id']}", headers={H: ws})
        assert r.status_code == 409 and "System roles cannot be deleted" in r.text, key
    for key in ("owner", "admin"):
        r = client.patch(f"{ROLES}/{role_of(client, ws, key)['id']}", json={"capabilities": []}, headers={H: ws})
        assert r.status_code == 409 and "cannot be changed" in r.text, key
    # the others are edited freely: Automation is how workflows and AI are kept in check
    automation = role_of(client, ws, "automation")
    r = client.patch(f"{ROLES}/{automation['id']}", json={"capabilities": ["contacts.read"]}, headers={H: ws})
    assert r.status_code == 200 and r.json()["capabilities"] == ["contacts.read"] and r.json()["is_system"]


def test_a_role_in_use_is_not_deleted_until_its_people_have_another(crm, db):
    admin, ws, ids = crm
    role = make_role(admin, ws, "Temp")
    member = add_member(db, ids["org_id"], "t@example.com", workspace_id=ws, workspace_role="temp")
    r = admin.delete(f"{ROLES}/{role['id']}", headers={H: ws})
    assert r.status_code == 409 and r.json()["error"]["code"] == "role_in_use"
    assert member.get("/api/v1/objects", headers={H: ws}).status_code == 200  # and the member still has it
    r = admin.put(f"{MEMBERS}/{user_id_of(member)}", json={"role_id": role_of(admin, ws, "viewer")["id"]},
                  headers={H: ws})
    assert r.status_code == 200
    assert admin.delete(f"{ROLES}/{role['id']}", headers={H: ws}).status_code == 204
    assert admin.get(f"{ROLES}/{role['id']}", headers={H: ws}).status_code == 404
    assert db.scalar(text("SELECT count(*) FROM role_object_rules WHERE role_id = :r"), {"r": role["id"]}) == 0


def test_roles_belong_to_the_organization_so_only_its_owners_and_admins_change_them(crm, db):
    admin, ws, ids = crm
    second = admin.post("/api/workspaces", json={"name": "Second", "brand_id": ids["brand_id"]}).json()["id"]
    role = make_role(admin, ws, "Shared")
    # an admin of one workspace only holds the Admin role there: every capability, but not the organization's roles
    local = add_member(db, ids["org_id"], "l@example.com", workspace_id=ws, workspace_role="admin")
    assert local.get(ROLES, headers={H: ws}).status_code == 200
    for r in (local.post(ROLES, json={"name": "Mine", "copy_from": "viewer"}, headers={H: ws}),
              local.patch(f"{ROLES}/{role['id']}", json={"name": "Hijacked"}, headers={H: ws}),
              local.delete(f"{ROLES}/{role['id']}", headers={H: ws})):
        assert r.status_code == 403 and "organization owners and admins" in r.text
    assert local.post("/api/v1/teams", json={"name": "East"}, headers={H: ws}).status_code == 201  # their own workspace
    # an org admin does, and the role is the same one in every workspace of the org
    org_admin = add_member(db, ids["org_id"], "oa@example.com", org_role="admin")
    assert org_admin.patch(f"{ROLES}/{role['id']}", json={"description": "d"}, headers={H: second}).status_code == 200
    assert admin.get(f"{ROLES}/{role['id']}", headers={H: ws}).json()["description"] == "d"


def test_a_role_without_members_read_cannot_list_roles_teams_or_people(crm, db):
    admin, ws, ids = crm
    make_role(admin, ws, "Blind", copy_from="viewer", capabilities=["contacts.read"])
    blind = add_member(db, ids["org_id"], "b@example.com", workspace_id=ws, workspace_role="blind")
    for path in (ROLES, MEMBERS, "/api/v1/teams", "/api/v1/objects", "/api/v1/tags", "/api/v1/views"):
        r = blind.get(path, headers={H: ws})
        assert r.status_code == 403, path
    assert blind.get("/api/v1/objects/contact/records", headers={H: ws}).status_code == 200


def test_a_role_without_the_read_capability_sees_no_records_of_that_kind(crm, db):
    admin, ws, ids = crm
    ada, acme = make_record(admin, ws, first_name="Ada"), make_record(admin, ws, "company", name="Acme")
    make_role(admin, ws, "Companies only", copy_from="viewer", capabilities=["companies.read", "schema.read"])
    user = add_member(db, ids["org_id"], "c@example.com", workspace_id=ws, workspace_role="companies_only")
    assert user.get("/api/v1/objects/contact/records", headers={H: ws}).status_code == 403
    assert user.get(f"/api/v1/objects/contact/records/{ada['id']}", headers={H: ws}).status_code == 403
    assert user.get(f"/api/v1/records/{ada['id']}/timeline", headers={H: ws}).status_code == 404  # not even a hint
    companies = user.get("/api/v1/objects/company/records", headers={H: ws}).json()["data"]
    assert [r["id"] for r in companies] == [acme["id"]]


def test_the_member_list_and_role_assignment(crm, db):
    admin, ws, ids = crm
    owner = user_id_of(admin)
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    outsider = add_member(db, ids["org_id"], "o@example.com")  # in the organization, not in this workspace
    people = {p["email"]: p for p in admin.get(MEMBERS, headers={H: ws}).json()["data"]}
    assert set(people) == {"a@example.com", "m@example.com"}  # the outsider is not shown
    assert people["a@example.com"]["implicit"] and people["a@example.com"]["role"]["key"] == "owner"
    assert not people["m@example.com"]["implicit"] and people["m@example.com"]["role"]["key"] == "member"
    viewer = role_of(admin, ws, "viewer")
    # give the member a new role, and the outsider a first one in this workspace
    r = admin.put(f"{MEMBERS}/{user_id_of(member)}", json={"role_id": viewer["id"]}, headers={H: ws})
    assert r.status_code == 200 and r.json()["role"]["key"] == "viewer"
    assert member.post("/api/v1/objects/contact/records", json={"values": {"first_name": "X"}},
                       headers={H: ws}).status_code == 403  # applies on their next request
    assert outsider.get("/api/v1/objects", headers={H: ws}).status_code == 404  # no access to the workspace yet
    r = admin.put(f"{MEMBERS}/{user_id_of(outsider)}", json={"role_id": viewer["id"]}, headers={H: ws})
    assert r.status_code == 200 and outsider.get("/api/v1/objects", headers={H: ws}).status_code == 200
    assert {p["email"] for p in admin.get(MEMBERS, headers={H: ws}).json()["data"]} >= {"o@example.com"}
    # refused: organization owners and admins keep admin everywhere, strangers and unknown roles are not found
    assert admin.put(f"{MEMBERS}/{owner}", json={"role_id": viewer["id"]}, headers={H: ws}).status_code == 409
    stranger = uuid.uuid4()
    assert admin.put(f"{MEMBERS}/{stranger}", json={"role_id": viewer["id"]}, headers={H: ws}).status_code == 404
    assert admin.put(f"{MEMBERS}/{user_id_of(member)}", json={"role_id": str(uuid.uuid4())},
                     headers={H: ws}).status_code == 404


def test_nobody_hands_out_a_role_that_can_do_more_than_their_own(crm, db):
    admin, ws, ids = crm
    helper = make_role(admin, ws, "People helper", copy_from="viewer",
                       capabilities=[*role_of(admin, ws, "viewer")["capabilities"], "members.manage"])
    lead = add_member(db, ids["org_id"], "lead@example.com", workspace_id=ws, workspace_role=helper["key"])
    target = add_member(db, ids["org_id"], "t@example.com", workspace_id=ws, workspace_role="viewer")
    r = lead.put(f"{MEMBERS}/{user_id_of(target)}", json={"role_id": role_of(admin, ws, "manager")["id"]},
                 headers={H: ws})
    assert r.status_code == 403 and "more than yours" in r.json()["error"]["message"]
    # a role within their own reach is fine, and so is an organization admin handing out anything
    assert lead.put(f"{MEMBERS}/{user_id_of(target)}", json={"role_id": role_of(admin, ws, "viewer")["id"]},
                    headers={H: ws}).status_code == 200
    assert admin.put(f"{MEMBERS}/{user_id_of(target)}", json={"role_id": role_of(admin, ws, "owner")["id"]},
                     headers={H: ws}).status_code == 200


def test_a_role_cannot_be_edited_to_change_its_own_key_or_system_flag_in_sql(crm, db):
    """The database refuses what the API never does: request handlers may not change a role's key or system flag,
    delete a system role, or edit Owner and Admin or their rules (row level security and column grants)."""
    from sqlalchemy.exc import DBAPIError

    from app.db import engine
    _, ws, ids = crm
    org = ids["org_id"]
    with engine.connect() as conn:
        for statement, message in [
                ("UPDATE roles SET key = 'hacked'", "permission denied"),
                ("UPDATE roles SET is_system = false", "permission denied"),
                ("DELETE FROM roles WHERE is_system", None),
                ("UPDATE roles SET capabilities = '{}' WHERE key IN ('owner', 'admin')", None),
                ("UPDATE role_object_rules SET scope = 'none' "
                 "WHERE role_id IN (SELECT id FROM roles WHERE key = 'owner')", None)]:
            with conn.begin():
                context(conn, workspace_id=ws, org_id=org)
                if message:
                    with pytest.raises(DBAPIError, match=message):
                        conn.execute(text(statement))
                else:
                    assert conn.execute(text(statement)).rowcount == 0, statement  # the policy hides these rows
        with conn.begin():
            context(conn, workspace_id=ws, org_id=org)
            with pytest.raises(DBAPIError, match="row-level security"):  # and no request may create a system role
                conn.execute(text("INSERT INTO roles (org_id, key, name, is_system) VALUES (:o, 'sneaky', 'S', true)"),
                             {"o": org})
