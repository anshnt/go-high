import assert from "node:assert/strict";
import { test } from "node:test";
import { asDark, byLevel, duplicateBlock, insertAt, issuesByBlock, moveBlock, newBlock, percent, ratio, removeBlock, scheduleBody, summary, updateBlock, withIds } from "../src/email/blocks.ts";
import type { Doc } from "../src/email/api.ts";

const doc = (): Doc => withIds({ blocks: [{ type: "heading", text: "Hi" }, { type: "text", text: "Body [link](https://x.test)" }, { type: "divider" }] });

test("documents from the server get ids, inside columns too, and keep their content", () => {
  const d = withIds({ blocks: [{ type: "columns", columns: [{ blocks: [{ type: "text", text: "a" }] }, { blocks: [] }] }] });
  assert.ok(d.blocks[0]!.id);
  const cols = d.blocks[0]!;
  assert.equal(cols.type, "columns");
  if (cols.type === "columns") assert.ok(cols.columns[0]!.blocks[0]!.id);
  assert.equal(d.version, 1);
  assert.deepEqual(withIds(null).blocks, []);
});

test("blocks move, stop at either end, duplicate below themselves and are removed", () => {
  const d = doc();
  const [a, b, c] = d.blocks.map((x) => x.id!);
  assert.deepEqual(moveBlock(d, b!, -1).blocks.map((x) => x.id), [b, a, c]);
  assert.deepEqual(moveBlock(d, a!, -1).blocks.map((x) => x.id), [a, b, c]);
  assert.deepEqual(moveBlock(d, c!, 1), d);
  const dup = duplicateBlock(d, a!);
  assert.equal(dup.blocks.length, 4);
  assert.equal(dup.blocks[1]!.type, "heading");
  assert.notEqual(dup.blocks[1]!.id, a);
  assert.deepEqual(removeBlock(d, b!).blocks.map((x) => x.id), [a, c]);
  assert.equal(insertAt(d, 99, newBlock("spacer")).blocks.at(-1)!.type, "spacer");
  assert.equal(insertAt(d, -3, newBlock("spacer")).blocks[0]!.type, "spacer");
  assert.equal((updateBlock(d, a!, { text: "Hello" }).blocks[0] as { text: string }).text, "Hello");
  assert.equal(d.blocks[0]!.type === "heading" && d.blocks[0]!.text, "Hi"); // nothing was changed in place
});

test("every new block is valid for the server out of the box", () => {
  for (const type of ["heading", "text", "button", "image", "divider", "spacer", "columns"] as const) {
    const b = newBlock(type);
    assert.equal(b.type, type);
    assert.ok(b.id);
  }
  const image = newBlock("image");
  assert.ok(image.type === "image" && image.src.startsWith("https://"));
});

test("the outline describes a block in a few words", () => {
  assert.equal(summary({ type: "text", text: "Read **this** [now](https://x.test)" }), "Read this now");
  assert.equal(summary({ type: "spacer", height: 32 }), "32 px");
  assert.equal(summary({ type: "text", text: "x".repeat(80) }).length, 60);
});

test("the server's error paths land on the block they are about", () => {
  const d = doc();
  const out = issuesByBlock(d, { "document.blocks.1.text": "unknown merge field {{nickname}}", subject: "unknown merge field {{x}}", "document.blocks.9.url": "gone" });
  assert.deepEqual(out.blocks, { [d.blocks[1]!.id!]: "text: unknown merge field {{nickname}}" });
  assert.deepEqual(out.other, ["Subject: unknown merge field {{x}}", "gone"]);
  const variant = issuesByBlock(d, { "ab.variants.0.document.blocks.0": "bad" }, "ab.variants.0.document");
  assert.deepEqual(Object.values(variant.blocks), ["bad"]);
});

test("rates read as people read them", () => {
  assert.equal(percent(0.4567), "46%");
  assert.equal(percent(0.0123), "1.2%");
  assert.equal(percent(0), "0%");
  assert.equal(percent(null), "None yet");
  assert.equal(ratio(1, 0), null);
  assert.equal(ratio(1, 4), 0.25);
});

test("issues come errors first", () => {
  const sorted = byLevel([
    { level: "info", code: "a", message: "" },
    { level: "error", code: "b", message: "" },
    { level: "warning", code: "c", message: "" },
  ]);
  assert.deepEqual(
    sorted.map((i) => i.code),
    ["b", "c", "a"],
  );
});

test("a schedule is a wall clock time and its zone; the server places it", () => {
  assert.deepEqual(scheduleBody("2027-03-14", "09:00", "America/New_York"), { scheduled_at: "2027-03-14T09:00:00", timezone: "America/New_York" });
  assert.equal(scheduleBody("", "09:00", "UTC"), null);
  assert.equal(scheduleBody("2027-03-14", "9am", "UTC"), null);
});

test("the dark preview applies the renderer's dark rules outright", () => {
  const html = "<html><head><style>a{color:red}@media (prefers-color-scheme:dark){.gh-bg{background-color:#000!important}.gh-text{color:#fff!important}}[data-ogsc] .x{}</style></head><body></body></html>";
  const dark = asDark(html);
  assert.ok(dark.includes("<style>:root{color-scheme:dark}.gh-bg{background-color:#000!important}.gh-text{color:#fff!important}</style></head>"));
  assert.equal(asDark("<html><head></head></html>"), "<html><head></head></html>");
  assert.equal(summary({ type: "heading", text: "Hi {{first_name|there}} **now** _yes_" }), "Hi {{first_name|there}} now yes");
});
