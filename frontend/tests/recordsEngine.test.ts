import assert from "node:assert/strict";
import { test } from "node:test";
import { compareKeys, decodeCursor, dirsOf, encodeCursor, matchesQuery } from "../src/records/engine.ts";
import { RecordsError } from "../src/records/errors.ts";

test("engine: empty values sort last both ways, numbers sort as numbers, text naturally, ties on id", () => {
  const asc: (1 | -1)[] = [1];
  const desc: (1 | -1)[] = [-1];
  assert.ok(compareKeys([null], [1], asc, "a", "b") > 0);
  assert.ok(compareKeys([null], [1], desc, "a", "b") > 0, "still last when descending");
  assert.ok(compareKeys([1], [null], desc, "a", "b") < 0);
  assert.ok(compareKeys([9], [10], asc, "a", "b") < 0);
  assert.ok(compareKeys(["item 9"], ["item 10"], asc, "a", "b") < 0, "digits inside text compare as numbers");
  assert.equal(compareKeys(["Acme"], ["acme"], asc, "a", "b"), -1, "case does not matter, so the id decides");
  assert.equal(compareKeys([1, "x"], [1, "x"], [1, 1], "b", "a"), 1);
  assert.equal(compareKeys([], [], [], "a", "a"), 0);
  assert.ok(compareKeys([1, "b"], [1, "a"], [1, -1], "a", "b") < 0, "the second key decides in its own direction");
  assert.deepEqual(dirsOf([{ field: "a", dir: "asc" }, { field: "b", dir: "desc" }]), [1, -1]);
});

test("engine: cursors round trip any text and refuse anything that is not one", () => {
  const cursor = { k: ["Zoë Ångström 🙂", 12.5, null], id: "rec_1" };
  const encoded = encodeCursor(cursor);
  assert.match(encoded, /^[A-Za-z0-9_-]+$/, "safe in a URL as it is");
  assert.deepEqual(decodeCursor(encoded), cursor);
  const bad = [
    "!!!",
    "",
    encodeCursor({ k: "not a list", id: "x" } as never),
    encodeCursor({ k: [], id: 3 } as never),
    btoa("null"),
    btoa("[]"),
  ];
  for (const s of bad) {
    assert.throws(
      () => decodeCursor(s),
      (e: unknown) => e instanceof RecordsError && e.status === 400,
      s,
    );
  }
});

test("engine: every word of a search must appear in the record's text", () => {
  const blob = "ada lovelace ada@example.com analytical engine";
  assert.ok(matchesQuery(blob, "Ada  ENGINE"));
  assert.ok(matchesQuery(blob, "   "), "an empty query matches everything");
  assert.ok(!matchesQuery(blob, "ada babbage"));
});
