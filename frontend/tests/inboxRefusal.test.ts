import assert from "node:assert/strict";
import { test } from "node:test";
import { consentLine, consentRefusal, describeRefusal, isRefusalCode, REFUSAL_CODES } from "../src/inbox/refusal.ts";
import type { Consent } from "../src/inbox/types.ts";

const NOW = new Date(2026, 9, 21, 15, 30);

test("every refusal code the server can answer with has a title, a way forward and the server's own sentence", () => {
  assert.deepEqual([...REFUSAL_CODES].sort(), ["channel_disabled", "dnd", "frequency_cap", "no_address", "no_channel", "opted_out", "quiet_hours"]);
  for (const code of REFUSAL_CODES) {
    const r = describeRefusal({ code, message: `server says ${code}` }, NOW)!;
    assert.equal(r.code, code);
    assert.equal(r.text, `server says ${code}`);
    assert.ok(r.title.length > 3 && r.hint.length > 10, code);
    assert.ok(!r.title.includes("—") && !r.hint.includes("—"), code); // no long dashes in UI copy
  }
});

test("an opt-out blocks sending, and says only the contact can opt back in", () => {
  const r = describeRefusal({ code: "opted_out", message: "Opted out by STOP on Oct 3" }, NOW)!;
  assert.equal(r.text, "Opted out by STOP on Oct 3");
  assert.equal(r.blocking, true);
  assert.match(r.hint, /START/);
});

test("quiet hours say when sending resumes, from retry_at in the reader's time", () => {
  const retry = new Date(2026, 9, 22, 8, 0).toISOString();
  const r = describeRefusal({ code: "quiet_hours", message: "Quiet hours for this contact (America/New_York): sending resumes at 08:00", fields: { retry_at: retry } }, NOW)!;
  assert.equal(r.until, "Thu, Oct 22, 8:00 AM");
  assert.equal(r.blocking, false); // waiting helps, and the draft is kept
  assert.equal(describeRefusal({ code: "quiet_hours", message: "m" }, NOW)!.until, undefined);
  assert.equal(describeRefusal({ code: "quiet_hours", message: "m", fields: { retry_at: "garbage" } }, NOW)!.until, undefined);
  assert.equal(describeRefusal({ code: "dnd", message: "m", fields: { retry_at: retry } }, NOW)!.until, undefined);
});

test("a frequency cap and do not disturb wait or switch; a missing address or channel cannot be sent through", () => {
  assert.equal(describeRefusal({ code: "frequency_cap", message: "m" }, NOW)!.blocking, false);
  assert.equal(describeRefusal({ code: "dnd", message: "m" }, NOW)!.blocking, false);
  for (const code of ["no_address", "no_channel", "channel_disabled"]) assert.equal(describeRefusal({ code, message: "m" }, NOW)!.blocking, true, code);
});

test("an error that is not a refusal (a dropped connection, a 500, a validation error) is not shown as one", () => {
  assert.equal(describeRefusal({ code: "validation_failed", message: "The message is empty" }, NOW), null);
  assert.equal(describeRefusal({ message: "Could not reach the server" }, NOW), null);
  assert.equal(isRefusalCode("opted_out"), true);
  assert.equal(isRefusalCode("nope"), false);
  assert.equal(isRefusalCode(undefined), false);
});

test("a consent on file reads like the server's refusal, before anyone presses Send", () => {
  const consent = (status: Consent["status"], source: string, kind: Consent["kind"] = "sms"): Consent => ({ kind, status, source, reason: null, changed_at: new Date(2026, 9, 3, 12).toISOString() });
  assert.equal(consentRefusal(consent("opted_out", "stop"))!.text, "Opted out by STOP on Oct 3");
  assert.equal(consentRefusal(consent("opted_out", "complaint", "email"))!.text, "Opted out by a spam complaint on Oct 3");
  assert.equal(consentRefusal(consent("dnd", "manual"))!.text, "Do not disturb is on for sms");
  assert.equal(consentRefusal(consent("opted_in", "start")), null);
  assert.equal(consentLine(undefined), "No record");
  assert.equal(consentLine(consent("opted_in", "start")), "Opted in");
  assert.equal(consentLine(consent("dnd", "manual")), "Do not disturb");
  assert.equal(consentLine(consent("opted_out", "stop")), "Opted out by STOP on Oct 3");
});
