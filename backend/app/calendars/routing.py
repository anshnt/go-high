"""Who gets a booking (module 16). A personal or class calendar has one host and a collective one sends everybody. Round
robin and service calendars rotate: of the hosts who are free (not in another booking, within their hours, under their
daily cap) the one with the fewest bookings for their weight goes first, a tie going to the higher priority and then to
the host added first. A host who owns the contact keeps them, whatever the rotation says. Counts are the calendar's own
bookings from the last ROLLING_DAYS days onward, so a host who was away catches up and nobody is starved or flooded.

`simulate` plays the rotation forward on the snapshot, one booking for each of the next open start times in order, and
writes nothing: it is the "who would get the next 20 bookings" preview."""
import uuid
from datetime import datetime, timedelta
from fractions import Fraction
from typing import NamedTuple

from .slots import Person, Snapshot, Verdict, open_slots

ROTATING = ("round_robin", "service")


class Pick(NamedTuple):
    host: Person  # who the booking belongs to
    attendees: list[Person]  # everyone who attends (more than the host on a collective calendar)
    reason: str


def share(host: Person) -> Fraction:
    return Fraction(host.count, host.weight)


def choose(snap: Snapshot, verdict: Verdict, owner_id: uuid.UUID | None = None) -> Pick:
    """The host for a time that `verdict` says is open."""
    kind, free = snap.calendar.kind, verdict.free
    if kind == "collective":
        return Pick(free[0], free, "every host attends")
    if kind not in ROTATING or len(free) == 1:
        return Pick(free[0], [free[0]], "the only host free" if kind in ROTATING else "the host")
    if owner := next((h for h in free if h.user_id == owner_id), None):
        return Pick(owner, [owner], "owns the contact")
    order = {h.user_id: i for i, h in enumerate(snap.hosts)}
    best = min(free, key=lambda h: (share(h), -h.priority, order[h.user_id]))
    return Pick(best, [best], f"fewest bookings for their weight ({best.count} at weight {best.weight})")


def simulate(snap: Snapshot, now: datetime, duration: int, n: int, owner_id: uuid.UUID | None = None) -> dict:
    """The next `n` bookings if they arrived now, one for each of the next open start times: who gets each, and per host
    the share they receive against the share their weight entitles them to."""
    hi = now + timedelta(days=snap.calendar.window_days + 1)
    rounds, given = [], {h.user_id: 0 for h in snap.hosts}
    for i, (start, verdict) in enumerate(open_slots(snap, now, hi, now, duration), 1):
        if i > n:
            break
        pick = choose(snap, verdict, owner_id)
        end = start + timedelta(minutes=duration)
        snap.add(start, end, [p.user_id for p in pick.attendees])
        given[pick.host.user_id] += 1
        who = {"user_id": pick.host.user_id, "name": pick.host.name}
        rounds.append({"n": i, "start": start, "end": end, "host": who, "reason": pick.reason,
                       "free": [h.name for h in verdict.free]})
    weights = {h.user_id: h.weight for h in snap.hosts if h.active and h.weight > 0}
    total = sum(weights.values())
    hosts = [{"user_id": h.user_id, "name": h.name, "weight": h.weight, "bookings": given[h.user_id],
              "target_share": round(weights.get(h.user_id, 0) / total, 3) if total else 0,
              "share": round(given[h.user_id] / len(rounds), 3) if rounds else 0} for h in snap.hosts]
    return {"rounds": rounds, "hosts": hosts, "asked": n, "found": len(rounds)}
