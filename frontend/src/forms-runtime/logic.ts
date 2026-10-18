// Form logic in the browser: the same rules as backend/app/forms/logic.py, line by line. The shared cases in
// backend/tests/fixtures/form_logic.json are run by both sides (tests/forms-logic.test.ts here, pytest there).
import type { Answers, Condition, Definition, Field, Flow, Rule } from "./types.ts";

export const ANSWERABLE = new Set(["short_text", "long_text", "email", "phone", "hidden", "number", "select", "multi_select", "checkbox", "date", "rating", "yes_no", "consent"]);

const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const norm = (x: unknown) => (typeof x === "string" ? x.trim().toLowerCase() : x);

export const empty = (x: unknown) => x == null || (Array.isArray(x) && x.length === 0) || (typeof x === "string" && x.trim() === "");

/** Whether `raw` counts as an answer to `f`: an unticked checkbox is no answer, a "no" is one. */
export const present = (f: Field, raw: unknown) => !empty(raw) && !((f.type === "checkbox" || f.type === "consent") && raw === false);

export function same(a: unknown, v: unknown): boolean {
  if (Array.isArray(a)) {
    if (!Array.isArray(v)) return false;
    const keys = (xs: unknown[]) => xs.map(norm).map(String).sort();
    const [x, y] = [keys(a), keys(v)];
    return x.length === y.length && x.every((k, i) => k === y[i]);
  }
  if (typeof a === "boolean" || typeof v === "boolean") return a === v;
  if (isNum(a) && isNum(v)) return a === v;
  return norm(a) === norm(v);
}

const contains = (a: unknown, v: unknown) => (Array.isArray(a) ? a.some((item) => same(item, v)) : typeof a === "string" && typeof v === "string" && String(norm(a)).includes(String(norm(v))));
const among = (a: unknown, values: unknown) => (Array.isArray(a) ? a : [a]).some((item) => (values as unknown[]).some((v) => same(item, v)));

function order(a: unknown, v: unknown): number | null {
  if ((isNum(a) && isNum(v)) || (typeof a === "string" && typeof v === "string")) return a > v ? 1 : a < v ? -1 : 0;
  return null;
}

export function holds(cond: Condition, answers: Answers): boolean {
  if ("and" in cond) return cond.and.every((c) => holds(c, answers));
  if ("or" in cond) return cond.or.some((c) => holds(c, answers));
  if ("not" in cond) return !holds(cond.not, answers);
  const a = answers[cond.field];
  const { op, value: v } = cond;
  if (op === "is_empty") return empty(a);
  if (op === "is_not_empty") return !empty(a);
  if (empty(a)) return op === "is_not" || op === "not_in";
  const o = op === "gt" || op === "gte" || op === "lt" || op === "lte" ? order(a, v) : null;
  switch (op) {
    case "is":
      return same(a, v);
    case "is_not":
      return !same(a, v);
    case "contains":
      return contains(a, v);
    case "in":
      return among(a, v);
    case "not_in":
      return !among(a, v);
    case "gt":
      return o !== null && o > 0;
    case "gte":
      return o !== null && o >= 0;
    case "lt":
      return o !== null && o < 0;
    default:
      return o !== null && o <= 0;
  }
}

/** Walks the steps for these answers: hidden steps and fields are skipped, a jump goes to a later step, an end rule
 * finishes the form. Conditions only see the answers of fields that are visible. */
export function flow(defn: Definition, answers: Answers): Flow {
  const steps = defn.steps;
  const index = new Map(steps.map((s, i) => [s.key, i]));
  const reveal = new Map<string, Rule[]>();
  const leave = new Map<string, Rule[]>();
  for (const r of defn.logic ?? []) {
    const [map, key] = r.do === "jump" || r.do === "end" ? [leave, r.from!] : [reveal, r.target!];
    map.set(key, [...(map.get(key) ?? []), r]);
  }
  const out: Flow = { steps: [], ended: false, answers: {} };
  const seen = out.answers;
  const hidden = (key: string) => {
    const mine = reveal.get(key) ?? [];
    const shows = mine.filter((r) => r.do === "show");
    return (shows.length > 0 && !shows.some((r) => holds(r.when, seen))) || mine.some((r) => r.do === "hide" && holds(r.when, seen));
  };
  let i = 0;
  while (i < steps.length && !out.ended) {
    const step = steps[i++]!;
    if (hidden(step.key)) continue;
    const keys: string[] = [];
    for (const f of step.fields) {
      if (hidden(f.key)) continue;
      keys.push(f.key);
      if (ANSWERABLE.has(f.type) && present(f, answers[f.key])) seen[f.key] = answers[f.key];
    }
    out.steps.push({ key: step.key, fields: keys });
    for (const r of leave.get(step.key) ?? []) {
      if (holds(r.when, seen)) {
        out.ended = r.do === "end";
        if (r.do === "jump") i = index.get(r.target!)!;
        break;
      }
    }
  }
  return out;
}
