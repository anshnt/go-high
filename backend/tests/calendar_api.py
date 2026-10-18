"""Helpers for the calendar tests that go through the API: a calendar made by the signed-in user, and a visitor (no
cookie, no workspace header) who reads the public page and books."""
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from calendar_helpers import NY, at
from fastapi.testclient import TestClient

from app.main import app

H = "X-Workspace-Id"


def weekday_after(days: int, weekday: int = 1) -> date:
    """The first date at least `days` from today that falls on this weekday (0 is Monday, 1 Tuesday)."""
    day = datetime.now(UTC).date() + timedelta(days=days)
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def make_calendar(client, ws, **body) -> dict:
    """A calendar through the API: a 30 minute call for the signed-in user, in New York, with no notice or reminders."""
    body = {"name": "Intro call", "time_zone": "America/New_York", "min_notice": 0, "window_days": 365,
            "reminders": [], **body}
    r = client.post("/api/v1/calendars", json=body, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def public_client() -> TestClient:
    """A visitor: no cookie, no workspace header."""
    return TestClient(app)


def page(cal: dict) -> str:
    """The `/api/public/calendars/<workspace>/<calendar>` path of a calendar."""
    _, _, workspace, slug = cal["public_path"].split("/")
    return f"/api/public/calendars/{workspace}/{slug}"


def public_slots(visitor, cal: dict, day, zone="America/New_York", **params) -> list[str]:
    r = visitor.get(f"{page(cal)}/slots", params={"from": str(day), "to": str(day), "tz": zone, **params})
    assert r.status_code == 200, r.text
    return next(iter(r.json()["days"].values()), [])


def visit(visitor, cal: dict, start: str, **body):
    """A visitor books `start` (an ISO instant)."""
    payload = {"start": start, "time_zone": "Europe/London", "name": "Ada Lovelace", "email": "ada@example.com",
               "phone": "+14155550100", **body}
    return visitor.post(f"{page(cal)}/bookings", json=payload)


def parse_ics(body: str) -> list[dict]:
    """The events of an iCalendar file as dicts of property to value, after checking its framing: CRLF line ends, lines
    folded within 75 octets, a VCALENDAR around every VEVENT."""
    assert body.endswith("\r\n") and "\n" not in body.replace("\r\n", "")
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    lines = body.replace("\r\n ", "").split("\r\n")[:-1]
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR" and "VERSION:2.0" in lines
    events, current = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            events.append(current)
            current = None
        elif current is not None:
            key, _, value = line.partition(":")
            current[key] = value
    assert current is None
    return events


def moment(value: str) -> datetime:
    """An instant from the API, whatever offset the database session wrote it with."""
    return datetime.fromisoformat(value)


def instant(day, clock: str, zone: ZoneInfo = NY) -> str:
    return at(str(day), clock, zone).isoformat()  # as the API writes an instant: 2026-11-03T14:00:00+00:00
