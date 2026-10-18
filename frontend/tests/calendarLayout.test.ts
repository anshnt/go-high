import assert from "node:assert/strict";
import { test } from "node:test";
import { usualWeek } from "../src/calendar/hours.ts";
import { MIN_BLOCK, firstWorkMinute, layoutDay, layoutWeek, offWindows, workWindows, type Span } from "../src/calendar/layout.ts";
import { zonedToUtc } from "../src/calendar/time.ts";

const NY = "America/New_York";
const DAY = "2026-10-19";
const at = (time: string, day = DAY) => zonedToUtc(day, time, NY);
const span = (item: string, from: string, to: string, day = DAY): Span<string> => ({ item, start: at(from, day), end: at(to, day) });

test("layout: overlapping events share the width and the rest take all of it", () => {
  const placed = layoutDay([span("a", "09:00", "10:00"), span("b", "09:30", "11:00"), span("c", "10:00", "10:30"), span("d", "11:00", "12:00")], DAY, NY);
  const by = Object.fromEntries(placed.map((p) => [p.item, p]));
  assert.deepEqual(by.a, { item: "a", top: 540, height: 60, col: 0, cols: 2 });
  assert.deepEqual(by.b, { item: "b", top: 570, height: 90, col: 1, cols: 2 });
  assert.deepEqual(by.c, { item: "c", top: 600, height: 30, col: 0, cols: 2 }, "c reuses the column a has left");
  assert.deepEqual(by.d, { item: "d", top: 660, height: 60, col: 0, cols: 1 }, "d starts as b ends: a cluster of its own");
});

test("layout: short events are drawn at a readable height, events at the same time keep their input order", () => {
  const placed = layoutDay([span("short", "09:00", "09:05"), span("twin", "09:00", "09:05")], DAY, NY);
  assert.deepEqual(placed.map((p) => [p.item, p.height, p.col, p.cols]), [["short", MIN_BLOCK, 0, 2], ["twin", MIN_BLOCK, 1, 2]]);
  const late = layoutDay([span("late", "23:55", "24:00")], DAY, NY)[0]!;
  assert.equal(late.top + late.height, 1440, "a block never runs past the end of the day");
});

test("layout: an event over midnight shows on both days, clipped to each", () => {
  const overnight: Span<string> = { item: "night", start: at("23:00"), end: at("02:00", "2026-10-20") };
  const week = layoutWeek([overnight, span("other", "09:00", "10:00", "2026-10-21")], ["2026-10-19", "2026-10-20", "2026-10-21"], NY);
  assert.deepEqual(week.get("2026-10-19"), [{ item: "night", top: 1380, height: 60, col: 0, cols: 1 }]);
  assert.deepEqual(week.get("2026-10-20"), [{ item: "night", top: 0, height: 120, col: 0, cols: 1 }]);
  assert.deepEqual(week.get("2026-10-21")!.map((p) => p.item), ["other"]);
  assert.deepEqual(layoutDay([overnight], "2026-10-22", NY), []);
});

test("layout: working hours are read in the worker's zone and shown on the viewer's clock", () => {
  const london = { time_zone: "Europe/London", weekly: usualWeek(), overrides: {} };
  assert.deepEqual(workWindows(london, DAY, NY), [[240, 720]], "09:00 to 17:00 in London is 04:00 to 12:00 in New York");
  // Tokyo's Monday starts on Sunday evening in New York, and its Tuesday on Monday evening
  const tokyo = { time_zone: "Asia/Tokyo", weekly: usualWeek(), overrides: {} };
  assert.deepEqual(workWindows(tokyo, DAY, NY), [[0, 240], [1200, 1440]]);
  assert.deepEqual(workWindows(tokyo, "2026-10-16", NY), [[0, 240]], "Tokyo's Friday is over by 04:00 on Friday in New York");
  assert.deepEqual(workWindows(tokyo, "2026-10-17", NY), [], "and nothing is left for Saturday");
  assert.deepEqual(workWindows(tokyo, "2026-10-18", NY), [[1200, 1440]], "Tokyo's Monday starts on Sunday evening");
});

test("layout: an override replaces the usual day, touching windows merge and broken ranges are skipped", () => {
  const hours = { time_zone: NY, weekly: usualWeek(), overrides: { [DAY]: [["08:00", "10:00"], ["10:00", "12:00"], ["oops", "13:00"]] as [string, string][] } };
  assert.deepEqual(workWindows(hours, DAY, NY), [[480, 720]]);
  assert.deepEqual(workWindows({ ...hours, overrides: { [DAY]: [] } }, DAY, NY), [], "an empty override is a day off");
  assert.deepEqual(workWindows({ ...hours, overrides: { "2026-03-08": [["00:00", "24:00"]] } }, "2026-03-08", NY), [[0, 1440]]);
});

test("layout: the gaps between windows, and where the grid scrolls to", () => {
  assert.deepEqual(offWindows([]), [[0, 1440]]);
  assert.deepEqual(offWindows([[60, 120], [100, 200], [1400, 1440]]), [[0, 60], [200, 1400]]);
  assert.deepEqual(offWindows([[0, 1440]]), []);
  const london = { time_zone: "Europe/London", weekly: usualWeek(), overrides: {} };
  assert.equal(firstWorkMinute(london, ["2026-10-19", "2026-10-20"], NY), 240);
  assert.equal(firstWorkMinute(null, [DAY], NY), 480);
  assert.equal(firstWorkMinute(london, ["2026-10-24", "2026-10-25"], NY), 480, "a weekend with no hours scrolls to 08:00");
});
