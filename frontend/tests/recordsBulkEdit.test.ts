import assert from "node:assert/strict";
import { test } from "node:test";
import { bulkError, bulkFields, bulkValue, undoGroups, withChange } from "../src/records/bulkEdit.ts";
import { RecordsError } from "../src/records/errors.ts";
import { schema } from "../src/records/seed.ts";
import type { FieldDef } from "../src/records/types.ts";
import { makeClient } from "./recordsFixture.ts";

const { fields } = schema();
const fieldsOf = (object: string) => fields[object]!;
const fieldOf = (object: string, key: string): FieldDef => fieldsOf(object).find((f) => f.key === key)!;

test("a bulk edit offers the fields a person can type into, not the record's columns, archived, read-only or calculated ones", () => {
  const contact = bulkFields(fieldsOf("contact")).map((f) => f.key);
  for (const k of ["email", "phone", "lifecycle", "lead_score", "subscribed", "last_contacted", "interests", "about", "company"]) assert.ok(contact.includes(k), k);
  for (const k of ["owner_id", "created_at", "updated_at", "display_name", "legacy_id"]) assert.ok(!contact.includes(k), k);
  const company = bulkFields(fieldsOf("company")).map((f) => f.key);
  assert.ok(!company.includes("contacts") && !company.includes("open_value"), "rollups are calculated");
  assert.ok(!bulkFields(fieldsOf("deal")).some((f) => f.key === "weighted"), "formulas are calculated");
  const locked: FieldDef = { ...fieldOf("contact", "city"), key: "imported_at", rules: { read_only: true } };
  assert.deepEqual(bulkFields([locked]), []);
});

test("the value is checked and normalized like an inline edit, and clearing is a choice of its own", () => {
  assert.deepEqual(bulkValue(fieldOf("contact", "email"), "  Ada@Example.COM ", false), { value: "ada@example.com" });
  assert.deepEqual(bulkValue(fieldOf("company", "website"), "alder.example", false), { value: "https://alder.example" });
  assert.match((bulkValue(fieldOf("contact", "email"), "nope", false) as { error: string }).error, /valid email/);
  assert.match((bulkValue(fieldOf("contact", "lead_score"), 120, false) as { error: string }).error, /at most 100/);
  assert.match((bulkValue(fieldOf("contact", "city"), "   ", false) as { error: string }).error, /clear city/i);
  assert.deepEqual(bulkValue(fieldOf("contact", "lifecycle"), "customer", false), { value: "customer" });
  assert.deepEqual(bulkValue(fieldOf("contact", "subscribed"), undefined, false), { value: false }, "a switch left off means no");
  assert.deepEqual(bulkValue(fieldOf("contact", "city"), "Austin", true), { value: undefined });
  assert.match((bulkValue(fieldOf("deal", "stage"), undefined, true) as { error: string }).error, /cannot be cleared/);
});

test("the optimistic row keeps the name in step, and undo groups the records by what they had before", () => {
  const row = { id: "r1", object: "contact", display_name: "Ada", values: { name: "Ada", city: "Austin" }, owner_id: null, created_at: "", updated_at: "", tags: [] };
  assert.equal(withChange(row, { primary_fields: ["name"] }, "name", "Ada L").display_name, "Ada L");
  assert.deepEqual(withChange(row, { primary_fields: ["name"] }, "city", undefined).values, { name: "Ada" });
  const rows = [row, { ...row, id: "r2", values: { city: "Boston" } }, { ...row, id: "r3", values: {} }, { ...row, id: "r4", values: { city: "Austin" } }];
  assert.deepEqual(undoGroups(rows, "city"), [
    { value: "Austin", ids: ["r1", "r4"] },
    { value: "Boston", ids: ["r2"] },
    { value: undefined, ids: ["r3"] },
  ]);
});

test("the API's field messages are shown for the field, or all of them when they are about another one", () => {
  assert.equal(bulkError(new RecordsError(422, "x", { email: "Enter a valid email address." }), "email"), "Enter a valid email address.");
  assert.equal(bulkError(new RecordsError(422, "x", { close_date: "Add a close date.", stage: "A won deal needs a close date." }), "source"), "Add a close date. A won deal needs a close date.");
  assert.equal(bulkError(new RecordsError(404, "That record was not found."), "email"), "That record was not found.");
  assert.equal(bulkError(new Error("boom"), "email"), "Something went wrong. Try again.");
});

test("the demo client sets and clears a field on many records, all or nothing", async () => {
  const c = makeClient();
  const city = async (ids: string[]) => Promise.all(ids.map(async (id) => (await c.get("contact", id)).values.city));
  await c.updateMany("contact", ["ct_1", "ct_2", "ct_3"], { city: "Oslo" });
  assert.deepEqual(await city(["ct_1", "ct_2", "ct_3"]), ["Oslo", "Oslo", "Oslo"]);
  await c.updateMany("contact", ["ct_1", "ct_2"], { city: null });
  assert.deepEqual(await city(["ct_1", "ct_2", "ct_3"]), [undefined, undefined, "Oslo"]);
  // a bad value, an unknown record, or a rule one record breaks refuses the whole batch
  await assert.rejects(c.updateMany("contact", ["ct_1", "ct_3"], { email: "nope" }), (e: RecordsError) => e.status === 422 && !!e.fields?.email);
  await assert.rejects(c.updateMany("contact", ["ct_3", "ct_nope"], { city: "Rome" }), (e: RecordsError) => e.status === 404);
  assert.deepEqual(await city(["ct_3"]), ["Oslo"]);
  await assert.rejects(c.updateMany("deal", ["dl_2", "dl_4"], { stage: "won" }), (e: RecordsError) => e.status === 422);
  assert.deepEqual([(await c.get("deal", "dl_2")).values.stage, (await c.get("deal", "dl_4")).values.stage], ["proposal", "new"]);
});
