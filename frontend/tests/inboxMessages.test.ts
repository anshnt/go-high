import assert from "node:assert/strict";
import { test } from "node:test";
import { draftMessage, fail, lastStoredSeq, mergeMessages, retrying, settle, tickOf } from "../src/inbox/messages.ts";
import type { Message, ThreadMessage } from "../src/inbox/types.ts";

const msg = (seq: number, over: Partial<Message> = {}): Message => ({
  id: `m${seq}`,
  conversation_id: "c1",
  seq,
  direction: "in",
  channel_id: "ch1",
  kind: "message",
  subject: null,
  body: `body ${seq}`,
  html: null,
  attachments: [],
  status: "received",
  error: null,
  provider_message_id: null,
  thread_ref: null,
  sent_by: null,
  occurred_at: `2026-10-20T10:0${seq}:00.000Z`,
  created_at: `2026-10-20T10:0${seq}:00.000Z`,
  segments: null,
  estimated_cost: null,
  ...over,
});
const draft = (key = "k1") => draftMessage({ key, conversationId: "c1", channelId: "ch1", kind: "message", body: "on its way", subject: null, html: null, me: "me", now: new Date("2026-10-20T11:00:00Z") });

test("a page of messages, newest first, ends up oldest first by seq", () => {
  assert.deepEqual(mergeMessages([], [msg(3), msg(2), msg(1)]).map((m) => m.seq), [1, 2, 3]);
});

test("the order is the server's seq, never the provider's clock", () => {
  const late = msg(1, { occurred_at: "2026-10-20T23:00:00.000Z" });
  const early = msg(2, { occurred_at: "2026-10-19T01:00:00.000Z" });
  assert.deepEqual(mergeMessages([], [early, late]).map((m) => m.id), ["m1", "m2"]);
});

test("a refetch updates a message we hold (a status that moved on) and never drops one it does not carry", () => {
  const held = [msg(1), msg(2, { direction: "out", status: "queued" }), msg(3)];
  const merged = mergeMessages(held, [msg(2, { direction: "out", status: "delivered" }), msg(4)]);
  assert.deepEqual(merged.map((m) => [m.seq, m.status]), [[1, "received"], [2, "delivered"], [3, "received"], [4, "received"]]);
});

test("a message still being sent stays after the stored ones until the server answers, then the stored one replaces it", () => {
  const d = draft();
  const thread = mergeMessages([d], [msg(1), msg(2)]);
  assert.deepEqual(thread.map((m) => m.id), ["m1", "m2", "local-k1"]);
  const stored = msg(3, { id: "m3", direction: "out", status: "queued", body: "on its way" });
  const settled = settle(thread, "k1", stored);
  assert.deepEqual(settled.map((m) => [m.id, !!m.local]), [["m1", false], ["m2", false], ["m3", false]]);
});

test("if a refetch brought the stored message in first, settling does not show it twice", () => {
  const d = draft();
  const stored = msg(3, { id: "m3", direction: "out", status: "sent", body: "on its way" });
  const withBoth = mergeMessages([msg(1), d], [stored]);
  assert.equal(withBoth.length, 3);
  const settled = settle(withBoth, "k1", { ...stored, status: "queued" });
  assert.deepEqual(settled.map((m) => m.id), ["m1", "m3"]);
  assert.equal(settled[1]!.status, "queued");
});

test("a send that did not leave is marked failed with its reason and keeps its key, so Retry sends the same thing", () => {
  const failed = fail([draft()], "k1", "Could not reach the server");
  assert.equal(failed[0]!.status, "failed");
  assert.deepEqual(failed[0]!.local, { key: "k1", state: "failed", error: "Could not reach the server", channelKind: undefined });
  const again = retrying(failed, "k1");
  assert.equal(again[0]!.local!.state, "sending");
  assert.equal(again[0]!.local!.key, "k1");
  assert.equal(again[0]!.status, "queued");
  assert.equal(again[0]!.error, null);
  assert.equal(fail([draft("other")], "k1", "x")[0]!.status, "queued"); // another draft is left alone
});

test("ticks: sending, sent, delivered, read and failed for what we sent; nothing for what they sent or for notes", () => {
  const out = (status: Message["status"], over: Partial<Message> = {}) => ({ ...msg(1), direction: "out" as const, status, ...over });
  assert.equal(tickOf(draft()), "sending");
  assert.equal(tickOf(out("queued")), "sending");
  assert.equal(tickOf(out("sent")), "sent");
  assert.equal(tickOf(out("delivered")), "delivered");
  assert.equal(tickOf(out("read")), "read");
  assert.equal(tickOf(out("failed")), "failed");
  assert.equal(tickOf(fail([draft()], "k1", "x")[0]!), "failed");
  assert.equal(tickOf(msg(1)), "none");
  assert.equal(tickOf(out("sent", { kind: "note" })), "none");
  assert.equal(tickOf(out("sent", { kind: "system" })), "none");
});

test("the read mark moves to the newest stored message, not to a draft", () => {
  const mixed: ThreadMessage[] = mergeMessages([draft()], [msg(1), msg(2), msg(5)]);
  assert.equal(lastStoredSeq(mixed), 5);
  assert.equal(lastStoredSeq([draft()]), 0);
});

test("a note draft is not on any channel", () => {
  const note = draftMessage({ key: "n", conversationId: "c1", channelId: "ch1", kind: "note", body: "x", subject: null, html: null, me: "me", now: new Date() });
  assert.equal(note.channel_id, null);
  assert.equal(tickOf(note), "none");
});
