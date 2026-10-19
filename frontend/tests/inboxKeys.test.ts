import assert from "node:assert/strict";
import { test } from "node:test";
import { actionFor, moveActive, nextAfterRemoval } from "../src/inbox/keys.ts";

const IDS = ["a", "b", "c", "d", "e"];

test("j and k move, Enter and o open, and the triage keys are the ones in the shortcut sheet", () => {
  const keys = { j: "next", k: "prev", Enter: "open", o: "open", e: "close", s: "snooze", a: "assign", r: "reply", n: "note", u: "unread", "/": "search", f: "find", i: "card", Escape: "escape", ArrowDown: "next", ArrowUp: "prev" };
  for (const [key, action] of Object.entries(keys)) assert.equal(actionFor({ key }), action, key);
  assert.equal(actionFor({ key: "x" }), null);
  assert.equal(actionFor({ key: "J" }), null); // a capital is another key, not ours
});

test("a chord is never an inbox key, so Ctrl+K, Cmd+Enter and Alt+Left keep their own meaning", () => {
  for (const mod of ["ctrlKey", "metaKey", "altKey"] as const) {
    for (const key of ["j", "k", "e", "Enter", "/", "a"]) assert.equal(actionFor({ key, [mod]: true }), null, `${mod} ${key}`);
  }
});

test("the cursor moves one row, starts at the first (or last) row, and stops at the ends", () => {
  assert.equal(moveActive(IDS, "b", 1), "c");
  assert.equal(moveActive(IDS, "b", -1), "a");
  assert.equal(moveActive(IDS, "e", 1), "e");
  assert.equal(moveActive(IDS, "a", -1), "a");
  assert.equal(moveActive(IDS, null, 1), "a");
  assert.equal(moveActive(IDS, null, -1), "e");
  assert.equal(moveActive(IDS, "gone", 1), "a"); // the row left the list: start over rather than jump
  assert.equal(moveActive([], "a", 1), null);
});

test("five j presses from the top land on the fifth row, and a sixth stays there", () => {
  let at: string | null = null;
  const seen: (string | null)[] = [];
  for (let i = 0; i < 6; i++) seen.push((at = moveActive(IDS, at, 1)));
  assert.deepEqual(seen, ["a", "b", "c", "d", "e", "e"]);
});

test("when a row leaves the list the cursor takes the row that took its place, else the one above", () => {
  assert.equal(nextAfterRemoval(IDS, "b"), "c");
  assert.equal(nextAfterRemoval(IDS, "a"), "b");
  assert.equal(nextAfterRemoval(IDS, "e"), "d");
  assert.equal(nextAfterRemoval(["a"], "a"), null);
  assert.equal(nextAfterRemoval(IDS, "zzz"), "a");
  assert.equal(nextAfterRemoval([], "a"), null);
});
