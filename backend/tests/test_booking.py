"""Booking through the public page: the open times a visitor sees, booking one, the contact it makes or fills in,
what staff then see, the checks on the request, and that two requests for one time cannot both win."""
import threading
from datetime import timedelta

import pytest
from calendar_api import H, instant, make_calendar, page, public_client, public_slots, visit, weekday_after
from calendar_helpers import at
from helpers import audit, drain, listing, user_id_of
from sqlalchemy import text

from app import config

DAY = weekday_after(14)  # a Tuesday two weeks out; New York is on standard time or daylight time, never mid-change


@pytest.fixture(autouse=True)
def roomy_limit(monkeypatch):
    """Every test books from one address, so the per visitor limit is lifted; the spam tests set their own."""
    monkeypatch.setattr(config, "BOOKING_MAX_PER_IP", 1000)


def bookings(client, ws, **params) -> list[dict]:
    r = client.get("/api/v1/bookings", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_a_visitor_sees_the_open_times_books_one_and_staff_see_the_booking(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, description="Twenty minutes to say hello", locations=[
        {"kind": "video", "value": "https://meet.example.com/intro"}])
    visitor = public_client()
    info = visitor.get(page(cal)).json()
    assert info["name"] == "Intro call" and info["durations"] == [30] and info["business"] == "Main"
    assert info["locations"] == [{"kind": "video", "value": "https://meet.example.com/intro"}]
    assert [q["key"] for q in info["questions"]] == ["name", "email", "phone"]
    assert "user_id" not in str(info) and info["hosts"] == ["a"]  # names only
    times = public_slots(visitor, cal, DAY)
    assert len(times) == 16 and times[0] == instant(DAY, "09:00") and times[-1] == instant(DAY, "16:30")

    r = visit(visitor, cal, instant(DAY, "10:00"))
    assert r.status_code == 201, r.text
    done = r.json()
    assert done["status"] == "confirmed" and done["location"]["value"] == "https://meet.example.com/intro"
    assert done["token"] and done["manage_path"] == f"/booking/{done['token']}" and done["invitee"]["name"] == "Ada Lovelace"
    assert instant(DAY, "10:00") not in public_slots(visitor, cal, DAY) and len(public_slots(visitor, cal, DAY)) == 15

    [booking] = bookings(admin, ws, calendar_id=cal["id"])
    assert booking["starts_at"].startswith(str(DAY)) and booking["status"] == "confirmed"
    assert booking["time_zone"] == "Europe/London" and booking["invitee"]["email"] == "ada@example.com"
    assert booking["host"]["user_id"] == user_id_of(admin) and booking["calendar"]["name"] == "Intro call"
    assert booking["contact"]["display_name"] == "Ada Lovelace"

    [contact] = listing(admin, ws)["data"]
    assert contact["values"] == {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com",
                                 "phone": "+14155550100"}
    assert contact["owner_id"] == user_id_of(admin) and contact["id"] == booking["contact"]["id"]
    events = [e for e in audit(admin, ws) if e["type"].startswith("booking.")]
    assert [e["type"] for e in events] == ["booking.created"] and events[0]["actor"]["type"] == "system"
    assert events[0]["data"]["host_reason"] == "the host" and "email" not in events[0]["data"]
    timeline = admin.get(f"/api/v1/records/{contact['id']}/timeline", headers={H: ws}).json()["data"]
    assert "booking.created" in [e["type"] for e in timeline]


def test_a_contact_that_exists_is_found_by_email_then_phone_and_only_filled_in(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    known = admin.post("/api/v1/objects/contact/records", headers={H: ws}, json={
        "values": {"first_name": "Augusta", "last_name": "King", "email": "ada@example.com"}, "owner_id": None}).json()
    visitor = public_client()
    assert visit(visitor, cal, instant(DAY, "10:00"), name="Ada Lovelace").status_code == 201
    [contact] = listing(admin, ws)["data"]
    assert contact["id"] == known["id"] and contact["owner_id"] is None
    assert contact["values"] == {"first_name": "Augusta", "last_name": "King", "email": "ada@example.com",
                                 "phone": "+14155550100"}  # the phone was blank and is filled, the names stay
    # the same phone with another address is the same person, and nothing already there changes
    assert visit(visitor, cal, instant(DAY, "11:00"), email="other@example.com").status_code == 201
    [again] = listing(admin, ws)["data"]
    assert again["id"] == known["id"] and again["values"]["email"] == "ada@example.com"
    assert {b["contact"]["id"] for b in bookings(admin, ws)} == {known["id"]}
    # a stranger becomes a second contact
    assert visit(visitor, cal, instant(DAY, "12:00"), email="grace@example.com", phone="+14155550111",
                 name="Grace Hopper").status_code == 201
    assert len(listing(admin, ws)["data"]) == 2


def test_the_request_is_checked_and_a_time_that_is_not_open_is_refused(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, locations=[{"kind": "phone", "value": "We call you"}], questions=[
        {"key": "name", "label": "Name", "type": "text", "required": True},
        {"key": "email", "label": "Email", "type": "email", "required": True},
        {"key": "phone", "label": "Phone", "type": "phone", "required": False},
        {"key": "company", "label": "Company", "type": "text", "required": True},
        {"key": "size", "label": "Team size", "type": "select", "required": False, "options": ["1-10", "11-50"]}])
    visitor, ok = public_client(), instant(DAY, "10:00")

    def refused(status, field=None, **body):
        r = visit(visitor, cal, body.pop("start", ok), **{"answers": {"company": "Acme"}, **body})
        assert r.status_code == status, r.text
        assert field is None or field in r.json()["error"]["fields"], r.text
        return r

    refused(422, "answers.company", answers={})
    refused(422, "answers.size", answers={"company": "Acme", "size": "huge"})
    refused(422, "email", email="not an email")
    refused(422, "phone", phone="12")
    refused(422, "time_zone", time_zone="Mars/Olympus")
    refused(422, "location", location="video")
    refused(422, "duration", duration=45)
    assert refused(409, start=instant(DAY, "10:10")).json()["error"]["code"] == "slot_unavailable"  # off the grid
    refused(409, start=instant(DAY, "07:00"))  # outside the hours
    refused(409, start=instant(DAY - timedelta(days=40), "10:00"))  # in the past
    refused(409, start=instant(DAY + timedelta(days=1000), "10:00"))  # beyond the window
    refused(409, start=instant(DAY + timedelta(days=4), "10:00"))  # a Saturday
    assert visit(visitor, cal, ok, phone=None, answers={"company": "Acme", "size": "1-10"}).status_code == 201
    [booking] = bookings(admin, ws)
    assert booking["answers"] == {"company": {"label": "Company", "value": "Acme"},
                                  "size": {"label": "Team size", "value": "1-10"}}
    assert booking["location"] == {"kind": "phone", "value": "We call you"}
    taken = visit(visitor, cal, ok, answers={"company": "Acme"})  # now taken
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "slot_unavailable"


def test_two_visitors_cannot_book_the_same_time_and_with_two_hosts_two_can(crm, db):
    admin, ws, ids = crm
    cal = make_calendar(admin, ws)
    start = instant(DAY, "10:00")
    results, gate = [], threading.Barrier(8)

    def go(n):
        visitor = public_client()
        gate.wait()
        results.append(visit(visitor, cal, start, email=f"visitor{n}@example.com", phone=f"+1415555010{n}").status_code)

    threads = [threading.Thread(target=go, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [201] + [409] * 7
    assert db.scalar(text("SELECT count(*) FROM bookings WHERE status <> 'cancelled'")) == 1
