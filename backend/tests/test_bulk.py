"""Bulk delete, restore and update (up to 1000 records in one call) and asking for tags back on a write."""
import uuid

from helpers import H, listing, make_record, names
from sqlalchemy import text

OBJECTS = "/api/v1/objects"
R = f"{OBJECTS}/contact/records"


def trash(client, ws, object_key="contact") -> list[dict]:
    r = client.get("/api/v1/trash", params={"object": object_key}, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_a_bulk_delete_and_restore_move_many_records_in_one_call_with_one_event_each(crm, db):
    client, ws, _ = crm
    ids = [make_record(client, ws, first_name=n)["id"] for n in ("Ada", "Grace", "Alan", "Edsger")]
    gone = client.post(f"{R}/delete", json={"ids": ids[:3] + ids[:1]}, headers={H: ws})  # a repeated id counts once
    assert gone.status_code == 200 and gone.json() == {"deleted": 3}
    assert names(listing(client, ws)) == ["Edsger"]
    assert sorted(r["display_name"] for r in trash(client, ws)) == ["Ada", "Alan", "Grace"]
    deleted = db.execute(text("SELECT subject_id, data, actor_type FROM events WHERE type = 'record.deleted'")).all()
    assert sorted(str(e.subject_id) for e in deleted) == sorted(ids[:3])
    assert all(e.actor_type == "user" and e.data["object"] == "contact" for e in deleted)

    # all or nothing: one id that is live (not in the trash) fails the whole restore
    refused = client.post(f"{R}/restore", json={"ids": [ids[0], ids[3]]}, headers={H: ws})
    assert refused.status_code == 404 and len(trash(client, ws)) == 3
    back = client.post(f"{R}/restore", json={"ids": ids[:2]}, headers={H: ws})
    assert back.status_code == 200 and back.json() == {"restored": 2}
    assert sorted(names(listing(client, ws))) == ["Ada", "Edsger", "Grace"]
    restored = db.scalars(text("SELECT subject_id FROM events WHERE type = 'record.restored'")).all()
    assert sorted(str(r) for r in restored) == sorted(ids[:2])
    # a delete naming a record that is already in the trash leaves the others alone
    again = client.post(f"{R}/delete", json={"ids": [ids[2], ids[3]]}, headers={H: ws})
    assert again.status_code == 404 and sorted(names(listing(client, ws))) == ["Ada", "Edsger", "Grace"]


def test_a_bulk_change_takes_one_to_a_thousand_ids_of_the_object_and_is_idempotent(crm, db):
    client, ws, _ = crm
    one, company = make_record(client, ws, first_name="Ada"), make_record(client, ws, "company", name="Acme")
    for path, body in ((f"{R}/delete", {"ids": []}), (f"{R}/restore", {"ids": [str(uuid.uuid4())] * 1001}),
                       (f"{R}/delete", {}), (f"{R}/delete", {"ids": ["not-an-id"]})):
        refused = client.post(path, json=body, headers={H: ws})
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "validation_failed", body
    thousand = [str(uuid.uuid4()) for _ in range(1000)]
    assert client.post(f"{R}/delete", json={"ids": thousand}, headers={H: ws}).status_code == 404  # allowed, unknown
    # a record of another object is not found through this one, and an unknown object is a 404
    assert client.post(f"{R}/delete", json={"ids": [company["id"]]}, headers={H: ws}).status_code == 404
    unknown = client.post(f"{OBJECTS}/nothing/records/delete", json={"ids": [one["id"]]}, headers={H: ws})
    assert unknown.status_code == 404
    body = {"ids": [one["id"]]}
    first = client.post(f"{R}/delete", json=body, headers={H: ws, "Idempotency-Key": "bulk-1"})
    replay = client.post(f"{R}/delete", json=body, headers={H: ws, "Idempotency-Key": "bulk-1"})
    assert first.json() == replay.json() == {"deleted": 1} and replay.headers["Idempotent-Replayed"] == "true"
    assert db.scalar(text("SELECT count(*) FROM events WHERE type = 'record.deleted'")) == 1


def test_a_bulk_delete_of_a_thousand_records_is_one_statement_worth_of_work(crm, db):
    client, ws, _ = crm
    # inserted directly: a thousand API calls would be the slow part of this test, not the thing it checks
    db.execute(text("INSERT INTO records (workspace_id, object_id, display_name, values) "
                    "SELECT o.workspace_id, o.id, 'Person ' || n, '{}' FROM objects o, generate_series(1, 1000) n "
                    "WHERE o.workspace_id = :w AND o.key = 'contact'"), {"w": ws})
    db.commit()
    ids = db.scalars(text("SELECT id FROM records WHERE workspace_id = :w"), {"w": ws}).all()
    assert len(ids) == 1000
    done = client.post(f"{R}/delete", json={"ids": [str(i) for i in ids]}, headers={H: ws})
    assert done.status_code == 200 and done.json() == {"deleted": 1000}
    assert db.scalar(text("SELECT count(*) FROM events WHERE type = 'record.deleted'")) == 1000
    assert db.scalar(text("SELECT count(*) FROM records WHERE deleted_at IS NOT NULL")) == 1000


def test_a_write_can_ask_for_the_tags_back_like_a_read(crm):
    client, ws, _ = crm
    tag = client.post("/api/v1/tags", json={"name": "vip"}, headers={H: ws}).json()
    created = client.post(R, json={"values": {"first_name": "Ada"}}, params={"include": "tags"}, headers={H: ws}).json()
    assert created["tags"] == []
    assert "tags" not in client.post(R, json={"values": {"first_name": "Bo"}}, headers={H: ws}).json()
    client.post(f"/api/v1/records/{created['id']}/tags", json={"add": [tag["id"]]}, headers={H: ws})
    path = f"{R}/{created['id']}"
    patched = client.patch(path, json={"values": {"last_name": "Lovelace"}}, params={"include": "tags"},
                           headers={H: ws})
    assert [t["name"] for t in patched.json()["tags"]] == ["vip"] and patched.json()["display_name"] == "Ada Lovelace"
    assert "tags" not in client.patch(path, json={"values": {"last_name": "L"}}, headers={H: ws}).json()
    bad = client.patch(path, json={"values": {}}, params={"include": "ghosts"}, headers={H: ws})
    assert bad.status_code == 400 and "include" in bad.json()["error"]["fields"]
    # a refused include changes nothing: the name is what the last good patch left
    assert client.get(path, headers={H: ws}).json()["display_name"] == "Ada L"


def test_a_bulk_update_changes_many_records_all_or_nothing_and_emits_only_for_real_changes(crm, db):
    client, ws, _ = crm
    me = client.get("/api/me").json()["user"]["id"]
    ids = [make_record(client, ws, first_name=n)["id"] for n in ("Ada", "Grace", "Alan")]
    mine = client.post(f"{R}/update", json={"ids": ids, "owner_id": me}, headers={H: ws})
    assert mine.status_code == 200 and mine.json() == {"updated": 3}
    assert {r["owner_id"] for r in listing(client, ws)["data"]} == {me}
    back = client.post(f"{R}/update", json={"ids": ids[1:], "owner_id": None, "values": {"last_name": "Austin"}},
                       headers={H: ws})
    assert back.status_code == 200 and back.json() == {"updated": 2}
    rows = {r["id"]: r for r in listing(client, ws)["data"]}
    assert [rows[i]["owner_id"] for i in ids] == [me, None, None]
    assert [rows[i]["values"].get("last_name") for i in ids] == [None, "Austin", "Austin"]
    # the same change again changes nothing and emits nothing
    events = db.scalar(text("SELECT count(*) FROM events WHERE type = 'record.updated'"))
    same = client.post(f"{R}/update", json={"ids": ids[1:], "owner_id": None, "values": {"last_name": "Austin"}},
                       headers={H: ws})
    assert same.json() == {"updated": 0}
    assert db.scalar(text("SELECT count(*) FROM events WHERE type = 'record.updated'")) == events
    # one bad value or one unknown id refuses the whole batch
    bad = client.post(f"{R}/update", json={"ids": ids, "values": {"email": "not an email"}}, headers={H: ws})
    assert bad.status_code == 422
    unknown = client.post(f"{R}/update", json={"ids": [ids[0], str(uuid.uuid4())], "values": {"last_name": "Oslo"}},
                          headers={H: ws})
    assert unknown.status_code == 404
    assert {r["values"].get("last_name") for r in listing(client, ws)["data"]} == {"Austin", None}
    empty = client.post(f"{R}/update", json={"ids": ids}, headers={H: ws})
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "validation_failed"
