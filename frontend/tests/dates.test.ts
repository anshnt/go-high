import assert from "node:assert/strict";
import { test } from "node:test";
import { bucketOf, dueDate, dueIso, dueLabel, fromInputDate, parseDue, toInputDate } from "../src/lib/dates.ts";

// Local times throughout, so the tests mean the same in any time zone.
const SUNDAY = new Date(2026, 9, 18, 10, 0); // Sun 18 Oct 2026, 10:00
const WEDNESDAY = new Date(2026, 9, 21, 10, 0);
const MONDAY = new Date(2026, 9, 19, 10, 0);
const day = (d: Date | null) => (d ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}` : null);
const clock = (d: Date | null) => (d ? `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}` : null);

test("a phrase at the end becomes the due date and leaves the title", () => {
  const p = parseDue("Call Ada tomorrow", SUNDAY);
  assert.equal(p.title, "Call Ada");
  assert.equal(day(p.due), "2026-10-19");
  assert.equal(p.allDay, true);
  assert.equal(p.phrase, "tomorrow");
  assert.equal(day(parseDue("Call Ada today", SUNDAY).due), "2026-10-18");
  assert.equal(day(parseDue("Call Ada tmrw", SUNDAY).due), "2026-10-19");
  assert.equal(parseDue("Call Ada TOMORROW", SUNDAY).title, "Call Ada");
});

test("text without a phrase is only a title", () => {
  for (const text of ["Call Ada", "Buy 3 tomatoes", "Order monitor", "Plan month end", "Holiday", "feb 30", "", "Call Ada at 25:00"]) {
    const p = parseDue(text, SUNDAY);
    assert.deepEqual([p.title, p.due, p.allDay, p.phrase], [text.trim(), null, true, null], text);
  }
});

test("a phrase with nothing else stays a title", () => {
  for (const text of ["tomorrow", "next mon", "in 3 days", "at 3pm", "oct 25"]) {
    const p = parseDue(text, SUNDAY);
    assert.deepEqual([p.title, p.due], [text, null], text);
  }
});

test("a weekday is the next one after today, and next means the following week", () => {
  assert.equal(day(parseDue("Send report mon", WEDNESDAY).due), "2026-10-26");
  assert.equal(day(parseDue("Send report fri", WEDNESDAY).due), "2026-10-23");
  assert.equal(day(parseDue("Send report monday", MONDAY).due), "2026-10-26"); // not today
  assert.equal(day(parseDue("Send report next mon", WEDNESDAY).due), "2026-10-26");
  assert.equal(day(parseDue("Send report next fri", WEDNESDAY).due), "2026-10-30");
  assert.equal(day(parseDue("Send report next mon", SUNDAY).due), "2026-10-19");
  assert.equal(day(parseDue("Send report Next Sun", WEDNESDAY).due), "2026-11-01");
  assert.equal(parseDue("Send report next mon", WEDNESDAY).title, "Send report");
  assert.equal(day(parseDue("Send report tues", WEDNESDAY).due), "2026-10-27");
});

test("next week is the coming Monday and next month the 1st", () => {
  assert.equal(day(parseDue("Review next week", WEDNESDAY).due), "2026-10-26");
  assert.equal(day(parseDue("Review next week", SUNDAY).due), "2026-10-19");
  assert.equal(day(parseDue("Review next month", WEDNESDAY).due), "2026-11-01");
});

test("in n minutes, hours, days or weeks", () => {
  const days = parseDue("Follow up in 3 days", WEDNESDAY);
  assert.equal(days.title, "Follow up");
  assert.equal(day(days.due), "2026-10-24");
  assert.equal(days.allDay, true);
  assert.equal(day(parseDue("Follow up in 2 weeks", SUNDAY).due), "2026-11-01");
  const hours = parseDue("Check the oven in 2 hours", SUNDAY);
  assert.equal(clock(hours.due), "12:00");
  assert.equal(hours.allDay, false);
  assert.equal(clock(parseDue("Check the oven in 90 min", SUNDAY).due), "11:30");
  assert.equal(day(parseDue("Check in 1 day", SUNDAY).due), "2026-10-19");
});

test("a month and day, this year or the next when it has passed, and ISO dates", () => {
  assert.equal(day(parseDue("Pay rent oct 25", SUNDAY).due), "2026-10-25");
  assert.equal(day(parseDue("Pay rent 25 oct", SUNDAY).due), "2026-10-25");
  assert.equal(day(parseDue("Pay rent October 25th", SUNDAY).due), "2026-10-25");
  assert.equal(day(parseDue("File taxes jan 5", SUNDAY).due), "2027-01-05");
  assert.equal(day(parseDue("Hello oct 18", SUNDAY).due), "2026-10-18"); // today counts
  assert.equal(day(parseDue("Renew 2027-03-09", SUNDAY).due), "2027-03-09");
  assert.equal(day(parseDue("Renew sept 3", SUNDAY).due), "2027-09-03");
  assert.equal(parseDue("Pay rent oct 25", SUNDAY).title, "Pay rent");
});

test("filler words before the phrase go with it", () => {
  for (const text of ["File taxes by oct 25", "File taxes due oct 25", "File taxes on oct 25", "File taxes for oct 25"]) {
    const p = parseDue(text, SUNDAY);
    assert.equal(p.title, "File taxes", text);
    assert.equal(day(p.due), "2026-10-25");
  }
});

test("a time makes the task timed", () => {
  const p = parseDue("Call Ada tomorrow at 3pm", SUNDAY);
  assert.deepEqual([p.title, day(p.due), clock(p.due), p.allDay, p.phrase], ["Call Ada", "2026-10-19", "15:00", false, "tomorrow at 3pm"]);
  assert.equal(clock(parseDue("Call Ada tomorrow 9:30", SUNDAY).due), "09:30");
  assert.equal(clock(parseDue("Call Ada tomorrow at 9:30am", SUNDAY).due), "09:30");
  assert.equal(clock(parseDue("Call Ada tomorrow 12am", SUNDAY).due), "00:00");
  assert.equal(clock(parseDue("Call Ada tomorrow 12pm", SUNDAY).due), "12:00");
  assert.equal(clock(parseDue("Lunch tomorrow at noon", SUNDAY).due), "12:00");
  assert.equal(clock(parseDue("Call Ada next mon at 17:45", WEDNESDAY).due), "17:45");
  assert.equal(day(parseDue("Call Ada next mon at 17:45", WEDNESDAY).due), "2026-10-26");
  assert.equal(parseDue("Call Ada tomorrow at 13pm", SUNDAY).due, null);
});

test("a time alone means the next time it is that time", () => {
  const morning = parseDue("Call Ada at 3pm", SUNDAY);
  assert.deepEqual([morning.title, day(morning.due), clock(morning.due)], ["Call Ada", "2026-10-18", "15:00"]);
  const late = parseDue("Call Ada at 3pm", new Date(2026, 9, 18, 16, 0));
  assert.equal(day(late.due), "2026-10-19");
  assert.equal(day(parseDue("Call Ada 9:15", SUNDAY).due), "2026-10-19"); // 09:15 has passed at 10:00
});

test("a due date is sent as midnight UTC when it is all day and as an instant when it is timed", () => {
  assert.equal(dueIso(new Date(2026, 9, 19), true), "2026-10-19T00:00:00.000Z");
  assert.equal(dueIso(new Date(2026, 9, 19, 15, 30), false), new Date(2026, 9, 19, 15, 30).toISOString());
  const back = dueDate({ due_at: "2026-10-19T00:00:00Z", all_day: true });
  assert.equal(day(back), "2026-10-19"); // the same date whatever the zone
  assert.equal(dueDate({ due_at: null, all_day: false }), null);
  const timed = new Date(2026, 9, 19, 15, 30);
  assert.equal(dueDate({ due_at: timed.toISOString(), all_day: false })!.getTime(), timed.getTime());
});

test("buckets: overdue, today, upcoming and none", () => {
  const timed = (d: Date) => ({ due_at: d.toISOString(), all_day: false });
  const allDay = (y: number, m: number, d: number) => ({ due_at: new Date(Date.UTC(y, m, d)).toISOString(), all_day: true });
  assert.equal(bucketOf({ due_at: null, all_day: false }, SUNDAY), "none");
  assert.equal(bucketOf(allDay(2026, 9, 17), SUNDAY), "overdue");
  assert.equal(bucketOf(allDay(2026, 9, 18), SUNDAY), "today"); // an all-day task is not late until the day is over
  assert.equal(bucketOf(allDay(2026, 9, 19), SUNDAY), "upcoming");
  assert.equal(bucketOf(timed(new Date(2026, 9, 18, 9, 0)), SUNDAY), "overdue"); // an hour ago
  assert.equal(bucketOf(timed(new Date(2026, 9, 18, 18, 0)), SUNDAY), "today");
  assert.equal(bucketOf(timed(new Date(2026, 9, 19, 9, 0)), SUNDAY), "upcoming");
  assert.equal(bucketOf({ ...timed(new Date(2026, 9, 18, 9, 0)), status: "done" }, SUNDAY), "today"); // finished is never overdue
});

test("labels", () => {
  const allDay = (y: number, m: number, d: number) => ({ due_at: new Date(Date.UTC(y, m, d)).toISOString(), all_day: true });
  assert.equal(dueLabel({ due_at: null, all_day: false }, SUNDAY), "No date");
  assert.equal(dueLabel(allDay(2026, 9, 18), SUNDAY), "Today");
  assert.equal(dueLabel(allDay(2026, 9, 19), SUNDAY), "Tomorrow");
  assert.equal(dueLabel(allDay(2026, 9, 17), SUNDAY), "Yesterday");
  assert.equal(dueLabel(allDay(2026, 9, 22), SUNDAY), "Thursday");
  assert.equal(dueLabel(allDay(2026, 10, 2), SUNDAY), "Mon, Nov 2");
  assert.equal(dueLabel(allDay(2027, 10, 2), SUNDAY), "Nov 2, 2027");
  const at = (h: number, m: number, d = 18) => ({ due_at: new Date(2026, 9, d, h, m).toISOString(), all_day: false });
  assert.equal(dueLabel(at(15, 30), SUNDAY), "Today, 3:30 PM");
  assert.equal(dueLabel(at(0, 5, 19), SUNDAY), "Tomorrow, 12:05 AM");
  assert.equal(dueLabel(at(12, 0), SUNDAY), "Today, 12:00 PM");
});

test("input dates round trip", () => {
  assert.equal(toInputDate(new Date(2026, 0, 5)), "2026-01-05");
  assert.equal(day(fromInputDate("2026-01-05")), "2026-01-05");
  assert.equal(fromInputDate("garbage"), null);
  assert.equal(fromInputDate(""), null);
});
