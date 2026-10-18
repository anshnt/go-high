"""Round robin without a database: weights, caps, stickiness, fairness over the rolling window, skipping hosts who are
not free, and the simulation that plays the rotation forward."""
from collections import Counter

from calendar_helpers import LONG_AGO, NY, at, book, calendar, host, snapshot

from app.calendars import routing, slots

TUESDAY = "2026-10-20"


def run(snap, n=9, owner=None, now=LONG_AGO):
    return routing.simulate(snap, now, 30, n, owner)


def winners(plan) -> list[str]:
    return [r["host"]["name"] for r in plan["rounds"]]


def test_weights_decide_how_often_each_host_is_chosen():
    snap = snapshot(calendar(kind="round_robin"), host("A", weight=2), host("B", weight=1))
    plan = run(snap, 9, now=at("2026-10-19", "00:00"))
    assert winners(plan) == ["A", "B", "A", "A", "B", "A", "A", "B", "A"]
    assert Counter(winners(plan)) == {"A": 6, "B": 3}
    shares = {h["name"]: (h["share"], h["target_share"]) for h in plan["hosts"]}
    assert shares == {"A": (0.667, 0.667), "B": (0.333, 0.333)}
    assert plan["found"] == 9 and plan["rounds"][0]["reason"].startswith("fewest bookings for their weight")


def test_equal_weights_alternate_and_a_tie_goes_to_priority_then_to_the_host_added_first():
    snap = snapshot(calendar(kind="round_robin"), host("A"), host("B"), host("C"))
    assert winners(run(snap, 6, now=at("2026-10-19"))) == ["A", "B", "C", "A", "B", "C"]
    ranked = snapshot(calendar(kind="round_robin"), host("A"), host("B", priority=5), host("C"))
    assert winners(run(ranked, 3, now=at("2026-10-19"))) == ["B", "A", "C"]


def test_a_host_with_weight_zero_gets_nothing_and_a_paused_host_gets_nothing():
    snap = snapshot(calendar(kind="round_robin"), host("A"), host("B", weight=0), host("C", active=False))
    plan = run(snap, 4, now=at("2026-10-19"))
    assert set(winners(plan)) == {"A"}
    by_name = {h["name"]: h for h in plan["hosts"]}
    assert by_name["B"]["target_share"] == 0 and by_name["A"]["target_share"] == 1


def test_recent_bookings_count_against_a_host_so_someone_who_was_busy_gets_fewer():
    a, b = host("A"), host("B")
    a.count, b.count = 4, 1  # in the rolling window already
    snap = snapshot(calendar(kind="round_robin"), a, b)
    assert winners(run(snap, 4, now=at("2026-10-19"))) == ["B", "B", "B", "A"]  # B catches up to A


def test_a_host_who_is_not_free_is_skipped_and_gets_the_next_one_instead():
    a, b = host("A"), host("B")
    a.busy.add(slots.Span(at(TUESDAY, "09:00"), at(TUESDAY, "09:30"), kind="busy"))
    snap = snapshot(calendar(kind="round_robin"), a, b)
    plan = run(snap, 2, now=at(TUESDAY))
    assert winners(plan) == ["B", "A"]  # at 09:00 only B is free; at 09:30 both are and A has fewer
    assert plan["rounds"][0]["reason"] == "the only host free" and plan["rounds"][0]["free"] == ["B"]


def test_the_contact_owner_keeps_their_contact_even_when_the_rotation_says_otherwise():
    a, b = host("A"), host("B")
    snap = snapshot(calendar(kind="round_robin"), a, b)
    plan = run(snap, 3, owner=b.user_id, now=at("2026-10-19"))
    assert winners(plan) == ["B", "B", "B"] and plan["rounds"][0]["reason"] == "owns the contact"
    # an owner who is not free at the time loses the contact to the host who is
    b.busy.add(slots.Span(at(TUESDAY, "09:00"), at(TUESDAY, "09:30"), kind="busy"))
    plan = run(snapshot(calendar(kind="round_robin"), a, b), 1, owner=b.user_id, now=at(TUESDAY))
    assert winners(plan) == ["A"] and plan["rounds"][0]["reason"] == "the only host free"


def test_a_daily_cap_sends_the_rest_of_the_day_to_the_other_hosts():
    a, b = host("A", daily_cap=2), host("B")
    snap = snapshot(calendar(kind="round_robin"), a, b)
    plan = run(snap, 8, now=at(TUESDAY))
    first_day = [r["host"]["name"] for r in plan["rounds"] if r["start"].astimezone(NY).date().isoformat() == TUESDAY]
    assert first_day.count("A") <= 2 and len(first_day) == 8  # all eight fit in the day; A takes at most two of them


def test_personal_and_collective_calendars_do_not_rotate():
    solo = snapshot(calendar(), host("A"))
    verdict = slots.check(solo, at(TUESDAY, "10:00"), 30, LONG_AGO)
    pick = routing.choose(solo, verdict)
    assert pick.host.name == "A" and [p.name for p in pick.attendees] == ["A"] and pick.reason == "the host"
    group = snapshot(calendar(kind="collective"), host("A"), host("B"))
    pick = routing.choose(group, slots.check(group, at(TUESDAY, "10:00"), 30, LONG_AGO))
    assert pick.host.name == "A" and [p.name for p in pick.attendees] == ["A", "B"]


def test_the_simulation_changes_nothing_it_was_given_and_stops_when_nothing_is_open():
    only = snapshot(calendar(kind="round_robin", window_days=1), host("A", weekly={"tue": [["09:00", "10:00"]]}))
    plan = run(only, 5, now=at(TUESDAY, "00:00"))
    assert plan["found"] == 2 and plan["asked"] == 5  # two half hours exist
    again = snapshot(calendar(kind="round_robin"), host("A"))
    book(again, TUESDAY, "09:00")
    assert again.hosts[0].count == 1
