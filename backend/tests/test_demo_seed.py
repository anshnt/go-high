"""The development seed: a fictional CRM written through the same store functions as the API."""
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from helpers import H, listing
from sqlalchemy import text

from app.records import demo_seed

SMALL = {"contacts": 60, "companies": 12, "deals": 10}


def shape(db, workspace_id) -> list[str]:
    """The records as content, without ids: the company a contact links to is told by its name."""
    rows = db.execute(text(
        "SELECT o.key, r.display_name, r.email_norm, r.phone_e164, r.owner_id IS NOT NULL AS owned, "
        "r.values - 'company' AS rest, "
        "(SELECT c.display_name FROM records c WHERE c.id::text = r.values ->> 'company') AS company "
        "FROM records r JOIN objects o ON o.id = r.object_id WHERE r.workspace_id = :w"),
        {"w": workspace_id}).all()
    return sorted(json.dumps([*r], default=str, sort_keys=True) for r in rows)


def test_the_seed_fills_a_workspace_through_the_real_write_path(crm, db):
    client, ws, _ = crm
    done = demo_seed.seed(db, ws, **SMALL)
    assert done == {**SMALL, "tags": 8}
    page = lambda key: listing(client, ws, key, count="true", limit=200, include="tags")  # noqa: E731
    contacts, companies, deals = page("contact"), page("company"), page("deal")
    assert (contacts["total"], companies["total"], deals["total"]) == (60, 12, 10)
    ada = contacts["data"][0]
    assert ada["values"]["first_name"] and ada["display_name"].startswith(ada["values"]["first_name"])
    stages = {"lead", "qualified", "customer", "churned", "other"}
    assert all(r["values"]["lifecycle"] in stages for r in contacts["data"])
    # a contact with a company works at it: the field and the association agree, and the company lists it
    linked = [r for r in contacts["data"] if "company" in r["values"]]
    assert 20 < len(linked) < 60
    works_at = db.scalar(text("SELECT count(*) FROM associations a JOIN association_types t ON t.id = a.type_id "
                              "WHERE t.label = 'works at'"))
    assert works_at == len(linked)
    one = client.get(f"/api/v1/records/{linked[0]['id']}/associations", headers={H: ws}).json()["data"]
    assert [m["label"] for m in one if m["record"]["object"] == "company"] == ["works at"]
    # deals are linked to a contact and a company through associations, and carry money and a stage
    assert all(d["values"]["amount"]["amount"] > 0 and d["values"]["stage"] for d in deals["data"])
    with_links = client.get("/api/v1/objects/deal/records", params={"include": "contact,company", "limit": 200},
                            headers={H: ws}).json()["data"]
    assert sum(1 for d in with_links if d["associations"]["contact"]) >= 5 and any(
        d["associations"]["company"] for d in with_links)
    # tags exist with usage, and the people who can own records are the signed-up user and the fictional team
    tags = client.get("/api/v1/tags", headers={H: ws}).json()["data"]
    assert [t["name"] for t in tags if t["count"]] and len(tags) == 8 and {t["color"] for t in tags} <= {
        "purple", "blue", "teal", "amber", "red", "green", "orange", "gray"}
    members = client.get("/api/v1/members", headers={H: ws}).json()["data"]
    assert sorted(m["name"] for m in members) == ["Diego Salazar", "Maya Okafor", "Priya Raman", "Theo Lindqvist", "a"]
    owners = {r["owner_id"] for r in contacts["data"]} - {None}
    assert owners <= {m["id"] for m in members} and len(owners) > 2
    # records are dated back, and the events of their creation with them, but some are recent
    ages = [datetime.fromisoformat(r["created_at"]) for r in contacts["data"]]
    now = datetime.now(UTC)
    assert min(ages) < now - timedelta(days=90) and any(a > now - timedelta(days=30) for a in ages)
    assert all(datetime.fromisoformat(r["updated_at"]) >= datetime.fromisoformat(r["created_at"])
               for r in contacts["data"])
    events = client.get(f"/api/v1/records/{ada['id']}/timeline", headers={H: ws}).json()["data"]
    created = [e for e in events if e["type"] == "record.created"]
    assert len(created) == 1 and datetime.fromisoformat(created[0]["occurred_at"]) == datetime.fromisoformat(
        ada["created_at"])
    assert db.scalar(text("SELECT count(*) FROM events WHERE type = 'record.created'")) == 82


def test_the_same_seed_makes_the_same_crm_and_refuses_a_workspace_that_has_one(crm, make_user, db):
    _, ws, _ = crm
    _, other = make_user("zed@example.com")
    for workspace in (ws, other["workspace_id"]):
        demo_seed.seed(db, workspace, **SMALL)
    first, second = shape(db, ws), shape(db, other["workspace_id"])
    assert len(first) == 82 and first == second
    with pytest.raises(SystemExit, match="records already"):
        demo_seed.seed(db, ws, **SMALL)
    with pytest.raises(SystemExit, match="no workspace"):
        demo_seed.seed(db, "00000000-0000-4000-8000-000000000000", **SMALL)


def test_the_command_line_seeds_a_workspace(crm, capsys):
    client, ws, _ = crm
    demo_seed.main([ws, "--contacts", "7", "--companies", "3", "--deals", "2"])
    assert capsys.readouterr().out.strip() == "Seeded: 3 companies, 7 contacts, 2 deals, 8 tags"
    assert listing(client, ws, count="true")["total"] == 7


def test_the_default_seed_is_a_thousand_contacts_and_it_is_quick(crm, db):
    client, ws, _ = crm
    start = time.monotonic()
    done = demo_seed.seed(db, ws)
    took = time.monotonic() - start
    assert done == {"companies": 150, "contacts": 1000, "deals": 80, "tags": 8} and took < 60, took
    assert listing(client, ws, count="true", limit=1)["total"] == 1000
    assert listing(client, ws, "company", count="true", limit=1)["total"] == 150
    # the shape the screens depend on: customers made in the last 30 days exist
    recent = {"and": [{"field": "lifecycle", "op": "is", "value": "customer"},
                      {"field": "created_at", "op": "within_last", "value": {"days": 30}}]}
    assert listing(client, ws, count="true", filter=json.dumps(recent))["total"] > 5
