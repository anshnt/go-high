import assert from "node:assert/strict";
import { test } from "node:test";
import type { Conversation, Counts } from "../src/inbox/types.ts";
import { EMPTY_COUNTS, matchesView, withCounts, withRow, type Filter } from "../src/inbox/views.ts";

const ME = "me";
const conv = (id: string, over: Partial<Conversation> = {}): Conversation => ({
  id,
  contact: { id: `p-${id}`, display_name: id, email: null, phone: null },
  status: "open",
  assignee_id: null,
  team_id: null,
  snooze_until: null,
  last_message_at: "2026-10-20T10:00:00.000Z",
  last_inbound_at: null,
  channel_id: "ch1",
  channel_kind: "sms",
  preview: "hi",
  last_direction: "in",
  unread: false,
  last_seq: 1,
  visitor: false,
  created_at: "2026-10-01T10:00:00.000Z",
  ...over,
});
const OPEN: Filter = { view: "open", channel: null };

test("each view takes the conversations the server's rule gives it", () => {
  const open = conv("a");
  const mine = conv("b", { assignee_id: ME });
  const theirs = conv("c", { assignee_id: "other" });
  const snoozed = conv("d", { status: "snoozed", unread: true });
  const closed = conv("e", { status: "closed", unread: true });
  const table: [string, Conversation, boolean[]][] = [
    // open, mine, unassigned, unread, snoozed, closed
    ["open", open, [true, false, true, false, false, false]],
    ["mine", mine, [true, true, false, false, false, false]],
    ["assigned to someone else", theirs, [true, false, false, false, false, false]],
    ["snoozed and unread", snoozed, [false, false, false, true, true, false]],
    ["closed and unread (not in unread)", closed, [false, false, false, false, false, true]],
  ];
  for (const [name, c, want] of table) {
    const got = (["open", "mine", "unassigned", "unread", "snoozed", "closed"] as const).map((v) => matchesView(v, c, ME));
    assert.deepEqual(got, want, name);
  }
  assert.equal(matchesView("mine", conv("x", { assignee_id: ME }), null), false);
});

test("closing a conversation takes it out of the open list and moves the counts at once", () => {
  const before = conv("a", { assignee_id: ME, unread: true });
  const rows = [before, conv("b")];
  const after = { ...before, status: "closed" as const };
  assert.deepEqual(withRow(rows, after, OPEN, ME).map((r) => r.id), ["b"]);
  const counts: Counts = { ...EMPTY_COUNTS, open: 5, mine: 2, unassigned: 3, unread: 4, closed: 1, channels: { ch1: 5 } };
  assert.deepEqual(withCounts(counts, before, after, ME), { ...counts, open: 4, mine: 1, unread: 3, closed: 2, channels: { ch1: 4 } });
});

test("snoozing moves a conversation to Snoozed; reopening brings it back and counts it per channel again", () => {
  const open = conv("a");
  const snoozed = { ...open, status: "snoozed" as const, snooze_until: "2026-10-21T09:00:00.000Z" };
  const there = withCounts({ ...EMPTY_COUNTS, open: 2, unassigned: 2, channels: { ch1: 2 } }, open, snoozed, ME);
  assert.deepEqual(there, { ...EMPTY_COUNTS, open: 1, unassigned: 1, snoozed: 1, channels: { ch1: 1 } });
  assert.deepEqual(withCounts(there, snoozed, open, ME), { ...EMPTY_COUNTS, open: 2, unassigned: 2, channels: { ch1: 2 } });
});

test("assigning to me moves a conversation from Unassigned to Mine and counts never go below zero", () => {
  const before = conv("a");
  const after = { ...before, assignee_id: ME };
  const c = withCounts({ ...EMPTY_COUNTS, open: 1, unassigned: 1 }, before, after, ME);
  assert.deepEqual([c.open, c.mine, c.unassigned], [1, 1, 0]);
  assert.equal(withCounts(EMPTY_COUNTS, before, null, ME).open, 0);
});

test("a conversation that starts to belong is inserted by activity; one that is already there is updated in place", () => {
  const rows = [conv("a", { last_message_at: "2026-10-20T12:00:00.000Z" }), conv("c", { last_message_at: "2026-10-20T08:00:00.000Z" })];
  const fresh = conv("b", { last_message_at: "2026-10-20T10:00:00.000Z" });
  assert.deepEqual(withRow(rows, fresh, OPEN, ME).map((r) => r.id), ["a", "b", "c"]);
  const newer = conv("c", { last_message_at: "2026-10-20T13:00:00.000Z", preview: "new" });
  const moved = withRow(rows, newer, OPEN, ME);
  assert.deepEqual(moved.map((r) => r.id), ["c", "a"]);
  assert.equal(moved[0]!.preview, "new");
  const read = { ...rows[0]!, unread: false };
  assert.equal(withRow(rows, read, OPEN, ME)[0], read);
  assert.deepEqual(withRow(rows, conv("z", { status: "closed" }), OPEN, ME), rows); // does not belong: untouched
});

test("with more pages still to come, a conversation older than the last row loaded waits for its page instead of jumping in", () => {
  const rows = [conv("a", { last_message_at: "2026-10-20T12:00:00.000Z" }), conv("c", { last_message_at: "2026-10-20T08:00:00.000Z" })];
  const old = conv("z", { last_message_at: "2026-10-19T08:00:00.000Z" });
  const between = conv("b", { last_message_at: "2026-10-20T10:00:00.000Z" });
  assert.deepEqual(withRow(rows, old, OPEN, ME, false, true), rows);
  assert.deepEqual(withRow(rows, old, OPEN, ME, false, false).map((r) => r.id), ["a", "c", "z"]); // the whole list is loaded: it is the last row
  assert.deepEqual(withRow(rows, between, OPEN, ME, false, true).map((r) => r.id), ["a", "b", "c"]);
});

test("a channel filter keeps other channels out, and a search list never gains rows it cannot judge", () => {
  const sms: Filter = { view: "open", channel: "ch1" };
  assert.deepEqual(withRow([], conv("a", { channel_id: "ch2" }), sms, ME), []);
  assert.deepEqual(withRow([], conv("a", { channel_id: "ch1" }), sms, ME).map((r) => r.id), ["a"]);
  assert.deepEqual(withRow([], conv("a"), OPEN, ME, true), []);
  const rows = [conv("a")];
  const closed = { ...rows[0]!, status: "closed" as const };
  assert.equal(withRow(rows, closed, OPEN, ME, true)[0], closed); // in a search it stays, shown as it is now
});
