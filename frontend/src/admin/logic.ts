// The pure rules of the admin screens: role rules and the field matrix, the team tree, audit and delivery filters,
// event type families, and field settings checked the way backend/app/records/types.py checks them. No React, no
// Vite, so node tests it (tests/admin*.test.ts).

export type Scope = "all" | "team" | "own" | "own_and_unassigned" | "none";
export type FieldType =
  | "text"
  | "long_text"
  | "number"
  | "money"
  | "date"
  | "datetime"
  | "boolean"
  | "select"
  | "multi_select"
  | "email"
  | "phone"
  | "url"
  | "user"
  | "record"
  | "stage"
  | "formula"
  | "rollup";

// ---- roles ----

export const SCOPES: { value: Scope; label: string; help: string }[] = [
  { value: "all", label: "All records", help: "Every record of this kind." },
  { value: "team", label: "Their team's records", help: "Records they own or are assigned, and those owned by anyone in their teams or the teams below them." },
  { value: "own_and_unassigned", label: "Own and unassigned", help: "Records they own or are assigned, and records nobody owns." },
  { value: "own", label: "Only their own", help: "Records they own, or where a person field names them." },
  { value: "none", label: "None", help: "No records of this kind." },
];
export const scopeLabel = (s: Scope | string) => SCOPES.find((x) => x.value === s)?.label ?? s;

/** The record families of the capability catalog, in the order of the matrix, and the four actions. */
export const FAMILIES = [
  { key: "contacts", label: "Contacts" },
  { key: "companies", label: "Companies" },
  { key: "deals", label: "Deals" },
  { key: "records", label: "Custom objects" },
];
export const ACTIONS = [
  { key: "read", label: "See" },
  { key: "write", label: "Create and edit" },
  { key: "delete", label: "Delete" },
  { key: "export", label: "Export" },
] as const;
export const familyOf = (objectKey: string) => ({ contact: "contacts", company: "companies", deal: "deals" })[objectKey] ?? "records";

export type Rule = { object_key: string; scope: Scope; hidden_fields: string[]; readonly_fields: string[] };
export type Access = "edit" | "readonly" | "hidden";
export const ANY = "*";

/** The modules of the catalog in their first-seen order, each with its capabilities. */
export function groupCatalog<T extends { module: string }>(entries: T[]): { module: string; items: T[] }[] {
  const out: { module: string; items: T[] }[] = [];
  for (const e of entries) {
    const g = out.find((x) => x.module === e.module);
    if (g) g.items.push(e);
    else out.push({ module: e.module, items: [e] });
  }
  return out;
}

/** The rule that applies to an object: its own, else the `*` rule, else none (no records at all). */
export const ruleFor = (rules: Rule[], objectKey: string): Rule | undefined => rules.find((r) => r.object_key === objectKey) ?? rules.find((r) => r.object_key === ANY);

export const accessOf = (rule: Rule | undefined, field: string): Access =>
  rule?.hidden_fields.includes(field) ? "hidden" : rule?.readonly_fields.includes(field) ? "readonly" : "edit";

/** The rules with one field of one object set to `access`. The object gets its own rule, a copy of the `*` scope, if it had none. */
export function withAccess(rules: Rule[], objectKey: string, field: string, access: Access): Rule[] {
  const base = rules.find((r) => r.object_key === objectKey) ?? { object_key: objectKey, scope: ruleFor(rules, objectKey)?.scope ?? "none", hidden_fields: [], readonly_fields: [] };
  const next: Rule = {
    ...base,
    hidden_fields: base.hidden_fields.filter((k) => k !== field).concat(access === "hidden" ? [field] : []),
    readonly_fields: base.readonly_fields.filter((k) => k !== field).concat(access === "readonly" ? [field] : []),
  };
  return upsert(rules, next);
}

/** The rules with an object's scope set; `null` removes the object's own rule (it falls back to `*`). */
export function withScope(rules: Rule[], objectKey: string, scope: Scope | null): Rule[] {
  if (scope === null) return rules.filter((r) => r.object_key !== objectKey);
  const base = rules.find((r) => r.object_key === objectKey) ?? { object_key: objectKey, scope, hidden_fields: [], readonly_fields: [] };
  return upsert(rules, { ...base, scope });
}

const upsert = (rules: Rule[], rule: Rule) => (rules.some((r) => r.object_key === rule.object_key) ? rules.map((r) => (r.object_key === rule.object_key ? rule : r)) : [...rules, rule]);

/** A canonical form, so a draft compares equal to what the server answers. */
export const normalizeRules = (rules: Rule[]): Rule[] =>
  [...rules]
    .map((r) => ({ object_key: r.object_key, scope: r.scope, hidden_fields: [...new Set(r.hidden_fields)].sort(), readonly_fields: [...new Set(r.readonly_fields)].filter((k) => !r.hidden_fields.includes(k)).sort() }))
    .sort((a, b) => (a.object_key < b.object_key ? -1 : a.object_key > b.object_key ? 1 : 0));

export type RoleDraft = { name: string; description: string; capabilities: string[]; object_rules: Rule[] };
export const sameRole = (a: RoleDraft, b: RoleDraft) =>
  a.name.trim() === b.name.trim() && a.description.trim() === b.description.trim() && JSON.stringify([...new Set(a.capabilities)].sort()) === JSON.stringify([...new Set(b.capabilities)].sort()) && JSON.stringify(normalizeRules(a.object_rules)) === JSON.stringify(normalizeRules(b.object_rules));

/** What changed between the saved role and the draft, in words, for the save bar. */
export function roleChanges(saved: RoleDraft, draft: RoleDraft): string[] {
  const out: string[] = [];
  if (saved.name.trim() !== draft.name.trim() || saved.description.trim() !== draft.description.trim()) out.push("name and description");
  const was = new Set(saved.capabilities);
  const now = new Set(draft.capabilities);
  const added = [...now].filter((c) => !was.has(c)).length;
  const removed = [...was].filter((c) => !now.has(c)).length;
  if (added) out.push(`${added} capabilit${added === 1 ? "y" : "ies"} added`);
  if (removed) out.push(`${removed} capabilit${removed === 1 ? "y" : "ies"} removed`);
  if (JSON.stringify(normalizeRules(saved.object_rules)) !== JSON.stringify(normalizeRules(draft.object_rules))) out.push("record access");
  return out;
}

/** Capabilities a draft holds that it cannot use: an action on records without seeing them is still allowed by the
 * server, but `write` without `read` is almost always a mistake worth a note. */
export function capabilityWarnings(caps: string[]): string[] {
  const held = new Set(caps);
  const out: string[] = [];
  for (const f of FAMILIES) {
    const acts = ACTIONS.filter((a) => a.key !== "read" && held.has(`${f.key}.${a.key}`));
    if (acts.length && !held.has(`${f.key}.read`)) out.push(`${f.label}: ${acts.map((a) => a.label.toLowerCase()).join(", ")} without see. The role will not find any records to act on.`);
  }
  if (held.has("members.manage") && !held.has("members.read")) out.push("People: managing members without seeing them leaves the team screens empty.");
  return out;
}

// ---- teams ----

export type TeamLike = { id: string; name: string; parent_team_id: string | null };

/** Teams in tree order (each parent before its sub-teams, siblings by name), with their depth. A team whose parent is
 * missing is shown at the top level. */
export function teamTree<T extends TeamLike>(teams: T[]): { team: T; depth: number }[] {
  const ids = new Set(teams.map((t) => t.id));
  const kids = new Map<string | null, T[]>();
  for (const t of teams) {
    const p = t.parent_team_id && ids.has(t.parent_team_id) ? t.parent_team_id : null;
    kids.set(p, [...(kids.get(p) ?? []), t]);
  }
  const out: { team: T; depth: number }[] = [];
  const seen = new Set<string>();
  const walk = (parent: string | null, depth: number) => {
    for (const t of (kids.get(parent) ?? []).sort((a, b) => a.name.localeCompare(b.name))) {
      if (seen.has(t.id)) continue;
      seen.add(t.id);
      out.push({ team: t, depth });
      walk(t.id, depth + 1);
    }
  };
  walk(null, 0);
  for (const t of teams) if (!seen.has(t.id)) out.push({ team: t, depth: 0 }); // a cycle the server would refuse
  return out;
}

/** The team and every team below it: the parents it may not be moved under. */
export function subtree(teams: TeamLike[], id: string): Set<string> {
  const out = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const t of teams)
      if (t.parent_team_id && out.has(t.parent_team_id) && !out.has(t.id)) {
        out.add(t.id);
        grew = true;
      }
  }
  return out;
}

/** "Sales / East / Inside": the path of a team from the top. */
export function teamPath(teams: TeamLike[], id: string): string {
  const by = new Map(teams.map((t) => [t.id, t]));
  const names: string[] = [];
  const seen = new Set<string>();
  for (let t = by.get(id); t && !seen.has(t.id); t = t.parent_team_id ? by.get(t.parent_team_id) : undefined) {
    seen.add(t.id);
    names.unshift(t.name);
  }
  return names.join(" / ");
}

// ---- filters (audit log and delivery log) ----

export type AuditFilters = { actor?: string; subject?: string; type?: string; from?: string; to?: string };
export type DeliveryFilters = { status?: string; type?: string; from?: string; to?: string };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isUuid = (s: string) => UUID.test(s.trim());
/** An event type (`record.updated`) or a family of them (`record.*`), as the API takes it. */
export const TYPE_PATTERN = /^[a-z_]+\.([a-z_]+|\*)$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

/** The start or the end of a calendar day on the viewer's clock, as an ISO instant (`to` is inclusive). */
export function dayBound(day: string, edge: "start" | "end"): string | undefined {
  if (!DAY.test(day)) return undefined;
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  const at = edge === "start" ? new Date(y, m - 1, d, 0, 0, 0, 0) : new Date(y, m - 1, d, 23, 59, 59, 999);
  return Number.isNaN(at.getTime()) ? undefined : at.toISOString();
}

/** The filters a screen keeps in its address (days as YYYY-MM-DD), read back; anything malformed is dropped. */
export function readFilters(q: URLSearchParams, keys: readonly string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of keys) {
    const v = q.get(k)?.trim();
    if (!v) continue;
    if ((k === "actor" || k === "subject") && !isUuid(v)) continue;
    if (k === "type" && !TYPE_PATTERN.test(v)) continue;
    if ((k === "from" || k === "to") && !DAY.test(v)) continue;
    if (k === "status" && !["pending", "retrying", "succeeded", "failed"].includes(v)) continue;
    out[k] = v;
  }
  return out;
}

/** The days of the address as API bounds: `from` the start of its day, `to` the end of its day. */
export function withDayBounds<T extends { from?: string; to?: string }>(f: T): T {
  return { ...f, from: f.from ? dayBound(f.from, "start") : undefined, to: f.to ? dayBound(f.to, "end") : undefined };
}

export const rangeError = (from?: string, to?: string) => (from && to && from > to ? "The start date is after the end date." : undefined);

// ---- event types ----

/** Event types grouped by what they are about (`record.created` is in `record`), families and types sorted. */
export function families(types: string[]): { family: string; types: string[] }[] {
  const by = new Map<string, string[]>();
  for (const t of [...types].sort()) {
    const f = t.split(".")[0]!;
    by.set(f, [...(by.get(f) ?? []), t]);
  }
  return [...by.entries()].map(([family, list]) => ({ family, types: list }));
}

export const familyLabel = (f: string) => f.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** "Every event", or "3 events: record.created, tag.added and 1 more". */
export function subscriptionText(types: string[]): string {
  if (types.includes("*")) return "Every event";
  if (types.length <= 2) return types.join(" and ");
  return `${types.length} events: ${types.slice(0, 2).join(", ")} and ${types.length - 2} more`;
}

// ---- audit events, in words ----

type Ev = { type: string; subject: { type: string; id: string }; actor: { type: string; id: string | null }; data: Record<string, unknown> };

/** Who did it: a person's name, "a workflow", "the system". */
export function actorLabel(e: Pick<Ev, "actor">, names: Map<string, string>): string {
  if (e.actor.type === "user") return (e.actor.id && names.get(e.actor.id)) || "A former member";
  if (e.actor.type === "workflow") return "A workflow";
  return "The system";
}

const str = (v: unknown) => (typeof v === "string" && v ? v : undefined);

/** A short phrase about the event's subject ("Ada Lovelace (contact)", "role Sales rep", "tag VIP on a contact"). */
export function subjectLabel(e: Ev, names: Map<string, string> = new Map()): string {
  const d = e.data;
  const object = str(d.object);
  const kind = e.subject.type.replace(/_/g, " ");
  if (e.type === "tag.added" || e.type === "tag.removed") return `tag ${str(d.name) ?? ""} on a ${object ?? "record"}`.replace("  ", " ");
  if (e.subject.type === "record") {
    const name = str(d.display_name);
    return name ? `${name}${object ? ` (${object})` : ""}` : `a ${object ?? "record"}`;
  }
  if (e.subject.type === "user") return names.get(e.subject.id) ?? "a person";
  const name = str(d.name) ?? str(d.label) ?? str(d.key) ?? str(d.display_name);
  return name ? `${kind} ${name}` : `a ${kind}`;
}

export type Change = { field: string; old: unknown; new: unknown };
/** The `changes` of an event as rows (`{field: {old, new}}`), sorted by field. */
export function changesOf(data: Record<string, unknown>): Change[] {
  const c = data.changes;
  if (!c || typeof c !== "object" || Array.isArray(c)) return [];
  return Object.entries(c as Record<string, unknown>)
    .map(([field, v]) => (v && typeof v === "object" && !Array.isArray(v) && ("old" in v || "new" in v) ? { field, old: (v as Change).old, new: (v as Change).new } : { field, old: undefined, new: v }))
    .sort((a, b) => a.field.localeCompare(b.field));
}

/** A value from an event as one line of text. */
export function valueText(v: unknown): string {
  if (v === undefined || v === null || v === "") return "empty";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

/** `audit-2026-10-20.csv`, with the filters in the name when there are any. */
export function exportName(f: AuditFilters, today: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const day = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;
  const parts = [f.type?.replace("*", "all").replace(/[^a-z0-9_.-]/gi, ""), f.from && `from-${f.from}`, f.to && `to-${f.to}`].filter(Boolean);
  return `audit-${day}${parts.length ? `-${parts.join("-")}` : ""}.csv`;
}

// ---- objects and fields ----

export const TYPES: { value: FieldType; label: string; help: string; group: string }[] = [
  { value: "text", label: "Text", help: "One line of text, up to 1000 characters.", group: "Text" },
  { value: "long_text", label: "Long text", help: "Paragraphs, up to 20 000 characters.", group: "Text" },
  { value: "email", label: "Email", help: "An email address, stored in lower case.", group: "Text" },
  { value: "phone", label: "Phone", help: "A phone number, stored as +15551234567.", group: "Text" },
  { value: "url", label: "URL", help: "An http or https address.", group: "Text" },
  { value: "number", label: "Number", help: "A number, optionally whole and within a range.", group: "Numbers and dates" },
  { value: "money", label: "Money", help: "An amount in a currency, kept in minor units (cents).", group: "Numbers and dates" },
  { value: "date", label: "Date", help: "A calendar date.", group: "Numbers and dates" },
  { value: "datetime", label: "Date and time", help: "A moment in time, stored in UTC.", group: "Numbers and dates" },
  { value: "boolean", label: "Yes or no", help: "A checkbox.", group: "Choices" },
  { value: "select", label: "Select", help: "One choice from a list.", group: "Choices" },
  { value: "multi_select", label: "Multi-select", help: "Any number of choices from a list.", group: "Choices" },
  { value: "user", label: "Person", help: "A member of the workspace. Whoever it names counts as assigned to the record.", group: "Links" },
  { value: "record", label: "Record link", help: "A record of another object.", group: "Links" },
  { value: "stage", label: "Stage", help: "A stage of a pipeline.", group: "Links" },
  { value: "formula", label: "Formula", help: "Stored, but not computed yet: it cannot be filled in or filtered on.", group: "Computed" },
  { value: "rollup", label: "Rollup", help: "Stored, but not computed yet: it cannot be filled in or filtered on.", group: "Computed" },
];
export const typeLabel = (t: string) => TYPES.find((x) => x.value === t)?.label ?? t;

/** The rules beyond `required` each type takes (types.py `Kind.rules`). */
export const RULES: Partial<Record<FieldType, ("min_length" | "max_length" | "timezone" | "min" | "max" | "integer" | "max_items")[]>> = {
  text: ["min_length", "max_length", "timezone"],
  long_text: ["min_length", "max_length"],
  email: ["min_length", "max_length"],
  url: ["min_length", "max_length"],
  number: ["min", "max", "integer"],
  money: ["min", "max"],
  multi_select: ["max_items"],
};
const CAPS: Partial<Record<FieldType, number>> = { text: 1000, long_text: 20000, email: 254, url: 2000 };
export const NAME_TYPES: FieldType[] = ["text", "long_text", "email", "phone", "url"];
const RESERVED = new Set(["id", "display_name", "owner_id", "created_by", "created_at", "updated_at", "deleted_at", "tag", "tags", "values", "relevance"]);
export const COLORS = ["gray", "blue", "teal", "green", "amber", "orange", "red", "pink", "purple", "indigo"] as const;

export type ChoiceDraft = { id?: string; label: string; color?: string };
export type FieldDraft = {
  key: string;
  label: string;
  type: FieldType;
  required: boolean;
  /** rule values as typed; empty means no rule */
  min_length: string;
  max_length: string;
  min: string;
  max: string;
  integer: boolean;
  timezone: boolean;
  max_items: string;
  choices: ChoiceDraft[];
  currency: string;
  region: string;
  object: string;
  expression: string;
  association: string;
  rollupField: string;
  rollupFunction: string;
};

export const emptyField = (type: FieldType = "text"): FieldDraft => ({
  key: "",
  label: "",
  type,
  required: false,
  min_length: "",
  max_length: "",
  min: "",
  max: "",
  integer: false,
  timezone: false,
  max_items: "",
  choices: type === "select" || type === "multi_select" ? [{ label: "" }] : [],
  currency: "USD",
  region: "",
  object: "",
  expression: "",
  association: "",
  rollupField: "",
  rollupFunction: "count",
});

const num = (v: unknown) => (typeof v === "number" ? String(v) : "");

/** A saved field as a draft for the edit form. */
export function draftOf(f: { key: string; label: string; type: FieldType; options: Record<string, unknown>; rules: Record<string, unknown> }): FieldDraft {
  const o = f.options;
  const r = f.rules;
  return {
    ...emptyField(f.type),
    key: f.key,
    label: f.label,
    required: r.required === true,
    min_length: num(r.min_length),
    max_length: num(r.max_length),
    min: num(r.min),
    max: num(r.max),
    integer: r.integer === true,
    timezone: r.timezone === true,
    max_items: num(r.max_items),
    choices: Array.isArray(o.choices) ? (o.choices as ChoiceDraft[]).map((c) => ({ id: c.id, label: c.label, color: c.color })) : [],
    currency: typeof o.currency === "string" ? o.currency : "USD",
    region: typeof o.region === "string" ? o.region : "",
    object: typeof o.object === "string" ? o.object : "",
    expression: typeof o.expression === "string" ? o.expression : "",
    association: typeof o.association === "string" ? o.association : "",
    rollupField: typeof o.field === "string" ? o.field : "",
    rollupFunction: typeof o.function === "string" ? o.function : "count",
  };
}

/** A field key from its label: `Lead source` becomes `lead_source`. */
export function keyFrom(label: string, max = 63): string {
  let k = label
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (k && !/^[a-z]/.test(k)) k = `f_${k}`;
  return k.slice(0, max).replace(/_+$/, "");
}

const finite = (s: string) => s.trim() !== "" && Number.isFinite(Number(s));

/** What is wrong with a draft, by form field (the same checks as the server, so most mistakes never leave the page). */
export function fieldErrors(d: FieldDraft, opts: { creating: boolean; taken: string[] }): Record<string, string> {
  const e: Record<string, string> = {};
  if (!d.label.trim()) e.label = "Give the field a name.";
  else if (d.label.trim().length > 100) e.label = "At most 100 characters.";
  if (opts.creating) {
    if (!d.key) e.key = "Give the field a key.";
    else if (!/^[a-z][a-z0-9_]{0,62}$/.test(d.key)) e.key = "Lower case letters, digits and _, starting with a letter (at most 63).";
    else if (RESERVED.has(d.key)) e.key = `${d.key} is a built-in column of every record.`;
    else if (opts.taken.includes(d.key)) e.key = "Another field (maybe an archived one) has this key.";
  }
  const rules = RULES[d.type] ?? [];
  for (const k of ["min_length", "max_length", "min", "max", "max_items"] as const) {
    const v = d[k];
    if (!rules.includes(k) || v.trim() === "") continue;
    if (!finite(v)) e[k] = "Must be a number.";
    else if (["min_length", "max_length", "max_items"].includes(k) && (!Number.isInteger(Number(v)) || Number(v) < 0)) e[k] = "Must be a whole number, 0 or more.";
  }
  const cap = CAPS[d.type];
  if (cap && !e.max_length && d.max_length.trim() && Number(d.max_length) > cap) e.max_length = `${typeLabel(d.type)} fields hold at most ${cap} characters.`;
  if (!e.min_length && !e.max_length && d.min_length.trim() && d.max_length.trim() && Number(d.min_length) > Number(d.max_length)) e.max_length = "Must be at least the minimum length.";
  if (!e.min && !e.max && d.min.trim() && d.max.trim() && Number(d.min) > Number(d.max)) e.max = "Must be at least the minimum.";
  if (d.type === "money") {
    for (const k of ["min", "max"] as const) if (!e[k] && d[k].trim() && !Number.isInteger(Number(d[k]))) e[k] = "Amounts are whole minor units (cents).";
    if (!/^[A-Za-z]{3}$/.test(d.currency.trim())) e.currency = "A three letter ISO 4217 code, like USD or EUR.";
  }
  if (d.type === "phone" && d.region.trim() && !/^[A-Za-z]{2}$/.test(d.region.trim())) e.region = "A two letter country code, like US or GB.";
  if (d.type === "record" && !d.object) e.object = "Pick the object it links to.";
  if (d.type === "select" || d.type === "multi_select") {
    const labels = d.choices.map((c) => c.label.trim());
    if (labels.length === 0 || labels.every((l) => !l)) e.choices = "Add at least one choice.";
    else if (labels.some((l) => !l)) e.choices = "Every choice needs a label (or remove the empty one).";
    else if (labels.length > 200) e.choices = "At most 200 choices.";
    else if (new Set(labels.map((l) => l.toLowerCase())).size !== labels.length) e.choices = "Two choices have the same label.";
  }
  return e;
}

/** The `options` and `rules` the API takes for a draft. Choices keep their ids (records store them); new ones get one from the server. */
export function fieldBody(d: FieldDraft): { options: Record<string, unknown>; rules: Record<string, unknown> } {
  const options: Record<string, unknown> = {};
  const rules: Record<string, unknown> = {};
  if (d.required) rules.required = true;
  for (const k of RULES[d.type] ?? []) {
    if (k === "integer" || k === "timezone") {
      if (d[k]) rules[k] = true;
    } else if (d[k].trim() !== "") rules[k] = Number(d[k]);
  }
  if (d.type === "select" || d.type === "multi_select")
    options.choices = d.choices.filter((c) => c.label.trim()).map((c) => ({ ...(c.id ? { id: c.id } : {}), label: c.label.trim(), ...(c.color ? { color: c.color } : {}) }));
  if (d.type === "money") options.currency = d.currency.trim().toUpperCase();
  if (d.type === "phone" && d.region.trim()) options.region = d.region.trim().toUpperCase();
  if (d.type === "record") options.object = d.object;
  if (d.type === "formula" && d.expression.trim()) options.expression = d.expression.trim();
  if (d.type === "rollup") {
    if (d.association) options.association = d.association;
    if (d.rollupField) options.field = d.rollupField;
    if (d.rollupFunction) options.function = d.rollupFunction;
  }
  return { options, rules };
}

/** Where a server error about a field's settings belongs in the form (`options: currency 'XX' is not...` goes to currency). */
export function placeServerErrors(fields: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, msg] of Object.entries(fields)) {
    const text = msg.charAt(0).toUpperCase() + msg.slice(1);
    if (path === "options") out[/currency/.test(msg) ? "currency" : /region/.test(msg) ? "region" : /choice/.test(msg) ? "choices" : /object/.test(msg) ? "object" : "options"] = text;
    else if (path === "rules") out[(msg.match(/\b(min_length|max_length|min|max|max_items|integer|timezone)\b/)?.[1] ?? "rules")] = text;
    else out[path.split(".")[0]!] = text;
  }
  return out;
}

/** Moves the item at `from` to `to` (both clamped), for the up and down buttons. */
export function move<T>(list: T[], from: number, to: number): T[] {
  const n = list.length;
  if (from < 0 || from >= n) return list;
  const target = Math.max(0, Math.min(n - 1, to));
  if (target === from) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(target, 0, item!);
  return next;
}

/** An object key from its singular name: `Property` becomes `property`. */
export const objectKeyFrom = (singular: string) => keyFrom(singular, 40).replace(/^f_/, "o_");
/** A plural guess for the new object form, which the user can change. */
export function pluralOf(s: string): string {
  const t = s.trim();
  if (!t) return "";
  if (/[^aeiou]y$/i.test(t)) return `${t.slice(0, -1)}ies`;
  if (/(s|x|z|ch|sh)$/i.test(t)) return `${t}es`;
  return `${t}s`;
}

export const CARDINALITIES = [
  { value: "many_to_many", label: "Many to many" },
  { value: "one_to_many", label: "One to many" },
  { value: "one_to_one", label: "One to one" },
] as const;
