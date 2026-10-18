import assert from "node:assert/strict";
import { test } from "node:test";
import { ordinal, parseRule, presetOf, ruleFor, ruleText, summarize } from "../src/lib/recurrence.ts";

test("rules are summarized in plain language", () => {
  assert.equal(summarize(null), "Does not repeat");
  assert.equal(summarize("FREQ=DAILY"), "Every day");
  assert.equal(summarize("FREQ=DAILY;INTERVAL=3"), "Every 3 days");
  assert.equal(summarize("FREQ=WEEKLY"), "Every week");
  assert.equal(summarize("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"), "Every weekday");
  assert.equal(summarize("FREQ=WEEKLY;BYDAY=SA,SU"), "Every weekend");
  assert.equal(summarize("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"), "Every 2 weeks on Mon");
  assert.equal(summarize("FREQ=WEEKLY;BYDAY=WE,MO"), "Every week on Mon, Wed");
  assert.equal(summarize("FREQ=MONTHLY"), "Monthly");
  assert.equal(summarize("FREQ=MONTHLY;BYMONTHDAY=1"), "Monthly on the 1st");
  assert.equal(summarize("FREQ=MONTHLY;BYMONTHDAY=22"), "Monthly on the 22nd");
  assert.equal(summarize("FREQ=MONTHLY;BYMONTHDAY=-1"), "Monthly on the last day");
  assert.equal(summarize("FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=15"), "Every 3 months on the 15th");
});

test("an end is part of the summary", () => {
  assert.equal(summarize("FREQ=DAILY;COUNT=5"), "Every day, 5 times");
  assert.equal(summarize("FREQ=WEEKLY;BYDAY=MO;UNTIL=20261231"), "Every week on Mon, until Dec 31, 2026");
  assert.equal(summarize("FREQ=DAILY;UNTIL=20261231T120000Z"), "Every day, until Dec 31, 2026");
});

test("text this page does not understand is still called a repeat", () => {
  assert.equal(summarize("FREQ=YEARLY"), "Repeats");
  assert.equal(summarize("nonsense"), "Repeats");
  assert.equal(parseRule("FREQ=WEEKLY;BYDAY=XX"), null);
  assert.equal(parseRule(""), null);
  assert.equal(parseRule(null), null);
});

test("ordinals", () => {
  const spelled = [1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 30, 31].map(ordinal);
  assert.deepEqual(spelled, ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "30th", "31st"]);
});

test("a rule survives being parsed and written again", () => {
  for (const text of ["FREQ=DAILY", "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE", "FREQ=MONTHLY;BYMONTHDAY=-1;COUNT=4", "FREQ=DAILY;UNTIL=20261231"]) {
    assert.equal(ruleText(parseRule(text)!), text);
  }
  assert.equal(ruleText(parseRule("rrule:freq=weekly;byday=we,mo")!), "FREQ=WEEKLY;BYDAY=MO,WE");
  assert.equal(ruleText(parseRule("FREQ=WEEKLY;BYDAY=MO,MO")!), "FREQ=WEEKLY;BYDAY=MO");
});

test("each preset means a rule for the due date", () => {
  const wednesday = new Date(2026, 9, 21);
  assert.equal(ruleFor("none", wednesday), null);
  assert.equal(ruleFor("daily", wednesday), "FREQ=DAILY");
  assert.equal(ruleFor("weekdays", wednesday), "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR");
  assert.equal(ruleFor("weekly", wednesday), "FREQ=WEEKLY;BYDAY=WE");
  assert.equal(ruleFor("weekly", new Date(2026, 9, 25)), "FREQ=WEEKLY;BYDAY=SU");
  assert.equal(ruleFor("biweekly", wednesday), "FREQ=WEEKLY;INTERVAL=2;BYDAY=WE");
  assert.equal(ruleFor("monthly", wednesday), "FREQ=MONTHLY;BYMONTHDAY=21");
  assert.equal(summarize(ruleFor("monthly", new Date(2026, 10, 1))), "Monthly on the 1st");
  assert.equal(summarize(ruleFor("biweekly", new Date(2026, 9, 19))), "Every 2 weeks on Mon");
});

test("a stored rule is shown as the preset that says the same", () => {
  const wednesday = new Date(2026, 9, 21);
  for (const preset of ["none", "daily", "weekdays", "weekly", "biweekly", "monthly"] as const) {
    assert.equal(presetOf(ruleFor(preset, wednesday), wednesday), preset);
  }
  assert.equal(presetOf("FREQ=WEEKLY", wednesday), "weekly"); // no days: the weekday of the due date
  assert.equal(presetOf("FREQ=MONTHLY", wednesday), "monthly");
  assert.equal(presetOf("FREQ=WEEKLY;BYDAY=MO", wednesday), "custom"); // another day than the due date
  assert.equal(presetOf("FREQ=DAILY;COUNT=3", wednesday), "custom");
  assert.equal(presetOf("FREQ=DAILY;INTERVAL=2", wednesday), "custom");
  assert.equal(presetOf("garbage", wednesday), "custom");
});
