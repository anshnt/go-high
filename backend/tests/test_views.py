"""Saved views: stored filter, columns and sort, live counts, and who can see and change them."""
import json
import uuid

from helpers import H, add_member, listing, make_record, names

VIEWS = "/api/v1/views"
OBJECTS = "/api/v1/objects"
LEADS = {"field": "lifecycle", "op": "is", "value": "lead"}


def make_view(client, ws, **body) -> dict:
    r = client.post(VIEWS, json={"object": "contact", "name": "Leads", "filter": LEADS, **body}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def people(client, ws):
    for first, lifecycle in (("Ada", "lead"), ("Grace", "customer"), ("Alan", "lead"), ("Edsger", "lead"),
                             ("Linus", None)):
        make_record(client, ws, first_name=first, **({"lifecycle": lifecycle} if lifecycle else {}))


def test_a_view_stores_a_filter_columns_and_sort_and_counts_live(crm):
    client, ws, _ = crm
    people(client, ws)
    view = make_view(client, ws, columns=["display_name", "email", "lifecycle"], sort=["-display_name"])
    assert view["object"] == "contact" and view["shared"] is False and view["filter"] == LEADS
    assert view["columns"] == ["display_name", "email", "lifecycle"] and view["sort"] == ["-display_name"]
    assert view["owner_id"] == client.get("/api/me").json()["user"]["id"] and "count" not in view
    assert client.get(f"{VIEWS}/{view['id']}", headers={H: ws}).json()["count"] == 3
    got = client.get(VIEWS, params={"counts": "true"}, headers={H: ws}).json()
    assert [(v["name"], v["count"]) for v in got["data"]] == [("Leads", 3)]
    assert "count" not in client.get(VIEWS, headers={H: ws}).json()["data"][0]  # counts are asked for
    make_record(client, ws, first_name="Barbara", lifecycle="lead")
    assert client.get(f"{VIEWS}/{view['id']}", headers={H: ws}).json()["count"] == 4  # live, not a snapshot

    # opening it: its filter and sort, narrowed by the request
    opened = listing(client, ws, view=view["id"], count="true")
    assert opened["total"] == 4 and names(opened) == ["Edsger", "Barbara", "Alan", "Ada"]  # the view's sort
    narrowed = listing(client, ws, view=view["id"], filter=json.dumps({"field": "first_name", "op": "starts_with",
                                                                       "value": "a"}))
    assert names(narrowed) == ["Alan", "Ada"]  # leads whose name starts with a, in the view's order
    assert names(listing(client, ws, view=view["id"], sort="display_name"))[0] == "Ada"  # the request's sort wins
    r = client.get(f"{OBJECTS}/company/records", params={"view": view["id"]}, headers={H: ws})
    assert r.status_code == 400 and "view" in r.json()["error"]["fields"]  # a view of contacts is not for companies
    assert client.get(f"{OBJECTS}/contact/records", params={"view": str(uuid.uuid4())}, headers={H: ws}
                      ).status_code == 404
    paged = client.post(f"{OBJECTS}/contact/records/query", json={"view": view["id"], "limit": 2},
                        headers={H: ws}).json()
    assert len(paged["data"]) == 2 and paged["next_cursor"]


def test_a_view_is_only_saved_if_it_runs(crm):
    client, ws, _ = crm

    def bad(status, **body):
        r = client.post(VIEWS, json={"object": "contact", "name": "V", **body}, headers={H: ws})
        assert r.status_code == status, (body, r.text)
        return r.json()["error"]["fields"]

    fields = bad(400, filter={"field": "nope", "op": "is", "value": 1})
    assert fields == {"filter.field": "unknown field 'nope' on contact"}
    assert "filter.op" in bad(400, filter={"field": "first_name", "op": "gt", "value": 1})
    assert "columns.1" in bad(422, columns=["first_name", "nope"])
    assert "sort" in bad(400, sort=["nope"])
    assert "sort" in bad(422, sort=["a", "b", "c", "d"])
    bad(422, name="")
    bad(422, name="x" * 201)
    bad(422, columns=["x"] * 51)
    assert client.post(VIEWS, json={"object": "nothing", "name": "V"}, headers={H: ws}).status_code == 404
    assert client.get(VIEWS, headers={H: ws}).json()["data"] == []
    ok = client.post(VIEWS, json={"object": "contact", "name": "Everyone", "columns": ["display_name", "created_at"]},
                     headers={H: ws})
    assert ok.status_code == 201 and ok.json()["filter"] == {} and ok.json()["sort"] == []


def test_a_view_is_changed_and_deleted_and_survives_an_archived_field(crm):
    client, ws, _ = crm
    people(client, ws)
    client.post(f"{OBJECTS}/contact/fields", json={"key": "score", "label": "Score", "type": "number"}, headers={H: ws})
    view = make_view(client, ws, filter={"field": "score", "op": "gt", "value": 1}, columns=["score"])
    path = f"{VIEWS}/{view['id']}"
    r = client.patch(path, json={"name": "Hot", "shared": True, "sort": ["-score"]}, headers={H: ws})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["shared"], r.json()["sort"]) == ("Hot", True, ["-score"])
    assert r.json()["updated_at"] > view["updated_at"] and r.json()["filter"] == view["filter"]
    for body in ({"filter": {"field": "nope", "op": "is", "value": 1}}, {"columns": ["nope"]}, {"sort": ["nope"]}):
        assert client.patch(path, json=body, headers={H: ws}).status_code in (400, 422), body
    for body in ({"name": None}, {"filter": None}, {"shared": None}):
        assert client.patch(path, json=body, headers={H: ws}).status_code == 422, body

    client.delete(f"{OBJECTS}/contact/fields/score", headers={H: ws})  # the view now names a field that is gone
    shown = client.get(path, headers={H: ws}).json()
    assert shown["name"] == "Hot" and "count" not in shown  # still readable, with no count
    assert client.get(VIEWS, params={"counts": "true"}, headers={H: ws}).status_code == 200
    assert client.get(f"{OBJECTS}/contact/records", params={"view": view["id"]}, headers={H: ws}).status_code == 400
    assert client.patch(path, json={"filter": LEADS, "columns": ["display_name"]}, headers={H: ws}).status_code == 200
    assert client.get(path, headers={H: ws}).json()["count"] == 3

    assert client.delete(path, headers={H: ws}).status_code == 204
    assert client.get(path, headers={H: ws}).status_code == 404
    assert client.delete(path, headers={H: ws}).status_code == 404
    assert client.patch(f"{VIEWS}/{uuid.uuid4()}", json={}, headers={H: ws}).status_code == 404


def test_shared_views_are_the_workspaces_and_private_views_only_their_owners(crm, db):
    client, ws, ids = crm  # an admin
    ann = add_member(db, ids["org_id"], "ann@example.com", workspace_id=ws)
    bob = add_member(db, ids["org_id"], "bob@example.com", workspace_id=ws)
    mine = make_view(ann, ws, name="Ann private")
    shared = make_view(ann, ws, name="Ann shared", shared=True)
    for who, expected in ((ann, {"Ann private", "Ann shared"}), (bob, {"Ann shared"}), (client, {"Ann shared"})):
        assert {v["name"] for v in who.get(VIEWS, headers={H: ws}).json()["data"]} == expected
    # a private view does not exist for anyone else: not even the admin
    for who in (bob, client):
        assert who.get(f"{VIEWS}/{mine['id']}", headers={H: ws}).status_code == 404
        assert who.patch(f"{VIEWS}/{mine['id']}", json={"name": "x"}, headers={H: ws}).status_code == 404
        assert who.delete(f"{VIEWS}/{mine['id']}", headers={H: ws}).status_code == 404
        assert who.get(f"{OBJECTS}/contact/records", params={"view": mine["id"]}, headers={H: ws}).status_code == 404
    assert ann.get(f"{VIEWS}/{mine['id']}", headers={H: ws}).json()["name"] == "Ann private"
    # a shared view is read by all, changed by its owner or an admin only
    assert bob.get(f"{VIEWS}/{shared['id']}", headers={H: ws}).json()["name"] == "Ann shared"
    assert bob.get(f"{OBJECTS}/contact/records", params={"view": shared["id"]}, headers={H: ws}).status_code == 200
    assert bob.patch(f"{VIEWS}/{shared['id']}", json={"name": "x"}, headers={H: ws}).status_code == 403
    assert bob.delete(f"{VIEWS}/{shared['id']}", headers={H: ws}).status_code == 403
    assert client.patch(f"{VIEWS}/{shared['id']}", json={"name": "By admin"}, headers={H: ws}).status_code == 200
    assert client.patch(f"{VIEWS}/{shared['id']}", json={"shared": False}, headers={H: ws}).status_code == 403
    assert ann.patch(f"{VIEWS}/{shared['id']}", json={"shared": False}, headers={H: ws}).status_code == 200
    assert {v["name"] for v in bob.get(VIEWS, headers={H: ws}).json()["data"]} == set()  # now private
    assert ann.patch(f"{VIEWS}/{mine['id']}", json={"shared": True}, headers={H: ws}).status_code == 200
    assert {v["name"] for v in bob.get(VIEWS, headers={H: ws}).json()["data"]} == {"Ann private"}
    assert client.delete(f"{VIEWS}/{mine['id']}", headers={H: ws}).status_code == 204  # admin removes a shared one
    # the filter by object, and the pages
    for n in range(3):
        make_view(bob, ws, name=f"deal view {n}", object="deal", filter={})
    assert len(client.get(VIEWS, params={"object": "deal"}, headers={H: ws}).json()["data"]) == 0  # bob's are private
    assert len(bob.get(VIEWS, params={"object": "deal"}, headers={H: ws}).json()["data"]) == 3
    first = bob.get(VIEWS, params={"limit": 2}, headers={H: ws}).json()
    rest = bob.get(VIEWS, params={"cursor": first["next_cursor"]}, headers={H: ws}).json()
    assert len(first["data"]) == 2 and len(rest["data"]) == 1 and rest["next_cursor"] is None
    assert bob.get(VIEWS, params={"object": "nothing"}, headers={H: ws}).status_code == 404


def test_creating_a_view_twice_with_the_same_key_creates_it_once(crm):
    client, ws, _ = crm
    body = {"object": "contact", "name": "Once", "filter": LEADS}
    one = client.post(VIEWS, json=body, headers={H: ws, "Idempotency-Key": "view-1"})
    two = client.post(VIEWS, json=body, headers={H: ws, "Idempotency-Key": "view-1"})
    assert one.json() == two.json() and len(client.get(VIEWS, headers={H: ws}).json()["data"]) == 1
