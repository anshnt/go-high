import assert from "node:assert/strict";
import { test } from "node:test";
import { RecordsError } from "../src/records/errors.ts";
import { createMemoryClient } from "../src/records/memoryClient.ts";
import { seedDataset } from "../src/records/seed.ts";
import type { RecordRow, SortSpec } from "../src/records/types.ts";

const ANCHOR = Date.parse("2026-10-17T09:00:00Z");
const fresh = () => createMemoryClient({ dataset: seedDataset({ anchor: ANCHOR }), now: () => ANCHOR, me: () => ({ id: "u_me", name: "Test User" }) });

async function pages(c: ReturnType<typeof fresh>, sort: SortSpec[], limit: number, between?: (page: number, seen: RecordRow[]) => Promise<void>, object = "contact") {
  const seen: RecordRow[] = [];
  let cursor: string | null = null;
  for (let n = 0; ; n++) {
    const p = await c.query(object, { sort, limit, cursor });
    seen.push(...p.data);
    if (!p.next_cursor) break;
    cursor = p.next_cursor;
    await between?.(n, seen);
  }
  return seen;
}

test("the demo data is the size the screens have to cope with, and the same every run", async () => {
  const a = fresh();
  const b = fresh();
  assert.equal((await a.query("contact", { limit: 1 })).total, 2000);
  assert.equal((await a.query("company", { limit: 1 })).total, 300);
  assert.equal((await a.query("deal", { limit: 1 })).total, 150);
  const first = async (c: typeof a) => (await c.query("contact", { sort: [{ field: "id", dir: "asc" }], limit: 3 })).data.map((r) => [r.id, r.display_name, r.values.email]);
  assert.deepEqual(await first(a), await first(b));
  const recent = await a.query("contact", { filter: { and: [{ field: "lifecycle", op: "is", value: "customer" }, { field: "created_at", op: "within_last", value: { days: 30 } }] } });
  assert.ok(recent.total! > 20, `customers created in the last 30 days: ${recent.total}`);
});

test("paging in any sort visits every row once, in order", async () => {
  const c = fresh();
  for (const sort of [
    [{ field: "name", dir: "asc" }],
    [{ field: "lifecycle", dir: "desc" }], // thousands of ties
    [{ field: "email", dir: "asc" }], // empty values last
    [{ field: "lead_score", dir: "desc" }, { field: "name", dir: "asc" }],
    [{ field: "created_at", dir: "desc" }],
  ] as SortSpec[]) {
    const seen = await pages(c, sort, 137);
    assert.equal(seen.length, 2000, JSON.stringify(sort));
    assert.equal(new Set(seen.map((r) => r.id)).size, 2000, JSON.stringify(sort));
    const whole = await c.query("contact", { sort, limit: 200 });
    assert.deepEqual(seen.slice(0, 200).map((r) => r.id), whole.data.map((r) => r.id));
  }
});

test("paging stays correct while records are created, renamed and deleted between pages", async () => {
  const c = fresh();
  const sort: SortSpec[] = [{ field: "name", dir: "asc" }];
  const before = (await pages(c, sort, 2000)).map((r) => r.id);
  let created = "";
  let removed = "";
  let renamed = "";
  const seen = await pages(c, sort, 100, async (n, soFar) => {
    if (n !== 2) return;
    // delete a row that was already shown, add one that sorts after the cursor, and move an unseen row further down
    removed = soFar[5]!.id;
    await c.remove("contact", [removed]);
    created = (await c.create("contact", { values: { name: "Zzz New Contact" } })).id;
    renamed = before[1500]!;
    await c.update("contact", renamed, { name: "Zzzz Renamed" });
  });
  const ids = seen.map((r) => r.id);
  assert.equal(new Set(ids).size, ids.length, "no row appears twice");
  assert.ok(ids.includes(removed), "a row already shown stays shown");
  assert.ok(ids.includes(created), "a row created after the cursor shows up");
  assert.ok(ids.includes(renamed));
  assert.equal(seen.find((r) => r.id === renamed)!.display_name, "Zzzz Renamed");
  const untouched = before.filter((id) => id !== renamed && id !== removed);
  assert.equal(untouched.filter((id) => !ids.includes(id)).length, 0, "no untouched row is skipped");
  assert.equal(ids.length, 2000 + 1 - 0, "2000 original rows (the deleted one was already shown) plus the new one");
});

test("a bad cursor, or one from another sort, is a 400", async () => {
  const c = fresh();
  const p = await c.query("contact", { sort: [{ field: "name", dir: "asc" }], limit: 5 });
  const bad = (e: unknown) => e instanceof RecordsError && e.status === 400;
  await assert.rejects(c.query("contact", { cursor: "not-a-cursor" }), bad);
  await assert.rejects(c.query("contact", { sort: [{ field: "name", dir: "asc" }, { field: "city", dir: "asc" }], cursor: p.next_cursor }), bad);
});

test("an exhausted list has no next cursor, an empty result is fine", async () => {
  const c = fresh();
  const all = await c.query("deal", { limit: 200 });
  assert.equal(all.data.length, 150);
  assert.equal(all.next_cursor, null);
  const none = await c.query("contact", { q: "no such person anywhere" });
  assert.deepEqual([none.data.length, none.total, none.next_cursor], [0, 0, null]);
});

test("timeline pages newest first and records changes with old and new values", async () => {
  const c = fresh();
  const [row] = (await c.query("deal", { filter: { field: "stage", op: "is", value: "proposal" }, limit: 1 })).data;
  const id = row!.id;
  await c.update("deal", id, { stage: "negotiation" });
  await c.tag([id], "tag_vip");
  const t = await c.timeline(id);
  assert.equal(t.data[0]!.type, "tagged");
  assert.equal(t.data[1]!.type, "updated");
  assert.deepEqual(t.data[1]!.changes, [{ field: "stage", from: "proposal", to: "negotiation" }]);
  assert.equal(t.data.at(-1)!.type, "created");
  const times = t.data.map((e) => e.at);
  assert.deepEqual(times, [...times].sort().reverse());
  const small = await c.timeline(id, null);
  assert.equal(new Set(small.data.map((e) => e.id)).size, small.data.length);
});

test("a long timeline pages without gaps or repeats, even when events share a millisecond", async () => {
  const c = fresh();
  const id = (await c.query("contact", { limit: 1 })).data[0]!.id;
  for (let i = 1; i <= 30; i++) await c.update("contact", id, { lead_score: i });
  const seen: { id: string; to?: unknown }[] = [];
  let cursor: string | null = null;
  let pagesRead = 0;
  do {
    const p = await c.timeline(id, cursor);
    seen.push(...p.data.map((e) => ({ id: e.id, to: e.changes?.[0]?.to })));
    cursor = p.next_cursor;
    pagesRead++;
  } while (cursor);
  assert.ok(pagesRead >= 2, "more than one page");
  assert.equal(new Set(seen.map((e) => e.id)).size, seen.length);
  assert.deepEqual(seen.slice(0, 30).map((e) => e.to), Array.from({ length: 30 }, (_, i) => 30 - i));
  assert.equal(seen.length, (await c.timeline(id)).total);
});

test("writes are validated like the server will, and exit rules are enforced", async () => {
  const c = fresh();
  const bad = (status: number) => (e: unknown) => e instanceof RecordsError && e.status === status;
  await assert.rejects(c.create("contact", { values: { email: "x@y.example" } }), (e: unknown) => e instanceof RecordsError && e.status === 422 && !!e.fields?.name);
  await assert.rejects(c.create("contact", { values: { name: "A", email: "nope" } }), bad(422));
  const open = (await c.query("deal", { filter: { and: [{ field: "stage", op: "is", value: "new" }, { field: "close_date", op: "is_empty" }] }, limit: 1 })).data[0]!;
  await assert.rejects(c.update("deal", open.id, { stage: "won" }), (e: unknown) => e instanceof RecordsError && e.status === 422 && /close date/.test(e.message));
  assert.equal((await c.get("deal", open.id)).values.stage, "new", "nothing was saved");
  const ok = await c.update("deal", open.id, { stage: "won", close_date: "2026-10-01" });
  assert.equal(ok.values.stage, "won");
  const same = await c.update("deal", open.id, { stage: "won" });
  assert.equal(same.updated_at, ok.updated_at, "saving the same value changes nothing");
  await assert.rejects(c.update("deal", open.id, { weighted: 5 }), bad(422));
  await assert.rejects(c.get("deal", "dl_9999"), bad(404));
});

test("delete is a soft delete that restore reverses, links and rollups follow", async () => {
  const c = fresh();
  const co = (await c.query("company", { filter: { field: "contacts", op: "gt", value: 2 }, limit: 1 })).data[0]!;
  const members = (await c.query("contact", { filter: { field: "company", op: "is", value: co.id } })).data;
  await c.remove("contact", [members[0]!.id]);
  assert.equal((await c.get("company", co.id)).values.contacts, members.length - 1);
  await assert.rejects(c.get("contact", members[0]!.id), (e: unknown) => e instanceof RecordsError && e.status === 404);
  await c.restore("contact", [members[0]!.id]);
  assert.equal((await c.get("company", co.id)).values.contacts, members.length);
});

test("saved views: create, update, delete, and only the owner may change one", async () => {
  const c = fresh();
  const base = { object: "contact", name: "Mine", filter: null, columns: ["name"], sort: [], shared: false };
  const v = await c.saveView(base);
  assert.equal(v.owner_id, "u_me");
  const v2 = await c.saveView({ ...base, id: v.id, name: "Renamed", shared: true });
  assert.deepEqual([v2.name, v2.shared], ["Renamed", true]);
  assert.ok((await c.listViews("contact")).some((x) => x.id === v.id));
  assert.equal((await c.listViews("deal")).some((x) => x.id === v.id), false);
  await c.deleteView(v.id);
  assert.equal((await c.listViews("contact")).some((x) => x.id === v.id), false);
  await assert.rejects(c.deleteView("v_customers"), (e: unknown) => e instanceof RecordsError && e.status === 403);
  await assert.rejects(c.saveView({ ...base, name: "  " }), (e: unknown) => e instanceof RecordsError && e.status === 422);
});

test("tagging is idempotent and shows on the row", async () => {
  const c = fresh();
  const ids = (await c.query("contact", { limit: 3 })).data.map((r) => r.id);
  await c.tag(ids, "tag_priority");
  await c.tag(ids, "tag_priority");
  const rows = (await c.query("contact", { filter: { tag: "tag_priority" }, limit: 200 })).data;
  assert.ok(ids.every((id) => rows.find((r) => r.id === id)!.tags.filter((t) => t.id === "tag_priority").length === 1));
  await c.untag(ids, "tag_priority");
  assert.equal((await c.query("contact", { filter: { tag: "tag_priority" } })).data.some((r) => ids.includes(r.id)), false);
});
