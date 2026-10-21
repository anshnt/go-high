// The builder's words and forms come from the catalog: a step's line on the canvas, the server's errors as sentences,
// and the controls each action's JSON schema gets.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { JsonSchema } from "../src/workflows/api.ts";
import { branchLabel, summary, title, triggerSummary, type Names } from "../src/workflows/describe.ts";
import { eventHelp, eventLabel, objectsFor } from "../src/workflows/graph.ts";
import { defaults, errorText, props, settingLabel } from "../src/workflows/schema.ts";

const names: Names = {
  user: (id) => (id === "u1" ? "Ada" : undefined),
  tag: (v) => (v === "t1" || v.toLowerCase() === "vip" ? "VIP" : undefined),
  channel: (id) => (id === "c1" ? "Front desk SMS" : undefined),
  stage: (id) => (id === "s1" ? "Won" : undefined),
  field: (k) => ({ lifecycle: "Lifecycle stage", birthday: "Birthday" })[k],
  form: (id) => (id === "f1" ? "Get a quote" : undefined),
  filter: () => "Lifecycle stage is Customer",
  action: (k) => ({ "tag.add": "Add a tag", "message.send": "Send a message" })[k],
};

test("a step's title is its label, else its action or kind", () => {
  assert.equal(title({ type: "action", action: "tag.add", config: {} }, names), "Add a tag");
  assert.equal(title({ type: "action", action: "tag.add", config: {}, label: "Mark VIP" }, names), "Mark VIP");
  assert.equal(title({ type: "condition", config: {} }), "If / else");
});

test("a step's line says what it does, or what is missing", () => {
  assert.equal(summary({ type: "action", action: "tag.add", config: { tag: "t1" } }, names), 'Add "VIP"');
  assert.equal(summary({ type: "action", action: "tag.add", config: { tag: "0b8a3c1e-1111-4222-8333-944455556666" } }, names), "Add a tag that no longer exists");
  assert.equal(summary({ type: "action", action: "tag.remove", config: {} }, names), "Choose a tag");
  assert.equal(summary({ type: "action", action: "message.send", config: { channel_id: "c1", body: "Hi {{first_name}}" } }, names), 'Front desk SMS: "Hi {{first_name}}"');
  assert.equal(summary({ type: "action", action: "message.send", config: {} }, names), "Choose a channel and write the message");
  assert.equal(summary({ type: "action", action: "owner.assign", config: { round_robin: ["u1", "u2"] } }, names), "Round robin over 2 people");
  assert.equal(summary({ type: "action", action: "task.create", config: { title: "Call", due: { days: 1 }, assignee: "owner" } }, names), `"Call", due in 1 day, for the record's owner`);
  assert.equal(summary({ type: "action", action: "deal.move_stage", config: { stage_id: "s1" } }, names), "To Won");
  assert.equal(summary({ type: "action", action: "webhook.send", config: { url: "https://hooks.example.com/x" } }, names), "POST to hooks.example.com");
  assert.equal(summary({ type: "action", action: "record.update", config: { values: { lifecycle: "customer" } } }, names), "Set Lifecycle stage");
  assert.equal(summary({ type: "wait", config: { duration: { days: 2 } } }), "For 2 days");
  assert.equal(summary({ type: "wait", config: { until_field: { field: "birthday", offset: { days: -1 }, at: "09:00" } } }, names), "Until 1 day before Birthday");
  assert.equal(summary({ type: "wait", config: { event: { event: "form.submitted", timeout: { days: 3 } } } }), "Until form submitted, at most 3 days");
  assert.equal(summary({ type: "condition", config: { filter: {} } }, names), "Set the condition");
  assert.equal(summary({ type: "condition", config: { filter: { tag: "vip" } } }, names), "If Lifecycle stage is Customer");
  assert.equal(summary({ type: "goal", config: { filter: { tag: "vip" }, otherwise: "end" } }, names), "When Lifecycle stage is Customer; reaching it otherwise ends the run");
  assert.equal(summary({ type: "split", config: { paths: [{ name: "a", percent: 70 }, { name: "b", percent: 30 }] } }), "a 70%, b 30%");
});

test("the trigger in a line, and branches in words", () => {
  assert.equal(triggerSummary({ event: "form.submitted", data: { form_id: "f1" }, filter: { tag: "vip" } }, names), "Form submitted (Get a quote), when Lifecycle stage is Customer");
  assert.equal(triggerSummary({ event: "tag.added", data: {}, filter: {} }, names), "Tag added");
  assert.equal(branchLabel({ type: "condition", config: {} }, "no"), "No");
  assert.equal(branchLabel({ type: "wait", config: { event: {} } }, "timeout"), "If it times out");
  assert.equal(branchLabel({ type: "split", config: { paths: [{ name: "a", percent: 50 }] } }, "a"), "Path a (50%)");
});

test("events in words, and which records they can start", () => {
  assert.equal(eventLabel("booking.created"), "Appointment booked");
  assert.equal(eventLabel("thing.happened_now"), "Thing happened now");
  assert.equal(eventHelp("A record was created. `data` is its full state. Subject: the record."), "A record was created.");
  assert.equal(eventHelp("A reminder came due, `offset_minutes` before its start. More."), "A reminder came due, offset_minutes before its start.");
  assert.deepEqual(objectsFor("contact_id", "form.submitted", ["contact", "deal"]), ["contact"]);
  assert.deepEqual(objectsFor("subject", "deal.stage_changed", ["contact", "deal"]), ["deal"]);
  assert.deepEqual(objectsFor("subject", "record.created", ["contact", "deal"]), ["contact", "deal"]);
});

// what pydantic writes for SendMessage and CreateTask
const send: JsonSchema = {
  additionalProperties: false,
  properties: {
    channel_id: { format: "uuid", title: "Channel Id", type: "string" },
    body: { maxLength: 5000, minLength: 1, title: "Body", type: "string" },
    subject: { anyOf: [{ maxLength: 500, type: "string" }, { type: "null" }], default: null, title: "Subject" },
    if_refused: { default: "fail", enum: ["fail", "skip"], title: "If Refused", type: "string" },
  },
  required: ["channel_id", "body"],
};
const task: JsonSchema = {
  properties: {
    title: { maxLength: 300, minLength: 1, type: "string", title: "Title" },
    due: { anyOf: [{ additionalProperties: { type: "integer" }, maxProperties: 1, minProperties: 1, propertyNames: { enum: ["minutes", "hours", "days", "weeks"] }, type: "object" }, { type: "null" }], default: null },
    assignee: { anyOf: [{ type: "string" }, { type: "null" }], default: "owner" },
    priority: { default: "none", enum: ["none", "low", "medium", "high"], type: "string" },
  },
  required: ["title"],
};

test("each setting gets a control from its schema, and a picker where it names something", () => {
  const p = props(send);
  assert.deepEqual(p.map((x) => [x.key, x.kind, x.widget ?? null, x.required, x.nullable]), [
    ["channel_id", "uuid", "channel", true, false],
    ["body", "long_text", null, true, false],
    ["subject", "text", null, false, true],
    ["if_refused", "choice", null, false, false],
  ]);
  assert.equal(p[0]!.label, "Channel");
  assert.equal(p[3]!.label, "If consent says no");
  const t = props(task);
  assert.deepEqual(t.map((x) => [x.key, x.kind, x.widget ?? null]), [["title", "text", null], ["due", "offset", null], ["assignee", "text", "person"], ["priority", "choice", null]]);
  assert.deepEqual(props({ properties: { user_id: { anyOf: [{ format: "uuid", type: "string" }, { type: "null" }] } } }).map((x) => x.widget), ["user"]);
  assert.deepEqual(props({ properties: { values: { type: "object", patternProperties: { "^[a-z]+$": {} } } } }).map((x) => x.kind), ["fields"]);
  assert.deepEqual(props({ properties: { payload: { type: "object", additionalProperties: { type: "string" } } } }).map((x) => x.kind), ["map"]);
});

test("a new step starts with the schema's defaults", () => {
  assert.deepEqual(defaults(send), { if_refused: "fail" });
  assert.deepEqual(defaults(task), { assignee: "owner", priority: "none" });
});

test("the server's errors read as sentences", () => {
  assert.equal(settingLabel("config.channel_id"), "Channel");
  assert.equal(errorText("config.channel_id", "is required"), "Channel is required");
  assert.equal(errorText("config.body", "uses {{x}}, which is not a field of contact"), "Message uses {{x}}, which is not a field of contact");
  assert.equal(errorText("config.values.email", "Email must be an email"), "Fields to set: Email must be an email");
  assert.equal(errorText("", "is not reachable: nothing leads to it"), "Is not reachable: nothing leads to it");
  assert.equal(errorText("config.duration", "give exactly one of duration, until_field and event"), "How long: give exactly one of duration, until_field and event");
});
