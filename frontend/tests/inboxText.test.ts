import assert from "node:assert/strict";
import { test } from "node:test";
import { holds, holdsAll } from "../src/lib/holds.ts";
import { hasRemoteImages, queryTerms, textParts } from "../src/inbox/text.ts";

const show = (parts: ReturnType<typeof textParts>) => parts.map((p) => (p.hit ? `[${p.text}]` : p.text)).join("");

test("a search marks the start of every word a term begins, like the server matches", () => {
  assert.equal(show(textParts("Where is my invoice 1043?", "invoice 1043")), "Where is my [invoice] [1043]?");
  assert.equal(show(textParts("Invoices and INVOICE", "invoice")), "[Invoice]s and [INVOICE]");
  assert.equal(show(textParts("preinvoice", "invoice")), "preinvoice"); // the middle of a word is not a match
  assert.equal(show(textParts("nothing here", "")), "nothing here");
  assert.equal(show(textParts("a.b (c)", "a.b")), "[a].[b] (c)");
});

test("terms are words: punctuation, case and repeats do not matter, other scripts work", () => {
  assert.deepEqual(queryTerms("  Invoice, invoice! 1043 "), ["invoice", "1043"]);
  assert.deepEqual(queryTerms("café"), ["café"]);
  assert.deepEqual(queryTerms("***"), []);
  assert.equal(show(textParts("Un café s'il vous plaît", "café")), "Un [café] s'il vous plaît");
});

test("web addresses become links without the full stop after them, and hits inside them still show", () => {
  const parts = textParts("See https://pay.example.com/i/1043. Thanks", "pay");
  const url = "https://pay.example.com/i/1043";
  assert.ok(parts.filter((p) => p.href).every((p) => p.href === url));
  assert.equal(parts.filter((p) => p.href).map((p) => p.text).join(""), url); // the full stop is not part of it
  assert.equal(parts.map((p) => p.text).join(""), `See ${url}. Thanks`);
  assert.ok(parts.some((p) => p.hit && p.href));
  assert.equal(textParts("no links", "")[0]!.href, undefined);
  assert.equal(textParts("javascript:alert(1)", "")[0]!.href, undefined); // only http and https become links
});

test("remote images are only offered when the email would actually load one", () => {
  assert.equal(hasRemoteImages('<p>Hi</p><img src="https://cdn.example.com/a.png">'), true);
  assert.equal(hasRemoteImages('<img src="//cdn.example.com/a.png">'), true);
  assert.equal(hasRemoteImages('<div style="background:url(https://x.example/y.png)">'), true);
  assert.equal(hasRemoteImages('<table background="http://x.example/y.png">'), true);
  assert.equal(hasRemoteImages('<img src="data:image/png;base64,AAAA">'), false);
  assert.equal(hasRemoteImages("<p>Just text</p>"), false);
  assert.equal(hasRemoteImages(null), false);
});

test("a capability is held, or not yet known, which counts as held", () => {
  const known = { ready: true, caps: new Set(["conversations.read", "messages.send"]) };
  assert.equal(holds(known, "messages.send"), true);
  assert.equal(holds(known, "channels.manage"), false);
  assert.equal(holds({ ready: false, caps: new Set() }, "channels.manage"), true);
  assert.equal(holdsAll(known, ["conversations.read", "messages.send"]), true);
  assert.equal(holdsAll(known, ["conversations.read", "channels.manage"]), false);
  assert.equal(holdsAll(known, []), true);
});
