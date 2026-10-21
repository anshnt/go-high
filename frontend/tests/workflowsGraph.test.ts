// The workflow builder edits the graph as plain data. These checks keep every edit in the shape the server expects:
// edges named as it names them, nothing orphaned, a removed step's followers kept, and its errors put on the right node.
import assert from "node:assert/strict";
import { test } from "node:test";
import { addGoal, blank, dropped, exits, insert, move, newId, offsetText, order, place, prune, reachable, remove, removalImpact, same, secondsText, slotsTo, tree, update, type Graph } from "../src/workflows/graph.ts";

const graph = (): Graph => ({
  trigger: { event: "form.submitted", object: "contact", filter: {}, data: {} },
  start: "hello",
  nodes: {
    hello: { type: "action", action: "task.create", config: { title: "Call" }, next: "pause" },
    pause: { type: "wait", config: { duration: { days: 2 } }, next: "check" },
    check: { type: "condition", config: { filter: { tag: "vip" } }, branches: { yes: "tag", no: null } },
    tag: { type: "action", action: "tag.add", config: { tag: "cold" }, next: null },
    won: { type: "goal", config: { filter: { tag: "customer" }, otherwise: "continue" }, next: null },
  },
});

test("exits follow the server: conditions yes/no, splits by path, event waits event/timeout", () => {
  assert.deepEqual(exits({ type: "condition", config: {} }), { kind: "branches", names: ["yes", "no"] });
  assert.deepEqual(exits({ type: "split", config: { paths: [{ name: "a" }, { name: "b" }] } }), { kind: "branches", names: ["a", "b"] });
  assert.deepEqual(exits({ type: "wait", config: { event: { event: "form.submitted" } } }), { kind: "branches", names: ["event", "timeout"] });
  assert.deepEqual(exits({ type: "wait", config: { duration: { days: 1 } } }), { kind: "next" });
  assert.deepEqual(exits({ type: "end", config: {} }), { kind: "none" });
});

test("inserting puts the new step on the edge and what was there after it", () => {
  const g = insert(graph(), { from: "hello" }, "note", { type: "action", action: "notify.user", config: {} });
  assert.equal(g.nodes.hello!.next, "note");
  assert.equal(g.nodes.note!.next, "pause");
  const first = insert(graph(), { from: "start" }, "first", { type: "wait", config: { duration: { hours: 1 } } });
  assert.equal(first.start, "first");
  assert.equal(first.nodes.first!.next, "hello");
  const branchy = insert(graph(), { from: "check", branch: "no" }, "ab", { type: "split", config: { paths: [{ name: "a", percent: 50 }, { name: "b", percent: 50 }] } });
  assert.deepEqual(branchy.nodes.ab!.branches, { a: null, b: null });
  assert.equal(branchy.nodes.check!.branches!.no, "ab");
  const before = insert(graph(), { from: "pause" }, "fork", { type: "condition", config: { filter: {} } });
  assert.deepEqual(before.nodes.fork!.branches, { yes: "check", no: null }, "what followed goes down the first branch");
  assert.equal(before.nodes.fork!.next, undefined);
});

test("an end step drops what followed, and so does nothing else", () => {
  const g = insert(graph(), { from: "pause" }, "stop", { type: "end", config: {} });
  assert.deepEqual(Object.keys(g.nodes).sort(), ["hello", "pause", "stop", "won"]);
  assert.equal("next" in g.nodes.stop!, false);
});

test("removing a step reconnects what led to it; a branching step keeps its first branch", () => {
  const g = remove(graph(), "pause");
  assert.equal(g.nodes.hello!.next, "check");
  const c = remove(graph(), "check");
  assert.equal(c.nodes.pause!.next, "tag");
  assert.deepEqual(removalImpact(graph(), "check"), ["check"]);
  const s = insert(graph(), { from: "check", branch: "no" }, "late", { type: "action", action: "tag.add", config: { tag: "late" } });
  assert.deepEqual(removalImpact(s, "check").sort(), ["check", "late"], "the no branch goes with it");
  const first = remove(graph(), "hello");
  assert.equal(first.start, "pause");
});

test("a goal stands alone and is kept though nothing leads to it", () => {
  const g = addGoal(blank(), "met", { type: "goal", config: { filter: { tag: "x" } } });
  assert.ok(reachable(g).has("met"));
  assert.deepEqual(Object.keys(prune(g).nodes), ["met"]);
  const t = tree(graph());
  assert.equal(t.goals.length, 1);
  assert.equal(t.goals[0]!.kind === "node" && t.goals[0]!.id, "won");
});

test("changing a node's settings reshapes its edges and keeps what it can", () => {
  const split = insert(graph(), { from: "tag" }, "ab", { type: "split", config: { paths: [{ name: "a", percent: 50 }, { name: "b", percent: 50 }] } });
  const withB = insert(split, { from: "ab", branch: "b" }, "bee", { type: "action", action: "tag.add", config: { tag: "b" } });
  const renamed = update(withB, "ab", { config: { paths: [{ name: "a", percent: 50 }, { name: "c", percent: 50 }] } });
  assert.deepEqual(renamed.nodes.ab!.branches, { a: null, c: "bee" }, "a renamed path keeps its steps");
  const three = update(withB, "ab", { config: { paths: [{ name: "a", percent: 40 }, { name: "b", percent: 30 }, { name: "z", percent: 30 }] } });
  assert.deepEqual(three.nodes.ab!.branches, { a: null, b: "bee", z: null });
  const two = update(three, "ab", { config: { paths: [{ name: "a", percent: 50 }, { name: "z", percent: 50 }] } });
  assert.deepEqual(dropped(three, two), ["bee"]);
  const eventWait = update(graph(), "pause", { config: { event: { event: "form.submitted", timeout: { days: 1 } } } });
  assert.deepEqual(eventWait.nodes.pause!.branches, { event: "check", timeout: null });
  assert.equal("next" in eventWait.nodes.pause!, false);
  const back = update(eventWait, "pause", { config: { duration: { days: 1 } } });
  assert.equal(back.nodes.pause!.next, "check");
  assert.equal(update(graph(), "hello", { label: "" }).nodes.hello!.label, undefined);
});

test("moving a step up and down its chain", () => {
  const up = move(graph(), "pause", "up");
  assert.equal(up.start, "pause");
  assert.equal(up.nodes.pause!.next, "hello");
  assert.equal(up.nodes.hello!.next, "check");
  const down = move(graph(), "hello", "down");
  assert.ok(same(down, up));
  const g = graph();
  assert.equal(move(g, "hello", "up"), g, "the first step stays first");
  assert.equal(move(graph(), "tag", "up").nodes.check!.branches!.yes, "tag", "a step right after a branch does not leave it");
});

test("the tree draws each node once and later edges as go-tos", () => {
  const g = graph();
  g.nodes.tag!.next = "pause"; // a loop back through the wait
  const t = tree(g);
  assert.deepEqual(order(g), ["hello", "pause", "check", "tag", "won"]);
  const walk = (c: (typeof t)["main"]): string[] => (c.kind === "node" ? [c.id, ...(c.out.kind === "next" ? walk(c.out.child) : c.out.kind === "branches" ? c.out.branches.flatMap((b) => walk(b.child)) : [])] : c.kind === "goto" ? [`goto:${c.id}`] : ["end"]);
  assert.deepEqual(walk(t.main), ["hello", "pause", "check", "tag", "goto:pause", "end"]);
  assert.deepEqual(slotsTo(g, "pause"), [{ from: "hello" }, { from: "tag" }]);
});

test("ids are readable and unique", () => {
  assert.equal(newId(graph(), "message.send"), "message_send");
  assert.equal(newId(graph(), "tag"), "tag_2");
  assert.equal(newId(graph(), "9 Lives!"), "lives");
  assert.equal(newId(graph(), "___"), "step");
  assert.match(newId(graph(), "x".repeat(80)), /^[a-z][a-z0-9_]{0,39}$/);
});

test("the server's errors land on the trigger, the node and its field", () => {
  const p = place({
    "graph.nodes.send.config.body": "is required",
    "graph.nodes.pause": "is not reachable",
    "graph.trigger.filter.and.0.field": "is not a field",
    "graph.start": "is required: the id of the first node",
    "graph.nodes": "add a step first",
    name: "is too long",
  });
  assert.deepEqual(p.nodes.send, { "config.body": "is required" });
  assert.deepEqual(p.nodes.pause, { "": "is not reachable" });
  assert.deepEqual(p.trigger, { "filter.and.0.field": "is not a field" });
  assert.deepEqual(p.general, ["The first step is required: the id of the first node", "nodes: add a step first", "name: is too long"]);
});

test("time in words", () => {
  assert.equal(offsetText({ days: 2 }), "2 days");
  assert.equal(offsetText({ hours: 1 }), "1 hour");
  assert.equal(offsetText({ days: -1 }), "1 day");
  assert.equal(offsetText({}), "");
  assert.equal(secondsText(172800), "2 days");
  assert.equal(secondsText(5400), "1 hour 30 minutes");
  assert.equal(secondsText(0), "no time");
});

test("same ignores key order and undefined values", () => {
  assert.ok(same({ a: 1, b: { c: [1, 2] } }, { b: { c: [1, 2] }, a: 1, d: undefined }));
  assert.ok(!same({ a: [1, 2] }, { a: [2, 1] }));
});
