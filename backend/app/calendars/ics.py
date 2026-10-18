"""iCalendar (RFC 5545) for bookings: one event for a confirmation link, many for a person's private feed. Times are
UTC, lines end in CRLF and fold at 75 octets, text is escaped. No attendee addresses go in: an event file travels by
mail and chat, and the invitee's address belongs to the booking, not to the file."""
from datetime import UTC, datetime

from .models import Booking, Calendar

STATUS = {"booked": "TENTATIVE", "confirmed": "CONFIRMED", "rescheduled": "CONFIRMED", "showed": "CONFIRMED",
          "no_show": "CONFIRMED", "cancelled": "CANCELLED"}
LIMIT = 75


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def text(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n")
            .replace("\r", "\n").replace("\n", "\\n"))


def fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after one space, never inside a UTF-8 character."""
    out, current, size = [], "", 0
    for ch in line:
        width = len(ch.encode())
        if size + width > (LIMIT if not out else LIMIT - 1):
            out.append(current)
            current, size = "", 0
        current += ch
        size += width
    return "\r\n ".join([*out, current])


def event(b: Booking, cal: Calendar, *, url: str | None = None, now: datetime | None = None) -> list[str]:
    place = b.location.get("value") or b.location.get("kind", "")
    notes = [f"Booked with {cal.name}.", *([f"Change or cancel: {url}"] if url else [])]
    lines = ["BEGIN:VEVENT", f"UID:{b.id}@go-high", f"DTSTAMP:{stamp(now or datetime.now(UTC))}",
             f"DTSTART:{stamp(b.starts_at)}", f"DTEND:{stamp(b.ends_at)}", f"SUMMARY:{text(cal.name)}",
             f"DESCRIPTION:{text(chr(10).join(notes))}", f"STATUS:{STATUS[b.status]}",
             f"SEQUENCE:{b.reschedules + (b.status == 'cancelled')}", f"LAST-MODIFIED:{stamp(b.updated_at)}"]
    if place:
        lines.append(f"LOCATION:{text(place)}")
    if url:
        lines.append(f"URL:{url}")
    return [*lines, "END:VEVENT"]


def calendar(events: list[list[str]], name: str = "Bookings") -> str:
    head = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//go-high//calendars//EN", "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH", f"X-WR-CALNAME:{text(name)}"]
    lines = [*head, *(line for e in events for line in e), "END:VCALENDAR"]
    return "".join(fold(line) + "\r\n" for line in lines)
