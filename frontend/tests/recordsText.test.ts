import assert from "node:assert/strict";
import { test } from "node:test";
import { canonical, cleanFilter, convertValue, countConditions, defaultValue, filterFields, filterToText, isComplete, opsFor, toRoot } from "../src/records/filter.ts";
import { schema, TAGS, USERS } from "../src/records/seed.ts";
import type { Filter } from "../src/records/types.ts";

const { objects, fields } = schema();
const contact = fields.contact!;
const refs = filterFields("contact", objects, fields);
const flat = refs.map((r) => r.field);
const ctx = { tags: TAGS, users: USERS, records: { co_1: "Alder Labs" } };
const text = (f: Filter | null) => filterToText(f, flat, ctx);

test("one condition reads as a sentence", () => {
  assert.equal(text({ field: "lifecycle", op: "is", value: "customer" }), "Lifecycle is Customer");
  assert.equal(text({ field: "name", op: "contains", value: "ada" }), 'Name contains "ada"');
  assert.equal(text({ field: "email", op: "is_empty" }), "Email is empty");
  assert.equal(text({ field: "lead_score", op: "between", value: [10, 50] }), "Lead score is between 10 and 50");
  assert.equal(text({ field: "lead_score", op: "gte", value: 50 }), "Lead score is at least 50");
  assert.equal(text({ field: "subscribed", op: "is", value: true }), "Email subscribed is Yes");
  assert.equal(text({ field: "company", op: "is", value: "co_1" }), "Company is Alder Labs");
  assert.equal(text({ field: "owner_id", op: "in", value: ["u_maya", "u_theo"] }), "Owner is any of Maya Okafor, Theo Lindqvist");
  assert.equal(text({ field: "interests", op: "contains", value: "pricing" }), "Interests includes Pricing");
  assert.equal(text({ field: "last_contacted", op: "lt", value: "2026-10-01" }), "Last contacted is before Oct 1, 2026");
});

test("relative dates", () => {
  assert.equal(text({ field: "created_at", op: "within_last", value: { days: 30 } }), "Created is within the last 30 days");
  assert.equal(text({ field: "created_at", op: "within_last", value: { days: 1 } }), "Created is within the last 1 day");
  assert.equal(text({ field: "created_at", op: "older_than", value: { days: 90 } }), "Created is older than 90 days");
});

test("tags and money", () => {
  assert.equal(text({ tag: "tag_vip" }), "Tagged VIP");
  assert.equal(text({ tag: "tag_gone" }), "Tagged tag_gone");
  const deal = filterFields("deal", objects, fields).map((r) => r.field);
  assert.equal(filterToText({ field: "amount", op: "gt", value: { amount: 500000, currency: "USD" } }, deal), "Amount is greater than $5,000");
  assert.equal(filterToText({ field: "amount", op: "between", value: [{ amount: 100, currency: "EUR" }, { amount: 20000, currency: "EUR" }] }, deal), "Amount is between €1.00 and €200.00");
});

test("groups: and, or, nesting with brackets, empties dropped", () => {
  const ast: Filter = {
    and: [
      { field: "lifecycle", op: "is", value: "customer" },
      { field: "created_at", op: "within_last", value: { days: 30 } },
      { or: [{ tag: "tag_vip" }, { field: "deal.amount", op: "gt", value: { amount: 500000, currency: "USD" } }] },
    ],
  };
  assert.equal(text(ast), "Lifecycle is Customer and Created is within the last 30 days and (Tagged VIP or Deal amount is greater than $5,000)");
  assert.equal(text({ or: [{ tag: "tag_vip" }, { tag: "tag_partner" }] }), "Tagged VIP or Tagged Partner");
  assert.equal(text({ and: [{ and: [] }, { tag: "tag_vip" }] }), "Tagged VIP");
  assert.equal(text({ and: [{ or: [{ tag: "tag_vip" }] }] }), "Tagged VIP");
  assert.equal(text({ and: [] }), "");
  assert.equal(text(null), "");
});

test("association paths use the other object's labels, unknown keys are spelled out", () => {
  assert.equal(text({ field: "company.industry", op: "is", value: "software" }), "Company industry is Software");
  assert.equal(text({ field: "deal.stage", op: "is_not", value: "won" }), "Deal stage is not Won");
  assert.equal(filterToText({ field: "mystery_field", op: "is", value: 3 }, []), "Mystery field is 3");
  assert.equal(filterToText({ field: "company.size", op: "is_empty" }, []), "Company size is empty");
});

test("operators by field type", () => {
  const by = (key: string) => contact.find((f) => f.key === key)!;
  assert.deepEqual(opsFor(by("name")), ["contains", "is", "is_not", "starts_with", "is_empty", "is_not_empty"]);
  assert.ok(opsFor(by("lead_score")).includes("between"));
  assert.ok(!opsFor(by("lead_score")).includes("contains"));
  assert.ok(opsFor(by("created_at")).includes("within_last"));
  assert.ok(!opsFor(by("last_contacted")).includes("contains"));
  assert.deepEqual(opsFor(by("subscribed")), ["is"]);
  assert.ok(opsFor(by("interests")).includes("contains"));
  assert.ok(!opsFor(by("interests")).includes("is"));
  assert.deepEqual(opsFor(by("company")), ["is", "is_not", "is_empty", "is_not_empty"]);
  const rollup = fields.company!.find((f) => f.key === "open_value")!;
  assert.ok(opsFor(rollup).includes("gt"));
});

test("a half-built filter is tidied before it is applied", () => {
  const raw: Filter = {
    and: [
      { field: "lifecycle", op: "is" },
      { field: "name", op: "contains", value: "" },
      { field: "lead_score", op: "between", value: [10, null] },
      { field: "lead_score", op: "between", value: [10, 20] },
      { field: "created_at", op: "within_last", value: { days: 0 } },
      { field: "email", op: "is_empty" },
      { tag: "" },
      { or: [{ field: "owner_id", op: "in", value: [] }, { tag: "tag_vip" }] },
      { and: [{ field: "city", op: "is" }] },
    ],
  };
  assert.deepEqual(cleanFilter(raw), {
    and: [
      { field: "lead_score", op: "between", value: [10, 20] },
      { field: "email", op: "is_empty" },
      { or: [{ tag: "tag_vip" }] },
    ],
  });
  assert.equal(cleanFilter({ and: [{ field: "name", op: "is" }] }), null);
  assert.equal(cleanFilter(null), null);
  assert.equal(countConditions(cleanFilter(raw)), 3);
  assert.equal(isComplete({ field: "x", op: "is", value: false }), true);
  assert.equal(isComplete({ field: "x", op: "is", value: 0 }), true);
});

test("changing the operator keeps what was typed when it can", () => {
  const f = contact.find((x) => x.key === "lead_score")!;
  assert.equal(convertValue(f, "gt", "lt", 5), 5);
  assert.deepEqual(convertValue(f, "gt", "between", 5), [5, null]);
  assert.equal(convertValue(f, "between", "gt", [5, 9]), 5);
  const sel = contact.find((x) => x.key === "lifecycle")!;
  assert.deepEqual(convertValue(sel, "is", "in", "lead"), ["lead"]);
  assert.equal(convertValue(sel, "in", "is", ["lead", "former"]), "lead");
  assert.deepEqual(defaultValue(f, "between"), [null, null]);
  assert.deepEqual(defaultValue(f, "within_last"), { days: 30 });
  assert.equal(defaultValue(contact.find((x) => x.key === "subscribed")!, "is"), true);
});

test("the builder always edits a group", () => {
  assert.deepEqual(toRoot(null), { and: [] });
  assert.deepEqual(toRoot({ tag: "tag_vip" }), { and: [{ tag: "tag_vip" }] });
  assert.deepEqual(toRoot({ or: [] }), { or: [] });
});

test("two filters are the same whatever the key order", () => {
  assert.equal(canonical({ field: "a", op: "is", value: 1 }), canonical({ value: 1, op: "is", field: "a" }));
  assert.notEqual(canonical({ and: [{ tag: "a" }] }), canonical({ or: [{ tag: "a" }] }));
  assert.equal(canonical(null), canonical(undefined));
});

test("fields a filter can reach: own, through links, and from the other side", () => {
  const paths = refs.map((r) => r.path);
  assert.ok(paths.includes("lifecycle"));
  assert.ok(paths.includes("created_at"));
  assert.ok(paths.includes("company.name"));
  assert.ok(paths.includes("company.industry"));
  assert.ok(paths.includes("deal.amount"));
  assert.ok(paths.includes("deal.stage"));
  assert.ok(!paths.includes("legacy_id"), "archived fields stay hidden");
  assert.ok(!paths.includes("company.contacts"), "computed fields are not offered across a link");
  assert.ok(paths.includes("company.owner_id"), "system columns of the other object are fine");
  const amount = refs.find((r) => r.path === "deal.amount")!;
  assert.equal(amount.group, "Deals");
  assert.equal(amount.field.label, "Deal amount");
  assert.equal(amount.field.key, "deal.amount");
  const forDeal = filterFields("deal", objects, fields).map((r) => r.path);
  assert.ok(forDeal.includes("contact.name") && forDeal.includes("company.industry"));
  const forCompany = filterFields("company", objects, fields).map((r) => r.path);
  assert.ok(forCompany.includes("contact.lifecycle") && forCompany.includes("deal.amount"));
});
