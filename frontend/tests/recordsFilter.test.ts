import assert from "node:assert/strict";
import { test } from "node:test";
import { RecordsError } from "../src/records/errors.ts";
import { ids, makeClient } from "./recordsFixture.ts";

const c = makeClient();
const contacts = (filter: unknown, extra?: Record<string, unknown>) => ids(c, "contact", filter, extra);
const cond = (field: string, op: string, value?: unknown) => ({ field, op, ...(value === undefined ? {} : { value }) });
const usd = (amount: number) => ({ amount, currency: "USD" });

test("is: text ignores case, select and record match ids, booleans treat unset as false", async () => {
  assert.deepEqual(await contacts(cond("name", "is", "ada lovelace")), ["ct_1"]);
  assert.deepEqual(await contacts(cond("lifecycle", "is", "customer")), ["ct_1", "ct_4"]);
  assert.deepEqual(await contacts(cond("company", "is", "co_1")), ["ct_1", "ct_2"]);
  assert.deepEqual(await contacts(cond("subscribed", "is", true)), ["ct_1", "ct_4"]);
  assert.deepEqual(await contacts(cond("subscribed", "is", false)), ["ct_2", "ct_3", "ct_5", "ct_6", "ct_7", "ct_8"]);
  assert.deepEqual(await contacts(cond("lead_score", "is", 40)), ["ct_2"]);
  assert.deepEqual(await contacts(cond("owner_id", "is", "u_maya")), ["ct_1", "ct_4"]);
});

test("is_not keeps records with no value", async () => {
  assert.deepEqual(await contacts(cond("lifecycle", "is_not", "customer")), ["ct_2", "ct_3", "ct_5", "ct_6", "ct_7", "ct_8"]);
});

test("contains and starts_with on text, contains on multi select", async () => {
  assert.deepEqual(await contacts(cond("name", "contains", "ADA")), ["ct_1", "ct_7"]);
  assert.deepEqual(await contacts(cond("name", "starts_with", "ada")), ["ct_1", "ct_7"]);
  assert.deepEqual(await contacts(cond("email", "starts_with", "ada.")), ["ct_7"]);
  assert.deepEqual(await contacts(cond("interests", "contains", "pricing")), ["ct_1"]);
});

test("gt, gte, lt, lte, between on numbers", async () => {
  assert.deepEqual(await contacts(cond("lead_score", "gt", 55)), ["ct_1", "ct_4"]);
  assert.deepEqual(await contacts(cond("lead_score", "gte", 55)), ["ct_1", "ct_4", "ct_6"]);
  assert.deepEqual(await contacts(cond("lead_score", "lt", 10)), ["ct_5"]);
  assert.deepEqual(await contacts(cond("lead_score", "lte", 10)), ["ct_3", "ct_5"]);
  assert.deepEqual(await contacts(cond("lead_score", "between", [40, 75])), ["ct_2", "ct_4", "ct_6"]);
});

test("is_empty and is_not_empty", async () => {
  assert.deepEqual(await contacts(cond("email", "is_empty")), ["ct_3", "ct_5", "ct_6", "ct_8"]);
  assert.deepEqual(await contacts(cond("email", "is_not_empty")), ["ct_1", "ct_2", "ct_4", "ct_7"]);
  assert.deepEqual(await contacts(cond("company", "is_empty")), ["ct_3", "ct_6", "ct_7", "ct_8"]);
  assert.deepEqual(await contacts(cond("interests", "is_empty")), ["ct_2", "ct_3", "ct_5", "ct_6", "ct_7", "ct_8"]);
});

test("within_last and older_than on instants (now is 2026-10-17 12:00 UTC)", async () => {
  assert.deepEqual(await contacts(cond("created_at", "within_last", { days: 7 })), ["ct_1", "ct_4", "ct_6"]);
  assert.deepEqual(await contacts(cond("created_at", "within_last", { days: 1 })), ["ct_4", "ct_6"]);
  assert.deepEqual(await contacts(cond("created_at", "within_last", { days: 30 })), ["ct_1", "ct_2", "ct_4", "ct_6"]);
  assert.deepEqual(await contacts(cond("created_at", "older_than", { days: 30 })), ["ct_3", "ct_5", "ct_7", "ct_8"]);
});

test("within_last and older_than on day-only dates work in whole days", async () => {
  assert.deepEqual(await contacts(cond("last_contacted", "within_last", { days: 7 })), ["ct_1"]);
  assert.deepEqual(await contacts(cond("last_contacted", "within_last", { days: 6 })), []);
  assert.deepEqual(await contacts(cond("last_contacted", "older_than", { days: 30 })), ["ct_2"]);
});

test("date comparisons: day boundaries on instants, plain strings on dates", async () => {
  assert.deepEqual(await contacts(cond("created_at", "is", "2026-10-17")), ["ct_6"]);
  assert.deepEqual(await contacts(cond("created_at", "gt", "2026-10-16")), ["ct_6"]);
  assert.deepEqual(await contacts(cond("created_at", "gte", "2026-10-16")), ["ct_4", "ct_6"]);
  assert.deepEqual(await contacts(cond("created_at", "lt", "2026-06-01")), ["ct_5", "ct_8"]);
  assert.deepEqual(await contacts(cond("created_at", "lte", "2026-06-01")), ["ct_3", "ct_5", "ct_8"]);
  assert.deepEqual(await contacts(cond("created_at", "between", ["2026-09-20", "2026-10-11"])), ["ct_1", "ct_2"]);
  assert.deepEqual(await contacts(cond("last_contacted", "gt", "2026-10-01")), ["ct_1"]);
  assert.deepEqual(await contacts(cond("last_contacted", "lte", "2026-08-01")), ["ct_2"]);
  assert.deepEqual(await contacts(cond("last_contacted", "between", ["2026-08-01", "2026-10-10"])), ["ct_1", "ct_2"]);
  assert.deepEqual(await contacts(cond("last_contacted", "is", "2026-10-10")), ["ct_1"]);
});

test("in and not_in on select, user and multi select", async () => {
  assert.deepEqual(await contacts(cond("lifecycle", "in", ["customer", "former"])), ["ct_1", "ct_4", "ct_5"]);
  assert.deepEqual(await contacts(cond("lifecycle", "not_in", ["customer", "former"])), ["ct_2", "ct_3", "ct_6", "ct_7", "ct_8"]);
  assert.deepEqual(await contacts(cond("owner_id", "in", ["u_maya", "u_theo"])), ["ct_1", "ct_2", "ct_4"]);
  assert.deepEqual(await contacts(cond("interests", "in", ["pricing", "integrations"])), ["ct_1", "ct_4"]);
  assert.deepEqual(await contacts(cond("interests", "not_in", ["pricing"])), ["ct_2", "ct_3", "ct_4", "ct_5", "ct_6", "ct_7", "ct_8"]);
});

test("tags", async () => {
  assert.deepEqual(await contacts({ tag: "tag_vip" }), ["ct_1", "ct_3"]);
  assert.deepEqual(await contacts({ tag: "tag_partner" }), ["ct_3", "ct_6"]);
});

test("and, or and nested groups; an empty group matches everything", async () => {
  assert.deepEqual(await contacts({ and: [cond("lifecycle", "is", "customer"), cond("created_at", "within_last", { days: 7 })] }), ["ct_1", "ct_4"]);
  assert.deepEqual(await contacts({ or: [cond("lifecycle", "is", "former"), { tag: "tag_partner" }] }), ["ct_3", "ct_5", "ct_6"]);
  assert.deepEqual(
    await contacts({ and: [cond("lifecycle", "is", "lead"), { or: [{ tag: "tag_partner" }, cond("lead_score", "gt", 30)] }] }),
    ["ct_2", "ct_6"],
  );
  assert.equal((await contacts({ and: [] })).length, 8);
  assert.equal((await contacts(null)).length, 8);
});

test("money compares inside one currency only", async () => {
  const deals = (f: unknown) => ids(c, "deal", f);
  assert.deepEqual(await deals(cond("amount", "gt", usd(500_000))), ["dl_1"]);
  assert.deepEqual(await deals(cond("amount", "gte", usd(300_000))), ["dl_1", "dl_2"]);
  assert.deepEqual(await deals(cond("amount", "lt", usd(300_000))), ["dl_4"]);
  assert.deepEqual(await deals(cond("amount", "lte", usd(300_000))), ["dl_2", "dl_4"]);
  assert.deepEqual(await deals(cond("amount", "between", [usd(200_000), usd(500_000)])), ["dl_2"]);
  assert.deepEqual(await deals(cond("amount", "is", usd(50_000))), ["dl_4"]);
  assert.deepEqual(await deals(cond("amount", "is", { amount: 800_000, currency: "EUR" })), ["dl_3"]);
  assert.deepEqual(await deals(cond("close_date", "is_empty")), ["dl_4"]);
  assert.deepEqual(await deals(cond("stage", "in", ["won", "lost"])), ["dl_1"]);
});

test("formula and rollup fields filter like their result type", async () => {
  assert.deepEqual(await ids(c, "deal", cond("weighted", "gt", usd(500_000))), ["dl_1"]);
  assert.deepEqual(await ids(c, "deal", cond("weighted", "between", [usd(100_000), usd(200_000)])), ["dl_2"]);
  assert.deepEqual(await ids(c, "company", cond("contacts", "gt", 1)), ["co_1"]);
  assert.deepEqual(await ids(c, "company", cond("open_value", "gt", usd(0))), ["co_1"]);
});

test("association paths match when any linked record matches", async () => {
  assert.deepEqual(await contacts(cond("company.industry", "is", "software")), ["ct_1", "ct_2"]);
  assert.deepEqual(await contacts(cond("company.name", "contains", "dental")), ["ct_4"]);
  assert.deepEqual(await contacts(cond("deal.stage", "is", "won")), ["ct_1"]);
  assert.deepEqual(await contacts(cond("deal.amount", "gt", usd(500_000))), ["ct_1"]);
  assert.deepEqual(await ids(c, "company", cond("contact.lifecycle", "is", "customer")), ["co_1", "co_2"]);
  assert.deepEqual(await ids(c, "company", cond("deal.stage", "is", "won")), ["co_1"]);
  assert.deepEqual(await ids(c, "deal", cond("contact.name", "starts_with", "grace")), ["dl_2"]);
});

test("negative operators over an association mean no linked record matches", async () => {
  assert.deepEqual(await contacts(cond("deal.stage", "is_not", "won")), ["ct_2", "ct_3", "ct_4", "ct_5", "ct_6", "ct_7", "ct_8"]);
  assert.deepEqual(await contacts(cond("deal.stage", "not_in", ["won", "proposal"])), ["ct_3", "ct_4", "ct_5", "ct_6", "ct_7", "ct_8"]);
  assert.deepEqual(await contacts(cond("deal.stage", "is_empty")), ["ct_3", "ct_5", "ct_6", "ct_7", "ct_8"]);
  assert.deepEqual(await contacts(cond("company.name", "is_empty")), ["ct_3", "ct_6", "ct_7", "ct_8"]);
  assert.deepEqual(await contacts(cond("company.name", "is_not_empty")), ["ct_1", "ct_2", "ct_4", "ct_5"]);
});

test("unknown fields, associations and operators that do not fit the type are 400s", async () => {
  const bad = async (f: unknown) => assert.rejects(contacts(f), (e: unknown) => e instanceof RecordsError && e.status === 400);
  await bad(cond("nope", "is", 1));
  await bad(cond("lead_score", "contains", "x"));
  await bad(cond("name", "gt", "a"));
  await bad(cond("subscribed", "in", [true]));
  await bad(cond("planet.name", "is", "x"));
});

test("text search needs every word, and finds phone digits and tag names", async () => {
  const q = async (text: string) => ids(c, "contact", null, { q: text });
  assert.deepEqual(await q("ada"), ["ct_1", "ct_7"]);
  assert.deepEqual(await q("ada lov"), ["ct_1"]);
  assert.deepEqual(await q("5550102"), ["ct_3"]);
  assert.deepEqual(await q("vip"), ["ct_1", "ct_3"]);
  assert.deepEqual(await q("founder ada"), ["ct_1"]);
  assert.deepEqual(await q("founder grace"), []);
  assert.deepEqual(await q("   "), await q(""));
});

test("sort puts empty values last whichever way it goes, ties break on id", async () => {
  const asc = await c.query("contact", { sort: [{ field: "lead_score", dir: "asc" }] });
  assert.deepEqual(asc.data.map((r) => r.id), ["ct_5", "ct_3", "ct_2", "ct_6", "ct_4", "ct_1", "ct_7", "ct_8"]);
  const desc = await c.query("contact", { sort: [{ field: "lead_score", dir: "desc" }] });
  assert.deepEqual(desc.data.map((r) => r.id), ["ct_1", "ct_4", "ct_6", "ct_2", "ct_3", "ct_5", "ct_7", "ct_8"]);
  const byStage = await c.query("deal", { sort: [{ field: "stage", dir: "desc" }] });
  assert.deepEqual(byStage.data.map((r) => r.id), ["dl_1", "dl_3", "dl_2", "dl_4"]);
  const two = await c.query("contact", { sort: [{ field: "lifecycle", dir: "asc" }, { field: "name", dir: "desc" }] });
  assert.deepEqual(two.data.map((r) => r.id).slice(0, 4), ["ct_6", "ct_2", "ct_7", "ct_3"]);
  await assert.rejects(c.query("contact", { sort: [{ field: "interests", dir: "asc" }] }), (e: unknown) => e instanceof RecordsError && e.status === 400);
});

test("rows carry computed values and the total", async () => {
  const page = await c.query("company", { filter: cond("name", "is", "Alder Labs") });
  assert.equal(page.total, 1);
  assert.equal(page.data[0]!.values.contacts, 2);
  assert.deepEqual(page.data[0]!.values.open_value, usd(300_000));
});
