"""Edges of calendar settings and the public booking page: the questions a calendar may ask, the answers a visitor
must give, a move to a zone that does not exist, and a date's hours set before the week was ever saved."""
from datetime import timedelta

import pytest
from calendar_api import H, instant, make_calendar, public_client, public_slots, visit, weekday_after
from helpers import user_id_of

from app import config

DAY = weekday_after(14)
CALENDARS = "/api/v1/calendars"
BUILT_IN = [{"key": "name", "label": "Name", "type": "text", "required": True},
            {"key": "email", "label": "Email", "type": "email", "required": True},
            {"key": "phone", "label": "Phone", "type": "phone", "required": False}]


@pytest.fixture(autouse=True)
def roomy_limit(monkeypatch):
    monkeypatch.setattr(config, "BOOKING_MAX_PER_IP", 1000)


def own(key, type_="text", **extra) -> dict:
    return {"key": key, "label": key.title(), "type": type_, **extra}


@pytest.mark.parametrize("questions, fragment", [
    (BUILT_IN + [own("topic"), own("topic")], "its own key"),
    (BUILT_IN[:2], "always asked"),
    ([{**BUILT_IN[0], "required": False}, *BUILT_IN[1:]], "name and email are required"),
    ([BUILT_IN[0], {**BUILT_IN[1], "type": "text"}, BUILT_IN[2]], "email is a email question"),
    (BUILT_IN + [own("Topic")], "not a valid key"),
    (BUILT_IN + [own("work_email", "email")], "text, long text or select"),
    (BUILT_IN + [own("size", "select", options=["Only one"])], "2 to 20 options"),
    (BUILT_IN + [own("size", "select", options=[str(n) for n in range(21)])], "2 to 20 options"),
    (BUILT_IN + [own(f"q{n}") for n in range(11)], "at most 10"),
])
def test_the_questions_of_a_calendar_are_checked(crm, questions, fragment):
    admin, ws, _ = crm
    r = admin.post(CALENDARS, json={"name": "Call", "time_zone": "UTC", "questions": questions}, headers={H: ws})
    assert r.status_code == 422, r.text
    assert any(f.startswith("questions") and fragment in m for f, m in r.json()["error"]["fields"].items()), r.json()
    cal = make_calendar(admin, ws)
    r = admin.patch(f"{CALENDARS}/{cal['id']}", json={"questions": questions}, headers={H: ws})
    assert r.status_code == 422, r.text
    fine = BUILT_IN + [own(f"q{n}") for n in range(10)]
    assert admin.patch(f"{CALENDARS}/{cal['id']}", json={"questions": fine}, headers={H: ws}).status_code == 200


def test_a_calendar_asks_for_a_phone_unless_it_is_made_optional(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)  # the default questions: the phone is required
    visitor = public_client()
    r = visit(visitor, cal, instant(DAY, "10:00"), phone=None)
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"phone": "is required"}
    r = visit(visitor, cal, instant(DAY, "10:00"), phone="  ")
    assert r.status_code == 422 and "phone" in r.json()["error"]["fields"]
    assert admin.get("/api/v1/bookings", headers={H: ws}).json()["data"] == []
    admin.patch(f"{CALENDARS}/{cal['id']}", json={"questions": BUILT_IN}, headers={H: ws})
    assert visit(visitor, cal, instant(DAY, "10:00"), phone=None).status_code == 201


def test_answers_are_capped_by_the_kind_of_question(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws, questions=BUILT_IN + [own("company"), own("notes", "long_text")])
    visitor = public_client()

    def answer(**answers):
        return visit(visitor, cal, instant(DAY, "10:00"), answers=answers)

    r = answer(company="x" * 1001)
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"answers.company": "is too long"}
    r = answer(notes="x" * 5001)
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"answers.notes": "is too long"}
    r = answer(company="x" * 1000, notes="x" * 5000, unasked="kept out")
    assert r.status_code == 201, r.text
    [booking] = admin.get("/api/v1/bookings", headers={H: ws}).json()["data"]
    assert set(booking["answers"]) == {"company", "notes"}  # an answer to no question is not stored


def test_a_move_to_a_zone_that_does_not_exist_is_refused_and_changes_nothing(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    visitor = public_client()
    done = visit(visitor, cal, instant(DAY, "10:00")).json()
    r = visitor.post(f"/api/public/bookings/{done['token']}/reschedule",
                     json={"start": instant(DAY, "11:00"), "time_zone": "Mars/Olympus"})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"time_zone": "is not a time zone"}
    seen = visitor.get(f"/api/public/bookings/{done['token']}").json()
    assert seen["status"] == "confirmed" and seen["time_zone"] == "Europe/London"
    assert instant(DAY, "11:00") in public_slots(visitor, cal, DAY)


def test_a_link_with_a_malformed_secret_is_not_found_on_every_public_route(crm):
    admin, ws, _ = crm
    cal = make_calendar(admin, ws)
    visitor = public_client()
    done = visit(visitor, cal, instant(DAY, "10:00")).json()
    secret = done["token"].split(".", 1)[1]
    for token in (f"not-a-uuid.{secret}", f".{secret}", f"{ws.replace('-', '')}.", "%00", "a.b.c"):
        base = f"/api/public/bookings/{token}"
        for method, path, body in (("GET", base, None), ("GET", f"{base}/ics", None),
                                   ("GET", f"{base}/slots?from={DAY}&to={DAY}", None),
                                   ("POST", f"{base}/cancel", {}),
                                   ("POST", f"{base}/reschedule", {"start": instant(DAY, "11:00"), "time_zone": "UTC"}),
                                   ("GET", f"/api/public/feeds/{token}.ics", None)):
            r = visitor.request(method, path, json=body)
            assert r.status_code == 404, (token, method, path, r.text)
    assert visitor.get(f"/api/public/bookings/{done['token']}").json()["status"] == "confirmed"


def test_a_dates_hours_set_before_the_week_was_saved_keep_the_usual_week(crm):
    admin, ws, _ = crm
    me = user_id_of(admin)
    cal = make_calendar(admin, ws)
    r = admin.put(f"/api/v1/availability/users/{me}/overrides/{DAY}", json={"hours": [["10:00", "11:00"]]},
                  headers={H: ws})
    assert r.status_code == 200, r.text
    assert r.json()["overrides"] == {str(DAY): [["10:00", "11:00"]]} and r.json()["weekly"]["mon"] == [["09:00",
                                                                                                         "17:00"]]
    visitor = public_client()
    assert public_slots(visitor, cal, DAY) == [instant(DAY, "10:00"), instant(DAY, "10:30")]
    assert len(public_slots(visitor, cal, DAY + timedelta(days=1))) == 16  # the next day has the usual 9 to 5
