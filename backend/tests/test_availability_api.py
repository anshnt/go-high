"""Working hours, date overrides and imported busy time through the API, and what they do to the open times."""
from datetime import timedelta

import pytest
from calendar_api import H, instant, make_calendar, moment, public_client, public_slots, visit, weekday_after
from calendar_helpers import LON, at
from helpers import add_member, audit, user_id_of
from sqlalchemy import text

from app import config

DAY = weekday_after(14)
A = "/api/v1/availability"


@pytest.fixture(autouse=True)
def roomy_limit(monkeypatch):
    monkeypatch.setattr(config, "BOOKING_MAX_PER_IP", 1000)


def hours(client, ws, who, **body):
    return client.put(f"{A}/users/{who}", json=body, headers={H: ws})


def test_hours_default_to_a_week_until_saved_and_saving_changes_what_is_offered(crm):
    admin, ws, _ = crm
    me = user_id_of(admin)
    seen = admin.get(f"{A}/users/{me}", headers={H: ws}).json()
    assert not seen["saved"] and seen["weekly"]["mon"] == [["09:00", "17:00"]] and seen["weekly"]["sat"] == []
    assert seen["sync"] == {"status": "none", "synced_at": None, "error": None} and seen["overrides"] == {}
    cal = make_calendar(admin, ws)
    visitor = public_client()
    week = {d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")} | {"tue": [["13:00", "15:00"]]}
    r = hours(admin, ws, me, time_zone="America/New_York", weekly=week)
    assert r.status_code == 200 and r.json()["saved"] and r.json()["weekly"]["tue"] == [["13:00", "15:00"]]
    assert public_slots(visitor, cal, DAY) == [instant(DAY, "13:00"), instant(DAY, "13:30"), instant(DAY, "14:00"),
                                               instant(DAY, "14:30")]
    # the same hours read in London are five hours earlier in New York
    hours(admin, ws, me, time_zone="Europe/London", weekly=week)
    assert public_slots(visitor, cal, DAY)[0] == at(str(DAY), "13:00", LON).isoformat()
    assert public_slots(visitor, cal, DAY, "Europe/London")[0] == at(str(DAY), "13:00", LON).isoformat()
    assert audit(admin, ws, type="availability.updated")[0]["data"] == {"owner": "users", "id": me, "change": "weekly"}


def test_hours_that_make_no_sense_are_refused(crm):
    admin, ws, _ = crm
    me = user_id_of(admin)
    week = {"mon": [["09:00", "17:00"]]}
    for bad in ({"time_zone": "Mars/Olympus", "weekly": week},
                {"time_zone": "UTC", "weekly": {"mon": [["17:00", "09:00"]]}},
                {"time_zone": "UTC", "weekly": {"funday": []}}, {"time_zone": "UTC", "weekly": {"mon": [["9", "10"]]}},
                {"time_zone": "UTC"}, {"weekly": week}):
        assert hours(admin, ws, me, **bad).status_code == 422, bad
    assert admin.get(f"{A}/users/00000000-0000-0000-0000-000000000000", headers={H: ws}).status_code == 404
    assert admin.get(f"{A}/teams/{me}", headers={H: ws}).status_code == 422


def test_a_date_override_is_a_day_off_or_short_hours_and_deleting_it_restores_the_week(crm):
    admin, ws, _ = crm
    me = user_id_of(admin)
    cal = make_calendar(admin, ws)
    hours(admin, ws, me, time_zone="America/New_York", weekly={d: [["09:00", "17:00"]] for d in (
        "mon", "tue", "wed", "thu", "fri")} | {"sat": [], "sun": []})
    visitor, url = public_client(), f"{A}/users/{me}/overrides/{DAY}"
    r = admin.put(url, json={"hours": []}, headers={H: ws})
    assert r.status_code == 200 and r.json()["overrides"] == {str(DAY): []}
    assert public_slots(visitor, cal, DAY) == [] and len(public_slots(visitor, cal, DAY + timedelta(days=1))) == 16
    r = admin.put(url, json={"hours": [["10:00", "11:00"]]}, headers={H: ws})
    assert public_slots(visitor, cal, DAY) == [instant(DAY, "10:00"), instant(DAY, "10:30")]
    sunday = DAY + timedelta(days=5)
    admin.put(f"{A}/users/{me}/overrides/{sunday}", json={"hours": [["12:00", "13:00"]]}, headers={H: ws})
    assert public_slots(visitor, cal, sunday) == [instant(sunday, "12:00"), instant(sunday, "12:30")]  # a day opened
    assert admin.delete(url, headers={H: ws}).json()["overrides"] == {str(sunday): [["12:00", "13:00"]]}
    assert len(public_slots(visitor, cal, DAY)) == 16
    assert admin.delete(url, headers={H: ws}).status_code == 404
    for bad in ({"hours": [["11:00", "10:00"]]}, {"hours": "closed"}, {}):
        assert admin.put(url, json=bad, headers={H: ws}).status_code == 422
    assert admin.put(f"{A}/users/{me}/overrides/not-a-date", json={"hours": []}, headers={H: ws}).status_code == 422


def test_people_change_their_own_hours_and_managers_change_anyones(crm, db):
    admin, ws, ids = crm
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws, workspace_role="member")
    manager = add_member(db, ids["org_id"], "g@example.com", workspace_id=ws, workspace_role="manager")
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    week = {"time_zone": "UTC", "weekly": {"mon": [["08:00", "12:00"]]}}
    mine, theirs = user_id_of(member), user_id_of(admin)
    assert hours(member, ws, mine, **week).status_code == 200
    r = hours(member, ws, theirs, **week)
    assert r.status_code == 403 and "your own hours" in r.json()["error"]["message"]
    assert member.put(f"{A}/users/{theirs}/overrides/{DAY}", json={"hours": []}, headers={H: ws}).status_code == 403
    assert hours(manager, ws, mine, **week).status_code == 200
    assert hours(manager, ws, theirs, **week).status_code == 200
    r = hours(viewer, ws, user_id_of(viewer), **week)
    assert r.status_code == 403 and "calendars.write" in r.json()["error"]["message"]
    assert viewer.get(f"{A}/users/{mine}", headers={H: ws}).status_code == 200
    room = admin.post("/api/v1/resources", json={"name": "Room"}, headers={H: ws}).json()
    assert hours(member, ws, room["id"], **week).status_code == 404  # not a person
    r = member.put(f"{A}/resources/{room['id']}", json=week, headers={H: ws})
    assert r.status_code == 403 and "calendars.manage" in r.json()["error"]["message"]
    saved = admin.put(f"{A}/resources/{room['id']}", json=week, headers={H: ws})
    assert saved.json()["weekly"]["mon"] == [["08:00", "12:00"]]
    assert admin.get(f"{A}/resources/{room['id']}", headers={H: ws}).json()["sync"] is None


def test_imported_busy_time_hides_slots_and_a_reread_of_the_range_replaces_it(crm):
    admin, ws, _ = crm
    me = user_id_of(admin)
    cal = make_calendar(admin, ws)
    visitor = public_client()
    start, end = at(str(DAY), "10:15"), at(str(DAY), "11:15")
    block = {"start": start.isoformat(), "end": end.isoformat(), "external_id": "evt-1"}
    r = admin.post(f"{A}/busy", json={"source": "calendar_a", "blocks": [block]}, headers={H: ws})
    assert r.status_code == 200 and r.json()["imported"] == 1 and r.json()["sync"]["status"] == "ok"
    times = public_slots(visitor, cal, DAY)
    assert {instant(DAY, "10:00"), instant(DAY, "10:30"), instant(DAY, "11:00")}.isdisjoint(times)
    assert instant(DAY, "09:30") in times and instant(DAY, "11:30") in times
    moved = {**block, "start": at(str(DAY), "14:00").isoformat(), "end": at(str(DAY), "14:30").isoformat()}
    admin.post(f"{A}/busy", json={"source": "calendar_a", "blocks": [moved]}, headers={H: ws})  # same id: updated
    times = public_slots(visitor, cal, DAY)
    assert instant(DAY, "10:00") in times and instant(DAY, "14:00") not in times
    other = {"start": at(str(DAY), "09:00").isoformat(), "end": at(str(DAY), "09:30").isoformat()}
    admin.post(f"{A}/busy", json={"source": "calendar_b", "blocks": [other]}, headers={H: ws})
    assert instant(DAY, "09:00") not in public_slots(visitor, cal, DAY)
    replace = {"source": "calendar_a", "blocks": [], "replace_from": at(str(DAY), "00:00").isoformat(),
               "replace_to": at(str(DAY + timedelta(days=1)), "00:00").isoformat()}
    admin.post(f"{A}/busy", json=replace, headers={H: ws})  # the day is empty in the outside calendar now
    times = public_slots(visitor, cal, DAY)
    assert instant(DAY, "14:00") in times and instant(DAY, "09:00") not in times  # the other source stays
    seen = admin.get(f"{A}/users/{me}", headers={H: ws}).json()["sync"]
    assert seen["status"] == "ok" and moment(seen["synced_at"]) and seen["error"] is None
    assert visit(visitor, cal, instant(DAY, "09:00")).status_code == 409  # booking honours it as well


def test_sync_health_reports_errors_and_goes_stale(crm, db):
    admin, ws, _ = crm
    me = user_id_of(admin)
    admin.post(f"{A}/busy", json={"blocks": [], "status": "error", "error": "token expired"}, headers={H: ws})
    seen = admin.get(f"{A}/users/{me}", headers={H: ws}).json()
    assert seen["sync"]["status"] == "error" and seen["sync"]["error"] == "token expired"
    assert seen["saved"] is False  # the row only carries the sync health, so the person still has no hours
    admin.post(f"{A}/busy", json={"blocks": []}, headers={H: ws})
    ok = admin.get(f"{A}/users/{me}", headers={H: ws}).json()["sync"]
    assert ok["status"] == "ok" and ok["error"] is None and ok["synced_at"]
    db.execute(text("UPDATE availability SET synced_at = now() - interval '2 days'"))
    db.commit()
    assert admin.get(f"{A}/users/{me}", headers={H: ws}).json()["sync"]["status"] == "stale"


def test_busy_blocks_are_checked_and_only_managers_import_for_others(crm, db):
    admin, ws, ids = crm
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    t0, t1 = at(str(DAY), "10:00").isoformat(), at(str(DAY), "11:00").isoformat()
    for bad in ({"blocks": [{"start": t1, "end": t0}]}, {"blocks": [{"start": "2026-01-01T10:00:00", "end": t1}]},
                {"blocks": [{"start": t0, "end": t1}], "source": "Not Valid!"}, {"blocks": [{"start": t0, "end": t1}],
                                                                                  "replace_from": t0},
                {"blocks": [{"start": t0, "end": t1}] * 2001}, {}):
        assert admin.post(f"{A}/busy", json=bad, headers={H: ws}).status_code == 422, str(bad)[:80]
    good = {"blocks": [{"start": t0, "end": t1}], "user_id": user_id_of(admin)}
    r = member.post(f"{A}/busy", json=good, headers={H: ws})
    assert r.status_code == 403 and "your own hours" in r.json()["error"]["message"]
    assert member.post(f"{A}/busy", json={"blocks": good["blocks"]}, headers={H: ws}).status_code == 200  # their own
    assert admin.post(f"{A}/busy", json={**good, "user_id": user_id_of(member)}, headers={H: ws}).status_code == 200
    stranger = "00000000-0000-0000-0000-000000000000"
    assert admin.post(f"{A}/busy", json={**good, "user_id": stranger}, headers={H: ws}).status_code == 404
    assert audit(admin, ws, type="availability.updated")[0]["data"]["change"] == "busy"
