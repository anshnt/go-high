import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, fetchSend, httpOf, queryString } from "../src/lib/http.ts";
import { asRecordsError, colorName, convertFilter, createApiClient, parseSort, sortParam, stageChoices, toTimelineEvent, type ApiEvent, type ApiPipeline } from "../src/records/apiClient.ts";
import { RecordsError } from "../src/records/errors.ts";
import type { Filter, Tag } from "../src/records/types.ts";

// A fake server behind fetch: each test says how it answers, and reads back what was asked.
type Call = { method: string; path: string; body: any; headers: Record<string, string> };
type Handler = (call: Call) => unknown;

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

function fake(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  const fetchImpl = (async (path: string, init: RequestInit) => {
    const call: Call = { method: init.method ?? "GET", path, body: init.body ? JSON.parse(String(init.body)) : undefined, headers: init.headers as Record<string, string> };
    calls.push(call);
    const key = Object.keys(routes).find((k) => `${call.method} ${call.path}`.startsWith(k));
    if (!key) return json({ error: { code: "not_found", message: `no route ${call.method} ${call.path}` } }, 404);
    const out = routes[key]!(call);
    return out instanceof Response ? out : out === undefined ? new Response(null, { status: 204 }) : json(out);
  }) as unknown as typeof fetch;
  const http = httpOf(fetchSend({ workspace: () => "ws-1", fetch: fetchImpl }));
  const client = createApiClient(http);
  return { calls, client, http };
}

const page = <T>(data: T[], next_cursor: string | null = null, extra: object = {}) => ({ data, next_cursor, ...extra });
const row = (id: string, extra: object = {}) => ({ id, object: "contact", display_name: `Person ${id}`, values: {}, owner_id: null, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-02T00:00:00Z", ...extra });
const field = (key: string, type: string, extra: object = {}) => ({ key, label: key, type, options: {}, rules: {}, is_system: true, position: 0, archived_at: null, ...extra });
const contact = { id: "o1", key: "contact", singular: "Contact", plural: "Contacts", icon: "user", is_system: true, primary_fields: ["first_name", "last_name"], archived_at: null };
const company = { id: "o2", key: "company", singular: "Company", plural: "Companies", icon: "building", is_system: true, primary_fields: ["name"], archived_at: null };

async function fails(run: () => Promise<unknown>): Promise<RecordsError> {
  try {
    await run();
  } catch (e) {
    assert.ok(e instanceof RecordsError, `expected a RecordsError, got ${e}`);
    return e;
  }
  throw new Error("expected a failure");
}

test("every request names the workspace, and bodies are JSON", async () => {
  const { calls, client } = fake({ "GET /api/v1/members": () => page([{ user_id: "u1", name: "Ada", email: "ada@example.com", role: { key: "admin" }, implicit: true, teams: [] }]) });
  assert.deepEqual(await client.listUsers(), [{ id: "u1", name: "Ada", email: "ada@example.com" }]); // the permissions module's user_id is the picker's id
  assert.equal(calls[0]!.headers["X-Workspace-Id"], "ws-1");
  assert.equal(calls[0]!.headers["Content-Type"], undefined);
});

test("the error envelope becomes a RecordsError with a status and fields keyed by the field", async () => {
  const envelope = { error: { code: "validation_failed", message: "The contact is not valid", fields: { "values.email": "Email is not an email address", "values.phone": "Phone is not a phone number", values: "A contact needs a name", owner_id: "is not a member of this workspace" }, trace_id: "t1" } };
  const { client } = fake({ "PATCH /api/v1/objects/contact/records/c1": () => json(envelope, 422) });
  const e = await fails(() => client.update("contact", "c1", { email: "nope" }));
  assert.equal(e.status, 422);
  assert.deepEqual(e.fields, { email: "Email is not an email address", phone: "Phone is not a phone number", values: "A contact needs a name", owner_id: "is not a member of this workspace" });
  assert.equal(e.message, "Email is not an email address"); // the first field's message, as the memory client does

  const gone = fake({ "GET /api/v1/objects/contact/records/c9": () => json({ error: { code: "not_found", message: "Record not found" } }, 404) });
  const nf = await fails(() => gone.client.get("contact", "c9"));
  assert.deepEqual([nf.status, nf.message, nf.fields], [404, "Record not found", undefined]);

  const denied = fake({ "GET /api/v1/objects": () => json({ error: { code: "forbidden", message: "Workspace admins only" } }, 403) });
  assert.equal((await fails(() => denied.client.listObjects())).status, 403);

  const old = fake({ "GET /api/v1/members": () => json({ detail: "Sign in required" }, 401) }); // the older routes' shape
  const e401 = await fails(() => old.client.listUsers());
  assert.deepEqual([e401.status, e401.message], [401, "Sign in required"]);

  const offline = createApiClient(httpOf(fetchSend({ workspace: () => null, fetch: (async () => Promise.reject(new TypeError("fetch failed"))) as unknown as typeof fetch })));
  const e0 = await fails(() => offline.listUsers());
  assert.equal(e0.status, 0);
  assert.match(e0.message, /Could not reach the server/);
});

test("errors that are not the API's pass through untouched", () => {
  const bug = new TypeError("a bug");
  assert.equal(asRecordsError(bug), bug);
  const mine = new RecordsError(409, "x");
  assert.equal(asRecordsError(mine), mine);
  const api = asRecordsError(new ApiError(429, "Slow down", 7)) as RecordsError;
  assert.deepEqual([api.status, api.message], [429, "Slow down"]);
});

test("objects come back page by page with the primary fields, and their fields with the derived name and the system columns", async () => {
  const { calls, client } = fake({
    "GET /api/v1/objects/contact/fields": () => page([field("first_name", "text"), field("email", "email", { position: 2 }), field("legacy", "text", { position: 3, archived_at: "2026-01-01T00:00:00Z" })]),
    "GET /api/v1/objects/company/fields": () => page([field("name", "text", { rules: { required: true } })]),
    "GET /api/v1/objects?limit=200&cursor=next": () => page([company]),
    "GET /api/v1/objects?limit=200": () => page([contact], "next"),
  });
  const objects = await client.listObjects();
  assert.deepEqual(objects.map((o) => [o.key, o.primary_fields, o.icon]), [["contact", ["first_name", "last_name"], "user"], ["company", ["name"], "building"]]);
  assert.ok(!("archived_at" in objects[0]!));
  assert.equal(calls.length, 2);

  const fields = await client.listFields("contact");
  assert.deepEqual(fields.map((f) => f.key), ["display_name", "first_name", "email", "legacy", "owner_id", "created_at", "updated_at"]);
  const byKey = new Map(fields.map((f) => [f.key, f]));
  assert.equal(byKey.get("display_name")!.label, "Name");
  assert.equal(byKey.get("display_name")!.rules.read_only, true); // derived: it sorts and filters, it is not typed into
  assert.equal(byKey.get("legacy")!.archived, true);
  assert.equal(byKey.get("email")!.archived, false);
  assert.equal(byKey.get("owner_id")!.type, "user");
  assert.equal(byKey.get("owner_id")!.rules.read_only, undefined); // the owner can be changed
  assert.deepEqual([byKey.get("created_at")!.type, byKey.get("created_at")!.rules.read_only, byKey.get("updated_at")!.rules.read_only], ["datetime", true, true]);
  assert.ok(fields[4]!.position > fields[3]!.position && fields[5]!.position > fields[4]!.position); // after the fields, in order

  // a company has one primary field: that field is its name, so no derived column
  assert.deepEqual((await client.listFields("company")).map((f) => f.key), ["name", "owner_id", "created_at", "updated_at"]);
  const before = calls.length;
  await client.listFields("contact");
  assert.equal(calls.length, before); // read once
  assert.equal((await fails(() => client.listFields("nothing"))).status, 404);
});

test("a failed read is forgotten, so a retry asks again", async () => {
  let down = true;
  const { client, calls } = fake({ "GET /api/v1/tags": () => (down ? json({ error: { code: "x", message: "Try later" } }, 503) : page([{ id: "t1", name: "VIP", color: "purple" }])) });
  await fails(() => client.listTags());
  down = false;
  assert.deepEqual(await client.listTags(), [{ id: "t1", name: "VIP", color: "purple" }]);
  assert.equal(calls.length, 2);
});

test("a list query sends the sort as the API spells it, asks for tags, and counts the first page only", async () => {
  const { calls, client } = fake({
    "GET /api/v1/objects/contact/fields": () => page([field("lifecycle", "select")]),
    "GET /api/v1/objects?limit=200": () => page([contact]),
    "POST /api/v1/objects/contact/records/query": () =>
      page([row("c1", { tags: [{ id: "t1", name: "VIP", color: "purple" }, { id: "t2", name: "Odd", color: "#ff0000" }], values: { email: "a@example.com" } }), row("c2")], "cur2", { total: 120 }),
  });
  const first = await client.query("contact", { filter: { field: "lifecycle", op: "is", value: "lead" }, sort: [{ field: "created_at", dir: "desc" }, { field: "display_name", dir: "asc" }], q: "ada", limit: 100 });
  const posts = () => calls.filter((c) => c.method === "POST");
  assert.deepEqual(posts()[0]!.body, {
    filter: { field: "lifecycle", op: "is", value: "lead" },
    sort: ["-created_at", "display_name"],
    q: "ada",
    limit: 100,
    include: ["tags"],
    count: true,
  });
  assert.equal(first.total, 120);
  assert.equal(first.next_cursor, "cur2");
  assert.deepEqual(first.data[0]!.tags, [{ id: "t1", name: "VIP", color: "purple" }, { id: "t2", name: "Odd", color: "gray" }]); // colors the theme does not know are gray
  assert.deepEqual(first.data[1]!.tags, []);
  assert.equal(first.data[0]!.values.email, "a@example.com");

  await client.query("contact", { cursor: "cur2", q: "" });
  assert.deepEqual(posts()[1]!.body, { filter: {}, sort: [], limit: 50, cursor: "cur2", include: ["tags"], count: false });
});

test("sort specs round trip through the API's spelling", () => {
  assert.equal(sortParam({ field: "name", dir: "asc" }), "name");
  assert.equal(sortParam({ field: "created_at", dir: "desc" }), "-created_at");
  assert.deepEqual(parseSort("-created_at"), { field: "created_at", dir: "desc" });
  assert.deepEqual(parseSort("name"), { field: "name", dir: "asc" });
});

test("one record: read, create and change, with the tags back each time", async () => {
  const { calls, client } = fake({
    "GET /api/v1/objects/contact/records/c1?include=tags": () => row("c1", { tags: [{ id: "t1", name: "VIP", color: "blue" }] }),
    "POST /api/v1/objects/contact/records?include=tags": () => row("c2"),
    "PATCH /api/v1/objects/contact/records/c1?include=tags": () => row("c1", { values: { last_name: "Lovelace" }, tags: [] }),
    "POST /api/v1/records/c2/tags": () => ({ added: 1, removed: 0 }),
  });
  assert.equal((await client.get("contact", "c1")).tags[0]!.name, "VIP");

  await client.create("contact", { values: { first_name: "Ada" } });
  assert.deepEqual(calls[1]!.body, { values: { first_name: "Ada" } }); // no owner sent: the server decides, by the creator's role
  await client.create("contact", { values: { first_name: "Bo" }, owner_id: null });
  assert.equal(calls[2]!.body.owner_id, null);
  await client.create("contact", { values: { first_name: "Cy" }, owner_id: "u9" });
  assert.equal(calls[3]!.body.owner_id, "u9");

  const tagged = fake({
    "POST /api/v1/objects/contact/records?include=tags": () => row("c2"),
    "POST /api/v1/records/c2/tags": () => ({ added: 1, removed: 0 }),
    "GET /api/v1/objects/contact/records/c2?include=tags": () => row("c2", { tags: [{ id: "t1", name: "VIP", color: "blue" }] }),
  });
  const made = await tagged.client.create("contact", { values: { first_name: "Ada" }, tags: ["t1"] });
  assert.deepEqual(tagged.calls.map((c) => `${c.method} ${c.path}`), ["POST /api/v1/objects/contact/records?include=tags", "POST /api/v1/records/c2/tags", "GET /api/v1/objects/contact/records/c2?include=tags"]);
  assert.deepEqual(tagged.calls[1]!.body, { add: ["t1"] });
  assert.equal(made.tags[0]!.name, "VIP");

  await client.update("contact", "c1", { last_name: "Lovelace", email: null });
  assert.deepEqual(calls.at(-1)!.body, { values: { last_name: "Lovelace", email: null } }); // owner untouched: not sent
  await client.update("contact", "c1", { owner_id: null });
  assert.deepEqual(calls.at(-1)!.body, { values: {}, owner_id: null }); // sent as null: unassigns
  await client.update("contact", "c1", { owner_id: "u2", city: "Austin" });
  assert.deepEqual(calls.at(-1)!.body, { values: { city: "Austin" }, owner_id: "u2" });
});

test("bulk delete, restore and tags are one call up to a thousand ids and chunked beyond", async () => {
  const { calls, client } = fake({
    "POST /api/v1/objects/contact/records/delete": (c) => ({ deleted: c.body.ids.length }),
    "POST /api/v1/objects/contact/records/restore": (c) => ({ restored: c.body.ids.length }),
    "POST /api/v1/records/tags": () => ({ added: 1, removed: 0 }),
  });
  const ids = Array.from({ length: 2500 }, (_, i) => `id${i}`);
  await client.remove("contact", ids.slice(0, 3));
  assert.deepEqual(calls.map((c) => c.body.ids.length), [3]);
  await client.remove("contact", ids);
  assert.deepEqual(calls.slice(1).map((c) => c.body.ids.length), [1000, 1000, 500]);
  await client.restore("contact", ["a", "b"]);
  assert.deepEqual([calls.at(-1)!.path, calls.at(-1)!.body], ["/api/v1/objects/contact/records/restore", { ids: ["a", "b"] }]);
  await client.tag(["a", "b"], "t1");
  assert.deepEqual(calls.at(-1)!.body, { record_ids: ["a", "b"], add: ["t1"] });
  await client.untag(["a"], "t1");
  assert.deepEqual(calls.at(-1)!.body, { record_ids: ["a"], remove: ["t1"] });
  const failing = fake({ "POST /api/v1/objects/contact/records/delete": () => json({ error: { code: "not_found", message: "Record not found" } }, 404) });
  assert.equal((await fails(() => failing.client.remove("contact", ["x"]))).status, 404);
});

test("bulk update sends the values and the owner, null to unassign, and leaves the owner out when not changed", async () => {
  const { calls, client } = fake({ "POST /api/v1/objects/contact/records/update": (c) => ({ updated: c.body.ids.length }) });
  await client.updateMany("contact", ["a", "b"], { owner_id: null });
  assert.deepEqual([calls.at(-1)!.path, calls.at(-1)!.body], ["/api/v1/objects/contact/records/update", { ids: ["a", "b"], values: {}, owner_id: null }]);
  await client.updateMany("contact", ["a"], { city: "Austin" });
  assert.deepEqual(calls.at(-1)!.body, { ids: ["a"], values: { city: "Austin" } });
});

test("saved views map the filter, the sort and the owner both ways", async () => {
  const view = (extra: object = {}) => ({ id: "v1", object: "contact", name: "Leads", filter: { and: [{ field: "lifecycle", op: "is", value: "lead" }] }, columns: ["display_name", "tags"], sort: ["-created_at"], shared: true, owner_id: "u1", ...extra });
  const { calls, client } = fake({
    "GET /api/v1/views": () => page([view({ id: "v2", filter: {}, sort: [], shared: false, owner_id: null }), view()]),
    "POST /api/v1/views": () => view({ id: "v3" }),
    "PATCH /api/v1/views/v1": () => view(),
    "DELETE /api/v1/views/v1": () => undefined,
  });
  const views = await client.listViews("contact"); // the API sends the newest first (v2)
  assert.match(calls[0]!.path, /object=contact/);
  assert.deepEqual(views.map((v) => v.id), ["v1", "v2"]); // the tabs read oldest first
  assert.deepEqual(views[0], { id: "v1", object: "contact", name: "Leads", filter: { and: [{ field: "lifecycle", op: "is", value: "lead" }] }, columns: ["display_name", "tags"], sort: [{ field: "created_at", dir: "desc" }], shared: true, owner_id: "u1" });
  assert.deepEqual([views[1]!.filter, views[1]!.sort, views[1]!.owner_id], [null, [], null]); // no filter is null on the screens, {} on the server

  const input = { object: "contact", name: "Leads", filter: null, columns: ["display_name"], sort: [{ field: "created_at", dir: "desc" as const }], shared: false };
  await client.saveView(input);
  assert.deepEqual(calls[1]!.body, { object: "contact", name: "Leads", filter: {}, columns: ["display_name"], sort: ["-created_at"], shared: false });
  await client.saveView({ ...input, id: "v1" });
  assert.deepEqual([calls[2]!.method, calls[2]!.path], ["PATCH", "/api/v1/views/v1"]);
  assert.equal("object" in calls[2]!.body, false); // a view never changes its object
  await client.deleteView("v1");
  assert.deepEqual([calls[3]!.method, calls[3]!.path], ["DELETE", "/api/v1/views/v1"]);

  const readonly = fake({ "PATCH /api/v1/views/v9": () => json({ error: { code: "forbidden", message: "Only the owner or a workspace admin can change a shared view" } }, 403) });
  assert.equal((await fails(() => readonly.client.saveView({ ...input, id: "v9" }))).status, 403);
});

test("tags, people and link types", async () => {
  const { client } = fake({
    "GET /api/v1/tags": () => page([{ id: "t1", name: "VIP", color: "purple", count: 4 }, { id: "t2", name: "None", color: null }]),
    "GET /api/v1/members": () => page([{ user_id: "u1", name: "Ada", email: "a@example.com" }]),
    "GET /api/v1/association-types": () => page([{ id: "a1", from_object: "contact", to_object: "company", label: "works at", inverse_label: "employs", cardinality: "many_to_many" }]),
  });
  assert.deepEqual(await client.listTags(), [{ id: "t1", name: "VIP", color: "purple" }, { id: "t2", name: "None", color: "gray" }]);
  assert.deepEqual(await client.listLinkTypes(), [{ from: "contact", to: "company", label: "works at", inverse_label: "employs" }]);
  assert.equal(colorName("teal"), "teal");
  assert.equal(colorName(null), "gray");
});

test("the timeline turns the engine's events into lines, and leaves out the ones the screen has no line for", async () => {
  const types = [{ id: "a1", from_object: "contact", to_object: "company", label: "works at", inverse_label: "employs" }];
  const tags = new Map<string, Tag>([["t1", { id: "t1", name: "VIP", color: "purple" }]]);
  const ev = (type: string, data: object, actor: object = { type: "user", id: "u1" }, id: number = 1): ApiEvent => ({ id, type, occurred_at: "2026-10-17T10:00:00Z", actor: actor as ApiEvent["actor"], data: data as ApiEvent["data"] });
  const at = (e: ApiEvent, id = "c1") => toTimelineEvent(e, id, types, tags);

  assert.deepEqual(at(ev("record.created", {}, { type: "system", id: null }, 7)), { id: "7", record_id: "c1", at: "2026-10-17T10:00:00Z", actor_id: null, type: "created" });
  assert.deepEqual(at(ev("record.updated", { changes: { lifecycle: { old: "lead", new: "customer" }, email: { old: null, new: "a@example.com" }, owner_id: { old: "u1", new: null } } }))!.changes, [
    { field: "lifecycle", from: "lead", to: "customer" },
    { field: "email", from: null, to: "a@example.com" },
    { field: "owner_id", from: "u1", to: null },
  ]);
  assert.equal(at(ev("record.updated", { changes: {} })), null);
  const tagged = at(ev("tag.added", { record_id: "c1", object: "contact", tag_id: "t1", name: "VIP" }))!;
  assert.deepEqual([tagged.type, tagged.tag, tagged.actor_id], ["tagged", { id: "t1", name: "VIP", color: "purple" }, "u1"]);
  assert.deepEqual(at(ev("tag.removed", { record_id: "c1", object: "contact", tag_id: "t9", name: "Gone" }))!.tag, { id: "t9", name: "Gone", color: "gray" });

  const link = { id: "l1", type_id: "a1", from_record_id: "c1", to_record_id: "co1", label: "works at", inverse_label: "employs" };
  assert.deepEqual(at(ev("association.created", link))!.link, { label: "works at", object: "company", id: "co1" }); // from the contact's side
  const seen = at(ev("association.deleted", link), "co1")!; // from the company's side: the other end is the contact
  assert.deepEqual([seen.type, seen.link], ["unlinked", { label: "employs", object: "contact", id: "c1" }]);
  assert.equal(at(ev("association.created", { ...link, type_id: "gone" })), null);
  for (const type of ["record.deleted", "record.restored", "tag.merged", "webhook.test"]) assert.equal(at(ev(type, {})), null, type);

  const { client } = fake({
    "GET /api/v1/records/c1/timeline": () => page([ev("record.deleted", {}), ev("record.created", {}, undefined, 2)], "next"),
    "GET /api/v1/association-types": () => page(types),
    "GET /api/v1/tags": () => page([]),
  });
  const first = await client.timeline("c1");
  assert.deepEqual(first.data.map((e) => e.type), ["created"]);
  assert.equal(first.next_cursor, "next");
});

// ---- day filters on datetime fields ----

const typeOf = (path: string) => ({ created_at: "datetime", "company.updated_at": "datetime", joined: "date", lifecycle: "select" })[path] as never;
const ZONES = { "America/Chicago": ["2026-10-17T05:00:00.000Z", "2026-10-18T05:00:00.000Z"], "Asia/Calcutta": ["2026-10-16T18:30:00.000Z", "2026-10-17T18:30:00.000Z"], UTC: ["2026-10-17T00:00:00.000Z", "2026-10-18T00:00:00.000Z"] } as const;

test("a day on a datetime field is that day where the viewer is, in any zone", () => {
  for (const [zone, [start, next]] of Object.entries(ZONES)) {
    process.env.TZ = zone;
    const c = (op: string, value: unknown) => ({ field: "created_at", op, value }) as never;
    const day = "2026-10-17";
    assert.deepEqual(convertFilter(c("is", day), typeOf), { and: [{ field: "created_at", op: "gte", value: start }, { field: "created_at", op: "lt", value: next }] }, zone);
    assert.deepEqual(convertFilter(c("is_not", day), typeOf), { not: { and: [{ field: "created_at", op: "gte", value: start }, { field: "created_at", op: "lt", value: next }] } }, zone);
    assert.deepEqual(convertFilter(c("gt", day), typeOf), { field: "created_at", op: "gte", value: next }, zone); // after the day: from the next one
    assert.deepEqual(convertFilter(c("gte", day), typeOf), { field: "created_at", op: "gte", value: start }, zone);
    assert.deepEqual(convertFilter(c("lt", day), typeOf), { field: "created_at", op: "lt", value: start }, zone);
    assert.deepEqual(convertFilter(c("lte", day), typeOf), { field: "created_at", op: "lt", value: next }, zone); // through the end of the day
    assert.deepEqual(convertFilter(c("between", [day, day]), typeOf), { and: [{ field: "created_at", op: "gte", value: start }, { field: "created_at", op: "lt", value: next }] }, zone);
  }
});

test("the day after a clock change is 23 or 25 hours long", () => {
  process.env.TZ = "America/Chicago"; // the clocks go back on 2026-11-01
  const out = convertFilter({ field: "created_at", op: "is", value: "2026-11-01" }, typeOf) as { and: { value: string }[] };
  assert.deepEqual(out.and.map((c) => c.value), ["2026-11-01T05:00:00.000Z", "2026-11-02T06:00:00.000Z"]);
});

test("everything else in a filter goes through as it is", () => {
  process.env.TZ = "America/Chicago";
  const same = (f: Filter) => assert.deepEqual(convertFilter(f, typeOf), f);
  same({ field: "created_at", op: "within_last", value: { days: 30 } }); // a span from now, the same in every zone
  same({ field: "created_at", op: "older_than", value: { days: 30 } });
  same({ field: "created_at", op: "is_empty" });
  same({ field: "created_at", op: "gt", value: "2026-10-17T10:00:00Z" }); // already an instant
  same({ field: "created_at", op: "between", value: ["2026-10-01", null] }); // unfinished
  same({ field: "joined", op: "is", value: "2026-10-17" }); // a date is a calendar day, with no zone
  same({ field: "lifecycle", op: "is", value: "lead" });
  same({ field: "mystery", op: "is", value: "2026-10-17" });
  same({ tag: "t1" });
});

test("groups and paths convert inside, and the company's own datetime fields too", () => {
  process.env.TZ = "UTC";
  const f: Filter = { and: [{ field: "lifecycle", op: "is", value: "customer" }, { or: [{ tag: "t1" }, { field: "company.updated_at", op: "gte", value: "2026-10-01" }] }] };
  assert.deepEqual(convertFilter(f, typeOf), { and: [{ field: "lifecycle", op: "is", value: "customer" }, { or: [{ tag: "t1" }, { field: "company.updated_at", op: "gte", value: "2026-10-01T00:00:00.000Z" }] }] });
});

test("a query converts day filters using the fields of the object and of the one it reaches through", async () => {
  process.env.TZ = "America/Chicago";
  const { calls, client } = fake({
    "POST /api/v1/objects/contact/records/query": () => page([]),
    "GET /api/v1/objects/contact/fields": () => page([field("lifecycle", "select")]),
    "GET /api/v1/objects/company/fields": () => page([field("name", "text")]),
    "GET /api/v1/objects?limit=200": () => page([contact, company]),
  });
  await client.query("contact", { filter: { and: [{ field: "created_at", op: "gte", value: "2026-10-01" }, { field: "company.created_at", op: "lt", value: "2026-10-05" }, { field: "lifecycle", op: "is", value: "lead" }] } });
  const body = calls.find((c) => c.method === "POST")!.body;
  assert.deepEqual(body.filter, { and: [{ field: "created_at", op: "gte", value: "2026-10-01T05:00:00.000Z" }, { field: "company.created_at", op: "lt", value: "2026-10-05T05:00:00.000Z" }, { field: "lifecycle", op: "is", value: "lead" }] });
});

test("the query string helper leaves out what is not there", () => {
  assert.equal(queryString({}), "");
  assert.equal(queryString({ a: 1, b: undefined, c: null, d: "", e: "x y", f: ["p", "q"], g: false }), "?a=1&e=x+y&f=p%2Cq&g=false");
});

// ---- stages: a deal's stage is a pipeline stage, and the pipelines say which ----

const pipeline = (id: string, name: string, object = "deal", archived_at: string | null = null): ApiPipeline => ({
  id,
  object,
  name,
  archived_at,
  stages: [
    { id: `${id}-lead`, name: "Lead", kind: "open", probability: 10, color: "gray" },
    { id: `${id}-proposal`, name: "Proposal", kind: "open", probability: 50, color: "amber" },
    { id: `${id}-won`, name: "Won", kind: "won", probability: 100, color: "green" },
    { id: `${id}-lost`, name: "Lost", kind: "lost", probability: 0, color: "#123456" },
  ],
});

test("the stages of the pipelines are the choices of a stage field", () => {
  const one = stageChoices([pipeline("p1", "Sales")], "deal");
  assert.deepEqual(one.choices.map((c) => [c.label, c.color, c.probability]), [["Lead", "gray", 0.1], ["Proposal", "amber", 0.5], ["Won", "green", 1], ["Lost", "gray", 0]]);
  assert.equal(one.first, "p1-lead"); // a new deal starts in the first open stage
  // with several live pipelines the choices say which; an archived one takes no new deals and says so
  const many = stageChoices([pipeline("p1", "Sales"), pipeline("p3", "Old", "deal", "2026-01-01T00:00:00Z"), pipeline("p2", "Renewals")], "deal");
  assert.deepEqual(many.choices.slice(0, 2).map((c) => c.label), ["Sales: Lead", "Sales: Proposal"]);
  assert.equal(many.choices.at(-1)!.label, "Old (archived): Lost");
  assert.equal(many.choices.length, 12);
  assert.equal(many.first, "p1-lead");
  assert.deepEqual(stageChoices([pipeline("p1", "Sales")], "contact"), { choices: [], first: undefined });
  assert.equal(stageChoices([pipeline("p3", "Old", "deal", "2026-01-01T00:00:00Z")], "deal").first, undefined);
});

test("a deal's stage field comes with the stages, a default and no way to clear it", async () => {
  const deal = { id: "o3", key: "deal", singular: "Deal", plural: "Deals", icon: "handshake", is_system: true, primary_fields: ["name"], archived_at: null };
  const { calls, client } = fake({
    "GET /api/v1/objects/deal/fields": () => page([field("name", "text", { rules: { required: true } }), field("stage", "stage"), field("lost_reason", "select", { options: { choices: [{ id: "price", label: "Price" }] } })]),
    "GET /api/v1/objects?limit=200": () => page([deal]),
    "GET /api/v1/pipelines?archived=true": () => page([]),
    "GET /api/v1/pipelines": () => page([pipeline("p1", "Sales")]),
  });
  const fields = await client.listFields("deal");
  const stage = fields.find((f) => f.key === "stage")!;
  assert.deepEqual(stage.options.choices!.map((c) => c.label), ["Lead", "Proposal", "Won", "Lost"]);
  assert.equal(stage.options.default, "p1-lead");
  assert.equal(stage.rules.required, true);
  assert.deepEqual(fields.find((f) => f.key === "lost_reason")!.options.choices, [{ id: "price", label: "Price" }]); // other fields are left alone
  await client.listFields("deal");
  assert.equal(calls.filter((c) => c.path.startsWith("/api/v1/pipelines")).length, 2); // live and archived, once
});

test("an object without a stage field never asks for pipelines", async () => {
  const { calls, client } = fake({
    "GET /api/v1/objects/contact/fields": () => page([field("first_name", "text")]),
    "GET /api/v1/objects?limit=200": () => page([contact]),
  });
  await client.listFields("contact");
  assert.ok(!calls.some((c) => c.path.startsWith("/api/v1/pipelines")));
});

test("a move an exit rule refuses comes back as the messages of what is missing, keyed by field", async () => {
  const refused = { error: { code: "validation_failed", message: "The deal cannot leave Proposal yet", fields: { "values.close_date": "Close date is required to leave Proposal", "values.amount": "Amount is required to leave Proposal" } } };
  const { calls, client } = fake({ "PATCH /api/v1/objects/deal/records/d1": () => json(refused, 422) });
  const e = await fails(() => client.update("deal", "d1", { stage: "p1-won" }));
  assert.equal(e.status, 422);
  assert.deepEqual(e.fields, { close_date: "Close date is required to leave Proposal", amount: "Amount is required to leave Proposal" });
  assert.deepEqual(calls[0]!.body, { values: { stage: "p1-won" } });
  const lost = { error: { code: "validation_failed", message: "The deal is not valid", fields: { "values.lost_reason": "Lost reason is required to move a deal to Lost" } } };
  const again = fake({ "PATCH /api/v1/objects/deal/records/d1": () => json(lost, 422) });
  assert.deepEqual((await fails(() => again.client.update("deal", "d1", { stage: "p1-lost" }))).fields, { lost_reason: "Lost reason is required to move a deal to Lost" });
});

test("people the role may not see leave the owner picker empty, anything else still fails", async () => {
  const denied = fake({ "GET /api/v1/members": () => json({ error: { code: "forbidden", message: "Your role does not allow this" } }, 403) });
  assert.deepEqual(await denied.client.listUsers(), []);
  const down = fake({ "GET /api/v1/members": () => json({ error: { code: "x", message: "Try later" } }, 503) });
  assert.equal((await fails(() => down.client.listUsers())).status, 503);
});
