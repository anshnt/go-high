// The builder edits a form definition as plain data. These checks keep the edits safe: keys stay unique, a removed
// question takes the rules that used it along, and a rule that the server would refuse is flagged before saving.
import assert from "node:assert/strict";
import { test } from "node:test";
import { addField, addStep, allFields, duplicateField, freshKey, moveField, moveStep, newField, nudgeField, problems, prune, removeField, removeStep, slug, summarize, updateField } from "../src/forms/edit.ts";
import type { Definition } from "../src/forms-runtime/types.ts";

const def = (): Definition => ({
  steps: [
    { key: "s1", title: "One", fields: [{ key: "size", type: "select", label: "Size", options: [{ id: "big", label: "Big" }, { id: "small", label: "Small" }] }, { key: "note", type: "short_text", label: "Note" }] },
    { key: "s2", title: "Two", fields: [{ key: "detail", type: "short_text", label: "Detail" }] },
    { key: "s3", title: "Three", fields: [{ key: "email", type: "email", label: "Email" }] },
  ],
  logic: [
    { id: "r1", do: "jump", from: "s1", target: "s3", when: { field: "size", op: "is", value: "big" } },
    { id: "r2", do: "hide", target: "detail", when: { and: [{ field: "size", op: "is", value: "small" }, { field: "note", op: "is_not_empty" }] } },
  ],
});
const keys = (d: Definition) => d.steps.map((s) => [s.key, s.fields.map((f) => f.key)]);

test("keys come from labels and never repeat across steps and fields", () => {
  assert.equal(slug("Company size!"), "company_size");
  assert.equal(slug("123 go"), "go");
  assert.equal(slug("???"), "field");
  assert.equal(freshKey(def(), "Size"), "size_2");
  assert.equal(freshKey(def(), "s1"), "s1_2"); // a step's key counts too
  const d = addField(def(), "s2", newField(def(), "short_text"));
  const again = addField(d, "s2", newField(d, "short_text"));
  assert.deepEqual(allFields(again).map((f) => f.key).filter((k) => k.startsWith("short_answer")), ["short_answer", "short_answer_2"]);
});

test("new fields start with sensible settings", () => {
  const pick = newField(def(), "select");
  assert.deepEqual(pick.options?.map((o) => o.id), ["option_1", "option_2"]);
  assert.equal(newField(def(), "consent").required, true);
  const hidden = newField(def(), "hidden");
  assert.equal(hidden.param, hidden.key);
});

test("moving a field within and across steps", () => {
  const d = moveField(def(), "note", "s1", 0);
  assert.deepEqual(keys(d)[0], ["s1", ["note", "size"]]);
  const across = moveField(def(), "note", "s3", 1);
  assert.deepEqual(keys(across), [["s1", ["size"]], ["s2", ["detail"]], ["s3", ["email", "note"]]]);
  assert.deepEqual(keys(moveField(def(), "ghost", "s1", 0)), keys(def())); // unknown key: nothing happens
  assert.deepEqual(def().steps[0]!.fields.map((f) => f.key), ["size", "note"]); // the original is untouched
});

test("keyboard nudges cross into the neighbouring step at the ends", () => {
  assert.deepEqual(keys(nudgeField(def(), "size", 1))[0], ["s1", ["note", "size"]]);
  assert.deepEqual(keys(nudgeField(def(), "note", 1)), [["s1", ["size"]], ["s2", ["note", "detail"]], ["s3", ["email"]]]);
  assert.deepEqual(keys(nudgeField(def(), "detail", -1)), [["s1", ["size", "note", "detail"]], ["s2", []], ["s3", ["email"]]]);
  assert.deepEqual(keys(nudgeField(def(), "size", -1)), keys(def())); // the very first place stays
  assert.deepEqual(keys(nudgeField(def(), "email", 1)), keys(def()));
});

test("duplicating a field gives it its own key", () => {
  const d = duplicateField(def(), "note");
  assert.deepEqual(d.steps[0]!.fields.map((f) => f.key), ["size", "note", "note_copy"]);
  assert.equal(d.steps[0]!.fields[2]!.label, "Note (copy)");
});

test("removing a question removes the tests that used it, and rules left with nothing", () => {
  const d = removeField(def(), "note");
  assert.deepEqual(d.logic?.map((r) => r.id), ["r1", "r2"]);
  assert.deepEqual(d.logic![1]!.when, { and: [{ field: "size", op: "is", value: "small" }] }); // one test left
  const gone = removeField(d, "size");
  assert.equal(gone.logic, undefined); // both rules were about it
});

test("removing a step removes the rules that jump from or to it, and the last step stays", () => {
  assert.deepEqual(removeStep(def(), "s3").logic?.map((r) => r.id), ["r2"]);
  assert.deepEqual(removeStep(def(), "s2").logic?.map((r) => r.id), ["r1"]); // the hide rule targeted a field of s2
  const one = { steps: [def().steps[0]!] };
  assert.equal(removeStep(one, "s1").steps.length, 1);
});

test("steps are added after another and moved", () => {
  const d = addStep(def(), "s1");
  assert.deepEqual(d.steps.map((s) => s.key), ["s1", "step", "s2", "s3"]);
  assert.deepEqual(addStep(def()).steps.map((s) => s.key), ["s1", "s2", "s3", "step"]);
  assert.deepEqual(moveStep(def(), "s3", -1).steps.map((s) => s.key), ["s1", "s3", "s2"]);
  assert.deepEqual(moveStep(def(), "s1", -1).steps.map((s) => s.key), ["s1", "s2", "s3"]);
});

test("rules that the server would refuse are flagged", () => {
  assert.deepEqual(problems(def()), {});
  const moved = moveStep(def(), "s3", -1); // order s1, s3, s2: the jump from s1 to s3 still goes forward
  assert.deepEqual(problems(moved), {});
  const back = moveStep(def(), "s1", 1); // order s2, s1, s3: the hide rule on a question of s2 now uses answers from a later step
  assert.match(problems(back)[1]!, /comes after/);
  const field = moveField(def(), "size", "s3", 1); // the question the jump tests moves behind the step it leaves
  assert.match(problems(field)[0]!, /comes after/);
  const broken: Definition = { ...def(), logic: [{ id: "x", do: "jump", from: "s2", target: "s1", when: { field: "size", op: "is", value: "big" } }] };
  assert.match(problems(broken)[0]!, /after the one it leaves/);
  const ghost: Definition = { ...def(), logic: [{ id: "x", do: "hide", target: "nope", when: { field: "size", op: "is", value: "big" } }] };
  assert.match(problems(ghost)[0]!, /removed/);
});

test("prune keeps what is still valid and is a copy", () => {
  const d = def();
  assert.deepEqual(prune(d), d);
  assert.notEqual(prune(d), d);
});

test("conditions read as sentences", () => {
  const d = def();
  assert.equal(summarize(d.logic![0]!.when, d), "Size is Big");
  assert.equal(summarize(d.logic![1]!.when, d), "Size is Small and Note is filled in");
  assert.equal(summarize({ not: { field: "size", op: "in", value: ["big", "small"] } }, d), "not (Size is one of Big, Small)");
  assert.equal(summarize({ field: "gone", op: "is_empty" }, d), "gone is empty");
});

test("updating a field changes only that field, and undefined removes a setting", () => {
  const d = updateField(def(), "note", { required: true, help: "Say more" });
  assert.equal(allFields(d).find((f) => f.key === "note")?.required, true);
  const cleared = updateField(d, "note", { help: undefined });
  assert.equal(allFields(cleared).find((f) => f.key === "note")?.help, undefined);
  assert.equal(allFields(def()).find((f) => f.key === "note")?.required, undefined);
});
