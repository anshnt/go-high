import assert from "node:assert/strict";
import { test } from "node:test";
import { backoff, isNothing, parseEvent, planRefetch, type Showing, type StreamEvent } from "../src/inbox/stream.ts";

const SHOWING: Showing = { conversationId: "c1", contactId: "p1", rowsByContact: new Map([["p1", "c1"], ["p2", "c2"]]) };
const ev = (type: string, ids: StreamEvent["ids"] = {}): StreamEvent => ({ id: 1, type, workspace_id: "w", ids });

test("a new message in the open conversation reads its row, the counts and the thread again, and nothing else", () => {
  const r = planRefetch([ev("message.received", { message_id: "m", conversation_id: "c1", contact_id: "p1" })], SHOWING);
  assert.deepEqual(r, { everything: false, rows: ["c1"], counts: true, thread: true, contact: false });
});

test("a message in another conversation refreshes its row and the counts but not the open thread", () => {
  const r = planRefetch([ev("message.received", { conversation_id: "c9" })], SHOWING);
  assert.deepEqual(r, { everything: false, rows: ["c9"], counts: true, thread: false, contact: false });
});

test("a delivery report or an edited note changes a message, not who has unread: no counts", () => {
  for (const type of ["message.sent", "message.failed", "message.status_changed", "message.note_added", "message.updated"]) {
    const r = planRefetch([ev(type, { conversation_id: "c1" })], SHOWING);
    assert.equal(r.counts, false, type);
    assert.equal(r.thread, true, type);
    assert.deepEqual(r.rows, ["c1"], type);
  }
});

test("any conversation event moves a conversation between views, so the counts are read again", () => {
  for (const type of ["conversation.created", "conversation.updated"]) assert.equal(planRefetch([ev(type, { conversation_id: "c9" })], SHOWING).counts, true, type);
});

test("a batch asks for each conversation once and for the union of what its events need", () => {
  const r = planRefetch(
    [ev("message.sent", { conversation_id: "c1" }), ev("message.status_changed", { conversation_id: "c1" }), ev("conversation.updated", { conversation_id: "c2" }), ev("message.received", { conversation_id: "c1" })],
    SHOWING,
  );
  assert.deepEqual(r.rows.sort(), ["c1", "c2"]);
  assert.equal(r.counts, true);
  assert.equal(r.thread, true);
});

test("stream.resync, which means events were missed, refetches everything shown", () => {
  const r = planRefetch([ev("message.sent", { conversation_id: "c1" }), { type: "stream.resync" }], SHOWING);
  assert.deepEqual(r, { everything: true, rows: [], counts: false, thread: false, contact: false });
});

test("a change to the open contact reads the card and its row; a contact in the list reads its row; a stranger is ignored", () => {
  assert.deepEqual(planRefetch([ev("record.updated", { object: "contact", record_id: "p1" })], SHOWING), { everything: false, rows: ["c1"], counts: false, thread: false, contact: true });
  assert.deepEqual(planRefetch([ev("record.updated", { object: "contact", record_id: "p2" })], SHOWING), { everything: false, rows: ["c2"], counts: false, thread: false, contact: false });
  assert.equal(isNothing(planRefetch([ev("record.updated", { object: "contact", record_id: "p77" })], SHOWING)), true);
  assert.equal(isNothing(planRefetch([ev("record.updated", { object: "deal", record_id: "p1" })], SHOWING)), true);
});

test("events that name nothing we show, and unknown types, ask for nothing", () => {
  assert.equal(isNothing(planRefetch([], SHOWING)), true);
  assert.equal(isNothing(planRefetch([ev("channel.updated"), ev("consent.changed", { contact_id: "p1" })], SHOWING)), true);
  assert.equal(isNothing(planRefetch([ev("message.sent", {})], SHOWING)), true);
  assert.equal(planRefetch([ev("message.sent", { conversation_id: "c1" })], { ...SHOWING, conversationId: null }).thread, false);
});

test("reconnecting waits 1 s, 2 s, 4 s and so on up to 30 s, with a little jitter", () => {
  const none = () => 0;
  const most = () => 1;
  assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 7, 20].map((n) => backoff(n, none)), [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000, 30000]);
  assert.equal(backoff(0, most), 1250);
  assert.equal(backoff(9, most), 37500);
  assert.equal(backoff(-3, none), 1000);
  const j = backoff(2);
  assert.ok(j >= 4000 && j <= 5000);
});

test("a data line is one of our events, or nothing", () => {
  assert.deepEqual(parseEvent('{"id":7,"type":"message.sent","workspace_id":"w","ids":{"conversation_id":"c1"}}'), { id: 7, type: "message.sent", workspace_id: "w", ids: { conversation_id: "c1" } });
  assert.equal(parseEvent("not json"), null);
  assert.equal(parseEvent("42"), null);
  assert.equal(parseEvent('{"no":"type"}'), null);
  assert.equal(parseEvent("null"), null);
});
