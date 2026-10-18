"""Records through the API: seeding, validation, display name and identity columns, updates, trash, events."""
import json
import uuid

from helpers import H, add_member, drain, listing, make_record, names, verify_signature
from sqlalchemy import text

from app import config
from app.records import objects, seed

OBJECTS = "/api/v1/objects"
R = f"{OBJECTS}/contact/records"


def get(client, ws, path, **params):
    return client.get(path, params=params, headers={H: ws})


def events_of(db, record_id) -> list[tuple[str, dict]]:
    db.expire_all()
    return [(e.type, e.data) for e in db.execute(text(
        "SELECT type, data FROM events WHERE subject_id = :i ORDER BY id"), {"i": record_id})]


def row(db, record_id) -> dict:
    db.expire_all()
    return dict(db.execute(text("SELECT display_name, email_norm, phone_e164, owner_id, values FROM records "
                                "WHERE id = :i"), {"i": record_id}).mappings().one())


def test_every_workspace_starts_with_contacts_companies_and_deals(make_user, crm):
    client, ws, ids = crm
    second = client.post("/api/workspaces", json={"name": "Second", "brand_id": ids["brand_id"]}).json()["id"]
    for workspace in (ws, second):
        page = get(client, workspace, OBJECTS).json()
        assert {o["key"] for o in page["data"]} == {"contact", "company", "deal"}
        assert all(o["is_system"] for o in page["data"])
        contact = get(client, workspace, f"{OBJECTS}/contact").json()
        assert contact["primary_fields"] == ["first_name", "last_name"]
        assert [(f["key"], f["type"]) for f in contact["fields"]] == [
            ("first_name", "text"), ("last_name", "text"), ("email", "email"), ("phone", "phone"),
            ("lifecycle", "select"), ("company", "record")]
        assert [c["id"] for c in contact["fields"][4]["options"]["choices"]] == [
            "lead", "qualified", "customer", "churned", "other"]
        assert contact["fields"][5]["options"] == {"object": "company"}
        company = get(client, workspace, f"{OBJECTS}/company").json()
        assert [(f["key"], f["type"]) for f in company["fields"]] == [
            ("name", "text"), ("domain", "text"), ("industry", "text"), ("size", "select")]
        assert company["fields"][0]["rules"] == {"required": True}
        deal = get(client, workspace, f"{OBJECTS}/deal").json()
        assert [(f["key"], f["type"]) for f in deal["fields"]] == [
            ("name", "text"), ("amount", "money"), ("stage", "stage"), ("close_date", "date")]
        assert deal["fields"][1]["options"] == {"currency": "USD"}
        types = get(client, workspace, "/api/v1/association-types").json()["data"]
        assert {(t["from_object"], t["to_object"], t["label"], t["inverse_label"]) for t in types} == {
            ("contact", "company", "works at", "employs"), ("deal", "contact", "contact", "deal"),
            ("deal", "company", "company", "deal")}
        assert all(t["cardinality"] == "many_to_many" and t["is_system"] for t in types)
    mine = {o["id"] for o in get(client, ws, OBJECTS).json()["data"]}
    assert not mine & {o["id"] for o in get(client, second, OBJECTS).json()["data"]}  # not shared between workspaces


def test_a_contact_is_validated_normalized_and_named(crm, db):
    client, ws, _ = crm
    me = client.get("/api/me").json()["user"]["id"]
    ada = make_record(client, ws, first_name=" Ada ", last_name="Lovelace", email=" Ada@Example.com ",
                      phone="(415) 555-2671", lifecycle="lead")
    assert ada["display_name"] == "Ada Lovelace" and ada["object"] == "contact" and ada["created_by"] == me
    assert ada["values"] == {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com",
                             "phone": "+14155552671", "lifecycle": "lead"}
    assert ada["owner_id"] is None and ada["deleted_at"] is None and ada["created_at"] == ada["updated_at"]
    stored = row(db, ada["id"])
    assert (stored["display_name"], stored["email_norm"], stored["phone_e164"]) == (
        "Ada Lovelace", "ada@example.com", "+14155552671")
    assert get(client, ws, f"{R}/{ada['id']}").json() == ada

    # the name is the first and last name, else the email, else the phone; nothing at all is refused
    assert make_record(client, ws, first_name="Grace")["display_name"] == "Grace"
    assert make_record(client, ws, last_name="Hopper")["display_name"] == "Hopper"
    assert make_record(client, ws, email="x@example.com")["display_name"] == "x@example.com"
    assert make_record(client, ws, phone="+442079460958")["display_name"] == "+442079460958"
    both = make_record(client, ws, email="e@example.com", phone="+442079460958")
    assert both["display_name"] == "e@example.com"
    r = client.post(R, json={"values": {"lifecycle": "lead"}}, headers={H: ws})
    assert r.status_code == 422 and "needs a name" in r.json()["error"]["fields"]["values"]
    assert client.post(R, json={}, headers={H: ws}).status_code == 422

    company = make_record(client, ws, "company", name="Analytical Engines")
    assert company["display_name"] == "Analytical Engines"
    deal = make_record(client, ws, "deal", name="Engine order", amount={"amount": 250000, "currency": "usd"},
                       stage="proposal", close_date="2026-12-01")
    assert deal["values"]["amount"] == {"amount": 250000, "currency": "USD"}
    assert row(db, deal["id"])["email_norm"] is None and row(db, deal["id"])["phone_e164"] is None


def test_a_bad_record_names_every_bad_field(crm):
    client, ws, _ = crm
    r = client.post(R, json={"values": {"first_name": 5, "email": "nope", "phone": "123", "lifecycle": "vip",
                                        "mystery": 1, "company": "x"}}, headers={H: ws})
    error = r.json()["error"]
    assert r.status_code == 422 and error["code"] == "validation_failed"
    assert set(error["fields"]) == {"values.first_name", "values.email", "values.phone", "values.lifecycle",
                                    "values.mystery", "values.company"}
    assert error["fields"]["values.email"] == "Email is not an email address"
    assert error["fields"]["values.mystery"] == "is not a field of contact"
    r = client.post(f"{OBJECTS}/company/records", json={"values": {"domain": "x.com"}}, headers={H: ws})
    assert r.json()["error"]["fields"] == {"values.name": "Name is required"}
    assert client.post(R, json={"values": "text"}, headers={H: ws}).status_code == 422
    assert client.post(R, json={"values": {}, "owner_id": "nope"}, headers={H: ws}).status_code == 422
    assert client.post(f"{OBJECTS}/nothing/records", json={"values": {}}, headers={H: ws}).status_code == 404
    assert listing(client, ws)["data"] == []  # nothing was saved


def test_update_merges_clears_and_emits_only_when_something_changed(crm, db):
    client, ws, _ = crm
    me = client.get("/api/me").json()["user"]["id"]
    ada = make_record(client, ws, first_name="Ada", email="ada@example.com", phone="+14155552671")
    path = f"{R}/{ada['id']}"
    r = client.patch(path, json={"values": {"last_name": "Lovelace", "lifecycle": "customer"}}, headers={H: ws})
    assert r.status_code == 200 and r.json()["display_name"] == "Ada Lovelace"
    assert r.json()["values"]["email"] == "ada@example.com"  # untouched
    assert r.json()["updated_at"] > ada["updated_at"]

    # a null clears; identity columns follow
    r = client.patch(path, json={"values": {"phone": None, "email": "ADA@work.example"}}, headers={H: ws})
    assert "phone" not in r.json()["values"] and r.json()["values"]["email"] == "ada@work.example"
    stored = row(db, ada["id"])
    assert (stored["email_norm"], stored["phone_e164"]) == ("ada@work.example", None)

    # nothing changed: no new version, no event
    before = events_of(db, ada["id"])
    same = client.patch(path, json={"values": {"lifecycle": "customer", "last_name": "Lovelace"}}, headers={H: ws})
    assert same.status_code == 200 and same.json()["updated_at"] == r.json()["updated_at"]
    assert client.patch(path, json={}, headers={H: ws}).status_code == 200
    assert events_of(db, ada["id"]) == before

    # owner: set, change, unassign; only people of the workspace
    assert client.patch(path, json={"owner_id": me}, headers={H: ws}).json()["owner_id"] == me
    assert row(db, ada["id"])["owner_id"] == uuid.UUID(me)
    assert client.patch(path, json={"owner_id": None}, headers={H: ws}).json()["owner_id"] is None
    assert client.patch(path, json={"owner_id": str(uuid.uuid4())}, headers={H: ws}).json()["error"]["fields"] == {
        "owner_id": "is not a member of this workspace"}

    # a required field cannot be cleared, and the name cannot be emptied
    company = make_record(client, ws, "company", name="Acme")
    r = client.patch(f"{OBJECTS}/company/records/{company['id']}", json={"values": {"name": None}}, headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"values.name": "Name is required"}
    bare = make_record(client, ws, email="solo@example.com")
    r = client.patch(f"{R}/{bare['id']}", json={"values": {"email": None}}, headers={H: ws})
    assert r.status_code == 422 and "needs a name" in r.json()["error"]["fields"]["values"]
    assert client.patch(f"{R}/{uuid.uuid4()}", json={}, headers={H: ws}).status_code == 404
    assert client.patch(f"{R}/{company['id']}", json={}, headers={H: ws}).status_code == 404  # another object's record


def test_record_events_carry_the_new_state_and_the_changes(crm, db):
    client, ws, _ = crm
    me = client.get("/api/me").json()["user"]["id"]
    ada = make_record(client, ws, first_name="Ada", lifecycle="lead")
    path = f"{R}/{ada['id']}"
    client.patch(path, json={"values": {"lifecycle": "customer", "last_name": "L", "first_name": None},
                             "owner_id": me}, headers={H: ws})
    client.delete(path, headers={H: ws})
    client.post(f"{path}/restore", headers={H: ws})
    created, updated, deleted, restored = events_of(db, ada["id"])
    assert created == ("record.created", {"id": ada["id"], "object": "contact", "display_name": "Ada",
                                          "values": {"first_name": "Ada", "lifecycle": "lead"}, "owner_id": None})
    assert updated[0] == "record.updated" and updated[1]["display_name"] == "L"
    assert updated[1]["values"] == {"last_name": "L", "lifecycle": "customer"} and updated[1]["owner_id"] == me
    assert updated[1]["changes"] == {"lifecycle": {"old": "lead", "new": "customer"},
                                     "last_name": {"old": None, "new": "L"},
                                     "first_name": {"old": "Ada", "new": None},
                                     "owner_id": {"old": None, "new": me}}
    assert deleted == ("record.deleted", {"id": ada["id"], "object": "contact", "display_name": "L"})
    assert restored == ("record.restored", {"id": ada["id"], "object": "contact", "display_name": "L"})
    actors = db.execute(text("SELECT DISTINCT actor_type, actor_id::text FROM events WHERE subject_id = :i"),
                        {"i": ada["id"]}).all()
    assert actors == [("user", me)]
    # a failed request leaves no event behind
    count = db.scalar(text("SELECT count(*) FROM events"))
    assert client.post(R, json={"values": {"email": "bad"}}, headers={H: ws}).status_code == 422
    assert db.scalar(text("SELECT count(*) FROM events")) == count


def test_a_record_event_reaches_a_subscribed_webhook(crm, receiver):
    client, ws, _ = crm
    hook = client.post("/api/v1/webhooks", json={"url": receiver.url(), "event_types": ["record.created",
                                                                                          "record.updated"]},
                       headers={H: ws}).json()
    ada = make_record(client, ws, first_name="Ada", email="ada@example.com")
    client.patch(f"{R}/{ada['id']}", json={"values": {"lifecycle": "lead"}}, headers={H: ws})
    client.delete(f"{R}/{ada['id']}", headers={H: ws})  # not subscribed to record.deleted
    drain()
    requests = sorted(receiver.requests, key=lambda r: json.loads(r["body"])["id"])  # deliveries are not ordered
    seen = [json.loads(r["body"]) for r in requests]
    assert [s["type"] for s in seen] == ["record.created", "record.updated"]
    assert seen[0]["subject"] == {"type": "record", "id": ada["id"]}
    assert seen[0]["data"]["values"] == {"first_name": "Ada", "email": "ada@example.com"}
    assert seen[1]["data"]["changes"] == {"lifecycle": {"old": None, "new": "lead"}}
    assert verify_signature(hook["secret"], requests[0]["headers"]["gohigh-signature"], requests[0]["body"])


def test_record_links_and_owners_must_exist_in_this_workspace(crm, make_user, db):
    client, ws, ids = crm
    acme = make_record(client, ws, "company", name="Acme")
    ada = make_record(client, ws, first_name="Ada", company=acme["id"])
    assert ada["values"]["company"] == acme["id"]
    other, other_ids = make_user("b@example.com")
    other_ws = other_ids["workspace_id"]
    foreign_company = make_record(other, other_ws, "company", name="Foreign")
    foreign_user = other.get("/api/me").json()["user"]["id"]
    deleted = make_record(client, ws, "company", name="Gone")
    client.delete(f"{OBJECTS}/company/records/{deleted['id']}", headers={H: ws})
    for company in (foreign_company["id"], str(uuid.uuid4()), deleted["id"], ada["id"]):  # the last: a contact
        r = client.post(R, json={"values": {"first_name": "X", "company": company}}, headers={H: ws})
        assert r.status_code == 422 and r.json()["error"]["fields"] == {"values.company": "is not a company record"}
    r = client.post(R, json={"values": {"first_name": "X"}, "owner_id": foreign_user}, headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"owner_id": "is not a member of this workspace"}
    # people of the workspace: members, and the admins of its organization
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    stranger = add_member(db, ids["org_id"], "s@example.com")  # org member without access to this workspace
    admin = add_member(db, ids["org_id"], "ad@example.com", org_role="admin")
    for who, ok in ((member, True), (admin, True), (stranger, False)):
        user_id = who.get("/api/me").json()["user"]["id"]
        r = client.post(R, json={"values": {"first_name": "Y"}, "owner_id": user_id}, headers={H: ws})
        assert (r.status_code == 201) is ok, who


def test_deleting_moves_a_record_to_the_trash_until_it_is_restored(crm, db):
    client, ws, _ = crm
    ada, grace = make_record(client, ws, first_name="Ada"), make_record(client, ws, first_name="Grace")
    path = f"{R}/{ada['id']}"
    assert client.delete(path, headers={H: ws}).status_code == 204
    assert get(client, ws, path).status_code == 404
    assert names(listing(client, ws)) == ["Grace"]
    assert client.delete(path, headers={H: ws}).status_code == 404
    assert client.patch(path, json={}, headers={H: ws}).status_code == 404
    assert client.post(f"{R}/{grace['id']}/restore", headers={H: ws}).status_code == 404  # not in the trash

    trash = get(client, ws, "/api/v1/trash", object="contact").json()
    assert [r["id"] for r in trash["data"]] == [ada["id"]] and trash["next_cursor"] is None
    assert trash["data"][0]["deleted_at"] is not None and trash["data"][0]["display_name"] == "Ada"
    assert trash["data"][0]["restorable_until"] > trash["data"][0]["deleted_at"]
    assert get(client, ws, "/api/v1/trash", object="company").json()["data"] == []
    assert get(client, ws, "/api/v1/trash", object="nothing").status_code == 404
    assert get(client, ws, "/api/v1/trash").status_code == 422
    assert db.scalar(text("SELECT count(*) FROM records")) == 2  # kept, only hidden

    restored = client.post(f"{path}/restore", headers={H: ws})
    assert restored.status_code == 200 and restored.json()["deleted_at"] is None
    assert sorted(names(listing(client, ws))) == ["Ada", "Grace"]
    assert get(client, ws, "/api/v1/trash", object="contact").json()["data"] == []
    for key in ("a", "b", "c"):  # the trash pages by deletion time
        client.delete(f"{R}/{make_record(client, ws, first_name=key)['id']}", headers={H: ws})
    first = get(client, ws, "/api/v1/trash", object="contact", limit=2).json()
    rest = get(client, ws, "/api/v1/trash", object="contact", cursor=first["next_cursor"]).json()
    assert [r["display_name"] for r in first["data"] + rest["data"]] == ["c", "b", "a"] and rest["next_cursor"] is None


def test_a_create_with_an_idempotency_key_runs_once(crm, db):
    client, ws, _ = crm
    body = {"values": {"first_name": "Ada"}}
    one = client.post(R, json=body, headers={H: ws, "Idempotency-Key": "k1"})
    two = client.post(R, json=body, headers={H: ws, "Idempotency-Key": "k1"})
    assert one.status_code == two.status_code == 201 and one.json() == two.json()
    assert two.headers["Idempotent-Replayed"] == "true"
    assert db.scalar(text("SELECT count(*) FROM records")) == 1
    clash = client.post(R, json={"values": {"first_name": "Grace"}}, headers={H: ws, "Idempotency-Key": "k1"})
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "idempotency_key_reused"


def test_custom_objects_have_no_cap_and_work_like_the_built_in_ones(crm):
    client, ws, _ = crm
    for n in range(15):  # the incumbent stops at 10
        r = client.post(OBJECTS, json={"key": f"thing_{n}", "singular": f"Thing {n}", "plural": f"Things {n}"},
                        headers={H: ws})
        assert r.status_code == 201, r.text
    assert len(get(client, ws, OBJECTS, limit=200).json()["data"]) == 18
    made = client.post(OBJECTS, json={"key": "property", "singular": "Property", "plural": "Properties",
                                      "icon": "home"}, headers={H: ws}).json()
    assert made["primary_fields"] == ["name"] and made["is_system"] is False and made["icon"] == "home"
    fields = get(client, ws, f"{OBJECTS}/property/fields").json()["data"]
    assert [(f["key"], f["type"], f["rules"]) for f in fields] == [("name", "text", {"required": True})]
    home = make_record(client, ws, "property", name="12 Elm Street")
    assert home["display_name"] == "12 Elm Street" and home["object"] == "property"
    assert names(listing(client, ws, "property")) == ["12 Elm Street"]
    assert listing(client, ws, "thing_3")["data"] == []  # each object has its own records
    assert client.post(f"{OBJECTS}/property/records", json={"values": {}}, headers={H: ws}).status_code == 422

    for body, field in [({"key": "property", "singular": "P", "plural": "P"}, None),  # taken: 409
                        ({"key": "Bad Key", "singular": "P", "plural": "P"}, "key"),
                        ({"key": "tags", "singular": "P", "plural": "P"}, "key"),
                        ({"key": "x", "singular": "", "plural": "P"}, "singular"),
                        ({"key": "x", "singular": "P", "plural": "P", "icon": "Bad Icon!"}, "icon")]:
        r = client.post(OBJECTS, json=body, headers={H: ws})
        assert r.status_code == (409 if field is None else 422), body
        assert field is None or field in r.json()["error"]["fields"]


def test_an_object_is_renamed_re_named_by_other_fields_and_archived(crm):
    client, ws, _ = crm
    client.post(OBJECTS, json={"key": "property", "singular": "Property", "plural": "Properties"}, headers={H: ws})
    client.post(f"{OBJECTS}/property/fields", json={"key": "address", "label": "Address", "type": "text"},
                headers={H: ws})
    home = make_record(client, ws, "property", name="12 Elm", address="Elm St")
    assert home["display_name"] == "12 Elm"
    r = client.patch(f"{OBJECTS}/property", json={"singular": "Listing", "plural": "Listings", "icon": "key"},
                     headers={H: ws})
    assert (r.json()["singular"], r.json()["plural"], r.json()["icon"]) == ("Listing", "Listings", "key")
    assert r.json()["key"] == "property"  # keys never change
    for bad in (["nope"], ["created_at"], []):
        r = client.patch(f"{OBJECTS}/property", json={"primary_fields": bad}, headers={H: ws})
        assert r.status_code == 422 and "primary_fields" in r.json()["error"]["fields"]
    client.post(f"{OBJECTS}/property/fields", json={"key": "price", "label": "Price", "type": "money"}, headers={H: ws})
    assert client.patch(f"{OBJECTS}/property", json={"primary_fields": ["price"]}, headers={H: ws}).status_code == 422
    assert client.patch(f"{OBJECTS}/property", json={"singular": None}, headers={H: ws}).status_code == 422
    stamp = get(client, ws, f"{OBJECTS}/property/records/{home['id']}").json()["updated_at"]
    assert client.patch(f"{OBJECTS}/property", json={"primary_fields": ["address", "name"]},
                        headers={H: ws}).json()["primary_fields"] == ["address", "name"]
    renamed = get(client, ws, f"{OBJECTS}/property/records/{home['id']}").json()  # every record follows at once
    assert renamed["display_name"] == "Elm St 12 Elm" and renamed["updated_at"] == stamp
    assert names(listing(client, ws, "property", q="elm st")) == ["Elm St 12 Elm"]
    bare = make_record(client, ws, "property", name="9 Oak")
    assert bare["display_name"] == "9 Oak"
    client.patch(f"{OBJECTS}/property", json={"primary_fields": ["address"]}, headers={H: ws})
    assert get(client, ws, f"{OBJECTS}/property/records/{bare['id']}").json()["display_name"] == "9 Oak"  # kept

    assert client.delete(f"{OBJECTS}/contact", headers={H: ws}).status_code == 409  # built in
    assert client.patch(f"{OBJECTS}/contact", json={"archived": True}, headers={H: ws}).status_code == 409
    assert client.delete(f"{OBJECTS}/property", headers={H: ws}).status_code == 204
    assert get(client, ws, f"{OBJECTS}/property").status_code == 404
    assert client.post(f"{OBJECTS}/property/records", json={"values": {"name": "x"}},
                       headers={H: ws}).status_code == 404
    assert get(client, ws, f"{OBJECTS}/property/records/{home['id']}").status_code == 404
    assert "property" not in {o["key"] for o in get(client, ws, OBJECTS).json()["data"]}
    assert [o["key"] for o in get(client, ws, OBJECTS, archived="true").json()["data"]] == ["property"]
    assert client.patch(f"{OBJECTS}/property", json={"singular": "x"}, headers={H: ws}).status_code == 404
    assert client.post(OBJECTS, json={"key": "property", "singular": "P", "plural": "P"},
                       headers={H: ws}).status_code == 409  # the key stays taken
    back = client.patch(f"{OBJECTS}/property", json={"archived": False}, headers={H: ws})
    assert back.status_code == 200 and back.json()["archived_at"] is None
    assert get(client, ws, f"{OBJECTS}/property/records/{home['id']}").json()["display_name"] == "Elm St"


def test_fields_are_added_changed_and_archived_without_losing_values(crm, db):
    client, ws, _ = crm
    fields = f"{OBJECTS}/contact/fields"
    made = client.post(fields, json={"key": "score", "label": "Score", "type": "number",
                                     "rules": {"min": 0, "max": 100, "integer": True}}, headers={H: ws})
    assert made.status_code == 201 and made.json()["position"] == 6  # after the six built in
    assert made.json()["options"] == {} and made.json()["is_system"] is False
    ada = make_record(client, ws, first_name="Ada", score=90)
    assert client.post(R, json={"values": {"first_name": "B", "score": 101}}, headers={H: ws}).status_code == 422

    r = client.patch(f"{fields}/score", json={"label": "Lead score", "rules": {"min": 0, "max": 200}, "position": 99},
                     headers={H: ws})
    assert (r.json()["label"], r.json()["rules"], r.json()["position"]) == ("Lead score", {"min": 0, "max": 200}, 99)
    assert r.json()["key"] == "score" and r.json()["type"] == "number"
    assert client.patch(f"{fields}/last_name", json={"position": 98}, headers={H: ws}).status_code == 200
    assert [f["key"] for f in get(client, ws, fields).json()["data"]][-2:] == ["last_name", "score"]  # by position
    assert make_record(client, ws, first_name="C", score=150)["values"]["score"] == 150  # the new rule applies

    # choices can be renamed and added; ids stay
    r = client.patch(f"{fields}/lifecycle", json={"options": {"choices": [
        {"id": "lead", "label": "New lead"}, {"id": "customer", "label": "Customer"}, {"label": "Partner"}]}},
        headers={H: ws})
    assert [c["id"] for c in r.json()["options"]["choices"]] == ["lead", "customer", "partner"]
    assert make_record(client, ws, first_name="P", lifecycle="partner")["values"]["lifecycle"] == "partner"

    # archiving hides the field and keeps what is stored
    assert client.delete(f"{fields}/score", headers={H: ws}).status_code == 204
    assert "score" not in {f["key"] for f in get(client, ws, fields).json()["data"]}
    assert [f["key"] for f in get(client, ws, fields, archived="true").json()["data"]] == ["score"]
    assert "score" not in get(client, ws, f"{R}/{ada['id']}").json()["values"]
    assert "score" not in {f["key"] for f in get(client, ws, f"{OBJECTS}/contact").json()["fields"]}
    assert db.scalar(text("SELECT values->'score' FROM records WHERE id = :i"), {"i": ada["id"]}) == 90
    assert client.post(R, json={"values": {"first_name": "D", "score": 5}}, headers={H: ws}).status_code == 422
    assert client.patch(f"{R}/{ada['id']}", json={"values": {"last_name": "L"}}, headers={H: ws}).status_code == 200
    assert db.scalar(text("SELECT values->'score' FROM records WHERE id = :i"), {"i": ada["id"]}) == 90  # still kept
    back = client.patch(f"{fields}/score", json={"archived": False}, headers={H: ws})
    assert back.status_code == 200 and back.json()["archived_at"] is None
    assert get(client, ws, f"{R}/{ada['id']}").json()["values"]["score"] == 90

    # what cannot be done
    assert client.delete(f"{fields}/email", headers={H: ws}).status_code == 409  # built in
    assert client.delete(f"{fields}/first_name", headers={H: ws}).status_code == 409
    assert client.patch(f"{fields}/nothing", json={}, headers={H: ws}).status_code == 404
    assert client.patch(f"{fields}/score", json={"label": None}, headers={H: ws}).status_code == 422


def test_a_field_is_created_with_checked_options_rules_and_a_unique_key(crm, monkeypatch):
    client, ws, _ = crm
    fields = f"{OBJECTS}/contact/fields"

    def make(**body):
        return client.post(fields, json={"label": "L", **body}, headers={H: ws})

    for body, field in [({"key": "email", "type": "text"}, None),  # taken
                        ({"key": "id", "type": "text"}, "key"), ({"key": "display_name", "type": "text"}, "key"),
                        ({"key": "Bad-Key", "type": "text"}, "key"), ({"key": "x", "type": "file"}, "type"),
                        ({"key": "x", "type": "select", "options": {"choices": "a"}}, "options"),
                        ({"key": "x", "type": "money", "options": {"currency": "QQQ"}}, "options"),
                        ({"key": "x", "type": "record", "options": {"object": "nothing"}}, "options"),
                        ({"key": "x", "type": "record"}, "options"),
                        ({"key": "x", "type": "text", "options": {"choices": []}}, "options"),
                        ({"key": "x", "type": "text", "rules": {"min": 1}}, "rules"),
                        ({"key": "x", "type": "number", "rules": {"required": "yes"}}, "rules")]:
        r = make(**body)
        assert r.status_code == (409 if field is None else 422), (body, r.text)
        assert field is None or field in r.json()["error"]["fields"], body
    assert make(key="owner", type="user").status_code == 201
    assert make(key="parent", type="record", options={"object": "contact"}).status_code == 201
    assert make(key="calc", type="formula", options={"expression": "1 + 1"}).status_code == 201
    # a computed field cannot be written, and is listed
    r = client.post(R, json={"values": {"first_name": "A", "calc": 2}}, headers={H: ws})
    assert r.json()["error"]["fields"] == {"values.calc": "L is computed and read-only"}
    monkeypatch.setattr(objects, "MAX_FIELDS", 10)
    assert make(key="extra1", type="text").status_code == 201
    assert make(key="extra2", type="text").status_code == 409  # the ceiling


def test_only_workspace_admins_change_the_schema_but_members_work_with_records(crm, db):
    client, ws, ids = crm
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    for method, path, body in [("POST", OBJECTS, {"key": "x", "singular": "X", "plural": "Xs"}),
                               ("PATCH", f"{OBJECTS}/contact", {"icon": "x"}),
                               ("DELETE", f"{OBJECTS}/contact", None),
                               ("POST", f"{OBJECTS}/contact/fields", {"key": "x", "label": "X", "type": "text"}),
                               ("PATCH", f"{OBJECTS}/contact/fields/email", {"label": "X"}),
                               ("DELETE", f"{OBJECTS}/contact/fields/email", None),
                               ("POST", "/api/v1/association-types", {"from_object": "contact", "to_object": "deal",
                                                                      "label": "a", "inverse_label": "b"})]:
        r = member.request(method, path, json=body, headers={H: ws})
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden", (method, path)
    assert get(member, ws, OBJECTS).status_code == 200
    assert get(member, ws, f"{OBJECTS}/contact/fields").status_code == 200
    ada = make_record(member, ws, first_name="Ada")  # records are for everyone in the workspace
    assert member.patch(f"{R}/{ada['id']}", json={"values": {"last_name": "L"}}, headers={H: ws}).status_code == 200
    assert member.delete(f"{R}/{ada['id']}", headers={H: ws}).status_code == 204


def test_get_one_record_can_expand_tags_and_unknown_expansions_are_refused(crm):
    client, ws, _ = crm
    ada = make_record(client, ws, first_name="Ada")
    one = get(client, ws, f"{R}/{ada['id']}", include="tags").json()
    assert one["tags"] == [] and one["display_name"] == "Ada"
    client.post(OBJECTS, json={"key": "property", "singular": "Property", "plural": "Properties"}, headers={H: ws})
    for bad in ("nothing", "property", "tags,nothing"):  # no such object, an object it has no association with
        r = get(client, ws, f"{R}/{ada['id']}", include=bad)
        assert r.status_code == 400 and "include" in r.json()["error"]["fields"], bad


def test_seed_is_one_function_for_sign_up_new_workspaces_and_the_migration():
    assert set(seed.SYSTEM_OBJECTS) == {"contact", "company", "deal"}
    assert config.DEFAULT_PHONE_REGION == "US"
    for key, (_, _, _, primary, fields) in seed.SYSTEM_OBJECTS.items():
        assert set(primary) <= {f[0] for f in fields}, key
