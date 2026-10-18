"""Recurrence rules of tasks: parsing, the canonical text and the next due date for each frequency (pure functions)."""
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.tasks import recurrence as r

NEW_YORK = ZoneInfo("America/New_York")


def at(y, m, d, hour=9) -> datetime:
    return datetime(y, m, d, hour, tzinfo=UTC)


def dates(rule: str, first: datetime, n: int = 6, all_day: bool = False, tz=UTC) -> list[date]:
    """The dates of the first n occurrences after `first`, completing each in turn as the API does."""
    found, rule_, due = [], r.parse(rule), first
    for seen in range(1, n + 1):
        following = r.advance(rule_, due, all_day, tz, seen)
        if following is None:
            break
        due, rule_ = following
        found.append(due.astimezone(UTC if all_day else tz).date())
    return found


def test_daily_every_n_days():
    assert dates("FREQ=DAILY", at(2026, 10, 30), 3) == [date(2026, 10, 31), date(2026, 11, 1), date(2026, 11, 2)]
    assert dates("FREQ=DAILY;INTERVAL=3", at(2026, 10, 30), 2) == [date(2026, 11, 2), date(2026, 11, 5)]


def test_weekly_repeats_on_the_same_weekday_unless_byday_says_otherwise():
    monday = at(2026, 10, 19)
    assert dates("FREQ=WEEKLY", monday, 2) == [date(2026, 10, 26), date(2026, 11, 2)]
    assert dates("FREQ=WEEKLY;INTERVAL=2", monday, 2) == [date(2026, 11, 2), date(2026, 11, 16)]


def test_weekly_byday_walks_the_days_of_each_week():
    monday = at(2026, 10, 19)
    assert dates("FREQ=WEEKLY;BYDAY=MO,WE,FR", monday, 5) == [
        date(2026, 10, 21), date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 28), date(2026, 10, 30)]
    weekdays = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    assert dates(weekdays, at(2026, 10, 23), 3) == [date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)]
    # every other week skips a whole week after the last day of the one it is in
    assert dates("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE", monday, 4) == [
        date(2026, 10, 21), date(2026, 11, 2), date(2026, 11, 4), date(2026, 11, 16)]
    # the week starts on Monday, so a Sunday is the end of its week, not the start of the next
    assert dates("FREQ=WEEKLY;BYDAY=SU", at(2026, 10, 21), 2) == [date(2026, 10, 25), date(2026, 11, 1)]
    # a due date that is not one of the days moves on to the next listed day
    assert dates("FREQ=WEEKLY;BYDAY=MO", at(2026, 10, 21), 1) == [date(2026, 10, 26)]
    assert dates("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO", at(2026, 10, 21), 1) == [date(2026, 11, 2)]


def test_monthly_keeps_its_day_and_clamps_to_the_end_of_short_months():
    january_31st = at(2027, 1, 31)
    assert dates("FREQ=MONTHLY", january_31st, 5) == [
        date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30), date(2027, 5, 31), date(2027, 6, 30)]
    assert dates("FREQ=MONTHLY", at(2028, 1, 31), 1) == [date(2028, 2, 29)]  # a leap year
    assert dates("FREQ=MONTHLY;BYMONTHDAY=-1", at(2027, 1, 15), 4) == [  # the 31st of January is still ahead
        date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31), date(2027, 4, 30)]
    assert dates("FREQ=MONTHLY;BYMONTHDAY=31", at(2027, 1, 10), 3) == [
        date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)]
    assert dates("FREQ=MONTHLY;BYMONTHDAY=1", at(2026, 11, 15), 2) == [date(2026, 12, 1), date(2027, 1, 1)]
    assert dates("FREQ=MONTHLY;INTERVAL=3", at(2026, 11, 30), 3) == [date(2027, 2, 28), date(2027, 5, 30),
                                                                     date(2027, 8, 30)]
    assert dates("FREQ=MONTHLY", at(2026, 12, 15), 2) == [date(2027, 1, 15), date(2027, 2, 15)]  # across a year


def test_a_monthly_rule_without_a_day_fixes_the_day_it_started_on():
    first = r.advance(r.parse("FREQ=MONTHLY"), at(2027, 1, 31), False, UTC, 1)
    assert first and r.render(first[1]) == "FREQ=MONTHLY;BYMONTHDAY=31"


def test_count_is_the_number_of_occurrences_including_the_first():
    assert dates("FREQ=DAILY;COUNT=3", at(2026, 10, 19), 10) == [date(2026, 10, 20), date(2026, 10, 21)]
    assert dates("FREQ=DAILY;COUNT=1", at(2026, 10, 19), 10) == []
    assert dates("FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4", at(2026, 10, 19), 10) == [
        date(2026, 10, 21), date(2026, 10, 26), date(2026, 10, 28)]


def test_until_ends_the_series_on_that_day_inclusive():
    assert dates("FREQ=DAILY;UNTIL=20261022", at(2026, 10, 19), 10) == [
        date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]
    assert dates("FREQ=DAILY;UNTIL=20261019", at(2026, 10, 19), 10) == []
    assert dates("FREQ=DAILY;UNTIL=20261021T090000Z", at(2026, 10, 19), 10) == [date(2026, 10, 20), date(2026, 10, 21)]
    assert dates("FREQ=DAILY;UNTIL=20261021T085959Z", at(2026, 10, 19), 10) == [date(2026, 10, 20)]


def test_a_timed_task_keeps_its_wall_clock_across_a_daylight_saving_change():
    friday = datetime(2026, 10, 30, 9, tzinfo=NEW_YORK).astimezone(UTC)  # 13:00 UTC, summer time
    following = r.advance(r.parse("FREQ=DAILY"), friday, False, NEW_YORK, 1)
    saturday = following[0]
    assert saturday.astimezone(NEW_YORK).hour == 9 and saturday.astimezone(NEW_YORK).date() == date(2026, 10, 31)
    after = r.advance(r.parse("FREQ=DAILY"), saturday, False, NEW_YORK, 2)[0]  # the clocks went back on 1 November
    assert after.astimezone(NEW_YORK).hour == 9 and after.hour == 14 and saturday.hour == 13


def test_an_all_day_task_moves_by_dates_in_any_zone():
    midnight = datetime(2026, 10, 19, tzinfo=UTC)
    for zone in (UTC, NEW_YORK, ZoneInfo("Pacific/Auckland")):
        assert r.advance(r.parse("FREQ=WEEKLY"), midnight, True, zone, 1)[0] == datetime(2026, 10, 26, tzinfo=UTC)


@pytest.mark.parametrize("text, canonical", [
    ("FREQ=DAILY", "FREQ=DAILY"),
    ("freq=weekly;byday=we,mo", "FREQ=WEEKLY;BYDAY=MO,WE"),
    ("RRULE:FREQ=WEEKLY;INTERVAL=1;BYDAY=MO", "FREQ=WEEKLY;BYDAY=MO"),
    ("FREQ=MONTHLY;INTERVAL=2;BYMONTHDAY=-1;COUNT=5", "FREQ=MONTHLY;INTERVAL=2;BYMONTHDAY=-1;COUNT=5"),
    ("FREQ=DAILY;UNTIL=20261231", "FREQ=DAILY;UNTIL=20261231"),
    ("FREQ=DAILY;UNTIL=20261231T120000Z", "FREQ=DAILY;UNTIL=20261231T120000Z"),
    ("FREQ=WEEKLY;BYDAY=MO,MO", "FREQ=WEEKLY;BYDAY=MO"),
])
def test_rules_are_written_in_one_canonical_form(text, canonical):
    assert r.render(r.parse(text)) == canonical
    assert r.parse(canonical) == r.parse(text)


@pytest.mark.parametrize("text", [
    "", "FREQ", "FREQ=YEARLY", "FREQ=HOURLY", "INTERVAL=2", "FREQ=DAILY;FREQ=DAILY", "FREQ=DAILY;INTERVAL=0",
    "FREQ=DAILY;INTERVAL=100", "FREQ=DAILY;INTERVAL=x", "FREQ=DAILY;COUNT=0", "FREQ=DAILY;COUNT=1000",
    "FREQ=DAILY;COUNT=2;UNTIL=20261231", "FREQ=DAILY;UNTIL=2026-12-31", "FREQ=DAILY;BYDAY=MO",
    "FREQ=WEEKLY;BYDAY=XX", "FREQ=WEEKLY;BYDAY=1MO", "FREQ=WEEKLY;BYMONTHDAY=1", "FREQ=MONTHLY;BYMONTHDAY=0",
    "FREQ=MONTHLY;BYMONTHDAY=32", "FREQ=MONTHLY;BYMONTHDAY=-2", "FREQ=DAILY;BYSETPOS=1", "FREQ=DAILY;;",
])
def test_rules_outside_the_supported_subset_are_refused(text):
    with pytest.raises(r.RuleError):
        r.parse(text)
