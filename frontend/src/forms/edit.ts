// Editing a form definition as plain data: every function takes a definition and returns a changed copy, so the builder
// can keep history and compare for unsaved changes. No React in here, so node can test it.
import { ANSWERABLE } from "../forms-runtime/logic.ts";
import type { Condition, Definition, Field, FieldType, Rule, Step } from "../forms-runtime/types.ts";

export const DEFAULT_LABEL: Record<FieldType, string> = {
  short_text: "Short answer", long_text: "Long answer", email: "Email", phone: "Phone", number: "Number", select: "Choose one",
  multi_select: "Choose any", checkbox: "Checkbox", date: "Date", rating: "Rating", yes_no: "Yes or no", hidden: "Hidden value",
  consent: "I agree to be contacted", heading: "Heading", paragraph: "Some text",
};

const clone = <T,>(x: T): T => structuredClone(x);
function apply(target: object, patch: object) {
  const t = target as Record<string, unknown>;
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) delete t[k];
    else t[k] = v;
  }
}
export const allFields = (def: Definition): Field[] => def.steps.flatMap((s) => s.fields);
export const isCondition = (c: Condition): c is Extract<Condition, { field: string }> => "field" in c;

/** A lower case key from a label: letters, digits and underscores, starting with a letter. */
export function slug(label: string): string {
  const s = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^[0-9_]+/, "").slice(0, 36);
  return s || "field";
}

/** `base`, or `base_2`, `base_3`... whichever no step or field has. */
export function freshKey(def: Definition, base: string): string {
  const taken = new Set([...def.steps.map((s) => s.key), ...allFields(def).map((f) => f.key)]);
  const root = slug(base);
  if (!taken.has(root)) return root;
  for (let n = 2; ; n++) if (!taken.has(`${root}_${n}`)) return `${root}_${n}`;
}

export function newField(def: Definition, type: FieldType): Field {
  const label = DEFAULT_LABEL[type];
  const f: Field = { key: freshKey(def, label), type, label };
  if (type === "select" || type === "multi_select") f.options = [1, 2].map((n) => ({ id: `option_${n}`, label: `Option ${n}` }));
  if (type === "hidden") f.param = f.key;
  if (type === "consent") f.required = true;
  return f;
}

export function locate(def: Definition, key: string): { step: number; index: number } | null {
  for (const [step, s] of def.steps.entries()) {
    const index = s.fields.findIndex((f) => f.key === key);
    if (index >= 0) return { step, index };
  }
  return null;
}

export function addField(def: Definition, stepKey: string, field: Field, index?: number): Definition {
  const d = clone(def);
  const step = d.steps.find((s) => s.key === stepKey) ?? d.steps[d.steps.length - 1]!;
  step.fields.splice(index ?? step.fields.length, 0, field);
  return d;
}

export function updateField(def: Definition, key: string, patch: Partial<Field>): Definition {
  const d = clone(def);
  const f = allFields(d).find((x) => x.key === key);
  if (f) apply(f, patch);
  return d;
}

export function updateStep(def: Definition, key: string, patch: Partial<Step>): Definition {
  const d = clone(def);
  const s = d.steps.find((x) => x.key === key);
  if (s) apply(s, patch);
  return d;
}

/** Moves a field to `toIndex` of a step (an index in that step's list after the field has been taken out). */
export function moveField(def: Definition, key: string, toStepKey: string, toIndex: number): Definition {
  const at = locate(def, key);
  if (!at) return def;
  const d = clone(def);
  const [field] = d.steps[at.step]!.fields.splice(at.index, 1);
  const target = d.steps.find((s) => s.key === toStepKey) ?? d.steps[at.step]!;
  target.fields.splice(Math.max(0, Math.min(toIndex, target.fields.length)), 0, field!);
  return d;
}

/** One place up or down, crossing into the neighbouring step at the ends. */
export function nudgeField(def: Definition, key: string, dir: -1 | 1): Definition {
  const at = locate(def, key);
  if (!at) return def;
  const here = def.steps[at.step]!;
  const to = at.index + dir;
  if (to >= 0 && to < here.fields.length) return moveField(def, key, here.key, to);
  const next = def.steps[at.step + dir];
  return next ? moveField(def, key, next.key, dir < 0 ? next.fields.length : 0) : def;
}

export function duplicateField(def: Definition, key: string): Definition {
  const at = locate(def, key);
  if (!at) return def;
  const copy = clone(def.steps[at.step]!.fields[at.index]!);
  copy.key = freshKey(def, `${copy.key}_copy`);
  copy.label = `${copy.label} (copy)`;
  if (copy.param) copy.param = copy.key;
  return addField(def, def.steps[at.step]!.key, copy, at.index + 1);
}

export function removeField(def: Definition, key: string): Definition {
  const at = locate(def, key);
  if (!at) return def;
  const d = clone(def);
  d.steps[at.step]!.fields.splice(at.index, 1);
  return prune(d);
}

export function addStep(def: Definition, afterKey?: string): Definition {
  const d = clone(def);
  const at = afterKey ? d.steps.findIndex((s) => s.key === afterKey) : d.steps.length - 1;
  d.steps.splice(at + 1, 0, { key: freshKey(d, "step"), title: "", fields: [] });
  return d;
}

export function moveStep(def: Definition, key: string, dir: -1 | 1): Definition {
  const i = def.steps.findIndex((s) => s.key === key);
  if (i < 0 || i + dir < 0 || i + dir >= def.steps.length) return def;
  const d = clone(def);
  [d.steps[i], d.steps[i + dir]] = [d.steps[i + dir]!, d.steps[i]!];
  return d;
}

export function removeStep(def: Definition, key: string): Definition {
  if (def.steps.length < 2) return def;
  const d = clone(def);
  d.steps = d.steps.filter((s) => s.key !== key);
  return prune(d);
}

const refs = (c: Condition): string[] => ("and" in c ? c.and.flatMap(refs) : "or" in c ? c.or.flatMap(refs) : "not" in c ? refs(c.not) : [c.field]);

/** Drops what points at something that no longer exists: tests of a removed question, rules of a removed step. */
export function prune(def: Definition): Definition {
  const d = clone(def);
  const keys = new Set([...d.steps.map((s) => s.key), ...allFields(d).map((f) => f.key)]);
  const steps = new Set(d.steps.map((s) => s.key));
  const cut = (c: Condition): Condition | null => {
    if ("and" in c || "or" in c) {
      const list = ("and" in c ? c.and : c.or).map(cut).filter((x): x is Condition => x !== null);
      return list.length === 0 ? null : "and" in c ? { and: list } : { or: list };
    }
    if ("not" in c) {
      const inner = cut(c.not);
      return inner && { not: inner };
    }
    return keys.has(c.field) ? c : null;
  };
  d.logic = (d.logic ?? []).flatMap((r) => {
    const ok = r.do === "show" || r.do === "hide" ? keys.has(r.target ?? "") : steps.has(r.from ?? "") && (r.do === "end" || steps.has(r.target ?? ""));
    const when = ok ? cut(r.when) : null;
    return when ? [{ ...r, when }] : [];
  });
  if (d.logic.length === 0) delete d.logic;
  return d;
}

const position = (def: Definition) => {
  const where = new Map<string, [number, number]>();
  for (const [i, s] of def.steps.entries()) {
    where.set(s.key, [i, -1]);
    for (const [j, f] of s.fields.entries()) where.set(f.key, [i, j]);
  }
  return where;
};
const before = (a: [number, number], b: [number, number]) => a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]);

/** The questions a rule may test: answerable ones that come before what the rule controls. */
export function earlierFields(def: Definition, r: Pick<Rule, "do" | "target" | "from">): Field[] {
  const where = position(def);
  let limit: [number, number] | undefined;
  if (r.do === "show" || r.do === "hide") limit = where.get(r.target ?? "");
  else {
    const i = def.steps.findIndex((s) => s.key === r.from);
    if (i >= 0) limit = [i + 1, -1];
  }
  return limit ? allFields(def).filter((f) => ANSWERABLE.has(f.type) && before(where.get(f.key)!, limit!)) : [];
}

/** For each rule (by index) why the server would refuse it, as the builder can tell from the structure alone. */
export function problems(def: Definition): Record<number, string> {
  const where = position(def);
  const out: Record<number, string> = {};
  (def.logic ?? []).forEach((r: Rule, i) => {
    const step = (k?: string) => def.steps.findIndex((s) => s.key === k);
    let limit: [number, number] | undefined;
    if (r.do === "show" || r.do === "hide") limit = where.get(r.target ?? "");
    else {
      const from = step(r.from);
      if (from >= 0) limit = [from + 1, -1];
      if (r.do === "jump" && (step(r.target) < 0 || step(r.target) <= from)) out[i] = "A jump must go to a step after the one it leaves.";
    }
    if (!limit) return void (out[i] ??= "This rule points at something that was removed.");
    for (const f of refs(r.when)) {
      const at = where.get(f);
      if (!at) out[i] ??= "A question this rule uses was removed.";
      else if (!before(at, limit)) out[i] ??= "This rule uses an answer that comes after what it controls.";
    }
  });
  return out;
}

const OP_TEXT: Record<string, string> = { is: "is", is_not: "is not", contains: "contains", in: "is one of", not_in: "is none of", gt: "is above", gte: "is at least", lt: "is below", lte: "is at most", is_empty: "is empty", is_not_empty: "is filled in" };

/** A short sentence for a condition, for the logic map and the rule list. */
export function summarize(c: Condition, def: Definition): string {
  if ("and" in c) return c.and.map((x) => summarize(x, def)).join(" and ");
  if ("or" in c) return c.or.map((x) => summarize(x, def)).join(" or ");
  if ("not" in c) return `not (${summarize(c.not, def)})`;
  const f = allFields(def).find((x) => x.key === c.field);
  const show = (v: unknown) => (typeof v === "boolean" ? (v ? "yes" : "no") : f?.options?.find((o) => o.id === v)?.label ?? String(v));
  const value = c.op === "is_empty" || c.op === "is_not_empty" ? "" : ` ${Array.isArray(c.value) ? c.value.map(show).join(", ") : show(c.value)}`;
  return `${f?.label ?? c.field} ${OP_TEXT[c.op] ?? c.op}${value}`;
}

export const stepNumber = (def: Definition, key: string) => def.steps.findIndex((s) => s.key === key) + 1;
