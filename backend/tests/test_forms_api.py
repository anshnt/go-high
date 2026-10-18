"""The forms admin API: create, validate, version, publish, close, duplicate, trash, list."""
import uuid

import pytest
from forms_helpers import H, Site, form, lead, q, step
from helpers import add_member
from sqlalchemy import text

ROOT = "/api/v1/forms"


def events_of(db, type_: str) -> list[dict]:
    return [row for row in db.execute(text("SELECT data, subject_id::text, actor_type FROM events WHERE type = :t "
                                           "ORDER BY id"), {"t": type_}).mappings()]


def test_a_new_form_starts_as_a_draft_with_a_starter_version(site, db):
    made = site.create("Contact us")
    assert made["status"] == "draft" and made["kind"] == "form" and made["slug"] == "contact-us"
    assert made["latest_version"] == 1 and made["published_version"] is None and made["has_draft_changes"] is False
    assert len(made["public_key"]) == 16 and made["responses"] == 0 and made["completion_rate"] is None
    fields = [f["key"] for f in made["definition"]["steps"][0]["fields"]]
    assert fields == ["first_name", "email"]
    assert made["settings"]["spam_protection"] is True and made["settings"]["rate_limit_per_minute"] == 30
    assert site.get(f"forms/{made['id']}").json()["definition"] == made["definition"]
    created = events_of(db, "form.created")
    assert created[0]["data"] == {"id": made["id"], "name": "Contact us", "kind": "form", "slug": "contact-us",
                                  "status": "draft"} and created[0]["actor_type"] == "user"


def test_each_kind_has_a_working_starter(site):
    for kind in ("survey", "quiz"):
        made = site.create(f"A {kind}", kind=kind)
        assert made["kind"] == kind and made["definition"]["steps"][0]["fields"][0]["type"] == "select"
        assert ("quiz" in made["definition"]) is (kind == "quiz")
        site.publish(made)  # and each can be published as it is


def test_link_names_are_unique_per_workspace_and_chosen_ones_conflict(site, make_user):
    a, b, c = site.create("Same name"), site.create("Same name"), site.create("Same name")
    assert [a["slug"], b["slug"], c["slug"]] == ["same-name", "same-name-2", "same-name-3"]
    assert [site.create("Same name", slug="mine")["slug"]] == ["mine"]
    r = site.client.post(ROOT, json={"name": "x", "slug": "mine"}, headers={H: site.ws})
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    other, ids = make_user("b@example.com")
    assert Site(other, ids["workspace_id"]).create("Same name", slug="mine")["slug"] == "mine"  # per workspace
    for bad in ("Has Space", "-dash", "x" * 80, "UPPER", ""):
        r = site.client.post(ROOT, json={"name": "x", "slug": bad}, headers={H: site.ws})
        assert r.status_code == 422, bad
    assert site.create("!!!")["slug"] == "form"  # a name with no usable letters


@pytest.mark.parametrize("body, field", [
    ({"name": ""}, "name"), ({"name": "x" * 201}, "name"), ({"name": "x", "kind": "poll"}, "kind"),
    ({"name": "x", "settings": {"redirect_url": "javascript:alert(1)"}}, "settings.redirect_url"),
    ({"name": "x", "settings": {"max_body_kb": 1}}, "settings.max_body_kb"),
    ({"name": "x", "settings": {"nope": 1}}, "settings.nope")])
def test_create_validates_the_request(site, body, field):
    r = site.client.post(ROOT, json=body, headers={H: site.ws})
    assert r.status_code == 422 and field in r.json()["error"]["fields"], r.text


def test_a_definition_with_bad_logic_or_mapping_is_refused_and_nothing_is_saved(site, db):
    bad_logic = form(step("s1", q("a"), q("b")), step("s2", q("c")),
                     logic_=[{"when": {"field": "c", "op": "is", "value": "x"}, "do": "hide", "target": "b"}])
    r = site.client.post(ROOT, json={"name": "x", "definition": bad_logic}, headers={H: site.ws})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert "earlier" in r.json()["error"]["fields"]["definition.logic.0.when.field"]
    mapped = form(step("s1", q("a", maps_to="not_a_field"), q("b", "number", maps_to="first_name")))
    r = site.client.post(ROOT, json={"name": "x", "definition": mapped}, headers={H: site.ws})
    fields = r.json()["error"]["fields"]
    assert "no contact field" in fields["definition.steps.0.fields.0.maps_to"]
    assert "cannot fill" in fields["definition.steps.0.fields.1.maps_to"]
    assert [db.scalar(text(f"SELECT count(*) FROM {t}")) for t in ("forms", "form_versions")] == [0, 0]
    made = site.create()
    r = site.client.post(f"{ROOT}/{made['id']}/versions", json={"definition": bad_logic}, headers={H: site.ws})
    assert r.status_code == 422 and db.scalar(text("SELECT count(*) FROM form_versions")) == 1
    assert site.client.post(f"{ROOT}/{made['id']}/versions", json={}, headers={H: site.ws}).status_code == 422


def test_saving_a_draft_is_a_new_immutable_version_and_a_repeat_changes_nothing(site, db):
    made = site.create()
    v2_def = lead(q("phone", "phone", maps_to="phone"))
    v2 = site.save(made, v2_def)
    assert v2["number"] == 2 and v2["published"] is False
    assert v2["definition"]["steps"][0]["fields"][-1]["key"] == "phone"
    again = site.save(made, v2_def)
    assert again["id"] == v2["id"] and db.scalar(text("SELECT count(*) FROM form_versions")) == 2  # no new row
    v3 = site.save(made, lead())
    assert v3["number"] == 3
    listed = site.get(f"forms/{made['id']}/versions").json()["data"]
    assert [v["number"] for v in listed] == [3, 2, 1] and all("definition" not in v for v in listed)
    one = site.get(f"forms/{made['id']}/versions/{v2['id']}").json()
    assert one["number"] == 2 and one["definition"] == v2["definition"]
    assert site.get(f"forms/{made['id']}").json()["definition"] == v3["definition"]  # the builder edits the newest
    assert site.get(f"forms/{made['id']}/versions/{uuid.uuid4()}").status_code == 404
    page = site.get(f"forms/{made['id']}/versions", limit=2).json()
    assert [v["number"] for v in page["data"]] == [3, 2] and page["next_cursor"]
    assert [v["number"] for v in site.get(f"forms/{made['id']}/versions", limit=2, cursor=page["next_cursor"]
                                          ).json()["data"]] == [1]
    stored = db.scalar(text("SELECT definition FROM form_versions WHERE number = 2"))
    assert stored == v2["definition"]


def test_publishing_chooses_what_visitors_see_and_drafts_do_not_change_it(site, db):
    made = site.create(definition=lead())
    published = site.publish(made)
    assert published["status"] == "published" and published["published_version"] == 1
    assert published["has_draft_changes"] is False
    site.save(made, lead(q("company")))
    after = site.get(f"forms/{made['id']}").json()
    assert after["published_version"] == 1 and after["latest_version"] == 2 and after["has_draft_changes"] is True
    live = site.page(made["public_key"]).json()
    assert live["version"] == 1
    assert [f["key"] for f in live["definition"]["steps"][0]["fields"]] == ["first_name", "email"]
    again = site.publish(made)  # the newest version
    assert again["published_version"] == 2 and again["has_draft_changes"] is False
    assert site.page(made["public_key"]).json()["version"] == 2
    old = site.get(f"forms/{made['id']}/versions").json()["data"][-1]
    back = site.publish(made, version_id=old["id"])  # an older one can be published again
    assert back["published_version"] == 1 and back["has_draft_changes"] is True
    events = events_of(db, "form.published")
    assert [e["data"]["version"] for e in events] == [1, 2, 1]
    assert site.publish(made)["published_version"] == 2
    count = len(events_of(db, "form.published"))
    site.publish(made)
    assert len(events_of(db, "form.published")) == count  # publishing what is live is not a change


def test_a_form_without_a_question_cannot_be_published(site):
    empty = form(step("s1", q("intro", "heading", label="Welcome")))
    made = site.create(definition=empty)
    r = site.client.post(f"{ROOT}/{made['id']}/publish", headers={H: site.ws})
    assert r.status_code == 422 and "add a question" in r.json()["error"]["fields"]["definition.steps"]
    assert site.get(f"forms/{made['id']}").json()["status"] == "draft"
    r = site.client.post(f"{ROOT}/{made['id']}/publish", json={"version_id": str(uuid.uuid4())}, headers={H: site.ws})
    assert r.status_code == 404


def test_close_take_offline_and_reopen(site):
    made = site.live()
    key = made["public_key"]
    r = site.client.patch(f"{ROOT}/{made['id']}", json={"status": "closed"}, headers={H: site.ws})
    assert r.json()["status"] == "closed" and r.json()["closed_reason"] == "manual"
    assert site.page(key).status_code == 410
    assert site.publish(made)["status"] == "published" and site.page(key).status_code == 200  # publish reopens
    r = site.client.patch(f"{ROOT}/{made['id']}", json={"status": "draft"}, headers={H: site.ws})
    assert r.json()["status"] == "draft" and r.json()["published_version_id"] is None
    assert site.page(key).status_code == 404  # offline, as if it never existed
    r = site.client.patch(f"{ROOT}/{made['id']}", json={"status": "closed"}, headers={H: site.ws})
    assert r.status_code == 409  # only a published form can be closed
    assert site.client.patch(f"{ROOT}/{made['id']}", json={"status": "published"}, headers={H: site.ws}
                             ).status_code == 422


def test_patching_name_link_and_settings_emits_what_changed(site, db):
    made = site.create("Old name")
    other = site.create("Other")
    r = site.client.patch(f"{ROOT}/{made['id']}", json={"name": "New name", "slug": "new-link", "settings": {
        "success_message": "Done!", "max_responses": 5}}, headers={H: site.ws})
    body = r.json()
    assert r.status_code == 200 and body["name"] == "New name" and body["slug"] == "new-link"
    assert body["settings"]["success_message"] == "Done!" and body["settings"]["max_responses"] == 5
    changed = events_of(db, "form.updated")[0]["data"]
    assert set(changed["changes"]) == {"name", "slug", "settings"} and changed["changes"]["name"] == {
        "old": "Old name", "new": "New name"}
    r = site.client.patch(f"{ROOT}/{made['id']}", json={"name": "New name"}, headers={H: site.ws})
    assert r.status_code == 200 and len(events_of(db, "form.updated")) == 1  # no change, no event
    assert site.client.patch(f"{ROOT}/{made['id']}", json={"slug": other["slug"]}, headers={H: site.ws}
                             ).status_code == 409
    assert site.client.patch(f"{ROOT}/{made['id']}", json={"slug": "new-link"}, headers={H: site.ws}).status_code == 200
    for bad in ({"name": None}, {"settings": {"redirect_url": "ftp://x.test"}}, {"slug": "No Good"}):
        r = site.client.patch(f"{ROOT}/{made['id']}", json=bad, headers={H: site.ws})
        assert r.status_code == 422, bad
    kept = site.client.patch(f"{ROOT}/{made['id']}", json={"kind": "quiz"}, headers={H: site.ws})
    assert kept.status_code == 200 and kept.json()["kind"] == "form"  # the kind cannot change
    assert site.client.patch(f"{ROOT}/{uuid.uuid4()}", json={"name": "x"}, headers={H: site.ws}).status_code == 404


def test_duplicate_copies_the_newest_version_as_a_draft(site):
    made = site.create("Original", settings={"success_message": "Copied!"})
    site.publish(made)
    site.save(made, lead(q("company")))
    r = site.client.post(f"{ROOT}/{made['id']}/duplicate", headers={H: site.ws})
    copy = r.json()
    assert r.status_code == 201 and copy["name"] == "Original (copy)" and copy["status"] == "draft"
    assert copy["slug"] == "original-copy" and copy["public_key"] != made["public_key"] and copy["id"] != made["id"]
    assert [f["key"] for f in copy["definition"]["steps"][0]["fields"]][-1] == "company"  # the newest, not the live one
    assert copy["settings"]["success_message"] == "Copied!" and copy["latest_version"] == 1
    named = site.client.post(f"{ROOT}/{made['id']}/duplicate", json={"name": "Spring"}, headers={H: site.ws}).json()
    assert named["name"] == "Spring" and named["slug"] == "spring"
    assert site.client.post(f"{ROOT}/{uuid.uuid4()}/duplicate", headers={H: site.ws}).status_code == 404


def test_deleting_moves_a_form_to_the_trash_and_it_can_come_back(site, db):
    made = site.live()
    site.submit(made, {"first_name": "Ada", "email": "ada@example.com"})
    assert site.client.delete(f"{ROOT}/{made['id']}", headers={H: site.ws}).status_code == 204
    assert site.get(f"forms/{made['id']}").status_code == 404
    assert site.page(made["public_key"]).status_code == 404  # the link stops working
    assert site.get("forms").json()["data"] == []
    trash = site.get("forms", trashed="true").json()["data"]
    assert [f["id"] for f in trash] == [made["id"]] and trash[0]["responses"] == 1 and trash[0]["deleted_at"]
    assert db.scalar(text("SELECT count(*) FROM form_submissions")) == 1  # the responses are kept
    assert site.client.delete(f"{ROOT}/{made['id']}", headers={H: site.ws}).status_code == 404
    assert site.client.post(f"{ROOT}/{made['id']}/restore", headers={H: site.ws}).status_code == 200
    assert site.get(f"forms/{made['id']}").json()["status"] == "published"
    assert site.page(made["public_key"]).status_code == 200
    assert site.client.post(f"{ROOT}/{made['id']}/restore", headers={H: site.ws}).status_code == 404  # not in trash
    assert [e["data"]["id"] for e in events_of(db, "form.deleted")] == [made["id"]]
    assert [e["data"]["id"] for e in events_of(db, "form.restored")] == [made["id"]]


def test_the_list_filters_pages_and_counts(site):
    forms = [site.create(f"Form {i}", kind="survey" if i == 3 else "form") for i in range(4)]
    site.publish(forms[0])
    site.publish(forms[1])
    site.client.patch(f"{ROOT}/{forms[1]['id']}", json={"status": "closed"}, headers={H: site.ws})

    def names(**params):
        return [f["name"] for f in site.get("forms", **params).json()["data"]]

    assert names() == ["Form 1", "Form 0", "Form 3", "Form 2"]  # most recently changed first
    assert names(status="published") == ["Form 0"] and names(status="closed") == ["Form 1"]
    assert names(status="draft") == ["Form 3", "Form 2"] and names(kind="survey") == ["Form 3"]
    assert names(q="form 2") == ["Form 2"] and names(q="%") == [] and names(q="FORM") == names()
    page = site.get("forms", limit=3).json()
    assert len(page["data"]) == 3 and page["next_cursor"]
    assert names(limit=3, cursor=page["next_cursor"]) == ["Form 2"]
    site.client.patch(f"{ROOT}/{forms[2]['id']}", json={"name": "Form 2 renamed"}, headers={H: site.ws})
    assert names()[0] == "Form 2 renamed"  # an edit moves it to the top
    assert site.get("forms", status="nonsense").status_code == 422


def test_counts_and_completion_rate_show_in_the_list(site):
    made = site.live()
    site.submit(made, {"first_name": "Ada", "email": "ada@example.com"})
    site.submit(made, {"first_name": "Bob", "email": "bob@example.com"})
    site.start(made["public_key"], {"first_name": "Cy"})  # started, never finished
    row = site.get("forms").json()["data"][0]
    assert (row["starts"], row["responses"], row["completion_rate"]) == (3, 2, 0.6667)


def test_creating_with_an_idempotency_key_creates_one_form(site):
    kw = dict(json={"name": "Once"}, headers={H: site.ws, "Idempotency-Key": "form-once-1"})
    first, second = site.client.post(ROOT, **kw), site.client.post(ROOT, **kw)
    assert first.status_code == 201 and second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert len(site.get("forms").json()["data"]) == 1


def test_the_definition_is_normalized_on_the_way_in(site):
    made = site.create(definition=form(step("s1", q("c", "select", options=[{"label": "Red"}, {"label": "Green"}]),
                                            q("note", help="  Say more  "))))
    fields = made["definition"]["steps"][0]["fields"]
    assert [o["id"] for o in fields[0]["options"]] == ["red", "green"] and fields[1]["help"] == "Say more"


def test_any_member_uses_forms_but_strangers_and_visitors_do_not(crm, make_user, db):
    client, ws, ids = crm
    mine = Site(client, ws)
    made = mine.live()
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    as_member = Site(member, ws)
    assert as_member.get("forms").json()["data"][0]["id"] == made["id"]
    assert as_member.create("By a member")["name"] == "By a member"
    stranger, other = make_user("b@example.com")
    calls = [("GET", ROOT), ("POST", ROOT), ("GET", f"{ROOT}/{made['id']}"), ("POST", f"{ROOT}/{made['id']}/publish"),
             ("GET", f"{ROOT}/{made['id']}/submissions"), ("GET", f"{ROOT}/{made['id']}/analytics")]
    for method, path in calls:
        assert stranger.request(method, path, json={"name": "x"}, headers={H: ws}).status_code == 404, path
        assert Site(client, ws).anonymous.request(method, path, json={"name": "x"}, headers={H: ws}
                                                  ).status_code == 401, path
        assert stranger.request(method, path, json={"name": "x"}).status_code == 400  # no workspace chosen
    assert stranger.get(ROOT, headers={H: other["workspace_id"]}).json()["data"] == []


def test_the_forms_routes_are_in_the_api_document(site):
    paths = site.anonymous.get("/api/openapi.json").json()["paths"]
    assert {"/api/v1/forms", "/api/v1/forms/{form_id}/publish", "/api/v1/forms/{form_id}/analytics",
            "/api/public/forms/{public_key}", "/api/public/forms/{public_key}/submissions/{submission_id}/complete",
            } <= set(paths)
