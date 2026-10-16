import assert from "node:assert/strict";
import { test } from "node:test";
import {
  dayHeading,
  formatDateTime,
  formatDay,
  formatMoney,
  fromLocalInput,
  toLocalInput,
  minorDigits,
  moneyToInput,
  parseDay,
  parseMoney,
  relativeDay,
  relativeTime,
  toDay,
  valueText,
} from "../src/records/format.ts";
import { normalizeText, validateValue } from "../src/records/validate.ts";
import { schema } from "../src/records/seed.ts";

// A fixed local noon, so day arithmetic holds in any time zone.
const NOON = new Date(2026, 9, 17, 12, 0, 0).getTime();
const at = (days: number, hours = 0, minutes = 0) => new Date(NOON + days * 86_400_000 + hours * 3_600_000 + minutes * 60_000).toISOString();

test("money is formatted from integer minor units in its own currency", () => {
  assert.equal(formatMoney({ amount: 123450, currency: "USD" }), "$1,234.50");
  assert.equal(formatMoney({ amount: 5, currency: "USD" }), "$0.05");
  assert.equal(formatMoney({ amount: 800000, currency: "EUR" }), "€8,000.00");
  assert.equal(formatMoney({ amount: 1500, currency: "JPY" }), "¥1,500");
  assert.equal(formatMoney({ amount: 12345, currency: "KWD" }).normalize("NFKC"), "KWD 12.345");
  assert.equal(formatMoney({ amount: -2500, currency: "USD" }), "-$25.00");
  assert.equal(formatMoney({ amount: 100, currency: "NOPE" }), "$1.00");
});

test("minor units per currency", () => {
  assert.equal(minorDigits("USD"), 2);
  assert.equal(minorDigits("JPY"), 0);
  assert.equal(minorDigits("KWD"), 3);
});

test("typed amounts become minor units without float drift", () => {
  assert.equal(parseMoney("1,234.50", "USD"), 123450);
  assert.equal(parseMoney("$19.99", "USD"), 1999);
  assert.equal(parseMoney("0.07", "USD"), 7);
  assert.equal(parseMoney("12", "USD"), 1200);
  assert.equal(parseMoney(".5", "USD"), 50);
  assert.equal(parseMoney("1500", "JPY"), 1500);
  assert.equal(parseMoney("-3", "USD"), -300);
  assert.equal(parseMoney("1.005", "USD"), null);
  assert.equal(parseMoney("1.5", "JPY"), null);
  assert.equal(parseMoney("abc", "USD"), null);
  assert.equal(parseMoney("", "USD"), null);
  assert.equal(parseMoney("1.2.3", "USD"), null);
  assert.equal(parseMoney("99999999999999999999", "USD"), null);
});

test("amounts go back into the input as plain decimals", () => {
  assert.equal(moneyToInput({ amount: 123450, currency: "USD" }), "1234.50");
  assert.equal(moneyToInput({ amount: 1500, currency: "JPY" }), "1500");
  assert.equal(moneyToInput(null), "");
});

test("calendar days are never shifted by a time zone", () => {
  assert.equal(formatDay("2026-10-17"), "Oct 17, 2026");
  assert.equal(formatDay("2026-01-01"), "Jan 1, 2026");
  assert.equal(parseDay("2026-02-30"), null);
  assert.equal(parseDay("nope"), null);
  assert.equal(toDay(parseDay("2026-12-31")!), "2026-12-31");
  assert.equal(formatDateTime("2026-10-17T09:05:00Z", "UTC"), "Oct 17, 2026, 9:05 AM");
  assert.equal(formatDateTime("garbage"), "garbage");
});

test("relative times read both ways", () => {
  assert.equal(relativeTime(new Date(NOON - 20_000).toISOString(), NOON), "just now");
  assert.equal(relativeTime(at(0, 0, -1), NOON), "1 minute ago");
  assert.equal(relativeTime(at(0, 0, -5), NOON), "5 minutes ago");
  assert.equal(relativeTime(at(0, 0, 90), NOON), "in 2 hours");
  assert.equal(relativeTime(at(0, -3), NOON), "3 hours ago");
  assert.equal(relativeTime(at(-1), NOON), "yesterday");
  assert.equal(relativeTime(at(3), NOON), "in 3 days");
  assert.equal(relativeTime(at(-14), NOON), "2 weeks ago");
  assert.equal(relativeTime(at(-90), NOON), "3 months ago");
  assert.equal(relativeTime(at(-800), NOON), "2 years ago");
  assert.equal(relativeTime("garbage", NOON), "");
});

test("relative days count calendar days", () => {
  assert.equal(relativeDay("2026-10-17", NOON), "today");
  assert.equal(relativeDay("2026-10-18", NOON), "tomorrow");
  assert.equal(relativeDay("2026-10-16", NOON), "yesterday");
  assert.equal(relativeDay("2026-10-24", NOON), "next week");
  assert.equal(relativeDay("2026-09-17", NOON), "last month");
  assert.equal(relativeDay("2026-11-20", NOON), "next month");
  assert.equal(relativeDay("2026-11-15", NOON), "in 4 weeks");
  assert.equal(relativeDay("nope", NOON), "nope");
});

test("timeline day headings", () => {
  assert.equal(dayHeading(at(0, -2), NOON), "Today");
  assert.equal(dayHeading(at(-1), NOON), "Yesterday");
  assert.equal(dayHeading(at(-5), NOON), "Mon, Oct 12");
  assert.equal(dayHeading("2025-03-04T12:00:00.000Z", NOON), "Mar 4, 2025");
});

test("any value as words", () => {
  const f = Object.fromEntries(schema().fields.contact!.map((x) => [x.key, x]));
  assert.equal(valueText(f.lifecycle!, "customer"), "Customer");
  assert.equal(valueText(f.interests!, ["pricing", "support"]), "Pricing, Support");
  assert.equal(valueText(f.subscribed!, false), "No");
  assert.equal(valueText(f.last_contacted!, "2026-10-10"), "Oct 10, 2026");
  assert.equal(valueText(f.owner_id!, "u_x", { users: [{ id: "u_x", name: "Pat Example" }] }), "Pat Example");
  assert.equal(valueText(f.company!, "co_1", { records: { co_1: "Alder Labs" } }), "Alder Labs");
  assert.equal(valueText(f.lead_score!, 1234.5), "1,234.5");
  assert.equal(valueText(f.email!, ""), "");
  assert.equal(valueText(f.email!, undefined), "");
  const rollup = schema().fields.company!.find((x) => x.key === "open_value")!;
  assert.equal(valueText(rollup, { amount: 300000, currency: "USD" }), "$3,000.00");
});

test("validation messages", () => {
  const f = Object.fromEntries(schema().fields.contact!.map((x) => [x.key, x]));
  assert.equal(validateValue(f.name!, ""), "Name is required.");
  assert.equal(validateValue(f.name!, "Ada"), null);
  assert.equal(validateValue(f.email!, ""), null);
  assert.match(validateValue(f.email!, "ada@")!, /valid email/);
  assert.equal(validateValue(f.email!, "ada@alder.example"), null);
  assert.match(validateValue(f.phone!, "12")!, /phone/);
  assert.equal(validateValue(f.phone!, "+1 415 555 0101"), null);
  assert.match(validateValue(f.lead_score!, 101)!, /at most 100/);
  assert.match(validateValue(f.lead_score!, -1)!, /at least 0/);
  assert.equal(validateValue(f.lead_score!, 0), null);
  assert.match(validateValue(f.lifecycle!, "wat")!, /options/);
  assert.match(validateValue(f.last_contacted!, "2026-13-01")!, /valid date/);
  const company = Object.fromEntries(schema().fields.company!.map((x) => [x.key, x]));
  assert.match(validateValue(company.website!, "alder")!, /web address/);
  assert.equal(validateValue(company.website!, "https://alder.example"), null);
  assert.match(validateValue(company.annual_revenue!, { amount: -1, currency: "USD" })!, /negative/);
  assert.match(validateValue(company.contacts!, 3)!, /calculated/);
});

test("typed text is tidied before it is saved", () => {
  const company = Object.fromEntries(schema().fields.company!.map((x) => [x.key, x]));
  const contact = Object.fromEntries(schema().fields.contact!.map((x) => [x.key, x]));
  assert.equal(normalizeText(company.website!, "  alder.example "), "https://alder.example");
  assert.equal(normalizeText(company.website!, "http://alder.example"), "http://alder.example");
  assert.equal(normalizeText(contact.email!, " Ada@Alder.Example "), "ada@alder.example");
  assert.equal(normalizeText(contact.name!, "  Ada  "), "Ada");
});

test("datetime inputs round-trip through the viewer's zone", () => {
  const iso = new Date(2026, 9, 17, 9, 5).toISOString();
  assert.equal(toLocalInput(iso), "2026-10-17T09:05");
  assert.equal(fromLocalInput("2026-10-17T09:05"), iso);
  assert.equal(fromLocalInput(""), undefined);
  assert.equal(toLocalInput("nope"), "");
});
