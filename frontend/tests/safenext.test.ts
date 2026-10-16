import assert from "node:assert/strict";
import { test } from "node:test";
import { safeNext } from "../src/lib/safeNext.ts";

test("same-origin relative paths pass, with query and hash", () => {
  assert.equal(safeNext("/inbox"), "/inbox");
  assert.equal(safeNext("/settings/security"), "/settings/security");
  assert.equal(safeNext("/contacts?view=mine&q=a%20b#top"), "/contacts?view=mine&q=a%20b#top");
  assert.equal(safeNext("/signing-docs"), "/signing-docs");
});

test("missing or empty falls back", () => {
  assert.equal(safeNext(null), "/");
  assert.equal(safeNext(undefined), "/");
  assert.equal(safeNext(""), "/");
  assert.equal(safeNext("", "/inbox"), "/inbox");
});

test("other origins and protocol-relative URLs are refused", () => {
  for (const bad of ["https://evil.example", "http://evil.example/x", "//evil.example", "///evil.example", "inbox", "javascript:alert(1)", "evil.example/x"]) {
    assert.equal(safeNext(bad), "/", bad);
  }
});

test("backslash and control character tricks are refused", () => {
  for (const bad of ["/\\evil.example", "/\\/evil.example", "/\t/evil.example", "/\n/evil.example", "/ /evil.example", "/a\\b", "/x\u0000"]) {
    assert.equal(safeNext(bad), "/", JSON.stringify(bad));
  }
});

test("never loops back into the sign-in screens", () => {
  for (const bad of ["/signin", "/signin?next=/inbox", "/signup", "/auth/magic?token=abc", "/auth"]) {
    assert.equal(safeNext(bad), "/", bad);
  }
});
