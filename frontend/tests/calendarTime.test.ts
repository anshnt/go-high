import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addDays,
  dateKey,
  endOfDay,
  formatClock,
  formatWhen,
  isClock,
  isDateKey,
  isZone,
  offsetMinutes,
  rangeLabel,
  startOfDay,
  wallMinutes,
  weekRange,
  weekdayOf,
  zoneList,
  zoneNote,
  zonedToUtc,
} from "../src/calendar/time.ts";

const NY = "America/New_York";
const iso = (ms: number) => new Date(ms).toISOString();

test("calendar time: date keys and clocks are checked strictly", () => {
  assert.ok(isDateKey("2028-02-29") && isDateKey("2026-12-31"));
  assert.ok(!isDateKey("2026-02-29") && !isDateKey("2026-13-01") && !isDateKey("2026-1-01") && !isDateKey(""));
  assert.ok(isClock("00:00") && isClock("23:59"));
  assert.ok(!isClock("24:00") && !isClock("9:00") && !isClock("12:60"));
  assert.ok(isZone(NY) && !isZone("Mars/Olympus"));
});

test("calendar time: day arithmetic has no zone, so it crosses months, years and leap days", () => {
  assert.equal(addDays("2026-12-31", 1), "2027-01-01");
  assert.equal(addDays("2028-03-01", -1), "2028-02-29");
  assert.equal(addDays("2026-03-08", 1), "2026-03-09", "the day the clocks change is still one day");
  assert.equal(weekdayOf("2026-10-19"), 0, "a Monday");
  assert.equal(weekdayOf("2026-10-18"), 6, "a Sunday");
});

test("calendar time: an instant falls on the day of the viewer's wall clock", () => {
  const ms = Date.UTC(2026, 9, 19, 2, 0); // 02:00 UTC is still the evening before in New York
  assert.equal(dateKey(ms, "UTC"), "2026-10-19");
  assert.equal(dateKey(ms, NY), "2026-10-18");
  assert.equal(wallMinutes(ms, NY), 22 * 60);
  assert.equal(offsetMinutes(Date.UTC(2026, 6, 1), NY), -240);
  assert.equal(offsetMinutes(Date.UTC(2026, 0, 1), NY), -300);
  assert.equal(offsetMinutes(Date.UTC(2026, 6, 1), "Asia/Kolkata"), 330);
});

test("calendar time: a skipped time lands after the gap and a repeated time is the first of the two", () => {
  // 2026-03-08 02:30 does not happen in New York: the clock goes from 02:00 EST to 03:00 EDT
  assert.equal(iso(zonedToUtc("2026-03-08", "02:30", NY)), "2026-03-08T07:30:00.000Z");
  // 2026-11-01 01:30 happens twice; the first is EDT (UTC-4)
  assert.equal(iso(zonedToUtc("2026-11-01", "01:30", NY)), "2026-11-01T05:30:00.000Z");
  assert.equal(iso(zonedToUtc("2026-10-19", "09:30", NY)), "2026-10-19T13:30:00.000Z");
  assert.equal(zonedToUtc("2026-10-19", "24:00", NY), startOfDay("2026-10-20", NY), "24:00 is the end of the day");
  assert.equal(endOfDay("2026-10-19", NY), startOfDay("2026-10-20", NY));
});

test("calendar time: a week runs Monday to Sunday and is an hour short or long when the clocks change", () => {
  const week = weekRange("2026-10-21", NY);
  assert.deepEqual(week.days, ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"]);
  assert.deepEqual(weekRange("2026-10-25", NY).days, week.days, "Sunday belongs to the week before it");
  assert.equal((week.to - week.from) / 3_600_000, 168);
  assert.equal((weekRange("2026-03-04", NY).to - weekRange("2026-03-04", NY).from) / 3_600_000, 167);
  assert.equal((weekRange("2026-10-28", NY).to - weekRange("2026-10-28", NY).from) / 3_600_000, 169);
  assert.equal(iso(week.from), "2026-10-19T04:00:00.000Z");
});

test("calendar time: labels for ranges, clocks and zones", () => {
  assert.equal(rangeLabel("2026-10-19", "2026-10-25"), "Oct 19 - 25, 2026");
  assert.equal(rangeLabel("2026-10-26", "2026-11-01"), "Oct 26 - Nov 1, 2026");
  assert.equal(rangeLabel("2026-12-28", "2027-01-03"), "Dec 28, 2026 - Jan 3, 2027");
  assert.equal(rangeLabel("2026-10-19", "2026-10-19"), "Oct 19, 2026");
  const ms = Date.UTC(2026, 9, 19, 13, 30);
  assert.equal(formatClock(ms, NY), "9:30 AM");
  assert.equal(formatWhen(ms, NY), "Mon, Oct 19, 9:30 AM");
  assert.equal(zoneNote(NY, Date.UTC(2026, 6, 1)), "America/New_York (GMT-4)");
  assert.equal(zoneNote("Not/AZone", 0), "Not/AZone", "an unknown zone is shown as it is, never thrown");
});

test("calendar time: the zone list puts UTC and extra zones first, drops unknown names and repeats none", () => {
  const zones = zoneList(["Asia/Calcutta", "Not/AZone"]);
  assert.ok(zones.includes("UTC") && zones.includes("Asia/Calcutta") && zones.includes(NY));
  assert.ok(!zones.includes("Not/AZone"));
  assert.equal(new Set(zones).size, zones.length);
  assert.ok(zones.indexOf("UTC") <= 1);
  const original = Intl.supportedValuesOf;
  try {
    Intl.supportedValuesOf = () => {
      throw new RangeError("no");
    };
    const short = zoneList();
    assert.ok(short.includes("Europe/Paris") && short.includes("Pacific/Auckland"));
  } finally {
    Intl.supportedValuesOf = original;
  }
});
