// Reads the catalog's JSON schemas (pydantic's output) into the controls the config panel draws. Pure, for node tests.
import type { JsonSchema } from "./api.ts";
import { UNITS } from "./graph.ts";

/** The kinds of control a setting gets. A key with a picker of its own (a channel, a person) is named by `widget`. */
export type Kind = "text" | "long_text" | "number" | "boolean" | "choice" | "offset" | "map" | "uuid" | "uuid_list" | "fields" | "json";
export type Prop = { key: string; label: string; kind: Kind; required: boolean; nullable: boolean; schema: JsonSchema; choices?: string[]; widget?: Widget; hint?: string; max?: number };
export type Widget = "channel" | "user" | "person" | "users" | "stage" | "tag";

/** Words for the settings whose schema title is only the key spelled out ("If Refused"). */
const LABELS: Record<string, string> = {
  channel_id: "Channel",
  user_id: "Person",
  round_robin: "Round robin over",
  stage_id: "Stage",
  lost_reason: "Lost reason",
  lost_note: "Lost note",
  if_refused: "If consent says no",
  assignee: "Assign to",
  due: "Due",
  url: "Address (https)",
  payload: "Data to send",
  values: "Fields to set",
  body: "Message",
};
const MORE_LABELS: Record<string, string> = {
  duration: "How long",
  until_field: "Date field",
  event: "Event",
  timeout: "Time limit",
  match: "Event details",
  filter: "Condition",
  paths: "Paths",
  otherwise: "Otherwise",
  title: "Title",
  subject: "Subject",
  notes: "Notes",
  priority: "Priority",
  tag: "Tag",
  object: "Records",
  data: "Event details",
  label: "Name",
  branches: "Branches",
  next: "Next step",
  type: "Type",
  action: "Action",
};
/** A setting's name in words, from its key or a path into a config ("config.channel_id", "values.email"). */
export function settingLabel(key: string): string {
  const k = key.replace(/^config\.?/, "").split(".")[0] ?? "";
  const text = LABELS[k] ?? MORE_LABELS[k] ?? (k.charAt(0).toUpperCase() + k.slice(1).replace(/_id$/, "").replace(/_/g, " "));
  return text;
}
/** A server message about a setting, as a sentence: "Channel is required", "Message: uses {{x}}, which...". */
export function errorText(path: string, message: string): string {
  const rest = path.replace(/^config\.?/, "");
  if (!rest) return message.charAt(0).toUpperCase() + message.slice(1);
  return `${settingLabel(rest)}${/^(is|are|must|needs?|has|have|leads|uses|cannot|can't)\b/.test(message) ? " " : ": "}${message}`;
}

const HINTS: Record<string, string> = {
  body: "Text may hold {{field_key}}, for example {{first_name}}.",
  title: "Text may hold {{field_key}}.",
  if_refused: "Quiet hours never refuse: the step waits for the next allowed time.",
  payload: "Sent as data. Values may hold {{field_key}}; nothing else about the record leaves.",
  due: "From the moment the step runs. Leave empty for no due date.",
  lost_reason: "A lost stage needs one.",
  url: "Only public https addresses. The request is signed with the workflow's secret.",
};
const WIDGETS: Record<string, Widget> = { channel_id: "channel", stage_id: "stage", tag: "tag", round_robin: "users", assignee: "person" };
const CHOICE_WORDS: Record<string, string> = { fail: "Fail the step", skip: "Skip and go on", none: "None", low: "Low", medium: "Medium", high: "High", continue: "Go on from the goal", end: "End the run" };
export const choiceLabel = (v: string) => CHOICE_WORDS[v] ?? v.charAt(0).toUpperCase() + v.slice(1).replace(/_/g, " ");

export function resolve(s: JsonSchema, root: JsonSchema): JsonSchema {
  if (s.$ref?.startsWith("#/$defs/")) return root.$defs?.[s.$ref.slice(8)] ?? s;
  return s;
}

/** The schema without its `| null`, and whether null was allowed. */
function unwrap(s: JsonSchema, root: JsonSchema): { schema: JsonSchema; nullable: boolean } {
  if (s.anyOf) {
    const rest = s.anyOf.filter((x) => x.type !== "null");
    const nullable = rest.length < s.anyOf.length;
    if (rest.length === 1) return { schema: { ...resolve(rest[0]!, root), default: s.default, title: s.title }, nullable };
    return { schema: s, nullable };
  }
  return { schema: resolve(s, root), nullable: false };
}

const isOffset = (s: JsonSchema) => s.type === "object" && !!s.propertyNames?.enum && UNITS.every((u) => s.propertyNames!.enum!.includes(u));

function kindOf(key: string, s: JsonSchema): Kind {
  if (key === "values" && s.patternProperties) return "fields";
  if (s.enum) return "choice";
  if (isOffset(s)) return "offset";
  if (s.type === "boolean") return "boolean";
  if (s.type === "integer" || s.type === "number") return "number";
  if (s.type === "array" && s.items?.format === "uuid") return "uuid_list";
  if (s.type === "object" && s.additionalProperties && typeof s.additionalProperties === "object") return "map";
  if (s.type === "object") return "json";
  if (s.format === "uuid") return "uuid";
  if (s.type === "string") return (s.maxLength ?? 0) > 500 || key === "body" || key === "notes" ? "long_text" : "text";
  return "text";
}

/** The settings of a config schema, in its order, each with the control it gets. */
export function props(root: JsonSchema | null | undefined): Prop[] {
  if (!root?.properties) return [];
  const required = new Set(root.required ?? []);
  return Object.entries(root.properties).map(([key, raw]) => {
    const { schema, nullable } = unwrap(raw, root);
    const kind = kindOf(key, schema);
    // "user_id" is a person (a user or "owner") where the schema does not insist on a uuid
    const widget = key === "user_id" ? (schema.format === "uuid" ? "user" : "person") : WIDGETS[key];
    return {
      key,
      label: LABELS[key] ?? schema.title ?? raw.title ?? key,
      kind,
      required: required.has(key),
      nullable,
      schema,
      choices: schema.enum?.map(String),
      widget,
      hint: HINTS[key],
      max: schema.maxLength,
    };
  });
}

/** A new config: every default the schema gives, nothing else (the panel asks for the rest). */
export function defaults(root: JsonSchema | null | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(root?.properties ?? {})) {
    if (raw.default !== undefined && raw.default !== null) out[key] = structuredClone(raw.default);
  }
  return out;
}
