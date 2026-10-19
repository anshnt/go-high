import assert from "node:assert/strict";
import { test } from "node:test";
import { dayKey, dayLabel, fromLocalInput, groupByDay, listTime, snoozePresets, toLocalInput, whenLabel } from "../src/inbox/time.ts";

// Local times throughout, so the tests mean the same in any time zone.
const NOW = new Date(2026, 9, 21, 15, 30); // Wed 21 Oct 2026, 15:30
const at = (y: number, mo: number, d: number, h = 12, mi = 0) => new Date(y, mo - 1, d, h, mi);
const msg = (id: string, d: Date) => ({ id, occurred_at: d.toISOString() });

test("a day is named Today, Yesterday, then by weekday and date, with the year only when it is another year", () => {
  assert.equal(dayLabel(at(2026, 10, 21, 1), NOW), "Today");
  assert.equal(dayLabel(at(2026, 10, 20, 23), NOW), "Yesterday");
  assert.equal(dayLabel(at(2026, 10, 12), NOW), "Mon, Oct 12");
  assert.equal(dayLabel(at(2025, 12, 31), NOW), "Dec 31, 2025");
  assert.equal(dayKey(at(2026, 1, 5)), "2026-01-05");
});

test("messages are grouped by the day they happened, in the order given, with the day in the reader's own zone", () => {
  const groups = groupByDay(
    [msg("a", at(2026, 10, 19, 9)), msg("b", at(2026, 10, 19, 23, 59)), msg("c", at(2026, 10, 20, 0, 1)), msg("d", at(2026, 10, 21, 8))],
    NOW,
  );
  assert.deepEqual(groups.map((g) => [g.label, g.items.map((m) => m.id)]), [
    ["Mon, Oct 19", ["a", "b"]],
    ["Yesterday", ["c"]],
    ["Today", ["d"]],
  ]);
  assert.deepEqual(groupByDay([], NOW), []);
});

test("a provider clock that runs behind never prints a day twice or goes back a day", () => {
  const groups = groupByDay([msg("a", at(2026, 10, 20, 10)), msg("b", at(2026, 10, 19, 23)), msg("c", at(2026, 10, 20, 11))], NOW);
  assert.equal(groups.length, 1);
  assert.deepEqual(groups[0]!.items.map((m) => m.id), ["a", "b", "c"]);
  assert.equal(groups[0]!.label, "Yesterday");
  // a time that cannot be read joins the day before it instead of breaking the list
  const odd = groupByDay([msg("a", at(2026, 10, 20)), { id: "b", occurred_at: "not a date" }], NOW);
  assert.equal(odd.length, 1);
});

test("a list row shows the clock today, then Yesterday, the weekday this week, and a date after that", () => {
  assert.equal(listTime(at(2026, 10, 21, 9, 5).toISOString(), NOW), "9:05 AM");
  assert.equal(listTime(at(2026, 10, 20, 23).toISOString(), NOW), "Yesterday");
  assert.equal(listTime(at(2026, 10, 17).toISOString(), NOW), "Sat");
  assert.equal(listTime(at(2026, 10, 14).toISOString(), NOW), "Oct 14");
  assert.equal(listTime(at(2025, 3, 2).toISOString(), NOW), "Mar 2, 2025");
  assert.equal(listTime("nope", NOW), "");
});

test("snooze presets: an hour from now, tomorrow at 9, and the next Monday at 9 (never today)", () => {
  const [hour, tomorrow, week] = snoozePresets(NOW);
  assert.equal(hour!.at.getTime(), NOW.getTime() + 3_600_000);
  assert.equal(toLocalInput(tomorrow!.at), "2026-10-22T09:00");
  assert.equal(toLocalInput(week!.at), "2026-10-26T09:00");
  // on a Monday, "next week" is the Monday after, and on a Sunday it is the next day
  assert.equal(toLocalInput(snoozePresets(at(2026, 10, 19, 8))[2]!.at), "2026-10-26T09:00");
  assert.equal(toLocalInput(snoozePresets(at(2026, 10, 18, 8))[2]!.at), "2026-10-19T09:00");
  assert.equal(toLocalInput(snoozePresets(at(2026, 10, 24, 8))[2]!.at), "2026-10-26T09:00");
  // across a month end
  assert.equal(toLocalInput(snoozePresets(at(2026, 10, 31, 20))[1]!.at), "2026-11-01T09:00");
});

test("the custom time round-trips through a datetime-local value", () => {
  const d = at(2026, 11, 3, 7, 45);
  assert.equal(toLocalInput(d), "2026-11-03T07:45");
  assert.equal(fromLocalInput("2026-11-03T07:45")!.getTime(), d.getTime());
  assert.equal(fromLocalInput(""), null);
  assert.equal(fromLocalInput("2026-11-03"), null);
  assert.equal(whenLabel(at(2026, 10, 22, 9), NOW), "Thu, Oct 22, 9:00 AM");
  assert.equal(whenLabel(at(2026, 10, 21, 18), NOW), "Today, 6:00 PM");
});
