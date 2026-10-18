import assert from "node:assert/strict";
import { test } from "node:test";
import { subtitle } from "../src/records/format.ts";
import { phoneLines } from "../src/records/phoneRow.ts";
import { DISPLAY_NAME, isSortable, nameKey, nameOf } from "../src/records/schema.ts";
import type { FieldDef, FieldType, ObjectDef, RecordRow } from "../src/records/types.ts";

let position = 0;
const f = (key: string, type: FieldType, extra: Partial<FieldDef> = {}): FieldDef => ({ key, label: key, type, options: {}, rules: {}, is_system: false, position: ++position, archived: false, ...extra });
const row = (values: Record<string, unknown>): RecordRow => ({ id: "r1", object: "contact", display_name: "Ada Lovelace", values, owner_id: "u1", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-02T00:00:00Z", tags: [] });
const def = (...primary: string[]): Pick<ObjectDef, "primary_fields"> => ({ primary_fields: primary });

const contactFields = [
  f(DISPLAY_NAME, "text", { rules: { read_only: true } }),
  f("first_name", "text"),
  f("last_name", "text"),
  f("city", "text"),
  f("phone", "phone"),
  f("lifecycle", "select"),
  f("company", "record", { options: { object: "company" } }),
  f("email", "email"),
  f("subscribed", "boolean"),
  f("about", "long_text"),
  f("owner_id", "user", { is_system: true }),
  f("created_at", "datetime", { is_system: true }),
];

test("a phone row shows the email and the company under the name", () => {
  const lines = phoneLines(def("first_name", "last_name"), row({ first_name: "Ada", last_name: "Lovelace", email: "ada@example.com", phone: "+14155550101", company: "co1", lifecycle: "lead", city: "Austin" }), contactFields);
  assert.deepEqual(lines.map((l) => [l.field.key, l.value]), [["email", "ada@example.com"], ["company", "co1"]]);
});

test("without an email the next most useful values take its place, and never more than two", () => {
  const only = (values: Record<string, unknown>) => phoneLines(def("first_name", "last_name"), row(values), contactFields).map((l) => l.field.key);
  assert.deepEqual(only({ company: "co1", phone: "+14155550101", lifecycle: "lead" }), ["company", "phone"]);
  assert.deepEqual(only({ phone: "+14155550101", lifecycle: "lead", city: "Austin" }), ["phone", "lifecycle"]);
  assert.deepEqual(only({ lifecycle: "lead", city: "Austin" }), ["lifecycle", "city"]);
  assert.deepEqual(only({ city: "Austin" }), ["city"]);
  assert.deepEqual(only({}), []);
  assert.deepEqual(only({ email: "a@example.com" }), ["email"]);
});

test("the name, the owner, the dates, flags and long text are never a second line", () => {
  const lines = phoneLines(def("first_name", "last_name"), row({ first_name: "Ada", last_name: "Lovelace", subscribed: true, about: "A long story", email: "" }), contactFields);
  assert.deepEqual(lines, []); // an empty email is no email
});

test("archived fields and empty values are skipped, equal types keep the workspace's field order", () => {
  const fields = [f("name", "text"), f("old_email", "email", { archived: true }), f("size", "select"), f("industry", "select")];
  const lines = phoneLines(def("name"), row({ name: "Acme", old_email: "x@example.com", industry: "software", size: "11-50" }), fields);
  assert.deepEqual(lines.map((l) => l.field.key), ["size", "industry"]);
  assert.deepEqual(phoneLines(def("name"), row({ name: "Acme", old_email: "x@example.com" }), fields), []);
});

test("an object named by one field is listed by that field, one named by several by the derived name", () => {
  assert.equal(nameKey(def("name")), "name");
  assert.equal(nameKey(def("first_name", "last_name")), DISPLAY_NAME);
  assert.equal(nameOf(def("first_name", "last_name"), { first_name: "Ada", last_name: "Lovelace" }), "Ada Lovelace");
  assert.equal(nameOf(def("first_name", "last_name"), { first_name: "Ada" }), "Ada");
  assert.equal(nameOf(def("first_name", "last_name"), { last_name: "", first_name: "Ada", email: "a@example.com" }), "Ada");
  assert.equal(nameOf(def("name"), {}), "");
});

test("people are not sortable, since a sort would need the users joined", () => {
  assert.equal(isSortable(f("owner_id", "user")), false);
  assert.equal(isSortable(f("rep", "user")), false);
  assert.equal(isSortable(f("created_at", "datetime")), true);
  assert.equal(isSortable(f(DISPLAY_NAME, "text")), true);
  assert.equal(isSortable(f("company", "record")), false);
});

test("a subtitle skips every field that makes up the name", () => {
  const fields = [f("first_name", "text"), f("last_name", "text"), f("email", "email")];
  assert.equal(subtitle({ first_name: "Ada", last_name: "Lovelace", email: "ada@example.com" }, fields, ["first_name", "last_name"]), "ada@example.com");
  assert.equal(subtitle({ first_name: "Ada" }, fields, ["first_name", "last_name"]), "");
});
