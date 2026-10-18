"""Tags: creation, usage counts, rename, merge with a preview, delete, and adding or removing them on records."""
import uuid

from helpers import H, add_member, make_record, make_role, names, rule, user_id_of
from sqlalchemy import text

TAGS = "/api/v1/tags"
R = "/api/v1/objects/contact/records"


def tag(client, ws, name, **body) -> dict:
    r = client.post(TAGS, json={"name": name, **body}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def put(client, ws, record_id, add=(), remove=()) -> dict:
    r = client.post(f"/api/v1/records/{record_id}/tags", json={"add": list(add), "remove": list(remove)},
                    headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def listed(client, ws, **params) -> dict:
    r = client.get(TAGS, params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def events_of(db, kind) -> list[dict]:
    db.expire_all()
    return [e for (e,) in db.execute(text("SELECT data FROM events WHERE type = :t ORDER BY id"), {"t": kind})]


def test_a_tag_has_a_group_color_description_and_a_unique_name(crm, db):
    client, ws, ids = crm
    vip = tag(client, ws, " VIP ", color="#ff0000", group="Segments", description="Big spenders")
    assert (vip["name"], vip["color"], vip["group"], vip["description"], vip["count"]) == (
        "VIP", "#ff0000", "Segments", "Big spenders", 0)
    for name in ("vip", "Vip", "VIP"):
        r = client.post(TAGS, json={"name": name}, headers={H: ws})
        assert r.status_code == 409 and r.json()["error"]["code"] == "tag_exists", name
    assert client.post(TAGS, json={"name": ""}, headers={H: ws}).status_code == 422
    assert client.post(TAGS, json={"name": "x" * 101}, headers={H: ws}).status_code == 422
    assert client.post(TAGS, json={"name": "ok", "color": "x" * 21}, headers={H: ws}).status_code == 422
    assert client.post(TAGS, json={"name": "a\u0000b"}, headers={H: ws}).status_code == 422
    plain = tag(client, ws, "plain")
    assert plain["color"] is None and plain["group"] is None and plain["description"] is None
    assert [t["name"] for t in listed(client, ws)["data"]] == ["plain", "VIP"]  # newest first, like every list
    assert [t["name"] for t in listed(client, ws, q="v")["data"]] == ["VIP"]
    assert [t["name"] for t in listed(client, ws, q="PL")["data"]] == ["plain"]
    assert listed(client, ws, q="%")["data"] == [] and listed(client, ws, q="nothing")["data"] == []
    assert events_of(db, "tag.created")[0] == {"id": vip["id"], "name": "VIP", "color": "#ff0000", "group": "Segments",
                                               "description": "Big spenders"}
    # the same name is free in another workspace
    other_ws = client.post("/api/workspaces", json={"name": "B", "brand_id": ids["brand_id"]}).json()["id"]
    assert tag(client, other_ws, "VIP")["name"] == "VIP"
    assert len(listed(client, other_ws)["data"]) == 1


def test_tags_list_with_usage_counts_that_ignore_the_trash(crm):
    client, ws, _ = crm
    vip, beta = tag(client, ws, "vip"), tag(client, ws, "beta")
    people = [make_record(client, ws, first_name=n) for n in ("a", "b", "c")]
    for p in people:
        put(client, ws, p["id"], add=[vip["id"]])
    put(client, ws, people[0]["id"], add=[beta["id"]])
    counts = {t["name"]: t["count"] for t in listed(client, ws)["data"]}
    assert counts == {"vip": 3, "beta": 1}
    client.delete(f"{R}/{people[1]['id']}", headers={H: ws})
    assert {t["name"]: t["count"] for t in listed(client, ws)["data"]} == {"vip": 2, "beta": 1}
    client.post(f"{R}/{people[1]['id']}/restore", headers={H: ws})
    assert {t["name"]: t["count"] for t in listed(client, ws)["data"]}["vip"] == 3
    page = listed(client, ws, limit=1)
    assert len(page["data"]) == 1 and page["next_cursor"]
    assert [t["name"] for t in listed(client, ws, limit=1, cursor=page["next_cursor"])["data"]] == ["vip"]


def test_a_tag_is_renamed_edited_and_deleted_by_an_admin(crm, db):
    client, ws, _ = crm
    vip = tag(client, ws, "vip")
    tag(client, ws, "other")
    ada = make_record(client, ws, first_name="Ada")
    put(client, ws, ada["id"], add=[vip["id"]])
    r = client.patch(f"{TAGS}/{vip['id']}", json={"name": "VIPs", "color": "gold", "group": "Segments"},
                     headers={H: ws})
    assert r.status_code == 200 and (r.json()["name"], r.json()["color"], r.json()["count"]) == ("VIPs", "gold", 1)
    updated = events_of(db, "tag.updated")[0]
    assert updated["changes"] == {"name": {"old": "vip", "new": "VIPs"}, "color": {"old": None, "new": "gold"},
                                  "group": {"old": None, "new": "Segments"}} and updated["name"] == "VIPs"
    assert client.patch(f"{TAGS}/{vip['id']}", json={"name": "vips"}, headers={H: ws}).status_code == 200  # own name
    assert client.patch(f"{TAGS}/{vip['id']}", json={"name": "OTHER"}, headers={H: ws}).status_code == 409
    assert client.patch(f"{TAGS}/{vip['id']}", json={"name": None}, headers={H: ws}).status_code == 422
    assert client.patch(f"{TAGS}/{vip['id']}", json={"color": None}, headers={H: ws}).json()["color"] is None
    count = len(events_of(db, "tag.updated"))
    client.patch(f"{TAGS}/{vip['id']}", json={"color": None}, headers={H: ws})  # nothing changed: no event
    assert len(events_of(db, "tag.updated")) == count
    assert client.patch(f"{TAGS}/{uuid.uuid4()}", json={}, headers={H: ws}).status_code == 404

    assert client.delete(f"{TAGS}/{vip['id']}", headers={H: ws}).status_code == 204
    assert [t["name"] for t in listed(client, ws)["data"]] == ["other"]
    assert db.scalar(text("SELECT count(*) FROM record_tags")) == 0  # its links went with it
    assert events_of(db, "tag.deleted")[0]["records"] == 1 and events_of(db, "tag.deleted")[0]["name"] == "vips"
    assert client.delete(f"{TAGS}/{vip['id']}", headers={H: ws}).status_code == 404
    assert client.get(f"{R}/{ada['id']}", params={"include": "tags"}, headers={H: ws}).json()["tags"] == []


def test_merge_previews_then_moves_every_record_and_removes_the_old_tag(crm, db):
    client, ws, _ = crm
    old, new, bystander = tag(client, ws, "vip"), tag(client, ws, "VIP customers"), tag(client, ws, "beta")
    people = [make_record(client, ws, first_name=n) for n in "abcde"]
    for p in people[:4]:
        put(client, ws, p["id"], add=[old["id"]])
    for p in people[2:]:  # c and d have both, e only the new one
        put(client, ws, p["id"], add=[new["id"]])
    put(client, ws, people[0]["id"], add=[bystander["id"]])
    client.delete(f"{R}/{people[3]['id']}", headers={H: ws})  # a trashed record is not counted

    path = f"{TAGS}/{old['id']}/merge"
    preview = client.post(path, json={"into": new["id"], "preview": True}, headers={H: ws})
    assert preview.status_code == 200
    assert (preview.json()["preview"], preview.json()["records"], preview.json()["gaining"]) == (True, 3, 2)
    assert preview.json()["source"]["name"] == "vip" and preview.json()["into"]["name"] == "VIP customers"
    assert len(listed(client, ws)["data"]) == 3  # a preview changes nothing
    assert db.scalar(text("SELECT count(*) FROM record_tags")) == 4 + 3 + 1
    assert client.post(path, json={"into": old["id"]}, headers={H: ws}).status_code == 422
    assert client.post(path, json={"into": str(uuid.uuid4())}, headers={H: ws}).status_code == 404
    assert client.post(f"{TAGS}/{uuid.uuid4()}/merge", json={"into": new["id"]}, headers={H: ws}).status_code == 404

    done = client.post(path, json={"into": new["id"]}, headers={H: ws})
    assert done.status_code == 200 and done.json()["preview"] is False and done.json()["records"] == 3
    assert {t["name"]: t["count"] for t in listed(client, ws)["data"]} == {"VIP customers": 4, "beta": 1}
    assert sorted(names(client.get(R, params={"filter": '{"tag": "VIP customers"}'}, headers={H: ws}).json())) == [
        "a", "b", "c", "e"]  # d is in the trash
    merged = events_of(db, "tag.merged")
    assert merged == [{"id": new["id"], "name": "VIP customers", "source_id": old["id"], "source_name": "vip",
                       "records": 3}]
    assert client.post(path, json={"into": new["id"]}, headers={H: ws}).status_code == 404  # the old tag is gone
    assert db.scalar(text("SELECT count(*) FROM record_tags WHERE tag_id = :t"), {"t": old["id"]}) == 0
    # a merge the trash has not seen: d keeps the merged tag, so restoring it shows the new one
    client.post(f"{R}/{people[3]['id']}/restore", headers={H: ws})
    restored = client.get(f"{R}/{people[3]['id']}", params={"include": "tags"}, headers={H: ws}).json()
    assert [t["name"] for t in restored["tags"]] == ["VIP customers"]


def test_tags_are_added_and_removed_on_one_record_with_an_event_for_each_change(crm, db):
    client, ws, _ = crm
    vip, beta = tag(client, ws, "vip"), tag(client, ws, "beta")
    ada = make_record(client, ws, first_name="Ada")
    assert put(client, ws, ada["id"], add=[vip["id"], beta["id"]]) == {"added": 2, "removed": 0}
    assert put(client, ws, ada["id"], add=[vip["id"]]) == {"added": 0, "removed": 0}  # already there
    assert put(client, ws, ada["id"], remove=[beta["id"]], add=[]) == {"added": 0, "removed": 1}
    assert put(client, ws, ada["id"], remove=[beta["id"]]) == {"added": 0, "removed": 0}
    one = client.get(f"{R}/{ada['id']}", params={"include": "tags"}, headers={H: ws}).json()
    assert one["tags"] == [{"id": vip["id"], "name": "vip", "color": None}]
    added, removed = events_of(db, "tag.added"), events_of(db, "tag.removed")
    assert [(e["name"], e["record_id"], e["object"]) for e in added] == [("vip", ada["id"], "contact"),
                                                                       ("beta", ada["id"], "contact")]
    assert [(e["name"], e["tag_id"]) for e in removed] == [("beta", beta["id"])]
    subject = db.execute(text("SELECT DISTINCT subject_type, subject_id::text FROM events "
                              "WHERE type = 'tag.added'")).all()
    assert subject == [("record", ada["id"])]  # shows on the record's own timeline


    def bad(**body):
        return client.post(f"/api/v1/records/{ada['id']}/tags", json=body, headers={H: ws})

    assert bad(add=[str(uuid.uuid4())]).status_code == 404
    assert bad(remove=[str(uuid.uuid4())]).status_code == 404
    assert bad(add=[vip["id"]], remove=[vip["id"]]).status_code == 422
    assert bad(add=[str(uuid.uuid4()) for _ in range(11)]).status_code == 422  # ten at most, each is an event
    assert bad(add=["nope"]).status_code == 422
    assert client.post(f"/api/v1/records/{uuid.uuid4()}/tags", json={}, headers={H: ws}).status_code == 404
    client.delete(f"{R}/{ada['id']}", headers={H: ws})
    assert bad(add=[vip["id"]]).status_code == 404  # no tagging a record in the trash


def test_bulk_tagging_takes_up_to_a_thousand_records_in_one_call(crm, db, monkeypatch):
    client, ws, _ = crm
    vip, beta = tag(client, ws, "vip"), tag(client, ws, "beta")
    # a thousand records, written straight to the table so the test stays quick
    db.execute(text("""INSERT INTO records (workspace_id, object_id, display_name, "values")
                       SELECT CAST(:w AS uuid), o.id, 'bulk ' || g, jsonb_build_object('first_name', 'bulk ' || g)
                       FROM objects o, generate_series(1, 1001) g WHERE o.workspace_id = :w AND o.key = 'contact'"""),
               {"w": ws})
    db.commit()
    ids = [str(i) for i in db.scalars(text("SELECT id FROM records ORDER BY display_name"))]
    r = client.post("/api/v1/records/tags", json={"record_ids": ids[:1000], "add": [vip["id"]]}, headers={H: ws})
    assert r.status_code == 200 and r.json() == {"added": 1000, "removed": 0}
    assert listed(client, ws)["data"][1]["count"] == 1000
    assert db.scalar(text("SELECT count(*) FROM events WHERE type = 'tag.added'")) == 1000
    assert client.post("/api/v1/records/tags", json={"record_ids": ids, "add": [vip["id"]]},
                       headers={H: ws}).status_code == 422  # 1001 records
    r = client.post("/api/v1/records/tags", json={"record_ids": ids[:500], "remove": [vip["id"]], "add": [beta["id"]]},
                    headers={H: ws})
    assert r.json() == {"added": 500, "removed": 500}
    assert {t["name"]: t["count"] for t in listed(client, ws)["data"]} == {"vip": 500, "beta": 500}
    assert db.scalar(text("SELECT count(*) FROM jobs WHERE kind = 'events.dispatch'")) <= 12  # one wake-up per call
    for body in ({"record_ids": []}, {"record_ids": ["x"]}, {}):
        assert client.post("/api/v1/records/tags", json=body, headers={H: ws}).status_code == 422
    unknown = client.post("/api/v1/records/tags", json={"record_ids": [ids[0], str(uuid.uuid4())], "add": [vip["id"]]},
                          headers={H: ws})
    assert unknown.status_code == 404  # all or nothing
    assert {t["name"]: t["count"] for t in listed(client, ws)["data"]}["vip"] == 500


def test_members_apply_tags_but_only_admins_rename_merge_and_delete(crm, db):
    client, ws, ids = crm
    vip, other = tag(client, ws, "vip"), tag(client, ws, "other")
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    ada = make_record(member, ws, first_name="Ada")
    assert tag(member, ws, "from member")["name"] == "from member"
    assert put(member, ws, ada["id"], add=[vip["id"]]) == {"added": 1, "removed": 0}
    assert member.get(TAGS, headers={H: ws}).status_code == 200
    for method, path, body in [("PATCH", f"{TAGS}/{vip['id']}", {"name": "x"}), ("DELETE", f"{TAGS}/{vip['id']}", None),
                               ("POST", f"{TAGS}/{vip['id']}/merge", {"into": other["id"]})]:
        r = member.request(method, path, json=body, headers={H: ws})
        assert r.status_code == 403, (method, path)
    assert {t["name"] for t in listed(client, ws)["data"]} == {"vip", "other", "from member"}


def test_tagging_needs_write_on_the_records_object_and_merge_counts_only_what_the_caller_sees(crm, db):
    client, ws, ids = crm
    vip, other = tag(client, ws, "vip"), tag(client, ws, "other")
    reader = make_role(client, ws, "Tagging reader", copy_from="viewer", capabilities=[
        "contacts.read", "schema.read", "tags.write"])
    keeper = make_role(client, ws, "Own tag keeper", copy_from="viewer", capabilities=[
        "contacts.read", "schema.read", "tags.write", "tags.manage"], rules=[rule("*", "own")])
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role=reader["key"])
    lead = add_member(db, ids["org_id"], "k@example.com", workspace_id=ws, workspace_role=keeper["key"])
    ada = make_record(client, ws, first_name="Ada")
    mine = make_record(client, ws, first_name="Mine", owner_id=user_id_of(lead))
    r = viewer.post(f"/api/v1/records/{ada['id']}/tags", json={"add": [vip["id"]]}, headers={H: ws})
    assert r.status_code == 403 and "contacts.write" in r.json()["error"]["message"]
    for record in (ada, mine):
        put(client, ws, record["id"], add=[vip["id"]])
    preview = lead.post(f"{TAGS}/{vip['id']}/merge", json={"into": other["id"], "preview": True}, headers={H: ws})
    assert (preview.json()["records"], preview.json()["gaining"]) == (1, 1)  # Ada is outside the lead's scope
