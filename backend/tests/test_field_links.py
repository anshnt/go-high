"""A contact's `company` field and the "works at" association stay in step, in the same transaction as the write."""
import json

from helpers import H, link, listing, make_record, names, type_id
from sqlalchemy import text

OBJECTS = "/api/v1/objects"
R = f"{OBJECTS}/contact/records"


def links(client, ws, record_id) -> list[tuple[str, str, str]]:
    r = client.get(f"/api/v1/records/{record_id}/associations", params={"limit": 200}, headers={H: ws})
    assert r.status_code == 200, r.text
    return sorted((m["label"], m["direction"], m["record"]["display_name"]) for m in r.json()["data"])


def timeline(client, ws, record_id) -> list[str]:
    r = client.get(f"/api/v1/records/{record_id}/timeline", params={"limit": 200}, headers={H: ws})
    return [e["type"] for e in r.json()["data"]]


def patch(client, ws, record_id, **values):
    r = client.patch(f"{R}/{record_id}", json={"values": values}, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def count(db, kind) -> int:
    db.expire_all()
    return db.scalar(text("SELECT count(*) FROM events WHERE type = :t"), {"t": kind})


def test_a_contact_made_with_a_company_works_at_it_and_both_timelines_say_so(crm, db):
    client, ws, _ = crm
    acme = make_record(client, ws, "company", name="Acme")
    ada = make_record(client, ws, first_name="Ada", company=acme["id"])
    assert links(client, ws, ada["id"]) == [("works at", "forward", "Acme")]
    assert links(client, ws, acme["id"]) == [("employs", "inverse", "Ada")]
    assert timeline(client, ws, ada["id"]) == ["association.created", "record.created"]
    assert timeline(client, ws, acme["id"]) == ["association.created", "record.created"]
    assert count(db, "association.created") == 1
    # the association is the system "works at" type, from the contact to the company
    row = db.execute(text("SELECT t.label, a.from_record_id, a.to_record_id FROM associations a "
                          "JOIN association_types t ON t.id = a.type_id")).one()
    assert (row.label, str(row.from_record_id), str(row.to_record_id)) == ("works at", ada["id"], acme["id"])


def test_moving_or_clearing_the_company_moves_or_removes_the_link(crm, db):
    client, ws, _ = crm
    acme, bolt = (make_record(client, ws, "company", name=n) for n in ("Acme", "Bolt"))
    ada = make_record(client, ws, first_name="Ada", company=acme["id"])
    patch(client, ws, ada["id"], company=bolt["id"])
    assert links(client, ws, ada["id"]) == [("works at", "forward", "Bolt")]
    assert links(client, ws, acme["id"]) == [] and links(client, ws, bolt["id"]) == [("employs", "inverse", "Ada")]
    assert timeline(client, ws, acme["id"])[:2] == ["association.deleted", "association.created"]  # it shows there too
    assert (count(db, "association.created"), count(db, "association.deleted")) == (2, 1)
    patch(client, ws, ada["id"], company=None)
    assert links(client, ws, ada["id"]) == [] and "company" not in listing(client, ws)["data"][0]["values"]
    assert (count(db, "association.created"), count(db, "association.deleted")) == (2, 2)
    patch(client, ws, ada["id"], company=acme["id"])
    assert links(client, ws, ada["id"]) == [("works at", "forward", "Acme")]


def test_an_existing_link_is_kept_not_repeated_and_other_changes_leave_links_alone(crm, db):
    client, ws, _ = crm
    works_at = type_id(client, ws, "contact", "company")
    acme, bolt, cask = (make_record(client, ws, "company", name=n) for n in ("Acme", "Bolt", "Cask"))
    ada = make_record(client, ws, first_name="Ada")
    link(client, ws, ada["id"], acme["id"], works_at)  # made by hand, the field is empty
    link(client, ws, ada["id"], cask["id"], works_at)  # a second employer, also by hand
    patch(client, ws, ada["id"], company=acme["id"])  # the same company: nothing new to add
    assert links(client, ws, ada["id"]) == [("works at", "forward", "Acme"), ("works at", "forward", "Cask")]
    assert count(db, "association.created") == 2
    patch(client, ws, ada["id"], last_name="Lovelace", lifecycle="lead")  # unrelated fields
    assert count(db, "association.created") == 2 and count(db, "association.deleted") == 0
    patch(client, ws, ada["id"], company=bolt["id"])  # moves the field's company; the hand made Cask link stays
    assert links(client, ws, ada["id"]) == [("works at", "forward", "Bolt"), ("works at", "forward", "Cask")]
    # a patch that changes nothing is no write at all
    patch(client, ws, ada["id"], company=bolt["id"])
    assert count(db, "association.created") == 3 and count(db, "association.deleted") == 1


def test_only_a_record_field_named_like_its_object_is_followed(crm):
    client, ws, _ = crm
    client.post(f"{OBJECTS}/contact/fields", json={"key": "former_employer", "label": "Former employer",
                                                    "type": "record", "options": {"object": "company"}},
                headers={H: ws})
    client.post(f"{OBJECTS}/deal/fields", json={"key": "company", "label": "Company", "type": "record",
                                                "options": {"object": "company"}}, headers={H: ws})
    acme = make_record(client, ws, "company", name="Acme")
    ada = make_record(client, ws, first_name="Ada", former_employer=acme["id"])
    assert links(client, ws, ada["id"]) == []
    deal = make_record(client, ws, "deal", name="Rollout", company=acme["id"])  # deal to company: its own type
    assert links(client, ws, deal["id"]) == [("company", "forward", "Acme")]
    assert links(client, ws, acme["id"]) == [("deal", "inverse", "Rollout")]


def test_a_company_lists_its_contacts_linked_either_way_once_each(crm, db):
    client, ws, _ = crm
    works_at = type_id(client, ws, "contact", "company")
    acme, bolt = (make_record(client, ws, "company", name=n) for n in ("Acme", "Bolt"))
    both = make_record(client, ws, first_name="Both", company=acme["id"])  # field and association (in step)
    field_only = make_record(client, ws, first_name="Field", company=acme["id"])
    link_only = make_record(client, ws, first_name="Link")
    elsewhere = make_record(client, ws, first_name="Else", company=bolt["id"])
    link(client, ws, link_only["id"], acme["id"], works_at)
    db.execute(text("DELETE FROM associations WHERE from_record_id = :r"), {"r": field_only["id"]})  # data from before
    db.commit()
    either = {"or": [{"field": "company", "op": "is", "value": acme["id"]},
                     {"field": "company.id", "op": "is", "value": acme["id"]}]}
    found = listing(client, ws, filter=json.dumps(either), count="true", sort="display_name")
    assert names(found) == ["Both", "Field", "Link"] and found["total"] == 3
    assert elsewhere["id"] not in {r["id"] for r in found["data"]} and both["id"] in {r["id"] for r in found["data"]}
    # one batch resolves the names behind links, by id
    page = client.get(f"{OBJECTS}/company/records", headers={H: ws}, params={
        "filter": json.dumps({"field": "id", "op": "in", "value": [acme["id"], bolt["id"]]}), "sort": "display_name"})
    assert names(page.json()) == ["Acme", "Bolt"]
