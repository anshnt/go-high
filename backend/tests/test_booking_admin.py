"""What the people who run a calendar do with bookings (list, cancel, move, confirm, mark), the explainer and the
rotation preview, and bookings on round robin, collective and class calendars, including two hosts under concurrent
requests."""
import threading
from datetime import timedelta

import pytest
from calendar_api import H, instant, make_calendar, moment, public_client, public_slots, visit, weekday_after
from calendar_helpers import at
from helpers import add_member, audit, make_record, user_id_of
from sqlalchemy import text

from app import config

DAY = weekday_after(14)
NEXT = DAY + timedelta(days=1)
CALENDARS, BOOKINGS = "/api/v1/calendars", "/api/v1/bookings"


@pytest.fixture(autouse=True)
def roomy_limit(monkeypatch):
    monkeypatch.setattr(config, "BOOKING_MAX_PER_IP", 1000)


@pytest.fixture
def team(crm, db):
    """(admin, workspace, ben's client, ids of admin and ben): a workspace with a second member."""
    admin, ws, ids = crm
    ben = add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws)
    return admin, ws, ben, (user_id_of(admin), user_id_of(ben))


def rotation(admin, ws, hosts, **body) -> dict:
    cal = make_calendar(admin, ws, kind=body.pop("kind", "round_robin"), hosts=hosts, **body)
    return cal


def host_of(admin, ws, booking_id) -> str:
    return admin.get(f"{BOOKINGS}/{booking_id}", headers={H: ws}).json()["host"]["user_id"]


def test_the_list_filters_by_range_host_calendar_status_and_contact_and_pages_by_start(team):
    admin, ws, ben, (me, ben_id) = team
    cal = rotation(admin, ws, [{"user_id": me}, {"user_id": ben_id}])
    other = make_calendar(admin, ws, name="Other call")
    visitor = public_client()
    made = {}
    for n, clock in enumerate(("09:00", "10:00", "11:00", "12:00")):
        r = visit(visitor, cal, instant(DAY, clock), email=f"v{n}@example.com", phone=f"+1415555020{n}",
                  name=f"Visitor {n}")
        made[clock] = r.json()
    assert visit(visitor, other, instant(DAY, "15:00")).status_code == 201
    everything = admin.get(BOOKINGS, headers={H: ws}).json()
    starts = [moment(b["starts_at"]) for b in everything["data"]]
    assert starts == sorted(starts)
    assert len(everything["data"]) == 5 and everything["next_cursor"] is None
    rng = {"from": instant(DAY, "10:00"), "to": instant(DAY, "12:00")}  # overlap: the 10:00 and 11:00 bookings
    assert [b["invitee"]["name"] for b in admin.get(BOOKINGS, params=rng, headers={H: ws}).json()["data"]] == [
        "Visitor 1", "Visitor 2"]
    mine = admin.get(BOOKINGS, params={"host_id": me, "calendar_id": cal["id"]}, headers={H: ws}).json()["data"]
    theirs = admin.get(BOOKINGS, params={"host_id": ben_id}, headers={H: ws}).json()["data"]
    names = {b["invitee"]["name"] for b in mine} | {b["invitee"]["name"] for b in theirs}
    assert names >= {f"Visitor {n}" for n in range(4)}
    assert len(mine) == 2 and len(theirs) == 2
    contact = everything["data"][0]["contact"]["id"]
    of_contact = admin.get(BOOKINGS, params={"contact_id": contact}, headers={H: ws}).json()["data"]
    assert [b["contact"]["id"] for b in of_contact] == [contact]
    first = everything["data"][0]["id"]
    admin.post(f"{BOOKINGS}/{first}/cancel", json={}, headers={H: ws})
    cancelled = admin.get(BOOKINGS, params={"status": "cancelled"}, headers={H: ws}).json()["data"]
    assert [b["id"] for b in cancelled] == [first]
    assert len(admin.get(BOOKINGS, params={"status": "confirmed,rescheduled"}, headers={H: ws}).json()["data"]) == 4
    page = admin.get(BOOKINGS, params={"limit": 2}, headers={H: ws}).json()
    rest = admin.get(BOOKINGS, params={"limit": 3, "cursor": page["next_cursor"]}, headers={H: ws}).json()
    assert [b["id"] for b in page["data"] + rest["data"]] == [b["id"] for b in everything["data"]]
    assert rest["next_cursor"] is None
    newest = admin.get(BOOKINGS, params={"order": "desc", "limit": 1}, headers={H: ws}).json()["data"][0]
    assert newest["id"] == everything["data"][-1]["id"]
    assert admin.get(BOOKINGS, params={"status": "nope"}, headers={H: ws}).status_code == 422
    assert admin.get(BOOKINGS, params={"cursor": "junk"}, headers={H: ws}).status_code == 400
    assert admin.get(f"{BOOKINGS}/{first}", headers={H: ws}).json()["status"] == "cancelled"
    assert admin.get(f"{BOOKINGS}/00000000-0000-0000-0000-000000000000", headers={H: ws}).status_code == 404


def test_staff_cancel_move_and_mark_bookings(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, buffer_after=15)
    visitor = public_client()
    one = visit(visitor, cal, instant(DAY, "10:00")).json()
    two = visit(visitor, cal, instant(DAY, "12:00"), email="b@example.com", phone="+14155550111").json()
    ids = {b["starts_at"][:16]: b["id"] for b in admin.get(BOOKINGS, headers={H: ws}).json()["data"]}
    when = {i: moment(admin.get(f"{BOOKINGS}/{i}", headers={H: ws}).json()["starts_at"]) for i in ids.values()}
    first, second = sorted(when, key=when.get)
    moved = admin.post(f"{BOOKINGS}/{first}/reschedule", json={"start": instant(NEXT, "09:00")}, headers={H: ws})
    assert moved.status_code == 200 and moment(moved.json()["starts_at"]) == at(str(NEXT), "09:00")
    assert moved.json()["status"] == "rescheduled" and moved.json()["time_zone"] == "Europe/London"
    taken = admin.post(f"{BOOKINGS}/{first}/reschedule", json={"start": instant(DAY, "12:00")}, headers={H: ws})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "slot_unavailable"  # the other booking
    buffer = admin.post(f"{BOOKINGS}/{first}/reschedule", json={"start": instant(DAY, "12:30")}, headers={H: ws})
    assert buffer.status_code == 409  # inside the 15 minutes after the 12:00 booking
    assert admin.post(f"{BOOKINGS}/{first}/reschedule", json={"start": instant(DAY, "13:00")},
                      headers={H: ws}).status_code == 200
    showed = admin.post(f"{BOOKINGS}/{second}/status", json={"status": "showed"}, headers={H: ws})
    assert showed.json()["status"] == "showed"
    flip = admin.post(f"{BOOKINGS}/{second}/status", json={"status": "no_show"}, headers={H: ws})
    assert flip.status_code == 200 and flip.json()["status"] == "no_show"  # a mistake can be put right
    assert admin.post(f"{BOOKINGS}/{second}/status", json={"status": "confirmed"}, headers={H: ws}).status_code == 409
    assert admin.post(f"{BOOKINGS}/{second}/reschedule", json={"start": instant(NEXT, "11:00")},
                      headers={H: ws}).status_code == 409
    assert admin.post(f"{BOOKINGS}/{first}/status", json={"status": "bogus"}, headers={H: ws}).status_code == 422
    gone = admin.post(f"{BOOKINGS}/{first}/cancel", json={"reason": "No longer needed"}, headers={H: ws})
    assert gone.status_code == 200
    assert admin.post(f"{BOOKINGS}/{first}/status", json={"status": "showed"}, headers={H: ws}).status_code == 409
    assert admin.post(f"{BOOKINGS}/{first}/reschedule", json={"start": instant(NEXT, "11:00")},
                      headers={H: ws}).status_code == 409
    types = [e["type"] for e in audit(admin, ws) if e["type"].startswith("booking.")]
    assert types == ["booking.cancelled", "booking.status_changed", "booking.status_changed", "booking.rescheduled",
                     "booking.rescheduled", "booking.created", "booking.created"]
    flipped = audit(admin, ws, type="booking.status_changed")[0]["data"]
    assert flipped["status"] == "no_show" and flipped["from_status"] == "showed"
    assert one["token"] and two["token"]


def test_a_calendar_that_confirms_by_hand_starts_bookings_as_booked(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, confirmation="manual")
    visitor = public_client()
    done = visit(visitor, cal, instant(DAY, "10:00")).json()
    assert done["status"] == "booked" and done["confirmation"] == "manual"
    [booking] = admin.get(BOOKINGS, headers={H: ws}).json()["data"]
    assert booking["status"] == "booked"
    r = admin.post(f"{BOOKINGS}/{booking['id']}/status", json={"status": "confirmed"}, headers={H: ws})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert visitor.get(f"/api/public/bookings/{done['token']}").json()["status"] == "confirmed"
    again = admin.post(f"{BOOKINGS}/{booking['id']}/status", json={"status": "confirmed"}, headers={H: ws})
    assert again.status_code == 409


def test_the_explainer_says_why_a_time_is_hidden_and_who_would_get_it_when_it_is_not(team):
    admin, ws, ben, (me, ben_id) = team
    cal = rotation(admin, ws, [{"user_id": me}, {"user_id": ben_id}], buffer_after=15)
    assert visit(public_client(), cal, instant(DAY, "10:00")).status_code == 201
    explain = f"{CALENDARS}/{cal['id']}/explain"

    def ask(clock, **params):
        r = admin.get(explain, params={"start": instant(DAY, clock), **params}, headers={H: ws})
        assert r.status_code == 200, r.text
        return r.json()

    early = ask("07:00")
    assert not early["offered"] and [h["free"] for h in early["hosts"]] == [False, False]
    assert all(h["reasons"][0]["message"].startswith("Outside ") for h in early["hosts"])
    assert early["hosts"][0]["name"] == "a" and "a's hours" in early["hosts"][0]["reasons"][0]["message"]
    mid = ask("10:00")  # one host has the booking, the other is free, so it is still offered
    assert mid["offered"] and [h["free"] for h in mid["hosts"]] == [False, True]
    assert mid["hosts"][0]["reasons"][0]["message"] == "a has a booking from 10:00 to 10:30"
    assert mid["assigned"]["user_id"] == ben_id and mid["assigned"]["reason"] == "the only host free"
    buffered = ask("10:30", tz="Europe/London")
    assert buffered["hosts"][0]["reasons"][0]["message"] == "Buffer after the 15:00 booking"  # on London's clock
    free = ask("11:00")
    assert free["offered"] and free["reasons"] == [] and free["assigned"]["reason"].startswith("fewest bookings")
    off = ask("10:10")
    assert not off["offered"] and off["reasons"][0]["code"] == "off_grid"
    at_ten = instant(DAY, "10:00")
    assert admin.get(explain, params={"start": at_ten, "tz": "Mars/X"}, headers={H: ws}).status_code == 422
    assert admin.get(explain, params={"start": "tomorrow"}, headers={H: ws}).status_code == 422
    assert admin.get(explain, params={"start": at_ten, "duration": 45}, headers={H: ws}).status_code == 422


def test_the_simulation_shows_the_next_bookings_by_weight_and_writes_nothing(team, db):
    admin, ws, ben, (me, ben_id) = team
    cal = rotation(admin, ws, [{"user_id": me, "weight": 2}, {"user_id": ben_id, "weight": 1}])
    before = db.execute(text("SELECT (SELECT count(*) FROM bookings), (SELECT count(*) FROM jobs), "
                             "(SELECT count(*) FROM events), (SELECT count(*) FROM records)")).one()
    r = admin.post(f"{CALENDARS}/{cal['id']}/simulate", params={"n": 9}, headers={H: ws})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["found"] == 9 and plan["kind"] == "round_robin" and plan["duration"] == 30
    assert [x["host"]["user_id"] for x in plan["rounds"]] == [me, ben_id, me, me, ben_id, me, me, ben_id, me]
    assert {h["name"]: (h["bookings"], h["target_share"]) for h in plan["hosts"]} == {"a": (6, 0.667), "M": (3, 0.333)}
    starts = [moment(x["start"]) for x in plan["rounds"]]
    assert starts == sorted(starts) and len(set(starts)) == 9
    after = db.execute(text("SELECT (SELECT count(*) FROM bookings), (SELECT count(*) FROM jobs), "
                            "(SELECT count(*) FROM events), (SELECT count(*) FROM records)")).one()
    assert tuple(after) == tuple(before)
    assert admin.post(f"{CALENDARS}/{cal['id']}/simulate", params={"n": 0}, headers={H: ws}).status_code == 422
    assert admin.post(f"{CALENDARS}/{cal['id']}/simulate", params={"n": 101}, headers={H: ws}).status_code == 422
    contact = make_record(admin, ws, first_name="Ada", email="ada@example.com", owner_id=ben_id)
    params = {"n": 3, "contact_id": contact["id"]}
    sticky = admin.post(f"{CALENDARS}/{cal['id']}/simulate", params=params, headers={H: ws})
    assert {x["host"]["user_id"] for x in sticky.json()["rounds"]} == {ben_id}


def test_a_round_robin_gives_each_booking_to_the_host_the_rotation_picks_and_the_contacts_owner_keeps_them(team):
    admin, ws, ben, (me, ben_id) = team
    cal = rotation(admin, ws, [{"user_id": me}, {"user_id": ben_id}])
    visitor = public_client()
    hosts = []
    for n, clock in enumerate(("09:00", "09:30", "10:00", "10:30")):
        r = visit(visitor, cal, instant(DAY, clock), email=f"v{n}@example.com", phone=f"+1415555010{n}")
        assert r.status_code == 201, r.text
        listed = admin.get(BOOKINGS, params={"limit": 200}, headers={H: ws}).json()["data"]
        hosts.append(host_of(admin, ws, listed[n]["id"]))
    assert hosts == [me, ben_id, me, ben_id]
    known = make_record(admin, ws, first_name="Ben's", last_name="Client", email="client@example.com", owner_id=ben_id)
    r = visit(visitor, cal, instant(DAY, "11:00"), email="client@example.com", phone="+14155550199", name="Client")
    assert r.status_code == 201
    latest = admin.get(BOOKINGS, params={"order": "desc", "limit": 1}, headers={H: ws}).json()["data"][0]
    assert latest["host"]["user_id"] == ben_id and latest["contact"]["id"] == known["id"]  # ben owns this contact
    event = audit(admin, ws, type="booking.created")[0]["data"]
    assert event["host_reason"] == "owns the contact" and event["host_user_id"] == ben_id
    stranger = visit(visitor, cal, instant(DAY, "11:30"), email="new@example.com", phone="+14155550198")
    assert stranger.status_code == 201
    mine = admin.get("/api/v1/objects/contact/records", params={"q": "new"}, headers={H: ws}).json()["data"][0]
    assert mine["owner_id"] in (me, ben_id)  # a new contact belongs to whoever got the booking


def test_two_hosts_can_each_take_one_booking_of_the_same_time_and_no_more(team, db):
    admin, ws, ben, (me, ben_id) = team
    cal = rotation(admin, ws, [{"user_id": me}, {"user_id": ben_id}])
    start, results, gate = instant(DAY, "10:00"), [], threading.Barrier(6)

    def go(n):
        visitor = public_client()
        gate.wait()
        results.append(visit(visitor, cal, start, email=f"v{n}@example.com", phone=f"+1415555010{n}").status_code)

    threads = [threading.Thread(target=go, args=(n,)) for n in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [201, 201, 409, 409, 409, 409]
    hosts = {h for (h,) in db.execute(text("SELECT host_user_id::text FROM bookings"))}
    assert hosts == {me, ben_id}  # one each: nobody is booked twice at once
    assert instant(DAY, "10:00") not in public_slots(public_client(), cal, DAY)


def test_a_collective_calendar_books_everyone_and_needs_everyone_free(team):
    admin, ws, ben, (me, ben_id) = team
    cal = rotation(admin, ws, [{"user_id": me}, {"user_id": ben_id}], kind="collective")
    visitor = public_client()
    r = visit(visitor, cal, instant(DAY, "10:00"))
    assert r.status_code == 201, r.text
    [booking] = admin.get(BOOKINGS, params={"host_id": ben_id}, headers={H: ws}).json()["data"]  # it is ben's as well
    assert [h["user_id"] for h in booking["hosts"]] == [me, ben_id] and booking["host"]["user_id"] == me
    assert len(admin.get(BOOKINGS, params={"host_id": me}, headers={H: ws}).json()["data"]) == 1
    single = make_calendar(admin, ws, name="Just ben", hosts=[{"user_id": ben_id}])  # ben is busy at 10:00 everywhere
    assert instant(DAY, "10:00") not in public_slots(visitor, single, DAY)
    assert visit(visitor, cal, instant(DAY, "10:00"), email="x@example.com").status_code == 409
    ben.put(f"/api/v1/availability/users/{ben_id}/overrides/{NEXT}", json={"hours": []}, headers={H: ws})
    assert public_slots(visitor, cal, NEXT) == []  # everyone must be free, and ben is off
    assert len(public_slots(visitor, single, NEXT)) == 0 and len(public_slots(visitor, cal, DAY)) == 15


def test_a_class_sells_seats_until_it_is_full(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, kind="class", seats=2, slot_interval=60, name="Workshop")
    visitor = public_client()
    codes = [visit(visitor, cal, instant(DAY, "10:00"), email=f"v{n}@example.com", phone=f"+1415555010{n}").status_code
             for n in range(3)]
    assert codes == [201, 201, 409]
    open_now = public_slots(visitor, cal, DAY)
    assert instant(DAY, "10:00") not in open_now and instant(DAY, "11:00") in open_now
    r = visit(visitor, cal, instant(DAY, "11:00"), email="v0@example.com")
    assert r.status_code == 201
    people = {b["contact"]["id"] for b in admin.get(BOOKINGS, headers={H: ws}).json()["data"]}
    assert len(people) == 2  # one person twice
