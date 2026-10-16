import assert from "node:assert/strict";
import { test } from "node:test";
import { fuzzy, rank, STRONG } from "../src/lib/fuzzy.ts";

const labels = ["Settings", "Setup health", "Show keyboard shortcuts", "Use compact density", "Contacts"];
const pick = (q: string) => rank(labels, (l) => fuzzy(q, l));

test("substring and word-prefix matches hide loose ones", () => {
  assert.deepEqual(pick("sett"), ["Settings"]);
  assert.deepEqual(pick("key short"), ["Show keyboard shortcuts"]);
});

test("loose subsequence still works when nothing matches strongly", () => {
  assert.deepEqual(pick("cntc"), ["Contacts"]);
});

test("empty query keeps every item in order", () => {
  assert.deepEqual(pick(""), labels);
});

test("tiers", () => {
  assert.ok(fuzzy("health", "Setup health")! > STRONG);
  assert.equal(fuzzy("zzz", "Settings"), null);
});
