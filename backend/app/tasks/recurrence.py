"""Recurrence rules of tasks: the part of RRULE (RFC 5545) people use, as pure functions with no database.

    FREQ=DAILY|WEEKLY|MONTHLY   required
    INTERVAL=n                  every n days, weeks or months (default 1)
    BYDAY=MO,WE                 weekly only: which days of the week
    BYMONTHDAY=n                monthly only: the day of the month, 1 to 31, or -1 for the last day
    COUNT=n | UNTIL=date        stop after n occurrences (the first included), or after a date (never both)

A short month clamps the day (the 31st becomes the 28th), so BYMONTHDAY=31 means "the 31st, or the last day". A task
carries the rule as text; completing it asks `advance` for the next due date and the rule to carry on with."""
import calendar
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, tzinfo

DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")  # the week starts on Monday, as in `date.weekday()`
FREQS = ("DAILY", "WEEKLY", "MONTHLY")
MAX_INTERVAL = 99
MAX_COUNT = 999


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    freq: str
    interval: int = 1
    byday: tuple[str, ...] = ()
    bymonthday: int | None = None
    count: int | None = None
    until: date | datetime | None = None  # a date ends the series on that day (inclusive), a datetime at that instant


def number(name: str, raw: str, low: int, high: int) -> int:
    if not re.fullmatch(r"-?\d+", raw) or not low <= int(raw) <= high:
        raise RuleError(f"{name} must be a number from {low} to {high}")
    return int(raw)


def parse_until(raw: str) -> date | datetime:
    try:
        if len(raw) == 8:
            return datetime.strptime(raw, "%Y%m%d").date()
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        raise RuleError("UNTIL must be YYYYMMDD or YYYYMMDDTHHMMSSZ") from None


def parse(text: str) -> Rule:
    """The rule in `text` (an optional `RRULE:` prefix is allowed), or RuleError saying what is wrong."""
    parts: dict[str, str] = {}
    for item in text.removeprefix("RRULE:").strip().split(";"):
        key, _, value = item.partition("=")
        key = key.strip().upper()
        if not value or key in parts:
            raise RuleError(f"{item!r} is not a rule part, or it is repeated")
        parts[key] = value.strip().upper()
    if parts.get("FREQ") not in FREQS:
        raise RuleError("FREQ must be DAILY, WEEKLY or MONTHLY")
    unknown = parts.keys() - {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "COUNT", "UNTIL"}
    if unknown:
        raise RuleError(f"{sorted(unknown)[0]} is not supported")
    if "COUNT" in parts and "UNTIL" in parts:
        raise RuleError("COUNT and UNTIL cannot be used together")
    freq = parts["FREQ"]
    if "BYDAY" in parts and freq != "WEEKLY":
        raise RuleError("BYDAY needs FREQ=WEEKLY")
    if "BYMONTHDAY" in parts and freq != "MONTHLY":
        raise RuleError("BYMONTHDAY needs FREQ=MONTHLY")
    days = parts.get("BYDAY", "").split(",") if "BYDAY" in parts else []
    if any(d not in DAYS for d in days):
        raise RuleError("BYDAY must list days from MO, TU, WE, TH, FR, SA, SU")
    monthday = number("BYMONTHDAY", parts["BYMONTHDAY"], -1, 31) if "BYMONTHDAY" in parts else None
    if monthday == 0:
        raise RuleError("BYMONTHDAY must be 1 to 31, or -1 for the last day")
    return Rule(freq, number("INTERVAL", parts["INTERVAL"], 1, MAX_INTERVAL) if "INTERVAL" in parts else 1,
                tuple(sorted(set(days), key=DAYS.index)), monthday,
                number("COUNT", parts["COUNT"], 1, MAX_COUNT) if "COUNT" in parts else None,
                parse_until(parts["UNTIL"]) if "UNTIL" in parts else None)


def render(rule: Rule) -> str:
    """The canonical text of a rule: parse(render(rule)) == rule, and equal rules give equal text."""
    until = rule.until.strftime("%Y%m%d" if type(rule.until) is date else "%Y%m%dT%H%M%SZ") if rule.until else None
    parts = [("FREQ", rule.freq), ("INTERVAL", rule.interval if rule.interval != 1 else None),
             ("BYDAY", ",".join(rule.byday) or None), ("BYMONTHDAY", rule.bymonthday), ("COUNT", rule.count),
             ("UNTIL", until)]
    return ";".join(f"{k}={v}" for k, v in parts if v is not None)


def month_day(year: int, month: int, wanted: int) -> date:
    length = calendar.monthrange(year, month)[1]
    return date(year, month, length + 1 + wanted if wanted < 0 else min(wanted, length))


def step(rule: Rule, day: date) -> date:
    """The occurrence after the one on `day`."""
    if rule.freq == "DAILY":
        return day + timedelta(days=rule.interval)
    if rule.freq == "MONTHLY":
        if rule.bymonthday and (here := month_day(day.year, day.month, rule.bymonthday)) > day:
            return here  # the day of this month is still ahead
        year, month = divmod(day.year * 12 + day.month - 1 + rule.interval, 12)
        return month_day(year, month + 1, rule.bymonthday or day.day)
    if not rule.byday:
        return day + timedelta(weeks=rule.interval)
    days = [DAYS.index(d) for d in rule.byday]
    later = [d for d in days if d > day.weekday()]  # the rest of this week first, then `interval` weeks on
    if later:
        return day + timedelta(days=later[0] - day.weekday())
    return day - timedelta(days=day.weekday()) + timedelta(weeks=rule.interval, days=days[0])


# ponytail: the next occurrence follows the old due date even when that is already past (no catch-up to today), so
# finishing a daily task three days late leaves the next one overdue too.
def advance(rule: Rule, due: datetime, all_day: bool, tz: tzinfo, occurrences: int) -> tuple[datetime, Rule] | None:
    """The next due date after `due` (the `occurrences`-th of the series) and the rule to carry on with, or None when
    the series ends. A timed task keeps its wall clock time in `tz`; an all-day task (stored as midnight UTC) moves by
    dates. A monthly rule without BYMONTHDAY gets the day it started on, so the 31st does not drift to the 28th."""
    if rule.count is not None and occurrences >= rule.count:
        return None
    zone = UTC if all_day else tz
    local = due.astimezone(zone)
    if rule.freq == "MONTHLY" and rule.bymonthday is None:
        rule = replace(rule, bymonthday=local.day)
    day = step(rule, local.date())
    when = datetime.combine(day, local.time(), zone).astimezone(UTC)
    if rule.until is not None and (when > rule.until if isinstance(rule.until, datetime) else day > rule.until):
        return None
    return when, rule
