import assert from "node:assert/strict";
import { test } from "node:test";
import { buildCreate, buildPatch, emptyValues, errorsByField, missing, SPECS, specOf, valuesOf, type Spec } from "../src/inbox/channelSpecs.ts";
import type { Channel } from "../src/inbox/types.ts";

const spec = (id: string): Spec => SPECS.find((s) => s.id === id)!;
const fill = (s: Spec, fields: Record<string, string>, rules: Partial<ReturnType<typeof emptyValues>["rules"]> = {}) => {
  const v = emptyValues(s);
  return { fields: { ...v.fields, ...fields }, rules: { ...v.rules, ...rules } };
};

test("every provider of the README table has a form, and a provider the form does not know falls back to SMTP", () => {
  assert.deepEqual(SPECS.map((s) => s.provider).sort(), ["internal", "mailgun", "meta", "smtp", "telnyx", "twilio"]);
  assert.equal(specOf({ provider: "ses" }).provider, "smtp"); // SES is the SMTP adapter pointed at its endpoint
  for (const s of SPECS) assert.ok(s.fields.some((f) => f.where === "name"), s.id);
});

test("a Twilio channel is created with its number as the address, its SID as a setting and its token as a secret", () => {
  const s = spec("twilio");
  const body = buildCreate(s, fill(s, { name: " Main line ", address: "+14155550123", account_sid: "ACexample", auth_token: "token-not-real" }, { segment_cost: "0.0079", quiet_start: "21:00", quiet_end: "08:00", cap_max: "5", cap_hours: "12" }));
  assert.deepEqual(body, {
    kind: "sms",
    provider: "twilio",
    name: "Main line",
    address: "+14155550123",
    config: { account_sid: "ACexample", segment_cost: 0.0079, quiet_start: "21:00", quiet_end: "08:00", frequency_cap: { max: 5, hours: 12 } },
    secrets: { auth_token: "token-not-real" },
  });
});

test("empty optional settings are left out of a new channel, and a secret never lands in config", () => {
  const s = spec("smtp");
  const body = buildCreate(s, fill(s, { name: "Mail", address: "hello@example.com", host: "smtp.example.com", username: "hello@example.com", password: "p@ss" }, { reply_to: "support@example.com" }));
  assert.deepEqual(body.config, { host: "smtp.example.com", port: 587, security: "starttls", username: "hello@example.com", reply_to: "support@example.com" });
  assert.deepEqual(body.secrets, { password: "p@ss" });
  assert.ok(!JSON.stringify(body.config).includes("p@ss"));
  const bare = buildCreate(s, fill(s, { name: "Mail", address: "hello@example.com", host: "smtp.example.com" }));
  assert.equal("secrets" in bare, false); // nothing typed: nothing sent
});

test("a web chat widget has no address of its own and takes its look as settings", () => {
  const s = spec("internal");
  const body = buildCreate(s, fill(s, { name: "Website chat", title: "Chat with us", greeting: "" }));
  assert.deepEqual(body, { kind: "webchat", provider: "internal", name: "Website chat", address: "", config: { title: "Chat with us", color: "#4f46e5" } });
});

const saved = (over: Partial<Channel> = {}): Channel => ({ id: "c1", kind: "email", provider: "mailgun", name: "Support mail", address: "hello@mg.example.com", status: "active", status_detail: null, created_at: "", updated_at: "", secrets_set: true, config: { domain: "mg.example.com", region: "eu", reply_to: "help@example.com" }, ...over });

test("editing starts from the saved settings and never from a secret, which the API does not return", () => {
  const s = spec("mailgun");
  const v = valuesOf(s, saved());
  assert.equal(v.fields.name, "Support mail");
  assert.equal(v.fields.address, "hello@mg.example.com");
  assert.equal(v.fields.domain, "mg.example.com");
  assert.equal(v.fields.region, "eu");
  assert.equal(v.fields.api_key, "");
  assert.equal(v.fields.signing_key, "");
  assert.equal(v.rules.reply_to, "help@example.com");
});

test("a save sends the settings as the form has them, removes an emptied optional one and sends only the secrets that were typed", () => {
  const s = spec("mailgun");
  const v = valuesOf(s, saved());
  v.rules.reply_to = "";
  v.fields.message_id_domain = "";
  v.fields.api_key = "key-not-real";
  const patch = buildPatch(s, v);
  assert.deepEqual(patch.config, { domain: "mg.example.com", region: "eu", message_id_domain: null, reply_to: null });
  assert.deepEqual(patch.secrets, { api_key: "key-not-real" });
  assert.equal(patch.name, "Support mail");
  assert.equal(buildPatch(s, valuesOf(s, saved())).secrets, undefined);
  const chat = spec("internal");
  assert.equal("address" in buildPatch(chat, valuesOf(chat, saved({ kind: "webchat", provider: "internal", config: { title: "Hi" } }))), false); // the widget key cannot change
});

test("the SMS rules come back as text and a cap is saved as both numbers", () => {
  const s = spec("twilio");
  const v = valuesOf(s, saved({ kind: "sms", provider: "twilio", config: { account_sid: "ACexample", segment_cost: 0.0079, frequency_cap: { max: 10, hours: 24 }, quiet_start: "21:00", quiet_end: "08:00" } }));
  assert.deepEqual(v.rules, { segment_cost: "0.0079", quiet_start: "21:00", quiet_end: "08:00", cap_max: "10", cap_hours: "24", reply_to: "" });
  v.rules.cap_max = "";
  v.rules.cap_hours = "";
  assert.equal(buildPatch(s, v).config.frequency_cap, null);
});

test("what is missing is found before the server is asked, and a saved secret need not be typed again", () => {
  const s = spec("twilio");
  assert.deepEqual(missing(s, emptyValues(s), false), ["name", "address", "account_sid", "auth_token"]);
  assert.deepEqual(missing(s, fill(s, { name: "x", address: "+1", account_sid: "AC" }), true), []);
  assert.deepEqual(missing(s, fill(s, { name: "x", address: "+1", account_sid: "AC" }), false), ["auth_token"]);
});

test("the server's errors land on the form's fields by their own names", () => {
  const s = spec("twilio");
  assert.deepEqual(errorsByField(s, { "config.account_sid": "is required", "secrets.auth_token": "is required", address: "must be a phone number in E.164 form", name: "is required" }), {
    account_sid: "Is required",
    auth_token: "Is required",
    address: "Must be a phone number in E.164 form",
    name: "Is required",
  });
  assert.deepEqual(errorsByField(s, { kind: "twilio is for sms channels" }), { kind: "Twilio is for sms channels" });
  assert.deepEqual(errorsByField(s, undefined), {});
});
