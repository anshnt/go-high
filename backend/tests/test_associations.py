"""Associations between records, their types, and what shows on a record's timeline."""
import json
import uuid

from helpers import H, add_member, link, listing, make_record, names, type_id
from sqlalchemy import text

OBJECTS = "/api/v1/objects"
TYPES = "/api/v1/association-types"


def links(client, ws, record_id, **params) -> dict:
    r = client.get(f"/api/v1/records/{record_id}/associations", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def timeline(client, ws, record_id, **params) -> dict:
    r = client.get(f"/api/v1/records/{record_id}/timeline", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def new_type(client, ws, a, b, label, inverse, cardinality="many_to_many") -> dict:
    r = client.post(TYPES, json={"from_object": a, "to_object": b, "label": label, "inverse_label": inverse,
                                 "cardinality": cardinality}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_custom_object_links_to_contacts_and_deals_and_shows_on_both_timelines(crm):
    client, ws, _ = crm
    assert client.post(OBJECTS, json={"key": "property", "singular": "Property", "plural": "Properties"},
                       headers={H: ws}).status_code == 201
    client.post(f"{OBJECTS}/property/fields", json={"key": "address", "label": "Address", "type": "text"},
                headers={H: ws})
    owns = new_type(client, ws, "contact", "property", "owns", "owned by")
    listed_for = new_type(client, ws, "deal", "property", "for", "deal")
    assert (owns["from_object"], owns["to_object"], owns["cardinality"], owns["is_system"]) == (
        "contact", "property", "many_to_many", False)
    ada = make_record(client, ws, first_name="Ada", last_name="Lovelace")
    deal = make_record(client, ws, "deal", name="Elm Street sale")
    home = make_record(client, ws, "property", name="12 Elm", address="12 Elm Street")
    other_home = make_record(client, ws, "property", name="9 Oak", address="9 Oak Avenue")

    first = link(client, ws, ada["id"], home["id"], owns["id"])
    assert first["label"] == "owns" and first["inverse_label"] == "owned by"
    assert (first["from_record_id"], first["to_record_id"]) == (ada["id"], home["id"])
    link(client, ws, home["id"], deal["id"], listed_for["id"])  # from the property's side: the same link, stored once

    # both directions, with the label as seen from the record asking
    mine = links(client, ws, ada["id"])["data"]
    assert [(m["label"], m["direction"], m["record"]["display_name"], m["record"]["object"]) for m in mine] == [
        ("owns", "forward", "12 Elm", "property")]
    theirs = links(client, ws, home["id"])["data"]
    assert sorted((m["label"], m["direction"], m["record"]["display_name"]) for m in theirs) == [
        ("deal", "inverse", "Elm Street sale"), ("owned by", "inverse", "Ada Lovelace")]
    assert [(m["label"], m["direction"]) for m in links(client, ws, deal["id"])["data"]] == [("for", "forward")]
    assert links(client, ws, other_home["id"])["data"] == []

    # filter across the link, in every direction
    assert names(listing(client, ws, "property", filter=json.dumps(
        {"field": "contact.last_name", "op": "is", "value": "Lovelace"}))) == ["12 Elm"]
    assert names(listing(client, ws, "contact", filter=json.dumps(
        {"field": "property.address", "op": "contains", "value": "elm"}))) == ["Ada Lovelace"]
    assert names(listing(client, ws, "property", filter=json.dumps(
        {"field": "deal.name", "op": "starts_with", "value": "elm"}))) == ["12 Elm"]
    assert names(listing(client, ws, "deal", filter=json.dumps(
        {"field": "property.address", "op": "is", "value": "9 Oak Avenue"}))) == []

    # the link is on the timeline of both ends, and of no other record
    for record, links_made in ((ada, 1), (home, 2), (deal, 1)):
        kinds = [e["type"] for e in timeline(client, ws, record["id"])["data"]]
        assert kinds == ["association.created"] * links_made + ["record.created"], record["object"]
    assert "association.created" not in [e["type"] for e in timeline(client, ws, other_home["id"])["data"]]
    event = timeline(client, ws, ada["id"])["data"][0]
    assert event["type"] == "association.created" and event["subject"] == {"type": "association", "id": first["id"]}
    assert event["data"] == {"id": first["id"], "type_id": owns["id"], "from_record_id": ada["id"],
                             "to_record_id": home["id"], "label": "owns", "inverse_label": "owned by"}

    # expansion in a list
    page = listing(client, ws, "property", include="contact,deal,tags")
    homes = {r["display_name"]: r for r in page["data"]}
    assert [(a["label"], a["record"]["display_name"]) for a in homes["12 Elm"]["associations"]["contact"]] == [
        ("owned by", "Ada Lovelace")]
    assert [(a["label"], a["record"]["display_name"]) for a in homes["12 Elm"]["associations"]["deal"]] == [
        ("deal", "Elm Street sale")]
    assert homes["9 Oak"]["associations"] == {"contact": [], "deal": []} and homes["9 Oak"]["tags"] == []
    ada_page = listing(client, ws, "contact", include="property")["data"][0]
    assert [(a["label"], a["type_id"]) for a in ada_page["associations"]["property"]] == [("owns", owns["id"])]


def test_the_built_in_links_read_both_ways_and_each_pair_links_once(crm, db):
    client, ws, _ = crm
    works_at = type_id(client, ws, "contact", "company")
    ada, grace = make_record(client, ws, first_name="Ada"), make_record(client, ws, first_name="Grace")
    acme = make_record(client, ws, "company", name="Acme")
    link(client, ws, ada["id"], acme["id"], works_at)
    r = client.post(f"/api/v1/records/{acme['id']}/associations", json={"type_id": works_at, "other_id": grace["id"]},
                    headers={H: ws})  # from the company's side: the contact still works at the company
    assert r.status_code == 201 and (r.json()["from_record_id"], r.json()["to_record_id"]) == (grace["id"], acme["id"])
    assert sorted((m["label"], m["direction"], m["record"]["display_name"]) for m in links(client, ws, acme["id"])[
        "data"]) == [("employs", "inverse", "Ada"), ("employs", "inverse", "Grace")]
    for a, b in ((ada, acme), (acme, ada)):  # a second link of the same type and pair, from either side
        r = client.post(f"/api/v1/records/{a['id']}/associations", json={"type_id": works_at, "other_id": b["id"]},
                        headers={H: ws})
        assert r.status_code == 409 and r.json()["error"]["code"] == "already_associated"
    assert db.scalar(text("SELECT count(*) FROM associations")) == 2
    # a contact has many companies: many to many
    link(client, ws, ada["id"], make_record(client, ws, "company", name="Beta")["id"], works_at)
    assert len(links(client, ws, ada["id"])["data"]) == 2


def test_a_bad_link_is_refused(crm, make_user):
    client, ws, _ = crm
    works_at = type_id(client, ws, "contact", "company")
    ada = make_record(client, ws, first_name="Ada")
    acme = make_record(client, ws, "company", name="Acme")
    deal = make_record(client, ws, "deal", name="D")
    other, other_ids = make_user("b@example.com")
    foreign = make_record(other, other_ids["workspace_id"], first_name="Foreign")
    foreign_type = type_id(other, other_ids["workspace_id"], "contact", "company")

    def attempt(record, other_id, type_, status, code=None):
        r = client.post(f"/api/v1/records/{record}/associations", json={"type_id": type_, "other_id": other_id},
                        headers={H: ws})
        assert r.status_code == status, r.text
        assert code is None or r.json()["error"]["code"] == code
        return r

    wrong = attempt(ada["id"], deal["id"], works_at, 422, "validation_failed")  # works at links a contact and a company
    assert "links contact to company, not contact and deal" in wrong.json()["error"]["fields"]["type_id"]
    attempt(ada["id"], acme["id"], str(uuid.uuid4()), 404)
    attempt(ada["id"], str(uuid.uuid4()), works_at, 404)
    attempt(str(uuid.uuid4()), acme["id"], works_at, 404)
    attempt(ada["id"], foreign["id"], works_at, 404)  # another workspace's record
    attempt(ada["id"], acme["id"], foreign_type, 404)  # another workspace's type
    attempt(foreign["id"], acme["id"], works_at, 404)
    attempt(ada["id"], "not-an-id", works_at, 422)
    client.delete(f"{OBJECTS}/company/records/{acme['id']}", headers={H: ws})
    attempt(ada["id"], acme["id"], works_at, 404)  # a record in the trash cannot be linked
    assert links(client, ws, ada["id"])["data"] == []


def test_a_type_between_an_object_and_itself_needs_a_direction_only_to_say_which_end(crm):
    client, ws, _ = crm
    reports = new_type(client, ws, "contact", "contact", "reports to", "manages")
    boss, worker = make_record(client, ws, first_name="Boss"), make_record(client, ws, first_name="Worker")
    r = client.post(f"/api/v1/records/{worker['id']}/associations",
                    json={"type_id": reports["id"], "other_id": boss["id"]}, headers={H: ws})  # worker -> boss
    assert r.status_code == 201 and r.json()["from_record_id"] == worker["id"]
    r = client.post(f"/api/v1/records/{boss['id']}/associations", json={"type_id": reports["id"],
                                                                         "other_id": worker["id"],
                                                                         "direction": "inverse"}, headers={H: ws})
    assert r.status_code == 409  # boss manages worker is the same link
    seen = {who: [(m["label"], m["direction"]) for m in links(client, ws, record["id"])["data"]]
            for who, record in (("worker", worker), ("boss", boss))}
    assert seen == {"worker": [("reports to", "forward")], "boss": [("manages", "inverse")]}
    r = client.post(f"/api/v1/records/{boss['id']}/associations",
                    json={"type_id": reports["id"], "other_id": boss["id"]}, headers={H: ws})
    assert r.status_code == 422 and "other_id" in r.json()["error"]["fields"]  # not with itself
    assert client.post(f"/api/v1/records/{boss['id']}/associations",
                       json={"type_id": reports["id"], "other_id": boss["id"], "direction": "sideways"},
                       headers={H: ws}).status_code == 422
    # a path filter reads a link between an object and itself from both ends
    def reaches(name):
        return names(listing(client, ws, filter=json.dumps({"field": "contact.first_name", "op": "is", "value": name})))

    assert reaches("Boss") == ["Worker"] and reaches("Worker") == ["Boss"]


def test_cardinality_is_enforced(crm):
    client, ws, _ = crm
    one = new_type(client, ws, "contact", "company", "founded", "founded by", "one_to_one")
    many = new_type(client, ws, "company", "contact", "employs", "works for", "one_to_many")
    people = [make_record(client, ws, first_name=n) for n in "abc"]
    firms = [make_record(client, ws, "company", name=n) for n in "XYZ"]

    def attempt(a, b, type_):
        return client.post(f"/api/v1/records/{a['id']}/associations", json={"type_id": type_["id"],
                                                                            "other_id": b["id"]}, headers={H: ws})

    assert attempt(people[0], firms[0], one).status_code == 201
    for a, b in ((people[0], firms[1]), (people[1], firms[0])):  # neither end may be used twice
        r = attempt(a, b, one)
        assert r.status_code == 409 and r.json()["error"]["code"] == "cardinality_violated"
    assert attempt(people[1], firms[1], one).status_code == 201
    # one to many: a company has many contacts, a contact has one such company
    assert attempt(firms[0], people[0], many).status_code == 201
    assert attempt(firms[0], people[1], many).status_code == 201  # the one side may repeat
    r = attempt(firms[1], people[0], many)  # the many side may not
    assert r.status_code == 409 and r.json()["error"]["code"] == "cardinality_violated"
    assert attempt(firms[1], people[2], many).status_code == 201


def test_removing_a_link_emits_an_event_and_the_trash_hides_links_without_losing_them(crm, db):
    client, ws, _ = crm
    works_at = type_id(client, ws, "contact", "company")
    ada, acme = make_record(client, ws, first_name="Ada"), make_record(client, ws, "company", name="Acme")
    made = link(client, ws, ada["id"], acme["id"], works_at)
    client.delete(f"{OBJECTS}/company/records/{acme['id']}", headers={H: ws})
    assert links(client, ws, ada["id"])["data"] == []  # a trashed record is not listed
    assert listing(client, ws, include="company")["data"][0]["associations"]["company"] == []
    client.post(f"{OBJECTS}/company/records/{acme['id']}/restore", headers={H: ws})
    assert [m["id"] for m in links(client, ws, ada["id"])["data"]] == [made["id"]]

    client.delete(f"{OBJECTS}/company/records/{acme['id']}", headers={H: ws})  # an end in the trash: still removable
    assert client.delete(f"/api/v1/associations/{made['id']}", headers={H: ws}).status_code == 204
    assert client.delete(f"/api/v1/associations/{made['id']}", headers={H: ws}).status_code == 404
    assert client.delete(f"/api/v1/associations/{uuid.uuid4()}", headers={H: ws}).status_code == 404
    assert db.scalar(text("SELECT count(*) FROM associations")) == 0
    gone = db.execute(text("SELECT data, subject_id::text FROM events WHERE type = 'association.deleted'")).one()
    assert gone.data["id"] == made["id"] and gone.subject_id == made["id"] and gone.data["label"] == "works at"
    kinds = [e["type"] for e in timeline(client, ws, ada["id"])["data"]]
    assert kinds[0] == "association.deleted" and "association.created" in kinds  # both stay on the timeline
    assert db.scalar(text("SELECT count(*) FROM event_records")) == 4  # two ends, created and deleted


def test_links_page_newest_first(crm):
    client, ws, _ = crm
    works_at = type_id(client, ws, "contact", "company")
    ada = make_record(client, ws, first_name="Ada")
    firms = [make_record(client, ws, "company", name=f"firm {i}") for i in range(5)]
    for firm in firms:
        link(client, ws, ada["id"], firm["id"], works_at)
    first = links(client, ws, ada["id"], limit=2)
    rest = links(client, ws, ada["id"], limit=2, cursor=first["next_cursor"])
    last = links(client, ws, ada["id"], limit=2, cursor=rest["next_cursor"])
    seen = [m["record"]["display_name"] for m in first["data"] + rest["data"] + last["data"]]
    assert seen == [f"firm {i}" for i in (4, 3, 2, 1, 0)] and last["next_cursor"] is None
    assert client.get(f"/api/v1/records/{ada['id']}/associations", params={"cursor": "junk"},
                      headers={H: ws}).status_code == 400
    r = client.get(f"/api/v1/records/{ada['id']}/associations", params={"limit": 0}, headers={H: ws})
    assert r.status_code == 422


def test_association_types_are_listed_created_and_removed_by_admins(crm, db):
    client, ws, ids = crm
    listed = client.get(TYPES, headers={H: ws}).json()["data"]
    assert len(listed) == 3
    assert {(t["from_object"], t["to_object"]) for t in client.get(TYPES, params={"object": "company"},
                                                                    headers={H: ws}).json()["data"]} == {
        ("contact", "company"), ("deal", "company")}
    assert client.get(TYPES, params={"object": "nothing"}, headers={H: ws}).status_code == 404
    made = new_type(client, ws, "company", "company", "parent of", "child of")
    assert len(client.get(TYPES, params={"object": "company"}, headers={H: ws}).json()["data"]) == 3
    for body, status in [({"from_object": "company", "to_object": "company", "label": "parent of",
                           "inverse_label": "x"}, 409),
                         ({"from_object": "nothing", "to_object": "company", "label": "a", "inverse_label": "b"}, 404),
                         ({"from_object": "company", "to_object": "company", "label": "", "inverse_label": "b"}, 422),
                         ({"from_object": "company", "to_object": "company", "label": "a", "inverse_label": "b",
                           "cardinality": "some"}, 422)]:
        assert client.post(TYPES, json=body, headers={H: ws}).status_code == status, body
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    assert member.get(TYPES, headers={H: ws}).status_code == 200
    assert member.delete(f"{TYPES}/{made['id']}", headers={H: ws}).status_code == 403
    builtin = type_id(client, ws, "contact", "company")
    assert client.delete(f"{TYPES}/{builtin}", headers={H: ws}).status_code == 409
    a, b = make_record(client, ws, "company", name="A"), make_record(client, ws, "company", name="B")
    made_link = link(client, ws, a["id"], b["id"], made["id"])
    assert client.delete(f"{TYPES}/{made['id']}", headers={H: ws}).status_code == 409  # still in use
    client.delete(f"/api/v1/associations/{made_link['id']}", headers={H: ws})
    assert client.delete(f"{TYPES}/{made['id']}", headers={H: ws}).status_code == 204
    assert client.delete(f"{TYPES}/{made['id']}", headers={H: ws}).status_code == 404
    assert len(client.get(TYPES, headers={H: ws}).json()["data"]) == 3


def test_a_records_timeline_is_its_events_newest_first_with_a_cursor(crm, db):
    client, ws, _ = crm
    ada = make_record(client, ws, first_name="Ada")
    path = f"{OBJECTS}/contact/records/{ada['id']}"
    for value in ("lead", "customer", "other"):
        client.patch(path, json={"values": {"lifecycle": value}}, headers={H: ws})
    tag = client.post("/api/v1/tags", json={"name": "vip"}, headers={H: ws}).json()
    client.post(f"/api/v1/records/{ada['id']}/tags", json={"add": [tag["id"]]}, headers={H: ws})
    client.delete(path, headers={H: ws})
    bystander = make_record(client, ws, first_name="Bystander")

    full = timeline(client, ws, ada["id"])
    assert [e["type"] for e in full["data"]] == ["record.deleted", "tag.added", "record.updated", "record.updated",
                                                "record.updated", "record.created"]
    assert full["next_cursor"] is None
    assert [e["type"] for e in timeline(client, ws, bystander["id"])["data"]] == ["record.created"]
    newest = full["data"][0]
    me = client.get("/api/me").json()["user"]["id"]
    assert newest["actor"] == {"type": "user", "id": me} and newest["subject"] == {"type": "record", "id": ada["id"]}
    assert newest["data"]["display_name"] == "Ada" and newest["occurred_at"]
    assert [e["id"] for e in full["data"]] == sorted((e["id"] for e in full["data"]), reverse=True)

    seen, cursor = [], None
    for _ in range(4):
        part = timeline(client, ws, ada["id"], limit=2, **({"cursor": cursor} if cursor else {}))
        seen += [e["id"] for e in part["data"]]
        cursor = part["next_cursor"]
        if not cursor:
            break
    assert seen == [e["id"] for e in full["data"]]  # the trashed record's timeline still reads
    for params, status in (({"limit": 0}, 422), ({"limit": 201}, 422), ({"cursor": "junk"}, 400),
                           ({"cursor": client.get(f"/api/v1/records/{ada['id']}/timeline", params={"limit": 1},
                                                  headers={H: ws}).json()["next_cursor"][:-2] + "zz"}, 400)):
        assert client.get(f"/api/v1/records/{ada['id']}/timeline", params=params, headers={H: ws}).status_code == status
    assert client.get(f"/api/v1/records/{uuid.uuid4()}/timeline", headers={H: ws}).status_code == 404
