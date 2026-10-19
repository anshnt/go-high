import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchSend, httpOf } from "../src/lib/http.ts";
import { createPipelineApiClient } from "../src/pipeline/apiClient.ts";
import { createMemoryPipelineClient } from "../src/pipeline/memoryClient.ts";
import { RecordsError } from "../src/records/errors.ts";
import { seedDataset } from "../src/records/seed.ts";
import { createMemoryClient } from "../src/records/memoryClient.ts";
import { makeClient, NOW } from "./recordsFixture.ts";

// ---- over the API ----

type Call = { method: string; path: string; body: any };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

function fake(routes: Record<string, (c: Call) => unknown>) {
  const calls: Call[] = [];
  const fetchImpl = (async (path: string, init: RequestInit) => {
    const call: Call = { method: init.method ?? "GET", path, body: init.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const key = Object.keys(routes).find((k) => `${call.method} ${call.path}`.startsWith(k));
    if (!key) return json({ error: { code: "not_found", message: `no route ${call.method} ${call.path}` } }, 404);
    const out = routes[key]!(call);
    return out instanceof Response ? out : out === undefined ? new Response(null, { status: 204 }) : json(out);
  }) as unknown as typeof fetch;
  return { calls, client: createPipelineApiClient(httpOf(fetchSend({ workspace: () => "ws-1", fetch: fetchImpl }))) };
}

const apiStage = (id: string, extra: object = {}) => ({ id, pipeline_id: "p1", name: id, position: 0, kind: "open", probability: 10, rotting_days: null, exit_rules: {}, color: null, created_at: "2026-10-01T00:00:00Z", ...extra });
const apiCard = (id: string, extra: object = {}) => ({ id, display_name: id, amount: null, close_date: null, owner_id: null, board_position: "0", stage_id: "s1", stage_entered_at: "2026-10-01T00:00:00Z", days_in_stage: 3, rotting: false, last_activity_at: null, values: {}, ...extra });

test("the board is one call with a page size, and a column's next page names its stage and cursor", async () => {
  const { calls, client } = fake({
    "GET /api/v1/pipelines/p1/board": (c) =>
      c.path.includes("stage=")
        ? { id: "p1", name: "Sales", stages: [{ ...apiStage("s1"), count: 3, amount: {}, weighted: {}, deals: [apiCard("d9")], next_cursor: null }] }
        : { id: "p1", name: "Sales", stages: [{ ...apiStage("s1"), count: 3, amount: { USD: 500 }, weighted: { USD: 50 }, deals: [apiCard("d1", { amount: { amount: 500, currency: "USD" }, values: { amount: { amount: 500, currency: "USD" } } })], next_cursor: "c1" }] },
  });
  const board = await client.board("p1", 10);
  assert.equal(calls[0]!.path, "/api/v1/pipelines/p1/board?limit=10");
  const s1 = board.stages[0]!;
  assert.deepEqual([s1.count, s1.amount, s1.next_cursor, s1.deals[0]!.amount], [3, { USD: 500 }, "c1", { amount: 500, currency: "USD" }]);
  assert.equal("deals" in { ...s1 } && s1.exit_rules !== undefined, true);
  const more = await client.column("p1", "s1", "c1", 10);
  assert.equal(calls[1]!.path, "/api/v1/pipelines/p1/board?limit=10&stage=s1&cursor=c1");
  assert.deepEqual([more.deals.map((d) => d.id), more.next_cursor], [["d9"], null]);
});

test("a move sends the stage and its neighbours, and a refusal comes back with the fields that are missing", async () => {
  const { calls, client } = fake({
    "POST /api/v1/deals/d1/move": (c) =>
      c.body.stage_id === "won" && !c.body.lost_reason
        ? json({ error: { code: "validation_failed", message: "The deal cannot leave Negotiation yet", fields: { "values.close_date": "Close date is required to leave Negotiation", "contact.email": "Email is required to leave Negotiation" } } }, 422)
        : apiCard("d1", { stage_id: c.body.stage_id }),
  });
  const ok = await client.move("d1", { stage_id: "s2", after_id: "a", before_id: null });
  assert.deepEqual(calls[0]!.body, { stage_id: "s2", after_id: "a", before_id: null });
  assert.equal(ok.stage_id, "s2");
  await assert.rejects(client.move("d1", { stage_id: "won" }), (e: unknown) => e instanceof RecordsError && e.status === 422 && e.fields?.close_date === "Close date is required to leave Negotiation" && e.fields["contact.email"] !== undefined);
});

test("layouts are the caller's own, saved with PUT, and pipelines and stages are plain calls", async () => {
  const { calls, client } = fake({
    "GET /api/v1/pipelines/p1/layout": () => ({ pipeline_id: "p1", collapsed: ["s2"], card_fields: [], updated_at: null }),
    "PUT /api/v1/pipelines/p1/layout": (c) => ({ pipeline_id: "p1", ...c.body, updated_at: "2026-10-01T00:00:00Z" }),
    "GET /api/v1/pipelines/p1/forecast": () => ({ pipeline_id: "p1", period: "quarter", periods: [] }),
    "GET /api/v1/pipelines?archived=true": () => ({ data: [{ id: "old", name: "Old", position: 1, archived_at: "2026-09-01T00:00:00Z", stages: [apiStage("x")] }], next_cursor: null }),
    "GET /api/v1/pipelines": () => ({ data: [{ id: "p1", name: "Sales", position: 0, archived_at: null, stages: [apiStage("s1")] }], next_cursor: null }),
    "PATCH /api/v1/pipelines/p1/stages/s1": (c) => apiStage("s1", c.body),
    "POST /api/v1/pipelines/p1/stages/reorder": (c) => ({ id: "p1", name: "Sales", position: 0, archived_at: null, stages: c.body.stage_ids.map((id: string) => apiStage(id)) }),
    "DELETE /api/v1/pipelines/p1/stages/s1": () => undefined,
  });
  assert.deepEqual(await client.layout("p1"), { collapsed: ["s2"], card_fields: ["amount", "close_date", "owner_id"] }, "an empty list of fields is the default one");
  assert.deepEqual(await client.saveLayout("p1", { collapsed: ["s1"], card_fields: ["amount"] }), { collapsed: ["s1"], card_fields: ["amount"] });
  assert.equal(calls[1]!.method, "PUT");
  await client.forecast("p1", "quarter");
  assert.equal(calls[2]!.path, "/api/v1/pipelines/p1/forecast?period=quarter");
  assert.equal((await client.list()).length, 1);
  assert.deepEqual((await client.list(true)).map((p) => [p.id, p.archived_at !== null]), [["old", true]]);
  const patched = await client.updateStage("p1", "s1", { probability: 40, exit_rules: { and: [{ field: "amount", op: "is_not_empty" }] } });
  assert.equal(patched.probability, 40);
  assert.deepEqual(calls[calls.length - 1]!.body, { probability: 40, exit_rules: { and: [{ field: "amount", op: "is_not_empty" }] } });
  assert.deepEqual((await client.reorderStages("p1", ["b", "a"])).map((s) => s.id), ["b", "a"], "one call for the whole order");
  assert.equal(calls.filter((c) => c.path.endsWith("/stages/reorder")).length, 1);
  await client.deleteStage("p1", "s1");
  assert.equal(calls[calls.length - 1]!.method, "DELETE");
});

// ---- the demo's pipelines over its records ----

const fresh = () => {
  const records = makeClient();
  return { records, pipelines: createMemoryPipelineClient(records, { now: () => NOW }) };
};
const refused = (status: number, check?: (e: RecordsError) => boolean) => (e: unknown) => e instanceof RecordsError && e.status === status && (check?.(e) ?? true);

test("the demo board has the deals of each stage with counts and sums by currency", async () => {
  const { pipelines } = fresh();
  const [sales] = await pipelines.list();
  assert.equal(sales!.name, "Sales");
  const board = await pipelines.board(sales!.id);
  const by = Object.fromEntries(board.stages.map((s) => [s.id, s]));
  assert.deepEqual(board.stages.map((s) => s.name), ["Lead", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]);
  assert.deepEqual([by.new!.count, by.proposal!.count, by.negotiation!.count, by.won!.count, by.lost!.count], [1, 1, 1, 1, 0]);
  assert.deepEqual(by.negotiation!.amount, { EUR: 800_000 });
  assert.deepEqual(by.negotiation!.weighted, { EUR: 640_000 }, "80%");
  assert.deepEqual(by.won!.amount, { USD: 1_200_000 });
  assert.equal(by.proposal!.deals[0]!.display_name, "Alder Labs add-on");
});

test("a card is paged by cursor, top first, and a drop between two cards lands between them", async () => {
  const records = makeClient(seedDataset({ anchor: NOW }));
  const pipelines = createMemoryPipelineClient(records, { now: () => NOW });
  const board = await pipelines.board("pl_sales", 5);
  const lead = board.stages[0]!;
  assert.equal(lead.deals.length, 5);
  assert.ok(lead.count > 5 && lead.next_cursor);
  const seen = new Set(lead.deals.map((d) => d.id));
  let cursor = lead.next_cursor;
  while (cursor) {
    const page = await pipelines.column("pl_sales", "new", cursor, 5);
    for (const d of page.deals) assert.ok(!seen.has(d.id), "no card twice");
    page.deals.forEach((d) => seen.add(d.id));
    cursor = page.next_cursor;
  }
  assert.equal(seen.size, lead.count);
  // drop a Qualified deal that can leave (it has a close date) between the first two Proposal cards
  const prop = board.stages[2]!.deals;
  const mover = (await pipelines.board("pl_sales", 100)).stages[1]!.deals.find((d) => d.close_date)!;
  const moved = await pipelines.move(mover.id, { stage_id: "proposal", after_id: prop[0]!.id, before_id: prop[1]!.id });
  const order = (await pipelines.board("pl_sales", 100)).stages[2]!.deals.map((d) => d.id);
  assert.deepEqual(order.slice(0, 3), [prop[0]!.id, mover.id, prop[1]!.id]);
  assert.equal(moved.days_in_stage, 0);
  await assert.rejects(pipelines.move(mover.id, { stage_id: "proposal", after_id: "dl_nope" }), refused(422, (e) => !!e.fields?.after_id));
  await assert.rejects(pipelines.move(mover.id, { stage_id: "proposal", after_id: prop[1]!.id, before_id: prop[0]!.id }), refused(409));
});

test("leaving a stage needs what its exit rules ask for, and Won needs an amount and a close date", async () => {
  const { records, pipelines } = fresh();
  // dl_4 is a Lead with an amount and no close date
  await assert.rejects(pipelines.move("dl_4", { stage_id: "won" }), refused(422, (e) => !!e.fields?.close_date && !e.fields.amount));
  assert.equal((await records.get("deal", "dl_4")).values.stage, "new", "nothing changed");
  await records.update("deal", "dl_4", { close_date: "2026-11-30" });
  const won = await pipelines.move("dl_4", { stage_id: "won" });
  assert.equal(won.stage_id, "won");
  assert.equal((await records.get("deal", "dl_4")).values.stage, "won", "the record the Deals list shows moved too");
  // a rule an admin adds in settings: Proposal needs a contact before a deal leaves it
  await pipelines.updateStage("pl_sales", "proposal", { exit_rules: { and: [{ field: "amount", op: "gt", value: { amount: 999_999_999, currency: "USD" } }] } });
  await assert.rejects(pipelines.move("dl_2", { stage_id: "negotiation" }), refused(422, (e) => /to leave Proposal/.test(e.fields?.amount ?? "")));
});

test("a lost stage needs a reason, which is kept, and leaving it clears the reason", async () => {
  const { records, pipelines } = fresh();
  await assert.rejects(pipelines.move("dl_2", { stage_id: "lost" }), refused(422, (e) => !!e.fields?.lost_reason));
  await pipelines.move("dl_2", { stage_id: "lost", lost_reason: "price", lost_note: "Went with a cheaper plan" });
  const row = await records.get("deal", "dl_2");
  assert.deepEqual([row.values.stage, row.values.lost_reason, row.values.lost_note], ["lost", "price", "Went with a cheaper plan"]);
  await pipelines.move("dl_2", { stage_id: "proposal" });
  const back = await records.get("deal", "dl_2");
  assert.deepEqual([back.values.stage, back.values.lost_reason, back.values.lost_note], ["proposal", undefined, undefined]);
});

test("the demo forecast is made of the deals' close dates, and moving a deal to Won moves its money to Won", async () => {
  const { pipelines } = fresh();
  const before = await pipelines.forecast("pl_sales", "month");
  assert.deepEqual(before.periods.map((p) => p.label), ["2026-09", "2026-10", "2026-11"]);
  assert.deepEqual(before.periods[2]!.pipeline, { USD: 300_000 });
  await pipelines.move("dl_2", { stage_id: "won" });
  const after = await pipelines.forecast("pl_sales", "month");
  assert.deepEqual(after.periods[2]!.won, { USD: 300_000 });
  assert.deepEqual(after.periods[2]!.pipeline, {});
});

test("layouts keep their own collapsed stages, and unknown stages are dropped", async () => {
  const { pipelines } = fresh();
  assert.deepEqual(await pipelines.layout("pl_sales"), { collapsed: [], card_fields: ["amount", "close_date", "owner_id"] });
  const saved = await pipelines.saveLayout("pl_sales", { collapsed: ["lost", "nope", "lost"], card_fields: ["amount", "source"] });
  assert.deepEqual(saved, { collapsed: ["lost"], card_fields: ["amount", "source"] });
  assert.deepEqual(await pipelines.layout("pl_sales"), saved);
});

test("settings: a stage made here takes deals, an order is one call, and a stage with deals cannot go", async () => {
  const { records, pipelines } = fresh();
  const stage = await pipelines.createStage("pl_sales", { name: "Contract", kind: "open", probability: 90 });
  const moved = await pipelines.move("dl_3", { stage_id: stage.id });
  assert.equal(moved.stage_id, stage.id);
  assert.equal((await records.get("deal", "dl_3")).values.stage, stage.id, "the stage field accepts the new stage");
  await assert.rejects(pipelines.deleteStage("pl_sales", stage.id), refused(409, (e) => /Move the 1 deal in Contract/.test(e.message)));
  const ids = (await pipelines.list())[0]!.stages.map((s) => s.id);
  const reordered = await pipelines.reorderStages("pl_sales", [...ids].reverse());
  assert.deepEqual(reordered.map((s) => s.id), [...ids].reverse());
  assert.deepEqual(reordered.map((s) => s.position), reordered.map((_, i) => i));
  await assert.rejects(pipelines.reorderStages("pl_sales", ids.slice(1)), refused(422));
  // won and lost stages have a fixed probability, and an open one that becomes won gets it
  await assert.rejects(pipelines.updateStage("pl_sales", "won", { probability: 70 }), refused(422, (e) => !!e.fields?.probability));
  const closed = await pipelines.updateStage("pl_sales", stage.id, { kind: "won" });
  assert.equal(closed.probability, 100);
  await pipelines.updateStage("pl_sales", "new", { probability: 15, rotting_days: null, name: "Inbound" });
  const lead = (await pipelines.board("pl_sales")).stages.find((s) => s.id === "new")!;
  assert.deepEqual([lead.name, lead.probability, lead.rotting_days], ["Inbound", 15, null]);
});

test("settings: pipelines are created, renamed and archived, and the last live one stays", async () => {
  const { pipelines } = fresh();
  const made = await pipelines.createPipeline("Partners");
  assert.equal(made.stages.length, 6, "starts with the Sales stages");
  assert.equal(new Set(made.stages.map((s) => s.id)).size, 6);
  await assert.rejects(pipelines.createPipeline("   "), refused(422, (e) => !!e.fields?.name));
  assert.equal((await pipelines.renamePipeline(made.id, "Channel")).name, "Channel");
  assert.deepEqual((await pipelines.list()).map((p) => p.name), ["Sales", "Channel"]);
  await pipelines.archivePipeline(made.id, true);
  assert.deepEqual((await pipelines.list(true)).map((p) => p.name), ["Channel"]);
  await assert.rejects(pipelines.archivePipeline("pl_sales", true), refused(409));
  await pipelines.archivePipeline(made.id, false);
  assert.equal((await pipelines.list()).length, 2);
  await assert.rejects(pipelines.board("nope"), refused(404));
});

test("a deal made later lands on top of its stage, and the demo's own data shows rotting and mine", async () => {
  const records = createMemoryClient({ dataset: seedDataset({ anchor: NOW, mine: "demo-user" }), now: () => NOW });
  const pipelines = createMemoryPipelineClient(records, { now: () => NOW });
  const first = await pipelines.board("pl_sales", 100);
  const made = await records.create("deal", { values: { name: "Fresh deal", amount: { amount: 5_000, currency: "USD" }, stage: "new" } });
  const lead = (await pipelines.board("pl_sales", 100)).stages[0]!;
  assert.equal(lead.deals[0]!.id, made.id);
  assert.equal(lead.count, first.stages[0]!.count + 1);
  const open = first.stages.slice(0, 4).flatMap((s) => s.deals);
  const rotting = open.filter((d) => d.rotting).length;
  assert.ok(rotting > 0 && rotting < open.length / 2, `some deals rot, most do not (${rotting} of ${open.length})`);
  assert.ok(first.stages.flatMap((s) => s.deals).some((d) => d.owner_id === "demo-user"), "the demo visitor owns deals");
  assert.ok(first.stages.flatMap((s) => s.deals).every((d) => d.last_activity_at && Date.parse(d.last_activity_at) >= Date.parse(d.stage_entered_at)), "activity is never older than the stage change");
});
