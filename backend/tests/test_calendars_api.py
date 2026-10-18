"""The calendars API: creating and changing calendars, their hosts and resources, what each role may do, the public
page and the link a workspace gets."""
import pytest
from calendar_api import H, instant, make_calendar, page, public_client, public_slots, visit, weekday_after
from helpers import add_member, audit, user_id_of
from sqlalchemy import text

from app import config

DAY = weekday_after(14)
CALENDARS = "/api/v1/calendars"


@pytest.fixture(autouse=True)
def roomy_limit(monkeypatch):
    monkeypatch.setattr(config, "BOOKING_MAX_PER_IP", 1000)


def test_a_calendar_starts_with_sensible_defaults_and_the_creator_as_its_host(crm):
    admin, ws, _ = crm
    r = admin.post(CALENDARS, json={"name": "Sales call"}, headers={H: ws})
    assert r.status_code == 201, r.text
    cal = r.json()
    assert (cal["slug"], cal["kind"], cal["durations"], cal["status"]) == ("sales-call", "personal", [30], "active")
    assert (cal["buffer_before"], cal["buffer_after"], cal["min_notice"], cal["window_days"]) == (0, 0, 240, 60)
    assert (cal["slot_interval"], cal["max_per_day"], cal["confirmation"]) == (30, None, "auto")
    assert cal["reminders"] == [1440, 60]
    assert [q["key"] for q in cal["questions"]] == ["name", "email", "phone"]
    assert all(q["required"] for q in cal["questions"])
    assert [(h["user_id"], h["weight"], h["active"]) for h in cal["hosts"]] == [(user_id_of(admin), 1, True)]
    assert cal["public_path"].startswith("/book/org-of-a-example-com-") and cal["public_path"].endswith("/sales-call")
    assert cal["public_url"].endswith(cal["public_path"])
    hours = admin.get(f"/api/v1/availability/users/{user_id_of(admin)}", headers={H: ws}).json()
    assert hours["saved"] and hours["weekly"]["mon"] == [["09:00", "17:00"]] and hours["time_zone"] == "UTC"
    assert [e["type"] for e in audit(admin, ws) if e["type"].startswith("calendar.")] == ["calendar.created"]
    again = admin.post(CALENDARS, json={"name": "Sales call"}, headers={H: ws}).json()
    assert again["slug"] == "sales-call-2"  # a clash gets a number
    assert admin.post(CALENDARS, json={"name": "X", "slug": "sales-call"}, headers={H: ws}).status_code == 409
    assert [c["slug"] for c in admin.get(CALENDARS, headers={H: ws}).json()["data"]] == ["sales-call", "sales-call-2"]


def test_settings_are_checked_and_changes_are_events(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    bad = {"durations": [10, 20, 30, 45], "time_zone": "Mars/Olympus", "reminders": [1, 2], "slug": "Not A Slug",
           "kind": "webinar", "buffer_after": 500, "color": "#fff", "seats": 0, "slot_interval": 1,
           "locations": [{"kind": "video", "value": "javascript:alert(1)"}],
           "questions": [{"key": "name", "label": "Name", "type": "text", "required": True}]}
    for key, value in bad.items():
        r = admin.patch(f"{CALENDARS}/{cal['id']}", json={key: value}, headers={H: ws})
        assert r.status_code == 422, (key, r.text)
        assert any(f.split(".")[0] == key for f in r.json()["error"]["fields"]), (key, r.json())
    r = admin.patch(f"{CALENDARS}/{cal['id']}", headers={H: ws}, json={
        "name": "Demo", "durations": [30, 60], "buffer_after": 10, "min_notice": 60, "max_per_day": 4,
        "confirmation": "manual", "reminders": [60, 1440], "cutoff_hours": 12,
        "locations": [{"kind": "video", "value": "https://meet.example.com/x"}, {"kind": "phone"}],
        "questions": [{"key": "name", "label": "Name", "type": "text", "required": True},
                      {"key": "email", "label": "Email", "type": "email", "required": True},
                      {"key": "phone", "label": "Phone", "type": "phone", "required": False},
                      {"key": "topic", "label": "Topic", "type": "long_text", "required": False}]})
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["name"], got["durations"], got["buffer_after"], got["max_per_day"], got["confirmation"]) == (
        "Demo", [30, 60], 10, 4, "manual") and got["reminders"] == [1440, 60] and got["cutoff_hours"] == 12
    assert got["slug"] == cal["slug"] and [q["key"] for q in got["questions"]][-1] == "topic"
    changed = audit(admin, ws, type="calendar.updated")[0]["data"]["changes"]
    assert changed["name"] == {"old": "Intro call", "new": "Demo"} and "slug" not in changed
    cleared = admin.patch(f"{CALENDARS}/{cal['id']}", json={"max_per_day": None}, headers={H: ws})
    assert cleared.json()["max_per_day"] is None
    assert admin.patch(f"{CALENDARS}/{cal['id']}", json={"name": None}, headers={H: ws}).status_code == 422
    renamed = admin.patch(f"{CALENDARS}/{cal['id']}", json={"slug": "demo-call"}, headers={H: ws})
    assert renamed.json()["slug"] == "demo-call"
    assert admin.get(f"{CALENDARS}/{cal['id']}", headers={H: ws}).json()["name"] == "Demo"


def test_a_calendar_with_bookings_is_archived_and_one_without_is_deleted(crm):
    admin, ws, _ = crm
    empty, used = make_calendar(admin, ws, name="Empty"), make_calendar(admin, ws, name="Used")
    assert admin.delete(f"{CALENDARS}/{empty['id']}", headers={H: ws}).status_code == 204
    assert admin.get(f"{CALENDARS}/{empty['id']}", headers={H: ws}).status_code == 404
    assert visit(public_client(), used, instant(DAY, "10:00")).status_code == 201
    r = admin.delete(f"{CALENDARS}/{used['id']}", headers={H: ws})
    assert r.status_code == 200 and r.json()["status"] == "archived"
    assert [c["name"] for c in admin.get(CALENDARS, headers={H: ws}).json()["data"]] == []
    archived = admin.get(CALENDARS, params={"archived": True}, headers={H: ws}).json()["data"]
    assert [c["name"] for c in archived] == ["Used"]
    visitor = public_client()
    assert visitor.get(page(used)).status_code == 404
    assert visit(visitor, used, instant(DAY, "11:00")).status_code == 404
    back = admin.patch(f"{CALENDARS}/{used['id']}", json={"status": "active"}, headers={H: ws})
    assert back.json()["status"] == "active"
    assert visitor.get(page(used)).status_code == 200
    types = [e["type"] for e in audit(admin, ws) if e["type"].startswith("calendar.")]
    assert types.count("calendar.deleted") == 1 and types.count("calendar.created") == 2


def test_a_paused_calendar_offers_nothing_and_says_so(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    admin.patch(f"{CALENDARS}/{cal['id']}", json={"status": "paused"}, headers={H: ws})
    visitor = public_client()
    assert visitor.get(page(cal)).json()["paused"] is True and public_slots(visitor, cal, DAY) == []
    assert visit(visitor, cal, instant(DAY, "10:00")).status_code == 409


def test_hosts_are_replaced_as_a_list_and_must_be_members(crm, db):
    admin, ws, ids = crm
    ben = add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws)
    outsider = add_member(db, ids["org_id"], "out@example.com")  # in the organization, not in this workspace
    me, ben_id = user_id_of(admin), user_id_of(ben)
    cal = make_calendar(admin, ws, kind="round_robin")
    put = f"{CALENDARS}/{cal['id']}/hosts"
    r = admin.put(put, json=[{"user_id": me, "weight": 2}, {"user_id": ben_id, "weight": 1, "priority": 3,
                                                          "daily_cap": 5}], headers={H: ws})
    assert r.status_code == 200, r.text
    assert [(h["user_id"], h["weight"], h["priority"], h["daily_cap"]) for h in r.json()["hosts"]] == [
        (me, 2, 0, None), (ben_id, 1, 3, 5)]
    assert admin.get(f"/api/v1/availability/users/{ben_id}", headers={H: ws}).json()["saved"]  # got the usual week
    assert admin.put(put, json=[{"user_id": user_id_of(outsider)}], headers={H: ws}).status_code == 422
    assert admin.put(put, json=[{"user_id": me}, {"user_id": me}], headers={H: ws}).status_code == 422
    assert admin.put(put, json=[{"user_id": me, "weight": 101}], headers={H: ws}).status_code == 422
    r = admin.put(put, json=[{"user_id": ben_id, "active": False}], headers={H: ws})  # me is removed, ben is paused
    assert [(h["user_id"], h["active"]) for h in r.json()["hosts"]] == [(ben_id, False)]
    personal = make_calendar(admin, ws, name="Personal")
    two = [{"user_id": me}, {"user_id": ben_id}]
    assert admin.put(f"{CALENDARS}/{personal['id']}/hosts", json=two, headers={H: ws}).status_code == 422
    admin.put(put, json=two, headers={H: ws})
    assert admin.patch(f"{CALENDARS}/{cal['id']}", json={"kind": "personal"}, headers={H: ws}).status_code == 422
    assert admin.patch(f"{CALENDARS}/{cal['id']}", json={"kind": "collective"}, headers={H: ws}).status_code == 200


def test_roles_decide_who_reads_who_books_and_who_manages(crm, db):
    admin, ws, ids = crm
    cal = make_calendar(admin, ws)
    assert visit(public_client(), cal, instant(DAY, "10:00")).status_code == 201
    [booking] = admin.get("/api/v1/bookings", headers={H: ws}).json()["data"]
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws, workspace_role="member")
    manager = add_member(db, ids["org_id"], "g@example.com", workspace_id=ws, workspace_role="manager")
    for who in (viewer, member, manager):
        assert who.get(CALENDARS, headers={H: ws}).status_code == 200
        assert who.get(f"{CALENDARS}/{cal['id']}/slots", params={"from": str(DAY), "to": str(DAY)},
                       headers={H: ws}).status_code == 200
        assert who.get("/api/v1/bookings", headers={H: ws}).json()["data"][0]["id"] == booking["id"]
        assert who.post(f"{CALENDARS}/{cal['id']}/simulate", headers={H: ws}).status_code == 200
    body = {"name": "Mine"}
    for who, capability in ((viewer, "calendars.manage"), (member, "calendars.manage")):
        r = who.post(CALENDARS, json=body, headers={H: ws})
        assert r.status_code == 403 and capability in r.json()["error"]["message"]
        assert who.patch(f"{CALENDARS}/{cal['id']}", json={"name": "x"}, headers={H: ws}).status_code == 403
        assert who.put(f"{CALENDARS}/{cal['id']}/hosts", json=[], headers={H: ws}).status_code == 403
        assert who.post("/api/v1/resources", json={"name": "Room"}, headers={H: ws}).status_code == 403
        assert who.delete(f"{CALENDARS}/{cal['id']}", headers={H: ws}).status_code == 403
    r = viewer.post(f"/api/v1/bookings/{booking['id']}/cancel", json={}, headers={H: ws})
    assert r.status_code == 403 and "calendars.write" in r.json()["error"]["message"]
    assert member.post(f"/api/v1/bookings/{booking['id']}/status", json={"status": "showed"},
                       headers={H: ws}).status_code == 200
    assert manager.post(CALENDARS, json=body, headers={H: ws}).status_code == 201
    assert manager.patch(f"{CALENDARS}/{cal['id']}", json={"name": "Renamed"}, headers={H: ws}).status_code == 200


def test_resources_are_shared_between_calendars_and_a_used_one_cannot_be_deleted(crm):
    admin, ws, _ = crm
    room = admin.post("/api/v1/resources", json={"name": "Room 1", "kind": "room"}, headers={H: ws}).json()
    assert room["quantity"] == 1 and room["kind"] == "room"
    studio = admin.post("/api/v1/resources", json={"name": "Camera", "kind": "equipment", "quantity": 2},
                        headers={H: ws}).json()
    assert [r["name"] for r in admin.get("/api/v1/resources", headers={H: ws}).json()["data"]] == ["Camera", "Room 1"]
    assert admin.patch(f"/api/v1/resources/{studio['id']}", json={"quantity": 3, "name": "Cameras"},
                       headers={H: ws}).json()["quantity"] == 3
    assert admin.post("/api/v1/resources", json={"name": "X", "quantity": 0}, headers={H: ws}).status_code == 422
    a, b = make_calendar(admin, ws, name="A call"), make_calendar(admin, ws, name="B call")
    for cal in (a, b):  # two calendars, one room; the second has a second host so only the room can stop it
        r = admin.put(f"{CALENDARS}/{cal['id']}/resources", json=[{"resource_id": room["id"]}], headers={H: ws})
        assert r.status_code == 200 and r.json()["resources"][0]["name"] == "Room 1"
    nobody = "00000000-0000-0000-0000-000000000000"
    ghost = admin.put(f"{CALENDARS}/{a['id']}/resources", json=[{"resource_id": nobody}], headers={H: ws})
    assert ghost.status_code == 422
    visitor = public_client()
    assert visit(visitor, a, instant(DAY, "10:00")).status_code == 201
    assert instant(DAY, "10:00") not in public_slots(visitor, b, DAY)  # the room is taken, and so is the one host
    admin.put(f"{CALENDARS}/{a['id']}/resources", json=[], headers={H: ws})
    assert admin.delete(f"/api/v1/resources/{room['id']}", headers={H: ws}).status_code == 409  # a booking holds it
    assert admin.delete(f"/api/v1/resources/{studio['id']}", headers={H: ws}).status_code == 204
    assert admin.delete(f"/api/v1/resources/{studio['id']}", headers={H: ws}).status_code == 404
    assert [e["type"] for e in audit(admin, ws) if e["type"].startswith("resource.")].count("resource.deleted") == 1


def test_the_booking_pages_are_served_and_the_public_api_may_be_called_from_any_site(crm, tmp_path, monkeypatch):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    (tmp_path / "book").mkdir()
    (tmp_path / "book" / "page.html").write_text("<!doctype html><title>Book</title>")
    monkeypatch.setattr(config, "FRONTEND_DIST", tmp_path)
    visitor = public_client()
    for path in (cal["public_path"], "/booking/abc.def"):
        r = visitor.get(path)
        assert r.status_code == 200 and "<title>Book</title>" in r.text, path
    r = visitor.get(page(cal), headers={"Origin": "https://customer.example.com"})
    assert r.headers["access-control-allow-origin"] == "*" and r.headers["cache-control"] == "no-store"
    pre = visitor.options(f"{page(cal)}/bookings", headers={"Origin": "https://customer.example.com",
                                                            "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 204 and "POST" in pre.headers["access-control-allow-methods"]
    assert "access-control-allow-origin" not in admin.get(CALENDARS, headers={H: ws}).headers  # the app itself: no
    assert visitor.get("/api/public/calendars/nobody/none").status_code == 404
    assert visitor.get(f"/api/public/calendars/{cal['public_path'].split('/')[2]}/none").status_code == 404


def test_a_workspace_gets_a_public_handle_and_two_of_one_name_get_different_ones(make_user, db):
    a, a_ids = make_user("a@example.com", "Acme Plumbing")
    b, b_ids = make_user("b@example.com", "Acme Plumbing")
    slugs = [s for (s,) in db.execute(text("SELECT slug FROM workspaces ORDER BY created_at"))]
    assert all(s.startswith("acme-plumbing-") and len(s) == len("acme-plumbing-") + 4 for s in slugs)
    assert len(set(slugs)) == 2
    created = a.post("/api/workspaces", json={"name": "Second Branch", "brand_id": a_ids["brand_id"]}).json()
    slug = db.scalar(text("SELECT slug FROM workspaces WHERE id = :i"), {"i": created["id"]})
    assert slug.startswith("second-branch-")
    assert b_ids["workspace_id"]
