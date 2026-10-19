import assert from "node:assert/strict";
import { test } from "node:test";
import { defaultChannel, hasAddress, reachable } from "../src/inbox/reach.ts";
import type { Channel, ChannelKind } from "../src/inbox/types.ts";

const ch = (id: string, kind: ChannelKind, status: Channel["status"] = "active"): Channel => ({ id, kind, provider: "internal", name: id, address: "", status, status_detail: null, created_at: "", updated_at: "" });
const CHANNELS = [ch("sms", "sms"), ch("mail", "email"), ch("wa", "whatsapp"), ch("chat", "webchat")];
const who = (phone: string | null, email: string | null, visitor = false, channel_id: string | null = null) => ({ contact: { id: "p", display_name: "X", phone, email }, visitor, channel_id });

test("a phone number reaches SMS and WhatsApp, an address reaches email, only a chat visitor reaches web chat", () => {
  assert.deepEqual(reachable(CHANNELS, who("+14155550101", null)).map((c) => c.id), ["sms", "wa"]);
  assert.deepEqual(reachable(CHANNELS, who(null, "a@example.com")).map((c) => c.id), ["mail"]);
  assert.deepEqual(reachable(CHANNELS, who("+14155550101", "a@example.com")).map((c) => c.id), ["sms", "mail", "wa"]);
  assert.deepEqual(reachable(CHANNELS, who(null, null, true)).map((c) => c.id), ["chat"]);
  assert.deepEqual(reachable(CHANNELS, who(null, null)), []);
  assert.equal(hasAddress("webchat", who("+14155550101", "a@example.com")), false);
});

test("a switched-off channel is not offered, a channel that is only pending or failing still is (the server decides)", () => {
  const list = [ch("sms", "sms", "disabled"), ch("sms2", "sms", "pending"), ch("sms3", "sms", "failing")];
  assert.deepEqual(reachable(list, who("+14155550101", null)).map((c) => c.id), ["sms2", "sms3"]);
});

test("a reply starts on the channel the conversation last used, else the quickest one the contact can be reached on", () => {
  const both = (channel_id: string | null) => who("+14155550101", "a@example.com", false, channel_id);
  assert.equal(defaultChannel(CHANNELS, both("mail"))!.id, "mail");
  assert.equal(defaultChannel(CHANNELS, both(null))!.id, "sms");
  assert.equal(defaultChannel([...CHANNELS].reverse(), both(null))!.id, "sms"); // whatever order the API lists them in
  assert.equal(defaultChannel(CHANNELS.filter((c) => c.kind !== "sms"), both(null))!.id, "wa");
  assert.equal(defaultChannel(CHANNELS, who(null, "a@example.com", false, "sms"))!.id, "mail"); // no phone any more
  assert.equal(defaultChannel(CHANNELS, who(null, null)), null);
  assert.equal(defaultChannel([], both("mail")), null);
});
