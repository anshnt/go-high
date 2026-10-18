import assert from "node:assert/strict";
import { test } from "node:test";
import {
  MAX_RANGES,
  copyToWeekdays,
  describeRanges,
  formatHM,
  nextRange,
  parseWeekly,
  rangeError,
  sameWeek,
  serialize,
  timeOptions,
  toMinutes,
  usualWeek,
  weekErrors,
  type Range,
} from "../src/calendar/hours.ts";

test("hours: times read as minutes, with 24:00 as the end of the day and anything else refused", () => {
  assert.equal(toMinutes("00:00"), 0);
  assert.equal(toMinutes("09:30"), 570);
  assert.equal(toMinutes("24:00"), 1440);
  for (const bad of ["24:15", "12:60", "9:30", "", "ab:cd", "09:30:00"]) assert.equal(toMinutes(bad), null, bad);
  assert.equal(formatHM("00:00"), "12:00 AM");
  assert.equal(formatHM("12:15"), "12:15 PM");
  assert.equal(formatHM("24:00"), "Midnight");
  assert.equal(formatHM("nonsense"), "nonsense");
});

test("hours: the time pickers step by a quarter hour and keep a stored time off the grid", () => {
  const starts = timeOptions("start");
  assert.equal(starts[0], "00:00");
  assert.equal(starts.at(-1), "23:45");
  assert.equal(starts.length, 96);
  const ends = timeOptions("end", "09:10");
  assert.equal(ends[0], "00:15");
  assert.equal(ends.at(-1), "24:00");
  assert.ok(ends.includes("09:10"));
  assert.deepEqual(ends, [...ends].sort());
  assert.ok(!timeOptions("end", "25:00").includes("25:00"), "a broken stored time is not offered");
});

test("hours: a day's ranges are checked for format, order, overlap and count", () => {
  assert.equal(rangeError([]), null);
  assert.equal(rangeError([["09:00", "12:00"], ["12:00", "17:00"]]), null, "touching ranges do not overlap");
  assert.equal(rangeError([["09:00", "9:00"]]), "Use times like 09:00.");
  assert.equal(rangeError([["10:00", "09:00"]]), "10:00 AM to 9:00 AM ends before it starts.");
  assert.equal(rangeError([["09:00", "09:00"]]), "9:00 AM to 9:00 AM ends before it starts.");
  assert.equal(rangeError([["13:00", "17:00"], ["09:00", "13:30"]]), "Two ranges overlap. Merge them or move one.");
  const many: Range[] = Array.from({ length: MAX_RANGES + 1 }, (_, i) => [`0${i}:00`, `0${i}:30`]);
  assert.match(rangeError(many)!, /Up to 6/);
});

test("hours: a new range follows the last one, is cut at midnight, and is refused when the day is full", () => {
  assert.deepEqual(nextRange([]), ["09:00", "10:00"]);
  assert.deepEqual(nextRange([["13:00", "14:00"], ["09:00", "10:00"]]), ["14:00", "15:00"]);
  assert.deepEqual(nextRange([["09:00", "23:30"]]), ["23:30", "24:00"]);
  assert.equal(nextRange([["09:00", "23:50"]]), null, "less than a quarter hour left");
  assert.equal(nextRange([["09:00", "24:00"]]), null);
  const full: Range[] = Array.from({ length: MAX_RANGES }, (_, i) => [`0${i}:00`, `0${i}:30`]);
  assert.equal(nextRange(full), null);
});

test("hours: the week is checked per day, copied to weekdays, and sent in order", () => {
  const week = usualWeek();
  assert.deepEqual(week.mon, [["09:00", "17:00"]]);
  assert.deepEqual(week.sat, []);
  assert.deepEqual(weekErrors(week), {});
  assert.deepEqual(weekErrors({ ...week, wed: [["17:00", "09:00"]] }), { wed: "5:00 PM to 9:00 AM ends before it starts." });

  const custom = { ...week, mon: [["13:00", "17:00"], ["08:00", "12:00"]] as Range[] };
  const copied = copyToWeekdays(custom, "mon");
  assert.deepEqual(copied.fri, custom.mon);
  assert.deepEqual(copied.sat, [], "the weekend is left alone");
  assert.notEqual(copied.fri, custom.mon, "each day gets its own copy");
  copied.fri[0]![0] = "07:00";
  assert.equal(custom.mon[0]![0], "13:00");

  assert.deepEqual(serialize(custom).mon, [["08:00", "12:00"], ["13:00", "17:00"]]);
  assert.ok(sameWeek(custom, { ...custom, mon: [["08:00", "12:00"], ["13:00", "17:00"]] }), "order does not make a change");
  assert.ok(!sameWeek(custom, week));
  assert.equal(describeRanges(custom.mon), "8:00 AM to 12:00 PM, 1:00 PM to 5:00 PM");
  assert.equal(describeRanges([["18:00", "24:00"]]), "6:00 PM to Midnight");
  assert.equal(describeRanges([]), "Unavailable");
});

test("hours: whatever the API sends is made safe to edit", () => {
  const parsed = parseWeekly({ mon: [["09:00", "17:00"], ["x"], [1, 2], "09:00"], funday: [["09:00", "10:00"]], tue: "nope" });
  assert.deepEqual(parsed.mon, [["09:00", "17:00"]]);
  assert.deepEqual(parsed.tue, []);
  assert.deepEqual(Object.keys(parsed), ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]);
  assert.deepEqual(parseWeekly(null).sun, []);
  assert.deepEqual(parseWeekly("weekly").mon, []);
});
