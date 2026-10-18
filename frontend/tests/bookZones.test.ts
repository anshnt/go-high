import assert from "node:assert/strict";
import { test } from "node:test";
import {
  FALLBACK_ZONES,
  clockLabel,
  dayKey,
  detectZone,
  formatDate,
  formatDay,
  formatTime,
  isToday,
  isZone,
  listZones,
  monthLabel,
  offsetLabel,
  splitZone,
  todayKey,
  weekdayLabels,
} from "../src/book/zones.ts";

test("zones: names are checked, listed with UTC and any extra, and detection never throws", () => {
  assert.ok(isZone("Europe/London") && isZone("UTC") && isZone("Pacific/Auckland"));
  assert.ok(!isZone("Mars/Olympus") && !isZone(""));
  const zones = listZones(["Asia/Calcutta", "Not/AZone"]);
  assert.ok(zones.includes("UTC") && zones.includes("America/New_York") && zones.includes("Asia/Calcutta"));
  assert.ok(!zones.includes("Not/AZone"));
  assert.deepEqual(zones, [...zones].sort());
  assert.equal(new Set(zones).size, zones.length);
  assert.ok(isZone(detectZone()));
  assert.ok(FALLBACK_ZONES.every(isZone), "every fallback name is a real zone");
});

test("zones: the listing falls back to a short list when the browser cannot list zones", () => {
  const original = Intl.supportedValuesOf;
  try {
    Intl.supportedValuesOf = () => {
      throw new RangeError("no");
    };
    const zones = listZones();
    assert.ok(zones.includes("Europe/Paris") && zones.includes("UTC"));
    assert.ok(zones.length < 100);
    Intl.supportedValuesOf = (() => []) as typeof Intl.supportedValuesOf;
    assert.ok(listZones().includes("Asia/Tokyo"));
  } finally {
    Intl.supportedValuesOf = original;
  }
});

test("zones: splitZone gives a region and a readable city", () => {
  assert.deepEqual(splitZone("America/New_York"), { region: "America", city: "New York" });
  assert.deepEqual(splitZone("America/Argentina/Buenos_Aires"), { region: "America", city: "Argentina/Buenos Aires" });
  assert.deepEqual(splitZone("UTC"), { region: "", city: "UTC" });
});

test("a time shows on the clock of the zone it is asked in, 12 or 24 hour by locale", () => {
  const t = "2026-11-03T14:00:00+00:00";
  assert.equal(formatTime(t, "UTC", "en-GB"), "14:00");
  assert.match(formatTime(t, "UTC", "en-US"), /^2:00\sPM$/);
  assert.equal(formatTime(t, "Asia/Tokyo", "en-GB"), "23:00");
  assert.equal(formatTime(t, "America/New_York", "en-GB"), "09:00");
  assert.equal(formatTime(new Date(t), "Europe/London", "en-GB"), "14:00");
});

test("a visitor in Tokyo or Auckland sees the same instant on the next day", () => {
  const late = "2026-11-03T20:30:00Z";
  assert.equal(dayKey(late, "UTC"), "2026-11-03");
  assert.equal(dayKey(late, "America/Los_Angeles"), "2026-11-03");
  assert.equal(dayKey(late, "Asia/Tokyo"), "2026-11-04");
  assert.equal(dayKey(late, "Pacific/Auckland"), "2026-11-04");
  assert.equal(formatDate(late, "Asia/Tokyo", "en-US"), "Wednesday, November 4, 2026");
  assert.equal(formatDate(late, "UTC", "en-US"), "Tuesday, November 3, 2026");
  const early = "2026-11-03T03:00:00Z"; // still the evening before in Los Angeles
  assert.equal(dayKey(early, "America/Los_Angeles"), "2026-11-02");
  assert.equal(dayKey(early, "Pacific/Kiritimati"), "2026-11-03");
});

test("dayKey and times across the United States daylight saving changes", () => {
  // 2026-03-08: clocks jump 02:00 -> 03:00 in New York (EST -5 -> EDT -4)
  assert.equal(formatTime("2026-03-08T06:30:00Z", "America/New_York", "en-GB"), "01:30");
  assert.equal(formatTime("2026-03-08T07:30:00Z", "America/New_York", "en-GB"), "03:30");
  assert.equal(dayKey("2026-03-08T04:59:59Z", "America/New_York"), "2026-03-07");
  assert.equal(dayKey("2026-03-08T05:00:00Z", "America/New_York"), "2026-03-08");
  assert.equal(dayKey("2026-03-09T03:59:59Z", "America/New_York"), "2026-03-08"); // a 23 hour day
  assert.equal(dayKey("2026-03-09T04:00:00Z", "America/New_York"), "2026-03-09");
  // 2026-11-01: clocks fall back 02:00 -> 01:00 (EDT -4 -> EST -5), a 25 hour day
  assert.equal(formatTime("2026-11-01T05:30:00Z", "America/New_York", "en-GB"), "01:30");
  assert.equal(formatTime("2026-11-01T06:30:00Z", "America/New_York", "en-GB"), "01:30");
  assert.equal(dayKey("2026-11-01T04:00:00Z", "America/New_York"), "2026-11-01");
  assert.equal(dayKey("2026-11-02T04:59:59Z", "America/New_York"), "2026-11-01");
  assert.equal(dayKey("2026-11-02T05:00:00Z", "America/New_York"), "2026-11-02");
});

test("dayKey and times across the United Kingdom daylight saving changes", () => {
  // 2026-03-29: 01:00 UTC is when London goes from GMT to BST
  assert.equal(formatTime("2026-03-29T00:59:00Z", "Europe/London", "en-GB"), "00:59");
  assert.equal(formatTime("2026-03-29T01:00:00Z", "Europe/London", "en-GB"), "02:00");
  assert.equal(dayKey("2026-03-28T23:59:59Z", "Europe/London"), "2026-03-28");
  assert.equal(dayKey("2026-03-29T23:00:00Z", "Europe/London"), "2026-03-30"); // BST: midnight is 23:00Z
  // 2026-10-25: back to GMT at 01:00 UTC, a 25 hour day
  assert.equal(formatTime("2026-10-25T00:30:00Z", "Europe/London", "en-GB"), "01:30");
  assert.equal(formatTime("2026-10-25T01:30:00Z", "Europe/London", "en-GB"), "01:30");
  assert.equal(dayKey("2026-10-24T23:00:00Z", "Europe/London"), "2026-10-25");
  assert.equal(dayKey("2026-10-25T23:59:59Z", "Europe/London"), "2026-10-25");
  assert.equal(dayKey("2026-10-26T00:00:00Z", "Europe/London"), "2026-10-26");
});

test("the short offset follows daylight saving and uses GMT for zero", () => {
  assert.equal(offsetLabel("Europe/London", new Date("2026-01-15T12:00:00Z"), "en"), "GMT");
  assert.equal(offsetLabel("Europe/London", new Date("2026-07-15T12:00:00Z"), "en"), "GMT+1");
  assert.equal(offsetLabel("America/New_York", new Date("2026-01-15T12:00:00Z"), "en"), "GMT-5");
  assert.equal(offsetLabel("America/New_York", new Date("2026-07-15T12:00:00Z"), "en"), "GMT-4");
  assert.equal(offsetLabel("Asia/Tokyo", new Date("2026-07-15T12:00:00Z"), "en"), "GMT+9");
  assert.equal(offsetLabel("Asia/Kolkata", new Date("2026-07-15T12:00:00Z"), "en"), "GMT+5:30");
  assert.equal(offsetLabel("UTC", new Date("2026-07-15T12:00:00Z"), "en"), "GMT");
  assert.equal(offsetLabel("Pacific/Auckland", new Date("2026-01-15T12:00:00Z"), "en"), "GMT+13");
  assert.equal(offsetLabel("Pacific/Auckland", new Date("2026-07-15T12:00:00Z"), "en"), "GMT+12");
});

test("today is the day it is where the visitor is", () => {
  const now = new Date("2026-11-03T20:30:00Z");
  assert.equal(todayKey("UTC", now), "2026-11-03");
  assert.equal(todayKey("Pacific/Auckland", now), "2026-11-04");
  assert.ok(isToday("2026-11-04", "Pacific/Auckland", now));
  assert.ok(!isToday("2026-11-03", "Pacific/Auckland", now));
  assert.ok(isToday("2026-11-03", "America/Los_Angeles", now));
});

test("labels for a month, a day, the weekday row and the clock over there", () => {
  assert.equal(monthLabel(2026, 11, "en-GB"), "November 2026");
  assert.equal(monthLabel(2028, 2, "en-US"), "February 2028");
  assert.equal(formatDay("2026-11-03", "en-GB"), "Tuesday 3 November");
  assert.deepEqual(weekdayLabels("short", "en-GB"), ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
  assert.equal(clockLabel("Asia/Tokyo", new Date("2026-11-03T14:05:00Z"), "en-GB"), "Tue 23:05");
  assert.equal(clockLabel("Pacific/Auckland", new Date("2026-11-03T14:05:00Z"), "en-GB"), "Wed 03:05");
});
