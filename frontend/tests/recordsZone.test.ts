import assert from "node:assert/strict";
import { test } from "node:test";
import type { Filter, LinkType } from "../src/records/types.ts";

// The date formatters are built when format.ts loads, in the zone then: pin one before anything loads.
process.env.TZ = "UTC";
const { filterFields, filterToText } = await import("../src/records/filter.ts");
const { schema } = await import("../src/records/seed.ts");
const { ids, makeClient } = await import("./recordsFixture.ts");

// "created on 2026-10-17" is that day where the viewer is: the same records are on different days in different zones.
// ct_4 was created 2026-10-16T13:00Z, ct_6 2026-10-17T06:00Z.
const c = makeClient();
const created = (op: string, value: unknown) => ids(c, "contact", { field: "created_at", op, value });

test("a day on a datetime field is a day in the viewer's zone (the memory client, as the API client sends it)", async () => {
  process.env.TZ = "UTC";
  assert.deepEqual(await created("is", "2026-10-17"), ["ct_6"]);
  assert.deepEqual(await created("is", "2026-10-16"), ["ct_4"]);

  process.env.TZ = "America/Los_Angeles"; // ct_6 is still the evening of the 16th there
  assert.deepEqual(await created("is", "2026-10-17"), []);
  assert.deepEqual(await created("is", "2026-10-16"), ["ct_4", "ct_6"]);
  assert.deepEqual(await created("gt", "2026-10-16"), []);
  assert.deepEqual(await created("lte", "2026-10-16"), ["ct_1", "ct_2", "ct_3", "ct_4", "ct_5", "ct_6", "ct_7", "ct_8"]);

  process.env.TZ = "Pacific/Kiritimati"; // UTC+14: ct_4 is already the 17th
  assert.deepEqual(await created("is", "2026-10-17"), ["ct_4", "ct_6"]);
  assert.deepEqual(await created("between", ["2026-10-17", "2026-10-17"]), ["ct_4", "ct_6"]);
  assert.deepEqual(await created("lt", "2026-10-17"), ["ct_1", "ct_2", "ct_3", "ct_5", "ct_7", "ct_8"]);
});

test("a date field has no zone: the same day everywhere", async () => {
  for (const zone of ["UTC", "America/Los_Angeles", "Pacific/Kiritimati"]) {
    process.env.TZ = zone;
    assert.deepEqual(await ids(c, "contact", { field: "last_contacted", op: "is", value: "2026-10-10" }), ["ct_1"], zone);
    assert.deepEqual(await ids(c, "contact", { field: "last_contacted", op: "lt", value: "2026-10-10" }), ["ct_2"], zone);
  }
});

const { objects, fields } = schema();
const flat = filterFields("contact", objects, fields).map((r) => r.field);

test("the summary of a day on a datetime field names the time zone, other conditions do not", () => {
  process.env.TZ = "UTC"; // the zone the formatters were built in
  const text = (f: Filter, timeZone?: string) => filterToText(f, flat, { timeZone });
  assert.equal(text({ field: "created_at", op: "gte", value: "2026-10-01" }, "Europe/Lisbon"), "Created is on or after Oct 1, 2026 (your time zone: Europe/Lisbon)");
  assert.equal(text({ field: "created_at", op: "between", value: ["2026-10-01", "2026-10-05"] }, "Asia/Calcutta"), "Created is between Oct 1, 2026 and Oct 5, 2026 (your time zone: Asia/Calcutta)");
  assert.equal(text({ field: "created_at", op: "is", value: "2026-10-17" }, "UTC"), "Created is Oct 17, 2026 (your time zone: UTC)");
  assert.equal(text({ field: "created_at", op: "within_last", value: { days: 30 } }, "UTC"), "Created is within the last 30 days"); // a span from now
  assert.equal(text({ field: "created_at", op: "is_empty" }, "UTC"), "Created is empty");
  assert.equal(text({ field: "last_contacted", op: "lt", value: "2026-10-01" }, "UTC"), "Last contacted is before Oct 1, 2026"); // a calendar day
  assert.equal(text({ field: "created_at", op: "gte", value: "2026-10-01" }), "Created is on or after Oct 1, 2026"); // no zone given: nothing added
  assert.equal(text({ and: [{ field: "lifecycle", op: "is", value: "customer" }, { field: "created_at", op: "lt", value: "2026-10-01" }] }, "UTC"), "Lifecycle is Customer and Created is before Oct 1, 2026 (your time zone: UTC)");
});

test("links that are associations offer the other object's fields in a filter, once", () => {
  const links: LinkType[] = [
    { from: "deal", to: "contact", label: "contact", inverse_label: "deal" },
    { from: "contact", to: "company", label: "works at", inverse_label: "employs" },
  ];
  const paths = (object: string, withLinks: LinkType[]) => filterFields(object, objects, fields, withLinks).map((r) => r.path);
  // the memory schema links through record fields: contacts reach company.* and deal.*
  const plain = paths("contact", []);
  assert.ok(plain.includes("company.industry") && plain.includes("deal.amount"));
  const linked = paths("contact", links);
  assert.deepEqual(linked, plain); // the same links by another route add no second copy
  assert.equal(new Set(linked).size, linked.length);
  // a link that no record field makes is new
  const onlyAssociation = filterFields("company", objects, { ...fields, deal: fields.deal!.filter((f) => f.type !== "record") }, [{ from: "deal", to: "company", label: "company", inverse_label: "deal" }]).map((r) => r.path);
  assert.ok(onlyAssociation.includes("deal.amount") && onlyAssociation.includes("deal.stage"));
  const without = filterFields("company", objects, { ...fields, deal: fields.deal!.filter((f) => f.type !== "record") }).map((r) => r.path);
  assert.ok(!without.includes("deal.amount"));
});
