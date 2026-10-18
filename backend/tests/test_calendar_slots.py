"""The availability engine without a database: hours, overrides, buffers, notice, window, caps, daylight saving, hosts
in different zones, collective and class calendars, resources, and the sentences that say why a time is hidden."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from calendar_helpers import (
    LON,
    LONG_AGO,
    NY,
    at,
    book,
    calendar,
    host,
    messages,
    offered,
    resource,
    snapshot,
    starts,
    why,
)

from app.calendars import slots

TUESDAY, SUNDAY = "2026-10-20", "2026-10-18"


def test_a_weekday_offers_every_slot_inside_the_hours():
    snap = snapshot(calendar(), host("Theo"))
    times = offered(snap, TUESDAY)
    assert times[0] == "09:00" and times[-1] == "16:30" and len(times) == 16
    assert offered(snap, SUNDAY) == []  # no hours on Sunday


def test_a_longer_meeting_must_end_inside_the_hours_and_the_interval_sets_the_start_times():
    snap = snapshot(calendar(), host("Theo"))
    assert offered(snap, TUESDAY, 60)[-1] == "16:00"
    hourly = snapshot(calendar(slot_interval=60), host("Theo"))
    assert offered(hourly, TUESDAY) == [f"{h:02d}:00" for h in range(9, 17)]
    quarter = snapshot(calendar(slot_interval=15), host("Theo"))
    assert len(offered(quarter, TUESDAY)) == 31  # 09:00 to 16:30


def test_split_days_have_a_gap_and_touching_ranges_join():
    split = snapshot(calendar(), host("Theo", weekly={"tue": [["09:00", "12:00"], ["13:00", "17:00"]]}))
    times = offered(split, TUESDAY)
    assert "12:00" not in times and "12:30" not in times and "13:00" in times
    assert "11:30" in offered(split, TUESDAY, 30) and "11:30" not in offered(split, TUESDAY, 60)
    joined = snapshot(calendar(), host("Theo", weekly={"tue": [["09:00", "12:00"], ["12:00", "15:00"]]}))
    assert "11:30" in offered(joined, TUESDAY, 60)  # an hour across the join


def test_a_date_override_replaces_the_week_for_that_day_only():
    off = snapshot(calendar(), host("Theo", overrides={TUESDAY: []}))
    assert offered(off, TUESDAY) == [] and len(offered(off, "2026-10-21")) == 16
    short = snapshot(calendar(), host("Theo", overrides={TUESDAY: [["10:00", "11:00"]]}))
    assert offered(short, TUESDAY) == ["10:00", "10:30"]
    extra = snapshot(calendar(), host("Theo", overrides={SUNDAY: [["12:00", "13:00"]]}))  # opening a day off
    assert offered(extra, SUNDAY) == ["12:00", "12:30"]


def test_a_booking_blocks_its_time_and_a_buffer_blocks_the_time_next_to_it():
    theo = host("Theo")
    snap = snapshot(calendar(buffer_after=15), theo)
    book(snap, TUESDAY, "10:00")
    times = offered(snap, TUESDAY)
    assert "10:00" not in times and "10:30" not in times  # its own time, and the buffer after it
    assert "09:00" in times and "11:00" in times
    assert "09:30" not in times  # a meeting with a buffer after it cannot be followed at once by another
    before = snapshot(calendar(buffer_before=15), theo)
    book(before, TUESDAY, "10:00")
    after_it = offered(before, TUESDAY)  # a buffer before a meeting wants that time empty on both sides
    assert {"09:30", "10:30"}.isdisjoint(after_it) and {"09:00", "11:00"} <= set(after_it)


def test_the_gap_between_meetings_is_the_larger_buffer_not_the_sum():
    snap = snapshot(calendar(buffer_before=15, buffer_after=15, slot_interval=15), host("Theo"))
    book(snap, TUESDAY, "10:00")  # busy 10:00 to 10:30 with 15 minutes either side
    times = offered(snap, TUESDAY)
    assert "10:45" in times and "10:30" not in times and "09:15" in times and "09:30" not in times


def test_a_booking_of_another_calendar_blocks_the_same_host_with_its_own_buffer():
    theo = host("Theo")
    snap = snapshot(calendar(), theo)
    start = at(TUESDAY, "10:00")
    other = uuid.uuid4()  # a booking of a calendar with a 30 minute buffer after it
    theo.busy.add(slots.Span(start, start + timedelta(minutes=30), 0, 30, other))
    times = offered(snap, TUESDAY)
    assert "10:30" not in times and "11:00" in times


def test_outside_busy_time_blocks_the_host():
    theo = host("Theo")
    snap = snapshot(calendar(), theo)
    theo.busy.add(slots.Span(at(TUESDAY, "13:15"), at(TUESDAY, "14:15"), kind="busy"))
    times = offered(snap, TUESDAY)
    assert {"13:00", "13:30", "14:00"}.isdisjoint(times) and "12:30" in times and "14:30" in times
    assert any("connected calendar" in m for m in messages(why(snap, TUESDAY, "13:30")))


def test_minimum_notice_and_the_booking_window():
    snap = snapshot(calendar(min_notice=240, window_days=7), host("Theo"))
    now = at(TUESDAY, "10:00")
    assert offered(snap, TUESDAY, now=now)[0] == "14:00"  # four hours from 10:00
    assert offered(snap, "2026-10-27", now=now) != []  # day 7
    assert offered(snap, "2026-10-28", now=now) == []  # past the window
    assert "Too far" in " ".join(messages(why(snap, "2026-10-28", "10:00", now=now)))
    assert any("minutes of notice" in m for m in messages(why(snap, TUESDAY, "12:00", now=now)))
    past = why(snapshot(calendar(), host("Theo")), TUESDAY, "11:00", now=at(TUESDAY, "12:00"))
    assert "In the past" in messages(past)


def test_the_calendars_limit_per_day_counts_every_host_and_stops_at_the_limit():
    a, b = host("A"), host("B")
    snap = snapshot(calendar(kind="round_robin", max_per_day=2), a, b)
    book(snap, TUESDAY, "09:00", 30, a)
    book(snap, TUESDAY, "09:00", 30, b)
    assert offered(snap, TUESDAY) == [] and len(offered(snap, "2026-10-21")) == 16
    assert "limit" in " ".join(messages(why(snap, TUESDAY, "12:00")))


def test_a_host_stops_taking_bookings_at_their_daily_cap_and_the_other_host_carries_on():
    a, b = host("A", daily_cap=1), host("B")
    snap = snapshot(calendar(kind="round_robin"), a, b)
    book(snap, TUESDAY, "09:00", 30, a)
    assert "10:00" in offered(snap, TUESDAY)  # B is free
    answer = why(snap, TUESDAY, "10:00")
    assert answer["offered"] and [h["free"] for h in answer["hosts"]] == [False, True]
    assert "reached 1 bookings" in messages(answer)[0]
    alone = snapshot(calendar(), host("A", daily_cap=1))
    book(alone, TUESDAY, "09:00")
    assert offered(alone, TUESDAY) == []


# --- daylight saving ---------------------------------------------------------------------------------------------

def test_the_clock_hours_stay_put_when_the_clocks_change():
    snap = snapshot(calendar(), host("Theo"))
    for day in ("2026-03-06", "2026-03-09", "2026-11-02"):  # Friday before and Monday after, in New York
        assert offered(snap, day)[0] == "09:00" and offered(snap, day)[-1] == "16:30", day
    assert at("2026-03-06", "09:00") - at("2026-03-09", "09:00") != timedelta(days=-3)  # the UTC instants moved


def test_the_hour_that_does_not_exist_is_not_offered_and_hours_that_remain_are():
    snap = snapshot(calendar(), host("Theo", weekly={"sun": [["01:00", "05:00"]]}))
    day = "2026-03-08"  # New York springs forward at 02:00
    assert offered(snap, day) == ["01:00", "01:30", "03:00", "03:30", "04:00", "04:30"]
    assert len(starts(snap, day)) == len(set(starts(snap, day)))  # no instant twice


def test_the_hour_that_happens_twice_is_offered_twice():
    snap = snapshot(calendar(), host("Theo", weekly={"sun": [["00:00", "04:00"]]}))
    day = "2026-11-01"  # New York falls back at 02:00: 01:00 to 02:00 happens twice
    found = starts(snap, day)
    assert len(found) == 10 and len(set(found)) == 10
    assert all(b - a == timedelta(minutes=30) for a, b in zip(found, found[1:], strict=False))  # none lost or doubled
    assert [s.astimezone(NY).strftime("%H:%M") for s in found].count("01:00") == 2


def test_a_day_with_25_hours_has_25_hourly_starts_and_one_with_23_has_23():
    open_all = {d: [["00:00", "24:00"]] for d in slots.WEEKDAYS}
    snap = snapshot(calendar(slot_interval=60), host("Theo", weekly=open_all))
    assert len(starts(snap, "2026-11-01")) == 25 and len(starts(snap, "2026-03-08")) == 23
    assert len(starts(snap, "2026-10-20")) == 24


def test_london_changes_its_clocks_on_other_dates_than_new_york():
    snap = snapshot(calendar(time_zone="Europe/London"), host("Edie", "Europe/London"))
    for day in ("2026-03-27", "2026-03-30", "2026-10-23", "2026-10-26"):  # Fridays and Mondays around both changes
        assert offered(snap, day, zone=LON)[0] == "09:00", day
    night = {"sun": [["00:00", "03:00"]]}
    sunday = snapshot(calendar(time_zone="Europe/London"), host("Edie", "Europe/London", weekly=night))
    assert len(starts(sunday, "2026-03-29", zone=LON)) == 4  # 01:00 does not exist: 00:00, 00:30, 02:00, 02:30
    assert len(starts(sunday, "2026-10-25", zone=LON)) == 8  # 02:00 twice


def test_a_visitor_in_another_zone_sees_the_same_instants_on_their_own_clock():
    snap = snapshot(calendar(), host("Theo"))
    here = starts(snap, TUESDAY)
    seen = [s.astimezone(LON).strftime("%H:%M") for s in here]
    assert seen[0] == "14:00" and seen[-1] == "21:30"  # BST is 5 hours ahead of EDT on 20 October


# --- hosts in different zones, collective and class calendars ----------------------------------------------------

def test_hosts_are_read_in_their_own_zones_and_a_round_robin_offers_when_either_is_free():
    ny, london = host("Nia"), host("Lee", "Europe/London")
    snap = snapshot(calendar(kind="round_robin"), ny, london)
    times = offered(snap, TUESDAY)
    assert times[0] == "04:00" and times[-1] == "16:30"  # Lee's 09:00 BST is 04:00 in New York; Nia works until 17:00
    morning = why(snap, TUESDAY, "05:00")
    assert [h["free"] for h in morning["hosts"]] == [False, True]
    assert "Outside Nia's hours" in messages(morning)[0]


def test_a_collective_calendar_offers_only_times_when_everyone_is_free():
    ny, london = host("Nia"), host("Lee", "Europe/London")
    snap = snapshot(calendar(kind="collective"), ny, london)
    assert offered(snap, TUESDAY) == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"]  # 09:00 NY to 17:00 BST
    book(snap, TUESDAY, "10:00", 30, ny, london)
    assert "10:00" not in offered(snap, TUESDAY)
    busy = snapshot(calendar(kind="collective"), host("Nia"), host("Lee"))
    busy.hosts[1].busy.add(slots.Span(at(TUESDAY, "11:00"), at(TUESDAY, "11:30"), kind="busy"))
    assert "11:00" not in offered(busy, TUESDAY) and "11:30" in offered(busy, TUESDAY)
    answer = why(busy, TUESDAY, "11:00")
    assert not answer["offered"] and [h["free"] for h in answer["hosts"]] == [True, False]


def test_a_collective_calendar_with_a_paused_host_waits_for_nobody_but_the_active_ones():
    snap = snapshot(calendar(kind="collective"), host("Nia"), host("Lee", active=False))
    assert len(offered(snap, TUESDAY)) == 16
    assert "paused" in " ".join(messages(why(snap, TUESDAY, "10:00")))


def test_a_class_has_seats_and_a_full_class_hides_its_slot():
    theo = host("Theo")
    snap = snapshot(calendar(kind="class", seats=3, slot_interval=60), theo)
    for _ in range(2):
        book(snap, TUESDAY, "10:00", 30, theo)
    assert "10:00" in offered(snap, TUESDAY)  # two of three seats taken
    book(snap, TUESDAY, "10:00", 30, theo)
    assert "10:00" not in offered(snap, TUESDAY) and "11:00" in offered(snap, TUESDAY)
    assert any("class is full" in m for m in messages(why(snap, TUESDAY, "10:00")))


def test_a_class_slot_does_not_overlap_another_class_that_starts_at_a_different_time():
    theo = host("Theo")
    snap = snapshot(calendar(kind="class", seats=5, durations=[60], slot_interval=30), theo)
    book(snap, TUESDAY, "10:00", 60, theo)
    times = offered(snap, TUESDAY, 60)
    assert "10:00" in times and "10:30" not in times and "09:30" not in times and "11:00" in times


# --- resources ---------------------------------------------------------------------------------------------------

def test_a_room_is_taken_by_one_booking_at_a_time_and_quantity_allows_more():
    room = resource("Room 1")
    snap = snapshot(calendar(kind="round_robin"), host("A"), host("B"), resources=[room])
    snap.add(at(TUESDAY, "10:00"), at(TUESDAY, "10:30"), [snap.hosts[0].user_id])
    assert "10:00" not in offered(snap, TUESDAY)  # B is free, but the room is not
    assert any("capacity reached" in m for m in messages(why(snap, TUESDAY, "10:00")))
    pair = resource("Bays", quantity=2)
    snap2 = snapshot(calendar(kind="round_robin"), host("A"), host("B"), resources=[pair])
    snap2.add(at(TUESDAY, "10:00"), at(TUESDAY, "10:30"), [snap2.hosts[0].user_id])
    assert "10:00" in offered(snap2, TUESDAY)
    snap2.add(at(TUESDAY, "10:00"), at(TUESDAY, "10:30"), [snap2.hosts[1].user_id])
    assert "10:00" not in offered(snap2, TUESDAY)


def test_a_booking_that_needs_two_of_a_resource_and_a_resource_with_its_own_hours():
    need_two = resource("Chairs", quantity=3, need=2)
    snap = snapshot(calendar(kind="round_robin"), host("A"), host("B"), resources=[need_two])
    snap.add(at(TUESDAY, "10:00"), at(TUESDAY, "10:30"), [snap.hosts[0].user_id])
    assert "10:00" not in offered(snap, TUESDAY)  # 2 used of 3, and another booking needs 2
    morning = resource("Studio", weekly={"tue": [["09:00", "12:00"]]})
    snap2 = snapshot(calendar(), host("A"), resources=[morning])
    times = offered(snap2, TUESDAY)
    assert times[-1] == "11:30" and any("closed" in m for m in messages(why(snap2, TUESDAY, "13:00")))


# --- explaining a time -------------------------------------------------------------------------------------------

def test_the_explainer_names_the_host_and_the_reason_for_each_hidden_time():
    theo = host("Theo")
    snap = snapshot(calendar(buffer_after=15), theo)
    book(snap, TUESDAY, "10:00")
    early = why(snap, TUESDAY, "07:00")
    assert not early["offered"] and messages(early) == ["Outside Theo's hours (works 09:00 to 17:00 on Tuesday, "
                                                         "America/New_York)"]
    taken = why(snap, TUESDAY, "10:00")
    assert messages(taken) == ["Theo has a booking from 10:00 to 10:30"]
    buffer = why(snap, TUESDAY, "10:30")
    assert messages(buffer) == ["Buffer after the 10:00 booking"]
    free = why(snap, TUESDAY, "11:00")
    assert free["offered"] and messages(free) == []
    assert why(snap, SUNDAY, "11:00")["hosts"][0]["reasons"][0]["code"] == "day_off"


def test_the_explainer_names_a_day_off_a_missing_week_a_paused_calendar_and_an_off_grid_time():
    snap = snapshot(calendar(), host("Theo", overrides={TUESDAY: []}))
    assert "Theo is off on Tuesday 20 October" in messages(why(snap, TUESDAY, "10:00"))
    none = snapshot(calendar(), host("Theo", has_hours=False, weekly={}))
    assert "Theo has no working hours set" in messages(why(none, TUESDAY, "10:00"))
    paused = snapshot(calendar(status="paused"), host("Theo"))
    assert offered(paused, TUESDAY) == [] and "The calendar is paused" in messages(why(paused, TUESDAY, "10:00"))
    odd = why(snapshot(calendar(), host("Theo")), TUESDAY, "10:10")
    assert not odd["offered"] and "every 30 minutes from midnight in America/New_York" in odd["reasons"][0]["message"]
    nobody = snapshot(calendar())
    assert "The calendar has no active hosts" in messages(why(nobody, TUESDAY, "10:00"))


def test_the_explainer_times_are_on_the_clock_it_is_asked_for():
    snap = snapshot(calendar(buffer_after=15), host("Theo"))
    book(snap, TUESDAY, "10:00")
    answer = slots.explain(snap, at(TUESDAY, "10:30"), 30, LONG_AGO, LON)
    assert messages(answer) == ["Buffer after the 15:00 booking"]  # 10:00 in New York is 15:00 in London


def test_an_empty_week_and_an_unknown_zone_are_refused():
    assert slots.clean_weekly({"mon": [["09:00", "17:00"]]})["tue"] == []
    assert slots.clean_weekly({"fri": [["09:00", "24:00"]]})["fri"] == [["09:00", "24:00"]]
    for bad in ({"mon": [["17:00", "09:00"]]}, {"mon": [["09:00", "10:00"], ["09:30", "11:00"]]},
                {"monday": []}, {"mon": [["9:00", "10:00"]]}, {"mon": [["09:00", "25:00"]]},
                {"mon": [["09:00", "10:00"]] * 7}, {"mon": "09:00"}):
        with pytest.raises(ValueError):
            slots.clean_weekly(bad)
    with pytest.raises(ValueError):
        slots.zone("Mars/Olympus")


def test_slots_are_never_offered_in_the_past():
    snap = snapshot(calendar(), host("Theo"))
    now = at(TUESDAY, "12:10")
    assert offered(snap, TUESDAY, now=now)[0] == "12:30"
    assert datetime(2026, 1, 1, tzinfo=UTC) < now
