"""Forms and roles (ADR 0004): who may read, write, publish, delete and export, a response writing its contact as the
Automation role, `source = form` on new contacts only, and what a role that cannot see a contact or a field sees of it
in the responses and on the timeline."""
import csv
import io

from forms_helpers import H, Site, lead, q
from helpers import add_member, make_record, make_role, rule
from sqlalchemy import text

FORM_CAPABILITIES = {"forms.read", "forms.write", "forms.publish", "forms.delete", "responses.read",
                     "responses.export"}
ROOT = "/api/v1/forms"
ANSWERS = {"first_name": "Ada", "email": "ada@example.com"}


def denied(r, capability: str) -> None:
    assert r.status_code == 403 and capability in r.json()["error"]["message"], (r.status_code, r.text)


def person(db, ids, ws, role: str, email: str) -> Site:
    return Site(add_member(db, ids["org_id"], email, workspace_id=ws, workspace_role=role), ws)


def test_the_system_roles_hold_the_form_capabilities_the_defaults_say(site):
    roles = {r["key"]: set(r["capabilities"]) for r in site.get("roles").json()["data"]}
    for key in ("owner", "admin", "manager"):
        assert FORM_CAPABILITIES <= roles[key], key
    assert roles["member"] & FORM_CAPABILITIES == {"forms.read", "forms.write", "responses.read"}
    assert roles["viewer"] & FORM_CAPABILITIES == {"forms.read", "responses.read"}
    assert not roles["automation"] & FORM_CAPABILITIES


def test_a_viewer_reads_forms_and_responses_and_changes_nothing(site, crm, db):
    _, ws, ids = crm
    made = site.live()
    done = site.submit(made, ANSWERS)
    viewer = person(db, ids, ws, "viewer", "v@example.com")
    for path in ("forms", f"forms/{made['id']}", f"forms/{made['id']}/versions", f"forms/{made['id']}/analytics",
                 f"forms/{made['id']}/submissions", f"forms/{made['id']}/submissions/{done['id']}"):
        assert viewer.get(path).status_code == 200, path
    versions = viewer.get(f"forms/{made['id']}/versions").json()["data"]
    assert viewer.get(f"forms/{made['id']}/versions/{versions[0]['id']}").status_code == 200
    denied(viewer.get(f"forms/{made['id']}/submissions/export.csv"), "responses.export")
    for method, path, body, capability in [
            ("POST", ROOT, {"name": "x"}, "forms.write"),
            ("POST", f"{ROOT}/{made['id']}/versions", {"definition": lead()}, "forms.write"),
            ("POST", f"{ROOT}/{made['id']}/duplicate", None, "forms.write"),
            ("PATCH", f"{ROOT}/{made['id']}", {"name": "x"}, "forms.write"),
            ("POST", f"{ROOT}/{made['id']}/publish", None, "forms.publish"),
            ("DELETE", f"{ROOT}/{made['id']}", None, "forms.delete"),
            ("POST", f"{ROOT}/{made['id']}/restore", None, "forms.delete")]:
        denied(viewer.client.request(method, path, json=body, headers={H: ws}), capability)
    assert site.get(f"forms/{made['id']}").json()["name"] == "Lead form"  # nothing changed


def test_a_member_works_on_forms_but_cannot_publish_delete_or_export(site, crm, db):
    _, ws, ids = crm
    live = site.live()
    member = person(db, ids, ws, "member", "m@example.com")
    mine = member.create("By a member")  # a draft of their own
    assert member.save(mine, lead(q("company")))["number"] == 2
    copy = member.client.post(f"{ROOT}/{live['id']}/duplicate", headers={H: ws})
    assert copy.status_code == 201 and copy.json()["status"] == "draft"
    patch = lambda form_id, **body: member.client.patch(f"{ROOT}/{form_id}", json=body, headers={H: ws})  # noqa: E731
    assert patch(live["id"], name="Renamed", slug="renamed").status_code == 200  # naming a live form is writing
    same = site.get(f"forms/{live['id']}").json()["settings"]
    assert patch(live["id"], settings=same).status_code == 200  # the same settings are no change
    denied(patch(live["id"], settings={**same, "redirect_url": "https://example.com/elsewhere"}), "forms.publish")
    denied(patch(live["id"], status="closed"), "forms.publish")  # a live form's behaviour changes with publishing
    denied(patch(live["id"], status="draft"), "forms.publish")
    changed = {**same, "success_message": "Thanks!"}
    assert patch(mine["id"], settings=changed).status_code == 200  # a draft is not visible to anyone yet
    denied(member.client.post(f"{ROOT}/{mine['id']}/publish", headers={H: ws}), "forms.publish")
    denied(member.client.delete(f"{ROOT}/{live['id']}", headers={H: ws}), "forms.delete")
    denied(member.get(f"forms/{live['id']}/submissions/export.csv"), "responses.export")
    assert member.get(f"forms/{live['id']}/submissions").status_code == 200
    assert site.get(f"forms/{live['id']}").json()["status"] == "published"
    assert site.get(f"forms/{live['id']}").json()["settings"]["redirect_url"] is None


def test_a_manager_publishes_closes_deletes_and_exports(site, crm, db):
    _, ws, ids = crm
    manager = person(db, ids, ws, "manager", "mg@example.com")
    made = manager.create("Managed")
    published = manager.publish(made)
    assert published["status"] == "published"
    closed = manager.client.patch(f"{ROOT}/{made['id']}", json={"status": "closed"}, headers={H: ws})
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    assert manager.publish(made)["status"] == "published"
    assert manager.get(f"forms/{made['id']}/submissions/export.csv").status_code == 200
    assert manager.client.delete(f"{ROOT}/{made['id']}", headers={H: ws}).status_code == 204
    assert manager.client.post(f"{ROOT}/{made['id']}/restore", headers={H: ws}).status_code == 200


def test_a_role_that_loses_a_form_capability_is_refused_at_once(site, crm, db):
    _, ws, ids = crm
    made = site.live()
    role = make_role(site.client, ws, "Reader", copy_from="member", capabilities=["forms.read", "contacts.read"])
    reader = person(db, ids, ws, role["key"], "r@example.com")
    assert reader.get("forms").status_code == 200
    denied(reader.client.post(ROOT, json={"name": "x"}, headers={H: ws}), "forms.write")
    denied(reader.get(f"forms/{made['id']}/submissions"), "responses.read")
    denied(reader.get(f"forms/{made['id']}/submissions/export.csv"), "responses.export")


# --- the contact a response writes -----------------------------------------------------------------------

def automation(site) -> dict:
    return next(r for r in site.get("roles").json()["data"] if r["key"] == "automation")


def set_capabilities(site, role: dict, capabilities) -> None:
    r = site.client.patch(f"/api/v1/roles/{role['id']}", json={"capabilities": sorted(capabilities)},
                          headers={H: site.ws})
    assert r.status_code == 200, r.text


def test_a_response_writes_its_contact_as_the_automation_role(site, db):
    role = automation(site)
    made = site.live()
    set_capabilities(site, role, set(role["capabilities"]) - {"contacts.write"})  # the organization says: not contacts
    site.submit(made, ANSWERS)
    row = db.execute(text("SELECT status, contact_id, contact_error FROM form_submissions")).mappings().one()
    assert row["status"] == "complete" and row["contact_id"] is None  # the response is kept
    assert "contacts.write" in row["contact_error"] and site.records() == []
    set_capabilities(site, role, role["capabilities"])
    site.submit(made, {"first_name": "Bo", "email": "bo@example.com"})
    [contact] = site.records()
    assert contact["values"]["first_name"] == "Bo" and contact["created_by"] is None


def test_a_new_contact_gets_source_form_and_a_known_one_keeps_its_own(site):
    field = site.client.post("/api/v1/objects/contact/fields", headers={H: site.ws}, json={
        "key": "source", "label": "Source", "type": "select",
        "options": {"choices": [{"id": "web", "label": "Web"}, {"id": "form", "label": "Form"}]}})
    assert field.status_code == 201, field.text
    made = site.live(settings={"contact": {"existing": "update"}})
    site.submit(made, {"first_name": "New", "email": "new@example.com"})
    known = make_record(site.client, site.ws, first_name="Old", email="old@example.com", source="web")
    bare = make_record(site.client, site.ws, first_name="Bare", email="bare@example.com")
    site.submit(made, {"first_name": "Changed", "email": "old@example.com"})
    site.submit(made, {"first_name": "Changed too", "email": "bare@example.com"})
    by_email = {c["values"]["email"]: c for c in site.records()}
    assert by_email["new@example.com"]["values"]["source"] == "form"
    assert by_email["old@example.com"]["values"] == {**known["values"], "first_name": "Changed"}  # still web
    assert by_email["bare@example.com"]["values"].get("source") is None  # never set on a known contact
    assert bare["id"] == by_email["bare@example.com"]["id"]


def test_without_a_source_field_there_is_nothing_to_set(site):
    site.submit(site.live(), ANSWERS)
    assert "source" not in site.records()[0]["values"]


# --- what a role may see of a response ----------------------------------------------------------------------

def phone_form():
    return {"steps": [{"key": "s1", "title": "", "fields": [
        q("first_name", maps_to="first_name"), q("email", "email", maps_to="email"),
        q("phone", "phone", maps_to="phone"), q("note")]}]}


def test_responses_leave_out_what_the_role_may_not_read_of_its_contact(site, crm, db):
    _, ws, ids = crm
    made = site.live(definition=phone_form())
    done = site.submit(made, {**ANSWERS, "phone": "+14155550100", "note": "hello"})
    contact_id = site.get(f"forms/{made['id']}/submissions/{done['id']}").json()["contact_id"]
    assert contact_id
    # reads every contact, but not their phones
    nophone = make_role(site.client, ws, "No phones", copy_from="viewer", rules=[rule("*", hidden=["phone"])])
    viewer = person(db, ids, ws, nophone["key"], "np@example.com")
    shown = viewer.get(f"forms/{made['id']}/submissions/{done['id']}").json()
    assert shown["answers"] == {"first_name": "Ada", "email": "ada@example.com", "note": "hello"}
    assert "phone" not in {f["key"] for f in shown["fields"]} and shown["contact_id"] == contact_id
    listed = viewer.get(f"forms/{made['id']}/submissions").json()["data"][0]
    assert "phone" not in listed["answers"]
    timeline = viewer.get(f"records/{contact_id}/timeline").json()["data"]
    submitted = next(e for e in timeline if e["type"] == "form.submitted")
    assert submitted["data"]["answers"] == {} and submitted["data"]["form_id"] == made["id"]  # the words are not shown
    # the owner sees it all
    assert "phone" in site.get(f"forms/{made['id']}/submissions/{done['id']}").json()["answers"]


def test_a_contact_outside_the_roles_scope_is_not_shown_in_the_responses(site, crm, db):
    _, ws, ids = crm
    made = site.live(definition=phone_form())
    done = site.submit(made, {"first_name": "Ada", "email": "ada@example.com", "phone": "+14155550100"})
    own = make_role(site.client, ws, "Own contacts", copy_from="viewer", rules=[rule("*", scope="own")])
    viewer = person(db, ids, ws, own["key"], "own@example.com")
    shown = viewer.get(f"forms/{made['id']}/submissions/{done['id']}").json()
    assert shown["contact_id"] is None and shown["status"] == "complete"  # the response, not the contact it made
    assert viewer.get(f"forms/{made['id']}/submissions").json()["data"][0]["contact_id"] is None
    rows = list(csv.reader(io.StringIO(site.get(f"forms/{made['id']}/submissions/export.csv").text.lstrip("﻿"))))
    contact_column = rows[0].index("Contact")
    assert rows[1][contact_column]  # the owner's export has it
    export = make_role(site.client, ws, "Exporter", copy_from="viewer",
                       capabilities=["responses.read", "responses.export", "forms.read", "contacts.read"],
                       rules=[rule("*", scope="own", hidden=["phone"])])
    exporter = person(db, ids, ws, export["key"], "ex@example.com")
    mine = list(csv.reader(io.StringIO(exporter.get(f"forms/{made['id']}/submissions/export.csv").text.lstrip("﻿"))))
    assert mine[1][contact_column] == "" and mine[1][mine[0].index("Phone")] == ""  # neither the contact nor the phone
    assert mine[1][mine[0].index("First Name")] == "Ada"
