"""What a visitor does with the link of a booking (see it, move it, cancel it, add it to their calendar), the reminders
that follow a booking around, the private feed, and the spam rules of the public page."""
from datetime import UTC, datetime, timedelta

import pytest
from calendar_api import (
    H,
    instant,
    make_calendar,
    moment,
    parse_ics,
    public_client,
    public_slots,
    visit,
    weekday_after,
)
from calendar_helpers import at
from helpers import audit, drain
from sqlalchemy import text

from app import config
from app.calendars.reminders import remind
from app.db import SessionLocal

DAY = weekday_after(14)
NEXT = DAY + timedelta(days=1)


@pytest.fixture(autouse=True)
def roomy_limit(monkeypatch):
    monkeypatch.setattr(config, "BOOKING_MAX_PER_IP", 1000)


def book(visitor, cal, day=DAY, clock="10:00", **body) -> dict:
    r = visit(visitor, cal, instant(day, clock), **body)
    assert r.status_code == 201, r.text
    return r.json()


def link(done: dict) -> str:
    return f"/api/public/bookings/{done['token']}"


def types(admin, ws) -> list[str]:
    return [e["type"] for e in audit(admin, ws) if e["type"].startswith("booking.")]


def test_the_link_shows_the_booking_and_only_the_booking(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, cutoff_hours=24)
    visitor = public_client()
    done = book(visitor, cal)
    seen = visitor.get(link(done)).json()
    assert seen["status"] == "confirmed" and moment(seen["starts_at"]) == at(str(DAY), "10:00") and seen["can_change"]
    assert seen["calendar"]["name"] == "Intro call" and seen["invitee"] == {"name": "Ada Lovelace"}
    assert "ada@example.com" not in str(seen)
    assert moment(seen["change_until"]) == at(str(DAY), "10:00") - timedelta(hours=24)
    for bad in ("nope", f"{'0' * 32}.nope", done["token"][:-1] + "x", done["token"].split(".")[0] + ".x"):
        assert visitor.get(f"/api/public/bookings/{bad}").status_code == 404, bad
    elsewhere = "1" * 32 + done["token"][32:]  # the secret with another workspace's name on it
    assert visitor.get(f"/api/public/bookings/{elsewhere}").status_code == 404


def test_a_visitor_moves_a_booking_to_another_open_time_and_it_keeps_its_link_and_host(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    visitor = public_client()
    done = book(visitor, cal)
    old = at(str(DAY), "10:00")
    r = visitor.get(f"{link(done)}/slots", params={"from": str(NEXT), "to": str(NEXT), "tz": "Europe/London"})
    assert r.status_code == 200 and instant(NEXT, "10:00") in r.json()["days"][str(NEXT.isoformat())]
    own = visitor.get(f"{link(done)}/slots", params={"from": str(DAY), "to": str(DAY)}).json()["days"][str(DAY)]
    assert instant(DAY, "10:00") in own  # its own time counts as free when moving it
    moved = visitor.post(f"{link(done)}/reschedule", json={"start": instant(NEXT, "11:30"), "time_zone": "Asia/Tokyo"})
    assert moved.status_code == 200, moved.text
    assert moment(moved.json()["starts_at"]) == at(str(NEXT), "11:30") and moved.json()["status"] == "rescheduled"
    assert instant(DAY, "10:00") in public_slots(visitor, cal, DAY)  # the old time is free again
    assert instant(NEXT, "11:30") not in public_slots(visitor, cal, NEXT)
    [booking] = admin.get("/api/v1/bookings", headers={H: ws}).json()["data"]
    assert booking["time_zone"] == "Asia/Tokyo" and booking["reschedules"] == 1 and booking["status"] == "rescheduled"
    assert moment(visitor.get(link(done)).json()["starts_at"]) == at(str(NEXT), "11:30")  # the same link
    taken = visitor.post(f"{link(done)}/reschedule", json={"start": instant(DAY, "07:00"), "time_zone": "UTC"})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "slot_unavailable"
    assert types(admin, ws) == ["booking.rescheduled", "booking.created"]
    event = audit(admin, ws, type="booking.rescheduled")[0]["data"]
    assert moment(event["from_starts_at"]) == old and moment(event["starts_at"]) == at(str(NEXT), "11:30")


def test_a_visitor_cancels_once_and_the_time_opens_again(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    visitor = public_client()
    done = book(visitor, cal)
    r = visitor.post(f"{link(done)}/cancel", json={"reason": "Clash with a trip"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and not r.json()["can_change"]
    assert visitor.post(f"{link(done)}/cancel", json={}).status_code == 200  # again: nothing more happens
    assert types(admin, ws) == ["booking.cancelled", "booking.created"]
    assert audit(admin, ws, type="booking.cancelled")[0]["data"]["reason"] == "Clash with a trip"
    assert instant(DAY, "10:00") in public_slots(visitor, cal, DAY)
    assert visitor.post(f"{link(done)}/reschedule", json={"start": instant(NEXT, "10:00"), "time_zone": "UTC"}
                        ).status_code == 409
    [booking] = admin.get("/api/v1/bookings", headers={H: ws}).json()["data"]
    assert booking["status"] == "cancelled" and booking["cancel_reason"] == "Clash with a trip"


def test_links_stop_working_inside_the_cutoff_and_after_the_meeting(crm, db):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, cutoff_hours=72)
    visitor = public_client()
    done = book(visitor, cal, weekday_after(1), "10:00")  # inside 72 hours when the day is close, so move it by SQL
    db.execute(text("UPDATE bookings SET starts_at = now() + interval '10 hours', ends_at = now() + interval '11 hours'"))
    db.commit()
    seen = visitor.get(link(done)).json()
    assert not seen["can_change"]
    for action, body in (("cancel", {}), ("reschedule", {"start": instant(DAY, "10:00"), "time_zone": "UTC"})):
        r = visitor.post(f"{link(done)}/{action}", json=body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "change_closed", r.text
    db.execute(text("UPDATE calendars SET cutoff_hours = NULL"))
    db.commit()
    assert visitor.get(link(done)).json()["can_change"]  # no cutoff: links work until the meeting
    db.execute(text("UPDATE bookings SET starts_at = now() - interval '2 hours', ends_at = now() - interval '1 hour'"))
    db.commit()
    assert not visitor.get(link(done)).json()["can_change"]


def test_the_ics_file_is_valid_and_has_the_right_times(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, locations=[{"kind": "in_person", "value": "1 Main St, Springfield; floor 2"}],
                        name="Intro call, with Theo; bring ideas")
    visitor = public_client()
    done = book(visitor, cal)
    r = visitor.get(f"{link(done)}/ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]
    [event] = parse_ics(r.text)
    start = at(str(DAY), "10:00")
    assert event["DTSTART"] == start.strftime("%Y%m%dT%H%M%SZ")
    assert event["DTEND"] == (start + timedelta(minutes=30)).strftime("%Y%m%dT%H%M%SZ")
    assert event["SUMMARY"] == "Intro call\\, with Theo\\; bring ideas"
    assert event["LOCATION"] == "1 Main St\\, Springfield\\; floor 2" and event["STATUS"] == "CONFIRMED"
    assert event["UID"].endswith("@go-high") and event["SEQUENCE"] == "0" and "DTSTAMP" in event
    assert event["URL"].endswith(f"/booking/{done['token']}") and "ada@example.com" not in r.text
    assert datetime.strptime(event["DTSTART"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) == start
    visitor.post(f"{link(done)}/reschedule", json={"start": instant(NEXT, "09:00"), "time_zone": "UTC"})
    [moved] = parse_ics(visitor.get(f"{link(done)}/ics").text)
    assert moved["UID"] == event["UID"] and moved["SEQUENCE"] == "1" and moved["DTSTART"].startswith(NEXT.strftime("%Y%m%d"))
    visitor.post(f"{link(done)}/cancel", json={})
    [cancelled] = parse_ics(visitor.get(f"{link(done)}/ics").text)
    assert cancelled["STATUS"] == "CANCELLED" and cancelled["SEQUENCE"] == "2"
    assert visitor.get("/api/public/bookings/bogus/ics").status_code == 404


def test_a_private_feed_lists_my_bookings_and_a_new_link_replaces_the_old(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, name="Intro call")
    visitor = public_client()
    book(visitor, cal)
    cancelled = book(visitor, cal, DAY, "11:00", email="late@example.com", phone="+14155550122")
    visitor.post(f"{link(cancelled)}/cancel", json={})
    url = admin.post("/api/v1/calendars/feed", headers={H: ws}).json()["url"]
    path = "/" + url.split("/", 3)[3]
    r = visitor.get(path)  # a calendar app subscribes with no sign in
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert [e["SUMMARY"] for e in parse_ics(r.text)] == ["Intro call"]  # the cancelled one is left out
    newer = admin.post("/api/v1/calendars/feed", headers={H: ws}).json()["url"]
    assert newer != url and visitor.get(path).status_code == 404
    assert visitor.get("/" + newer.split("/", 3)[3]).status_code == 200
    assert visitor.get(path.rsplit("/", 1)[0] + "/bogus.ics").status_code == 404


# --- reminders ----------------------------------------------------------------------------------------------------

def reminders(db) -> list[tuple[int, str, datetime]]:
    db.expire_all()
    return [(o, s, d) for o, s, d in db.execute(text(
        "SELECT offset_minutes, status, due_at FROM booking_reminders ORDER BY offset_minutes DESC"))]


def come_due(db) -> None:
    """Time passes: every pending reminder is now due, and its job is told the time it was scheduled for."""
    db.execute(text("UPDATE booking_reminders SET due_at = now() - interval '1 minute' WHERE status = 'pending'"))
    db.execute(text(
        "UPDATE jobs SET run_at = now(), payload = jsonb_set(payload, '{due}', to_jsonb((SELECT "
        "to_char(r.due_at AT TIME ZONE 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+00:00\"') FROM booking_reminders r "
        "WHERE r.id::text = jobs.payload ->> 'id'))) WHERE kind = 'calendars.reminder' AND status = 'queued'"))
    db.commit()


def test_reminders_are_scheduled_per_offset_and_recorded_once_when_due(crm, db):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, reminders=[60, 1440])
    visitor = public_client()
    book(visitor, cal)
    start = at(str(DAY), "10:00")
    assert [(o, s, d) for o, s, d in reminders(db)] == [(1440, "pending", start - timedelta(hours=24)),
                                                         (60, "pending", start - timedelta(hours=1))]
    jobs = db.execute(text("SELECT payload ->> 'id', run_at FROM jobs WHERE kind = 'calendars.reminder' "
                           "ORDER BY run_at")).all()
    assert len(jobs) == 2 and jobs[0][1] == start - timedelta(hours=24) and jobs[1][1] == start - timedelta(hours=1)
    assert types(admin, ws) == ["booking.created"]
    come_due(db)
    drain()
    due = audit(admin, ws, type="booking.reminder_due")
    assert sorted(e["data"]["offset_minutes"] for e in due) == [60, 1440]
    assert {s for _, s, _ in reminders(db)} == {"sent"}
    payload = {"id": db.scalar(text("SELECT id::text FROM booking_reminders LIMIT 1")), "due": "2020-01-01T00:00:00+00:00"}
    remind(db, payload)  # a duplicate or stale job finds nothing pending at that time
    db.commit()
    assert len(audit(admin, ws, type="booking.reminder_due")) == 2


def test_a_reminder_already_past_when_booked_is_not_scheduled(crm, db):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, reminders=[60, 14 * 24 * 60])  # the second is 14 days before: past for a booking within a week
    book(public_client(), cal, weekday_after(1))
    assert [o for o, _, _ in reminders(db)] == [60]


def test_moving_a_booking_moves_its_reminders_and_a_job_for_the_old_time_does_nothing(crm, db):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, reminders=[1440, 60])
    visitor = public_client()
    done = book(visitor, cal)
    old_jobs = [j for (j,) in db.execute(text("SELECT payload FROM jobs WHERE kind = 'calendars.reminder'"))]
    r = visitor.post(f"{link(done)}/reschedule", json={"start": instant(NEXT, "13:00"), "time_zone": "UTC"})
    assert r.status_code == 200, r.text
    start = at(str(NEXT), "13:00")
    assert reminders(db) == [(1440, "pending", start - timedelta(hours=24)), (60, "pending", start - timedelta(hours=1))]
    assert db.scalar(text("SELECT count(*) FROM jobs WHERE kind = 'calendars.reminder'")) == 4  # old two and new two
    for payload in old_jobs:
        remind(db, payload)  # the time they were made for is not the reminder's time any more
    db.commit()
    assert {s for _, s, _ in reminders(db)} == {"pending"} and not audit(admin, ws, type="booking.reminder_due")
    come_due(db)
    drain()
    assert len(audit(admin, ws, type="booking.reminder_due")) == 2  # one per offset, not one per job


def test_cancelling_a_booking_cancels_its_reminders(crm, db):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, reminders=[1440, 60])
    visitor = public_client()
    done = book(visitor, cal)
    visitor.post(f"{link(done)}/cancel", json={})
    assert {s for _, s, _ in reminders(db)} == {"cancelled"}
    come_due(db)
    drain()
    assert not audit(admin, ws, type="booking.reminder_due")


# --- spam ---------------------------------------------------------------------------------------------------------

def test_a_filled_honeypot_gets_a_believable_answer_and_stores_nothing(crm, db):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    visitor = public_client()
    r = visit(visitor, cal, instant(DAY, "10:00"), website="http://spam.example.com")
    assert r.status_code == 201 and r.json()["token"] and r.json()["status"] == "booked"
    assert db.scalar(text("SELECT count(*) FROM bookings")) == 0 and db.scalar(text("SELECT count(*) FROM records")) == 0
    assert instant(DAY, "10:00") in public_slots(visitor, cal, DAY)
    assert visitor.get(f"/api/public/bookings/{r.json()['token']}").status_code == 404  # the link goes nowhere


def test_one_visitor_is_limited_per_calendar_and_the_calendar_has_a_ceiling_of_its_own(crm, monkeypatch, db):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    other = make_calendar(admin, ws, name="Other call")
    monkeypatch.setattr(config, "BOOKING_MAX_PER_IP", 3)
    visitor = public_client()
    codes = [visit(visitor, cal, instant(DAY, f"{9 + n:02d}:00"), email=f"v{n}@example.com").status_code
             for n in range(5)]
    assert codes == [201, 201, 201, 429, 429]  # refused ones count as attempts too
    r = visit(visitor, cal, instant(DAY, "15:00"), email="again@example.com")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and int(r.headers["retry-after"]) > 0
    assert visit(visitor, other, instant(DAY, "14:00")).status_code == 201  # another calendar has its own count
    monkeypatch.setattr(config, "BOOKING_MAX_PER_IP", 1000)
    monkeypatch.setattr(config, "BOOKING_MAX_PER_CALENDAR", 7)
    assert visit(visitor, cal, instant(DAY, "16:00")).status_code == 201  # attempt 7 of the window
    assert visit(visitor, cal, instant(DAY, "16:30"), email="z@example.com").status_code == 429  # the ceiling
    db.execute(text("UPDATE booking_attempts SET created_at = now() - interval '1 hour'"))
    db.commit()
    assert visit(visitor, cal, instant(DAY, "16:30"), email="z@example.com").status_code == 201  # the window passed
    assert db.scalar(text("SELECT bool_and(ip_hash ~ '^[0-9a-f]{64}$') FROM booking_attempts"))  # a hash, not an address
