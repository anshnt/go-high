// The form logic evaluator and the quiz scorer must agree with the server. The cases are the shared fixtures that
// backend/tests/test_forms_logic.py runs too: change one, and both sides have to give the new answer.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { check } from "../src/forms-runtime/check.ts";
import { flow, holds } from "../src/forms-runtime/logic.ts";
import { score } from "../src/forms-runtime/quiz.ts";
import type { Definition, Field } from "../src/forms-runtime/types.ts";

const fixtures = JSON.parse(readFileSync(new URL("../../backend/tests/fixtures/form_logic.json", import.meta.url), "utf8"));

test("the fixtures are there and are not trivially few", () => {
  assert.ok(fixtures.conditions.length >= 40 && fixtures.flows.length >= 14 && fixtures.quizzes.length >= 9);
});

for (const c of fixtures.conditions) {
  test(`condition: ${c.name}`, () => assert.equal(holds(c.when, c.answers), c.expect));
}

for (const c of fixtures.flows) {
  test(`flow: ${c.name}`, () => {
    const fl = flow(c.definition, c.answers);
    assert.deepEqual({ path: fl.steps, ended: fl.ended, answers: fl.answers }, c.expect);
  });
}

for (const c of fixtures.quizzes) {
  test(`quiz: ${c.name}`, () => {
    const defn = c.definition as Definition;
    const fl = flow(defn, c.answers);
    const result = score(defn, fl, fl.answers);
    if (c.expect === null) return assert.equal(result, null);
    const { band, ...rest } = result!;
    const { band: title, ...expect } = c.expect;
    assert.equal(band?.title ?? null, title);
    assert.deepEqual(rest, expect);
  });
}

const field = (type: Field["type"], extra: Partial<Field> = {}): Field => ({ key: "k", type, label: "Thing", ...extra });

test("an empty optional answer is fine, an empty required one is not", () => {
  assert.equal(check(field("short_text"), ""), null);
  assert.equal(check(field("short_text", { required: true }), "  "), "Thing is required");
  assert.equal(check(field("consent", { required: true }), false), "This box must be ticked");
  assert.equal(check(field("yes_no", { required: true }), false), null); // a "no" is an answer
  assert.equal(check(field("checkbox"), false), null);
});

test("formats are checked where they are typed", () => {
  assert.equal(check(field("email"), "ada@example.com"), null);
  assert.match(check(field("email"), "ada@")!, /not an email address/);
  assert.match(check(field("phone"), "12")!, /not a phone number/);
  assert.match(check(field("short_text", { validation: { max_length: 3 } }), "abcd")!, /at most 3/);
  assert.match(check(field("short_text", { validation: { min_length: 3 } }), "ab")!, /at least 3/);
  assert.match(check(field("number", { validation: { min: 18 } }), 17)!, /at least 18/);
  assert.match(check(field("number", { validation: { integer: true } }), 2.5)!, /whole number/);
  assert.match(check(field("rating"), 6)!, /at most 5/);
  assert.match(check(field("date"), "18/10/2026")!, /date/);
  assert.equal(check(field("date"), "2026-10-18"), null);
});

test("choices must be among the options", () => {
  const options = [{ id: "a", label: "A" }, { id: "b", label: "B" }];
  assert.equal(check(field("select", { options }), "a"), null);
  assert.match(check(field("select", { options }), "z")!, /choices/);
  assert.equal(check(field("multi_select", { options, validation: { min_items: 2 } }), ["a", "b"]), null);
  assert.match(check(field("multi_select", { options, validation: { min_items: 2 } }), ["a"])!, /at least 2/);
  assert.match(check(field("multi_select", { options, validation: { max_items: 1 } }), ["a", "b"])!, /more than 1/);
});
