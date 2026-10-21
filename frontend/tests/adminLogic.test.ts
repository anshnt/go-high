import assert from "node:assert/strict";
import { test } from "node:test";
import {
  accessOf,
  actorLabel,
  capabilityWarnings,
  changesOf,
  dayBound,
  emptyField,
  exportName,
  families,
  fieldBody,
  fieldErrors,
  draftOf,
  groupCatalog,
  keyFrom,
  move,
  normalizeRules,
  objectKeyFrom,
  placeServerErrors,
  pluralOf,
  rangeError,
  readFilters,
  roleChanges,
  ruleFor,
  sameRole,
  subjectLabel,
  subscriptionText,
  subtree,
  teamPath,
  teamTree,
  withAccess,
  withScope,
  type Rule,
} from "../src/admin/logic.ts";

const any = (scope: Rule["scope"] = "all"): Rule => ({ object_key: "*", scope, hidden_fields: [], readonly_fields: [] });

test("a field's access comes from its object's own rule, and setting one gives the object a rule with the * scope", () => {
  const rules = [any("team")];
  assert.equal(ruleFor(rules, "deal")?.object_key, "*");
  const next = withAccess(rules, "deal", "amount", "hidden");
  const deal = next.find((r) => r.object_key === "deal")!;
  assert.deepEqual(deal, { object_key: "deal", scope: "team", hidden_fields: ["amount"], readonly_fields: [] });
  assert.equal(accessOf(deal, "amount"), "hidden");
  const locked = withAccess(next, "deal", "amount", "readonly");
  assert.equal(accessOf(locked.find((r) => r.object_key === "deal"), "amount"), "readonly");
  const free = withAccess(locked, "deal", "amount", "edit");
  assert.equal(accessOf(free.find((r) => r.object_key === "deal"), "amount"), "edit");
  assert.equal(next.length, 2);
  assert.equal(withAccess([], "deal", "x", "hidden")[0]!.scope, "none"); // no rule at all sees nothing
});

test("scopes are set per object and removing one falls back to *", () => {
  const rules = withScope([any()], "contact", "own");
  assert.equal(ruleFor(rules, "contact")?.scope, "own");
  assert.equal(ruleFor(withScope(rules, "contact", null), "contact")?.scope, "all");
  assert.deepEqual(withScope(rules, "*", null), [rules[1]]);
});

test("a draft compares equal to the saved role whatever the order, and its changes are said in words", () => {
  const saved = { name: "Rep", description: "", capabilities: ["a.read", "b.read"], object_rules: [any(), { object_key: "deal", scope: "team" as const, hidden_fields: ["x", "y"], readonly_fields: [] }] };
  const same = { ...saved, name: " Rep ", capabilities: ["b.read", "a.read"], object_rules: [{ ...saved.object_rules[1]!, hidden_fields: ["y", "x"] }, any()] };
  assert.ok(sameRole(saved, same));
  assert.deepEqual(normalizeRules(same.object_rules), normalizeRules(saved.object_rules));
  const edited = { ...saved, capabilities: ["a.read", "c.write", "d.write"], object_rules: [any("own")] };
  assert.ok(!sameRole(saved, edited));
  assert.deepEqual(roleChanges(saved, edited), ["2 capabilities added", "1 capability removed", "record access"]);
});

test("acting on records without seeing them is flagged", () => {
  assert.deepEqual(capabilityWarnings(["contacts.read", "contacts.write"]), []);
  assert.match(capabilityWarnings(["deals.write", "deals.export"])[0]!, /^Deals: create and edit, export without see/);
  assert.equal(capabilityWarnings(["members.manage"]).length, 1);
});

test("the catalog groups by module in first-seen order", () => {
  const g = groupCatalog([{ module: "B", c: 1 }, { module: "A", c: 2 }, { module: "B", c: 3 }]);
  assert.deepEqual(g.map((x) => [x.module, x.items.length]), [["B", 2], ["A", 1]]);
});

const T = (id: string, name: string, parent: string | null = null) => ({ id, name, parent_team_id: parent });

test("teams come in tree order with depth, and a team cannot move under its own subtree", () => {
  const teams = [T("w", "West", "s"), T("s", "Sales"), T("e", "East", "s"), T("i", "Inside", "e"), T("o", "Ops"), T("x", "Orphan", "gone")];
  assert.deepEqual(teamTree(teams).map(({ team, depth }) => `${depth}${team.name}`), ["0Ops", "0Orphan", "0Sales", "1East", "2Inside", "1West"]);
  assert.deepEqual([...subtree(teams, "s")].sort(), ["e", "i", "s", "w"]);
  assert.equal(teamPath(teams, "i"), "Sales / East / Inside");
  const loop = [T("a", "A", "b"), T("b", "B", "a")];
  assert.equal(teamTree(loop).length, 2); // a cycle never hangs or drops a team
  assert.equal(teamPath(loop, "a"), "B / A");
});

test("filters from the address keep only well formed values, and days become inclusive bounds", () => {
  const q = new URLSearchParams({ actor: "not-an-id", subject: "6f1c3c6e-2b0a-4c8e-9d3f-0a1b2c3d4e5f", type: "record.*", from: "2026-10-01", to: "yesterday", status: "nope" });
  assert.deepEqual(readFilters(q, ["actor", "subject", "type", "from", "to", "status"]), { subject: "6f1c3c6e-2b0a-4c8e-9d3f-0a1b2c3d4e5f", type: "record.*", from: "2026-10-01" });
  assert.deepEqual(readFilters(new URLSearchParams({ type: "Record.updated" }), ["type"]), {});
  const start = new Date(dayBound("2026-10-20", "start")!);
  const end = new Date(dayBound("2026-10-20", "end")!);
  assert.equal(end.getTime() - start.getTime(), 24 * 3600 * 1000 - 1);
  assert.equal(start.getHours(), 0);
  assert.equal(dayBound("20-10-2026", "start"), undefined);
  assert.equal(rangeError("2026-10-02", "2026-10-01"), "The start date is after the end date.");
  assert.equal(rangeError("2026-10-01", "2026-10-01"), undefined);
});

test("event types group by family and a subscription reads as words", () => {
  assert.deepEqual(families(["tag.added", "record.updated", "record.created"]), [
    { family: "record", types: ["record.created", "record.updated"] },
    { family: "tag", types: ["tag.added"] },
  ]);
  assert.equal(subscriptionText(["*"]), "Every event");
  assert.equal(subscriptionText(["a.b", "c.d"]), "a.b and c.d");
  assert.equal(subscriptionText(["a.b", "c.d", "e.f", "g.h"]), "4 events: a.b, c.d and 2 more");
});

test("audit events read as who and what", () => {
  const names = new Map([["u1", "Ada"]]);
  const e = (over: object) => ({ type: "record.updated", subject: { type: "record", id: "r1" }, actor: { type: "user", id: "u1" }, data: {}, ...over });
  assert.equal(actorLabel(e({}), names), "Ada");
  assert.equal(actorLabel(e({ actor: { type: "user", id: "u9" } }), names), "A former member");
  assert.equal(actorLabel(e({ actor: { type: "workflow", id: "w" } }), names), "A workflow");
  assert.equal(actorLabel(e({ actor: { type: "system", id: null } }), names), "The system");
  assert.equal(subjectLabel(e({ data: { display_name: "Grace", object: "contact" } })), "Grace (contact)");
  assert.equal(subjectLabel(e({ type: "tag.added", data: { name: "VIP", object: "deal" } })), "tag VIP on a deal");
  assert.equal(subjectLabel(e({ type: "role.updated", subject: { type: "role", id: "x" }, data: { name: "Rep" } })), "role Rep");
  assert.equal(subjectLabel(e({ type: "member.role_changed", subject: { type: "user", id: "u1" } }), names), "Ada");
  assert.deepEqual(changesOf({ changes: { b: { old: 1, new: 2 }, a: { old: null, new: "x" } } }), [
    { field: "a", old: null, new: "x" },
    { field: "b", old: 1, new: 2 },
  ]);
  assert.deepEqual(changesOf({ changes: ["nope"] }), []);
  assert.equal(exportName({ type: "record.*", from: "2026-10-01" }, new Date(2026, 9, 20)), "audit-2026-10-20-record.all-from-2026-10-01.csv");
  assert.equal(exportName({}, new Date(2026, 0, 5)), "audit-2026-01-05.csv");
});

test("keys come from labels and names", () => {
  assert.equal(keyFrom("Lead source"), "lead_source");
  assert.equal(keyFrom("Été 2026!"), "ete_2026");
  assert.equal(keyFrom("2nd phone"), "f_2nd_phone");
  assert.equal(keyFrom("x".repeat(80)).length, 63);
  assert.equal(objectKeyFrom("Insurance policy"), "insurance_policy");
  assert.equal(pluralOf("Property"), "Properties");
  assert.equal(pluralOf("Box"), "Boxes");
  assert.equal(pluralOf("Vehicle"), "Vehicles");
});

test("a field draft is checked like the server checks it", () => {
  const d = { ...emptyField("text"), label: "Notes", key: "notes" };
  assert.deepEqual(fieldErrors(d, { creating: true, taken: [] }), {});
  assert.equal(fieldErrors({ ...d, key: "Notes" }, { creating: true, taken: [] }).key?.startsWith("Lower case"), true);
  assert.match(fieldErrors({ ...d, key: "owner_id" }, { creating: true, taken: [] }).key!, /built-in/);
  assert.match(fieldErrors(d, { creating: true, taken: ["notes"] }).key!, /archived/);
  assert.deepEqual(fieldErrors({ ...d, key: "" }, { creating: false, taken: [] }), {}); // the key is fixed once made
  assert.match(fieldErrors({ ...d, max_length: "5000" }, { creating: true, taken: [] }).max_length!, /at most 1000/);
  assert.match(fieldErrors({ ...d, min_length: "9", max_length: "3" }, { creating: true, taken: [] }).max_length!, /minimum/);
  const money = { ...emptyField("money"), label: "Price", key: "price", min: "1.5", currency: "us" };
  const errs = fieldErrors(money, { creating: true, taken: [] });
  assert.match(errs.min!, /cents/);
  assert.match(errs.currency!, /ISO 4217/);
  const select = { ...emptyField("select"), label: "Status", key: "status" };
  assert.match(fieldErrors(select, { creating: true, taken: [] }).choices!, /at least one/);
  assert.match(fieldErrors({ ...select, choices: [{ label: "A" }, { label: "a" }] }, { creating: true, taken: [] }).choices!, /same label/);
  assert.match(fieldErrors({ ...emptyField("record"), label: "Owner", key: "owner" }, { creating: true, taken: [] }).object!, /Pick/);
  assert.match(fieldErrors({ ...emptyField("phone"), label: "P", key: "p", region: "USA" }, { creating: true, taken: [] }).region!, /two letter/);
});

test("a draft becomes the options and rules the API takes, and a saved field becomes a draft again", () => {
  const select = { ...emptyField("multi_select"), label: "Tags", key: "tags2", required: true, max_items: "3", choices: [{ id: "a", label: " A ", color: "blue" }, { label: "B" }, { label: "  " }] };
  assert.deepEqual(fieldBody(select), { options: { choices: [{ id: "a", label: "A", color: "blue" }, { label: "B" }] }, rules: { required: true, max_items: 3 } });
  const num = { ...emptyField("number"), integer: true, min: "0", max: "" };
  assert.deepEqual(fieldBody(num), { options: {}, rules: { min: 0, integer: true } });
  assert.deepEqual(fieldBody({ ...emptyField("money"), currency: "eur" }), { options: { currency: "EUR" }, rules: {} });
  assert.deepEqual(fieldBody({ ...emptyField("text"), min: "3", timezone: true }).rules, { timezone: true }); // only the type's own rules
  const back = draftOf({ key: "tags2", label: "Tags", type: "multi_select", options: { choices: [{ id: "a", label: "A" }] }, rules: { required: true, max_items: 3 } });
  assert.equal(back.max_items, "3");
  assert.equal(back.required, true);
  assert.deepEqual(back.choices, [{ id: "a", label: "A", color: undefined }]);
});

test("server errors about settings land on the right input", () => {
  assert.deepEqual(placeServerErrors({ options: "currency 'XX' is not an ISO 4217 code" }), { currency: "Currency 'XX' is not an ISO 4217 code" });
  assert.deepEqual(placeServerErrors({ rules: "max_length must be a number" }), { max_length: "Max_length must be a number" });
  assert.deepEqual(placeServerErrors({ "values.x": "bad" }), { values: "Bad" });
});

test("moving an item clamps at the ends and leaves the list alone when nothing moves", () => {
  const list = ["a", "b", "c"];
  assert.deepEqual(move(list, 2, 0), ["c", "a", "b"]);
  assert.deepEqual(move(list, 0, 1), ["b", "a", "c"]);
  assert.equal(move(list, 0, -1), list);
  assert.equal(move(list, 5, 0), list);
  assert.deepEqual(move(list, 1, 9), ["a", "c", "b"]);
});
