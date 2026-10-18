"""What a role sees and changes of records (ADR 0004): scope (own, own and unassigned, team with sub-teams, assignee
fields), hidden fields, read-only fields, and the simulator agreeing with all of it."""
import itertools
import json
import re
import uuid
from types import SimpleNamespace

import pytest
from helpers import (
    H,
    add_member,
    audit,
    link,
    listing,
    make_record,
    make_role,
    names,
    rule,
    type_id,
    user_id_of,
    v1_routes,
)

R = "/api/v1/objects/contact/records"
SECRET_EMAIL, SECRET_PHONE = "ada.lovelace@hidden-mail.example", "+14155550100"


def gone(client, ws, path, method="get", **kw):
    r = client.request(method, path, headers={H: ws}, **kw)
    assert r.status_code == 404, (method, path, r.status_code, r.text[:200])


def explain(admin, ws, user_id=None, record_id=None):
    params = {k: v for k, v in (("user_id", user_id), ("record_id", record_id)) if v}
    r = admin.get("/api/v1/permissions/explain", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def world(crm, db):
    """A workspace with an admin, people on three scopes, teams East > East North and West, and records of several
    owners. Contacts: Ada and Alan (Ann's), Bea (Bob's), Una (nobody's). Deals: one each for Cy, Eli, Fay, Gia and
    nobody. Acme the company is linked to Ada and Bea."""
    admin, ws, ids = crm
    org = ids["org_id"]
    rules = {"own": [rule(), rule("contact", "own")],
             "team": [rule(), rule("deal", "team", hidden=["amount"], readonly=["stage"])]}
    make_role(admin, ws, "Own contacts", rules=rules["own"])
    make_role(admin, ws, "Team deals", rules=rules["team"])
    w = SimpleNamespace(admin=admin, ws=ws, ids=ids, org=org, user={}, client={})
    for name, role in (("ann", "own_contacts"), ("bob", "own_contacts"), ("cy", "team_deals"), ("eli", "team_deals"),
                       ("fay", "team_deals"), ("gia", "team_deals"), ("dee", "viewer")):
        w.client[name] = add_member(db, org, f"{name}@example.com", workspace_id=ws, workspace_role=role)
        w.user[name] = user_id_of(w.client[name])
    w.user["admin"], w.client["admin"] = user_id_of(admin), admin

    def team(name, parent=None):
        r = admin.post("/api/v1/teams", json={"name": name, "parent_team_id": parent}, headers={H: ws})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    w.team = {"east": team("East")}
    w.team |= {"north": team("East North", w.team["east"]), "west": team("West")}
    for who, where in (("cy", "east"), ("gia", "east"), ("eli", "north"), ("fay", "west")):
        assert admin.put(f"/api/v1/teams/{w.team[where]}/members/{w.user[who]}", headers={H: ws}).status_code == 200
    contact = {"ada": ("Ada", "Alpha", "ann"), "alan": ("Alan", "Alpha", "ann"), "bea": ("Bea", "Beta", "bob"),
               "una": ("Una", "Unowned", None)}
    w.rec = {k: make_record(admin, ws, first_name=f, last_name=last, email=f"{f.lower()}@{last.lower()}.example",
                            owner_id=w.user[o] if o else None) for k, (f, last, o) in contact.items()}
    w.rec |= {f"deal_{k}": make_record(admin, ws, "deal", name=f"Deal of {k}", owner_id=w.user[k] if k != "none"
                                       else None, amount={"amount": 1500000, "currency": "USD"})
              for k in ("cy", "eli", "fay", "gia", "none")}
    w.rec["acme"] = make_record(admin, ws, "company", name="Acme")
    w.link = type_id(admin, ws, "contact", "company")
    w.links = {k: link(admin, ws, w.rec[k]["id"], w.rec["acme"]["id"], w.link)["id"] for k in ("ada", "bea")}
    return w


def test_scope_own_shows_a_member_only_their_records_in_lists_counts_and_search(world):
    w = world
    ann, bob, ws = w.client["ann"], w.client["bob"], w.ws
    assert sorted(names(listing(ann, ws))) == ["Ada Alpha", "Alan Alpha"]
    assert names(listing(bob, ws)) == ["Bea Beta"]
    assert len(listing(w.admin, ws)["data"]) == 4  # Una, who has no owner, is for nobody on this scope
    assert listing(ann, ws, count="true")["total"] == 2 and listing(bob, ws, count="true")["total"] == 1
    assert listing(w.admin, ws, count="true")["total"] == 4
    assert listing(ann, ws, q="alpha")["data"] and names(listing(ann, ws, q="beta")) == []
    assert names(listing(ann, ws, q="bea@beta")) == [] and names(listing(w.admin, ws, q="bea@beta")) == ["Bea Beta"]
    assert names(listing(ann, ws, filter=json.dumps({"field": "last_name", "op": "is", "value": "Beta"}))) == []
    page = listing(ann, ws, limit=1)  # paging does not run past the edge of the scope
    assert len(page["data"]) == 1 and page["next_cursor"]
    assert len(listing(ann, ws, cursor=page["next_cursor"], limit=1)["data"]) == 1
    # the companies and deals are not scoped for them, so the same people see them all
    assert names(listing(ann, ws, "company")) == ["Acme"] and len(listing(ann, ws, "deal")["data"]) == 5


def test_scope_own_gives_a_404_for_what_belongs_to_others(world):
    w = world
    ann, ws, bea = w.client["ann"], w.ws, w.rec["bea"]["id"]
    one = f"{R}/{bea}"
    gone(ann, ws, one)
    gone(ann, ws, one, "patch", json={"values": {"first_name": "X"}})
    gone(ann, ws, one, "delete")
    gone(ann, ws, f"{one}/restore", "post")
    gone(ann, ws, f"/api/v1/records/{bea}/timeline")
    gone(ann, ws, f"/api/v1/records/{bea}/associations")
    gone(ann, ws, f"/api/v1/records/{w.rec['una']['id']}/timeline")
    tag = w.admin.post("/api/v1/tags", json={"name": "vip"}, headers={H: w.ws}).json()["id"]
    gone(ann, ws, f"/api/v1/records/{bea}/tags", "post", json={"add": [tag]})
    gone(ann, ws, "/api/v1/records/tags", "post", json={"record_ids": [bea, w.rec["ada"]["id"]], "add": [tag]})
    gone(ann, ws, f"/api/v1/records/{w.rec['ada']['id']}/associations", "post",
         json={"type_id": w.link, "other_id": bea})
    gone(ann, ws, f"/api/v1/associations/{w.links['bea']}", "delete")
    assert ann.get(f"{R}/{w.rec['ada']['id']}", headers={H: ws}).status_code == 200  # their own are there
    assert ann.get(f"/api/v1/records/{w.rec['ada']['id']}/timeline", headers={H: ws}).json()["data"]
    # a record that is theirs but linked to one that is not: the link shows only what they may see
    links = ann.get(f"/api/v1/records/{w.rec['acme']['id']}/associations", headers={H: ws}).json()["data"]
    assert [x["record"]["display_name"] for x in links] == ["Ada Alpha"]


def test_scope_own_covers_views_expansion_filters_trash_tags_and_the_timeline(world):
    w = world
    ann, ws, admin = w.client["ann"], w.ws, w.admin
    everyone = admin.post("/api/v1/views", json={"object": "contact", "name": "Everyone", "shared": True},
                          headers={H: ws}).json()
    leads = admin.post("/api/v1/views", headers={H: ws}, json={
        "object": "contact", "name": "A names", "shared": True,
        "filter": {"field": "first_name", "op": "starts_with", "value": "a"}}).json()
    assert admin.get(f"/api/v1/views/{everyone['id']}", headers={H: ws}).json()["count"] == 4
    assert ann.get(f"/api/v1/views/{everyone['id']}", headers={H: ws}).json()["count"] == 2  # the live count is theirs
    counts = {v["name"]: v["count"] for v in ann.get("/api/v1/views", params={"counts": "true"},
                                                     headers={H: ws}).json()["data"]}
    assert counts == {"Everyone": 2, "A names": 2}
    assert sorted(names(listing(ann, ws, view=everyone["id"]))) == ["Ada Alpha", "Alan Alpha"]
    assert names(listing(w.client["bob"], ws, view=leads["id"])) == []  # Bea starts with B
    # expansion and association paths see only what the scope lets through
    page = listing(ann, ws, "company", include="contact")
    linked = [[x["record"]["display_name"] for x in c["associations"]["contact"]] for c in page["data"]]
    assert linked == [["Ada Alpha"]]
    page = listing(w.admin, ws, "company", include="contact")
    assert sorted(x["record"]["display_name"] for x in page["data"][0]["associations"]["contact"]) == [
        "Ada Alpha", "Bea Beta"]
    on_acme = json.dumps({"field": "company.name", "op": "is", "value": "Acme"})
    assert names(listing(ann, ws, filter=on_acme)) == ["Ada Alpha"]
    assert len(listing(w.admin, ws, filter=on_acme)["data"]) == 2
    # the trash is theirs
    assert w.client["bob"].delete(f"{R}/{w.rec['bea']['id']}", headers={H: ws}).status_code == 204
    assert ann.delete(f"{R}/{w.rec['alan']['id']}", headers={H: ws}).status_code == 204
    trash = ann.get("/api/v1/trash", params={"object": "contact"}, headers={H: ws}).json()["data"]
    assert [r["display_name"] for r in trash] == ["Alan Alpha"]
    assert len(admin.get("/api/v1/trash", params={"object": "contact"}, headers={H: ws}).json()["data"]) == 2
    gone(ann, ws, f"{R}/{w.rec['bea']['id']}/restore", "post")
    assert ann.post(f"{R}/{w.rec['alan']['id']}/restore", headers={H: ws}).status_code == 200
    # a tag counts the records of the one who asks
    tag = admin.post("/api/v1/tags", json={"name": "vip"}, headers={H: ws}).json()["id"]
    assert admin.post("/api/v1/records/tags", json={"record_ids": [w.rec["ada"]["id"], w.rec["una"]["id"]],
                                                     "add": [tag]}, headers={H: ws}).status_code == 200
    count = lambda who: {t["name"]: t["count"] for t in w.client[who].get(  # noqa: E731
        "/api/v1/tags", headers={H: ws}).json()["data"]}["vip"]
    assert (count("admin"), count("ann"), count("bob")) == (2, 1, 0)
    assert ann.patch(f"/api/v1/tags/{tag}", json={"name": "vip"}, headers={H: ws}).status_code == 403  # members: no
    assert admin.patch(f"/api/v1/tags/{tag}", json={"color": "red"}, headers={H: ws}).json()["count"] == 2
    # the timeline of what is theirs, and the links on it
    events = ann.get(f"/api/v1/records/{w.rec['ada']['id']}/timeline", headers={H: ws}).json()["data"]
    assert {e["type"] for e in events} >= {"record.created", "association.created", "tag.added"}
    acme = ann.get(f"/api/v1/records/{w.rec['acme']['id']}/timeline", headers={H: ws}).json()["data"]
    links = [e for e in acme if e["type"] == "association.created"]
    assert [e["data"]["from_record_id"] for e in links] == [w.rec["ada"]["id"]]  # Bea's link and id are not shown
    assert w.rec["bea"]["id"] not in json.dumps(acme)


def test_a_record_a_member_creates_is_theirs_unless_they_say_otherwise(world):
    w = world
    ann, ws = w.client["ann"], w.ws
    r = ann.post(R, json={"values": {"first_name": "Mine"}}, headers={H: ws})  # no owner sent
    assert r.status_code == 201
    mine = r.json()
    assert mine["owner_id"] == w.user["ann"] and "Mine" in names(listing(ann, ws))
    assert ann.get(f"{R}/{mine['id']}", headers={H: ws}).status_code == 200
    given = make_record(ann, ws, first_name="Given", owner_id=w.user["bob"])  # sent on purpose, so it is Bob's
    assert given["owner_id"] == w.user["bob"] and "Given" not in names(listing(ann, ws))
    assert "Given" in names(listing(w.client["bob"], ws))
    r = ann.post(R, json={"values": {"first_name": "Orphan"}, "owner_id": None}, headers={H: ws})
    assert r.status_code == 201 and r.json()["owner_id"] is None
    gone(ann, ws, f"{R}/{r.json()['id']}")  # unowned on purpose: out of reach on this scope
    assert make_record(w.admin, ws, first_name="Admins")["owner_id"] is None  # others keep creating unowned records


def test_scope_own_and_unassigned_adds_the_records_nobody_owns(world, db):
    w = world
    make_role(w.admin, w.ws, "Pickers", rules=[rule(), rule("contact", "own_and_unassigned")])
    gus = add_member(db, w.org, "gus@example.com", workspace_id=w.ws, workspace_role="pickers")
    assert names(listing(gus, w.ws)) == ["Una Unowned"]  # nobody's, and no one else's
    mine = make_record(gus, w.ws, first_name="Gus", owner_id=user_id_of(gus))
    assert sorted(names(listing(gus, w.ws))) == ["Gus", "Una Unowned"]
    unowned = make_record(gus, w.ws, first_name="Nobody")  # made by someone who sees unassigned records: unassigned
    assert unowned["owner_id"] is None and "Nobody" in names(listing(gus, w.ws))
    r = gus.patch(f"{R}/{w.rec['una']['id']}", json={"owner_id": user_id_of(gus)}, headers={H: w.ws})
    assert r.status_code == 200 and gus.get(f"{R}/{mine['id']}", headers={H: w.ws}).status_code == 200  # picked up
    gone(gus, w.ws, f"{R}/{w.rec['ada']['id']}")
    answer = explain(w.admin, w.ws, user_id_of(gus), w.rec["alan"]["id"])["record"]
    assert answer["reason"] == "not visible: the record is owned by someone else, scope own_and_unassigned"
    assert explain(w.admin, w.ws, user_id_of(gus), unowned["id"])["record"]["reason"] == (
        "visible: the record has no owner, scope own_and_unassigned")


def test_assignee_fields_count_as_ownership(world, db):
    w = world
    admin, ws = w.admin, w.ws
    assert admin.post("/api/v1/objects", json={"key": "project", "singular": "Project", "plural": "Projects"},
                      headers={H: ws}).status_code == 201
    assert admin.post("/api/v1/objects/project/fields", json={"key": "lead", "label": "Lead", "type": "user"},
                      headers={H: ws}).status_code == 201
    make_role(admin, ws, "Own everything", rules=[rule(scope="own")])
    ivy = add_member(db, w.org, "ivy@example.com", workspace_id=ws, workspace_role="own_everything")
    ivy_id = user_id_of(ivy)
    projects = {name: make_record(admin, ws, "project", owner_id=owner, name=name, **({"lead": lead} if lead else {}))
                for name, owner, lead in (("Led by Ivy", None, ivy_id), ("Led by Bob", None, w.user["bob"]),
                                          ("Owned by Ivy", ivy_id, None), ("Nobody's", None, None))}
    assert sorted(names(listing(ivy, ws, "project"))) == ["Led by Ivy", "Owned by Ivy"]
    assert listing(ivy, ws, "project", count="true")["total"] == 2 and len(listing(admin, ws, "project")["data"]) == 4
    gone(ivy, ws, f"/api/v1/objects/project/records/{projects['Led by Bob']['id']}")
    led = f"/api/v1/objects/project/records/{projects['Led by Ivy']['id']}"
    assert ivy.get(led, headers={H: ws}).status_code == 200
    why = explain(admin, ws, ivy_id, projects["Led by Ivy"]["id"])["record"]
    assert why["reason"] == "visible: the user is assigned in lead, scope own"
    assert names(listing(ivy, ws)) == []  # contacts have no user field, so only the owner counts there


def test_scope_team_includes_sub_teams_and_follows_membership(world):
    w = world
    cy, eli, fay, gia = (w.client[n] for n in ("cy", "eli", "fay", "gia"))
    ws, admin = w.ws, w.admin
    deals = lambda who: sorted(names(listing(who, ws, "deal")))  # noqa: E731
    # Cy is in East, Eli in East North (under East), Gia in East, Fay in West
    # East, and East North below it; not West, not nobody's
    assert deals(cy) == ["Deal of cy", "Deal of eli", "Deal of gia"]
    assert deals(eli) == ["Deal of eli"]  # a sub-team sees nothing of the team above
    assert deals(gia) == ["Deal of cy", "Deal of eli", "Deal of gia"]
    assert deals(fay) == ["Deal of fay"]
    assert len(listing(admin, ws, "deal")["data"]) == 5
    assert listing(cy, ws, "deal", count="true")["total"] == 3
    gone(cy, ws, f"/api/v1/objects/deal/records/{w.rec['deal_fay']['id']}")
    gone(cy, ws, f"/api/v1/objects/deal/records/{w.rec['deal_none']['id']}")
    # membership applies on the next request
    assert admin.put(f"/api/v1/teams/{w.team['east']}/members/{w.user['fay']}", headers={H: ws}).status_code == 200
    assert deals(cy) == ["Deal of cy", "Deal of eli", "Deal of fay", "Deal of gia"]
    assert admin.delete(f"/api/v1/teams/{w.team['east']}/members/{w.user['fay']}", headers={H: ws}).status_code == 204
    assert deals(cy) == ["Deal of cy", "Deal of eli", "Deal of gia"]
    # West under East: Fay's deals come along, and so does a new sub-team's member
    r = admin.patch(f"/api/v1/teams/{w.team['west']}", json={"parent_team_id": w.team["east"]}, headers={H: ws})
    assert r.status_code == 200 and r.json()["parent_team_id"] == w.team["east"]
    assert deals(cy) == ["Deal of cy", "Deal of eli", "Deal of fay", "Deal of gia"] and deals(fay) == ["Deal of fay"]
    # deleting West moves its sub-teams up and takes its members out of the tree
    assert admin.delete(f"/api/v1/teams/{w.team['west']}", headers={H: ws}).status_code == 204
    assert deals(cy) == ["Deal of cy", "Deal of eli", "Deal of gia"] and deals(fay) == ["Deal of fay"]  # still hers
    # the team scope never lets a cycle in
    r = admin.patch(f"/api/v1/teams/{w.team['east']}", json={"parent_team_id": w.team["north"]}, headers={H: ws})
    assert r.status_code == 422 and "parent_team_id" in r.json()["error"]["fields"]
    assert admin.patch(f"/api/v1/teams/{w.team['east']}", json={"parent_team_id": w.team["east"]},
                       headers={H: ws}).status_code == 422
    # the contacts of these people are not scoped by team: their role has all contacts
    assert len(listing(cy, ws)["data"]) == 4


def test_the_team_scope_with_a_hidden_field_and_a_read_only_field(world):
    """The done-when of module 03: a role limited to its team's deals, with a hidden field."""
    w = world
    cy, ws = w.client["cy"], w.ws
    deal = listing(cy, ws, "deal")["data"][0]
    # the amount is on it for everyone else, not for Cy (a deal starts in the first stage of the Sales pipeline)
    assert set(deal["values"]) == {"name", "stage"} and deal["values"]["name"] == deal["display_name"]
    assert "amount" in listing(w.admin, ws, "deal")["data"][0]["values"]
    r = cy.patch(f"/api/v1/objects/deal/records/{w.rec['deal_cy']['id']}", json={"values": {"amount": {
        "amount": 1, "currency": "USD"}}}, headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"values.amount": "is not a field of deal"}
    r = cy.patch(f"/api/v1/objects/deal/records/{w.rec['deal_cy']['id']}", json={"values": {"stage": "won"}},
                 headers={H: ws})
    assert r.status_code == 403 and r.json()["error"]["fields"] == {"values.stage": "is read-only for your role"}
    r = cy.patch(f"/api/v1/objects/deal/records/{w.rec['deal_cy']['id']}", json={"values": {"name": "Renamed"}},
                 headers={H: ws})
    assert r.status_code == 200 and "amount" not in r.json()["values"]
    assert w.admin.get(f"/api/v1/objects/deal/records/{w.rec['deal_cy']['id']}", headers={H: ws}).json()["values"][
        "amount"] == {"amount": 1500000, "currency": "USD"}  # what they cannot see is as it was


def test_explain_agrees_with_what_the_api_does_on_a_matrix_of_users_and_records(world):
    w = world
    ws = w.ws
    records = {k: v for k, v in w.rec.items()}
    seen = {True: 0, False: 0}
    for who, (name, rec) in itertools.product(w.user, records.items()):
        answer = explain(w.admin, ws, w.user[who], rec["id"])
        got = w.client[who].get(f"/api/v1/objects/{rec['object']}/records/{rec['id']}", headers={H: ws})
        assert got.status_code in (200, 404)
        assert answer["record"]["visible"] == (got.status_code == 200), (who, name, answer["record"])
        assert answer["record"]["reason"].startswith("visible" if answer["record"]["visible"] else "not visible")
        seen[answer["record"]["visible"]] += 1
        # and the same on the other doors of the engine: the list and the timeline
        in_list = rec["id"] in {r["id"] for r in w.client[who].get(
            f"/api/v1/objects/{rec['object']}/records", params={"limit": 200}, headers={H: ws}).json()["data"]}
        timeline = w.client[who].get(f"/api/v1/records/{rec['id']}/timeline", headers={H: ws}).status_code
        assert in_list == (got.status_code == 200) == (timeline == 200), (who, name)
    assert seen[True] > 50 and seen[False] >= 15  # the matrix has both kinds of answer in it


def test_explain_says_why_and_describes_the_role(world):
    w = world
    ws = w.ws
    # Cy sees Gia's deal because Gia is in East, and Eli's because Eli is in East North, below it
    got = explain(w.admin, ws, w.user["cy"], w.rec["deal_gia"]["id"])
    assert got["record"] == {"id": w.rec["deal_gia"]["id"], "object": "deal", "visible": True, "in_trash": False,
                             "reason": "visible: owner is in team East, scope team"}
    assert explain(w.admin, ws, w.user["cy"], w.rec["deal_eli"]["id"])["record"]["reason"] == (
        "visible: owner is in team East North, scope team")
    assert explain(w.admin, ws, w.user["cy"], w.rec["deal_cy"]["id"])["record"]["reason"] == (
        "visible: the user is the owner, scope team")
    assert explain(w.admin, ws, w.user["cy"], w.rec["deal_fay"]["id"])["record"]["reason"] == (
        "not visible: owner is in none of the user's teams, scope team")
    assert explain(w.admin, ws, w.user["cy"], w.rec["deal_none"]["id"])["record"]["reason"] == (
        "not visible: the record has no owner, scope team")
    assert explain(w.admin, ws, w.user["ann"], w.rec["bea"]["id"])["record"]["reason"] == (
        "not visible: the record is owned by someone else, scope own")
    assert explain(w.admin, ws, w.user["ann"], w.rec["ada"]["id"])["record"]["reason"] == (
        "visible: the user is the owner, scope own")
    assert explain(w.admin, ws, w.user["admin"], w.rec["bea"]["id"])["record"]["reason"] == "visible: scope all"
    # the role, what it holds, its rule per object and the teams in play
    cy = explain(w.admin, ws, w.user["cy"])
    assert cy["user"]["email"] == "cy@example.com" and cy["role"]["key"] == "team_deals"
    assert cy["role"]["source"] == "workspace" and "record" not in cy and "deals.write" in cy["capabilities"]
    assert cy["objects"]["deal"] == {"scope": "team", "rule_scope": "team", "hidden_fields": ["amount"],
                                     "readonly_fields": ["stage"],
                                     "can": {"read": True, "write": True, "delete": True, "export": False}}
    assert cy["objects"]["contact"]["scope"] == "all"
    assert [(t["name"], t["direct"]) for t in cy["teams"]] == [("East", True), ("East North", False)]
    admin = explain(w.admin, ws, w.user["admin"])
    assert admin["role"]["key"] == "owner" and admin["role"]["source"] == "organization"
    assert admin["objects"]["deal"]["scope"] == "all" and set(admin["capabilities"]) >= {"audit.read", "billing.manage"}
    dee = explain(w.admin, ws, w.user["dee"])
    assert dee["objects"]["contact"]["can"] == {"read": True, "write": False, "delete": False, "export": False}
    assert explain(w.admin, ws, None)["user"]["id"] == w.user["admin"]  # no user_id: the one asking
    # the people it does not know, and the roles that may not ask
    assert w.admin.get("/api/v1/permissions/explain", params={"user_id": str(uuid.uuid4())},
                       headers={H: ws}).status_code == 404
    assert w.admin.get("/api/v1/permissions/explain", params={"record_id": str(uuid.uuid4())},
                       headers={H: ws}).status_code == 404
    assert w.client["cy"].get("/api/v1/permissions/explain", headers={H: ws}).status_code == 403


def test_explain_follows_a_change_of_role_and_a_trashed_record(world):
    w = world
    ws, ada = w.ws, w.rec["ada"]["id"]
    assert explain(w.admin, ws, w.user["bob"], ada)["record"]["visible"] is False
    member = next(x for x in w.admin.get("/api/v1/roles", headers={H: ws}).json()["data"] if x["key"] == "member")
    r = w.admin.put(f"/api/v1/members/{w.user['bob']}", json={"role_id": member["id"]}, headers={H: ws})
    assert r.status_code == 200
    assert explain(w.admin, ws, w.user["bob"], ada)["record"]["visible"] is True
    assert w.client["bob"].get(f"{R}/{ada}", headers={H: ws}).status_code == 200
    assert w.admin.delete(f"{R}/{ada}", headers={H: ws}).status_code == 204
    assert explain(w.admin, ws, w.user["bob"], ada)["record"]["in_trash"] is True


# --- hidden fields ----------------------------------------------------------------------------------------------

@pytest.fixture
def redacted(crm, db):
    """A person whose role hides a contact's last name, email and phone and cannot change its lifecycle stage, and
    the records they must not learn those from."""
    admin, ws, ids = crm
    make_role(admin, ws, "Redacted", rules=[rule(), rule("contact", "all", hidden=["last_name", "email", "phone"],
                                                         readonly=["lifecycle"])])
    w = SimpleNamespace(admin=admin, ws=ws, ids=ids, user={}, client={})
    w.client["rae"] = add_member(db, ids["org_id"], "rae@example.com", workspace_id=ws, workspace_role="redacted")
    w.ada = make_record(admin, ws, first_name="Ada", last_name="Lovelace", email=SECRET_EMAIL, phone=SECRET_PHONE,
                        lifecycle="lead")
    w.nameless = make_record(admin, ws, email="only.email@hidden-mail.example")  # named by its email: hidden too
    w.acme = make_record(admin, ws, "company", name="Acme")
    w.link = link(admin, ws, w.ada["id"], w.acme["id"], type_id(admin, ws, "contact", "company"))["id"]
    return w


def leaks(payload) -> list[str]:
    text = json.dumps(payload)
    return [s for s in ("Lovelace", SECRET_EMAIL, "ada.lovelace", SECRET_PHONE, "4155550100", "only.email",
                        "hidden-mail") if s in text]


def test_hidden_fields_never_appear_in_a_record_response(redacted):
    w, rae, ws = redacted, redacted.client["rae"], redacted.ws
    one = rae.get(f"{R}/{w.ada['id']}", headers={H: ws}).json()
    assert set(one["values"]) == {"first_name", "lifecycle"} and one["display_name"] == "Ada"  # not "Ada Lovelace"
    page = listing(rae, ws, include="tags,company", count="true")
    assert not leaks(page) and sorted(names(page)) == ["(hidden)", "Ada"]  # the nameless one has nothing to show
    assert not leaks(rae.post(f"{R}/query", json={"limit": 5}, headers={H: ws}).json())
    assert set(w.admin.get(f"{R}/{w.ada['id']}", headers={H: ws}).json()["values"]) >= {"last_name", "email", "phone"}
    assert listing(w.admin, ws, q="lovelace")["data"]  # for others it is all there
    # the places a record turns up as a neighbour: links, expansion, the trash
    assert not leaks(rae.get(f"/api/v1/records/{w.acme['id']}/associations", headers={H: ws}).json())
    page = listing(rae, ws, "company", include="contact")
    assert not leaks(page) and page["data"][0]["associations"]["contact"][0]["record"]["display_name"] == "Ada"
    assert not leaks(rae.get(f"/api/v1/records/{w.ada['id']}/associations", headers={H: ws}).json())
    assert w.admin.delete(f"{R}/{make_record(w.admin, ws, first_name='Grace', last_name='Hopper')['id']}",
                          headers={H: ws}).status_code == 204
    trash = rae.get("/api/v1/trash", params={"object": "contact"}, headers={H: ws}).json()["data"]
    assert [r["display_name"] for r in trash] == ["Grace"] and "Hopper" not in json.dumps(trash)


def test_hidden_fields_cannot_be_searched_filtered_or_sorted_on(redacted):
    w, rae, ws = redacted, redacted.client["rae"], redacted.ws
    for q in ("lovelace", SECRET_EMAIL, "ada.lovelace", "+14155550100", "only.email"):
        assert listing(rae, ws, q=q)["data"] == [], q
        assert listing(w.admin, ws, q=q)["data"], q  # and they do match for someone who may see them
    for q in ("4155550100", "hidden-mail", "lovelace ada", "ada@hidden"):
        assert listing(rae, ws, q=q)["data"] == [], q
    assert names(listing(rae, ws, q="ada")) == ["Ada"] and names(listing(rae, ws, q="Ad")) == ["Ada"]

    def refused(**params):
        r = rae.get(R, params=params, headers={H: ws})
        assert r.status_code == 400, (params, r.status_code, r.text[:200])
        return r.json()["error"]["fields"]

    for key in ("email", "last_name", "phone", "display_name"):
        got = refused(filter=json.dumps({"field": key, "op": "is_not_empty"}))
        assert got == {"filter.field": f"unknown field {key!r} on contact"}  # as if it were not there at all
        assert list(refused(sort=key)) == ["sort"] and list(refused(sort=f"first_name,-{key}")) == ["sort"]
    nested = {"and": [{"field": "first_name", "op": "is", "value": "Ada"},
                      {"or": [{"not": {"field": "email", "op": "contains", "value": "ada"}}]}]}
    assert list(refused(filter=json.dumps(nested))) == ["filter.and.1.or.0.not.field"]
    assert list(rae.post(f"{R}/query", json={"filter": {"field": "phone", "op": "is", "value": "+1"}},
                         headers={H: ws}).json()["error"]["fields"]) == ["filter.field"]
    path = {"field": "contact.email", "op": "is", "value": SECRET_EMAIL}  # through an association of the company
    assert rae.get("/api/v1/objects/company/records", params={"filter": json.dumps(path)},
                   headers={H: ws}).status_code == 400
    assert names(listing(rae, ws, sort="first_name,-created_at", filter=json.dumps(
        {"field": "first_name", "op": "is", "value": "Ada"}))) == ["Ada"]  # what they may use works as ever


def test_hidden_fields_cannot_be_written_and_read_only_ones_cannot_be_changed(redacted):
    w, rae, ws = redacted, redacted.client["rae"], redacted.ws
    path = f"{R}/{w.ada['id']}"

    def patch(values, status):
        r = rae.patch(path, json={"values": values}, headers={H: ws})
        assert r.status_code == status, r.text
        return r.json()["error"]["fields"] if status != 200 else r.json()

    assert patch({"email": "x@y.example"}, 422) == {"values.email": "is not a field of contact"}
    assert patch({"first_name": "Ada", "last_name": "Byron", "phone": "+1"}, 422).keys() == {
        "values.last_name", "values.phone"}
    assert patch({"lifecycle": "customer"}, 403) == {"values.lifecycle": "is read-only for your role"}
    r = rae.post(R, json={"values": {"first_name": "New", "email": "n@y.example"}}, headers={H: ws})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"values.email": "is not a field of contact"}
    r = rae.post(R, json={"values": {"first_name": "New", "lifecycle": "lead"}}, headers={H: ws})
    assert r.status_code == 403 and r.json()["error"]["fields"] == {"values.lifecycle": "is read-only for your role"}
    ok = patch({"first_name": "Augusta"}, 200)  # what they may change, they change, and get back without the rest
    assert ok["values"] == {"first_name": "Augusta", "lifecycle": "lead"} and not leaks(ok)
    assert rae.get(path, headers={H: ws}).json()["values"]["lifecycle"] == "lead"
    seen = w.admin.get(path, headers={H: ws}).json()["values"]  # nothing they could not see was touched
    assert (seen["last_name"], seen["email"], seen["phone"], seen["lifecycle"]) == (
        "Lovelace", SECRET_EMAIL, SECRET_PHONE, "lead")
    created = make_record(rae, ws, first_name="Fresh")  # and a create with what they may
    assert created["values"] == {"first_name": "Fresh"}
    assert make_record(rae, ws, "company", name="Acme Two")["display_name"] == "Acme Two"  # other objects: no rules


def test_the_schema_the_timeline_views_and_audit_leave_hidden_fields_out(redacted, db):
    w, rae, ws, admin = redacted, redacted.client["rae"], redacted.ws, redacted.admin
    assert admin.patch(f"{R}/{w.ada['id']}", json={"values": {"email": "ada2@hidden-mail.example"}},
                       headers={H: ws}).status_code == 200
    keys = lambda c, path: {f["key"] for f in c.get(path, headers={H: ws}).json().get("fields", [])}  # noqa: E731
    assert keys(admin, "/api/v1/objects/contact") >= {"email", "phone", "last_name", "first_name"}
    assert keys(rae, "/api/v1/objects/contact") & {"email", "phone", "last_name"} == set()
    listed = {f["key"] for f in rae.get("/api/v1/objects/contact/fields", headers={H: ws}).json()["data"]}
    assert "first_name" in listed and not listed & {"email", "phone", "last_name"}
    timeline = rae.get(f"/api/v1/records/{w.ada['id']}/timeline", headers={H: ws}).json()
    assert {e["type"] for e in timeline["data"]} >= {"record.created", "record.updated"}
    assert not leaks(timeline) and "ada2" not in json.dumps(timeline)
    updated = next(e for e in timeline["data"] if e["type"] == "record.updated")
    assert updated["data"]["changes"] == {} and "display_name" not in updated["data"]
    created = next(e for e in timeline["data"] if e["type"] == "record.created")
    assert set(created["data"]["values"]) == {"first_name", "lifecycle"}
    full = admin.get(f"/api/v1/records/{w.ada['id']}/timeline", headers={H: ws}).json()
    assert "Lovelace" in json.dumps(full)
    # saved views: one that uses a hidden field does not exist for them, in the list, by id or as `?view=`
    shared = {"object": "contact", "shared": True}
    secret = admin.post("/api/v1/views", json={**shared, "name": "Has email", "filter": {
        "field": "email", "op": "is_not_empty"}}, headers={H: ws}).json()
    by_column = admin.post("/api/v1/views", json={**shared, "name": "Phones", "columns": ["first_name", "phone"]},
                           headers={H: ws}).json()
    by_path = admin.post("/api/v1/views", json={**shared, "name": "At Acme", "filter": {
        "field": "company.name", "op": "is", "value": "Acme"}}, headers={H: ws}).json()
    plain = admin.post("/api/v1/views", json={**shared, "name": "Everyone"}, headers={H: ws}).json()
    shown = {v["name"] for v in rae.get("/api/v1/views", params={"counts": "true"}, headers={H: ws}).json()["data"]}
    assert shown == {"At Acme", "Everyone"} and {v["name"] for v in admin.get(
        "/api/v1/views", headers={H: ws}).json()["data"]} == {"Has email", "Phones", "At Acme", "Everyone"}
    for hidden_view in (secret, by_column):
        assert rae.get(f"/api/v1/views/{hidden_view['id']}", headers={H: ws}).status_code == 404
        assert rae.get(R, params={"view": hidden_view["id"]}, headers={H: ws}).status_code == 404
        assert rae.delete(f"/api/v1/views/{hidden_view['id']}", headers={H: ws}).status_code == 404
    assert names(listing(rae, ws, view=plain["id"])) and by_path["id"]
    r = rae.post("/api/v1/views", json={"object": "contact", "name": "Mine", "filter": {
        "field": "email", "op": "is", "value": "x@y.example"}}, headers={H: ws})
    assert r.status_code == 400 and "filter.field" in r.json()["error"]["fields"]
    # the audit log: a role that may read it still does not get the fields it may not see
    make_role(admin, ws, "Redacted auditor", copy_from="member", capabilities=["audit.read", "contacts.read"],
              rules=[rule("*", "all", hidden=["last_name", "email", "phone"])])
    auditor = add_member(db, w.ids["org_id"], "aud@example.com", workspace_id=ws, workspace_role="redacted_auditor")
    rows = audit(auditor, ws, type="record.*")
    assert {r["type"] for r in rows} >= {"record.created", "record.updated"} and not leaks(rows)
    assert "Lovelace" in json.dumps(audit(admin, ws, type="record.*"))
    export = auditor.get("/api/v1/audit/export", params={"type": "record.*"}, headers={H: ws}).text
    assert "record.updated" in export and not leaks(export)


def test_no_route_shows_a_restricted_member_what_is_out_of_scope_or_hidden(world, db):
    """Every route that reads, called with the ids of what a person may not see and of what they may: the answer
    never holds an out-of-scope record, its owner's other records, or a field their role hides."""
    w = world
    ws, admin = w.ws, w.admin
    make_role(admin, ws, "Rex", rules=[rule(), rule("contact", "own", hidden=["last_name", "email"])])
    rex = add_member(db, w.org, "rex@example.com", workspace_id=ws, workspace_role="rex")
    mine = make_record(admin, ws, owner_id=user_id_of(rex), first_name="Rex", last_name="Rexford",
                       email="rex@rexford-hidden.example")
    secrets = ["Rexford", "rexford-hidden", "Beta", "bea@beta", "Unowned", "una@unowned", w.rec["bea"]["id"],
               w.rec["una"]["id"], w.links["bea"], "Alpha", "ada@alpha"]  # Ann's records are out of Rex's reach too
    values = {"key": ["contact", "company", "deal"], "field_key": ["email", "first_name"],
              "record_id": [w.rec[k]["id"] for k in ("bea", "una", "ada", "acme")] + [mine["id"]],
              "association_id": list(w.links.values()), "type_id": [w.link], "team_id": list(w.team.values()),
              "user_id": [w.user["bob"], w.user["ann"], user_id_of(rex)]}
    tag = admin.post("/api/v1/tags", json={"name": "vip"}, headers={H: ws}).json()["id"]
    values["tag_id"] = [tag]
    view = admin.post("/api/v1/views", json={"object": "contact", "name": "V", "shared": True}, headers={H: ws}).json()
    values["view_id"] = [view["id"]]
    calls = 0
    for method, path, _ in v1_routes():
        if method != "GET" and not path.endswith("/records/query"):
            continue
        params = re.findall(r"\{(\w+)\}", path)
        for combo in itertools.product(*[values.get(p, [str(uuid.uuid4())]) for p in params]):
            chosen = dict(zip(params, combo, strict=True))
            url = re.sub(r"\{(\w+)\}", lambda m, chosen=chosen: chosen[m.group(1)], path)
            for extra in ({}, {"object": "contact", "include": "tags,company", "count": "true", "q": "a"}):
                r = rex.request(method, url, params=extra or None, json={"q": "a", "include": ["tags"]}
                                if method == "POST" else None, headers={H: ws})
                calls += 1
                assert r.status_code < 500, (method, url, r.text[:200])
                bad = [s for s in secrets if s in r.text]
                assert not bad, (method, url, bad, r.text[:300])
    assert calls > 100
    own = rex.get(f"{R}/{mine['id']}", headers={H: ws}).json()
    assert own["values"] == {"first_name": "Rex"} and own["display_name"] == "Rex"  # and what is theirs does come back


def test_an_idempotency_key_replays_only_for_the_user_who_made_it(redacted):
    """A stored response was written for what its user may see, so another user is never handed it."""
    w, rae, ws = redacted, redacted.client["rae"], redacted.ws
    body = {"values": {"first_name": "Twice", "email": "twice@hidden-mail.example"}}
    key = {H: ws, "Idempotency-Key": "k1"}
    assert w.admin.post(R, json=body, headers=key).status_code == 201
    r = rae.post(R, json=body, headers=key)
    assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_key_reused"
    assert "hidden-mail" not in r.text
    assert w.admin.post(R, json=body, headers=key).headers["idempotent-replayed"] == "true"
