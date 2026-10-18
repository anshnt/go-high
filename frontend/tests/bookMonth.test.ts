import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addDays,
  daysIn,
  groupByDay,
  keyOf,
  monthGrid,
  monthRange,
  monthsBetween,
  normaliseDays,
  sameMonth,
  stepMonth,
  weekday,
  ymOfKey,
} from "../src/book/month.ts";

test("months have 28 to 31 days, leap years included", () => {
  assert.equal(daysIn({ year: 2026, month: 1 }), 31);
  assert.equal(daysIn({ year: 2026, month: 4 }), 30);
  assert.equal(daysIn({ year: 2026, month: 2 }), 28);
  assert.equal(daysIn({ year: 2028, month: 2 }), 29);
  assert.equal(daysIn({ year: 1900, month: 2 }), 28);
  assert.equal(daysIn({ year: 2000, month: 2 }), 29);
  assert.equal(daysIn({ year: 2026, month: 12 }), 31);
});

test("the range of a month is its first and last day, as the slots call wants it", () => {
  assert.deepEqual(monthRange({ year: 2026, month: 11 }), { from: "2026-11-01", to: "2026-11-30" });
  assert.deepEqual(monthRange({ year: 2026, month: 12 }), { from: "2026-12-01", to: "2026-12-31" });
  assert.deepEqual(monthRange({ year: 2028, month: 2 }), { from: "2028-02-01", to: "2028-02-29" });
  assert.deepEqual(monthRange({ year: 2026, month: 2 }), { from: "2026-02-01", to: "2026-02-28" });
  for (const month of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]) {
    const r = monthRange({ year: 2026, month });
    assert.ok((Date.parse(r.to) - Date.parse(r.from)) / 864e5 < 62);
  }
});

test("stepping a month crosses year ends in both directions", () => {
  assert.deepEqual(stepMonth({ year: 2026, month: 12 }, 1), { year: 2027, month: 1 });
  assert.deepEqual(stepMonth({ year: 2026, month: 1 }, -1), { year: 2025, month: 12 });
  assert.deepEqual(stepMonth({ year: 2026, month: 10 }, 0), { year: 2026, month: 10 });
  assert.deepEqual(stepMonth({ year: 2026, month: 3 }, 14), { year: 2027, month: 5 });
  assert.deepEqual(stepMonth({ year: 2026, month: 3 }, -15), { year: 2024, month: 12 });
  assert.equal(monthsBetween({ year: 2026, month: 10 }, { year: 2027, month: 2 }), 4);
  assert.equal(monthsBetween({ year: 2026, month: 10 }, { year: 2026, month: 8 }), -2);
  assert.ok(sameMonth(ymOfKey("2026-11-30"), { year: 2026, month: 11 }));
  assert.equal(keyOf({ year: 2026, month: 3 }, 7), "2026-03-07");
});

test("weekdays count from Monday and days add across month ends", () => {
  assert.equal(weekday("2026-11-02"), 0); // Monday
  assert.equal(weekday("2026-11-01"), 6); // Sunday
  assert.equal(weekday("2026-11-07"), 5);
  assert.equal(addDays("2026-11-30", 1), "2026-12-01");
  assert.equal(addDays("2026-03-01", -1), "2026-02-28");
  assert.equal(addDays("2028-03-01", -1), "2028-02-29");
  assert.equal(addDays("2026-11-03", 7), "2026-11-10");
  assert.equal(addDays("2026-12-31", 1), "2027-01-01");
});

test("the month grid starts on Monday with blanks around the month", () => {
  // November 2026 starts on a Sunday: six blanks, then the 1st at the end of the first row
  const nov = monthGrid({ year: 2026, month: 11 });
  assert.equal(nov.length, 6);
  assert.ok(nov.every((w) => w.length === 7));
  assert.deepEqual(nov[0].map((c) => c?.day ?? null), [null, null, null, null, null, null, 1]);
  assert.deepEqual(nov[5].map((c) => c?.day ?? null), [30, null, null, null, null, null, null]);
  assert.equal(nov[1][0]?.key, "2026-11-02");

  // June 2026 starts on a Monday and ends on a Tuesday
  const jun = monthGrid({ year: 2026, month: 6 });
  assert.equal(jun[0][0]?.day, 1);
  assert.equal(jun.length, 5);
  assert.equal(jun[4][1]?.day, 30);
  assert.equal(jun[4][2], null);

  // February 2027 is exactly four full weeks (starts Monday, 28 days): no blanks at all
  const feb = monthGrid({ year: 2027, month: 2 });
  assert.equal(feb.length, 4);
  assert.ok(feb.flat().every((c) => c !== null));

  // A month that needs six rows: August 2026 starts on a Saturday and has 31 days
  assert.equal(monthGrid({ year: 2026, month: 8 }).length, 6);
});

test("every month of several years has all its days once, in order, in whole weeks", () => {
  for (let year = 2024; year <= 2029; year++) {
    for (let month = 1; month <= 12; month++) {
      const cells = monthGrid({ year, month }).flat();
      assert.equal(cells.length % 7, 0);
      const days = cells.filter((c) => c !== null).map((c) => c!.day);
      assert.deepEqual(days, Array.from({ length: daysIn({ year, month }) }, (_, i) => i + 1));
      cells.forEach((c, i) => {
        if (c) assert.equal(weekday(c.key), i % 7, c.key);
      });
    }
  }
});

test("open times group by day on the visitor's clock, sorted and without repeats", () => {
  const instants = ["2026-11-03T22:00:00+00:00", "2026-11-03T14:00:00+00:00", "2026-11-03T14:00:00+00:00", "2026-11-04T09:00:00+00:00"];
  assert.deepEqual(groupByDay(instants, "UTC"), {
    "2026-11-03": ["2026-11-03T14:00:00+00:00", "2026-11-03T22:00:00+00:00"],
    "2026-11-04": ["2026-11-04T09:00:00+00:00"],
  });
  // in Tokyo the 22:00Z slot is already the next morning, in Auckland too
  assert.deepEqual(Object.keys(groupByDay(instants, "Asia/Tokyo")), ["2026-11-03", "2026-11-04"]);
  assert.deepEqual(groupByDay(instants, "Asia/Tokyo")["2026-11-04"], ["2026-11-03T22:00:00+00:00", "2026-11-04T09:00:00+00:00"]);
  assert.deepEqual(groupByDay(["2026-11-03T14:00:00+00:00"], "Pacific/Auckland"), { "2026-11-04": ["2026-11-03T14:00:00+00:00"] });
  assert.deepEqual(groupByDay([], "UTC"), {});
  assert.deepEqual(groupByDay(["not a time"], "UTC"), {});
});

test("the slots response is regrouped, tolerating a missing or empty days object", () => {
  const sent = { "2026-11-03": ["2026-11-03T22:00:00+00:00", "2026-11-03T14:00:00+00:00"], "2026-11-05": [] };
  assert.deepEqual(normaliseDays(sent, "UTC"), { "2026-11-03": ["2026-11-03T14:00:00+00:00", "2026-11-03T22:00:00+00:00"] });
  assert.deepEqual(normaliseDays(undefined, "UTC"), {});
  assert.deepEqual(normaliseDays({}, "Asia/Tokyo"), {});
  assert.deepEqual(normaliseDays(sent, "Pacific/Auckland"), {
    "2026-11-04": ["2026-11-03T14:00:00+00:00", "2026-11-03T22:00:00+00:00"],
  });
});

test("slots either side of the spring clock change in New York stay on their own days", () => {
  const sent = { "2026-03-07": ["2026-03-08T04:30:00+00:00"], "2026-03-08": ["2026-03-08T05:30:00+00:00", "2026-03-09T03:30:00+00:00"] };
  const grouped = normaliseDays(sent, "America/New_York");
  assert.deepEqual(Object.keys(grouped), ["2026-03-07", "2026-03-08"]);
  assert.equal(grouped["2026-03-08"].length, 2);
});
